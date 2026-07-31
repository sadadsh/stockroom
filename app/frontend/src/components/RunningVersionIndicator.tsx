import {
  runningVersion,
  updateIdentity,
  type UpdateStanding,
  type UpdateStandingView,
} from "../lib/updateStanding";
import { Dot, type BadgeTone } from "./primitives";

const STANDING_LABEL = {
  checking: "Checking…",
  current: "Current",
  available: "Update Available",
  updating: "Updating…",
  retrying: "Retrying…",
  blocked: "Blocked",
  restart_required: "Restart Required",
  unknown: "Unknown",
} as const;

const STANDING_TONE = {
  checking: "text-t3",
  current: "text-ok",
  available: "text-warn",
  updating: "text-acc",
  retrying: "text-warn",
  blocked: "text-err",
  restart_required: "text-warn",
  unknown: "text-t3",
} as const;

// The dot used to be a ternary chain whose last two arms both returned "neutral", so every standing
// except current and available rendered the same grey - a blocked convergence looked exactly like a
// healthy one. One table, in the same tone vocabulary the label beside it already uses.
const STANDING_DOT: Record<UpdateStanding, BadgeTone> = {
  checking: "neutral",
  current: "ok",
  available: "warn",
  updating: "neutral",
  retrying: "warn",
  blocked: "err",
  restart_required: "warn",
  unknown: "neutral",
};

/**
 * The running revision and its remotely proven standing.
 *
 * Takes the DERIVED standing rather than the raw query: the standing is time-bounded now (a dead
 * backend only reads as a restart for so long; an adoption only stays in flight for so long), and
 * those clocks belong to `useUpdateStanding`, not to a status readout.
 */
export function RunningVersionIndicator({
  view,
  buildVersion = __APP_VERSION__,
}: {
  view: UpdateStandingView;
  buildVersion?: string;
}) {
  const running = runningVersion(view.currentRevision, buildVersion);
  // The SECOND identity: the update's target while one is available, and the backend's own revision
  // while this window still runs an older bundle. A disagreement is information, so both sides of
  // it are on screen instead of one quietly winning.
  const other =
    view.standing === "available" && view.targetRevision
      ? updateIdentity(view.targetRevision)
      : view.standing === "restart_required" && view.currentRevision
        ? updateIdentity(view.currentRevision)
        : null;
  const label = STANDING_LABEL[view.standing];
  const accessibleVersion = `running ${running.kind} ${running.value}`;
  const accessibleOther = !other
    ? ""
    : view.standing === "available"
      ? `, target ${other.kind} ${other.value}`
      : `, backend ${other.kind} ${other.value}`;
  const identityPrefix =
    running.kind === "revision" ? "r" : running.kind === "version" ? "v" : "";
  const otherPrefix =
    other?.kind === "revision" ? "" : other?.kind === "version" ? "v" : "";

  return (
    <span
      role="status"
      aria-label={`${accessibleVersion}, ${label}${accessibleOther}`}
      title={view.detail}
      className="inline-flex min-w-0 items-center gap-1.5 whitespace-nowrap"
    >
      <Dot tone={STANDING_DOT[view.standing]} />
      {identityPrefix ? <span className="text-t3">{identityPrefix}</span> : null}
      <span className="font-mono tabular-nums text-t2">{running.value}</span>
      {other ? (
        <>
          <span aria-hidden className="text-line2">
            →
          </span>
          <span className="font-mono tabular-nums text-t2">
            {otherPrefix}
            {other.value}
          </span>
        </>
      ) : null}
      <span className={STANDING_TONE[view.standing]}>{label}</span>
    </span>
  );
}
