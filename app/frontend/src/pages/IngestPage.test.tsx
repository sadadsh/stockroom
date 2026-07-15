import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { ApiError, api } from "../api/client";
import type { EnrichmentResult, PartDetail, StagingCandidate } from "../api/types";
import { ToastProvider } from "../lib/toast";
import { ThemeProvider } from "../lib/theme";
import { IngestPage } from "./IngestPage";

vi.mock("../api/client", async (im) => {
  const actual = await im<typeof import("../api/client")>();
  return {
    ...actual,
    api: {
      ...actual.api,
      enrichFromUrl: vi.fn(),
      enrichPart: vi.fn(),
      passivePreview: vi.fn(),
      passiveAdd: vi.fn(),
      facets: vi.fn(),
      stockPreviewSvg: vi.fn(),
      stockModelGlb: vi.fn(),
      ingestInspect: vi.fn(),
      openJobStream: vi.fn(),
      ingestCommit: vi.fn(),
      ingestEnrich: vi.fn(),
    },
  };
});
const mockApi = vi.mocked(api);

function sf(value: unknown) {
  return { value, source: "mouser", confidence: "high" };
}

const EMPTY_RESULT: EnrichmentResult = {
  category: "",
  mpn: null,
  manufacturer: null,
  description: null,
  datasheet_url: null,
  stock: null,
  package: null,
  price_breaks: [],
  specs: {},
  add_plan: null,
  schema_version: 1,
};

const PASSIVE_RECORD = {
  id: "",
  display_name: "118 Ohm 1% 0603 Resistor",
  category: "Resistors",
  description: "Resistor, 118 Ohm, 1%, 0603",
  mpn: "560112116151",
  manufacturer: "",
  passive: true,
  symbol: { lib: "Device", name: "R" },
  footprint: { lib: "Resistor_SMD", name: "R_0603_1608Metric" },
  model: null,
  datasheet: { source_url: "" },
  purchase: [{ vendor: "Mouser", url: "https://www.mouser.com/x", part_number: "" }],
  specs: {
    Resistance: "118 Ohms",
    Tolerance: "1%",
    Package: "0603",
    "3D Model": "Resistor_SMD.3dshapes/R_0603_1608Metric.wrl",
  },
} as unknown as PartDetail;

const ZIP_CANDIDATE: StagingCandidate = {
  vendor: "snapeda",
  symbol_lib_path: "/tmp/x.kicad_sym",
  symbol_name: "STM32F103",
  footprint_variants: ["/tmp/LQFP48.kicad_mod"],
  chosen_footprint_index: 0,
  model_path: "/tmp/LQFP48.step",
  datasheet_path: null,
  display_name: "",
  entry_name: "STM32",
  category: "",
  mpn: "",
  manufacturer: "",
  description: "",
  tags: [],
  purchase: [],
  gaps: [],
};

function streamOf(chunks: string[]): ReadableStream<Uint8Array> {
  const enc = new TextEncoder();
  return new ReadableStream<Uint8Array>({
    start(c) {
      for (const s of chunks) c.enqueue(enc.encode(s));
      c.close();
    },
  });
}

function resultStream(candidates: StagingCandidate[]): ReadableStream<Uint8Array> {
  return streamOf([
    `event: result\ndata: ${JSON.stringify({ result: candidates })}\n\n`,
    "event: done\ndata: {}\n\n",
  ]);
}

function wrap(ui: ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <ThemeProvider>
        <ToastProvider>{ui}</ToastProvider>
      </ThemeProvider>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  mockApi.facets.mockResolvedValue({ by_category: {}, by_manufacturer: {} } as never);
  mockApi.stockPreviewSvg.mockRejectedValue(new ApiError(404, "no kicad"));
  mockApi.stockModelGlb.mockRejectedValue(new ApiError(404, "no kicad"));
});

