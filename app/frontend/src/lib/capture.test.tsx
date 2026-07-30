import { createElement, type ReactNode } from "react";
import { act, renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { api } from "../api/client";
import { CaptureProvider, useCapture } from "./capture";
import { mockCapture } from "../test/captureMocks";
import {
  defaultUiSession,
  readUiSession,
  resetUiSessionForTests,
} from "./uiSession";

function wrap(qc: QueryClient) {
  return ({ children }: { children: ReactNode }) =>
    createElement(QueryClientProvider, { client: qc }, createElement(CaptureProvider, null, children));
}

function _cadSources(url: string | null) {
  // The real DTO shape: a list in the backend's trust order, plus the flattened head. A mock that
  // still returned only `url`/`vendor` would pass while the code reads `sources`.
  return url === null
    ? []
    : [
        {
          key: "ultralibrarian",
          label: "Ultra Librarian",
          url,
          tools: ["kicad", "altium"],
          aggregator: false,
          instruction: "Pick the part, choose KiCad and Altium, then Download.",
        },
      ];
}

function mockSource(url: string | null = "https://app.ultralibrarian.com/x") {
  vi.spyOn(api, "partCadSource").mockResolvedValue({
    url,
    mpn: "M",
    vendor: "Ultra Librarian",
    needs: [],
    sources: _cadSources(url),
  } as never);
}

function terminalCompletion(overrides: Record<string, unknown> = {}) {
  return [
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
              status: "already-complete",
              needed: [],
              satisfied: [],
              remaining: [],
              sources: [],
              notes: [],
              error: "",
              ...overrides,
            },
          ],
          counts: { "already-complete": 1 },
          stopped: false,
          stop_reason: "",
        },
      },
    },
    { event: "done", data: {} },
  ];
}

afterEach(() => {
  vi.restoreAllMocks();
  resetUiSessionForTests();
  delete (window as { pywebview?: unknown }).pywebview;
});

