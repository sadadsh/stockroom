/**
 * One global network-capture job.
 *
 * The backend owns discovery, the provider window, download capture, validation, retention, and
 * coherent attachment. The PERSON owns the provider page itself: they sign in if the provider
 * asks, choose the formats, and download. There is exactly one lane, so this store carries no
 * mode and the run request sends none. The frontend starts that job and renders its evidenced
 * result. A native file picker can recover downloads for the active provider task, but it feeds
 * the same backend validation path; there is still no per-tool attach seam or client-side commit
 * authority.
 */
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { useQueryClient } from "@tanstack/react-query";
import { api, ApiError } from "../api/client";
import { invalidatePartCadProjection } from "../api/partCadProjectionQueries";
import type {
  CompletionEvidence,
  CompletionResult,
  CadSourceResponse,
  Requirement,
  WorkflowBatchSummary,
  WorkflowEvent,
} from "../api/types";
import { readUiSession, updateUiSession } from "./uiSession";
import {
  CaptureBusyError,
  captureInFlight,
  REQ_LABELS,
  type CaptureState,
} from "./captureRequirements";

const IDLE: CaptureState = {
  partId: null,
  workflowItemId: null,
  partName: null,
  status: "idle",
  message: null,
  url: null,
  routeToken: null,
  vendor: null,
  needs: [],
  received: {},
  backgrounded: false,
  providerOutcomes: [],
  completionEvidence: null,
  completionEvidenceReported: false,
};

const EVENT_PAGE_LIMIT = 200;
const POLL_INTERVAL_MS = 750;
const UNSUPPORTED_DURABLE_RUNTIME =
  "This Stockroom runtime returned only a process-local capture job. " +
  "Stockroom will not follow work that can be lost on restart. Restart or update the Windows app.";

class UnsupportedDurableRuntimeError extends Error {
  constructor() {
    super(UNSUPPORTED_DURABLE_RUNTIME);
    this.name = "UnsupportedDurableRuntimeError";
  }
}

function submissionKey(): string {
  return `guided-capture-${globalThis.crypto.randomUUID()}`;
}

function captureCommandKey(partId: string, sourceKey: string | undefined): string {
  return JSON.stringify({
    part_id: partId,
    provider: sourceKey || null,
  });
}

function persistWorkflow(batchId: string, itemId: string, cursor: number): void {
  const current = readUiSession();
  if (
    current.selected_ids.workflow_batch === batchId &&
    current.selected_ids.workflow_item === itemId &&
    current.event_sequence === cursor
  ) {
    return;
  }
  updateUiSession((snapshot) => ({
    ...snapshot,
    selected_ids: {
      ...snapshot.selected_ids,
      workflow_batch: batchId,
      workflow_item: itemId,
    },
    event_sequence: cursor,
  }));
}

function clearWorkflow(batchId: string): void {
  const current = readUiSession();
  if (current.selected_ids.workflow_batch !== batchId) return;
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

function savedWorkflow(): { batchId: string; itemId: string; cursor: number } | null {
  const snapshot = readUiSession();
  const batchId = snapshot.selected_ids.workflow_batch;
  const itemId = snapshot.selected_ids.workflow_item;
  if (!batchId || !itemId) return null;
  return { batchId, itemId, cursor: snapshot.event_sequence };
}

function delay(milliseconds: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, milliseconds));
}

function terminalWorkflow(batch: WorkflowBatchSummary): boolean {
  // A blocked guided-capture batch has finished every automatic stage it can
  // perform without a person-driven provider handoff. Leaving it non-terminal
  // traps the modal in `window-open` forever even though no embedded provider page was
  // opened, which disables Get Files. Consume
  // its durable report and return an actionable partial result instead.
  //
  // `paused` is terminal for this poll for the same reason.  Pause is a first-class batch
  // state a person can resume from the completion surface, so treating it as still-running
  // left the modal polling every 750 ms forever with `cadBusy` stuck true, which disabled
  // Get Files with no way back short of relaunching the app.
  return ["completed", "blocked", "failed", "cancelled", "paused"].includes(
    batch.status,
  );
}

