import type { UpdateCheck } from "../api/types";
import {
  deriveUpdateStanding,
  runningVersion,
  shortRevision,
} from "../lib/updateStanding";
import { Dot } from "./primitives";

const STANDING_LABEL = {
  checking: "Checking…",
  current: "Current",
  available: "Update Available",
  unknown: "Unknown",
} as const;

const STANDING_TONE = {
  checking: "text-t3",
  current: "text-ok",
  available: "text-warn",
  unknown: "text-t3",
} as const;

export function RunningVersionIndicator({
  data,
  checking,
  failed,
  buildVersion = __APP_VERSION__,
}: {
  data: UpdateCheck | undefined;
  checking: boolean;
  failed: boolean;
  buildVersion?: string;
}) {
  const view = deriveUpdateStanding({ data, checking, failed });
  const running = runningVersion(view.currentRevision, buildVersion);
  const target = shortRevision(view.targetRevision);
  const label = STANDING_LABEL[view.standing];
  const accessibleVersion =
    running.kind === "revision"
      ? `running revision ${running.value}`
      : `running version ${running.value}`;
  const accessibleTarget =
    view.standing === "available" && target ? `, target revision ${target}` : "";

  return (
    <span
      role="status"
      aria-label={`${accessibleVersion}, ${label}${accessibleTarget}`}
      title={view.detail}
      className="inline-flex min-w-0 items-center gap-1.5 whitespace-nowrap"
    >
      <Dot
        tone={
          view.standing === "current"
            ? "ok"
            : view.standing === "available"
              ? "warn"
              : "neutral"
        }
      />
      <span className="text-t3">{running.kind === "revision" ? "r" : "v"}</span>
      <span className="font-mono tabular-nums text-t2">{running.value}</span>
      {view.standing === "available" && target ? (
        <>
          <span aria-hidden className="text-line2">
            →
          </span>
          <span className="font-mono tabular-nums text-t2">{target}</span>
        </>
      ) : null}
      <span className={STANDING_TONE[view.standing]}>{label}</span>
    </span>
  );
}
