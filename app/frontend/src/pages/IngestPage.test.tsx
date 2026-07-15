import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { ApiError, api } from "../api/client";
import type { BulkReport, PartDetail, StagingCandidate } from "../api/types";
import { ToastProvider } from "../lib/toast";
import { IngestPage } from "./IngestPage";

vi.mock("../api/client", async (im) => {
  const actual = await im<typeof import("../api/client")>();
  return {
    ...actual,
    api: {
      ...actual.api,
      ingestInspect: vi.fn(),
      openJobStream: vi.fn(),
      ingestCommit: vi.fn(),
      enrichBulk: vi.fn(),
    },
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

const CANDIDATE: StagingCandidate = {
  vendor: "lcsc",
  symbol_lib_path: "/tmp/SR-ICs.kicad_sym",
  symbol_name: "NE555P",
  footprint_variants: ["/tmp/DIP-8.kicad_mod", "/tmp/SOIC-8.kicad_mod"],
  chosen_footprint_index: 0,
  model_path: null,
  datasheet_path: "/tmp/ne555.pdf",
  display_name: "NE555P",
  entry_name: "NE555P",
  category: "ICs",
  mpn: "NE555P",
  manufacturer: "Texas Instruments",
  description: "Single timer",
  tags: ["timer"],
  purchase: [],
  gaps: ["no 3D model in this package"],
};

const PART_DETAIL = { id: "ne555", display_name: "NE555P" } as PartDetail;

function resultStream(candidates: StagingCandidate[]): ReadableStream<Uint8Array> {
  return streamOf([
    'event: progress\ndata: {"pct":50,"message":"fetching"}\n\n',
    `event: result\ndata: ${JSON.stringify({ result: candidates })}\n\n`,
    "event: done\ndata: {}\n\n",
  ]);
}

function wrap(ui: ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <ToastProvider>{ui}</ToastProvider>
    </QueryClientProvider>,
  );
}

async function inspectOnce(candidates: StagingCandidate[]) {
  mockApi.ingestInspect.mockResolvedValue({ job_id: "j1" });
  mockApi.openJobStream.mockResolvedValue(resultStream(candidates));
  wrap(<IngestPage />);
  const user = userEvent.setup();
  await user.type(screen.getByLabelText("LCSC Part IDs"), "C123");
  await user.click(screen.getByRole("button", { name: "Inspect" }));
  return user;
}

describe("IngestPage", () => {
  it("inspects an LCSC id and renders the returned staging candidate", async () => {
    const user = await inspectOnce([CANDIDATE]);
    expect(mockApi.ingestInspect).toHaveBeenCalledWith([], ["C123"]);
    // The candidate's proposed name lands in an editable field.
    expect(await screen.findByLabelText("Name")).toHaveValue("NE555P");
    // Its gap is surfaced honestly.
    expect(screen.getByText(/no 3D model/i)).toBeInTheDocument();
    void user;
  });

  it("browses for a vendor ZIP via the host picker and inspects the chosen paths", async () => {
    mockApi.ingestInspect.mockResolvedValue({ job_id: "j1" });
    mockApi.openJobStream.mockResolvedValue(resultStream([]));
    const pick = vi.fn().mockResolvedValue(["C:/dl/MyPart.zip"]);
    (window as unknown as { pywebview?: unknown }).pywebview = { api: { pick_ingest_files: pick } };
    wrap(<IngestPage />);
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Browse For ZIP" }));
    await waitFor(() => expect(pick).toHaveBeenCalled());
    expect(mockApi.ingestInspect).toHaveBeenCalledWith(["C:/dl/MyPart.zip"], []);
    delete (window as unknown as { pywebview?: unknown }).pywebview;
  });

  it("commits a candidate and reports success", async () => {
    const user = await inspectOnce([CANDIDATE]);
    await screen.findByLabelText("Name");
    mockApi.ingestCommit.mockResolvedValue(PART_DETAIL);

    await user.click(screen.getByRole("button", { name: "Add To Library" }));

    expect(mockApi.ingestCommit).toHaveBeenCalledTimes(1);
    expect(mockApi.ingestCommit).toHaveBeenCalledWith(CANDIDATE);
    expect(await screen.findByText(/Added NE555P/i)).toBeInTheDocument();
  });

  it("surfaces the complete-to-add gate missing fields on a 422", async () => {
    const user = await inspectOnce([CANDIDATE]);
    await screen.findByLabelText("Name");
    mockApi.ingestCommit.mockRejectedValue(
      new ApiError(422, "IncompleteError", ["3D model", "purchase link"]),
    );

    await user.click(screen.getByRole("button", { name: "Add To Library" }));

    const card = (await screen.findByText("3D model")).closest("[data-candidate]")!;
    expect(within(card as HTMLElement).getByText("3D model")).toBeInTheDocument();
    expect(within(card as HTMLElement).getByText("purchase link")).toBeInTheDocument();
  });

  it("commits the edited candidate values, not the originals", async () => {
    const user = await inspectOnce([CANDIDATE]);
    await screen.findByLabelText("Name");
    mockApi.ingestCommit.mockResolvedValue(PART_DETAIL);

    const manu = screen.getByLabelText("Manufacturer");
    await user.clear(manu);
    await user.type(manu, "Acme Corp");
    await user.click(screen.getByRole("button", { name: "Add To Library" }));

    expect(mockApi.ingestCommit).toHaveBeenCalledWith(
      expect.objectContaining({ manufacturer: "Acme Corp" }),
    );
  });

  it("keeps edits on sibling candidates when one is committed", async () => {
    const A = { ...CANDIDATE, display_name: "PART_A", entry_name: "A", mpn: "A" };
    const B = { ...CANDIDATE, display_name: "PART_B", entry_name: "B", mpn: "B" };
    mockApi.ingestInspect.mockResolvedValue({ job_id: "j1" });
    mockApi.openJobStream.mockResolvedValue(resultStream([A, B]));
    mockApi.ingestCommit.mockResolvedValue(PART_DETAIL);
    wrap(<IngestPage />);
    const user = userEvent.setup();
    await user.type(screen.getByLabelText("LCSC Part IDs"), "C1 C2");
    await user.click(screen.getByRole("button", { name: "Inspect" }));
    await screen.findByText("Review And Add");

    // Edit the second card's Manufacturer, then commit the first card.
    const manus = screen.getAllByLabelText("Manufacturer");
    expect(manus).toHaveLength(2);
    await user.clear(manus[1]);
    await user.type(manus[1], "EDITED_B");
    await user.click(screen.getAllByRole("button", { name: "Add To Library" })[0]);
    await screen.findByText(/Added PART_A/i);

    // The surviving card must still hold the edit, not be reset by a remount.
    const remaining = screen.getAllByLabelText("Manufacturer");
    expect(remaining).toHaveLength(1);
    expect(remaining[0]).toHaveValue("EDITED_B");
  });

  it("renders a candidate that arrives without a purchase field instead of crashing", async () => {
    const noPurchase: Partial<StagingCandidate> = { ...CANDIDATE };
    delete noPurchase.purchase;
    const user = await inspectOnce([noPurchase as StagingCandidate]);
    expect(await screen.findByLabelText("Name")).toHaveValue("NE555P");
    void user;
  });

  it("shows an honest empty state when inspection finds nothing", async () => {
    const user = await inspectOnce([]);
    expect(await screen.findByText(/No parts found/i)).toBeInTheDocument();
    void user;
  });
});

function bulkResultStream(report: BulkReport): ReadableStream<Uint8Array> {
  return streamOf([
    'event: progress\ndata: {"pct":50,"message":"enriching 2 parts"}\n\n',
    `event: result\ndata: ${JSON.stringify({ result: report })}\n\n`,
    "event: done\ndata: {}\n\n",
  ]);
}

describe("Bulk Lookup (spec 8.1)", () => {
  it("looks up pasted MPNs and shows a per-part completeness report", async () => {
    mockApi.enrichBulk.mockResolvedValue({ job_id: "b1" });
    mockApi.openJobStream.mockResolvedValue(
      bulkResultStream({
        items: [
          { mpn: "TPS62130RGTR", complete: true, missing: [], error: "" },
          { mpn: "WIDGET99", complete: false, missing: ["manufacturer", "symbol"], error: "" },
        ],
      }),
    );
    wrap(<IngestPage />);
    const user = userEvent.setup();
    await user.type(screen.getByTestId("bulk-input"), "TPS62130RGTR\nWIDGET99");
    await user.click(screen.getByTestId("bulk-run"));

    const report = await screen.findByTestId("bulk-report");
    expect(report).toHaveTextContent("1 of 2 complete");
    expect(screen.getByTestId("bulk-item-TPS62130RGTR")).toHaveTextContent("Complete");
    expect(screen.getByTestId("bulk-item-WIDGET99")).toHaveTextContent(
      /Missing manufacturer, symbol/,
    );
    expect(mockApi.enrichBulk).toHaveBeenCalledWith({
      text: "TPS62130RGTR\nWIDGET99",
      category: "Other",
    });
  });

  it("disables the lookup for an empty input", () => {
    wrap(<IngestPage />);
    expect(screen.getByTestId("bulk-run")).toBeDisabled();
    expect(mockApi.enrichBulk).not.toHaveBeenCalled();
  });
});