const WORKFLOW_STAGE_MESSAGE: Record<string, string> = {
  identity_dedupe: "Confirming the exact manufacturer and part number.",
  metadata: "Keeping the best existing facts and filling missing part data.",
  datasheet: "Finding and verifying the manufacturer datasheet.",
  existing_evidence: "Checking saved CAD evidence before asking you to download anything again.",
  cad_acquisition:
    "Open the provider page, sign in if it asks, choose the formats you need, and download.",
  reconcile: "Reconciling the accepted sources into one canonical part.",
  canonical_definition: "Building the shared component definition.",
  template_generation: "Preparing equivalent KiCad and Altium inputs.",
  native_conversion_acquisition: "Converting and validating the native CAD files.",
  kicad_build_readback: "Opening the generated KiCad package for readback.",
  altium_build_readback: "Opening the generated Altium package for readback.",
  cross_eda_verification: "Checking KiCad and Altium describe the same physical part.",
  catalog_link_generation: "Linking the verified files into the component catalog.",
  publish: "Publishing the complete package atomically.",
};

const WORKFLOW_STAGE_FAILURE_MESSAGE: Record<string, string> = {
  identity_dedupe:
    "The part identity changed before completion could start. Refresh the part, then select Get Files again.",
  metadata:
    "Part data collection stopped. Select Get Files again; Stockroom will reuse retained evidence.",
  datasheet:
    "Datasheet collection stopped. Select Get Files again; Stockroom will reuse retained evidence.",
  existing_evidence:
    "Saved CAD evidence could not be read safely. Select Get Files again to recheck the retained files.",
  cad_acquisition:
    "CAD collection was interrupted. Select Get Files again; Stockroom will resume from retained evidence.",
  reconcile:
    "The collected sources could not be reconciled into one component. Select Get Files again to retry from retained evidence.",
  canonical_definition:
    "The shared component definition could not be built. Select Get Files again to retry from retained evidence.",
  template_generation:
    "The KiCad and Altium inputs could not be prepared. Select Get Files again to retry from retained evidence.",
  native_conversion_acquisition:
    "Native CAD conversion stopped. Select Get Files again; downloaded evidence will be reused.",
  kicad_build_readback:
    "KiCad readback could not verify the generated package. Select Get Files again to retry from retained evidence.",
  altium_build_readback:
    "Altium readback could not verify the generated package. Select Get Files again to retry from retained evidence.",
  cross_eda_verification:
    "KiCad and Altium could not be verified as the same component. Select Get Files again to retry from retained evidence.",
  catalog_link_generation:
    "The verified files could not be linked into the component catalog. Select Get Files again to retry publication.",
  publish:
    "The verified package could not be published to the library. Select Get Files again to retry publication from retained evidence.",
};

function latestEventStage(events: WorkflowEvent[], kind?: string): string | null {
  const newestFirst = [...events].sort((left, right) => right.sequence - left.sequence);
  for (const event of newestFirst) {
    const stage = event.details.stage;
    if ((kind === undefined || event.kind === kind) && typeof stage === "string") {
      return stage;
    }
  }
  return null;
}

function durableMessage(
  batch: WorkflowBatchSummary,
  events: WorkflowEvent[],
  _vendor: string | null,
): string {
  if (batch.status === "paused") {
    return "Completion is paused. Resume it from Library Completion when you are ready.";
  }
  if (batch.status === "blocked") {
    return (
      "Collection stopped before a complete CAD package was available. Clear the provider gate, " +
      "then select Get Files again; Stockroom will reuse the retained evidence."
    );
  }
  if (batch.status === "cancelled") return "Completion was cancelled before publication.";
  if (batch.status === "failed") {
    const failedStage = latestEventStage(events, "stage_failed");
    return failedStage
      ? (WORKFLOW_STAGE_FAILURE_MESSAGE[failedStage] ??
          "Completion stopped at a recorded workflow stage. Select Get Files again; Stockroom will reuse retained evidence.")
      : "Completion was interrupted. Select Get Files again; Stockroom will reuse retained evidence.";
  }
  if (batch.status === "completed") {
    return "Part data, datasheet, KiCad, Altium, and STEP are verified and linked.";
  }
  const latestStage = latestEventStage(events);
  if (latestStage === "cad_acquisition") {
    return (
      "Open the provider page, sign in if it asks, choose the formats you need, and download. " +
      "Stockroom captures each download and validates it."
    );
  }
  return latestStage
    ? (WORKFLOW_STAGE_MESSAGE[latestStage] ?? "Completing this part.")
    : "Completion is active. Stockroom is checking saved evidence and exact identity before opening the provider page.";
}

