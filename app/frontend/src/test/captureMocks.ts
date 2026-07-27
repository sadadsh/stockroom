/**
 * Test doubles for the guided-capture route.
 *
 * Capture used to run through `window.pywebview.api.open_cad_download`, so the tests mocked a
 * Windows-only host object. It now runs through `POST /api/library/capture/run` plus the job's SSE
 * stream - one path on Windows and Linux - so the doubles moved here, ONCE, rather than being
 * copied into each of the three test files that need them.
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
  frames: { event: string; data: unknown }[] = [
    { event: "progress", data: { message: "Working through the vendor page." } },
    { event: "result", data: { result: { counts: { completed: 1 } } } },
    { event: "done", data: {} },
  ],
): CaptureMock {
  const run = vi.spyOn(api, "runCapture").mockResolvedValue({ job_id: "job-1" });
  const stream = vi
    .spyOn(api, "openJobStream")
    .mockImplementation(async () => sseStream(frames) as never);
  return { run, stream } as CaptureMock;
}
