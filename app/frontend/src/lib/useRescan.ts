/**
 * Run the library-wide procurement rescan (Phase-1b-3) and expose its live state. Mirrors
 * useJob's SSE plumbing (the same api.openJobStream + streamEvents primitives, the same
 * open-failure / mid-stream-error / abnormal-EOF handling) but folds a RUNNING TALLY instead
 * of a single latest-progress snapshot: the rescan engine emits one progress event per part
 * (done/total/part_id/outcome), plus an occasional warn-level event ahead of a failed
 * lookup's own event, so a plain "keep only the latest event" state would lose every earlier
 * part's outcome. This hook accumulates them into updated/unchanged/no_data/failed counters
 * the panel renders live, the way the backend's own summary dict does server-side.
 *
 * A rescan already in flight (POST /api/library/rescan returns already_running: true) is
 * attached to exactly like a freshly started one: start() still calls run(job_id), which
 * just opens that job's SSE stream from wherever it currently is - no special-casing needed
 * beyond reporting already_running back to the caller so it can say so.
 */
import { useCallback, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import type { RescanSummary } from "../api/types";
import { streamEvents } from "./sse";

export type RescanStatus = "idle" | "running" | "done" | "error";

export interface RescanTally {
  done: number;
  total: number;
  updated: number;
  unchanged: number;
  no_data: number;
  failed: number;
}

const EMPTY_TALLY: RescanTally = {
  done: 0,
  total: 0,
  updated: 0,
  unchanged: 0,
  no_data: 0,
  failed: 0,
};

// The raw shape of a rescan job's `progress` event data (stockroom.enrich.rescan.RescanEngine).
// The first event carries done/total/message with no part_id; each per-part event carries
// done/total/part_id/outcome; a failed part additionally emits ONE extra warn-level event
// first (part_id + message, no outcome) before its own done/total/part_id/outcome="failed".
interface RescanProgressEvent {
  pct?: number;
  done?: number;
  total?: number;
  part_id?: string;
  outcome?: "updated" | "unchanged" | "no_data" | "failed";
  message?: string;
  level?: "warn";
}

interface RescanHookState {
  status: RescanStatus;
  tally: RescanTally;
  currentPartId: string | null;
  startMessage: string | null;
  summary: RescanSummary | null;
  error: string | null;
}

const IDLE_STATE: RescanHookState = {
  status: "idle",
  tally: EMPTY_TALLY,
  currentPartId: null,
  startMessage: null,
  summary: null,
  error: null,
};

function errMsg(err: unknown, fallback: string): string {
  return err instanceof Error ? err.message : fallback;
}

export function useRescan() {
  const [state, setState] = useState<RescanHookState>(IDLE_STATE);
  const qc = useQueryClient();

  const run = useCallback(
    async (jobId: string) => {
      let body: ReadableStream<Uint8Array>;
      try {
        body = await api.openJobStream(jobId);
      } catch (err) {
        setState((s) => ({
          ...s,
          status: "error",
          error: errMsg(err, "Could not open the rescan stream."),
        }));
        return;
      }
      try {
        for await (const ev of streamEvents(body)) {
          if (ev.event === "progress") {
            const p = ev.data as RescanProgressEvent;
            setState((s) => {
              const tally = { ...s.tally };
              if (p.total != null) tally.total = p.total;
              if (p.done != null) tally.done = p.done;
              if (p.outcome) tally[p.outcome] += 1;
              return {
                ...s,
                tally,
                currentPartId: p.part_id ?? s.currentPartId,
                // Only the very first event (before any part has been touched) carries the
                // "N parts to refresh" line; keep that one line stable for the whole run
                // rather than letting a later per-part / warn message overwrite it.
                startMessage: p.part_id ? s.startMessage : (p.message ?? s.startMessage),
              };
            });
          } else if (ev.event === "result") {
            const summary = (ev.data as { result: RescanSummary }).result;
            setState((s) => ({ ...s, status: "done", summary }));
            // The job just changed the on-disk rescan state; refetch it so the idle "last
            // refreshed" summary is current the next time this panel is shown fresh.
            qc.invalidateQueries({ queryKey: ["rescan-state"] });
          } else if (ev.event === "error") {
            const detail = (ev.data as { detail?: string }).detail;
            setState((s) => ({ ...s, status: "error", error: detail ?? "The rescan failed." }));
          } else if (ev.event === "done") {
            break;
          }
        }
      } catch (err) {
        setState((s) => ({
          ...s,
          status: "error",
          error: errMsg(err, "The rescan stream broke."),
        }));
        return;
      }
      // The stream ended cleanly but without a terminal result/error event (an abnormal
      // EOF). Do not sit in "running" forever; surface an honest error instead.
      setState((s) =>
        s.status === "running"
          ? { ...s, status: "error", error: "The rescan stream ended without a result." }
          : s,
      );
    },
    [qc],
  );

  // Starts a fresh rescan (or attaches to one already running). Fire-and-forget on the
  // stream itself (mirrors the ProjectsPage/IngestPage job-trigger convention): the returned
  // promise resolves as soon as the POST does, so the caller can toast about already_running
  // without waiting for the whole run to finish.
  const start = useCallback(
    async (force = false): Promise<{ already_running: boolean } | undefined> => {
      setState({ ...IDLE_STATE, status: "running" });
      let ref: { job_id: string; already_running?: boolean };
      try {
        ref = await api.rescanLibrary(force);
      } catch (err) {
        const message = errMsg(err, "Could not start the rescan.");
        setState((s) => ({ ...s, status: "error", error: message }));
        // Re-thrown (not just folded into state) so the caller can toast the SAME message
        // right away without racing this hook's own re-render (a stale-closure read of
        // `error` off the pre-update state would miss it).
        throw err instanceof Error ? err : new Error(message);
      }
      run(ref.job_id);
      return { already_running: !!ref.already_running };
    },
    [run],
  );

  return { ...state, start };
}
