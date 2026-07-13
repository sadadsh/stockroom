/**
 * Run a backend job and expose its live state. A job is started elsewhere (e.g.
 * ingestInspect returns a job_id); `run(jobId)` opens the SSE stream through the
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

  const run = useCallback(async (jobId: string) => {
    setState({ status: "running", progress: null, result: null, error: null });
    let body: ReadableStream<Uint8Array>;
    try {
      body = await api.openJobStream(jobId);
    } catch (err) {
      setState({
        status: "error",
        progress: null,
        result: null,
        error: err instanceof Error ? err.message : "could not open the job stream",
      });
      return;
    }
    try {
      for await (const ev of streamEvents(body)) {
        if (ev.event === "progress") {
          const progress = ev.data as JobProgress;
          setState((s) => ({ ...s, progress }));
        } else if (ev.event === "result") {
          const result = (ev.data as { result: T }).result;
          setState((s) => ({ ...s, status: "done", result }));
        } else if (ev.event === "error") {
          const detail = (ev.data as { detail?: string }).detail;
          setState((s) => ({ ...s, status: "error", error: detail ?? "the job failed" }));
        } else if (ev.event === "done") {
          break;
        }
      }
    } catch (err) {
      setState((s) => ({
        ...s,
        status: "error",
        error: err instanceof Error ? err.message : "the job stream broke",
      }));
    }
  }, []);

  return { ...state, run, reset };
}