describe("IngestPage — unified Add A Part", () => {
  it("looks up a passive link and adds it with no files", async () => {
    mockApi.enrichFromUrl.mockResolvedValue({
      ...EMPTY_RESULT,
      mpn: sf("560112116151"),
      specs: { Resistance: sf("118 Ohms") },
      add_plan: { kind: "resistor", package: "0603", value: "118 Ohms", tolerance: "1%" },
    });
    mockApi.passivePreview.mockResolvedValue({
      status: "ok",
      record: PASSIVE_RECORD,
      gaps: [],
      stock_present: true,
    });
    mockApi.passiveAdd.mockResolvedValue(PASSIVE_RECORD);
    wrap(<IngestPage />);
    const user = userEvent.setup();

    await user.type(
      screen.getByLabelText("Product link or part number"),
      "https://www.mouser.com/x",
    );
    await user.click(screen.getByRole("button", { name: "Look Up" }));

    expect(mockApi.enrichFromUrl).toHaveBeenCalledWith("https://www.mouser.com/x");
    // determined a passive
    expect(await screen.findByText("Passive")).toBeInTheDocument();
    // the file-less add resolves the stock footprint + shows the add button
    const addBtn = await screen.findByRole("button", { name: "Add To Library" });
    await user.click(addBtn);

    expect(mockApi.passiveAdd).toHaveBeenCalledTimes(1);
    expect(mockApi.passiveAdd.mock.calls[0][0]).toMatchObject({
      input: "https://www.mouser.com/x",
      kind: "resistor",
      package: "0603",
    });
    expect(await screen.findByText(/Added 118 Ohm/i)).toBeInTheDocument();
  });

  it("routes a bare part number through the MPN lookup, not the URL fetch", async () => {
    mockApi.enrichPart.mockResolvedValue({ ...EMPTY_RESULT, add_plan: null });
    wrap(<IngestPage />);
    const user = userEvent.setup();
    await user.type(screen.getByLabelText("Product link or part number"), "ERJ-P03F1101V");
    await user.click(screen.getByRole("button", { name: "Look Up" }));
    expect(mockApi.enrichPart).toHaveBeenCalledWith("ERJ-P03F1101V");
    expect(mockApi.enrichFromUrl).not.toHaveBeenCalled();
  });

  it("a non-passive link asks for files and merges the pulled data onto the dropped ZIP", async () => {
    mockApi.enrichFromUrl.mockResolvedValue({
      ...EMPTY_RESULT,
      category: "ICs",
      mpn: sf("STM32F103C8T6"),
      description: sf("ARM Cortex-M3 MCU"),
      add_plan: null,
    });
    mockApi.ingestInspect.mockResolvedValue({ job_id: "j1" });
    mockApi.openJobStream.mockResolvedValue(resultStream([ZIP_CANDIDATE]));
    const pick = vi.fn().mockResolvedValue(["C:/dl/STM32.zip"]);
    (window as unknown as { pywebview?: unknown }).pywebview = {
      api: { pick_ingest_files: pick },
    };
    wrap(<IngestPage />);
    const user = userEvent.setup();

    await user.type(
      screen.getByLabelText("Product link or part number"),
      "https://www.mouser.com/stm32",
    );
    await user.click(screen.getByRole("button", { name: "Look Up" }));

    expect(await screen.findByText("Needs Files")).toBeInTheDocument();
    expect(screen.getByText("STM32F103C8T6")).toBeInTheDocument(); // pulled identity shown

    await user.click(screen.getByRole("button", { name: "Browse For ZIP" }));
    await waitFor(() => expect(pick).toHaveBeenCalled());

    // the staged candidate carries the ZIP's assets AND the pulled identity (link wins)
    await screen.findByText("Review And Add");
    expect(screen.getByLabelText("Part Number")).toHaveValue("STM32F103C8T6");
    delete (window as unknown as { pywebview?: unknown }).pywebview;
  });

  it("adds a part from a vendor ZIP dropped with no link", async () => {
    const cand = { ...ZIP_CANDIDATE, mpn: "NE555P", display_name: "NE555P", datasheet_path: "/tmp/x.pdf" };
    mockApi.ingestInspect.mockResolvedValue({ job_id: "j1" });
    mockApi.openJobStream.mockResolvedValue(resultStream([cand]));
    mockApi.ingestCommit.mockResolvedValue({ id: "ne555", display_name: "NE555P" } as PartDetail);
    const pick = vi.fn().mockResolvedValue(["C:/dl/NE555.zip"]);
    (window as unknown as { pywebview?: unknown }).pywebview = {
      api: { pick_ingest_files: pick },
    };
    wrap(<IngestPage />);
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: "Browse For ZIP" }));
    await waitFor(() => expect(mockApi.ingestInspect).toHaveBeenCalledWith(["C:/dl/NE555.zip"], []));
    await screen.findByLabelText("Name");

    await user.click(screen.getByRole("button", { name: "Add To Library" }));
    expect(mockApi.ingestCommit).toHaveBeenCalledTimes(1);
    expect(await screen.findByText(/Added NE555P/i)).toBeInTheDocument();
    delete (window as unknown as { pywebview?: unknown }).pywebview;
  });

  it("is honest when a link yields nothing addable", async () => {
    mockApi.enrichFromUrl.mockResolvedValue({ ...EMPTY_RESULT, add_plan: null });
    wrap(<IngestPage />);
    const user = userEvent.setup();
    await user.type(
      screen.getByLabelText("Product link or part number"),
      "https://www.mouser.com/blocked",
    );
    await user.click(screen.getByRole("button", { name: "Look Up" }));
    expect(await screen.findByText(/Nothing was pulled/i)).toBeInTheDocument();
  });
});
