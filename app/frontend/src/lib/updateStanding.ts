import type { UpdateCheck } from "../api/types";

export type UpdateStanding =
  | "checking"
  | "current"
  | "available"
  | "ready"
  | "updating"
  | "retrying"
  | "blocked"
  // The backend adopted a revision this WINDOW never reloaded onto. The app is running one
  // revision's JavaScript against another's backend, which is a fact, not a detail.
  | "restart_required"
  | "unknown";
export type UpdateIdentityKind = "revision" | "version" | "release";

export interface UpdateIdentityView {
  value: string;
  kind: UpdateIdentityKind;
}

export interface UpdateStandingView {
  standing: UpdateStanding;
  currentRevision: string;
  targetRevision: string;
  detail: string;
}

export function updateTargetRevision(data: UpdateCheck | undefined): string {
  return (data?.target_release_id || data?.target_revision || "").trim();
}

export function updateCurrentRevision(data: UpdateCheck | undefined): string {
  return (data?.current_release_id || data?.current_revision || "").trim();
}

// The convergence phases that mean an adoption is IN FLIGHT: the host is staging a release,
// reloading this frontend, or handing off to a new backend. Named once because the standing and
// the clock that bounds it have to agree on what "in flight" means.
const ADOPTION_PHASES = ["applying", "reloading_frontend", "handing_off", "restarting"];

export function isAdoptionInFlight(data: UpdateCheck | undefined): boolean {
  if (!data) return false;
  return ADOPTION_PHASES.includes(data.convergence_phase ?? "") || data.state === "updating";
}

/**
 * How long a lost backend still reads as a restart rather than a failure.
 *
 * A real handoff KILLS the backend, so the check errors while the cached snapshot still says the
 * adoption is in flight - exactly the case the updating standing exists for. Past this window the
 * backend has had every chance to come back and "Retrying..." is the honest word again.
 */
export const RESTART_GRACE_MS = 90_000;

/**
 * How long an adoption may sit in a transitional phase before it is treated as stuck.
 *
 * Generous on purpose: staging, health-checking and handing off a release is minutes of work on a
 * cold machine. But an "Updating..." with no exit is worse than a late verdict - a host that
 * stalled left that pill on screen forever with nothing to act on.
 */
export const ADOPTION_STALL_MS = 10 * 60_000;

/** Milliseconds between two instants the CALLER supplied; an unknown clock reads as "just now". */
function elapsedSince(now: number | undefined, since: number | undefined): number {
  if (now === undefined || since === undefined) return 0;
  return Math.max(0, now - since);
}

/** The app-repo revision baked into this bundle at build time (`0.1.0+abcdef1`), if it carries one. */
function bundleRevision(buildVersion: string): string {
  return /\+([0-9a-f]{7,})$/i.exec(buildVersion.trim())?.[1] ?? "";
}

/**
 * Whether two identities are the same revision expressed at different lengths.
 *
 * Only Git revisions compare: a production install reports `release-1.2.3.4` while the bundle
 * carries a short SHA, and those two disagreeing about nothing is not evidence of anything.
 */
function revisionsDisagree(bundle: string, revision: string): boolean {
  if (!bundle || !/^[0-9a-f]{7,}$/i.test(revision)) return false;
  const a = bundle.toLowerCase();
  const b = revision.toLowerCase();
  return !a.startsWith(b) && !b.startsWith(a);
}

/**
 * The revision this window is RUNNING versus the revision the backend reports, when they disagree.
 *
 * The frontend is a bundle loaded once; the backend is a process that gets replaced under it. If a
 * seamless handoff swaps the backend but the WebView2 bundle never reloads, every version readout
 * would confidently show the new revision while old JavaScript is what is actually executing.
 * `null` means "no claim": either the bundle carries no revision, or the two identities are not
 * the same kind and comparing them would invent a disagreement.
 */
export function staleFrontend(
  data: UpdateCheck | undefined,
  buildVersion: string | undefined,
): { bundle: string; backend: string } | null {
  const bundle = bundleRevision(buildVersion ?? "");
  // Compare against the exact bundle the backend is serving, not the checkout HEAD. Because
  // frontend-dist is committed, a build commit necessarily follows the source revision baked
  // into its bundle; comparing those two Git commits made every clean release look stale forever.
  // Fall back for rolling compatibility with an older backend that has not learned this field.
  const backend = (data?.frontend_revision ?? data?.current_revision ?? "").trim();
  return revisionsDisagree(bundle, backend) ? { bundle, backend } : null;
}