function resultFromCanonicalProjection(
  partId: string,
  partName: string,
  initialNeeds: Requirement[],
  source: CadSourceResponse,
  diagnosticReport: CompletionResult | null = null,
): CompletionResult {
  const remaining = [...source.needs];
  const satisfied = initialNeeds.filter((value) => !remaining.includes(value));
  const evidence = source.completion_evidence ?? null;
  const complete =
    remaining.length === 0 &&
    (evidence?.state === "verified" || evidence?.state === "not-required");
  const diagnosticItem = diagnosticReport?.items.find(
    (candidate) => candidate.part_id === partId,
  );
  return {
    items: [
      {
        part_id: partId,
        mpn: source.mpn,
        display_name: partName,
        category: "",
        status: complete ? "completed" : satisfied.length > 0 ? "improved" : "unchanged",
        needed: initialNeeds,
        satisfied,
        remaining,
        // Provider outcomes explain what the acquisition pass attempted, but never decide whether
        // the library is complete. Only the canonical post-workflow readback above has that
        // authority; a staging report may exist even when later publication fails.
        sources: diagnosticItem?.sources ?? [],
        notes: diagnosticItem?.notes ?? [],
        error: diagnosticItem?.error ?? "",
        provider_outcomes: diagnosticItem?.provider_outcomes ?? [],
        collection_complete: diagnosticItem?.collection_complete ?? null,
        completion_evidence: evidence,
      },
    ],
    counts: { [complete ? "completed" : satisfied.length > 0 ? "improved" : "unchanged"]: 1 },
    retained: 0,
    collection_complete: null,
    stopped: false,
    stop_reason: "",
  };
}

export interface CaptureApi {
  active: CaptureState;
  start: (
    partId: string,
    partName: string,
    needs: Requirement[],
    sourceKey?: string,
  ) => Promise<void>;
  reset: () => void;
  keepWorking: () => void;
  showProvider: () => Promise<void>;
  /**
   * Register the surface that owns opening a part, and get its unsubscribe back.
   *
   * A CALLBACK rather than a `reopenPartId` value on this object, and the difference is not
   * cosmetic. The latched id made the reopen a two-step: the click wrote state here, a render
   * later the Library page's effect read it and moved the selection, and moving the selection woke
   * the auto-select effect beside it - three renders and a chain of effects for one click, where
   * the request had been known all along inside the click itself. It also could not deliver the
   * SAME part twice, because the second request wrote the id the latch already held, so no effect
   * re-ran and the pill simply stopped working; and nothing ever cleared the latch.
   */
  onReopen: (handler: (partId: string) => void) => () => void;
  requestReopen: () => void;
  requestOpenFor: (partId: string) => void;
}

const CaptureContext = createContext<CaptureApi | null>(null);

function errorMessage(error: unknown, fallback: string): string {
  return error instanceof Error ? error.message : fallback;
}

function verifiedManifest(evidence: CompletionEvidence | null): string | null {
  if (evidence?.state !== "verified") return null;
  const digest = evidence.manifest_digest?.trim() ?? "";
  return /^sha256:[0-9a-f]{64}$/.test(digest) ? digest : null;
}

