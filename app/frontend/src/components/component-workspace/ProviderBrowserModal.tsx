import { useCallback, useEffect, useState } from "react";
import {
  onProviderCloseRequest,
  providerHostAvailable,
  sendProviderCommand,
  type ProviderBrowserIdentity,
} from "../../lib/hostProviderViewport";
import { ModalShell } from "../primitives";
import { ProviderBrowserFrame } from "./ProviderBrowserFrame";

export function ProviderBrowserModal({
  identity,
  providerLabel,
  url,
  ready,
  canGoBack,
  canGoForward,
  loading,
  navigationError,
  stalled = false,
  navigateOnOpen = false,
  onRetry,
  onChooseAnother,
  onClose,
}: {
  identity: ProviderBrowserIdentity;
  providerLabel: string;
  url: string;
  ready: boolean;
  canGoBack?: boolean;
  canGoForward?: boolean;
  loading?: boolean;
  navigationError?: string;
  stalled?: boolean;
  navigateOnOpen?: boolean;
  onRetry?: () => void;
  onChooseAnother?: () => void;
  onClose: () => void;
}) {
  const title = `${providerLabel} Browser`;
  const [openError, setOpenError] = useState("");
  const [, bumpFrameRevision] = useState(0);
  useEffect(() => {
    setOpenError("");
  }, [identity.componentId, identity.providerId, identity.routeId, identity.sessionId, url]);
  useEffect(() => {
    if (!navigateOnOpen || !ready) return;
    let active = true;
    void sendProviderCommand(identity, "navigate", url).then((outcome) => {
      if (active) setOpenError(outcome.accepted ? "" : outcome.error);
    });
    return () => {
      active = false;
    };
  }, [identity, navigateOnOpen, ready, url]);
  const requestClose = useCallback(async () => {
    if (!providerHostAvailable()) {
      onClose();
      return;
    }
    const closeCommand = sendProviderCommand(identity, "close");
    // The React surface is always recoverable. Its viewport cleanup hides the native page even
    // when a superseded host route refuses this stale identity-bound command.
    onClose();
    await closeCommand.catch(() => undefined);
  }, [identity, onClose]);
  const retry = useCallback(() => {
    setOpenError("");
    onRetry?.();
  }, [onRetry]);
  const chooseAnother = useCallback(() => {
    setOpenError("");
    onChooseAnother?.();
  }, [onChooseAnother]);
  useEffect(
    () => onProviderCloseRequest(identity, () => void requestClose()),
    [identity, requestClose],
  );
  return (
    <ModalShell
      open
      title={title}
      label={title}
      onClose={() => void requestClose()}
      size="full"
      devId="component-browser.provider-modal"
      closeDevId="component-browser.provider-close"
      headerDevId="component-browser.provider-modal-drag"
      bodyDevId="component-browser.provider-modal-body"
      movable
      resizable
      onFrameMove={() => bumpFrameRevision((revision) => revision + 1)}
      frameStyle={{
        width: "min(1180px, calc(100vw - 48px))",
        height: "72vh",
      }}
      frameClassName="max-h-[calc(100vh-48px)] min-h-[min(420px,calc(100vh-48px))] max-w-[calc(100vw-48px)] min-w-[min(640px,calc(100vw-48px))]"
    >
      <ProviderBrowserFrame
        identity={identity}
        providerLabel={providerLabel}
        url={url}
        ready={ready}
        canGoBack={canGoBack}
        canGoForward={canGoForward}
        loading={loading}
        navigationError={openError || navigationError}
        stalled={stalled}
        onRetry={onRetry ? retry : undefined}
        onChooseAnother={onChooseAnother ? chooseAnother : undefined}
      />
    </ModalShell>
  );
}
