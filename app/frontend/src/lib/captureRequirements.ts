/**
 * What a capture is FOR, and how to read one, with no React in it.
 *
 * The capture provider lives in `capture.tsx` and is a component file. Everything here used to live
 * there beside it, which cost every surface that merely asks "is a capture running?" or "what is
 * this requirement called?" its Fast Refresh state: a component file that also exports plain values
 * has no refresh boundary, so editing the provider full-reloaded the app instead of preserving what
 * the person had open. These are values and types rather than components, so they belong on this
 * side of that boundary and `capture.tsx` imports them like any other consumer - deliberately with
 * no re-export, because a re-export would put the same non-component exports back in the component
 * file and restore the hazard exactly.
 *
 * The label table is registry VOCABULARY rather than authored copy: it names EDA tools and asset
 * kinds, so it does not go through the copy layer (see the reason recorded in
 * `copy.coverage.test.ts`). Surfaces that show a requirement to a person pass these as the copy
 * DEFAULT for a per-surface id, which is how a rewording stays possible without letting a rewording
 * change what a file IS.
 */
import type { CompletionEvidence, ProviderOutcome, Requirement } from "../api/types";

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

export class CaptureBusyError extends Error {
  constructor(partName: string) {
    super(`Finish the active completion for ${partName || "the current part"} before starting another.`);
    this.name = "CaptureBusyError";
  }
}

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

export type Received = Partial<Record<Requirement, boolean>>;

export interface CaptureState {
  partId: string | null;
  workflowItemId: string | null;
  partName: string | null;
  status: GuidedStatus;
  message: string | null;
  url: string | null;
  routeToken: string | null;
  vendor: string | null;
  needs: Requirement[];
  received: Received;
  backgrounded: boolean;
  providerOutcomes: ProviderOutcome[];
  completionEvidence: CompletionEvidence | null;
  completionEvidenceReported: boolean;
}

// A capture that has not reached a terminal verdict yet. Starting a different part while one of
// these is running is what abandons the earlier follow loop.
const IN_FLIGHT: GuidedStatus[] = ["resolving", "window-open", "receiving", "attaching"];

/**
 * Is this capture still running?
 *
 * There is exactly ONE capture slot here and a process-wide exclusive window in the backend, so
 * every surface that can START a capture has to ask this first. Exported rather than re-derived
 * per surface, because a second list of "busy" statuses is a second answer waiting to disagree.
 */
export function captureInFlight(state: CaptureState): boolean {
  return IN_FLIGHT.includes(state.status);
}

export function subsetComplete(
  needs: Requirement[],
  received: Received,
  subset: Requirement[],
): boolean {
  return needs.filter((need) => subset.includes(need)).every((need) => received[need]);
}