function completionEvidenceMessage(evidence: CompletionEvidence | null): string {
  const reason = evidence?.reason.trim() ?? "";
  if (!evidence) {
    return "Capture finished without completion evidence. Stockroom did not mark the files complete.";
  }
  if (evidence.state === "verified" && !verifiedManifest(evidence)) {
    return "Capture claimed verified completion without a canonical manifest digest. Stockroom did not mark the files complete.";
  }
  if (evidence.state === "unverified") {
    return reason
      ? `Completion was not verified. ${reason}`
      : "Completion was not verified. Stockroom did not mark the files complete.";
  }
  if (evidence.state === "not-required") {
    return reason || "CAD files are not required for this part.";
  }
  return reason || "The CAD package was reverified against an immutable manifest.";
}

export function CaptureProvider({
  children,
  initialCapture,
}: {
  children: ReactNode;
  /** A deterministic restored host handoff used by real-app Design Studio previews. */
  initialCapture?: { state: CaptureState; batchId: string; itemId: string };
}) {
  const [state, setState] = useState<CaptureState>(() => initialCapture?.state ?? IDLE);
  const stateRef = useRef(state);
  // Synced in a layout effect, not during render: render can be replayed or thrown away, and the
  // busy-slot guard in `start` must never reject against a capture state that no commit ever
  // published. `start` only ever runs from an event or an awaited continuation, both after commit.
  useLayoutEffect(() => {
    stateRef.current = state;
  });
  // Who currently owns opening a part, and a request that arrived while nobody did. Refs, not
  // state: a reopen request is a message delivered once, not a value this provider holds, and
  // holding it as state re-rendered every capture consumer for something only one surface acts on.
  const reopenHandlersRef = useRef(new Set<(partId: string) => void>());
  const pendingReopenRef = useRef<string | null>(null);
  const queryClient = useQueryClient();
  const partIdRef = useRef<string | null>(initialCapture?.state.partId ?? null);
  const needsRef = useRef<Requirement[]>(initialCapture?.state.needs ?? []);
  const batchIdRef = useRef<string | null>(initialCapture?.batchId ?? null);
  const itemIdRef = useRef<string | null>(initialCapture?.itemId ?? null);
  const followGenerationRef = useRef(0);
  const pendingStartRef = useRef<{
    commandKey: string;
    promise: Promise<void>;
  } | null>(null);
  const retrySubmissionRef = useRef<{
    commandKey: string;
    idempotencyKey: string;
  } | null>(null);

  const invalidate = useCallback(() => {
    const partId = partIdRef.current;
    queryClient.invalidateQueries({ queryKey: ["parts"] });
    queryClient.invalidateQueries({ queryKey: ["facets"] });
    queryClient.invalidateQueries({ queryKey: ["duplicates"] });
    queryClient.invalidateQueries({ queryKey: ["library-coverage"] });
    queryClient.invalidateQueries({ queryKey: ["library-cad"] });
    queryClient.invalidateQueries({ queryKey: ["altium-status"] });
    queryClient.invalidateQueries({ queryKey: ["altium-models-pending"] });
    if (partId) {
      queryClient.invalidateQueries({ queryKey: ["part-history", partId] });
      void invalidatePartCadProjection(queryClient, partId);
    }
  }, [queryClient]);

  const markReceived = useCallback((requirements: Requirement[]) => {
    setState((current) => {
      const received = { ...current.received };
      for (const requirement of requirements) {
        if (needsRef.current.includes(requirement)) received[requirement] = true;
      }
      return { ...current, received };
    });
  }, []);

  const applyResult = useCallback(
    (
      partId: string,
      needs: Requirement[],
      result: CompletionResult,
      durableSuccessMessage?: string,
    ) => {
      if (partIdRef.current !== partId) return;
      const item = result.items.find((candidate) => candidate.part_id === partId);
      if (!item) {
        throw new Error("The capture report did not contain the requested part.");
      }

      const completionEvidence = item.completion_evidence ?? null;
      const manifestDigest = verifiedManifest(completionEvidence);
      const completionProven =
        manifestDigest !== null || completionEvidence?.state === "not-required";
      const projectionComplete =
        (item.status === "completed" || item.status === "already-complete") &&
        item.remaining.length === 0 &&
        completionProven;
      if (projectionComplete && manifestDigest !== null) {
        markReceived(needs);
      } else {
        markReceived(
          item.satisfied.filter((value): value is Requirement =>
            needs.includes(value as Requirement),
          ),
        );
      }
      invalidate();

      const outcomes = (item.provider_outcomes ?? []).filter(
        (outcome) => outcome.attempted || outcome.status !== "not-attempted",
      );
      const remaining =
        item.remaining
          .map((requirement) => REQ_LABELS[requirement as Requirement] ?? requirement)
          .join(", ") || "required CAD files";
      const notes = (item.notes ?? []).join("; ");
      const missingLabels =
        item.remaining.length > 0 ? ` Still missing: ${remaining}.` : "";
      const operationDetail = item.error || notes;
      const operationSentence = operationDetail
        ? ` ${operationDetail.trim().replace(/[.\s]+$/, "")}.`
        : "";
      const incompleteMessage = `${
        completionProven
          ? "Completion did not produce every required CAD projection."
          : completionEvidenceMessage(completionEvidence)
      }${operationSentence}${missingLabels}`;

      setState((current) => ({
        ...current,
        // The active CAD package is the product outcome. An unavailable optional provider must
        // not turn a verified, usable KiCad/Altium package into a failed completion.
        status: projectionComplete ? "done" : "error",
        providerOutcomes: outcomes,
        completionEvidence,
        completionEvidenceReported: true,
        message: !projectionComplete
          ? incompleteMessage
          : completionEvidence?.state === "not-required"
            ? completionEvidenceMessage(completionEvidence)
            : (durableSuccessMessage ?? completionEvidenceMessage(completionEvidence)),
      }));
    },
    [invalidate, markReceived],
  );

  const followDurable = useCallback(
    async ({
      batchId,
      itemId,
      partId,
      partName,
      needs,
      vendor,
      cursor: initialCursor,
      generation,
    }: {
      batchId: string;
      itemId: string;
      partId: string;
      partName: string;
      needs: Requirement[];
      vendor: string | null;
      cursor: number;
      generation: number;
    }): Promise<void> => {
      let cursor = initialCursor;
      let failures = 0;
      let durableNeeds = needs;
      while (generation === followGenerationRef.current) {
        try {
          const [page, liveSession] = await Promise.all([
            api.workflowEvents(batchId, cursor, EVENT_PAGE_LIMIT),
            api.captureWorkflow(batchId),
          ]);
          if (page.batch.kind !== "guided_capture") {
            throw new Error("The saved workflow is not a guided capture.");
          }
          if (liveSession.workflow_item_id !== itemId || liveSession.part_id !== partId) {
            throw new Error("The durable capture identity changed while reconnecting.");
          }
          // The backend creates the durable workflow from the canonical record under its write
          // fence. That snapshot, not the renderer's earlier query, owns what this run set out to
          // complete. Adopt it on every poll so a concurrent repair or stale browser cache cannot
          // make progress and terminal projection disagree about the task's requirements.
          durableNeeds = liveSession.initial_needs;
          needsRef.current = durableNeeds;
          failures = 0;
          cursor = Math.max(cursor, page.cursor.next_sequence);
          persistWorkflow(batchId, itemId, cursor);
          setState((current) => ({
            ...current,
            status: page.batch.status === "blocked" ? "window-open" : "receiving",
            message: durableMessage(page.batch, page.events, vendor),
            needs: durableNeeds,
            vendor: liveSession.active_route?.vendor ?? current.vendor,
            url: liveSession.active_route?.detail_url ?? null,
            routeToken: liveSession.active_route?.route_token ?? null,
          }));

          if (page.cursor.has_more) continue;
          // A blocked batch with an exact active route is not a failed terminal result: it is the
          // durable handoff the person can reopen, clear, or feed selected files. Keep following it
          // so the same route token owns the eventual download and the modal never loses its
          // Show Provider / Use Downloaded Files actions. A blocked batch with no active route
          // still falls through to the honest terminal error below.
          if (page.batch.status === "blocked" && liveSession.active_route?.route_token) {
            await delay(POLL_INTERVAL_MS);
            continue;
          }
          if (terminalWorkflow(page.batch)) {
            const session = liveSession;
            const source = await api.partCadSource(partId);
            queryClient.setQueryData(["cad-source", partId], source);
            const result = resultFromCanonicalProjection(
              partId,
              partName,
              durableNeeds,
              source,
              session.report ?? null,
            );
            applyResult(
              partId,
              durableNeeds,
              result,
              page.batch.status === "completed"
                ? durableMessage(page.batch, page.events, vendor)
                : undefined,
            );
            const canonicalReady =
              source.needs.length === 0 &&
              ["verified", "not-required"].includes(
                source.completion_evidence?.state ?? "",
              );
            if (page.batch.status !== "completed" && !canonicalReady) {
              setState((current) => ({
                ...current,
                status: "error",
                message: durableMessage(page.batch, page.events, vendor),
              }));
            }
            if (!["failed", "paused"].includes(page.batch.status)) clearWorkflow(batchId);
            return;
          }
          await delay(POLL_INTERVAL_MS);
        } catch (error) {
          if (generation !== followGenerationRef.current) return;
          if (
            error instanceof ApiError &&
            [400, 404, 409].includes(error.status)
          ) {
            clearWorkflow(batchId);
            setState((current) => ({
              ...current,
              status: "error",
              message: error.message,
            }));
            return;
          }
          failures += 1;
          setState((current) => ({
            ...current,
            status: "receiving",
            message:
              failures === 1
                ? "Connection interrupted. Reconnecting to the durable completion run..."
                : `Still reconnecting to the durable completion run (attempt ${failures}).`,
          }));
          await delay(Math.min(5_000, 250 * 2 ** Math.min(failures - 1, 5)));
        }
      }
    },
    [applyResult, queryClient],
  );

  useEffect(() => {
    const saved = savedWorkflow();
    if (!saved) return;
    const { batchId, itemId, cursor } = saved;
    const generation = ++followGenerationRef.current;
    // Two guards, because there are two different things that can make this run irrelevant, and the
    // generation ref only covers one of them. The REF says "some other capture now owns the slot" -
    // it is shared, and a `start()` from a surface bumps it. This FLAG says "this effect instance is
    // gone", which is a fact about this closure alone and is what a teardown actually means.
    let cancelled = false;

    async function reconnect(): Promise<void> {
      let failures = 0;
      while (!cancelled && generation === followGenerationRef.current) {
        try {
          const session = await api.captureWorkflow(batchId);
          if (session.workflow_item_id !== itemId) {
            throw new Error("The saved capture item no longer matches its workflow.");
          }
          const detail = await api.partDetail(session.part_id);
          // The loop condition was tested BEFORE those two requests. Between them the effect can be
          // cleaned up, or a real capture can be started from a surface, and either bumps the
          // generation - so re-test it here, before this abandoned reconnect writes the identity refs
          // and the state. Without it a discarded reconnect could overwrite the refs the LIVE capture
          // is following with the part it had set out to restore. The requests are not cancelled and
          // nothing is deferred: only the result of a run nobody is waiting for is dropped.
          if (cancelled) return;
          if (generation !== followGenerationRef.current) return;
          const partName = detail.derived.display_name;
          partIdRef.current = session.part_id;
          needsRef.current = session.initial_needs;
          batchIdRef.current = batchId;
          itemIdRef.current = itemId;
          setState({
            ...IDLE,
            partId: session.part_id,
            workflowItemId: itemId,
            partName,
            needs: session.initial_needs,
            vendor: session.vendor ?? "All Sources",
            status: "receiving",
            backgrounded: true,
            message: "Reconnected to durable completion. Restoring the latest verified stage...",
          });
          await followDurable({
            batchId,
            itemId,
            partId: session.part_id,
            partName,
            needs: session.initial_needs,
            vendor: session.vendor,
            cursor,
            generation,
          });
          return;
        } catch (error) {
          if (cancelled) return;
          if (generation !== followGenerationRef.current) return;
          failures += 1;
          if (error instanceof ApiError && ![0, 503].includes(error.status)) {
            if ([400, 404, 409].includes(error.status)) clearWorkflow(batchId);
            setState({
              ...IDLE,
              status: "error",
              message: error.message,
            });
            return;
          }
          await delay(Math.min(5_000, 250 * 2 ** Math.min(failures - 1, 5)));
        }
      }
    }

    void reconnect();
    return () => {
      cancelled = true;
      if (followGenerationRef.current === generation) followGenerationRef.current += 1;
    };
  }, [followDurable]);

  const runStart = useCallback(
    async (
      partId: string,
      partName: string,
      needs: Requirement[],
      sourceKey?: string,
    ) => {
      const commandKey = captureCommandKey(partId, sourceKey);
      const idempotencyKey =
        retrySubmissionRef.current?.commandKey === commandKey
          ? retrySubmissionRef.current.idempotencyKey
          : submissionKey();
      retrySubmissionRef.current = { commandKey, idempotencyKey };
      const generation = ++followGenerationRef.current;
      partIdRef.current = partId;
      needsRef.current = needs;
      batchIdRef.current = null;
      itemIdRef.current = null;
      setState(() => ({
        ...IDLE,
        partId,
        partName,
        needs,
        vendor: sourceKey ?? "All Sources",
        status: "resolving",
        message:
          "Checking saved evidence and exact identity, then opening the provider page for you...",
      }));

      try {
        const reference = await api.runCapture({
          partIds: [partId],
          vendor: sourceKey || undefined,
          idempotencyKey,
        });
        if (
          partIdRef.current !== partId ||
          generation !== followGenerationRef.current
        ) {
          return;
        }
        if (!reference.workflow_batch_id) {
          if (reference.job_id) {
            // Deliberately not latched for the lifetime of the hook. Stockroom restarts
            // itself for every update, so a backend that could not serve a durable workflow
            // a moment ago may serve one now. Remembering it made the "Try Again" button
            // short-circuit to "unavailable" for every part until the app was relaunched.
            throw new UnsupportedDurableRuntimeError();
          }
          throw new Error(
            "The backend returned no durable workflow batch. Capture was not started.",
          );
        }
        if (!reference.workflow_item_id) {
          throw new Error("The durable capture returned no workflow item.");
        }
        retrySubmissionRef.current = null;
        const batchId = reference.workflow_batch_id;
        const itemId = reference.workflow_item_id;
        const cursor = reference.event_cursor ?? 0;
        batchIdRef.current = batchId;
        itemIdRef.current = itemId;
        persistWorkflow(batchId, itemId, cursor);
        setState((current) => ({
          ...current,
          workflowItemId: itemId,
          status: "receiving",
          message:
            "Completion is running. Open the provider page when it appears, sign in if it asks, " +
            "choose the formats you need, and download; Stockroom captures and validates each file as it lands.",
        }));
        await followDurable({
          batchId,
          itemId,
          partId,
          partName,
          needs,
          vendor: sourceKey ?? null,
          cursor,
          generation,
        });
      } catch (error) {
        if (
          partIdRef.current !== partId ||
          generation !== followGenerationRef.current
        ) {
          return;
        }
        setState((current) => ({
          ...current,
          status:
            error instanceof UnsupportedDurableRuntimeError ||
            (error instanceof ApiError && error.status === 503)
              ? "unavailable"
              : "error",
          message:
            error instanceof ApiError && error.status === 503
              ? `Durable capture is unavailable. ${error.message}`
              : errorMessage(error, "Capture failed."),
        }));
      }
    },
    [followDurable],
  );

  const start = useCallback(
    (
      partId: string,
      partName: string,
      needs: Requirement[],
      sourceKey?: string,
    ): Promise<void> => {
      const commandKey = captureCommandKey(partId, sourceKey);
      const pending = pendingStartRef.current;
      if (pending) {
        if (pending.commandKey === commandKey) return pending.promise;
        return Promise.reject(new CaptureBusyError(stateRef.current.partName ?? ""));
      }
      const currentCapture = stateRef.current;
      if (captureInFlight(currentCapture)) {
        // Also covers a workflow restored from durable UI state, which has no pending promise in
        // this renderer but is still the one capture slot being followed.
        return Promise.reject(new CaptureBusyError(currentCapture.partName ?? ""));
      }

      const promise = runStart(partId, partName, needs, sourceKey);
      const pendingEntry = { commandKey, promise };
      pendingStartRef.current = pendingEntry;
      const clearPending = () => {
        if (pendingStartRef.current === pendingEntry) pendingStartRef.current = null;
      };
      // Do not use an ignored `finally()` here. It creates a second promise that rejects whenever
      // `runStart` rejects, even when the caller correctly handles the original promise, which
      // surfaces as an unrelated unhandled rejection in the renderer.
      void promise.then(clearPending, clearPending);
      return promise;
    },
    [runStart],
  );

  const reset = useCallback(() => {
    followGenerationRef.current += 1;
    if (batchIdRef.current) clearWorkflow(batchIdRef.current);
    partIdRef.current = null;
    needsRef.current = [];
    batchIdRef.current = null;
    itemIdRef.current = null;
    setState(IDLE);
  }, []);

  const keepWorking = useCallback(() => {
    setState((current) => ({ ...current, backgrounded: true }));
  }, []);

  const showProvider = useCallback(async () => {
    const batchId = batchIdRef.current;
    if (!batchId) {
      throw new Error("This completion has no retained provider page to show.");
    }
    await api.showCaptureProvider(batchId);
  }, []);

  const onReopen = useCallback((handler: (partId: string) => void) => {
    const handlers = reopenHandlersRef.current;
    handlers.add(handler);
    // A request can arrive while no surface owns opening a part, because the pill both requests the
    // reopen and navigates to the Library, and the Library is not mounted until that navigation
    // commits. So the request waits here for exactly one subscriber and is then spent.
    const waiting = pendingReopenRef.current;
    if (waiting !== null) {
      pendingReopenRef.current = null;
      handler(waiting);
    }
    return () => {
      handlers.delete(handler);
    };
  }, []);

  const openPart = useCallback((partId: string) => {
    const handlers = [...reopenHandlersRef.current];
    if (handlers.length === 0) {
      pendingReopenRef.current = partId;
      return;
    }
    for (const handler of handlers) handler(partId);
  }, []);

  const requestReopen = useCallback(() => {
    const partId = partIdRef.current;
    setState((current) => ({ ...current, backgrounded: false }));
    if (partId) openPart(partId);
  }, [openPart]);

  const requestOpenFor = useCallback(
    (partId: string) => {
      openPart(partId);
    },
    [openPart],
  );

  // Held by identity rather than rebuilt inline. Every action below is a stable `useCallback`, so
  // the only thing that genuinely changes is the capture state. Rebuilding the object each render
  // meant a poll tick - one every 750ms for the whole life of a capture - re-rendered every
  // `useCapture` consumer in the application, including surfaces with nothing to redraw. Named
  // `captureApi`, not `api`: this component reads the API CLIENT as `api`, and shadowing it here
  // silently routes every request into this object.
  const captureApi = useMemo<CaptureApi>(
    () => ({
      active: state,
      start,
      reset,
      keepWorking,
      showProvider,
      onReopen,
      requestReopen,
      requestOpenFor,
    }),
    [state, start, reset, keepWorking, showProvider, onReopen, requestReopen, requestOpenFor],
  );

  return <CaptureContext.Provider value={captureApi}>{children}</CaptureContext.Provider>;
}

export function useCapture(): CaptureApi {
  const context = useContext(CaptureContext);
  if (!context) throw new Error("useCapture must be used within a CaptureProvider");
  return context;
}
