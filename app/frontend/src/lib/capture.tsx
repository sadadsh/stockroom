/**
 * One global network-capture job.
 *
 * The backend owns discovery, provider browsers, downloads, validation, retention, and coherent
 * attachment. The frontend starts that job and renders its evidenced result. It deliberately has
 * no host callback, local file picker, manual inspect/commit seam, or per-tool attach path.
 */
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { useQueryClient } from "@tanstack/react-query";
import { api, ApiError } from "../api/client";
import type {
  CompletionEvidence,
  CompletionResult,
  CadSourceResponse,
  ProviderOutcome,
  Requirement,
  WorkflowBatchSummary,
  WorkflowEvent,
} from "../api/types";
import { readUiSession, updateUiSession } from "./uiSession";

export type { Requirement };

export type GuidedStatus =
  | "idle"
  | "resolving"
  | "window-open"
  | "receiving"
  | "attaching"
  | "done"
  | "timed-out"
  | "unavailable"
  | "error";

export type CaptureMode = "automatic" | "assisted" | "collect-all";

export const KICAD_REQS: Requirement[] = [
  "kicad_symbol",
  "kicad_footprint",
  "kicad_model",
];
export const ALTIUM_REQS: Requirement[] = [
  "altium_symbol",
  "altium_footprint",
];

export const REQ_LABELS: Record<Requirement, string> = {
  kicad_symbol: "KiCad Symbol",
  kicad_footprint: "KiCad Footprint",
  kicad_model: "3D Model",
  altium_symbol: "Altium Symbol",
  altium_footprint: "Altium Footprint",
};

type Received = Partial<Record<Requirement, boolean>>;

export interface CaptureState {
  partId: string | null;
  partName: string | null;
  status: GuidedStatus;
  message: string | null;
  url: string | null;
  vendor: string | null;
  needs: Requirement[];
  received: Received;
  backgrounded: boolean;
  providerOutcomes: ProviderOutcome[];
  collectionComplete: boolean | null;
  completionEvidence: CompletionEvidence | null;
  completionEvidenceReported: boolean;
}

