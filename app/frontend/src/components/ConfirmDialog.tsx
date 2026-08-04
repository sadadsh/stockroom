/**
 * An in-window confirm dialog. Per the design spec everything happens in-window
 * (the only OS dialogs are the file pickers the OS owns), so destructive actions
 * confirm through this scrim-and-card, never a native prompt. Clicking the scrim
 * or Escape cancels; the confirm button carries the danger tone when destructive.
 */
import type { ReactNode } from "react";
import { Text } from "../lib/copy";
import { useModalDismiss } from "../lib/useModalDismiss";
import { Button, ModalActions } from "./primitives";

interface Props {
  open: boolean;
  title: string;
  body: ReactNode;
  confirmLabel: string;
  danger?: boolean;
  busy?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}

export function ConfirmDialog({
  open,
  title,
  body,
  confirmLabel,
  danger = false,
  busy = false,
  onConfirm,
  onCancel,
}: Props) {
  // The stack, not a private Escape listener. This dialog is opened FROM other surfaces (a part
  // row, a settings section, and potentially from inside a modal), and its own listener plus a
  // fixed z-[90] meant a confirm raised over an open modal both sat behind it and shared its
  // Escape. It also had no focus trap at all while every sibling window had one.
  const { ref, zIndex } = useModalDismiss(open, onCancel);

  if (!open) return null;

  return (
    <div
      data-dev-id="confirm.scrim"
      style={{ zIndex }}
      className="fixed inset-0 flex items-center justify-center bg-black/50 p-4"
      role="presentation"
      onClick={onCancel}
    >
      <div
        ref={ref}
        data-dev-id="confirm.root"
        className="w-full max-w-[380px] overflow-hidden rounded-card border border-line bg-popover shadow-pop outline-none"
        role="dialog"
        aria-modal="true"
        aria-label={title}
        tabIndex={-1}
        onClick={(e) => e.stopPropagation()}
      >
        <div data-dev-id="confirm.title" className="flex h-[34px] flex-none items-center border-b border-line bg-band px-4 text-sm font-semibold text-t1">{title}</div>
        <div data-dev-id="confirm.body" className="px-4 pt-3 text-sm text-t2">{body}</div>
        {/* The shared action bar: right-aligned, cancel before confirm, one primary. */}
        <ModalActions devId="confirm.actions" className="border-t-0 pt-3.5">
          <Button data-dev-id="confirm.cancel" small onClick={onCancel} disabled={busy}>
            <Text id="modal.confirm.cancel">Cancel</Text>
          </Button>
          <Button
            data-dev-id="confirm.confirm"
            small
            variant={danger ? "danger" : "accent"}
            onClick={onConfirm}
            disabled={busy}
          >
            {confirmLabel}
          </Button>
        </ModalActions>
      </div>
    </div>
  );
}
