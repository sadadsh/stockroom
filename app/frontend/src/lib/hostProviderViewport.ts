import { guardPreviewEffect } from "../design-studio/previewEffects";

export interface ProviderBrowserIdentity {
  componentId: string;
  providerId: string;
  routeId: string;
  sessionId: string;
}

export interface ProviderViewport extends ProviderBrowserIdentity {
  visible: boolean;
  x: number;
  y: number;
  width: number;
  height: number;
}

type ManagedHostApi = {
  setProviderViewport?: (viewport: ProviderViewport) => void;
  providerCommand?: (request: ProviderCommandRequest) => boolean | Promise<boolean>;
};

export type ProviderCommand = "back" | "forward" | "reload" | "close" | "navigate";

interface ProviderCommandRequest extends ProviderBrowserIdentity {
  command: ProviderCommand;
  url?: string;
}

export interface ProviderCommandOutcome {
  accepted: boolean;
  error: string;
}

const PROVIDER_CLOSE_REQUEST_EVENT = "stockroom:provider-close-requested";

function sameIdentity(left: ProviderBrowserIdentity, right: ProviderBrowserIdentity): boolean {
  return left.componentId === right.componentId
    && left.providerId === right.providerId
    && left.routeId === right.routeId
    && left.sessionId === right.sessionId;
}

export function onProviderCloseRequest(
  identity: ProviderBrowserIdentity,
  onClose: () => void,
): () => void {
  function listener(event: Event) {
    const detail = (event as CustomEvent<ProviderBrowserIdentity>).detail;
    if (detail && sameIdentity(identity, detail)) onClose();
  }
  window.addEventListener(PROVIDER_CLOSE_REQUEST_EVENT, listener);
  return () => window.removeEventListener(PROVIDER_CLOSE_REQUEST_EVENT, listener);
}

export function setProviderViewport(viewport: ProviderViewport): void {
  const bridge = (window as unknown as { __STOCKROOM_HOST__?: ManagedHostApi })
    .__STOCKROOM_HOST__?.setProviderViewport;
  if (!bridge) return;
  guardPreviewEffect({
    kind: "provider-viewport",
    action: "placing the native provider browser",
    instruction: "place the provider browser",
  });
  bridge(viewport);
}

export function providerHostAvailable(): boolean {
  return typeof (window as unknown as { __STOCKROOM_HOST__?: ManagedHostApi })
    .__STOCKROOM_HOST__?.providerCommand === "function";
}

function commandLabel(command: ProviderCommand): string {
  return command === "navigate"
    ? "Navigate"
    : command.charAt(0).toUpperCase() + command.slice(1);
}

export async function sendProviderCommand(
  identity: ProviderBrowserIdentity,
  command: ProviderCommand,
  url?: string,
): Promise<ProviderCommandOutcome> {
  const bridge = (window as unknown as { __STOCKROOM_HOST__?: ManagedHostApi })
    .__STOCKROOM_HOST__?.providerCommand;
  if (!bridge) {
    return {
      accepted: false,
      error: "The embedded provider browser is unavailable in this host.",
    };
  }
  guardPreviewEffect({
    kind: "provider-viewport",
    action: `using provider browser ${command}`,
    instruction: `use provider browser ${command}`,
  });
  try {
    const accepted = await bridge({
      ...identity,
      command,
      ...(url === undefined ? {} : { url }),
    });
    return accepted
      ? { accepted: true, error: "" }
      : {
          accepted: false,
          error: `The embedded provider browser refused ${commandLabel(command)}.`,
        };
  } catch (error) {
    return {
      accepted: false,
      error: error instanceof Error && error.message
        ? error.message
        : `The embedded provider browser could not execute ${commandLabel(command)}.`,
    };
  }
}
