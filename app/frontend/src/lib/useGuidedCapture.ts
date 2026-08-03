/**
 * Thin adapter over the global capture store (capture.tsx). Kept as `useGuidedCapture(partId,
 * needs, partName)` so the Complete-Part modal binds with a minimal change: it returns the LIVE
 * capture when this part is the one active capture, otherwise an idle projection carrying the
 * caller's needs (so the checklist renders before start()). All the state-machine behavior - the
 * watchdog, the session-token gate, both-format attach - lives in the provider now.
 */
import {
  captureInFlight,
  useCapture,
  subsetComplete,
  KICAD_REQS,
  ALTIUM_REQS,
  type CaptureMode,
} from "./capture";
import type { Requirement } from "../api/types";

export type { Requirement } from "./capture";
export type { GuidedStatus } from "./capture";

export function useGuidedCapture(partId: string, needs: Requirement[] = [], partName = "") {
  const cap = useCapture();
  const ownsState = cap.active.partId === partId;
  const isActive = ownsState && captureInFlight(cap.active);

  const status = ownsState ? cap.active.status : "idle";
  const message = ownsState ? cap.active.message : null;
  const url = ownsState ? cap.active.url : null;
  const vendor = ownsState ? cap.active.vendor : null;
  const activeNeeds = isActive ? cap.active.needs : needs;
  const received = ownsState ? cap.active.received : {};
  const backgrounded = ownsState ? cap.active.backgrounded : false;
  const providerOutcomes = ownsState ? cap.active.providerOutcomes : [];
  const collectionComplete = ownsState ? cap.active.collectionComplete : null;

  return {
    status,
    message,
    url,
    vendor,
    needs: activeNeeds,
    received,
    backgrounded,
    providerOutcomes,
    collectionComplete,
    kicadComplete: subsetComplete(activeNeeds, received, KICAD_REQS),
    altiumComplete: subsetComplete(activeNeeds, received, ALTIUM_REQS),
    start: (
      sourceKey?: string,
      mode: CaptureMode = "finish-first",
    ) => cap.start(partId, partName, needs, sourceKey, mode),
    reset: () => cap.reset(),
    keepWorking: () => cap.keepWorking(),
  };
}
