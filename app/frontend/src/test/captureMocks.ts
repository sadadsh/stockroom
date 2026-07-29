/**
 * Test doubles for the guided-capture route.
 *
 * Capture runs through `POST /api/library/capture/run` plus the job's SSE stream. These shared
 * doubles keep that one route consistent across the tests that exercise it.
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
  stream: ReturnType<typeof vi.spyOn>;
}

/**
 * Mock a capture run. By default it reports progress and finishes cleanly.
 *
 * `frames` overrides the stream so a test can drive the failure paths (an `error` frame) exactly
 * as the backend would, instead of asserting on a shape no server produces.
 */
export function mockCapture(
  frames?: { event: string; data: unknown }[],
): CaptureMock {
  let request: { partIds: string[]; needs?: string[] } | null = null;
  const run = vi.spyOn(api, "runCapture").mockImplementation(async (body) => {
    request = body as { partIds: string[]; needs?: string[] };
    return { job_id: "job-1" };
  });
  const stream = vi
    .spyOn(api, "openJobStream")
    .mockImplementation(async () => {
      const partId = request?.partIds[0] ?? "p1";
      const needs = request?.needs ?? ["kicad_symbol"];
      const emitted =
        frames ??
        [
          { event: "progress", data: { message: "Working through the vendor page." } },
          {
            event: "result",
            data: {
              result: {
                items: [
                  {
                    part_id: partId,
                    mpn: "M",
                    display_name: "Captured Part",
                    category: "ICs",
                    status: "completed",
                    needed: needs,
                    satisfied: needs,
                    remaining: [],
                    sources: ["ultralibrarian"],
                    notes: [],
                    error: "",
                  },
                ],
                counts: { completed: 1 },
                stopped: false,
                stop_reason: "",
              },
            },
          },
          { event: "done", data: {} },
        ];
      return sseStream(emitted) as never;
    });
  return { run, stream } as CaptureMock;
}
