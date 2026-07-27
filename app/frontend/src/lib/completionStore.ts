/**
 * Library-completion job state, held OUTSIDE React so it survives the surface that started it.
 *
 * WHY, and it is a stronger case than the bulk import's. A completion run is not minutes, it is
 * HOURS: at the measured catalogue pace (~8 parts a minute, forced by a WAF that blocks harder
 * pacing) a 10,000-part library is around 21 hours. Nobody is going to sit on the Settings page
 * for that, so the state cannot live in a component's `useState` -- the moment the user navigates
 * to Components the reader would unmount and the run's report, the entire point of the job, would
 * be gone. The job itself keeps running server-side either way; only the reader disappears.
 *
 * Deliberately the same shape as `bulkImportStore` rather than a cleverer one: two long-job
 * stores that behave differently is a trap for whoever debugs the second one. `useSyncExternalStore`
 * is React's own answer here and needs no dependency (zustand/jotai rejected for that reason;
 * TanStack Query rejected because a streaming job with progress is not a keyed fetch).
 *
 * The one thing this adds over the bulk store is the JOB ID, kept so Stop has something to send.
 */
import { useSyncExternalStore } from "react";
import { api } from "../api/client";
import type { CompletionProgress, CompletionResult } from "../api/types";
import type { JobStatus } from "./useJob";
import { streamEvents } from "./sse";

export interface CompletionState {
  status: JobStatus;
  progress: CompletionProgress | null;
  result: CompletionResult | null;
  error: string | null;
  /** The running job, so Stop can name it. Null unless a run is live. */
  jobId: string | null;
  /** True once Stop has been sent, so the button can say "Stopping" honestly. */
  stopping: boolean;
  /** Every part the run has reported, newest first, so a long run shows its work as it goes. */
  log: CompletionProgress[];
}

// A 10,000-part run would otherwise grow an unbounded array in the browser. The report from the
// terminal event is the complete record; this log is the live feed, so a window is enough.
const LOG_LIMIT = 300;

const IDLE: CompletionState = {
  status: "idle",
  progress: null,
  result: null,
  error: null,
  jobId: null,
  stopping: false,
  log: [],
};

let state: CompletionState = IDLE;
const listeners = new Set<() => void>();

function set(next: Partial<CompletionState>): void {
  state = { ...state, ...next };
  for (const l of listeners) l();
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

function snapshot(): CompletionState {
  return state;
}

export function resetCompletion(): void {
  set({ status: "idle", progress: null, result: null, error: null, jobId: null, stopping: false, log: [] });
}

/** Ask the running job to stop at its next safe point (between two parts, never inside one). */
export async function stopCompletion(): Promise<void> {
  const jobId = state.jobId;
  if (!jobId || state.status !== "running") return;
  set({ stopping: true });
  try {
    await api.stopJob(jobId);
  } catch {
    // A stop that cannot be delivered must not leave the button lying about what it did.
    set({ stopping: false });
  }
}

/**
 * Start a run and stream it to completion. Returns the terminal state; the store is updated
 * throughout either way, so a surface that unmounted mid-run finds the finished report waiting.
 */
export async function startCompletion(
  input: { partIds?: string[]; limit?: number } = {},
): Promise<CompletionState> {
  if (state.status === "running") return state;
  set({ status: "running", progress: null, result: null, error: null, stopping: false, log: [] });

  let ref: { job_id: string };
  try {
    ref = await api.runCompletion(input);
  } catch (err) {
    set({ status: "error", error: err instanceof Error ? err.message : "could not start the run" });
    return state;
  }
  set({ jobId: ref.job_id });

  let body: ReadableStream<Uint8Array>;
  try {
    body = await api.openJobStream(ref.job_id);
  } catch (err) {
    set({ status: "error", error: err instanceof Error ? err.message : "could not open the job stream" });
    return state;
  }

  // A FACT about the stream, tracked directly rather than inferred from the store afterwards.
  let sawTerminal = false;
  try {
    for await (const ev of streamEvents(body)) {
      if (ev.event === "progress") {
        const frame = ev.data as CompletionProgress;
        set({ progress: frame, log: [frame, ...state.log].slice(0, LOG_LIMIT) });
      } else if (ev.event === "result") {
        sawTerminal = true;
        set({
          status: "done",
          result: (ev.data as { result: CompletionResult }).result,
          jobId: null,
          stopping: false,
        });
      } else if (ev.event === "error") {
        sawTerminal = true;
        const detail = (ev.data as { detail?: string }).detail;
        set({ status: "error", error: detail ?? "the run failed", jobId: null, stopping: false });
      } else if (ev.event === "done") {
        break;
      }
    }
  } catch (err) {
    set({
      status: "error",
      error: err instanceof Error ? err.message : "the job stream broke",
      jobId: null,
      stopping: false,
    });
    return state;
  }
  // A clean EOF with no terminal event means the host dropped the stream. Never sit in "running"
  // forever on a job that will not report.
  if (!sawTerminal) {
    set({ status: "error", error: "the run ended without a result", jobId: null, stopping: false });
  }
  return state;
}

export function useCompletionState(): CompletionState {
  return useSyncExternalStore(subscribe, snapshot, snapshot);
}
