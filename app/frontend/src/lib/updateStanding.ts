import type { UpdateCheck } from "../api/types";

export type UpdateStanding =
  | "checking"
  | "current"
  | "available"
  | "updating"
  | "retrying"
  | "blocked"
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

export function deriveUpdateStanding({
  data,
  checking,
  failed,
}: {
  data: UpdateCheck | undefined;
  checking: boolean;
  failed: boolean;
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
  if (failed || ["offline", "unverified"].includes(data.state ?? "")) {
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
  if (
    ["applying", "reloading_frontend", "handing_off", "restarting"].includes(
      data.convergence_phase ?? "",
    ) ||
    data.state === "updating"
  ) {
    return {
      standing: "updating",
      currentRevision,
      targetRevision,
      detail: data.detail || "A verified application release is being adopted automatically.",
    };
  }
  if (data.update_available && targetRevision) {
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

export function runningVersion(
  currentRevision: string,
  buildVersion: string,
): UpdateIdentityView {
  if (currentRevision.trim()) {
    return updateIdentity(currentRevision);
  }
  const buildRevision = /\+([0-9a-f]{7,})$/i.exec(buildVersion.trim())?.[1];
  if (buildRevision) {
    return { value: shortRevision(buildRevision), kind: "revision" };
  }
  return { value: buildVersion.trim() || "Unknown", kind: "version" };
}
