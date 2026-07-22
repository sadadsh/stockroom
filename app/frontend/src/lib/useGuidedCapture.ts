/**
 * Thin adapter over the global capture store (capture.tsx). Kept as `useGuidedCapture(partId,
 * needs, partName)` so the Complete-Part modal binds with a minimal change: it returns the LIVE
 * capture when this part is the one active capture, otherwise an idle projection carrying the
 * caller's needs (so the checklist renders before start()). All the state-machine behavior - the
 * watchdog, the session-token gate, both-format attach - lives in the provider now.
 */
import {
  useCapture,
  subsetComplete,
  KICAD_REQS,
  ALTIUM_REQS,
} from "./capture";
import type { Requirement } from "../api/types";

export type { Requirement } from "./capture";
export type { GuidedStatus, CaptureForward } from "./capture";

export function useGuidedCapture(partId: string, needs: Requirement[] = [], partName = "") {
  const cap = useCapture();
  const isActive = cap.active.partId === partId;

  const status = isActive ? cap.active.status : "idle";
  const message = isActive ? cap.active.message : null;
  const url = isActive ? cap.active.url : null;
  const vendor = isActive ? cap.active.vendor : null;
  const activeNeeds = isActive ? cap.active.needs : needs;
  const received = isActive ? cap.active.received : {};
  const backgrounded = isActive ? cap.active.backgrounded : false;

  return {
    status,
    message,
    url,
    vendor,
    needs: activeNeeds,
    received,
    backgrounded,
    kicadComplete: subsetComplete(activeNeeds, received, KICAD_REQS),
    altiumComplete: subsetComplete(activeNeeds, received, ALTIUM_REQS),
    start: () => cap.start(partId, partName, needs),
    submitPaths: (paths: string[]) => cap.submitPaths(partId, partName, needs, paths),
    reset: () => cap.reset(),
    keepWorking: () => cap.keepWorking(),
  };
}
