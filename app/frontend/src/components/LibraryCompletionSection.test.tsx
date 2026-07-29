/**
 * The completion surface, tested for the things that make a report TRUSTWORTHY rather than
 * merely present. Most of these assert a distinction the UI must not collapse, because every
 * one of them, collapsed, turns into the surface quietly lying about the library.
 */
import { describe, expect, it, vi, beforeEach } from "vitest";
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { LibraryCompletionSection } from "./LibraryCompletionSection";
import { ToastProvider } from "../lib/toast";
import { api } from "../api/client";
import { resetCompletion } from "../lib/completionStore";
import type {
  LibraryCoverage,
  WorkflowBatchSummary,
  WorkflowEvent,
  WorkflowEventsPage,
} from "../api/types";

function coverage(over: Partial<LibraryCoverage> = {}): LibraryCoverage {
  return {
    total: 158,
    complete: 92,
    needs_files: 47,
    unsourced: 19,
    by_requirement: {
      kicad_symbol: 66,
      kicad_footprint: 66,
      kicad_model: 68,
      altium_symbol: 155,
      altium_footprint: 155,
    },
    sources: ["lcsc"],
    can_provide: ["kicad_footprint", "kicad_model", "kicad_symbol"],
    ...over,
  };
}

function durableBatch(
  status: WorkflowBatchSummary["status"],
  itemCounts: Record<string, number> = {},
  totalItems = 1,
): WorkflowBatchSummary {
  return {
    id: "batch-1",
    status,
    created_at: 1,
    updated_at: 2,
    total_items: totalItems,
    item_counts: itemCounts,
    cancellation:
      status === "cancelled"
        ? {
            state: "completed",
            requested_at: 2,
            completed_at: 2,
          }
        : null,
    actions: {
      can_pause: ["queued", "running", "blocked"].includes(status),
      can_resume: status === "paused",
      can_retry: status === "failed",
      can_cancel: ["queued", "running", "blocked", "paused", "failed"].includes(status),
    },
  };
}

function durablePage(
  batch: WorkflowBatchSummary,
  events: WorkflowEvent[],
  nextSequence: number,
  hasMore = false,
): WorkflowEventsPage {
  return {
    schema_version: 1,
    batch,
    events,
    cursor: {
      after_sequence: 0,
      next_sequence: nextSequence,
      limit: 200,
      has_more: hasMore,
    },
  };
}

function renderSection() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <ToastProvider>
        <LibraryCompletionSection />
      </ToastProvider>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  resetCompletion();
  vi.restoreAllMocks();
});

