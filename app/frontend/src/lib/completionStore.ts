/**
 * Library completion state that survives navigation and prefers the durable
 * workflow authority whenever the backend returns a workflow batch.
 *
 * Durable work is replayed from a monotonic sequence cursor. The legacy
 * process-local SSE job remains only as a bounded compatibility seam while the
 * persistent Windows owner is being mounted.
 */
import { useSyncExternalStore } from "react";
import { api } from "../api/client";
import type {
  CompletionProgress,
  CompletionResult,
  WorkflowBatchSummary,
  WorkflowControlResult,
  WorkflowEvent,
} from "../api/types";
import type { JobStatus } from "./useJob";
import { streamEvents } from "./sse";

export type CompletionStatus = JobStatus | "paused" | "failed" | "cancelled";
export type CompletionTransport = "durable" | "legacy";
export type WorkflowControl = "pause" | "resume" | "retry" | "cancel";

export interface CompletionState {
  status: CompletionStatus;
  transport: CompletionTransport | null;
  progress: CompletionProgress | null;
  result: CompletionResult | null;
  error: string | null;
  /** Present only for the temporary process-local compatibility runner. */
  jobId: string | null;
  /** Present for the durable vNext authority and safe to reconnect after navigation/reload. */
  batchId: string | null;
  cursor: number;
  workflow: WorkflowBatchSummary | null;
  workflowLog: WorkflowEvent[];
  controlPending: WorkflowControl | null;
  /** True once legacy Stop has been sent. */
  stopping: boolean;
  /** Every part the legacy run has reported, newest first. */
  log: CompletionProgress[];
  /** Per-part legacy SSE outcomes folded incrementally. */
  live: CompletionLiveSummary;
}

export interface CompletionLiveSummary {
  processed: number;
  counts: Record<string, number>;
  retained: number;
}

const LOG_LIMIT = 300;
const LEGACY_FALLBACK_LIMIT = 1_000;
const EVENT_PAGE_LIMIT = 200;
const POLL_INTERVAL_MS = 750;
const RECONNECT_DELAYS_MS = [0, 250, 500, 1_000];
const SESSION_KEY = "stockroom.completion.workflow.v1";

function emptyLiveSummary(): CompletionLiveSummary {
  return { processed: 0, counts: {}, retained: 0 };
}

function idleState(): CompletionState {
  return {
    status: "idle",
    transport: null,
    progress: null,
    result: null,
    error: null,
    jobId: null,
    batchId: null,
    cursor: 0,
    workflow: null,
    workflowLog: [],
    controlPending: null,
    stopping: false,
    log: [],
    live: emptyLiveSummary(),
  };
}

let state: CompletionState = idleState();
const listeners = new Set<() => void>();
const liveOutcomes = new Map<string, { status: string; retained: number }>();
let followGeneration = 0;
let followPromise: Promise<CompletionState> | null = null;

