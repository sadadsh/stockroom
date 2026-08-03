/**
 * Test doubles for the guided-capture route.
 *
 * Capture runs through a durable workflow submission, event cursor, and
 * terminal report projection. These doubles keep that reconnectable contract
 * consistent across the tests that exercise it.
 */
import { vi } from "vitest";
import { api } from "../api/client";

/** An SSE body carrying the frames a real job emits, in order. */
export function sseStream(frames: { event: string; data: unknown }[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder();
  return new ReadableStream<Uint8Array>({
    start(controller) {
      for (const frame of frames) {
        controller.enqueue(
          encoder.encode(`event: ${frame.event}\ndata: ${JSON.stringify(frame.data)}\n\n`),
        );
      }
      controller.close();
    },
  });
}

export interface CaptureMock {
  run: ReturnType<typeof vi.spyOn>;
  events: ReturnType<typeof vi.spyOn>;
  session: ReturnType<typeof vi.spyOn>;
  /** Legacy seam spy: durable UI tests require that it remains unused. */
  stream: ReturnType<typeof vi.spyOn>;
}

/**
 * Mock a durable capture run. By default it publishes one verified result.
 *
 * `frames` preserves the earlier fixture input shape while translating its
 * terminal result/error into the durable batch and report projections.
 */
export function mockCapture(
  frames?: { event: string; data: unknown }[],
): CaptureMock {
  type Request = {
    partIds?: string[];
    vendor?: string;
    mode?: "automatic" | "assisted" | "finish-first" | "collect-all";
  };
  type Run = {
    request: Request;
    report: Record<string, unknown> | null;
    failed: boolean;
  };

  let counter = 0;
  const runs = new Map<string, Run>();
  const run = vi.spyOn(api, "runCapture").mockImplementation(async (body) => {
    counter += 1;
    const request = body as Request;
    const partId = request.partIds?.[0] ?? "p1";
    const suppliedResult = frames?.find((frame) => frame.event === "result")?.data as
      | { result?: Record<string, unknown> }
      | undefined;
    const failed = Boolean(frames?.some((frame) => frame.event === "error"));
    const report =
      suppliedResult?.result ??
      (failed
        ? null
        : {
            items: [
              {
                part_id: partId,
                mpn: "M",
                display_name: "Captured Part",
                category: "ICs",
                status: "completed",
                needed: ["kicad_symbol"],
                satisfied: ["kicad_symbol"],
                remaining: [],
                sources: ["ultralibrarian"],
                notes: [],
                error: "",
                collection_complete: true,
                completion_evidence: {
                  state: "verified",
                  manifest_digest:
                    "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                  reason: "The active CAD package was reverified from this immutable manifest.",
                },
              },
            ],
            counts: { completed: 1 },
            collection_complete: true,
            stopped: false,
            stop_reason: "",
          });
    const batchId = `batch-capture-mock-${counter}`;
    runs.set(batchId, { request, report, failed });
    return {
      workflow_batch_id: batchId,
      workflow_item_id: `item-capture-mock-${counter}`,
      event_cursor: 0,
    };
  });
  const events = vi.spyOn(api, "workflowEvents").mockImplementation(async (batchId) => {
    const captured = runs.get(batchId);
    if (!captured) throw new Error("unknown mocked capture batch");
    const publishedItem = (
      captured.report as {
        items?: Array<{
          mpn?: string;
          remaining?: string[];
          completion_evidence?: unknown;
        }>;
      } | null
    )?.items?.[0];
    if (!captured.failed && publishedItem) {
      // A completed production workflow publishes before the terminal event becomes visible.
      // Mirror that canonical readback; the UI deliberately ignores the staging report as a
      // completion authority. Failed workflows leave the caller's existing projection untouched.
      vi.mocked(api.partCadSource).mockResolvedValue({
        url: null,
        mpn: publishedItem.mpn ?? "M",
        vendor: null,
        needs: publishedItem.remaining ?? [],
        sources: [],
        completion_evidence: publishedItem.completion_evidence ?? null,
      } as never);
    }
    return {
      schema_version: 1,
      batch: {
        id: batchId,
        kind: "guided_capture",
        status: captured.failed ? "failed" : "completed",
        created_at: 1,
        updated_at: 2,
        total_items: 1,
        item_counts: { [captured.failed ? "failed" : "completed"]: 1 },
        cancellation: null,
        actions: {
          can_pause: false,
          can_resume: false,
          can_retry: captured.failed,
          can_cancel: captured.failed,
        },
      },
      events: [
        {
          sequence: 1,
          item_id: null,
          stage_id: null,
          kind: captured.failed ? "stage_failed" : "publication_completed",
          details: { stage: captured.failed ? "cad_acquisition" : "publish" },
          created_at: 2,
        },
      ],
      cursor: {
        after_sequence: 0,
        next_sequence: 1,
        limit: 200,
        has_more: false,
      },
    };
  });
  const session = vi.spyOn(api, "captureWorkflow").mockImplementation(async (batchId) => {
    const captured = runs.get(batchId);
    if (!captured) throw new Error("unknown mocked capture batch");
    const item = (
      captured.report as { items?: Array<{ needed?: string[] }> } | null
    )?.items?.[0];
    const segments = batchId.split("-");
    const suffix = segments[segments.length - 1] ?? "1";
    return {
      workflow_batch_id: batchId,
      workflow_item_id: `item-capture-mock-${suffix}`,
      part_id: captured.request.partIds?.[0] ?? "p1",
      mode: captured.request.mode ?? "automatic",
      vendor: captured.request.vendor ?? null,
      background: false,
      initial_needs: (item?.needed ?? ["kicad_symbol"]) as never,
      report: captured.report as never,
    };
  });
  const stream = vi.spyOn(api, "openJobStream");
  return { run, events, session, stream } as CaptureMock;
}