describe("coverage", () => {
  it("says how many components hold every file they need", async () => {
    vi.spyOn(api, "libraryCoverage").mockResolvedValue(coverage());
    renderSection();
    expect(await screen.findByText(/components have every file they need/i)).toBeInTheDocument();
    // 92 appears in the headline AND in the KiCad symbol cell, which is correct: the sentence
    // and the matrix are two readings of the same fact.
    expect(screen.getAllByText("92").length).toBeGreaterThan(0);
  });

  it("shows both EDA tools as rows, so a missing tool cannot be averaged away", async () => {
    // The whole reason this is a matrix and not a percentage: 3 of 158 parts have Altium files,
    // and one number over 158 parts would report that as a healthy-looking library.
    vi.spyOn(api, "libraryCoverage").mockResolvedValue(coverage());
    renderSection();
    expect(await screen.findByRole("rowheader", { name: "KiCad" })).toBeInTheDocument();
    expect(screen.getByRole("rowheader", { name: "Altium" })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "3D Model" })).toBeInTheDocument();
  });

  it("counts each cell as have-of-total, not as an anonymous missing number", async () => {
    vi.spyOn(api, "libraryCoverage").mockResolvedValue(coverage());
    renderSection();
    // kicad_symbol: 66 of 158 missing -> 92 have.
    await screen.findByRole("rowheader", { name: "KiCad" });
    expect(screen.getAllByText("of 158").length).toBeGreaterThan(0);
  });

  it("marks a requirement no source can supply, instead of showing it as pending work", async () => {
    // Altium gaps are real and reported, but a run cannot touch them. Presenting them as work
    // the button will do is a promise the app cannot keep.
    vi.spyOn(api, "libraryCoverage").mockResolvedValue(coverage());
    renderSection();
    expect((await screen.findAllByText("No Source")).length).toBe(2);
  });

  it("states the number the action will actually work on, and how long it takes", async () => {
    // 47 parts at ~8/minute is 6 minutes. A run whose cost is discovered rather than stated is
    // one nobody can consent to.
    vi.spyOn(api, "libraryCoverage").mockResolvedValue(coverage());
    renderSection();
    // "can be filled" would be a promise the run cannot keep: 19 of those have no catalogue
    // entry and will find nothing. The copy says what is TRIED, not what is guaranteed.
    expect(
      await screen.findByText(/47 components have gaps a source ladder can try/i),
    ).toBeInTheDocument();
    expect(screen.getByText(/retains fallbacks/i)).toBeInTheDocument();
    expect(screen.getByText(/about 7 minutes/i)).toBeInTheDocument();
  });

  it("estimates a 10,000 part library in hours, not in 1250 minutes", async () => {
    vi.spyOn(api, "libraryCoverage").mockResolvedValue(
      coverage({ total: 10000, complete: 0, needs_files: 10000, unsourced: 0 }),
    );
    renderSection();
    expect(await screen.findByText(/about 23.8 hours/i)).toBeInTheDocument();
  });

  it("separately names the components neither acquisition lane can reach", async () => {
    vi.spyOn(api, "libraryCoverage").mockResolvedValue(coverage());
    renderSection();
    expect(
      await screen.findByText(/neither an automatic source nor a managed provider/i),
    ).toBeInTheDocument();
  });

  it("explains the one assisted session and its genuine human checkpoints", async () => {
    vi.spyOn(api, "libraryCoverage").mockResolvedValue(
      coverage({
        needs_assistance: 31,
        assisted_can_provide: ["altium_symbol", "altium_footprint"],
      }),
    );
    renderSection();

    expect(
      await screen.findByText(
        (_text, node) =>
          node?.tagName === "P" &&
          !!node.textContent?.match(
            /31 components have gaps that need one explicit collect all sources session/i,
          ),
      ),
    ).toBeInTheDocument();
    expect(screen.getByText(/reuses the provider session/i)).toBeInTheDocument();
    expect(
      screen.getByText(/provider-required login, security check, or download choice/i),
    ).toBeInTheDocument();
    expect(screen.getAllByText("Provider")).toHaveLength(2);
    expect(screen.queryByText("No Source")).not.toBeInTheDocument();
  });

  it("disables the action when there is genuinely nothing to do", async () => {
    vi.spyOn(api, "libraryCoverage").mockResolvedValue(
      coverage({ complete: 158, needs_files: 0, unsourced: 0, by_requirement: {} }),
    );
    renderSection();
    expect(
      await screen.findByText(/All 158 components have every file they need/i),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Fill Supported CAD Gaps" })).toBeDisabled();
  });

  it("says so plainly when the library is empty", async () => {
    vi.spyOn(api, "libraryCoverage").mockResolvedValue(
      coverage({ total: 0, complete: 0, needs_files: 0, unsourced: 0, by_requirement: {} }),
    );
    renderSection();
    expect(await screen.findByText(/no components yet/i)).toBeInTheDocument();
  });

  it("reports a read failure instead of rendering a confident zero", async () => {
    vi.spyOn(api, "libraryCoverage").mockRejectedValue(new Error("nope"));
    renderSection();
    expect(await screen.findByText(/Could not read your library/i)).toBeInTheDocument();
  });
});

