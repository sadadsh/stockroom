import { api } from "../api/client";
import {
  reconnectCompletion,
  resetCompletion,
  startCompletion,
} from "./completionStore";
import {
  defaultUiSession,
  readUiSession,
  resetUiSessionForTests,
} from "./uiSession";

function terminalEvents(batchId: string, afterSequence = 0) {
  return {
    schema_version: 1 as const,
    batch: {
      id: batchId,
      kind: "completion" as const,
      status: "completed" as const,
      created_at: 1,
      updated_at: 2,
      total_items: 1,
      item_counts: { completed: 1 },
      cancellation: null,
      actions: {
        can_pause: false,
        can_resume: false,
        can_retry: false,
        can_cancel: false,
      },
    },
    events: [
      {
        sequence: Math.max(afterSequence + 1, 1),
        item_id: "item-1",
        stage_id: null,
        kind: "publication_completed",
        details: { stage: "publish" },
        created_at: 2,
      },
    ],
    cursor: {
      after_sequence: afterSequence,
      next_sequence: Math.max(afterSequence + 1, 1),
      limit: 200,
      has_more: false,
    },
  };
}

afterEach(() => {
  vi.restoreAllMocks();
  resetCompletion();
  resetUiSessionForTests();
});

describe("durable completion store", () => {
  it("single-flights submission and follows one idempotent durable batch", async () => {
    let resolveReference!: (value: {
      workflow_batch_id: string;
      event_cursor: number;
    }) => void;
    const reference = new Promise<{
      workflow_batch_id: string;
      event_cursor: number;
    }>((resolve) => {
      resolveReference = resolve;
    });
    // CORRECTED with the worklist slice: the library-wide run is submitted through the CAPTURE
    // command with no part ids ("every part still missing files"), because only a capture item
    // retains the per-part report that carries each route's `requires-human` outcome. The batch
    // resolution, bound, and stage work are unchanged - an automatic capture request is exactly
    // what a completion item already decoded to.
    const run = vi.spyOn(api, "runCapture").mockImplementation(() => reference);
    const stream = vi.spyOn(api, "openJobStream");
    vi.spyOn(api, "workflowEvents").mockResolvedValue(
      terminalEvents("batch-completion-1"),
    );

    const first = startCompletion({ partIds: ["p1"], limit: 1 });
    const second = startCompletion({ partIds: ["p1"], limit: 1 });
    expect(second).toBe(first);
    expect(run).toHaveBeenCalledTimes(1);
    expect(run).toHaveBeenCalledWith({
      partIds: ["p1"],
      limit: 1,
      mode: "automatic",
      idempotencyKey: expect.stringMatching(/^library-completion-/),
    });

    resolveReference({
      workflow_batch_id: "batch-completion-1",
      event_cursor: 0,
    });
    const [firstState, secondState] = await Promise.all([first, second]);

    expect(firstState.status).toBe("done");
    expect(secondState.status).toBe("done");
    expect(readUiSession().selected_ids.workflow_batch).toBeNull();
    expect(stream).not.toHaveBeenCalled();
  });

  it("reconnects the saved durable cursor before considering a new submission", async () => {
    const restored = defaultUiSession();
    restored.selected_ids.workflow_batch = "batch-restored-completion";
    restored.selected_ids.workflow_item = null;
    restored.event_sequence = 41;
    resetUiSessionForTests(restored);
    const events = vi
      .spyOn(api, "workflowEvents")
      .mockResolvedValue(terminalEvents("batch-restored-completion", 41));
    const run = vi.spyOn(api, "runCapture");

    const result = await reconnectCompletion();

    expect(result.status).toBe("done");
    expect(events).toHaveBeenCalledWith("batch-restored-completion", 41, 200);
    expect(run).not.toHaveBeenCalled();
  });

  it("never follows or stores a process-local compatibility job", async () => {
    vi.spyOn(api, "runCapture").mockResolvedValue({ job_id: "memory-only-job" });
    const stream = vi.spyOn(api, "openJobStream");

    const result = await startCompletion({ limit: 1 });

    expect(result.status).toBe("error");
    expect(result.error).toContain("process-local completion job");
    expect(result.error).toContain("Restart or update the Windows app");
    expect(result.transport).toBeNull();
    expect(result.batchId).toBeNull();
    expect("jobId" in result).toBe(false);
    expect(stream).not.toHaveBeenCalled();
    expect(readUiSession().selected_ids.workflow_batch).toBeNull();
  });
});
