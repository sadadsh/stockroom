import { useCallback, useLayoutEffect, useRef, useState } from "react";
import { sendProviderCommand, setProviderViewport } from "../../lib/hostProviderViewport";
import { Text, useCopyFormatter, useText } from "../../lib/copy";
import { Button } from "../primitives";

export function ProviderBrowserFrame({
  componentId,
  providerLabel,
  url,
  onClose,
}: {
  componentId: string;
  providerLabel: string;
  url: string;
  onClose?: () => void;
}) {
  const viewportRef = useRef<HTMLDivElement | null>(null);
  const backLabel = useText("component-browser.manage-models-back", "Back");
  const forwardLabel = useText("component-browser.manage-models-forward", "Forward");
  const reloadLabel = useText("component-browser.manage-models-reload", "Reload");
  const closeLabel = useText("component-browser.manage-models-close", "Close Provider");
  const addressLabel = useText("component-browser.manage-models-address", "Provider Address");
  const browserLabel = useCopyFormatter(
    "component-browser.manage-models-browser-label",
    "{provider} Browser",
  );
  const [address, setAddress] = useState(url);

  function navigate() {
    const typed = address.trim();
    if (!typed) return;
    let parsed: URL;
    try {
      parsed = new URL(typed.includes("://") ? typed : `https://${typed}`);
    } catch {
      return;
    }
    if (parsed.protocol !== "https:" || parsed.username || parsed.password) return;
    setAddress(parsed.href);
    sendProviderCommand(componentId, "navigate", parsed.href);
  }

  const publish = useCallback(() => {
    const element = viewportRef.current;
    if (!element) return;
    const bounds = element.getBoundingClientRect();
    try {
      setProviderViewport({
        componentId,
        visible: bounds.width > 0 && bounds.height > 0,
        x: bounds.x,
        y: bounds.y,
        width: bounds.width,
        height: bounds.height,
      });
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
          onClick={() => sendProviderCommand(componentId, "back")}
        >
          ←
        </Button>
        <Button
          type="button"
          small
          data-dev-id="component-browser.provider-forward"
          aria-label={forwardLabel}
          onClick={() => sendProviderCommand(componentId, "forward")}
        >
          →
        </Button>
        <Button
          type="button"
          small
          data-dev-id="component-browser.provider-reload"
          aria-label={reloadLabel}
          onClick={() => sendProviderCommand(componentId, "reload")}
        >
          ↻
        </Button>
        <span className="ml-1 truncate text-xs font-medium text-t1">{providerLabel}</span>
        <form
          className="flex min-w-0 flex-1"
          onSubmit={(event) => {
            event.preventDefault();
            navigate();
          }}
        >
          <input
            type="text"
            aria-label={addressLabel}
            value={address}
            onChange={(event) => setAddress(event.target.value)}
            className="min-w-0 flex-1 rounded-control border border-line bg-surface px-2 py-1 text-xs text-t2 outline-none focus:border-focus"
          />
        </form>
        {address.startsWith("https://") ? (
          <span className="text-xs text-positive">
            <Text id="component-browser.manage-models-secure">Secure</Text>
          </span>
        ) : null}
        {onClose ? (
          <Button
            type="button"
            small
            data-dev-id="component-browser.provider-close"
            aria-label={closeLabel}
            title={closeLabel}
            onClick={() => {
              sendProviderCommand(componentId, "close");
              onClose();
            }}
          >
            ×
          </Button>
        ) : null}
      </div>
      <div
        ref={viewportRef}
        data-dev-id="component-browser.provider-viewport"
        className="relative m-1 mt-0 flex min-h-0 flex-1 items-center justify-center overflow-hidden bg-surface text-sm text-t3"
      >
        <Text id="component-browser.manage-models-browser-ready">Provider Page</Text>
      </div>
    </div>
  );
}
