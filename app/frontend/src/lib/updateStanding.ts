import type { UpdateCheck } from "../api/types";

type UpdateCheckWithTarget = UpdateCheck & { target_revision?: string };

export type UpdateStanding = "checking" | "current" | "available" | "unknown";

export interface UpdateStandingView {
  standing: UpdateStanding;
  currentRevision: string;
  targetRevision: string;
  detail: string;
}

export function updateTargetRevision(data: UpdateCheck | undefined): string {
  return ((data as UpdateCheckWithTarget | undefined)?.target_revision ?? "").trim();
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
  const currentRevision = (data?.current_revision ?? "").trim();
  const targetRevision = updateTargetRevision(data);
  if (checking) {
    return {
      standing: "checking",
      currentRevision,
      targetRevision,
      detail: "Checking the application remote for the latest revision.",
    };
  }
  if (failed || !data) {
    return {
      standing: "unknown",
      currentRevision,
      targetRevision: "",
      detail: "The latest application revision could not be verified.",
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
  return revision.length > 7 ? revision.slice(0, 7) : revision;
}

export function runningVersion(
  currentRevision: string,
  buildVersion: string,
): { value: string; kind: "revision" | "version" } {
  if (currentRevision.trim()) {
    return { value: shortRevision(currentRevision), kind: "revision" };
  }
  const buildRevision = /\+([0-9a-f]{7,})$/i.exec(buildVersion.trim())?.[1];
  if (buildRevision) {
    return { value: shortRevision(buildRevision), kind: "revision" };
  }
  return { value: buildVersion.trim() || "Unknown", kind: "version" };
}
