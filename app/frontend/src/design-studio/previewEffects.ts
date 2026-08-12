import type { ApiRequestDescriptor } from "./requestAdapter";

export type PreviewEffectKind =
  | "api"
  | "host-folder-picker"
  | "host-file-picker"
  | "external-navigation"
  | "download";

export interface PreviewEffectDescriptor {
  kind: PreviewEffectKind;
  action: string;
  instruction: string;
}

export const PREVIEW_EFFECT_BLOCKED_EVENT = "stockroom:preview-effect-blocked";

export class PreviewEffectError extends Error {
  readonly descriptor: PreviewEffectDescriptor;
  readonly scenarioId: string;

  constructor(scenarioId: string, descriptor: PreviewEffectDescriptor) {
    super(
      `Fixture preview blocked ${descriptor.action}. ` +
        `Return to Real Data to ${descriptor.instruction}.`,
    );
    this.name = "PreviewEffectError";
    this.scenarioId = scenarioId;
    this.descriptor = descriptor;
  }
}

const registrations: { scenarioId: string; active: boolean }[] = [];
let anchorGuardInstalled = false;

function activeScenarioId(): string | null {
  for (let index = registrations.length - 1; index >= 0; index -= 1) {
    const registration = registrations[index];
    if (registration.active) return registration.scenarioId;
  }
  return null;
}

/** Installs the one process-wide fixture-effect boundary for a scoped scenario lifetime. */
export function installPreviewEffectGuard(scenarioId: string): () => void {
  const registration = { scenarioId, active: true };
  registrations.push(registration);
  installAnchorGuard();
  return () => {
    if (!registration.active) return;
    registration.active = false;
    while (registrations.length && !registrations[registrations.length - 1]?.active) {
      registrations.pop();
    }
    if (!activeScenarioId()) uninstallAnchorGuard();
  };
}

function reportPreviewEffect(descriptor: PreviewEffectDescriptor): PreviewEffectError | null {
  const scenarioId = activeScenarioId();
  if (!scenarioId) return null;
  const error = new PreviewEffectError(scenarioId, descriptor);
  if (typeof window !== "undefined") {
    window.dispatchEvent(new CustomEvent<PreviewEffectError>(PREVIEW_EFFECT_BLOCKED_EVENT, {
      detail: error,
    }));
  }
  return error;
}

function guardedAnchor(event: MouseEvent): HTMLAnchorElement | null {
  const target = event.target;
  if (!(target instanceof Element)) return null;
  const anchor = target.closest("a");
  if (!(anchor instanceof HTMLAnchorElement)) return null;
  if (anchor.hasAttribute("download") || anchor.target.toLowerCase() === "_blank") return anchor;
  try {
    const destination = new URL(anchor.href, document.baseURI);
    return destination.origin !== window.location.origin ? anchor : null;
  } catch {
    return anchor;
  }
}

function blockAnchorEffect(event: MouseEvent): void {
  const anchor = guardedAnchor(event);
  if (!anchor || !activeScenarioId()) return;
  event.preventDefault();
  event.stopImmediatePropagation();
  const filename = anchor.download.trim();
  reportPreviewEffect(filename
    ? {
        kind: "download",
        action: `downloading ${filename}`,
        instruction: "download this file",
      }
    : {
        kind: "external-navigation",
        action: "opening an external page",
        instruction: "open this page",
      });
}

function installAnchorGuard(): void {
  if (anchorGuardInstalled || typeof document === "undefined") return;
  document.addEventListener("click", blockAnchorEffect, true);
  document.addEventListener("auxclick", blockAnchorEffect, true);
  anchorGuardInstalled = true;
}

function uninstallAnchorGuard(): void {
  if (!anchorGuardInstalled || typeof document === "undefined") return;
  document.removeEventListener("click", blockAnchorEffect, true);
  document.removeEventListener("auxclick", blockAnchorEffect, true);
  anchorGuardInstalled = false;
}

export function guardPreviewEffect(descriptor: PreviewEffectDescriptor): void {
  const error = reportPreviewEffect(descriptor);
  if (!error) return;
  throw error;
}

/**
 * Defense-in-depth for a live API dispatch. Scenario reads resolve before this boundary; the
 * machine-local personal design store is the sole live endpoint admitted during preview.
 */
export function guardPreviewLiveApiRequest(descriptor: ApiRequestDescriptor): void {
  if (
    ((descriptor.path === "/api/design-studio/personal" &&
      (descriptor.method.toUpperCase() === "GET" || descriptor.method.toUpperCase() === "PUT")) ||
      (descriptor.path === "/api/design-studio/personal/page-exit" && descriptor.method.toUpperCase() === "PUT"))
  ) return;
  guardPreviewEffect({
    kind: "api",
    action: `${descriptor.method.toUpperCase()} ${descriptor.path}`,
    instruction: "perform this Stockroom action",
  });
}