export function deriveUpdateStanding({
  data,
  checking,
  failed,
  now,
  failedSince,
  phaseStartedAt,
  buildVersion,
}: {
  data: UpdateCheck | undefined;
  checking: boolean;
  failed: boolean;
  // The clocks. This function stays PURE - every bound below is a duration derived from instants
  // the caller passes in, never from a Date.now() read in here. `useUpdateStanding` keeps them.
  now?: number;
  /** When the current failure streak began (not when the last attempt failed). */
  failedSince?: number;
  /** When the adoption currently in flight first reported a transitional phase. */
  phaseStartedAt?: number;
  /** The revision baked into this bundle, so a frontend that never reloaded can be named. */
  buildVersion?: string;
}): UpdateStandingView {
  const currentRevision = updateCurrentRevision(data);
  const targetRevision = updateTargetRevision(data);
  if (checking) {
    return {
      standing: "checking",
      currentRevision,
      targetRevision,
      detail: "Checking the application remote for the latest revision.",
    };
  }
  if (!data) {
    return {
      standing: failed ? "retrying" : "unknown",
      currentRevision,
      targetRevision: "",
      detail: failed
        ? "The remote check failed; Stockroom will retry automatically."
        : "The latest application revision could not be verified.",
    };
  }
  // A failing check used to be tested BEFORE the in-flight branch, so a healthy restart - the one
  // case that branch exists for - always rendered as "Retrying...": the handoff kills the backend,
  // the query errors, and the cached snapshot still says the adoption is under way. It cannot
  // simply be reordered either, because once the backend is genuinely gone "Retrying..." IS the
  // truth. So the failure is BOUNDED instead: it reads as the restart it claims to be only while
  // that claim is still young.
  if (failed) {
    if (
      isAdoptionInFlight(data) &&
      elapsedSince(now, failedSince) < RESTART_GRACE_MS
    ) {
      return {
        standing: "updating",
        currentRevision,
        targetRevision,
        detail: "Stockroom is restarting to finish adopting a verified release.",
      };
    }
    return {
      standing: "retrying",
      currentRevision,
      targetRevision,
      detail:
        data.detail ||
        "The remote check did not complete; Stockroom will retry automatically.",
    };
  }
  if (["offline", "unverified"].includes(data.state ?? "")) {
    return {
      standing: "retrying",
      currentRevision,
      targetRevision,
      detail:
        data.detail ||
        "The remote check did not complete; Stockroom will retry automatically.",
    };
  }
  if (["blocked", "diverged", "failed", "rolled_back", "no_remote"].includes(data.state ?? "")) {
    return {
      standing: "blocked",
      currentRevision,
      targetRevision,
      detail: data.detail || "Automatic application convergence needs attention.",
    };
  }
  if (isAdoptionInFlight(data)) {
    // "Updating..." had no exit. A host that stalls mid-adoption held that word forever, and the
    // only escape was closing the app, so an adoption that has run far past any plausible handoff
    // is reported as what it is: something that needs attention.
    if (elapsedSince(now, phaseStartedAt) > ADOPTION_STALL_MS) {
      return {
        standing: "blocked",
        currentRevision,
        targetRevision,
        detail: `The automatic adoption has not completed after ${Math.round(
          ADOPTION_STALL_MS / 60_000,
        )} minutes and needs attention; restart Stockroom to retry it.`,
      };
    }
    return {
      standing: "updating",
      currentRevision,
      targetRevision,
      detail: data.detail || "A verified application release is being adopted automatically.",
    };
  }
  // The host emits `checking` while it probes the remote. Leaving it unhandled dropped a
  // perfectly healthy check through to `unknown`, which renders as "Update Unknown" and, via
  // the Settings attention dot, as a warning that never clears.
  if (data.state === "checking") {
    return {
      standing: "checking",
      currentRevision,
      targetRevision,
      detail: data.detail || "Checking the application remote for the latest revision.",
    };
  }
  if (data.state === "ready" && targetRevision) {
    return {
      standing: "ready",
      currentRevision,
      targetRevision,
      detail: data.detail || "A verified release is ready to apply.",
    };
  }
  // Nothing is in flight and the backend has answered - so the backend's revision and this
  // bundle's revision are claims about the same thing, and a disagreement between them is the one
  // fact no other standing can carry. Every readout used to prefer the backend silently, which is
  // how a frontend that missed its reload still reported the new revision as "Current".
  const stale = staleFrontend(data, buildVersion);
  if (stale) {
    return {
      standing: "restart_required",
      currentRevision,
      targetRevision,
      detail:
        `This window is still running the ${shortRevision(stale.bundle)} interface while the ` +
        `backend reports ${shortRevision(stale.backend)}. Restart Stockroom to finish adopting it.`,
    };
  }
  // Convergence reports an available update as the state `update_available`, not only as the
  // `update_available` flag below, so a real pending update also fell through to `unknown`.
  if ((data.state === "update_available" || data.update_available) && targetRevision) {
    return {
      standing: "available",
      currentRevision,
      targetRevision,
      detail: data.detail || "A newer application revision is available.",
    };
  }
  if (data.update_available) {
    return {
      standing: "unknown",
      currentRevision,
      targetRevision: "",
      detail: "An update was reported, but its target revision could not be verified.",
    };
  }
  // `update_available: false` alone proves nothing. Current requires the backend's successful
  // fetch/ahead-behind state plus the exact upstream revision it compared against.
  if (
    data.state === "up_to_date" &&
    currentRevision &&
    targetRevision &&
    currentRevision === targetRevision
  ) {
    return {
      standing: "current",
      currentRevision,
      targetRevision,
      detail: "The application remote confirms this installation is current.",
    };
  }
  if (
    data.state === "up_to_date" &&
    currentRevision &&
    targetRevision &&
    currentRevision !== targetRevision
  ) {
    return {
      standing: "unknown",
      currentRevision,
      targetRevision,
      detail: "The installed and latest remote revisions do not match exactly.",
    };
  }
  return {
    standing: "unknown",
    currentRevision,
    targetRevision: "",
    detail: data.detail || "The latest application revision could not be verified.",
  };
}

