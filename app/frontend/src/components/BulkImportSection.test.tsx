/**
 * PRIOR ART: this file deliberately reuses the established test shape from
 * `EnrichPanel.test.tsx` - the `vi.mock("../api/client")` partial mock, the `streamOf` SSE
 * builder, and the `wrap` QueryClientProvider helper - because bulk import is the same kind of
 * surface (submit a job, read its SSE stream). REJECTED: extracting those three helpers into a
 * shared test util, which would touch four existing test files for no behaviour change and is a
 * refactor nobody asked for; and MSW, which the repo does not use anywhere and would add a
 * dependency to intercept two functions a partial mock already covers.
 *
 * The REAL `bulkImportStore` runs here; only the two network seams are stubbed, so these exercise
 * the wiring rather than a mock of it.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { api } from "../api/client";
import type { BulkImportItem } from "../api/types";
import { BulkImportSection } from "./BulkImportSection";
import { resetBulkImport, setBulkImportText } from "../lib/bulkImportStore";

vi.mock("../api/client", async (importActual) => {
  const actual = await importActual<typeof import("../api/client")>();
  return {
    ...actual,
    api: { ...actual.api, bulkImport: vi.fn(), openJobStream: vi.fn() },
  };
});

const mockApi = vi.mocked(api);

function streamOf(chunks: string[]): ReadableStream<Uint8Array> {
  const enc = new TextEncoder();
  return new ReadableStream<Uint8Array>({
    start(c) {
      for (const s of chunks) c.enqueue(enc.encode(s));
      c.close();
    },
  });
}

function mockRun(counts: Record<string, number>, items: BulkImportItem[] = []) {
  mockApi.bulkImport.mockResolvedValue({ job_id: "b1" });
  mockApi.openJobStream.mockResolvedValue(
    streamOf([
      `event: progress\ndata: ${JSON.stringify({ stage: "importing", pct: 0.5, message: "importing 595-A (1 of 2)" })}\n\n`,
      `event: result\ndata: ${JSON.stringify({ result: { counts, items } })}\n\n`,
      "event: done\ndata: {}\n\n",
    ]),
  );
}

function item(over: Partial<BulkImportItem>): BulkImportItem {
  return {
    query: "", mpn: "", part_id: "", status: "added", display_name: "",
    category: "", missing: [], error: "", resolved_by: "", assets: "none", ...over,
  };
}

function wrap(ui: ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>);
}

function box() {
  return screen.getByPlaceholderText(/595-TPD6E05U06RVZR/);
}

beforeEach(() => {
  vi.clearAllMocks();
  // The store is a module singleton ON PURPOSE (it must outlive the dialog), so each test has to
  // clear it or the previous run's report leaks into the next assertion.
  resetBulkImport();
  setBulkImportText("");
});

describe("BulkImportSection", () => {
  it("counts what was pasted the same way the backend will", async () => {
    const user = userEvent.setup();
    wrap(<BulkImportSection />);
    // blanks dropped, comments dropped, duplicates collapsed - parse_mpn_list's exact rules, so
    // the button never promises a number the run will not honour
    await user.click(box());
    await user.paste("595-A\n603-B\n\n# a comment\n595-A\n");
    expect(screen.getByRole("button", { name: "Import 2 Parts" })).toBeTruthy();
  });

  it("keeps both actions disabled until something is pasted", () => {
    wrap(<BulkImportSection />);
    expect(screen.getByRole("button", { name: "Import" })).toHaveProperty("disabled", true);
    expect(screen.getByRole("button", { name: "Preview Without Writing" })).toHaveProperty(
      "disabled",
      true,
    );
  });

  it("sends a pasted BOM CSV as csv, not as a list of whole lines", async () => {
    const user = userEvent.setup();
    mockRun({ added: 1 });
    wrap(<BulkImportSection />);
    await user.click(box());
    await user.paste("Ref,MPN,Qty\nU1,595-A,3\n");
    await user.click(screen.getByRole("button", { name: "Import 1 Part" }));
    await waitFor(() => expect(mockApi.bulkImport).toHaveBeenCalled());
    expect(mockApi.bulkImport.mock.calls[0][0].format).toBe("csv");
  });

  it("the preview action asks for a dry run", async () => {
    const user = userEvent.setup();
    mockRun({ "would-add": 1 });
    wrap(<BulkImportSection />);
    await user.click(box());
    await user.paste("595-A");
    await user.click(screen.getByRole("button", { name: "Preview Without Writing" }));
    await waitFor(() => expect(mockApi.bulkImport).toHaveBeenCalled());
    expect(mockApi.bulkImport.mock.calls[0][0].dryRun).toBe(true);
  });

  it("shows only the rows that need attention, and can reveal the rest", async () => {
    const user = userEvent.setup();
    mockRun({ added: 1, incomplete: 1 }, [
      item({ query: "595-A", mpn: "A", part_id: "a", display_name: "Part A", resolved_by: "mouser" }),
      item({ query: "MYSTERY", mpn: "MYSTERY", status: "incomplete", missing: ["datasheet"] }),
    ]);
    wrap(<BulkImportSection />);
    await user.click(box());
    await user.paste("595-A\nMYSTERY");
    await user.click(screen.getByRole("button", { name: "Import 2 Parts" }));

    await waitFor(() => expect(screen.getByText("MYSTERY")).toBeTruthy());
    expect(screen.getByText("Missing datasheet")).toBeTruthy();
    // 160 "Added" rows would bury the one that needs a decision, so it is hidden until asked for
    expect(screen.queryByText("Part A")).toBeNull();
    await user.click(screen.getByRole("button", { name: "Show All 2 Rows" }));
    expect(screen.getByText("Part A")).toBeTruthy();
  });

  it("keeps the report and the paste when the dialog is closed and reopened", async () => {
    // THE reason the store exists. A 166-part register import runs ~25 minutes inside the
    // Add-A-Part dialog; with the state in useState, dismissing that dialog unmounted the reader
    // and threw the finished report away while the job kept running server-side.
    const user = userEvent.setup();
    mockRun({ added: 1 }, [item({ query: "595-A", mpn: "A", part_id: "a", display_name: "Part A" })]);
    const view = wrap(<BulkImportSection />);
    await user.click(box());
    await user.paste("595-A");
    await user.click(screen.getByRole("button", { name: "Import 1 Part" }));
    await waitFor(() => expect(screen.getByText("Added")).toBeTruthy());

    view.unmount(); // the dialog is dismissed
    wrap(<BulkImportSection />); // and reopened

    expect(screen.getByText("Added")).toBeTruthy();
    expect((box() as HTMLTextAreaElement).value).toBe("595-A");
    await user.click(screen.getByRole("button", { name: "Show All 1 Rows" }));
    expect(screen.getByText("Part A")).toBeTruthy();
  });

  it("says whether the FILES landed, not just that the part did", async () => {
    // The owner's actual question. "Added" alone cannot answer it: a part can land complete on
    // its identity and still carry no symbol, footprint or 3D model.
    const user = userEvent.setup();
    mockRun({ added: 2 }, [
      item({ query: "81-GRM155R71C104KA88D", mpn: "GRM155R71C104KA88D", display_name: "100 nF 0402", assets: "kicad-stock" }),
      item({ query: "595-TPD6E05U06RVZR", mpn: "TPD6E05U06RVZR", display_name: "ESD array", assets: "none" }),
    ]);
    wrap(<BulkImportSection />);
    await user.click(box());
    await user.paste("81-GRM155R71C104KA88D\n595-TPD6E05U06RVZR");
    await user.click(screen.getByRole("button", { name: "Import 2 Parts" }));
    await waitFor(() => expect(screen.getByRole("button", { name: /Show All/ })).toBeTruthy());
    await user.click(screen.getByRole("button", { name: "Show All 2 Rows" }));
    expect(screen.getByText("Symbol, Footprint, 3D")).toBeTruthy();
    expect(screen.getByText("Needs Capture")).toBeTruthy();
  });

  it("shows what a stock number resolved to, never silently substituting it", async () => {
    const user = userEvent.setup();
    mockRun({ error: 1 }, [
      item({
        query: "595-TPS62130RGTR", mpn: "TPS62130RGTR", status: "error",
        error: "disk on fire", resolved_by: "mouser",
      }),
    ]);
    wrap(<BulkImportSection />);
    await user.click(box());
    await user.paste("595-TPS62130RGTR");
    await user.click(screen.getByRole("button", { name: "Import 1 Part" }));
    await waitFor(() => expect(screen.getByText("disk on fire")).toBeTruthy());
    // Scoped to the report. The pasted number also sits in the textarea, so an unscoped
    // getByText would match that and pass even if the report rendered nothing.
    const report = within(
      document.querySelector('[data-dev-id="ingest.bulk-result"]') as HTMLElement,
    );
    expect(report.getByText("595-TPS62130RGTR")).toBeTruthy();
    expect(report.getByText("TPS62130RGTR")).toBeTruthy();
  });
});
