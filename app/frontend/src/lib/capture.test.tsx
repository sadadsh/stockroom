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

function mockSource(
  url: string | null = "https://app.ultralibrarian.com/x",
  overrides: Record<string, unknown> = {},
) {
  vi.spyOn(api, "partCadSource").mockResolvedValue({
    url,
    mpn: "M",
    vendor: "Ultra Librarian",
    needs: [],
    sources: _cadSources(url),
    completion_evidence: {
      state: "verified",
      manifest_digest:
        "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
      reason: "The canonical library package was verified.",
    },
    ...overrides,
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
              collection_complete: true,
              ...overrides,
            },
          ],
          counts: { "already-complete": 1 },
          collection_complete: true,
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
      vendor: null,
      background: false,
      initial_needs: ["kicad_symbol"],
      report: terminalCompletion({
        needed: ["kicad_symbol"],
        satisfied: ["kicad_symbol"],
        collection_complete: false,
        provider_outcomes: [
          {
            route_id: "digikey:digikey-snapmagic",
            provider_key: "digikey",
            author_key: "digikey-snapmagic",
            label: "DigiKey / SnapMagic",
            status: "requires-human",
            attempted: true,
            retained: 0,
            activated: false,
            reason: "An optional route needs a provider step.",
          },
        ],
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
      // The renderer can hold an older query projection than the write-fenced durable intake.
      // The workflow snapshot must replace that stale caller value for progress and completion.
      await result.current.start("p1", "Part One", []);
    });

    expect(result.current.active.status).toBe("done");
    expect(result.current.active.received.kicad_symbol).toBe(true);
    expect(result.current.active.message).toContain("verified and linked");
    expect(stream).not.toHaveBeenCalled();
    expect(readUiSession().selected_ids.workflow_batch).toBeNull();
  });

  it("never treats a verified staging report as published library completion", async () => {
    mockSource(undefined, {
      needs: ["kicad_symbol"],
      completion_evidence: null,
    });
    vi.spyOn(api, "runCapture").mockResolvedValue({
      workflow_batch_id: "batch-publication-failed",
      workflow_item_id: "item-publication-failed",
      event_cursor: 0,
    });
    vi.spyOn(api, "workflowEvents").mockResolvedValue({
      schema_version: 1,
      batch: {
        id: "batch-publication-failed",
        kind: "guided_capture",
        status: "failed",
        created_at: 1,
        updated_at: 2,
        total_items: 1,
        item_counts: { failed: 1 },
        cancellation: null,
        actions: {
          can_pause: false,
          can_resume: false,
          can_retry: true,
          can_cancel: true,
        },
      },
      events: [
        {
          sequence: 4,
          item_id: "item-publication-failed",
          stage_id: null,
          kind: "stage_failed",
          details: { stage: "publish" },
          created_at: 2,
        },
      ],
      cursor: {
        after_sequence: 0,
        next_sequence: 4,
        limit: 200,
        has_more: false,
      },
    });
    vi.spyOn(api, "captureWorkflow").mockResolvedValue({
      workflow_batch_id: "batch-publication-failed",
      workflow_item_id: "item-publication-failed",
      part_id: "p1",
      vendor: "ultralibrarian",
      background: false,
      initial_needs: ["kicad_symbol"],
      report: terminalCompletion({
        status: "completed",
        needed: ["kicad_symbol"],
        satisfied: ["kicad_symbol"],
        remaining: [],
        completion_evidence: {
          state: "verified",
          manifest_digest:
            "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
          reason: "The staging package was verified before publication failed.",
        },
      })[0].data.result,
    } as never);
    const { result } = renderHook(() => useCapture(), {
      wrapper: wrap(new QueryClient()),
    });

    await act(async () => {
      await result.current.start("p1", "Part One", ["kicad_symbol"]);
    });

    expect(result.current.active.status).toBe("error");
    expect(result.current.active.received.kicad_symbol).not.toBe(true);
    expect(result.current.active.completionEvidence).toBeNull();
    expect(result.current.active.message).toContain(
      "verified package could not be published to the library",
    );
    expect(result.current.active.message).toContain("retained evidence");
  });

  it("turns a blocked automatic handoff into an actionable partial result", async () => {
    mockSource(undefined, {
      needs: ["kicad_symbol"],
      completion_evidence: {
        state: "unverified",
        manifest_digest: null,
        reason: "No complete shared CAD package was verified.",
      },
    });
    vi.spyOn(api, "runCapture").mockResolvedValue({
      workflow_batch_id: "batch-provider-handoff",
      workflow_item_id: "item-provider-handoff",
      event_cursor: 0,
    });
    vi.spyOn(api, "workflowEvents").mockResolvedValue({
      schema_version: 1,
      batch: {
        id: "batch-provider-handoff",
        kind: "guided_capture",
        status: "blocked",
        created_at: 1,
        updated_at: 2,
        total_items: 1,
        item_counts: { blocked: 1 },
        cancellation: null,
        actions: {
          can_pause: true,
          can_resume: false,
          can_retry: false,
          can_cancel: true,
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
      workflow_batch_id: "batch-provider-handoff",
      workflow_item_id: "item-provider-handoff",
      part_id: "p1",
      vendor: "ultralibrarian",
      background: false,
      initial_needs: ["kicad_symbol"],
      report: terminalCompletion({
        status: "unchanged",
        needed: ["kicad_symbol"],
        satisfied: [],
        remaining: ["kicad_symbol"],
        provider_outcomes: [
          {
            route_id: "ultralibrarian:ultralibrarian",
            provider_key: "ultralibrarian",
            author_key: "ultralibrarian",
            label: "Ultra Librarian",
            status: "requires-human",
            attempted: false,
            retained: 0,
            activated: false,
            reason: "A person-driven provider handoff is required.",
          },
        ],
        collection_complete: false,
        completion_evidence: {
          state: "unverified",
          manifest_digest: null,
          reason: "No complete shared CAD package was verified.",
        },
      })[0].data.result,
    } as never);
    const { result } = renderHook(() => useCapture(), {
      wrapper: wrap(new QueryClient()),
    });

    await act(async () => {
      await result.current.start("p1", "Part One", ["kicad_symbol"], "ultralibrarian");
    });

    expect(result.current.active.status).toBe("error");
    expect(result.current.active.message).toContain(
      "Clear the provider gate, then select Get Files again",
    );
    expect(result.current.active.providerOutcomes[0]?.status).toBe("requires-human");
    expect(readUiSession().selected_ids.workflow_batch).toBeNull();
  });

  it.each(["blocked", "running"] as const)(
    "keeps a %s exact provider route reopenable, then releases it on close",
    async (batchStatus) => {
      mockSource(undefined, {
        needs: ["kicad_symbol"],
        completion_evidence: {
          state: "unverified",
          manifest_digest: null,
          reason: "No complete shared CAD package was verified.",
        },
      });
      vi.spyOn(api, "runCapture").mockResolvedValue({
        workflow_batch_id: "batch-active-handoff",
        workflow_item_id: "item-active-handoff",
        event_cursor: 0,
      });
      let routeActive = true;
      vi.spyOn(api, "workflowEvents").mockImplementation(async () => ({
        schema_version: 1,
        batch: {
          id: "batch-active-handoff",
          kind: "guided_capture",
          status: routeActive ? batchStatus : "cancelled",
          created_at: 1,
          updated_at: 2,
          total_items: 1,
          item_counts: { [routeActive ? batchStatus : "cancelled"]: 1 },
          cancellation: null,
          actions: {
            can_pause: true,
            can_resume: false,
            can_retry: false,
            can_cancel: true,
          },
        },
        events: [],
        cursor: { after_sequence: 0, next_sequence: 1, limit: 200, has_more: false },
      }));
      vi.spyOn(api, "captureWorkflow").mockImplementation(async () => ({
        workflow_batch_id: "batch-active-handoff",
        workflow_item_id: "item-active-handoff",
        part_id: "p1",
        vendor: "ultralibrarian",
        background: false,
        active_route: routeActive
          ? {
              vendor: "ultralibrarian",
              detail_url: "https://app.ultralibrarian.com/x",
              route_token: "route-active-handoff",
              browser_state: {
                url: "https://app.ultralibrarian.com/redirected",
                loading: false,
                navigation_error: "",
                can_go_back: true,
                can_go_forward: false,
              },
            }
          : null,
        initial_needs: ["kicad_symbol"],
        report: null,
      }));
      const cancel = vi.spyOn(api, "workflowCancel").mockImplementation(async () => {
        routeActive = false;
        return {} as never;
      });
      const showProvider = vi.spyOn(api, "showCaptureProvider").mockResolvedValue({
        workflow_batch_id: "batch-active-handoff",
        part_id: "p1",
        visible: true,
      });
      const providerIntent = vi.spyOn(api, "signalCaptureIntent").mockResolvedValue({
        part_id: "p1",
        workflow_item_id: "item-active-handoff",
        action: "finish-route",
        accepted: true,
      });
      const { result } = renderHook(() => useCapture(), {
        wrapper: wrap(new QueryClient()),
      });

      let running!: Promise<void>;
      act(() => {
        running = result.current.start("p1", "Part One", ["kicad_symbol"]);
      });
      await waitFor(() => expect(result.current.active.status).toBe("window-open"));
      expect(result.current.active.routeToken).toBe("route-active-handoff");
      expect(result.current.active.url).toBe("https://app.ultralibrarian.com/redirected");
      expect(result.current.active.browserState?.can_go_back).toBe(true);
      await act(async () => result.current.showProvider());
      expect(showProvider).toHaveBeenCalledWith("batch-active-handoff");
      await act(async () => result.current.finishProvider());
      expect(providerIntent).toHaveBeenCalledWith({
        partId: "p1",
        workflowItemId: "item-active-handoff",
        action: "finish-route",
        routeToken: "route-active-handoff",
      });
      await act(async () => result.current.skipProvider());
      expect(providerIntent).toHaveBeenLastCalledWith({
        partId: "p1",
        workflowItemId: "item-active-handoff",
        action: "skip-part",
      });

      await act(async () => result.current.closeProvider());
      expect(cancel).toHaveBeenCalledWith("batch-active-handoff");
      expect(result.current.active.status).toBe("idle");
      await act(async () => running);
    },
  );

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

  it("allows a different part only after the previous capture reaches a terminal state", async () => {
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

  it("refuses a second part instead of orphaning the active durable workflow", async () => {
    mockSource();
    // Neither submission resolves, so p1's capture is genuinely still in flight when p2 starts.
    vi.spyOn(api, "runCapture").mockImplementation(
      () => new Promise(() => undefined),
    );
    const { result } = renderHook(() => useCapture(), { wrapper: wrap(new QueryClient()) });

    await act(async () => {
      void result.current.start("p1", "Part One", ["kicad_symbol"]);
      await Promise.resolve();
    });
    expect(result.current.active.partId).toBe("p1");
    await expect(
      result.current.start("p2", "Part Two", ["kicad_symbol"]),
    ).rejects.toThrow("Finish the active completion for Part One");
    expect(result.current.active.partId).toBe("p1");
    expect(api.runCapture).toHaveBeenCalledTimes(1);
  });

  it("refuses a new part while a durable workflow restored after reload is still running", async () => {
    const restored = defaultUiSession();
    restored.selected_ids.workflow_batch = "batch-restored-running";
    restored.selected_ids.workflow_item = "item-restored-running";
    restored.event_sequence = 7;
    resetUiSessionForTests(restored);
    vi.spyOn(api, "captureWorkflow").mockResolvedValue({
      workflow_batch_id: "batch-restored-running",
      workflow_item_id: "item-restored-running",
      part_id: "p1",
      vendor: null,
      background: true,
      initial_needs: ["kicad_symbol"],
      report: null,
    } as never);
    vi.spyOn(api, "partDetail").mockResolvedValue({
      id: "p1",
      derived: { display_name: "Part One" },
    } as never);
    vi.spyOn(api, "workflowEvents").mockReturnValue(new Promise(() => undefined));
    const run = vi.spyOn(api, "runCapture");
    const { result } = renderHook(() => useCapture(), {
      wrapper: wrap(new QueryClient()),
    });

    await waitFor(() => expect(result.current.active.status).toBe("receiving"));
    await expect(
      result.current.start("p2", "Part Two", ["kicad_symbol"]),
    ).rejects.toThrow("Finish the active completion for Part One");
    expect(result.current.active.partId).toBe("p1");
    expect(run).not.toHaveBeenCalled();
  });

  it("single-flights the same command and refuses a different command for the active part", async () => {
    mockSource();
    vi.spyOn(api, "runCapture").mockImplementation(
      () => new Promise(() => undefined),
    );
    const { result } = renderHook(() => useCapture(), { wrapper: wrap(new QueryClient()) });

    await act(async () => {
      void result.current.start("p1", "Part One", ["kicad_symbol"]);
      await Promise.resolve();
    });
    await expect(
      result.current.start("p1", "Part One", ["kicad_symbol"], "ultralibrarian"),
    ).rejects.toThrow("Finish the active completion for Part One");
    expect(result.current.active.partId).toBe("p1");
    expect(api.runCapture).toHaveBeenCalledTimes(1);
  });

  it("treats a different EDA selection as a different active capture command", async () => {
    mockSource();
    vi.spyOn(api, "runCapture").mockImplementation(() => new Promise(() => undefined));
    const { result } = renderHook(() => useCapture(), { wrapper: wrap(new QueryClient()) });

    await act(async () => {
      void result.current.start("p1", "Part One", ["kicad_symbol", "kicad_footprint", "kicad_model"]);
      await Promise.resolve();
    });

    await expect(
      result.current.start("p1", "Part One", ["altium_symbol", "altium_footprint", "kicad_model"]),
    ).rejects.toThrow("Finish the active completion for Part One");
    expect(api.runCapture).toHaveBeenCalledTimes(1);
    expect(api.runCapture).toHaveBeenCalledWith(expect.objectContaining({ edas: ["kicad"] }));
  });

  it("forces an explicitly selected provider visit even when retained evidence exists", async () => {
    mockSource();
    const run = vi.spyOn(api, "runCapture").mockImplementation(() => new Promise(() => undefined));
    const { result } = renderHook(() => useCapture(), { wrapper: wrap(new QueryClient()) });

    await act(async () => {
      void result.current.start(
        "p1",
        "Part One",
        ["altium_symbol", "altium_footprint", "kicad_model"],
        "ultralibrarian",
      );
      await Promise.resolve();
    });

    expect(run).toHaveBeenCalledWith(expect.objectContaining({
      vendor: "ultralibrarian",
      mode: "collect-all",
    }));
  });

  it("leaves EDA selection unset for legacy model-only capture", async () => {
    mockSource();
    const run = vi.spyOn(api, "runCapture").mockImplementation(() => new Promise(() => undefined));
    const { result } = renderHook(() => useCapture(), { wrapper: wrap(new QueryClient()) });

    await act(async () => {
      void result.current.start("p1", "Part One", ["kicad_model"]);
      await Promise.resolve();
    });

    expect(run).toHaveBeenCalledWith(expect.not.objectContaining({ edas: expect.anything() }));
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

  it("requestReopen hands the part id to the subscribed surface and unbackgrounds", async () => {
    mockSource();
    mockCapture();
    const { result } = renderHook(() => useCapture(), { wrapper: wrap(new QueryClient()) });

    await act(async () => {
      await result.current.start("p1", "One", ["kicad_symbol"]);
    });
    act(() => {
      result.current.keepWorking();
    });

    const opened: string[] = [];
    const unsubscribe = result.current.onReopen((partId) => opened.push(partId));

    act(() => {
      result.current.requestReopen();
    });
    // Delivered INSIDE the request, not on a later render. Read before any act() boundary could
    // flush an effect, which is what stops this from passing on a chain it was meant to remove.
    expect(opened).toEqual(["p1"]);
    expect(result.current.active.backgrounded).toBe(false);

    // The same part, twice. The latched id this replaced could not do it: the second request wrote
    // the value already held, so nothing downstream re-ran and the pill silently stopped working.
    act(() => {
      result.current.keepWorking();
    });
    act(() => {
      result.current.requestReopen();
    });
    expect(opened).toEqual(["p1", "p1"]);

    unsubscribe();
    act(() => {
      result.current.requestReopen();
    });
    expect(opened).toEqual(["p1", "p1"]);
  });

  it("holds a request made while no surface is subscribed, then spends it on the first one", async () => {
    mockSource();
    mockCapture();
    const { result } = renderHook(() => useCapture(), { wrapper: wrap(new QueryClient()) });

    await act(async () => {
      await result.current.start("p1", "One", ["kicad_symbol"]);
    });

    // What the capture pill does: it requests the reopen and navigates, so the Library page that
    // owns opening a part does not exist yet at the moment of the click.
    act(() => {
      result.current.requestReopen();
    });

    const first: string[] = [];
    result.current.onReopen((partId) => first.push(partId));
    expect(first).toEqual(["p1"]);

    // Spent, not latched: a page that mounts later must not reopen a part nobody asked for again.
    const second: string[] = [];
    result.current.onReopen((partId) => second.push(partId));
    expect(second).toEqual([]);
  });

  it("requestOpenFor delivers a part the capture never ran, for the intake continuation", async () => {
    mockSource();
    mockCapture();
    const { result } = renderHook(() => useCapture(), { wrapper: wrap(new QueryClient()) });

    const opened: string[] = [];
    result.current.onReopen((partId) => opened.push(partId));
    act(() => {
      result.current.requestOpenFor("freshly-added");
    });
    expect(opened).toEqual(["freshly-added"]);
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
          idempotencyKey: expect.stringMatching(/^guided-capture-/),
      }),
    );
    // and nothing reached for the host bridge that used to exist
    expect((window as { pywebview?: unknown }).pywebview).toBeUndefined();
  });

  it("a delayed capture submission cannot be replaced by another part", async () => {
    mockSource();
    const firstReference = new Promise<{
      workflow_batch_id: string;
      workflow_item_id: string;
      event_cursor: number;
    }>(() => undefined);
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

    const { result, unmount } = renderHook(() => useCapture(), {
      wrapper: wrap(new QueryClient()),
    });
    await act(async () => {
      void result.current.start("p1", "Part One", ["kicad_symbol"]);
      await Promise.resolve();
    });
    await expect(
      result.current.start("p2", "Part Two", ["kicad_symbol"]),
    ).rejects.toThrow("Finish the active completion for Part One");
    expect(result.current.active.partId).toBe("p1");
    expect(result.current.active.partName).toBe("Part One");
    expect(api.runCapture).toHaveBeenCalledTimes(1);
    expect(readUiSession().selected_ids.workflow_batch).toBeNull();
    unmount();
  });

  it("an error frame from the run surfaces as an error, never a silent done", async () => {
    mockSource(undefined, {
      needs: ["kicad_symbol"],
      completion_evidence: null,
    });
    mockCapture([
      { event: "error", data: { detail: "Ultra Librarian has no model for this part." } },
      { event: "done", data: {} },
    ]);
    const { result } = renderHook(() => useCapture(), { wrapper: wrap(new QueryClient()) });

    await act(async () => {
      await result.current.start("p1", "Part One", ["kicad_symbol"]);
    });

    expect(result.current.active.status).toBe("error");
    expect(result.current.active.message).toContain("CAD collection was interrupted");
    expect(result.current.active.message).toContain("retained evidence");
  });

  it("an unchanged completion report never reports verified completion", async () => {
    mockSource(undefined, {
      needs: ["kicad_symbol"],
      completion_evidence: null,
    });
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
    mockSource(undefined, { completion_evidence: null });
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
    mockSource(undefined, {
      completion_evidence: {
        state: "verified",
        manifest_digest: "sha256:not-canonical",
        reason: "The provider claimed verification.",
      },
    });
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
    mockSource(undefined, {
      completion_evidence: {
        state: "not-required",
        manifest_digest: null,
        reason: "This mechanical record has no EDA deliverables.",
      },
    });
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
    mockSource(undefined, {
      completion_evidence: {
        state: "unverified",
        manifest_digest: null,
        reason: "The active pointers did not match the retained manifest.",
      },
    });
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
    mockSource(undefined, {
      needs: ["kicad_symbol"],
      completion_evidence: null,
    });
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

  it("claims a saved workflow before reconnect I/O can submit a duplicate provider batch", async () => {
    const restored = defaultUiSession();
    restored.selected_ids.workflow_batch = "batch-restoring";
    restored.selected_ids.workflow_item = "item-restoring";
    restored.event_sequence = 3;
    resetUiSessionForTests(restored);

    vi.spyOn(api, "captureWorkflow").mockResolvedValue({
      workflow_batch_id: "batch-restoring",
      workflow_item_id: "item-restoring",
      part_id: "p1",
      vendor: "ultralibrarian",
      background: false,
      initial_needs: ["kicad_symbol"],
      report: null,
    } as never);
    let releaseDetail: (() => void) | null = null;
    vi.spyOn(api, "partDetail").mockImplementation(
      () =>
        new Promise((resolve) => {
          releaseDetail = () =>
            resolve({ id: "p1", derived: { display_name: "Part One" } } as never);
        }),
    );
    vi.spyOn(api, "workflowEvents").mockReturnValue(new Promise(() => undefined));
    const run = vi.spyOn(api, "runCapture");

    const { result } = renderHook(() => useCapture(), { wrapper: wrap(new QueryClient()) });

    // The durable identity read has not returned yet, but the slot is already owned. Before this
    // guard a provider click here created a second queued batch and replaced the saved id while the
    // first batch's native provider HWND remained hidden.
    expect(result.current.active.status).toBe("resolving");
    await expect(
      result.current.start("p2", "Part Two", ["kicad_symbol"]),
    ).rejects.toThrow("Finish the active completion");
    expect(run).not.toHaveBeenCalled();

    await act(async () => {
      releaseDetail?.();
      await Promise.resolve();
    });
    await waitFor(() => expect(result.current.active.partId).toBe("p1"));
    expect(result.current.active.status).toBe("receiving");
  });
});
