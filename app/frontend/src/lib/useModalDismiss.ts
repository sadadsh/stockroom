/**
 * The modal STACK: Escape-to-close, a Tab focus-trap, an ascending z-index, and focus-restore,
 * for every in-window modal in the app.
 *
 * It used to be a per-modal hook with no notion of other modals, and that was a real bug rather
 * than an omission. `DiffModal` and `WorkspaceModal` were both `z-[110]` and BOTH attached their
 * own `keydown` listener to `window`, so opening one inside the other meant a single Escape ran
 * two `onClose` handlers and closed both, while equal z-index left which one painted on top to
 * mount order. That is why the visual diff overlay in Sources & History could not be built: there
 * was nowhere safe to nest it.
 *
 * So every open modal registers a LAYER here, and the rules follow from the stack:
 *
 *   - Escape is answered by the TOP layer only, so one press closes one modal.
 *   - Tab is trapped by the TOP layer only, so focus cannot wander into the modal underneath.
 *   - z-index ascends with depth, so paint order is decided by nesting, not by mount order.
 *   - focus returns to the control that opened the layer, so closing a nested modal lands back
 *     inside its parent rather than on the page behind both.
 *
 * Registration is push-order, which is open-order: a nested modal is opened by a control inside
 * the modal that already exists, so the parent is always on the stack first.
 */
import { useEffect, useRef, useSyncExternalStore, type RefObject } from "react";

// One opaque token per open layer. An array, not a Set, because the ORDER is the whole point.
const stack: object[] = [];
const listeners = new Set<() => void>();

function emit(): void {
  // Copied before iteration: a listener that unsubscribes while we notify must not shorten the
  // set mid-loop and silently skip the layer after it.
  for (const listener of [...listeners]) listener();
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

/** The scrim z-index of the bottom-most open modal. */
export const MODAL_BASE_Z = 110;
/** How far each nested layer sits above the one it opened from. */
export const MODAL_Z_STEP = 10;

/** The z-index for a layer at `depth`. Depth -1 (not yet registered) reads as the base. */
export function modalZIndex(depth: number): number {
  return MODAL_BASE_Z + Math.max(0, depth) * MODAL_Z_STEP;
}

/** How many modals are open. Exported for tests and for reasoning about the stack. */
export function openModalCount(): number {
  return stack.length;
}

/** The focusable descendants of a dialog, in tab order. */
const FOCUSABLE =
  'button:not([disabled]), a[href], input:not([disabled]), select:not([disabled]), ' +
  'textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

export interface ModalLayer {
  /** Attach to the dialog element. The trap and the initial focus both read it. */
  ref: RefObject<HTMLDivElement>;
  /** 0 for the bottom-most open modal, 1 for one opened from inside it, and so on. */
  depth: number;
  /** Whether this layer answers Escape and traps Tab. Exactly one open layer is the top. */
  isTop: boolean;
  /** The scrim's z-index. Apply as an inline style: a Tailwind class built from a template
   *  literal produces a class name with no CSS behind it. */
  zIndex: number;
}

export function useModalDismiss(open: boolean, onClose: () => void): ModalLayer {
  const dialogRef = useRef<HTMLDivElement>(null);
  const restoreFocusRef = useRef<HTMLElement | null>(null);
  // A stable identity for this modal instance, independent of its props.
  const tokenRef = useRef<object>({});
  const token = tokenRef.current;

  // Join the stack while open. The cleanup runs both when `open` goes false and when the modal
  // unmounts outright, so a modal that is removed from the tree still leaves the stack.
  useEffect(() => {
    if (!open) return;
    stack.push(token);
    emit();
    return () => {
      const index = stack.indexOf(token);
      if (index >= 0) stack.splice(index, 1);
      emit();
    };
  }, [open, token]);

  const depth = useSyncExternalStore(
    subscribe,
    () => stack.indexOf(token),
    // Server/prerender: no stack, so no layer.
    () => -1,
  );

  // Remember where focus was, move it into the dialog, and put it back on the way out. The
  // restore lives in the CLEANUP rather than in an `else` branch so it also runs for a modal
  // that is unmounted while open (several windows here render only when open and never pass
  // `open={false}`), which is exactly the case that used to strand focus on inert background.
  useEffect(() => {
    if (!open) return;
    restoreFocusRef.current =
      document.activeElement instanceof HTMLElement ? document.activeElement : null;
    dialogRef.current?.focus();
    return () => {
      const target = restoreFocusRef.current;
      restoreFocusRef.current = null;
      // `isConnected` because the invoker may itself have been unmounted by the action that
      // closed the modal; focusing a detached node silently moves focus to <body>.
      if (target && target.isConnected) target.focus();
    };
  }, [open]);

  useEffect(() => {
    if (!open) return;
    function onKey(e: KeyboardEvent) {
      // Read the stack at EVENT time, not at effect time: the top layer changes while this
      // listener is attached, and a captured `isTop` would be stale the moment one nested.
      if (stack[stack.length - 1] !== token) return;
      if (e.key === "Escape") {
        e.preventDefault();
        // Stop the same press reaching any other keydown listener (a page-level shortcut, an
        // older modal that has not yet detached): one Escape is one dismissal.
        e.stopPropagation();
        onClose();
        return;
      }
      if (e.key === "Tab") {
        const nodes = dialogRef.current?.querySelectorAll<HTMLElement>(FOCUSABLE);
        if (!nodes || nodes.length === 0) return;
        const first = nodes[0];
        const last = nodes[nodes.length - 1];
        const active = document.activeElement;
        // A focus that is OUTSIDE this dialog (it drifted, or the layer below still held it)
        // is pulled back in rather than left to walk the inert page behind the scrim.
        if (!(active instanceof Node) || !dialogRef.current?.contains(active)) {
          e.preventDefault();
          (e.shiftKey ? last : first).focus();
          return;
        }
        if (e.shiftKey && active === first) {
          e.preventDefault();
          last.focus();
        } else if (!e.shiftKey && active === last) {
          e.preventDefault();
          first.focus();
        }
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose, token]);

  return {
    ref: dialogRef,
    depth,
    isTop: depth >= 0 && depth === stack.length - 1,
    zIndex: modalZIndex(depth),
  };
}