function set(next: Partial<CompletionState>): void {
  state = { ...state, ...next };
  for (const listener of listeners) listener();
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

function snapshot(): CompletionState {
  return state;
}

function sessionStorageAvailable(): Storage | null {
  try {
    return typeof sessionStorage === "undefined" ? null : sessionStorage;
  } catch {
    return null;
  }
}

function persistCursor(batchId: string, cursor: number): void {
  sessionStorageAvailable()?.setItem(SESSION_KEY, JSON.stringify({ batchId, cursor }));
}

function clearCursor(): void {
  sessionStorageAvailable()?.removeItem(SESSION_KEY);
}

function savedCursor(): { batchId: string; cursor: number } | null {
  const raw = sessionStorageAvailable()?.getItem(SESSION_KEY);
  if (!raw) return null;
  try {
    const parsed = JSON.parse(raw) as { batchId?: unknown; cursor?: unknown };
    if (
      typeof parsed.batchId === "string" &&
      parsed.batchId.length > 0 &&
      parsed.batchId.length <= 128 &&
      Number.isSafeInteger(parsed.cursor) &&
      Number(parsed.cursor) >= 0
    ) {
      return { batchId: parsed.batchId, cursor: Number(parsed.cursor) };
    }
  } catch {
    // A malformed browser value has no authority. Drop it and start cleanly.
  }
  clearCursor();
  return null;
}

function completionStatus(batch: WorkflowBatchSummary): CompletionStatus {
  switch (batch.status) {
    case "paused":
      return "paused";
    case "completed":
      return "done";
    case "failed":
      return "failed";
    case "cancelled":
      return "cancelled";
    default:
      return "running";
  }
}

function isTerminal(batch: WorkflowBatchSummary): boolean {
  return ["completed", "failed", "cancelled"].includes(batch.status);
}

function mergeWorkflowEvents(events: WorkflowEvent[]): WorkflowEvent[] {
  const bySequence = new Map<number, WorkflowEvent>();
  for (const event of state.workflowLog) bySequence.set(event.sequence, event);
  for (const event of events) bySequence.set(event.sequence, event);
  return [...bySequence.values()]
    .sort((left, right) => right.sequence - left.sequence)
    .slice(0, LOG_LIMIT);
}

function delay(milliseconds: number): Promise<void> {
  if (milliseconds <= 0) return Promise.resolve();
  return new Promise((resolve) => setTimeout(resolve, milliseconds));
}

async function followDurableBatch(
  batchId: string,
  initialCursor: number,
  generation: number,
): Promise<CompletionState> {
  let cursor = initialCursor;
  let failures = 0;
  while (generation === followGeneration) {
    let page;
    try {
      page = await api.workflowEvents(batchId, cursor, EVENT_PAGE_LIMIT);
      failures = 0;
    } catch (error) {
      if (generation !== followGeneration) return state;
      if (failures >= RECONNECT_DELAYS_MS.length) {
        set({
          status: "error",
          error:
            error instanceof Error
              ? `Could not reconnect to the durable run: ${error.message}`
              : "Could not reconnect to the durable run.",
        });
        return state;
      }
      await delay(RECONNECT_DELAYS_MS[failures]);
      failures += 1;
      continue;
    }

    if (generation !== followGeneration) return state;
    cursor = Math.max(cursor, page.cursor.next_sequence);
    set({
      status: completionStatus(page.batch),
      workflow: page.batch,
      workflowLog: mergeWorkflowEvents(page.events),
      cursor,
      error: null,
    });
    persistCursor(batchId, cursor);

    if (page.cursor.has_more) continue;
    if (isTerminal(page.batch)) {
      if (page.batch.status !== "failed") clearCursor();
      return state;
    }
    await delay(POLL_INTERVAL_MS);
  }
  return state;
}

function beginFollowing(batchId: string, cursor: number): Promise<CompletionState> {
  if (followPromise && state.batchId === batchId) return followPromise;
  const generation = ++followGeneration;
  const running = followDurableBatch(batchId, cursor, generation);
  followPromise = running.finally(() => {
    if (generation === followGeneration) followPromise = null;
  });
  return followPromise;
}

export function resetCompletion(): void {
  followGeneration += 1;
  followPromise = null;
  liveOutcomes.clear();
  clearCursor();
  state = idleState();
  for (const listener of listeners) listener();
}

/** Recover a durable run after a full renderer reload. Navigation needs no call; module state lives. */
export function reconnectCompletion(): Promise<CompletionState> {
  if (state.transport === "durable" && state.batchId) {
    return beginFollowing(state.batchId, state.cursor);
  }
  if (state.status !== "idle") return Promise.resolve(state);
  const saved = savedCursor();
  if (!saved) return Promise.resolve(state);
  set({
    status: "running",
    transport: "durable",
    batchId: saved.batchId,
    cursor: saved.cursor,
    error: null,
  });
  return beginFollowing(saved.batchId, saved.cursor);
}

/** Ask the temporary legacy runner to stop at its next safe per-part boundary. */
export async function stopCompletion(): Promise<void> {
  const jobId = state.jobId;
  if (state.transport !== "legacy" || !jobId || state.status !== "running") {
    return;
  }
  set({ stopping: true });
  try {
    await api.stopJob(jobId);
  } catch {
    set({ stopping: false });
  }
}

async function applyWorkflowControl(operation: WorkflowControl): Promise<void> {
  const batchId = state.batchId;
  if (!batchId || state.transport !== "durable" || state.controlPending) return;
  set({ controlPending: operation, error: null });
  let result: WorkflowControlResult;
  try {
    if (operation === "pause") result = await api.workflowPause(batchId);
    else if (operation === "resume") result = await api.workflowResume(batchId);
    else if (operation === "retry") result = await api.workflowRetry(batchId);
    else result = await api.workflowCancel(batchId);
  } catch (error) {
    set({
      controlPending: null,
      error: error instanceof Error ? error.message : `Could not ${operation} the durable run.`,
    });
    return;
  }

  set({
    status: completionStatus(result.batch),
    workflow: result.batch,
    controlPending: null,
  });
  persistCursor(batchId, state.cursor);
  if (operation === "resume" || operation === "retry") {
    void beginFollowing(batchId, state.cursor);
  }
}

export const pauseCompletion = (): Promise<void> => applyWorkflowControl("pause");
export const resumeCompletion = (): Promise<void> => applyWorkflowControl("resume");
export const retryCompletion = (): Promise<void> => applyWorkflowControl("retry");
export const cancelCompletion = (): Promise<void> => applyWorkflowControl("cancel");

async function runLegacy(jobId: string): Promise<CompletionState> {
  set({
    transport: "legacy",
    jobId,
    batchId: null,
    workflow: null,
    workflowLog: [],
  });

  let body: ReadableStream<Uint8Array>;
  try {
    body = await api.openJobStream(jobId);
  } catch (error) {
    set({
      status: "error",
      error:
        error instanceof Error ? error.message : "Could not open the compatibility job stream.",
    });
    return state;
  }

  let sawTerminal = false;
  try {
    for await (const event of streamEvents(body)) {
      if (event.event === "progress") {
        const frame = event.data as CompletionProgress;
        const previous = liveOutcomes.get(frame.part_id);
        const counts = { ...state.live.counts };
        let processed = state.live.processed;
        let retained = state.live.retained;
        if (previous) {
          counts[previous.status] = Math.max(0, (counts[previous.status] ?? 0) - 1);
          retained = Math.max(0, retained - previous.retained);
        } else {
          processed += 1;
        }
        const nextRetained = frame.retained ?? 0;
        counts[frame.status] = (counts[frame.status] ?? 0) + 1;
        retained += nextRetained;
        liveOutcomes.set(frame.part_id, {
          status: frame.status,
          retained: nextRetained,
        });
        set({
          progress: frame,
          log: [frame, ...state.log.filter((entry) => entry.part_id !== frame.part_id)].slice(
            0,
            LOG_LIMIT,
          ),
          live: { processed, counts, retained },
        });
      } else if (event.event === "result") {
        sawTerminal = true;
        liveOutcomes.clear();
        set({
          status: "done",
          result: (event.data as { result: CompletionResult }).result,
          jobId: null,
          stopping: false,
        });
      } else if (event.event === "error") {
        sawTerminal = true;
        liveOutcomes.clear();
        const detail = (event.data as { detail?: string }).detail;
        set({
          status: "error",
          error: detail ?? "The compatibility run failed.",
          jobId: null,
          stopping: false,
        });
      } else if (event.event === "done") {
        break;
      }
    }
  } catch (error) {
    liveOutcomes.clear();
    set({
      status: "error",
      error: error instanceof Error ? error.message : "The compatibility job stream broke.",
      jobId: null,
      stopping: false,
    });
    return state;
  }
  if (!sawTerminal) {
    liveOutcomes.clear();
    set({
      status: "error",
      error: "The compatibility run ended without a result.",
      jobId: null,
      stopping: false,
    });
  }
  return state;
}

/**
 * Start one bounded completion batch. A durable reference wins when both
 * transports are present; this prevents dual readers and duplicate ownership.
 */
export async function startCompletion(
  input: { partIds?: string[]; limit?: number } = {},
): Promise<CompletionState> {
  if (state.status === "running" || state.status === "paused" || state.status === "failed") {
    return state;
  }
  followGeneration += 1;
  followPromise = null;
  liveOutcomes.clear();
  clearCursor();
  set({
    ...idleState(),
    status: "running",
  });

  const requestedLimit = Math.min(
    LEGACY_FALLBACK_LIMIT,
    Math.max(1, input.limit ?? LEGACY_FALLBACK_LIMIT),
  );
  let ref;
  try {
    ref = await api.runCompletion({ ...input, limit: requestedLimit });
  } catch (error) {
    set({
      status: "error",
      error: error instanceof Error ? error.message : "Could not start the completion run.",
    });
    return state;
  }

  if (ref.workflow_batch_id) {
    const cursor = ref.event_cursor ?? 0;
    set({
      transport: "durable",
      batchId: ref.workflow_batch_id,
      cursor,
      jobId: null,
    });
    persistCursor(ref.workflow_batch_id, cursor);
    return beginFollowing(ref.workflow_batch_id, cursor);
  }
  if (ref.job_id) return runLegacy(ref.job_id);

  set({
    status: "error",
    error: "The backend returned no durable batch or compatibility job.",
  });
  return state;
}

export function useCompletionState(): CompletionState {
  return useSyncExternalStore(subscribe, snapshot, snapshot);
}
