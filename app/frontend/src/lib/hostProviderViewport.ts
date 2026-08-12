import { guardPreviewEffect } from "../design-studio/previewEffects";

export interface ProviderViewport {
  componentId: string;
  visible: boolean;
  x: number;
  y: number;
  width: number;
  height: number;
}

type ManagedHostApi = {
  setProviderViewport?: (viewport: ProviderViewport) => void;
  providerCommand?: (request: ProviderCommandRequest) => void;
};

export type ProviderCommand = "back" | "forward" | "reload";

interface ProviderCommandRequest {
  componentId: string;
  command: ProviderCommand;
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

export function sendProviderCommand(componentId: string, command: ProviderCommand): void {
  const bridge = (window as unknown as { __STOCKROOM_HOST__?: ManagedHostApi })
    .__STOCKROOM_HOST__?.providerCommand;
  if (!bridge) return;
  guardPreviewEffect({
    kind: "provider-viewport",
    action: `using provider browser ${command}`,
    instruction: `use provider browser ${command}`,
  });
  bridge({ componentId, command });
}
