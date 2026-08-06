/**
 * The completion surface, tested for the things that make a report TRUSTWORTHY rather than
 * merely present. Most of these assert a distinction the UI must not collapse, because every
 * one of them, collapsed, turns into the surface quietly lying about the library.
 */
import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { LibraryCompletionSection } from "./LibraryCompletionSection";
import { CaptureProvider } from "../lib/capture";
import { ToastProvider } from "../lib/toast";
import { api } from "../api/client";
import { resetCompletion } from "../lib/completionStore";
import { defaultUiSession, resetUiSessionForTests } from "../lib/uiSession";
import type {
  CaptureBatchWorklist,
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
    kind: "completion",
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

// One library-wide run's own split: two parts finished unattended, one provider route left that
// only a person can pass.
function worklist(): CaptureBatchWorklist {
  return {
    workflow_batch_id: "batch-1",
    total_items: 3,
    pending_items: 0,
    worklist: [
      {
        part_id: "lm317",
        mpn: "LM317",
        display_name: "LM317 Regulator",
        route_id: "ultralibrarian:ultralibrarian",
        provider_key: "ultralibrarian",
        label: "Ultra Librarian",
        status: "requires-human",
        reason: "no Ultra Librarian sign-in is saved on this PC",
        remaining: ["kicad_model"],
      },
    ],
    worklist_unit: "components",
    worklist_total: 1,
    unattended: [],
    unattended_total: 2,
    stalled: [],
    stalled_total: 0,
    unreadable: [],
  };
}

// CaptureProvider, because the worklist inside this section now STARTS captures rather than
// merely linking to a provider page, and it reads the one global capture slot to know whether a
// start is available. `main.tsx` mounts the same provider above the whole app.
function renderSection() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <CaptureProvider>
        <ToastProvider>
          <LibraryCompletionSection />
        </ToastProvider>
      </CaptureProvider>
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
    expect(await screen.findByText(/components hold each needed file/i)).toBeInTheDocument();
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
      await screen.findByText(/47 components have gaps a source ladder can attempt/i),
    ).toBeInTheDocument();
    expect(screen.getByText(/opening each provider page in turn/i)).toBeInTheDocument();
    expect(screen.getByText(/about 7 minutes/i)).toBeInTheDocument();
  });

  it("estimates a 10,000 part library in hours, not in 1250 minutes", async () => {
    vi.spyOn(api, "libraryCoverage").mockResolvedValue(
      coverage({ total: 10000, complete: 0, needs_files: 10000, unsourced: 0 }),
    );
    renderSection();
    expect(await screen.findByText(/about 23.8 hours/i)).toBeInTheDocument();
  });

  it("separately names the components no eligible source can reach", async () => {
    vi.spyOn(api, "libraryCoverage").mockResolvedValue(coverage());
    renderSection();
    expect(
      await screen.findByText(/no eligible source can provide so far/i),
    ).toBeInTheDocument();
  });

  it("explains the one Get Files run and its genuine human checkpoints", async () => {
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
            /31 components have gaps that need one Get Files run/i,
          ),
      ),
    ).toBeInTheDocument();
    expect(screen.getByText(/opens the provider page for each one/i)).toBeInTheDocument();
    expect(
      screen.getByText(/a person signs in where the provider asks, chooses the needed formats/i),
    ).toBeInTheDocument();
    expect(screen.getAllByText("Provider")).toHaveLength(2);
    expect(screen.queryByText("No Source")).not.toBeInTheDocument();
  });

  it("still runs when every remaining gap needs a provider route", async () => {
    // The run is the only thing that can say WHICH provider needs a person for WHICH part, so a
    // library whose last gaps are all assisted must still be able to start it. Disabling the
    // button here left the worklist permanently unreachable.
    vi.spyOn(api, "libraryCoverage").mockResolvedValue(
      coverage({
        needs_files: 0,
        needs_assistance: 12,
        assisted_can_provide: ["altium_symbol", "altium_footprint"],
      }),
    );
    renderSection();

    expect(await screen.findByRole("button", { name: "Fill Supported CAD Gaps" })).toBeEnabled();
    expect(screen.getByText(/Each remaining gap needs a provider route/i)).toBeInTheDocument();
  });

  it("disables the action when there is genuinely nothing to do", async () => {
    vi.spyOn(api, "libraryCoverage").mockResolvedValue(
      coverage({ complete: 158, needs_files: 0, unsourced: 0, by_requirement: {} }),
    );
    renderSection();
    expect(
      await screen.findByText(/All 158 components hold each needed file/i),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Fill Supported CAD Gaps" })).toBeDisabled();
  });

  it("says so plainly when the library is empty", async () => {
    vi.spyOn(api, "libraryCoverage").mockResolvedValue(
      coverage({ total: 0, complete: 0, needs_files: 0, unsourced: 0, by_requirement: {} }),
    );
    renderSection();
    expect(await screen.findByText(/has no components so far/i)).toBeInTheDocument();
  });

  it("reports a read failure instead of rendering a confident zero", async () => {
    vi.spyOn(api, "libraryCoverage").mockRejectedValue(new Error("nope"));
    renderSection();
    expect(await screen.findByText(/Could not read the catalog/i)).toBeInTheDocument();
  });
});

