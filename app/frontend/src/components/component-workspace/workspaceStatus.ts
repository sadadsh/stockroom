/**
 * The ONE status vocabulary the opened component speaks.
 *
 * Nine words, closed. A representation states its readiness with one of them, and a design tool's
 * compact chip states the same thing about everything that tool needs. The point of closing the
 * set is that "Ready", "Complete", "OK" and "Done" stop being four names for one condition on one
 * screen - and that a word never claims more than the record proves: `Downloaded` says a provider
 * gave us the file, `Validated` says a recorded check passed on it, and the two are not the same
 * sentence.
 */
import type {
  RepresentationStatus,
  RepresentationToolView,
  RepresentationView,
  RepresentationKind,
  SourceState,
} from "../../api/workspaceTypes";
import type { BadgeTone } from "../primitives";

export type WorkspaceStatus =
  | "Ready"
  | "Needs Review"
  | "Missing"
  | "Failed"
  | "Not Required"
  | "Validated"
  | "Downloaded"
  | "Available"
  | "Unknown";

/** A representation's own readiness, in the vocabulary. */
export const REPRESENTATION_STATUS_LABEL: Record<RepresentationStatus, WorkspaceStatus> = {
  ready: "Ready",
  review: "Needs Review",
  missing: "Missing",
  failed: "Failed",
  not_required: "Not Required",
};

const TONES: Record<WorkspaceStatus, BadgeTone> = {
  Ready: "ok",
  Validated: "ok",
  Downloaded: "ok",
  Available: "neutral",
  "Not Required": "neutral",
  Unknown: "neutral",
  "Needs Review": "warn",
  Missing: "warn",
  Failed: "err",
};

export function statusTone(status: WorkspaceStatus): BadgeTone {
  return TONES[status];
}

/**
 * What happened to one SOURCE. A different question from a representation's readiness, so a
 * separate closed set rather than four more words crowded into the one above.
 *
 * The four are kept apart on purpose. "Failed" accuses our own fetch (network, auth, rate limit)
 * and is worth retrying; "Not Carried" is the distributor answering honestly that it does not
 * stock this part; "Not Configured" is this machine having no credentials and never having
 * asked. Showing all three as a blank row is what let a broken API read as a part nobody sells.
 */
export type SourceStatusLabel = "Answered" | "Not Carried" | "Failed" | "Not Configured";

export const SOURCE_STATE_LABEL: Record<SourceState, SourceStatusLabel> = {
  success: "Answered",
  unavailable: "Not Carried",
  failed: "Failed",
  not_configured: "Not Configured",
};

const SOURCE_STATE_TONES: Record<SourceState, BadgeTone> = {
  success: "ok",
  unavailable: "neutral",
  failed: "err",
  not_configured: "warn",
};

export function sourceStateTone(state: SourceState): BadgeTone {
  return SOURCE_STATE_TONES[state] ?? "neutral";
}

/** A state a stale client (or an older record) did not send reads as `success`, never as failure. */
export function sourceStateOf(state: SourceState | undefined): SourceState {
  return state && state in SOURCE_STATE_LABEL ? state : "success";
}

/** Every per-tool view a design tool holds across the three representations. */
export function toolViews(
  representations: Record<RepresentationKind, RepresentationView>,
  tool: string,
): RepresentationToolView[] {
  return Object.values(representations)
    .flatMap((view) => view.tools)
    .filter((view) => view.tool === tool);
}

/**
 * The compact status for one design tool.
 *
 * Worst-first: a single failed check decides the chip, because a tool that is four-fifths ready is
 * not ready. Only once nothing is wrong does the chip get to say HOW ready - validated by a
 * recorded check, downloaded from a named provider, or merely available.
 */
export function toolStatus(
  representations: Record<RepresentationKind, RepresentationView>,
  tool: string,
): WorkspaceStatus {
  const views = toolViews(representations, tool);
  if (views.length === 0) return "Unknown";
  if (views.some((view) => view.status === "failed")) return "Failed";
  if (views.some((view) => view.status === "missing")) return "Missing";
  if (views.some((view) => view.status === "review")) return "Needs Review";
  const present = views.filter((view) => view.present);
  if (present.length === 0) return "Not Required";
  if (present.every((view) => view.checks.length > 0)) return "Validated";
  if (present.every((view) => view.sourceId)) return "Downloaded";
  return "Available";
}