describe("CaptureProvider store", () => {
  it("follows a durable capture batch and never opens the legacy job stream", async () => {
    mockSource();
    vi.spyOn(api, "runCapture").mockResolvedValue({
      workflow_batch_id: "batch-capture-1",
      workflow_item_id: "item-capture-1",
      event_cursor: 0,
    });
    vi.spyOn(api, "workflowEvents").mockResolvedValue({
      schema_version: 1,
      batch: {
        id: "batch-capture-1",
        kind: "guided_capture",
        status: "completed",
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
          sequence: 7,
          item_id: "item-capture-1",
          stage_id: null,
          kind: "publication_completed",
          details: { stage: "publish" },
          created_at: 2,
        },
      ],
      cursor: {
        after_sequence: 0,
        next_sequence: 7,
        limit: 200,
        has_more: false,
      },
    });
    vi.spyOn(api, "captureWorkflow").mockResolvedValue({
      workflow_batch_id: "batch-capture-1",
      workflow_item_id: "item-capture-1",
      part_id: "p1",
      mode: "automatic",
      vendor: null,
      background: false,
      initial_needs: ["kicad_symbol"],
      report: terminalCompletion({
        needed: ["kicad_symbol"],
        satisfied: ["kicad_symbol"],
        completion_evidence: {
          state: "verified",
          manifest_digest:
            "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
          reason: "Verified.",
        },
      })[0].data.result,
    } as never);
    const stream = vi.spyOn(api, "openJobStream");
    const { result } = renderHook(() => useCapture(), {
      wrapper: wrap(new QueryClient()),
    });

    await act(async () => {
      await result.current.start("p1", "Part One", ["kicad_symbol"]);
    });

    expect(result.current.active.status).toBe("done");
    expect(result.current.active.message).toContain("datasheet");
    expect(stream).not.toHaveBeenCalled();
    expect(readUiSession().selected_ids.workflow_batch).toBeNull();
  });

  it("single-flights the same capture command and submits one idempotent durable request", async () => {
    mockSource();
    let release: (() => void) | null = null;
    const reference = new Promise<{
      workflow_batch_id: string;
      workflow_item_id: string;
      event_cursor: number;
    }>((resolve) => {
      release = () =>
        resolve({
          workflow_batch_id: "batch-single-flight",
          workflow_item_id: "item-single-flight",
          event_cursor: 0,
        });
    });
    const run = vi.spyOn(api, "runCapture").mockImplementation(() => reference);
    vi.spyOn(api, "workflowEvents").mockResolvedValue({
      schema_version: 1,
      batch: {
        id: "batch-single-flight",
        kind: "guided_capture",
        status: "completed",
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
      events: [],
      cursor: {
        after_sequence: 0,
        next_sequence: 1,
        limit: 200,
        has_more: false,
      },
    });
    vi.spyOn(api, "captureWorkflow").mockResolvedValue({
      workflow_batch_id: "batch-single-flight",
      workflow_item_id: "item-single-flight",
      part_id: "p1",
      mode: "automatic",
      vendor: null,
      background: false,
      initial_needs: ["kicad_symbol"],
      report: terminalCompletion({
        needed: ["kicad_symbol"],
        satisfied: ["kicad_symbol"],
        completion_evidence: {
          state: "verified",
          manifest_digest:
            "sha256:dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd",
          reason: "Verified.",
        },
      })[0].data.result,
    } as never);
    const { result } = renderHook(() => useCapture(), {
      wrapper: wrap(new QueryClient()),
    });

    let first: Promise<void>;
    let second: Promise<void>;
    await act(async () => {
      first = result.current.start("p1", "Part One", ["kicad_symbol"]);
      second = result.current.start("p1", "Part One", ["kicad_symbol"]);
      await Promise.resolve();
    });

    expect(second!).toBe(first!);
    expect(run).toHaveBeenCalledTimes(1);
    expect(run).toHaveBeenCalledWith(
      expect.objectContaining({
        partIds: ["p1"],
        idempotencyKey: expect.stringMatching(/^guided-capture-/),
      }),
    );

    await act(async () => {
      release?.();
      await Promise.all([first!, second!]);
    });
    expect(result.current.active.status).toBe("done");
  });

  it("fails closed when a standalone runtime returns only a process-local job", async () => {
    mockSource();
    const run = vi.spyOn(api, "runCapture").mockResolvedValue({ job_id: "memory-only-job" });
    const stream = vi.spyOn(api, "openJobStream");
    const { result } = renderHook(() => useCapture(), {
      wrapper: wrap(new QueryClient()),
    });

    await act(async () => {
      await result.current.start("p1", "Part One", ["kicad_symbol"]);
    });

    expect(result.current.active.status).toBe("unavailable");
    expect(result.current.active.message).toContain("process-local capture job");
    expect(result.current.active.message).toContain("Restart or update the Windows app");
    expect(stream).not.toHaveBeenCalled();
    expect(readUiSession().selected_ids.workflow_batch).toBeNull();
    expect(run).toHaveBeenCalledWith(
      expect.objectContaining({
        idempotencyKey: expect.stringMatching(/^guided-capture-/),
      }),
    );
  });

  it("reconnects a saved capture item from its durable event cursor after a renderer reload", async () => {
    const restored = defaultUiSession();
    restored.selected_ids.workflow_batch = "batch-restored";
    restored.selected_ids.workflow_item = "item-restored";
    restored.event_sequence = 41;
    resetUiSessionForTests(restored);
    vi.spyOn(api, "captureWorkflow").mockResolvedValue({
      workflow_batch_id: "batch-restored",
      workflow_item_id: "item-restored",
      part_id: "p1",
      mode: "assisted",
      vendor: "ultralibrarian",
      background: false,
      initial_needs: ["kicad_symbol"],
      report: terminalCompletion({
        needed: ["kicad_symbol"],
        satisfied: ["kicad_symbol"],
        completion_evidence: {
          state: "verified",
          manifest_digest:
            "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
          reason: "Verified.",
        },
      })[0].data.result,
    } as never);
    vi.spyOn(api, "partDetail").mockResolvedValue({
      id: "p1",
      derived: { display_name: "Part One" },
    } as never);
    mockSource();
    const events = vi.spyOn(api, "workflowEvents").mockResolvedValue({
      schema_version: 1,
      batch: {
        id: "batch-restored",
        kind: "guided_capture",
        status: "completed",
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
      events: [],
      cursor: {
        after_sequence: 41,
        next_sequence: 41,
        limit: 200,
        has_more: false,
      },
    });
    const run = vi.spyOn(api, "runCapture");
    const stream = vi.spyOn(api, "openJobStream");

    const { result } = renderHook(() => useCapture(), {
      wrapper: wrap(new QueryClient()),
    });

    await waitFor(() => expect(result.current.active.status).toBe("done"));
    expect(result.current.active.partId).toBe("p1");
    expect(events).toHaveBeenCalledWith("batch-restored", 41, 200);
    expect(run).not.toHaveBeenCalled();
    expect(stream).not.toHaveBeenCalled();
  });

  it("holds one active capture and replaces it when a different part starts", async () => {
    mockSource();
    mockCapture();
    const { result } = renderHook(() => useCapture(), { wrapper: wrap(new QueryClient()) });

    await act(async () => {
      await result.current.start("p1", "Part One", ["kicad_symbol"]);
    });
    expect(result.current.active.partId).toBe("p1");
    expect(result.current.active.partName).toBe("Part One");
    // `start` now awaits the whole job, so a finished run reports `done`. It used to hand off to a
    // Windows-only host callback and sit in `receiving` waiting to be told.
    expect(result.current.active.status).toBe("done");

    await act(async () => {
      await result.current.start("p2", "Part Two", ["kicad_symbol"]);
    });
    expect(result.current.active.partId).toBe("p2"); // replaced, never two at once
    expect(result.current.active.partName).toBe("Part Two");
  });

  it("keepWorking backgrounds the active capture so the pill can take over", async () => {
    mockSource();
    mockCapture();
    const { result } = renderHook(() => useCapture(), { wrapper: wrap(new QueryClient()) });

    await act(async () => {
      await result.current.start("p1", "One", ["kicad_symbol"]);
    });
    expect(result.current.active.backgrounded).toBe(false);
    act(() => {
      result.current.keepWorking();
    });
    expect(result.current.active.backgrounded).toBe(true);
  });

  it("requestReopen exposes the part id and unbackgrounds; clearReopen clears it", async () => {
    mockSource();
    mockCapture();
    const { result } = renderHook(() => useCapture(), { wrapper: wrap(new QueryClient()) });

    await act(async () => {
      await result.current.start("p1", "One", ["kicad_symbol"]);
    });
    act(() => {
      result.current.keepWorking();
    });
    act(() => {
      result.current.requestReopen();
    });
    expect(result.current.reopenPartId).toBe("p1");
    expect(result.current.active.backgrounded).toBe(false);

    act(() => {
      result.current.clearReopen();
    });
    expect(result.current.reopenPartId).toBeNull();
  });

  it("reset clears the active capture back to idle", async () => {
    mockSource();
    mockCapture();
    const { result } = renderHook(() => useCapture(), { wrapper: wrap(new QueryClient()) });

    await act(async () => {
      await result.current.start("p1", "One", ["kicad_symbol"]);
    });
    act(() => {
      result.current.reset();
    });
    expect(result.current.active.partId).toBeNull();
    expect(result.current.active.status).toBe("idle");
  });

  // -- The behaviours that still matter now the host callback is gone -----------------------
  //
  // The old tests here drove `window.__STOCKROOM_CAD_DOWNLOAD__`: a token-guarded "done" signal
  // forwarded from a Windows-only host. That protocol no longer exists - the backend owns the
  // capture and reports through the job stream. What DOES still matter is kept, driven through
  // the real route.

  it("captures through the cross-platform route, not a Windows-only host object", async () => {
    mockSource();
    const capture = mockCapture();
    const { result } = renderHook(() => useCapture(), { wrapper: wrap(new QueryClient()) });

    await act(async () => {
      await result.current.start("p1", "Part One", ["kicad_symbol"]);
    });

    expect(capture.run).toHaveBeenCalledWith(
      expect.objectContaining({
        partIds: ["p1"],
        vendor: undefined,
        mode: "automatic",
        idempotencyKey: expect.stringMatching(/^guided-capture-/),
      }),
    );
    // and nothing reached for the host bridge that used to exist
    expect((window as { pywebview?: unknown }).pywebview).toBeUndefined();
  });

  it("a capture whose part was replaced mid-flight never marks the new part", async () => {
    // The B4 guard, preserved. Its mechanism changed (a token from the host -> comparing the part
    // the run was started for) but the failure it prevents is identical: one part's result landing
    // on another part's checklist.
    mockSource();
    let release: (() => void) | null = null;
    const firstReference = new Promise<{
      workflow_batch_id: string;
      workflow_item_id: string;
      event_cursor: number;
    }>((resolve) => {
      release = () =>
        resolve({
          workflow_batch_id: "batch-stale",
          workflow_item_id: "item-stale",
          event_cursor: 0,
        });
    });
    vi.spyOn(api, "runCapture")
      .mockImplementationOnce(() => firstReference)
      .mockResolvedValueOnce({
        workflow_batch_id: "batch-current",
        workflow_item_id: "item-current",
        event_cursor: 0,
      });
    vi.spyOn(api, "workflowEvents").mockResolvedValue({
      schema_version: 1,
      batch: {
        id: "batch-current",
        kind: "guided_capture",
        status: "completed",
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
      events: [],
      cursor: {
        after_sequence: 0,
        next_sequence: 1,
        limit: 200,
        has_more: false,
      },
    });
    vi.spyOn(api, "captureWorkflow").mockResolvedValue({
      workflow_batch_id: "batch-current",
      workflow_item_id: "item-current",
      part_id: "p2",
      mode: "automatic",
      vendor: null,
      background: false,
      initial_needs: ["kicad_symbol"],
      report: terminalCompletion({
        part_id: "p2",
        needed: ["kicad_symbol"],
        satisfied: ["kicad_symbol"],
        completion_evidence: {
          state: "verified",
          manifest_digest:
            "sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc",
          reason: "Verified.",
        },
      })[0].data.result,
    } as never);

    const { result } = renderHook(() => useCapture(), { wrapper: wrap(new QueryClient()) });
    let first: Promise<void>;
    await act(async () => {
      first = result.current.start("p1", "Part One", ["kicad_symbol"]);
      await Promise.resolve();
    });
    // a second part takes over while the first submission response is delayed
    await act(async () => {
      await result.current.start("p2", "Part Two", ["kicad_symbol"]);
    });
    await act(async () => {
      release?.();
      await first!;
    });

    expect(result.current.active.partId).toBe("p2");
    expect(result.current.active.partName).toBe("Part Two");
    expect(readUiSession().selected_ids.workflow_batch).toBeNull();
  });

  it("an error frame from the run surfaces as an error, never a silent done", async () => {
    mockSource();
    mockCapture([
      { event: "error", data: { detail: "Ultra Librarian has no model for this part." } },
      { event: "done", data: {} },
    ]);
    const { result } = renderHook(() => useCapture(), { wrapper: wrap(new QueryClient()) });

    await act(async () => {
      await result.current.start("p1", "Part One", ["kicad_symbol"]);
    });

    expect(result.current.active.status).toBe("error");
    expect(result.current.active.message).toContain("stopped before");
    expect(result.current.active.message).toContain("Retry");
  });

  it("an unchanged completion report never reports verified completion", async () => {
    mockSource();
    mockCapture([
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
                notes: [],
                error: "No provider delivered an exact model.",
              },
            ],
            counts: { unchanged: 1 },
            stopped: false,
            stop_reason: "",
          },
        },
      },
      { event: "done", data: {} },
    ]);
    const { result } = renderHook(() => useCapture(), { wrapper: wrap(new QueryClient()) });

    await act(async () => {
      await result.current.start("p1", "Part One", ["kicad_symbol"]);
    });

    expect(result.current.active.status).toBe("error");
    expect(result.current.active.message).toContain("No provider delivered");
  });

  it("fails closed when empty needs and remaining arrive without completion evidence", async () => {
    mockSource();
    mockCapture(terminalCompletion());
    const { result } = renderHook(() => useCapture(), {
      wrapper: wrap(new QueryClient()),
    });

    await act(async () => {
      await result.current.start("p1", "Part One", []);
    });

    expect(result.current.active.status).toBe("error");
    expect(result.current.active.completionEvidence).toBeNull();
    expect(result.current.active.message).toContain("without completion evidence");
  });

  it("accepts verified completion only with a canonical immutable manifest digest", async () => {
    mockSource();
    mockCapture(
      terminalCompletion({
        completion_evidence: {
          state: "verified",
          manifest_digest: "sha256:not-canonical",
          reason: "The provider claimed verification.",
        },
      }),
    );
    const { result } = renderHook(() => useCapture(), {
      wrapper: wrap(new QueryClient()),
    });

    await act(async () => {
      await result.current.start("p1", "Part One", []);
    });

    expect(result.current.active.status).toBe("error");
    expect(result.current.active.message).toContain("without a canonical manifest digest");
  });

  it("keeps not-required distinct from verified file completion", async () => {
    mockSource();
    mockCapture(
      terminalCompletion({
        completion_evidence: {
          state: "not-required",
          manifest_digest: null,
          reason: "This mechanical record has no EDA deliverables.",
        },
      }),
    );
    const { result } = renderHook(() => useCapture(), {
      wrapper: wrap(new QueryClient()),
    });

    await act(async () => {
      await result.current.start("p1", "Part One", []);
    });

    expect(result.current.active.status).toBe("done");
    expect(result.current.active.received).toEqual({});
    expect(result.current.active.completionEvidence).toEqual({
      state: "not-required",
      manifest_digest: null,
      reason: "This mechanical record has no EDA deliverables.",
    });
    expect(result.current.active.message).toBe(
      "This mechanical record has no EDA deliverables.",
    );
  });

  it("surfaces an explicit unverified verdict as incomplete", async () => {
    mockSource();
    mockCapture(
      terminalCompletion({
        completion_evidence: {
          state: "unverified",
          manifest_digest: null,
          reason: "The active pointers did not match the retained manifest.",
        },
      }),
    );
    const { result } = renderHook(() => useCapture(), {
      wrapper: wrap(new QueryClient()),
    });

    await act(async () => {
      await result.current.start("p1", "Part One", []);
    });

    expect(result.current.active.status).toBe("error");
    expect(result.current.active.message).toContain("Completion was not verified");
    expect(result.current.active.message).toContain("active pointers did not match");
  });

  it("shows non-error provider explanations before the remaining CAD gaps", async () => {
    mockSource();
    mockCapture([
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
      { event: "done", data: {} },
    ]);
    const { result } = renderHook(() => useCapture(), { wrapper: wrap(new QueryClient()) });

    await act(async () => {
      await result.current.start("p1", "Part One", ["kicad_symbol"]);
    });

    expect(result.current.active.status).toBe("error");
    expect(result.current.active.message).toContain("snapmagic: no exact CAD model was found");
    expect(result.current.active.message).toContain("Still missing: KiCad Symbol");
    expect(result.current.active.message?.indexOf("snapmagic")).toBeLessThan(
      result.current.active.message?.indexOf("Still missing") ?? 0,
    );
  });
});
