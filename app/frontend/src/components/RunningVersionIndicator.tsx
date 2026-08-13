import { useText } from "../lib/copy";
import {
  runningVersion,
  updateIdentity,
  type UpdateStanding,
  type UpdateStandingView,
} from "../lib/updateStanding";
import { Dot, type BadgeTone } from "./primitives";

const STANDING_TONE = {
  checking: "text-t3",
  current: "text-ok-text",
  available: "text-warn",
  ready: "text-warn",
  updating: "text-acc",
  retrying: "text-warn",
  blocked: "text-err-text",
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
  ready: "warn",
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
  identity = true,
}: {
  view: UpdateStandingView;
  buildVersion?: string;
  /**
   * Whether the revision identities are DRAWN.
   *
   * A commit hash is a build fact, and `r4f2a9c1 -> 2222222` in the corner of a component library
   * is developer output on a person's screen: it names something they cannot act on and did not
   * ask about. The standing is the actionable half and stays visible; the identities are drawn in
   * developer mode, in About, and in the accessible name - which is where a person who does want
   * the exact revision goes to find it.
   */
  identity?: boolean;
}) {
  // One hook per standing rather than a lookup inside the map: hooks cannot be called conditionally,
  // and the label is also read aloud through the aria-label below, so every arm has to be resolved.
  const standingLabel: Record<UpdateStanding, string> = {
    checking: useText("update.standing.checking", "Checking…"),
    current: useText("update.standing.current", "Current"),
    available: useText("update.standing.available", "Update Available"),
    ready: useText("update.standing.ready", "Prepared"),
    updating: useText("update.standing.updating", "Updating…"),
    retrying: useText("update.standing.retrying", "Rerunning…"),
    blocked: useText("update.standing.blocked", "Blocked"),
    restart_required: useText("update.standing.restart-required", "Restart Required"),
    unknown: useText("update.standing.unknown", "Unknown"),
  };
  const running = runningVersion(view.currentRevision, buildVersion);
  // The SECOND identity: the update's target while one is available, and the backend's own revision
  // while this window still runs an older bundle. A disagreement is information, so both sides of
  // it are on screen instead of one quietly winning.
  const other =
    ["available", "ready"].includes(view.standing) && view.targetRevision
      ? updateIdentity(view.targetRevision)
      : view.standing === "restart_required" && view.currentRevision
        ? updateIdentity(view.currentRevision)
        : null;
  const label = standingLabel[view.standing];
  const accessibleVersion = `running ${running.kind} ${running.value}`;
  const accessibleOther = !other
    ? ""
    : ["available", "ready"].includes(view.standing)
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
      {identity ? (
        <>
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
        </>
      ) : null}
      <span className={STANDING_TONE[view.standing]}>{label}</span>
    </span>
  );
}
