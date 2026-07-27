/**
 * Bulk-import job state, held OUTSIDE React so it survives the modal closing.
 *
 * WHY THIS EXISTS, and it is not a nicety. Importing the owner's Component Register is 166 parts
 * of real network work, about 25 minutes. `Import A List` lives inside the Add-A-Part dialog, so
 * with the state in `useState` the component unmounts the moment that dialog is dismissed - and
 * the run's REPORT, which is the entire point of a 25-minute job, is gone. The job itself keeps
 * running server-side; only the reader disappears. That is a result silently thrown away, which
 * is worse than a visible failure.
 *
 * PRIOR ART evaluated:
 * - `useJob` (this repo): ADOPTED in shape - the same submit-then-stream flow and the same
 *   terminal-event handling, including its honest "stream ended without a result" case. REJECTED
 *   as-is because its state is per-component `useState` by design, which is right for a lookup
 *   that takes two seconds and wrong for a job that outlives the surface that started it.
 * - TanStack Query's cache: REJECTED. It is a cache for FETCHED data keyed by input; a long
 *   streaming job with progress is not a query, and modelling it as one means fighting
 *   invalidation semantics for no gain.
 * - A state library (zustand/jotai): REJECTED. `useSyncExternalStore` is the React-native answer
 *   to exactly this and needs no dependency.
 *
 * The pasted text lives here too, so a 166-line paste is not lost by closing the dialog either.
 */
import { useSyncExternalStore } from "react";
import { api } from "../api/client";
import type { BulkImportResult } from "../api/types";
import type { JobProgress, JobStatus } from "./useJob";
import { streamEvents } from "./sse";

export interface BulkImportState {
  status: JobStatus;
  progress: JobProgress | null;
  result: BulkImportResult | null;
  error: string | null;
  /** What the user pasted, kept so closing the dialog does not discard a long list. */
  text: string;
  /** True when the finished run was a preview, so the report can say so. */
  wasDryRun: boolean;
}

const IDLE: BulkImportState = {
  status: "idle",
  progress: null,
  result: null,
  error: null,
  text: "",
  wasDryRun: false,
};

let state: BulkImportState = IDLE;
const listeners = new Set<() => void>();

function set(next: Partial<BulkImportState>): void {
  state = { ...state, ...next };
  for (const l of listeners) l();
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

function snapshot(): BulkImportState {
  return state;
}

export function setBulkImportText(text: string): void {
  set({ text });
}

export function resetBulkImport(): void {
  set({ status: "idle", progress: null, result: null, error: null, wasDryRun: false });
}

export interface BulkImportInput {
  text?: string;
  partNumbers?: string[];
  format?: "list" | "csv";
  dryRun?: boolean;
  category?: string;
}

/**
 * Start a run and stream it to completion. Returns the terminal state so a caller can act on the
 * outcome; the store is updated throughout either way, so a component that unmounted mid-run
 * finds the finished report waiting when it comes back.
 */
export async function startBulkImport(input: BulkImportInput): Promise<BulkImportState> {
  if (state.status === "running") return state;
  set({
    status: "running", progress: null, result: null, error: null,
    wasDryRun: Boolean(input.dryRun),
  });

  let ref: { job_id: string };
  try {
    ref = await api.bulkImport(input);
  } catch (err) {
    set({ status: "error", error: err instanceof Error ? err.message : "could not start the import" });
    return state;
  }

  let body: ReadableStream<Uint8Array>;
  try {
    body = await api.openJobStream(ref.job_id);
  } catch (err) {
    set({ status: "error", error: err instanceof Error ? err.message : "could not open the job stream" });
    return state;
  }

  // Tracked explicitly rather than read back off `state`: a terminal event is a FACT about the
  // stream, and inferring it from the store afterwards is the kind of indirect check that goes
  // wrong the moment anything else can write to the store.
  let sawTerminal = false;
  try {
    for await (const ev of streamEvents(body)) {
      if (ev.event === "progress") {
        set({ progress: ev.data as JobProgress });
      } else if (ev.event === "result") {
        sawTerminal = true;
        set({ status: "done", result: (ev.data as { result: BulkImportResult }).result });
      } else if (ev.event === "error") {
        sawTerminal = true;
        const detail = (ev.data as { detail?: string }).detail;
        set({ status: "error", error: detail ?? "the import failed" });
      } else if (ev.event === "done") {
        break;
      }
    }
  } catch (err) {
    set({ status: "error", error: err instanceof Error ? err.message : "the job stream broke" });
    return state;
  }
  // A clean EOF with no terminal event means the host dropped the stream. Never sit in "running"
  // forever on a job that will not report - say so (useJob's rule, kept).
  if (!sawTerminal) {
    set({ status: "error", error: "the import stream ended without a result" });
  }
  return state;
}

export function useBulkImportState(): BulkImportState {
  return useSyncExternalStore(subscribe, snapshot, snapshot);
}