export function shortRevision(value: string): string {
  const revision = value.trim();
  return /^[0-9a-f]{8,}$/i.test(revision) ? revision.slice(0, 7) : revision;
}

/**
 * Render the identity the backend actually supplied.
 *
 * Production uses immutable signed release IDs (`release-1.2.3.4`); development uses Git
 * revisions. Treating every non-empty identity as a SHA turned the production ID into the
 * meaningless `r release-`. Unknown release-ID schemes remain intact and are never truncated.
 */
export function updateIdentity(value: string): UpdateIdentityView {
  const identity = value.trim();
  const version = /^(?:release-|v)?(\d+(?:\.\d+)+)$/i.exec(identity)?.[1];
  if (version) {
    return { value: version, kind: "version" };
  }
  if (/^[0-9a-f]{7,}$/i.test(identity)) {
    return { value: shortRevision(identity), kind: "revision" };
  }
  return { value: identity || "Unknown", kind: "release" };
}

export function aboutVersion(
  data: UpdateCheck | undefined,
  buildVersion: string,
): string {
  const explicitRelease = (data?.current_release_id ?? "").trim();
  const revision = (data?.current_revision ?? "").trim();
  const productionRelease =
    data?.channel === "production" || /^release-/i.test(revision) ? revision : "";
  const authoritativeRelease = explicitRelease || productionRelease;
  if (authoritativeRelease) {
    return updateIdentity(authoritativeRelease).value;
  }
  return buildVersion.trim() || "Unknown";
}

/**
 * The revision this window is actually RUNNING.
 *
 * The backend's revision answers that only while the bundle agrees with it. When they disagree,
 * the executing JavaScript is this bundle's - reporting the backend's newer revision as "running"
 * is the confident lie a missed frontend reload produces, so the bundle wins and the disagreement
 * is named by the `restart_required` standing beside it.
 */
export function runningVersion(
  currentRevision: string,
  buildVersion: string,
): UpdateIdentityView {
  const buildRevision = bundleRevision(buildVersion);
  const revision = currentRevision.trim();
  if (revision && !revisionsDisagree(buildRevision, revision)) {
    return updateIdentity(revision);
  }
  if (buildRevision) {
    return { value: shortRevision(buildRevision), kind: "revision" };
  }
  return { value: buildVersion.trim() || "Unknown", kind: "version" };
}