const IDLE: CaptureState = {
  partId: null,
  partName: null,
  status: "idle",
  message: null,
  url: null,
  vendor: null,
  needs: [],
  received: {},
  backgrounded: false,
  providerOutcomes: [],
  collectionComplete: null,
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

function captureCommandKey(
  partId: string,
  sourceKey: string | undefined,
  mode: CaptureMode,
): string {
  return JSON.stringify({
    part_id: partId,
    provider: sourceKey || null,
    mode,
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
  // perform without a person-driven provider handoff.  Leaving it non-terminal
  // traps the modal in `window-open` forever even though no provider window was
  // opened, which disables both Open Provider and Collect All Sources.  Consume
  // its durable report and return an actionable partial result instead.
  return ["completed", "blocked", "failed", "cancelled"].includes(batch.status);
}

const WORKFLOW_STAGE_MESSAGE: Record<string, string> = {
  identity_dedupe: "Confirming the exact manufacturer and part number.",
  metadata: "Keeping the best existing facts and filling missing part data.",
  datasheet: "Finding and verifying the manufacturer datasheet.",
  existing_evidence: "Checking saved CAD evidence before downloading anything again.",
  cad_acquisition: "Finding one matched KiCad, Altium, and STEP source set.",
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

function durableMessage(
  batch: WorkflowBatchSummary,
  events: WorkflowEvent[],
  mode: CaptureMode,
  vendor: string | null,
): string {
  if (batch.status === "paused") {
    return "Completion is paused. Resume it from Library Completion when you are ready.";
  }
  if (batch.status === "blocked") {
    return `Automatic lookup finished without a complete CAD package. Open the ${
      vendor || "selected"
    } provider browser now, or choose Collect All Sources to try every eligible provider.`;
  }
  if (batch.status === "cancelled") return "Completion was cancelled before publication.";
  if (batch.status === "failed") {
    return "Completion stopped before the package could be verified and published. Retry to continue from durable evidence.";
  }
  if (batch.status === "completed") {
    return "Part data, datasheet, KiCad, Altium, and STEP are verified and linked.";
  }
  const latestStage = [...events]
    .sort((left, right) => right.sequence - left.sequence)
    .map((event) => event.details.stage)
    .find((stage): stage is string => typeof stage === "string");
  if (latestStage === "cad_acquisition") {
    if (mode === "collect-all") {
      return "Collecting every eligible source in order and retaining verified variants.";
    }
    if (mode === "assisted") {
      return `Using ${vendor || "the selected provider"} and handling every supported step. You only need to answer a provider security check.`;
    }
  }
  return latestStage
    ? (WORKFLOW_STAGE_MESSAGE[latestStage] ?? "Completing this part.")
    : mode === "assisted"
      ? `Starting the ${vendor || "selected"} provider browser. First launch normally takes 10 to 20 seconds. It opens in a separate window and keeps its login on this PC.`
      : mode === "collect-all"
        ? "Preparing the next visible provider route. Stockroom keeps every verified file as each route finishes."
        : "Completion is active. Stockroom is checking exact identity, saved evidence, and network sources in order.";
}

function resultFromProjection(
  partId: string,
  partName: string,
  initialNeeds: Requirement[],
  source: CadSourceResponse,
): CompletionResult {
  const remaining = [...source.needs];
  const satisfied = initialNeeds.filter((value) => !remaining.includes(value));
  const evidence = source.completion_evidence ?? null;
  const complete =
    remaining.length === 0 &&
    (evidence?.state === "verified" || evidence?.state === "not-required");
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
        sources: [],
        notes: [],
        error: "",
        provider_outcomes: [],
        collection_complete: null,
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

export function subsetComplete(
  needs: Requirement[],
  received: Received,
  subset: Requirement[],
): boolean {
  return needs.filter((need) => subset.includes(need)).every((need) => received[need]);
}

export interface CaptureApi {
  active: CaptureState;
  start: (
    partId: string,
    partName: string,
    needs: Requirement[],
    sourceKey?: string,
    mode?: CaptureMode,
  ) => Promise<void>;
  reset: () => void;
  keepWorking: () => void;
  reopenPartId: string | null;
  requestReopen: () => void;
  requestOpenFor: (partId: string) => void;
  clearReopen: () => void;
}

const CaptureContext = createContext<CaptureApi | null>(null);

function errorMessage(error: unknown, fallback: string): string {
  return error instanceof Error ? error.message : fallback;
}

function routeSummary(outcomes: ProviderOutcome[]): string {
  if (outcomes.length === 0) return "";
  const settled = outcomes.filter((outcome) =>
    ["activated", "succeeded-retained"].includes(outcome.status) ||
    (outcome.status === "unavailable" && outcome.attempted),
  ).length;
  return `${settled} of ${outcomes.length} source routes settled`;
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

export function CaptureProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<CaptureState>(IDLE);
  const [reopenPartId, setReopenPartId] = useState<string | null>(null);
  const queryClient = useQueryClient();
  const partIdRef = useRef<string | null>(null);
  const needsRef = useRef<Requirement[]>([]);
  const batchIdRef = useRef<string | null>(null);
  const itemIdRef = useRef<string | null>(null);
  const followGenerationRef = useRef(0);
  const pendingStartRef = useRef<{
    commandKey: string;
    promise: Promise<void>;
  } | null>(null);
  const retrySubmissionRef = useRef<{
    commandKey: string;
    idempotencyKey: string;
  } | null>(null);
  const unsupportedRuntimeRef = useRef(false);

  const invalidate = useCallback(() => {
    const partId = partIdRef.current;
    queryClient.invalidateQueries({ queryKey: ["parts"] });
    queryClient.invalidateQueries({ queryKey: ["facets"] });
    queryClient.invalidateQueries({ queryKey: ["duplicates"] });
    if (partId) {
      queryClient.invalidateQueries({ queryKey: ["part", partId] });
      queryClient.invalidateQueries({ queryKey: ["part-history", partId] });
      queryClient.invalidateQueries({ queryKey: ["cad-source", partId] });
      queryClient.invalidateQueries({ queryKey: ["cad-variants", partId] });
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
      mode: CaptureMode,
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

      const outcomes = item.provider_outcomes ?? [];
      const collectionComplete = item.collection_complete ?? null;
      const remaining =
        item.remaining
          .map((requirement) => REQ_LABELS[requirement as Requirement] ?? requirement)
          .join(", ") || "required CAD files";
      const notes = (item.notes ?? []).join("; ");
      const summary = routeSummary(outcomes);
      const collectSucceeded = mode !== "collect-all" || collectionComplete === true;
      const terminalDone = projectionComplete && collectSucceeded;
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
        status: terminalDone ? "done" : "error",
        providerOutcomes: outcomes,
        collectionComplete,
        completionEvidence,
        completionEvidenceReported: true,
        message:
          !projectionComplete
            ? incompleteMessage
            : mode === "collect-all"
              ? collectionComplete
                ? `${summary}. Every eligible route completed without a blocked or failed outcome.`
                : `${summary || "Source collection stopped"}. Review the blocked or failed routes below.`
              : completionEvidence?.state === "not-required"
                ? completionEvidenceMessage(completionEvidence)
                : durableSuccessMessage ?? completionEvidenceMessage(completionEvidence),
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
      mode,
      vendor,
      cursor: initialCursor,
      generation,
    }: {
      batchId: string;
      itemId: string;
      partId: string;
      partName: string;
      needs: Requirement[];
      mode: CaptureMode;
      vendor: string | null;
      cursor: number;
      generation: number;
    }): Promise<void> => {
      let cursor = initialCursor;
      let failures = 0;
      while (generation === followGenerationRef.current) {
        try {
          const page = await api.workflowEvents(batchId, cursor, EVENT_PAGE_LIMIT);
          if (page.batch.kind !== "guided_capture") {
            throw new Error("The saved workflow is not a guided capture.");
          }
          failures = 0;
          cursor = Math.max(cursor, page.cursor.next_sequence);
          persistWorkflow(batchId, itemId, cursor);
          setState((current) => ({
            ...current,
            status: page.batch.status === "blocked" ? "window-open" : "receiving",
            message: durableMessage(page.batch, page.events, mode, vendor),
          }));

          if (page.cursor.has_more) continue;
          if (terminalWorkflow(page.batch)) {
            const [session, source] = await Promise.all([
              api.captureWorkflow(batchId),
              api.partCadSource(partId),
            ]);
            if (session.workflow_item_id !== itemId || session.part_id !== partId) {
              throw new Error("The durable capture identity changed while reconnecting.");
            }
            const result =
              session.report ?? resultFromProjection(partId, partName, needs, source);
            applyResult(
              partId,
              needs,
              mode,
              result,
              page.batch.status === "completed"
                ? durableMessage(page.batch, page.events, mode, vendor)
                : undefined,
            );
            if (page.batch.status !== "completed") {
              setState((current) => ({
                ...current,
                status: "error",
                message: durableMessage(page.batch, page.events, mode, vendor),
              }));
            }
            if (page.batch.status !== "failed") clearWorkflow(batchId);
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
    [applyResult],
  );

  useEffect(() => {
    const saved = savedWorkflow();
    if (!saved) return;
    const { batchId, itemId, cursor } = saved;
    const generation = ++followGenerationRef.current;

    async function reconnect(): Promise<void> {
      let failures = 0;
      while (generation === followGenerationRef.current) {
        try {
          const session = await api.captureWorkflow(batchId);
          if (session.workflow_item_id !== itemId) {
            throw new Error("The saved capture item no longer matches its workflow.");
          }
          const detail = await api.partDetail(session.part_id);
          const partName = detail.derived.display_name;
          partIdRef.current = session.part_id;
          needsRef.current = session.initial_needs;
          batchIdRef.current = batchId;
          itemIdRef.current = itemId;
          setState({
            ...IDLE,
            partId: session.part_id,
            partName,
            needs: session.initial_needs,
            vendor: session.vendor ?? "Automatic",
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
            mode: session.mode,
            vendor: session.vendor,
            cursor,
            generation,
          });
          return;
        } catch (error) {
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
      if (followGenerationRef.current === generation) followGenerationRef.current += 1;
    };
  }, [followDurable]);

  const runStart = useCallback(
    async (
      partId: string,
      partName: string,
      needs: Requirement[],
      sourceKey?: string,
      mode: CaptureMode = "automatic",
    ) => {
      if (unsupportedRuntimeRef.current) {
        setState({
          ...IDLE,
          partId,
          partName,
          needs,
          vendor: sourceKey ?? "Automatic",
          status: "unavailable",
          message: UNSUPPORTED_DURABLE_RUNTIME,
        });
        return;
      }

      const commandKey = captureCommandKey(partId, sourceKey, mode);
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
      setState({
        ...IDLE,
        partId,
        partName,
        needs,
        vendor: sourceKey ?? "Automatic",
        status: "resolving",
        message:
          mode === "collect-all"
            ? "Planning every eligible source route..."
            : mode === "assisted"
              ? `Preparing ${sourceKey || "the selected provider"} for one assisted capture. Stockroom handles every supported step and pauses only for a provider security check.`
              : "Planning automatic exact-identity, data, datasheet, and shared CAD completion...",
      });

      try {
        const reference = await api.runCapture({
          partIds: [partId],
          vendor: sourceKey || undefined,
          mode,
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
            unsupportedRuntimeRef.current = true;
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
          status: "receiving",
          message:
            mode === "assisted"
              ? `Starting the ${sourceKey || "selected"} provider browser. First launch normally takes 10 to 20 seconds. It opens separately and keeps its login on this PC.`
              : mode === "collect-all"
                ? "Source collection started. Stockroom will open each provider route in order."
                : "Completion started. Stockroom is checking exact identity, saved evidence, and network sources in order.",
        }));
        await followDurable({
          batchId,
          itemId,
          partId,
          partName,
          needs,
          mode,
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
      mode: CaptureMode = "automatic",
    ): Promise<void> => {
      const commandKey = captureCommandKey(partId, sourceKey, mode);
      const pending = pendingStartRef.current;
      if (pending?.commandKey === commandKey) return pending.promise;

      const promise = runStart(partId, partName, needs, sourceKey, mode);
      const active = { commandKey, promise };
      pendingStartRef.current = active;
      void promise.finally(() => {
        if (pendingStartRef.current === active) pendingStartRef.current = null;
      });
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

  const requestReopen = useCallback(() => {
    setReopenPartId(partIdRef.current);
    setState((current) => ({ ...current, backgrounded: false }));
  }, []);

  const requestOpenFor = useCallback((partId: string) => {
    setReopenPartId(partId);
  }, []);

  const clearReopen = useCallback(() => setReopenPartId(null), []);

  return (
    <CaptureContext.Provider
      value={{
        active: state,
        start,
        reset,
        keepWorking,
        reopenPartId,
        requestReopen,
        requestOpenFor,
        clearReopen,
      }}
    >
      {children}
    </CaptureContext.Provider>
  );
}

export function useCapture(): CaptureApi {
  const context = useContext(CaptureContext);
  if (!context) throw new Error("useCapture must be used within a CaptureProvider");
  return context;
}
