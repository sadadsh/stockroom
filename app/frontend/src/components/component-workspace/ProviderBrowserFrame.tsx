import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import {
  sendProviderCommand,
  setProviderViewport,
  type ProviderBrowserIdentity,
  type ProviderViewport,
} from "../../lib/hostProviderViewport";
import { Text, useCopyFormatter, useText } from "../../lib/copy";
import { Icon } from "../Icon";
import { Button, StatusText } from "../primitives";

export function ProviderBrowserFrame({
  identity,
  providerLabel,
  url,
  ready = true,
  canGoBack = false,
  canGoForward = false,
  loading = false,
  navigationError = "",
  stalled = false,
  onRetry,
  onChooseAnother,
  onClose,
}: {
  identity: ProviderBrowserIdentity;
  providerLabel: string;
  url: string;
  ready?: boolean;
  canGoBack?: boolean;
  canGoForward?: boolean;
  loading?: boolean;
  navigationError?: string;
  stalled?: boolean;
  onRetry?: () => void;
  onChooseAnother?: () => void;
  onClose?: () => void;
}) {
  const viewportRef = useRef<HTMLDivElement | null>(null);
  const lastViewportRef = useRef<ProviderViewport | null>(null);
  const backLabel = useText("component-browser.manage-models-back", "Back");
  const forwardLabel = useText("component-browser.manage-models-forward", "Forward");
  const reloadLabel = useText("component-browser.manage-models-reload", "Reload");
  const closeLabel = useText("component-browser.manage-models-hide", "Hide Provider");
  const providerAddressLabel = useText(
    "component-browser.manage-models-provider-address",
    "Provider Address",
  );
  const goLabel = useText("component-browser.manage-models-go", "Go");
  const addressLabel = useText(
    "component-browser.manage-models-current-address",
    "Current provider address",
  );
  const browserLabel = useCopyFormatter(
    "component-browser.manage-models-browser-label",
    "{provider} Browser Page",
  );
  const [commandError, setCommandError] = useState<string | null>(null);
  const [address, setAddress] = useState(url);
  const [commandPending, setCommandPending] = useState(false);
  useEffect(() => setAddress(url), [url]);
  let visibleAddress = providerLabel;
  try {
    const parsed = new URL(url);
    visibleAddress = `${parsed.hostname.replace(/^www\./, "")}${parsed.pathname === "/" ? "" : parsed.pathname}`;
  } catch {
    // The authoritative navigation error remains visible below the toolbar.
  }

  async function command(
    name: "back" | "forward" | "reload" | "navigate" | "close",
    target?: string,
  ) {
    setCommandError(null);
    if (!ready) return;
    setCommandPending(true);
    const outcome = await sendProviderCommand(identity, name, target);
    setCommandPending(false);
    if (!outcome.accepted) setCommandError(outcome.error);
  }

  const publish = useCallback(() => {
    const element = viewportRef.current;
    if (!element) return;
    const bounds = element.getBoundingClientRect();
    const viewport: ProviderViewport = {
      ...identity,
      visible: bounds.width > 0 && bounds.height > 0,
      x: bounds.x,
      y: bounds.y,
      width: bounds.width,
      height: bounds.height,
    };
    const previous = lastViewportRef.current;
    if (
      previous
      && previous.componentId === viewport.componentId
      && previous.providerId === viewport.providerId
      && previous.routeId === viewport.routeId
      && previous.sessionId === viewport.sessionId
      && previous.visible === viewport.visible
      && previous.x === viewport.x
      && previous.y === viewport.y
      && previous.width === viewport.width
      && previous.height === viewport.height
    ) return;
    try {
      setProviderViewport(viewport);
      lastViewportRef.current = viewport;
    } catch {
      // Design Studio preview refusal is already reported by the central effect guard.
    }
  }, [identity]);

  useLayoutEffect(() => {
    const element = viewportRef.current;
    if (!element) return;
    const observer = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(publish);
    observer?.observe(element);
    window.addEventListener("scroll", publish, true);
    window.addEventListener("resize", publish);
    return () => {
      observer?.disconnect();
      window.removeEventListener("scroll", publish, true);
      window.removeEventListener("resize", publish);
      lastViewportRef.current = null;
      try {
        setProviderViewport({
          ...identity,
          visible: false,
          x: 0,
          y: 0,
          width: 0,
          height: 0,
        });
      } catch {
        // Same preview-only refusal as above.
      }
    };
  }, [identity, publish]);

  // Workspace movement changes only x/y; ResizeObserver deliberately does not fire for position.
  // Publish after every committed parent render so host geometry keeps the native WebView on the
  // exact React placeholder throughout window movement and resizing.
  useLayoutEffect(() => publish());

  return (
    <div
      role="region"
      aria-label={browserLabel({ provider: providerLabel })}
      data-testid="provider-browser-pane"
      className="flex h-full min-h-0 flex-1 flex-col"
    >
      <div className="flex h-[36px] flex-none items-center gap-1 border-b border-line bg-band px-2">
        <Button
          type="button"
          small
          data-dev-id="component-browser.provider-back"
          aria-label={backLabel}
          disabled={!ready || commandPending || !canGoBack}
          icon={<Icon id="nav.back" className="h-3.5 w-3.5" />}
          onClick={() => void command("back")}
        />
        <Button
          type="button"
          small
          data-dev-id="component-browser.provider-forward"
          aria-label={forwardLabel}
          disabled={!ready || commandPending || !canGoForward}
          icon={<Icon id="nav.forward" className="h-3.5 w-3.5" />}
          onClick={() => void command("forward")}
        />
        <Button
          type="button"
          small
          data-dev-id="component-browser.provider-reload"
          aria-label={reloadLabel}
          disabled={!ready || commandPending}
          icon={<Icon id="action.refresh" className="h-3.5 w-3.5" />}
          onClick={() => void command("reload")}
        />
        <span className="ml-1 flex-none text-xs font-semibold text-t1">{providerLabel}</span>
        <span className="h-3 w-px flex-none bg-line" aria-hidden="true" />
        <span
          aria-label={addressLabel}
          title={url}
          className="sr-only"
        >
          {visibleAddress}
        </span>
        <form
          className="flex min-w-0 flex-1 items-center gap-1"
          onSubmit={(event) => {
            event.preventDefault();
            void command("navigate", address.trim());
          }}
        >
          <input
            type="url"
            aria-label={providerAddressLabel}
            value={address}
            disabled={!ready || commandPending}
            onChange={(event) => setAddress(event.currentTarget.value)}
            className="h-[24px] min-w-0 flex-1 rounded-control border border-line2 bg-control px-2 text-xs text-t1 outline-none focus:border-focus"
          />
          <Button type="submit" small disabled={!ready || commandPending || !address.trim()}>
            {goLabel}
          </Button>
        </form>
        {loading ? (
          <StatusText tone="neutral" className="text-xs">
            <Text id="component-browser.manage-models-loading">Loading</Text>
          </StatusText>
        ) : null}
        {onClose ? (
          <Button
            type="button"
            small
            data-dev-id="component-browser.provider-close"
            aria-label={closeLabel}
            title={closeLabel}
            icon={<Icon id="action.close" className="h-3.5 w-3.5" />}
            onClick={() => {
              onClose();
              void command("close");
            }}
          />
        ) : null}
      </div>
      {commandError || navigationError ? (
        <div role="alert" className="flex flex-none items-center gap-2 border-b border-line bg-warn-soft px-2 py-1 text-xs text-warn-text">
          <span className="min-w-0 flex-1">{commandError || navigationError}</span>
          {stalled && onRetry ? (
            <Button type="button" small onClick={onRetry}>
              <Text id="component-browser.manage-models-browser-retry">Retry</Text>
            </Button>
          ) : null}
          {stalled && onChooseAnother ? (
            <Button type="button" small onClick={onChooseAnother}>
              <Text id="component-browser.manage-models-browser-choose-another">Choose Another Provider</Text>
            </Button>
          ) : null}
        </div>
      ) : null}
      <div
        ref={viewportRef}
        data-dev-id="component-browser.provider-viewport"
        className="relative m-1 mt-0 flex min-h-0 flex-1 items-center justify-center overflow-hidden bg-surface text-sm text-t3"
      >
        {ready ? (
          <Text id="component-browser.manage-models-browser-ready">Provider Page</Text>
        ) : (
          <Text id="component-browser.manage-models-browser-opening">Opening Provider...</Text>
        )}
      </div>
    </div>
  );
}