describe("running", () => {
  function streamOf(events: { event: string; data: unknown }[]): ReadableStream<Uint8Array> {
    const text = events
      .map((e) => `event: ${e.event}\ndata: ${JSON.stringify(e.data)}\n\n`)
      .join("");
    return new ReadableStream({
      start(controller) {
        controller.enqueue(new TextEncoder().encode(text));
        controller.close();
      },
    });
  }

  function controlledStream() {
    let controller!: ReadableStreamDefaultController<Uint8Array>;
    const encoder = new TextEncoder();
    const stream = new ReadableStream<Uint8Array>({
      start(next) {
        controller = next;
      },
    });
    return {
      stream,
      push(event: string, data: unknown) {
        controller.enqueue(encoder.encode(`event: ${event}\ndata: ${JSON.stringify(data)}\n\n`));
      },
      close() {
        controller.close();
      },
    };
  }

  function progress(
    partId: string,
    status: string,
    done: number,
    over: Record<string, unknown> = {},
  ) {
    return {
      stage: "completing",
      done,
      total: 1_000,
      pct: (done + 1) / 1_000,
      part_id: partId,
      mpn: `MPN-${partId}`,
      display_name: `Part ${partId}`,
      status,
      satisfied: status === "completed" || status === "improved" ? ["kicad_symbol"] : [],
      remaining: status === "completed" ? [] : ["kicad_model"],
      message: `MPN-${partId}`,
      ...over,
    };
  }

  it("streams each part as it is filed, and offers a way out", async () => {
    vi.spyOn(api, "libraryCoverage").mockResolvedValue(coverage());
    vi.spyOn(api, "runCompletion").mockResolvedValue({ job_id: "j1" });
    let release: () => void = () => {};
    const held = new Promise<void>((r) => (release = r));
    vi.spyOn(api, "openJobStream").mockImplementation(async () => {
      await held;
      return streamOf([
        {
          event: "result",
          data: { result: { items: [], counts: {}, stopped: false, stop_reason: "" } },
        },
      ]);
    });
    renderSection();
    await userEvent.click(await screen.findByRole("button", { name: "Fill Supported CAD Gaps" }));
    // A run that cannot be stopped is a commitment the user cannot take back.
    expect(await screen.findByRole("button", { name: "Stop" })).toBeInTheDocument();
    await act(async () => {
      release();
    });
    await screen.findByRole("button", { name: "Fill Supported CAD Gaps" });
  });

  it("folds per-part SSE outcomes incrementally without polling or replacing the whole report", async () => {
    const coverageRead = vi.spyOn(api, "libraryCoverage").mockResolvedValue(coverage());
    vi.spyOn(api, "runCompletion").mockResolvedValue({ job_id: "j1" });
    const controlled = controlledStream();
    vi.spyOn(api, "openJobStream").mockResolvedValue(controlled.stream);
    renderSection();

    await userEvent.click(await screen.findByRole("button", { name: "Fill Supported CAD Gaps" }));
    await screen.findByRole("button", { name: "Stop" });

    await act(async () => {
      controlled.push("progress", progress("A", "completed", 0));
    });
    expect(await screen.findByText("1 Processed")).toBeInTheDocument();
    expect(screen.getByText("1 Filed")).toBeInTheDocument();
    expect(screen.getAllByText("MPN-A")).toHaveLength(2);

    await act(async () => {
      controlled.push("progress", progress("B", "deferred", 1));
    });
    expect(await screen.findByText("2 Processed")).toBeInTheDocument();
    expect(screen.getByText("1 To Retry")).toBeInTheDocument();
    expect(screen.getByText("MPN-A")).toBeInTheDocument();
    expect(screen.getAllByText("MPN-B")).toHaveLength(2); // current frame + one log row
    // The coverage aggregate is still the one initial read. Per-part progress is folded locally.
    expect(coverageRead).toHaveBeenCalledTimes(1);

    // A replay/correction for the same part replaces that part's live outcome. It cannot grow the
    // processed total or leave contradictory retry + filed counts behind.
    await act(async () => {
      controlled.push("progress", progress("B", "improved", 1));
    });
    expect(screen.getByText("2 Processed")).toBeInTheDocument();
    expect(screen.getByText("2 Filed")).toBeInTheDocument();
    expect(screen.queryByText("1 To Retry")).toBeNull();
    expect(screen.getAllByText("MPN-B")).toHaveLength(2);

    await act(async () => {
      controlled.push("result", {
        result: {
          items: [],
          counts: { completed: 1, improved: 1 },
          stopped: false,
          stop_reason: "",
        },
      });
      controlled.push("done", {});
      controlled.close();
    });
    await screen.findByRole("button", { name: "Fill Supported CAD Gaps" });
    expect(screen.getByText("2 Filed")).toBeInTheDocument();
    await waitFor(() => expect(coverageRead).toHaveBeenCalledTimes(2));
  });

  it("keeps cooperative stop wired and returns a stopped run to the resumable action", async () => {
    vi.spyOn(api, "libraryCoverage").mockResolvedValue(coverage());
    vi.spyOn(api, "runCompletion").mockResolvedValue({ job_id: "j-stop" });
    vi.spyOn(api, "stopJob").mockResolvedValue({
      job_id: "j-stop",
      stopping: true,
    });
    const controlled = controlledStream();
    vi.spyOn(api, "openJobStream").mockResolvedValue(controlled.stream);
    renderSection();

    await userEvent.click(await screen.findByRole("button", { name: "Fill Supported CAD Gaps" }));
    await act(async () => {
      controlled.push("progress", progress("A", "completed", 0));
    });
    await userEvent.click(await screen.findByRole("button", { name: "Stop" }));
    expect(api.stopJob).toHaveBeenCalledWith("j-stop");
    expect(await screen.findByRole("button", { name: "Stopping" })).toBeDisabled();

    await act(async () => {
      controlled.push("result", {
        result: {
          items: [],
          counts: { completed: 1 },
          stopped: true,
          stop_reason: "",
        },
      });
      controlled.push("done", {});
      controlled.close();
    });
    expect(await screen.findByText(/Stopped\. Run it again to carry on/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Fill Supported CAD Gaps" })).toBeEnabled();
  });

  it("keeps a rate-limited part apart from one nothing can help", async () => {
    // The distinction the whole report rests on. `deferred` means run it again; `unchanged`
    // means do not bother. Merging them makes the report useless for deciding what to do next.
    vi.spyOn(api, "libraryCoverage").mockResolvedValue(coverage());
    vi.spyOn(api, "runCompletion").mockResolvedValue({ job_id: "j1" });
    vi.spyOn(api, "openJobStream").mockResolvedValue(
      streamOf([
        {
          event: "result",
          data: {
            result: {
              items: [],
              counts: { completed: 10, deferred: 33, unchanged: 19 },
              stopped: false,
              stop_reason: "",
            },
          },
        },
      ]),
    );
    renderSection();
    await userEvent.click(await screen.findByRole("button", { name: "Fill Supported CAD Gaps" }));
    expect(await screen.findByText("10 Filed")).toBeInTheDocument();
    expect(screen.getByText("33 To Retry")).toBeInTheDocument();
    expect(screen.getByText("19 No Source")).toBeInTheDocument();
  });

  it("shows the reason a run stopped itself", async () => {
    // A stop with no reason is indistinguishable from a crash.
    vi.spyOn(api, "libraryCoverage").mockResolvedValue(coverage());
    vi.spyOn(api, "runCompletion").mockResolvedValue({ job_id: "j1" });
    vi.spyOn(api, "openJobStream").mockResolvedValue(
      streamOf([
        {
          event: "result",
          data: {
            result: {
              items: [],
              counts: { deferred: 5 },
              stopped: true,
              stop_reason: "the catalogue is refusing requests, so the run stopped",
            },
          },
        },
      ]),
    );
    renderSection();
    await userEvent.click(await screen.findByRole("button", { name: "Fill Supported CAD Gaps" }));
    expect(await screen.findByText(/the catalogue is refusing requests/i)).toBeInTheDocument();
  });

  it("shows a provider's non-error reason before the remaining gaps", async () => {
    vi.spyOn(api, "libraryCoverage").mockResolvedValue(coverage());
    vi.spyOn(api, "runCompletion").mockResolvedValue({ job_id: "j1" });
    vi.spyOn(api, "openJobStream").mockResolvedValue(
      streamOf([
        {
          event: "result",
          data: {
            result: {
              items: [
                {
                  part_id: "p1",
                  mpn: "M",
                  display_name: "Part One",
                  category: "ICs",
                  status: "unchanged",
                  needed: ["kicad_symbol"],
                  satisfied: [],
                  remaining: ["kicad_symbol"],
                  sources: [],
                  notes: ["snapmagic: no exact CAD model was found"],
                  error: "",
                },
              ],
              counts: { unchanged: 1 },
              stopped: false,
              stop_reason: "",
            },
          },
        },
      ]),
    );
    renderSection();

    await userEvent.click(await screen.findByRole("button", { name: "Fill Supported CAD Gaps" }));

    const detail = await screen.findByText(/snapmagic: no exact CAD model was found/i);
    expect(detail).toHaveTextContent(/snapmagic:.*Still needs symbol/i);
  });

  it("reports supplementary files without presenting them as filed CAD", async () => {
    vi.spyOn(api, "libraryCoverage").mockResolvedValue(coverage());
    vi.spyOn(api, "runCompletion").mockResolvedValue({ job_id: "j1" });
    vi.spyOn(api, "openJobStream").mockResolvedValue(
      streamOf([
        {
          event: "result",
          data: {
            result: {
              items: [
                {
                  part_id: "p1",
                  mpn: "5212034-1",
                  display_name: "Connector",
                  category: "Connectors",
                  status: "unchanged",
                  needed: ["kicad_model"],
                  satisfied: [],
                  retained: 1,
                  remaining: ["kicad_model"],
                  sources: [],
                  notes: [
                    "DigiKey · TraceParts: retained 1 exact supplementary file; no incomplete CAD bundle was activated",
                  ],
                  error: "",
                },
              ],
              counts: { unchanged: 1 },
              stopped: false,
              stop_reason: "",
            },
          },
        },
      ]),
    );
    renderSection();

    await userEvent.click(await screen.findByRole("button", { name: "Fill Supported CAD Gaps" }));

    expect(await screen.findByText("1 Supplementary Retained")).toBeInTheDocument();
    expect(screen.getByText("0 Filed")).toBeInTheDocument();
    expect(
      screen.getByText(/DigiKey · TraceParts: retained 1 exact supplementary file/),
    ).toHaveTextContent(/Still needs 3D model/i);
  });

  it("surfaces a failure to start rather than sitting on a spinner", async () => {
    vi.spyOn(api, "libraryCoverage").mockResolvedValue(coverage());
    vi.spyOn(api, "runCompletion").mockRejectedValue(new Error("backend is down"));
    renderSection();
    await userEvent.click(await screen.findByRole("button", { name: "Fill Supported CAD Gaps" }));
    // Reported in two places on purpose: the toast is transient, the paragraph persists.
    await waitFor(() => expect(screen.getAllByText(/backend is down/i).length).toBeGreaterThan(0));
  });
});

describe("durable completion", () => {
  const event = (
    sequence: number,
    kind: string,
    details: Record<string, string | number> = {},
  ): WorkflowEvent => ({
    sequence,
    item_id: "item-1",
    stage_id: "stage-1",
    kind,
    details,
    created_at: sequence,
  });

  it("reconnects from the last sequence and never duplicates replayed events", async () => {
    vi.spyOn(api, "libraryCoverage").mockResolvedValue(coverage());
    vi.spyOn(api, "runCompletion").mockResolvedValue({
      workflow_batch_id: "batch-1",
      event_cursor: 10,
    });
    const openLegacy = vi.spyOn(api, "openJobStream");
    const events = vi
      .spyOn(api, "workflowEvents")
      .mockResolvedValueOnce(
        durablePage(
          durableBatch("running", { running: 1 }),
          [event(11, "stage_completed", { stage: "metadata" })],
          11,
          true,
        ),
      )
      .mockRejectedValueOnce(new Error("connection reset"))
      .mockResolvedValueOnce(
        durablePage(
          durableBatch("completed", { completed: 1 }),
          [event(12, "stage_completed", { stage: "publish" })],
          12,
        ),
      );

    renderSection();
    await userEvent.click(await screen.findByRole("button", { name: "Fill Supported CAD Gaps" }));

    expect(await screen.findByText(/The durable workflow completed/i)).toBeInTheDocument();
    expect(screen.getAllByText("#11")).toHaveLength(1);
    expect(screen.getAllByText("#12")).toHaveLength(1);
    expect(events.mock.calls).toEqual([
      ["batch-1", 10, 200],
      ["batch-1", 11, 200],
      ["batch-1", 11, 200],
    ]);
    expect(api.runCompletion).toHaveBeenCalledWith({ limit: 1_000 });
    expect(openLegacy).not.toHaveBeenCalled();
  });

  it("keeps a 1,000-item durable run aggregate while bounding its event-log DOM", async () => {
    vi.spyOn(api, "libraryCoverage").mockResolvedValue(coverage());
    vi.spyOn(api, "runCompletion").mockResolvedValue({
      workflow_batch_id: "batch-1",
      event_cursor: 0,
    });
    const finalCounts = {
      completed: 742,
      failed: 125,
      blocked: 100,
      cancelled: 33,
    };
    const pages = vi
      .spyOn(api, "workflowEvents")
      .mockImplementation(async (_batchId, afterSequence) => {
        const nextSequence = Math.min(afterSequence + 200, 1_000);
        const isFinal = nextSequence === 1_000;
        const events = Array.from({ length: nextSequence - afterSequence }, (_, index) =>
          event(afterSequence + index + 1, "stage_completed", {
            stage: `stage_${afterSequence + index + 1}`,
          }),
        );
        return durablePage(
          durableBatch(
            isFinal ? "failed" : "running",
            isFinal ? finalCounts : { running: 1 },
            1_000,
          ),
          events,
          nextSequence,
          !isFinal,
        );
      });

    renderSection();
    await userEvent.click(await screen.findByRole("button", { name: "Fill Supported CAD Gaps" }));

    expect(
      await screen.findByText(/Completed stages and their terminal evidence are preserved/i),
    ).toBeInTheDocument();
    const durableRun = screen.getByTestId("completion-durable-run");
    expect(durableRun).toHaveTextContent("900 of 1000 settled");
    expect(screen.getByText("742 Completed")).toBeInTheDocument();
    expect(screen.getByText("125 Failed")).toBeInTheDocument();
    expect(screen.getByText("100 Blocked")).toBeInTheDocument();
    expect(screen.getByText("33 Cancelled")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Retry" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Cancel" })).toBeEnabled();
    expect(screen.queryByRole("button", { name: "Pause" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Resume" })).toBeNull();

    const eventLog = durableRun.querySelector("ul");
    expect(eventLog).not.toBeNull();
    expect(eventLog?.querySelectorAll("li")).toHaveLength(40);
    expect(screen.getByText("#1000")).toBeInTheDocument();
    expect(screen.getByText("#961")).toBeInTheDocument();
    expect(screen.queryByText("#960")).toBeNull();
    expect(screen.queryByText("#1")).toBeNull();
    expect(pages.mock.calls.map(([, cursor, limit]) => [cursor, limit])).toEqual([
      [0, 200],
      [200, 200],
      [400, 200],
      [600, 200],
      [800, 200],
    ]);
    expect(api.runCompletion).toHaveBeenCalledWith({ limit: 1_000 });
  });

  it("recovers a persisted durable cursor when the renderer remounts", async () => {
    vi.spyOn(api, "libraryCoverage").mockResolvedValue(coverage());
    sessionStorage.setItem(
      "stockroom.completion.workflow.v1",
      JSON.stringify({ batchId: "batch-1", cursor: 77 }),
    );
    vi.spyOn(api, "workflowEvents").mockResolvedValue(
      durablePage(
        durableBatch("completed", { completed: 1 }),
        [event(78, "stage_completed", { stage: "publish" })],
        78,
      ),
    );
    const submit = vi.spyOn(api, "runCompletion");

    renderSection();

    expect(await screen.findByText(/The durable workflow completed/i)).toBeInTheDocument();
    expect(api.workflowEvents).toHaveBeenCalledWith("batch-1", 77, 200);
    expect(submit).not.toHaveBeenCalled();
  });

  it("exposes real pause, resume, and cancel controls from durable actions", async () => {
    vi.spyOn(api, "libraryCoverage").mockResolvedValue(coverage());
    vi.spyOn(api, "runCompletion").mockResolvedValue({
      workflow_batch_id: "batch-1",
      event_cursor: 0,
    });
    vi.spyOn(api, "workflowEvents")
      .mockResolvedValueOnce(durablePage(durableBatch("running", { running: 1 }), [], 0))
      .mockImplementation(() => new Promise<WorkflowEventsPage>(() => undefined));
    vi.spyOn(api, "workflowPause").mockResolvedValue({
      schema_version: 1,
      operation: "pause",
      changed: true,
      batch: durableBatch("paused", { queued: 1 }),
    });
    vi.spyOn(api, "workflowResume").mockResolvedValue({
      schema_version: 1,
      operation: "resume",
      changed: true,
      batch: durableBatch("running", { queued: 1 }),
    });
    vi.spyOn(api, "workflowCancel").mockResolvedValue({
      schema_version: 1,
      operation: "cancel",
      changed: true,
      batch: durableBatch("cancelled", { cancelled: 1 }),
    });

    renderSection();
    await userEvent.click(await screen.findByRole("button", { name: "Fill Supported CAD Gaps" }));
    await userEvent.click(await screen.findByRole("button", { name: "Pause" }));
    expect(api.workflowPause).toHaveBeenCalledWith("batch-1");

    await userEvent.click(await screen.findByRole("button", { name: "Resume" }));
    expect(api.workflowResume).toHaveBeenCalledWith("batch-1");

    await userEvent.click(await screen.findByRole("button", { name: "Cancel" }));
    expect(api.workflowCancel).toHaveBeenCalledWith("batch-1");
    expect((await screen.findAllByText("Cancelled")).length).toBeGreaterThan(0);
    expect(screen.queryByRole("button", { name: "Cancel" })).toBeNull();
  });

  it("retries only a durably failed batch and reports no invented file outcome", async () => {
    vi.spyOn(api, "libraryCoverage").mockResolvedValue(coverage());
    vi.spyOn(api, "runCompletion").mockResolvedValue({
      workflow_batch_id: "batch-1",
      event_cursor: 4,
    });
    vi.spyOn(api, "workflowEvents")
      .mockResolvedValueOnce(
        durablePage(
          durableBatch("failed", { failed: 1 }),
          [event(5, "stage_failed", { attempt: 1 })],
          5,
        ),
      )
      .mockResolvedValueOnce(
        durablePage(
          durableBatch("completed", { completed: 1 }),
          [event(6, "stage_completed", { stage: "publish" })],
          6,
        ),
      );
    vi.spyOn(api, "workflowRetry").mockResolvedValue({
      schema_version: 1,
      operation: "retry",
      changed: true,
      batch: durableBatch("queued", { queued: 1 }),
    });

    renderSection();
    await userEvent.click(await screen.findByRole("button", { name: "Fill Supported CAD Gaps" }));
    expect(
      await screen.findByText(/Completed stages and their terminal evidence are preserved/i),
    ).toBeInTheDocument();
    expect(screen.queryByText(/\d+ Filed/)).toBeNull();

    await userEvent.click(await screen.findByRole("button", { name: "Retry" }));
    expect(api.workflowRetry).toHaveBeenCalledWith("batch-1");
    expect(await screen.findByText(/The durable workflow completed/i)).toBeInTheDocument();
    expect(api.workflowEvents).toHaveBeenLastCalledWith("batch-1", 5, 200);
  });
});
