import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { ApiError, api } from "../api/client";
import type { EnrichmentResult, PartDetail, StagingCandidate } from "../api/types";
import { queuePaths } from "../lib/ingestQueue";
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

// Mirrors resultStream but wraps an EnrichmentResult: the enrichPart/enrichFromUrl
// lookup is a background job now (-> {job_id}), and the sourced result arrives on the
// job's SSE stream (openJobStream) rather than as the submit call's direct return.
function enrichStream(r: EnrichmentResult): ReadableStream<Uint8Array> {
  return streamOf([
    `event: result\ndata: ${JSON.stringify({ result: r })}\n\n`,
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
    mockApi.enrichFromUrl.mockResolvedValue({ job_id: "e1" });
    mockApi.openJobStream.mockResolvedValue(
      enrichStream({
        ...EMPTY_RESULT,
        mpn: sf("560112116151"),
        specs: { Resistance: sf("118 Ohms") },
        add_plan: { kind: "resistor", package: "0603", value: "118 Ohms", tolerance: "1%" },
      }),
    );
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
    const addBtn = await screen.findByRole("button", { name: "Add to Components" });
    await user.click(addBtn);

    expect(mockApi.passiveAdd).toHaveBeenCalledTimes(1);
    expect(mockApi.passiveAdd.mock.calls[0][0]).toMatchObject({
      input: "https://www.mouser.com/x",
      kind: "resistor",
      package: "0603",
    });
    expect(await screen.findByText(/Added 118 Ohm/i)).toBeInTheDocument();
  });

  it("shows an honest progress indicator while a distributor page is being pulled", async () => {
    // The submit resolves (a job is started), but the job's SSE stream deliberately
    // never closes past its first progress frame, so the pipeline's live rendering
    // stage stays in flight and the progress state (EnrichStages) is observable.
    mockApi.enrichFromUrl.mockResolvedValue({ job_id: "e1" });
    mockApi.openJobStream.mockResolvedValue(
      new ReadableStream<Uint8Array>({
        start(c) {
          c.enqueue(
            new TextEncoder().encode(
              `event: progress\ndata: ${JSON.stringify({ stage: "rendering", pct: 45, message: "settling" })}\n\n`,
            ),
          );
          // no close(): holds the stream (and the progress state) open indefinitely
        },
      }),
    );
    wrap(<IngestPage />);
    const user = userEvent.setup();
    await user.type(
      screen.getByLabelText("Product link or part number"),
      "https://www.mouser.com/ProductDetail/Panasonic/ERJ-P03F1101V",
    );
    await user.click(screen.getByRole("button", { name: "Look Up" }));
    expect(await screen.findByRole("progressbar")).toBeInTheDocument();
    // The old LookupProgress ("Fetching from Mouser") was replaced by EnrichStages,
    // which names the real pipeline phase and streams its live message.
    expect(await screen.findByText(/Rendering/)).toBeInTheDocument();
    expect(screen.getByText(/settling/)).toBeInTheDocument();
  });

  it("routes a bare part number through the MPN lookup, not the URL fetch", async () => {
    mockApi.enrichPart.mockResolvedValue({ job_id: "e1" });
    mockApi.openJobStream.mockResolvedValue(enrichStream({ ...EMPTY_RESULT, add_plan: null }));
    wrap(<IngestPage />);
    const user = userEvent.setup();
    await user.type(screen.getByLabelText("Product link or part number"), "ERJ-P03F1101V");
    await user.click(screen.getByRole("button", { name: "Look Up" }));
    // useEnrichLookup.runPart calls api.enrichPart(mpn, category, want); with only an
    // MPN here, category and want are both undefined.
    expect(mockApi.enrichPart).toHaveBeenCalledWith("ERJ-P03F1101V", undefined, undefined);
    expect(mockApi.enrichFromUrl).not.toHaveBeenCalled();
  });

  it("a non-passive link asks for files and merges the pulled data onto the dropped ZIP", async () => {
    // Both the URL lookup and the ZIP inspect stream over openJobStream, each under its
    // own job id, so the mock must key its response by which job is being opened.
    mockApi.enrichFromUrl.mockResolvedValue({ job_id: "enrich1" });
    mockApi.ingestInspect.mockResolvedValue({ job_id: "zip1" });
    mockApi.openJobStream.mockImplementation((jobId: string) =>
      Promise.resolve(
        jobId === "enrich1"
          ? enrichStream({
              ...EMPTY_RESULT,
              category: "ICs",
              mpn: sf("STM32F103C8T6"),
              description: sf("ARM Cortex-M3 MCU"),
              add_plan: null,
            })
          : resultStream([ZIP_CANDIDATE]),
      ),
    );
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

    await user.click(screen.getByRole("button", { name: "Browse for ZIP" }));
    await waitFor(() => expect(pick).toHaveBeenCalled());

    // the staged candidate carries the ZIP's assets AND the pulled identity (link wins)
    await screen.findByText("Review and Add");
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

    await user.click(screen.getByRole("button", { name: "Browse for ZIP" }));
    await waitFor(() => expect(mockApi.ingestInspect).toHaveBeenCalledWith(["C:/dl/NE555.zip"], []));
    await screen.findByLabelText("Name");

    await user.click(screen.getByRole("button", { name: "Add to Components" }));
    expect(mockApi.ingestCommit).toHaveBeenCalledTimes(1);
    expect(await screen.findByText(/Added NE555P/i)).toBeInTheDocument();
    delete (window as unknown as { pywebview?: unknown }).pywebview;
  });

  it("merges the pulled data when a ZIP is dropped mid-lookup (native drag race)", async () => {
    // The guided flow (look up, THEN drop when prompted) avoids it, but a native drag can drop
    // a vendor ZIP WHILE the link lookup is still streaming. The ZIP inspect settles first; its
    // staged candidate must still receive the pulled identity/specs/datasheet once the lookup
    // lands, never a silently un-merged part. The held enrich stream guarantees the ordering.
    const enc = new TextEncoder();
    let enrichController: ReadableStreamDefaultController<Uint8Array> | null = null;
    const heldEnrich = new ReadableStream<Uint8Array>({
      start(c) {
        c.enqueue(enc.encode(`event: progress\ndata: ${JSON.stringify({ stage: "fetching", pct: 10 })}\n\n`));
        enrichController = c; // held open: enrich.status stays "running" until the test pushes
      },
    });
    mockApi.enrichFromUrl.mockResolvedValue({ job_id: "enrich1" });
    mockApi.ingestInspect.mockResolvedValue({ job_id: "zip1" });
    mockApi.openJobStream.mockImplementation((jobId: string) =>
      Promise.resolve(jobId === "enrich1" ? heldEnrich : resultStream([ZIP_CANDIDATE])),
    );
    wrap(<IngestPage />);
    const user = userEvent.setup();

    await user.type(
      screen.getByLabelText("Product link or part number"),
      "https://www.mouser.com/stm32",
    );
    await user.click(screen.getByRole("button", { name: "Look Up" }));
    // the lookup is in flight (its stream is held open)
    await screen.findByRole("button", { name: "Looking Up..." });

    // a native drag drops the ZIP mid-lookup; its inspect settles while enrich is still running
    await act(async () => {
      queuePaths(["C:/dl/STM32.zip"]);
      await new Promise((r) => setTimeout(r, 20));
    });
    await waitFor(() => expect(mockApi.openJobStream).toHaveBeenCalledWith("zip1"));

    // now the lookup lands: push its sourced result and close the held stream
    await act(async () => {
      enrichController!.enqueue(
        enc.encode(
          `event: result\ndata: ${JSON.stringify({
            result: {
              ...EMPTY_RESULT,
              category: "ICs",
              mpn: sf("STM32F103C8T6"),
              description: sf("ARM Cortex-M3 MCU"),
              datasheet_url: sf("https://ds/stm32.pdf"),
              add_plan: null,
            },
          })}\n\n`,
        ),
      );
      enrichController!.enqueue(enc.encode("event: done\ndata: {}\n\n"));
      enrichController!.close();
    });

    // the staged candidate carries the ZIP's assets AND the pulled identity (the merge survived)
    await screen.findByText("Review and Add");
    expect(screen.getByLabelText("Part Number")).toHaveValue("STM32F103C8T6");
  });

  it("does not merge a just-added part's identity onto a later standalone ZIP", async () => {
    // The staging merge reads enrich.result, so reset() (run after a passive add) must clear the
    // lookup too. Otherwise the previous part's identity/specs stay live and get merged onto an
    // unrelated vendor ZIP browsed afterward - a silent cross-contamination.
    mockApi.enrichFromUrl.mockResolvedValue({ job_id: "e1" });
    mockApi.ingestInspect.mockResolvedValue({ job_id: "zip1" });
    mockApi.openJobStream.mockImplementation((jobId: string) =>
      Promise.resolve(
        jobId === "e1"
          ? enrichStream({
              ...EMPTY_RESULT,
              mpn: sf("560112116151"),
              specs: { Resistance: sf("118 Ohms") },
              add_plan: { kind: "resistor", package: "0603", value: "118 Ohms", tolerance: "1%" },
            })
          : resultStream([ZIP_CANDIDATE]),
      ),
    );
    mockApi.passivePreview.mockResolvedValue({
      status: "ok",
      record: PASSIVE_RECORD,
      gaps: [],
      stock_present: true,
    });
    mockApi.passiveAdd.mockResolvedValue(PASSIVE_RECORD);
    const pick = vi.fn().mockResolvedValue(["C:/dl/STM32.zip"]);
    (window as unknown as { pywebview?: unknown }).pywebview = {
      api: { pick_ingest_files: pick },
    };
    wrap(<IngestPage />);
    const user = userEvent.setup();

    // look up + add the passive resistor
    await user.type(
      screen.getByLabelText("Product link or part number"),
      "https://www.mouser.com/x",
    );
    await user.click(screen.getByRole("button", { name: "Look Up" }));
    await user.click(await screen.findByRole("button", { name: "Add to Components" }));
    await screen.findByText(/Added 118 Ohm/i); // reset() has run

    // now browse an UNRELATED vendor ZIP (no lookup active): it must stage standalone
    await user.click(screen.getByRole("button", { name: "Browse for ZIP" }));
    await screen.findByText("Review and Add");
    expect(screen.getByLabelText("Part Number")).toHaveValue(""); // not the resistor's MPN
    delete (window as unknown as { pywebview?: unknown }).pywebview;
  });

  it("tears down the part context after a non-passive commit so a later ZIP is not contaminated", async () => {
    // Committing a looked-up non-passive part (removeStaged) must reset the whole part context,
    // like a passive add does. Otherwise the just-added part's lookup stays live and its identity
    // merges onto an unrelated ZIP browsed afterward, and the completed ZIP job can resurrect
    // un-merged. Both are the "one part-context teardown after any add" property.
    mockApi.enrichFromUrl.mockResolvedValue({ job_id: "e1" });
    mockApi.ingestInspect
      .mockResolvedValueOnce({ job_id: "zipX" })
      .mockResolvedValueOnce({ job_id: "zipU" });
    mockApi.openJobStream.mockImplementation((jobId: string) => {
      if (jobId === "e1")
        return Promise.resolve(
          enrichStream({
            ...EMPTY_RESULT,
            category: "ICs",
            mpn: sf("STM32F103C8T6"),
            description: sf("ARM Cortex-M3 MCU"),
            add_plan: null,
          }),
        );
      if (jobId === "zipX") return Promise.resolve(resultStream([ZIP_CANDIDATE]));
      return Promise.resolve(resultStream([{ ...ZIP_CANDIDATE, entry_name: "UNREL555" }]));
    });
    mockApi.ingestCommit.mockResolvedValue({ id: "stm32", display_name: "STM32F103" } as PartDetail);
    const pick = vi
      .fn()
      .mockResolvedValueOnce(["C:/dl/STM32.zip"])
      .mockResolvedValueOnce(["C:/dl/UNREL.zip"]);
    (window as unknown as { pywebview?: unknown }).pywebview = {
      api: { pick_ingest_files: pick },
    };
    wrap(<IngestPage />);
    const user = userEvent.setup();

    // look up non-passive X, drop its ZIP (merged), and commit it
    await user.type(
      screen.getByLabelText("Product link or part number"),
      "https://www.mouser.com/stm32",
    );
    await user.click(screen.getByRole("button", { name: "Look Up" }));
    await screen.findByText("Needs Files");
    await user.click(screen.getByRole("button", { name: "Browse for ZIP" }));
    await screen.findByText("Review and Add");
    expect(screen.getByLabelText("Part Number")).toHaveValue("STM32F103C8T6"); // merged X
    await user.click(screen.getByRole("button", { name: "Add to Components" }));
    await screen.findByText(/Added STM32F103/i);

    // the whole part context tore down: no leftover "Needs Files" card, no resurrected staged card
    expect(screen.queryByText("Needs Files")).not.toBeInTheDocument();
    expect(screen.queryByText("Review and Add")).not.toBeInTheDocument();

    // browse an UNRELATED ZIP: it must NOT inherit the committed part's MPN
    await user.click(screen.getByRole("button", { name: "Browse for ZIP" }));
    await screen.findByText("Review and Add");
    expect(screen.getByLabelText("Part Number")).toHaveValue("");
    delete (window as unknown as { pywebview?: unknown }).pywebview;
  });

  it("commits two staged candidates concurrently without leaving a phantom card", async () => {
    // Multi-select Browse stages 2+ candidates, each with its own independent Add button and async
    // git commit. Committing both before the first resolves must not leave a phantom card for an
    // already-added part or skip the teardown (which would re-open contamination and allow a re-add).
    // The emptiness decision must read the LATEST staged, not a stale render-closure.
    const A = { ...ZIP_CANDIDATE, entry_name: "AAA", mpn: "AAA111", display_name: "AAA111" };
    const B = { ...ZIP_CANDIDATE, entry_name: "BBB", mpn: "BBB222", display_name: "BBB222" };
    mockApi.ingestInspect.mockResolvedValue({ job_id: "zip1" });
    mockApi.openJobStream.mockResolvedValue(resultStream([A, B]));
    let resolveA: (v: PartDetail) => void = () => {};
    let resolveB: (v: PartDetail) => void = () => {};
    mockApi.ingestCommit
      .mockImplementationOnce(() => new Promise((r) => (resolveA = r)))
      .mockImplementationOnce(() => new Promise((r) => (resolveB = r)));
    const pick = vi.fn().mockResolvedValue(["C:/dl/two.zip"]);
    (window as unknown as { pywebview?: unknown }).pywebview = {
      api: { pick_ingest_files: pick },
    };
    wrap(<IngestPage />);
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: "Browse for ZIP" }));
    await screen.findByText("Review and Add");
    const addButtons = screen.getAllByRole("button", { name: "Add to Components" });
    expect(addButtons).toHaveLength(2);

    // commit BOTH before either resolves: both onSuccess closures capture staged = [A, B]
    await user.click(addButtons[0]);
    await user.click(addButtons[1]);
    await act(async () => {
      resolveA({ id: "a", display_name: "AAA111" } as PartDetail);
    });
    await act(async () => {
      resolveB({ id: "b", display_name: "BBB222" } as PartDetail);
    });

    await waitFor(() => expect(mockApi.ingestCommit).toHaveBeenCalledTimes(2));
    // both parts added -> the staging area is fully torn down, no phantom card lingers
    await waitFor(() =>
      expect(screen.queryByText("Review and Add")).not.toBeInTheDocument(),
    );
    delete (window as unknown as { pywebview?: unknown }).pywebview;
  });

  it("is honest when a link yields nothing addable", async () => {
    mockApi.enrichFromUrl.mockResolvedValue({ job_id: "e1" });
    mockApi.openJobStream.mockResolvedValue(enrichStream({ ...EMPTY_RESULT, add_plan: null }));
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
