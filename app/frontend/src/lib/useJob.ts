/**
 * Run a backend job and expose its live state. A job is started elsewhere (e.g.
 * a network acquisition request returns a job_id); `run(jobId)` opens the SSE stream through the
 * fetch-based client (native EventSource cannot send the bearer token) and folds
 * progress / result / error events into React state. The stream always ends with a
 * `done` event, so the loop terminates cleanly on success or failure.
 */
import { useCallback, useState } from "react";
import { api } from "../api/client";
import { streamEvents } from "./sse";

export type JobStatus = "idle" | "running" | "done" | "error";

export interface JobProgress {
  pct?: number;
  message?: string;
  // The real pipeline phase (queued/fetching/rendering/extracting/validating), so the UI can
  // show honest per-stage loading instead of a bare spinner (spec section 8). Absent on jobs
  // that only report pct/message (e.g. bulk).
  stage?: string;
}

interface JobState<T> {
  status: JobStatus;
  progress: JobProgress | null;
  result: T | null;
  error: string | null;
}

const IDLE: JobState<never> = {
  status: "idle",
  progress: null,
  result: null,
  error: null,
};

export function useJob<T = unknown>() {
  const [state, setState] = useState<JobState<T>>(IDLE as JobState<T>);

  const reset = useCallback(() => setState(IDLE as JobState<T>), []);

  // Returns the TERMINAL state as well as setting it. A caller that needs to act on the result
  // (toast what was written, refetch a query) cannot read it off the hook afterwards: the `job`
  // object captured in its callback is the render-time snapshot, so `job.result` there is still
  // null. Handing the final state back is what lets the caller report what ACTUALLY happened
  // rather than the fact that a job was started.
  const run = useCallback(async (jobId: string): Promise<JobState<T>> => {
    let final: JobState<T> = { status: "running", progress: null, result: null, error: null };
    const settle = (next: JobState<T>): void => {
      // `run()` returns this exact terminal answer. Never derive it as a side effect inside a React
      // state updater: React 19 may batch that updater until after this async function returns.
      final = next;
      setState(next);
    };
    settle(final);
    let body: ReadableStream<Uint8Array>;
    try {
      body = await api.openJobStream(jobId);
    } catch (err) {
      settle({
        status: "error",
        progress: null,
        result: null,
        error: err instanceof Error ? err.message : "could not open the job stream",
      });
      return final;
    }
    try {
      for await (const ev of streamEvents(body)) {
        if (ev.event === "progress") {
          settle({ ...final, progress: ev.data as JobProgress });
        } else if (ev.event === "result") {
          settle({ ...final, status: "done", result: (ev.data as { result: T }).result });
        } else if (ev.event === "error") {
          const detail = (ev.data as { detail?: string }).detail;
          settle({ ...final, status: "error", error: detail ?? "the job failed" });
        } else if (ev.event === "done") {
          break;
        }
      }
    } catch (err) {
      settle({
        ...final,
        status: "error",
        error: err instanceof Error ? err.message : "the job stream broke",
      });
      return final;
    }
    // The stream ended cleanly but without a terminal result/error event (an
    // abnormal EOF: the sidecar died or the host dropped the SSE body). Do not sit
    // in "running" forever; surface an honest error instead.
    if (final.status === "running") {
      settle({ ...final, status: "error", error: "the job stream ended without a result" });
    }
    return final;
  }, []);

  // Submit a job and stream it as one call, so a POST failure (the submit itself) lands in
  // the same job state as a stream failure. The submitter returns the job ref; we flip to
  // running immediately (the spinner shows during the submit too), then hand off to run().
  const start = useCallback(
    async (submit: () => Promise<{ job_id: string }>): Promise<JobState<T>> => {
      setState({ status: "running", progress: null, result: null, error: null });
      let ref: { job_id: string };
      try {
        ref = await submit();
      } catch (err) {
        const failed: JobState<T> = {
          status: "error",
          progress: null,
          result: null,
          error: err instanceof Error ? err.message : "could not start the job",
        };
        setState(failed);
        return failed;
      }
      return run(ref.job_id);
    },
    [run],
  );

  return { ...state, run, start, reset };
}
