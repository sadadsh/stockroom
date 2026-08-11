/**
 * Shared Escape ownership for transient UI layers.
 *
 * Modals and lightweight popovers have different focus and paint contracts, but they share one
 * keyboard invariant: the newest open layer owns Escape, and one press dismisses one layer. Every
 * participating surface registers here so app shells and older page shortcuts cannot answer the
 * same keypress.
 */
import { useEffect, useRef } from "react";

// Open order is ownership order. An array is intentional: the newest layer is the top layer.
const escapeLayers: object[] = [];

/** Number of registered transient layers currently owning Escape above the application shell. */
export function openEscapeLayerCount(): number {
  return escapeLayers.length;
}

/** Register a transient layer and dismiss it only when it is the top Escape owner. */
export function useEscapeDismiss(open: boolean, onDismiss: () => void): void {
  const tokenRef = useRef<object>({});
  const dismissRef = useRef(onDismiss);
  dismissRef.current = onDismiss;

  useEffect(() => {
    if (!open) return;
    const token = tokenRef.current;
    escapeLayers.push(token);

    function onKey(event: KeyboardEvent) {
      if (event.key !== "Escape") return;
      if (escapeLayers[escapeLayers.length - 1] !== token) return;
      event.preventDefault();
      // Capture at window and stop sibling listeners too: stopPropagation alone does not suppress
      // another listener attached to window, which is the bug this shared owner resolves.
      event.stopImmediatePropagation();
      dismissRef.current();
    }

    window.addEventListener("keydown", onKey, true);
    return () => {
      window.removeEventListener("keydown", onKey, true);
      const index = escapeLayers.indexOf(token);
      if (index >= 0) escapeLayers.splice(index, 1);
    };
  }, [open]);
}
