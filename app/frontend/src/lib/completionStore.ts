/**
 * Library completion state that survives navigation through the durable
 * workflow authority.
 *
 * Work is replayed from a monotonic sequence cursor. A standalone backend may
 * still expose its bounded process-local job API for source-level development,
 * but the desktop UI deliberately refuses that reference: a run that cannot
 * reconnect after a renderer or host restart is not a valid Library run.
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
import { readUiSession, updateUiSession } from "./uiSession";

export type CompletionStatus = JobStatus | "paused" | "failed" | "cancelled";
export type CompletionTransport = "durable";
export type WorkflowControl = "pause" | "resume" | "retry" | "cancel";

export interface CompletionState {
  status: CompletionStatus;
  transport: CompletionTransport | null;
  progress: CompletionProgress | null;
  result: CompletionResult | null;
  error: string | null;
  /** Durable authority, safe to reconnect after navigation, reload, and host replacement. */
  batchId: string | null;
  cursor: number;
  workflow: WorkflowBatchSummary | null;
  workflowLog: WorkflowEvent[];
  controlPending: WorkflowControl | null;
  /** Kept for the shared presentation contract; process-local Stop is never used here. */
  stopping: boolean;
  /** Empty for durable runs; item projections come from the workflow authority. */
  log: CompletionProgress[];
  /** Empty for durable runs; retained for the existing presentation contract. */
  live: CompletionLiveSummary;
}

export interface CompletionLiveSummary {
  processed: number;
  counts: Record<string, number>;
  retained: number;
}

const LOG_LIMIT = 300;
const MAX_COMPLETION_BATCH = 1_000;
const EVENT_PAGE_LIMIT = 200;
const POLL_INTERVAL_MS = 750;
const RECONNECT_DELAYS_MS = [0, 250, 500, 1_000];
const UNSUPPORTED_RUNTIME =
  "This Stockroom runtime returned only a process-local completion job. " +
  "Stockroom will not follow work that can be lost on restart. Restart or update the Windows app.";

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
let followGeneration = 0;
let followPromise: Promise<CompletionState> | null = null;
let pendingStart:
  | {
      commandKey: string;
      promise: Promise<CompletionState>;
    }
  | null = null;
let retrySubmission:
  | {
      commandKey: string;
      idempotencyKey: string;
    }
  | null = null;

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

function persistCursor(batchId: string, cursor: number): void {
  const current = readUiSession();
  if (
    current.selected_ids.workflow_batch === batchId &&
    current.event_sequence === cursor
  ) {
    return;
  }
  updateUiSession((snapshot) => ({
    ...snapshot,
    selected_ids: {
      ...snapshot.selected_ids,
      workflow_batch: batchId,
      workflow_item: null,
    },
    event_sequence: cursor,
  }));
}

function clearCursor(): void {
  const current = readUiSession();
  if (
    current.selected_ids.workflow_batch === null &&
    current.event_sequence === 0
  ) {
    return;
  }
  updateUiSession((snapshot) => ({
    ...snapshot,
    selected_ids: {
      ...snapshot.selected_ids,
      workflow_batch: null,
      workflow_item: null,
    },
    event_sequence: 0,
  }));
}

function savedCursor(): { batchId: string; cursor: number } | null {
  const snapshot = readUiSession();
  const batchId = snapshot.selected_ids.workflow_batch;
  if (!batchId || snapshot.selected_ids.workflow_item !== null) return null;
  return { batchId, cursor: snapshot.event_sequence };
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
  pendingStart = null;
  retrySubmission = null;
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

/** Compatibility export for the existing surface; durable runs use Cancel instead of Stop. */
export async function stopCompletion(): Promise<void> {
  return Promise.resolve();
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

function submissionKey(): string {
  return `library-completion-${globalThis.crypto.randomUUID()}`;
}

function commandKey(input: { partIds?: string[]; limit: number }): string {
  return JSON.stringify({
    part_ids: input.partIds ?? null,
    limit: input.limit,
  });
}

/**
 * Start one bounded durable completion batch.
 *
 * A saved cursor always reconnects before a new command is considered. The
 * idempotency key is retained across a failed response so retrying the same
 * command cannot create a second durable batch after an ambiguous disconnect.
 */
async function startCompletionCommand(
  input: { partIds?: string[]; limit?: number },
  requestedLimit: number,
  requestedCommand: string,
): Promise<CompletionState> {
  const saved = savedCursor();
  if (saved) return reconnectCompletion();
  if (state.status === "running" || state.status === "paused" || state.status === "failed") {
    return state;
  }
  followGeneration += 1;
  followPromise = null;
  clearCursor();
  set({
    ...idleState(),
    status: "running",
  });

  const idempotencyKey =
    retrySubmission?.commandKey === requestedCommand
      ? retrySubmission.idempotencyKey
      : submissionKey();
  retrySubmission = { commandKey: requestedCommand, idempotencyKey };
  let ref;
  try {
    ref = await api.runCompletion({
      ...input,
      limit: requestedLimit,
      idempotencyKey,
    });
  } catch (error) {
    set({
      status: "error",
      error: error instanceof Error ? error.message : "Could not start the completion run.",
    });
    return state;
  }

  if (ref.workflow_batch_id) {
    const cursor = ref.event_cursor ?? 0;
    retrySubmission = null;
    set({
      transport: "durable",
      batchId: ref.workflow_batch_id,
      cursor,
    });
    persistCursor(ref.workflow_batch_id, cursor);
    return beginFollowing(ref.workflow_batch_id, cursor);
  }

  set({
    status: "error",
    transport: null,
    batchId: null,
    error: ref.job_id
      ? UNSUPPORTED_RUNTIME
      : "The backend returned no durable workflow batch. Completion was not started.",
  });
  return state;
}

export function startCompletion(
  input: { partIds?: string[]; limit?: number } = {},
): Promise<CompletionState> {
  const requestedLimit = Math.min(
    MAX_COMPLETION_BATCH,
    Math.max(1, input.limit ?? MAX_COMPLETION_BATCH),
  );
  const requestedCommand = commandKey({ ...input, limit: requestedLimit });
  if (pendingStart?.commandKey === requestedCommand) return pendingStart.promise;

  const promise = startCompletionCommand(input, requestedLimit, requestedCommand);
  const active = { commandKey: requestedCommand, promise };
  pendingStart = active;
  void promise.finally(() => {
    if (pendingStart === active) pendingStart = null;
  });
  return promise;
}

export function useCompletionState(): CompletionState {
  return useSyncExternalStore(subscribe, snapshot, snapshot);
}