describe("running", () => {
  it("shows a durable in-flight run and offers cancellation without a job stream", async () => {
    vi.spyOn(api, "libraryCoverage").mockResolvedValue(coverage());
    vi.spyOn(api, "runCapture").mockResolvedValue({
      workflow_batch_id: "batch-1",
      event_cursor: 0,
    });
    vi.spyOn(api, "workflowEvents")
      .mockResolvedValueOnce(durablePage(durableBatch("running", { running: 1 }), [], 0))
      .mockImplementation(() => new Promise<WorkflowEventsPage>(() => undefined));
    const openJob = vi.spyOn(api, "openJobStream");
    renderSection();
    await userEvent.click(await screen.findByRole("button", { name: "Fill Supported CAD Gaps" }));
    expect(await screen.findByText("Durable")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Cancel" })).toBeInTheDocument();
    expect(openJob).not.toHaveBeenCalled();
  });

  it("renders durable aggregate counts and refreshes coverage only after terminal completion", async () => {
    const coverageRead = vi.spyOn(api, "libraryCoverage").mockResolvedValue(coverage());
    vi.spyOn(api, "runCapture").mockResolvedValue({
      workflow_batch_id: "batch-1",
      event_cursor: 0,
    });
    vi.spyOn(api, "workflowEvents").mockResolvedValue(
      durablePage(
        durableBatch("completed", { completed: 2 }, 2),
        [
          {
            sequence: 1,
            item_id: "item-1",
            stage_id: "stage-1",
            kind: "publication_completed",
            details: { stage: "publish" },
            created_at: 2,
          },
        ],
        1,
      ),
    );
    const openJob = vi.spyOn(api, "openJobStream");
    renderSection();

    await userEvent.click(await screen.findByRole("button", { name: "Fill Supported CAD Gaps" }));
    expect(await screen.findByText("2 Completed")).toBeInTheDocument();
    expect(screen.getByTestId("completion-durable-run")).toHaveTextContent("2 of 2 settled");
    expect(openJob).not.toHaveBeenCalled();
    await waitFor(() => expect(coverageRead).toHaveBeenCalledTimes(2));
  });

  it("routes cancellation through the durable workflow control", async () => {
    vi.spyOn(api, "libraryCoverage").mockResolvedValue(coverage());
    vi.spyOn(api, "runCapture").mockResolvedValue({
      workflow_batch_id: "batch-1",
      event_cursor: 0,
    });
    vi.spyOn(api, "workflowEvents")
      .mockResolvedValueOnce(durablePage(durableBatch("running", { running: 1 }), [], 0))
      .mockImplementation(() => new Promise<WorkflowEventsPage>(() => undefined));
    const cancelled = durableBatch("running", { running: 1 });
    cancelled.cancellation = {
      state: "requested",
      requested_at: 3,
      completed_at: null,
    };
    cancelled.actions = {
      can_pause: false,
      can_resume: false,
      can_retry: false,
      can_cancel: false,
    };
    const cancel = vi.spyOn(api, "workflowCancel").mockResolvedValue({
      schema_version: 1,
      operation: "cancel",
      changed: true,
      batch: cancelled,
    });
    renderSection();

    await userEvent.click(await screen.findByRole("button", { name: "Fill Supported CAD Gaps" }));
    await userEvent.click(await screen.findByRole("button", { name: "Cancel" }));
    expect(cancel).toHaveBeenCalledWith("batch-1");
    expect(await screen.findByText("Cancelling")).toBeInTheDocument();
  });

  it("keeps completed and failed durable item counts distinct", async () => {
    vi.spyOn(api, "libraryCoverage").mockResolvedValue(coverage());
    vi.spyOn(api, "runCapture").mockResolvedValue({
      workflow_batch_id: "batch-1",
      event_cursor: 0,
    });
    vi.spyOn(api, "workflowEvents").mockResolvedValue(
      durablePage(
        durableBatch("failed", { completed: 10, failed: 19 }, 29),
        [],
        0,
      ),
    );
    renderSection();
    await userEvent.click(await screen.findByRole("button", { name: "Fill Supported CAD Gaps" }));
    expect(await screen.findByText("10 Completed")).toBeInTheDocument();
    expect(screen.getByText("19 Failed")).toBeInTheDocument();
    expect(screen.getByTestId("completion-durable-run")).toHaveTextContent("29 of 29 settled");
  });

  it("explains that durable retry preserves already completed evidence", async () => {
    vi.spyOn(api, "libraryCoverage").mockResolvedValue(coverage());
    vi.spyOn(api, "runCapture").mockResolvedValue({
      workflow_batch_id: "batch-1",
      event_cursor: 0,
    });
    vi.spyOn(api, "workflowEvents").mockResolvedValue(
      durablePage(durableBatch("failed", { failed: 1 }), [], 0),
    );
    renderSection();
    await userEvent.click(await screen.findByRole("button", { name: "Fill Supported CAD Gaps" }));
    expect(
      await screen.findByText(/Completed stages and their terminal evidence are preserved/i),
    ).toBeInTheDocument();
  });

  it("projects only the allowlisted durable failure event, never a raw provider payload", async () => {
    vi.spyOn(api, "libraryCoverage").mockResolvedValue(coverage());
    vi.spyOn(api, "runCapture").mockResolvedValue({
      workflow_batch_id: "batch-1",
      event_cursor: 0,
    });
    vi.spyOn(api, "workflowEvents").mockResolvedValue(
      durablePage(
        durableBatch("failed", { failed: 1 }),
        [
          {
            sequence: 5,
            item_id: "item-1",
            stage_id: "stage-1",
            kind: "stage_failed",
            details: { stage: "cad_acquisition" },
            created_at: 2,
          },
        ],
        5,
      ),
    );
    renderSection();

    await userEvent.click(await screen.findByRole("button", { name: "Fill Supported CAD Gaps" }));

    expect(await screen.findByText(/Stage Failed · cad acquisition/i)).toBeInTheDocument();
    expect(screen.queryByText(/snapmagic/i)).toBeNull();
  });

  it("does not infer filed CAD from a terminal workflow status", async () => {
    vi.spyOn(api, "libraryCoverage").mockResolvedValue(coverage());
    vi.spyOn(api, "runCapture").mockResolvedValue({
      workflow_batch_id: "batch-1",
      event_cursor: 0,
    });
    vi.spyOn(api, "workflowEvents").mockResolvedValue(
      durablePage(durableBatch("completed", { completed: 1 }), [], 0),
    );
    renderSection();

    await userEvent.click(await screen.findByRole("button", { name: "Fill Supported CAD Gaps" }));

    expect(
      await screen.findByText(/this status does not infer which files changed/i),
    ).toBeInTheDocument();
    expect(screen.queryByText(/Additional Retained/i)).toBeNull();
  });

  it("starts one bounded run over every component that needs files, never part by part", async () => {
    // The owner asked for "a simple download button ... that can do everything for you". One
    // press, no selection: the command carries no part ids, which the API defines as every part
    // still missing files. It is submitted as the one all-source CAPTURE so each part retains the
    // report the worklist below is read from; the batch it resolves is the same one either
    // command produced.
    vi.spyOn(api, "libraryCoverage").mockResolvedValue(coverage());
    const submit = vi.spyOn(api, "runCapture").mockResolvedValue({
      workflow_batch_id: "batch-1",
      event_cursor: 0,
    });
    vi.spyOn(api, "workflowEvents").mockResolvedValue(
      durablePage(durableBatch("completed", { completed: 2 }, 2), [], 0),
    );
    vi.spyOn(api, "captureWorklist").mockResolvedValue(worklist());
    renderSection();

    await userEvent.click(await screen.findByRole("button", { name: "Fill Supported CAD Gaps" }));

    expect(submit).toHaveBeenCalledTimes(1);
    expect(submit).toHaveBeenCalledWith({
      limit: 1_000,
      idempotencyKey: expect.stringMatching(/^library-completion-/),
    });
    expect(submit.mock.calls[0][0]).not.toHaveProperty("partIds");
  });

  it("shows the worklist of what the run could not finish alone, beside the run itself", async () => {
    vi.spyOn(api, "libraryCoverage").mockResolvedValue(coverage());
    vi.spyOn(api, "runCapture").mockResolvedValue({
      workflow_batch_id: "batch-1",
      event_cursor: 0,
    });
    vi.spyOn(api, "workflowEvents").mockResolvedValue(
      durablePage(durableBatch("completed", { completed: 2 }, 2), [], 0),
    );
    vi.spyOn(api, "captureWorklist").mockResolvedValue(worklist());
    vi.spyOn(api, "partCadSource").mockResolvedValue({
      mpn: "LM317",
      needs: ["kicad_model"],
      sources: [
        {
          key: "ultralibrarian",
          label: "Ultra Librarian",
          url: "https://app.ultralibrarian.com/search?queryText=LM317",
          tools: ["kicad", "altium"],
          aggregator: false,
          instruction: "Pick the part, choose KiCad and Altium, then Download.",
          capture_available: true,
        },
      ],
      url: "https://app.ultralibrarian.com/search?queryText=LM317",
      vendor: "Ultra Librarian",
    } as never);
    renderSection();

    await userEvent.click(await screen.findByRole("button", { name: "Fill Supported CAD Gaps" }));

    expect(await screen.findByTestId("completion-worklist")).toHaveTextContent("1 Needs You");
    expect(
      await screen.findByRole("button", { name: "Get files for LM317 Regulator" }),
    ).toBeEnabled();
    expect(screen.queryByRole("link", { name: /Open Ultra Librarian/ })).not.toBeInTheDocument();
    expect(api.captureWorklist).toHaveBeenCalledWith("batch-1");
  });

  it("surfaces a failure to start rather than sitting on a spinner", async () => {
    vi.spyOn(api, "libraryCoverage").mockResolvedValue(coverage());
    vi.spyOn(api, "runCapture").mockRejectedValue(new Error("backend is down"));
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
    vi.spyOn(api, "runCapture").mockResolvedValue({
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
    expect(api.runCapture).toHaveBeenCalledWith(
      expect.objectContaining({
        limit: 1_000,
        idempotencyKey: expect.stringMatching(/^library-completion-/),
      }),
    );
    expect(openLegacy).not.toHaveBeenCalled();
  });

  it("keeps a 1,000-item durable run aggregate while bounding its event-log DOM", async () => {
    vi.spyOn(api, "libraryCoverage").mockResolvedValue(coverage());
    vi.spyOn(api, "runCapture").mockResolvedValue({
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
    expect(screen.getByRole("button", { name: "Rerun" })).toBeEnabled();
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
    expect(api.runCapture).toHaveBeenCalledWith(
      expect.objectContaining({
        limit: 1_000,
        idempotencyKey: expect.stringMatching(/^library-completion-/),
      }),
    );
  });

  it("recovers a persisted durable cursor when the renderer remounts", async () => {
    vi.spyOn(api, "libraryCoverage").mockResolvedValue(coverage());
    const session = defaultUiSession();
    session.selected_ids.workflow_batch = "batch-1";
    session.event_sequence = 77;
    resetUiSessionForTests(session);
    vi.spyOn(api, "workflowEvents").mockResolvedValue(
      durablePage(
        durableBatch("completed", { completed: 1 }),
        [event(78, "stage_completed", { stage: "publish" })],
        78,
      ),
    );
    const submit = vi.spyOn(api, "runCapture");

    renderSection();

    expect(await screen.findByText(/The durable workflow completed/i)).toBeInTheDocument();
    expect(api.workflowEvents).toHaveBeenCalledWith("batch-1", 77, 200);
    expect(submit).not.toHaveBeenCalled();
  });

  it("exposes real pause, resume, and cancel controls from durable actions", async () => {
    vi.spyOn(api, "libraryCoverage").mockResolvedValue(coverage());
    vi.spyOn(api, "runCapture").mockResolvedValue({
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
    vi.spyOn(api, "runCapture").mockResolvedValue({
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

    await userEvent.click(await screen.findByRole("button", { name: "Rerun" }));
    expect(api.workflowRetry).toHaveBeenCalledWith("batch-1");
    expect(await screen.findByText(/The durable workflow completed/i)).toBeInTheDocument();
    expect(api.workflowEvents).toHaveBeenLastCalledWith("batch-1", 5, 200);
  });
});
