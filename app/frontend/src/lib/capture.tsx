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
  useRef,
  useState,
  type ReactNode,
} from "react";
import { useQueryClient } from "@tanstack/react-query";
import { api, ApiError } from "../api/client";
import type {
  CompletionResult,
  ProviderOutcome,
  Requirement,
} from "../api/types";
import { streamEvents } from "./sse";

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
};

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

export function CaptureProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<CaptureState>(IDLE);
  const [reopenPartId, setReopenPartId] = useState<string | null>(null);
  const queryClient = useQueryClient();
  const partIdRef = useRef<string | null>(null);
  const needsRef = useRef<Requirement[]>([]);

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

  const start = useCallback(
    async (
      partId: string,
      partName: string,
      needs: Requirement[],
      sourceKey?: string,
      mode: CaptureMode = "automatic",
    ) => {
      partIdRef.current = partId;
      needsRef.current = needs;
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
            : "Checking direct sources and provider libraries...",
      });

      try {
        const { job_id: jobId } = await api.runCapture({
          partIds: [partId],
          vendor: sourceKey || undefined,
          mode,
        });
        setState((current) => ({
          ...current,
          status: "receiving",
          message:
            mode === "collect-all"
              ? "Collecting verified sources in order. A provider page appears only when your input is required."
              : mode === "automatic"
                ? "Checking permitted automatic sources and validating anything they return."
                : "Complete the exact provider handoff. Stockroom handles every delivered file.",
        }));

        const body = await api.openJobStream(jobId);
        let failure: string | null = null;
        let result: CompletionResult | null = null;
        for await (const event of streamEvents(body)) {
          if (event.event === "progress") {
            const message = (event.data as { message?: string }).message;
            if (message) {
              setState((current) =>
                current.status === "done" ? current : { ...current, message },
              );
            }
          } else if (event.event === "error") {
            failure =
              (event.data as { detail?: string }).detail ?? "The capture failed.";
          } else if (event.event === "result") {
            result = (event.data as { result?: CompletionResult }).result ?? null;
          } else if (event.event === "done") {
            break;
          }
        }

        if (failure) throw new Error(failure);
        if (partIdRef.current !== partId) return;
        if (!result) {
          throw new Error("The capture ended without a verified completion report.");
        }
        const item = result.items.find((candidate) => candidate.part_id === partId);
        if (!item) {
          throw new Error("The capture report did not contain the requested part.");
        }

        const projectionComplete =
          (item.status === "completed" || item.status === "already-complete") &&
          item.remaining.length === 0;
        if (projectionComplete) {
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
        const collectSucceeded =
          mode !== "collect-all" || collectionComplete === true;
        const terminalDone = projectionComplete && collectSucceeded;

        setState((current) => ({
          ...current,
          status: terminalDone ? "done" : "error",
          providerOutcomes: outcomes,
          collectionComplete,
          message:
            mode === "collect-all"
              ? collectionComplete
                ? `${summary}. Every eligible route completed without a blocked or failed outcome.`
                : `${summary || "Source collection stopped"}. Review the blocked or failed routes below.`
              : projectionComplete
                ? "All network files were verified and attached."
                : item.error ||
                  (notes
                    ? `Capture finished incomplete. ${notes}. Still missing: ${remaining}.`
                    : `Capture finished incomplete. Still missing: ${remaining}.`),
        }));
      } catch (error) {
        if (partIdRef.current !== partId) return;
        setState((current) => ({
          ...current,
          status: "error",
          message:
            error instanceof ApiError
              ? error.message
              : errorMessage(error, "Capture failed."),
        }));
      }
    },
    [invalidate, markReceived],
  );

  const reset = useCallback(() => {
    partIdRef.current = null;
    needsRef.current = [];
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
