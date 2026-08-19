import { useCallback, useLayoutEffect, useRef, useState } from "react";
import {
  sendProviderCommand,
  setProviderViewport,
  type ProviderViewport,
} from "../../lib/hostProviderViewport";
import { Text, useCopyFormatter, useText } from "../../lib/copy";
import { Icon } from "../Icon";
import { Button, StatusText } from "../primitives";

export function ProviderBrowserFrame({
  componentId,
  providerLabel,
  url,
  ready = true,
  canGoBack = false,
  canGoForward = false,
  loading = false,
  navigationError = "",
  onClose,
}: {
  componentId: string;
  providerLabel: string;
  url: string;
  ready?: boolean;
  canGoBack?: boolean;
  canGoForward?: boolean;
  loading?: boolean;
  navigationError?: string;
  onClose?: () => void;
}) {
  const viewportRef = useRef<HTMLDivElement | null>(null);
  const lastViewportRef = useRef<ProviderViewport | null>(null);
  const backLabel = useText("component-browser.manage-models-back", "Back");
  const forwardLabel = useText("component-browser.manage-models-forward", "Forward");
  const reloadLabel = useText("component-browser.manage-models-reload", "Reload");
  const closeLabel = useText("component-browser.manage-models-hide", "Hide Provider");
  const addressLabel = useText(
    "component-browser.manage-models-current-address",
    "Current provider address",
  );
  const browserLabel = useCopyFormatter(
    "component-browser.manage-models-browser-label",
    "{provider} Browser",
  );
  const [commandError, setCommandError] = useState<string | null>(null);
  let visibleAddress = providerLabel;
  try {
    const parsed = new URL(url);
    visibleAddress = `${parsed.hostname.replace(/^www\./, "")}${parsed.pathname === "/" ? "" : parsed.pathname}`;
  } catch {
    // The authoritative navigation error remains visible below the toolbar.
  }

  function command(name: "back" | "forward" | "reload") {
    setCommandError(null);
    if (!ready) return;
    if (!sendProviderCommand(componentId, name)) {
      setCommandError("The embedded provider browser is unavailable in this host.");
    }
  }

  const publish = useCallback(() => {
    const element = viewportRef.current;
    if (!element) return;
    const bounds = element.getBoundingClientRect();
    const viewport: ProviderViewport = {
      componentId,
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
  }, [componentId]);

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
          componentId,
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
  }, [componentId, publish]);

  // Workspace movement changes only x/y; ResizeObserver deliberately does not fire for position.
  // Publish after every committed parent render so host geometry keeps the native WebView on the
  // exact React placeholder throughout window movement and resizing.
  useLayoutEffect(() => publish());

  return (
    <div
      role="region"
      aria-label={browserLabel({ provider: providerLabel })}
      data-testid="provider-browser-pane"
      className="flex min-h-0 flex-1 flex-col"
    >
      <div className="flex h-[36px] flex-none items-center gap-1 border-b border-line bg-band px-2">
        <Button
          type="button"
          small
          data-dev-id="component-browser.provider-back"
          aria-label={backLabel}
          disabled={!canGoBack}
          icon={<Icon id="nav.back" className="h-3.5 w-3.5" />}
          onClick={() => command("back")}
        />
        <Button
          type="button"
          small
          data-dev-id="component-browser.provider-forward"
          aria-label={forwardLabel}
          disabled={!canGoForward}
          icon={<Icon id="nav.back" className="h-3.5 w-3.5 rotate-180" />}
          onClick={() => command("forward")}
        />
        <Button
          type="button"
          small
          data-dev-id="component-browser.provider-reload"
          aria-label={reloadLabel}
          disabled={!ready}
          icon={<Icon id="action.refresh" className="h-3.5 w-3.5" />}
          onClick={() => command("reload")}
        />
        <span className="ml-1 flex-none text-xs font-semibold text-t1">{providerLabel}</span>
        <span className="h-3 w-px flex-none bg-line" aria-hidden="true" />
        <p
          aria-label={addressLabel}
          title={url}
          className="min-w-0 flex-1 truncate text-xs text-t3"
        >
          {visibleAddress}
        </p>
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
              sendProviderCommand(componentId, "close");
              onClose();
            }}
          />
        ) : null}
      </div>
      {commandError || navigationError ? (
        <div role="alert" className="flex-none border-b border-line bg-warn-soft px-2 py-1 text-xs text-warn-text">
          {commandError || navigationError}
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
