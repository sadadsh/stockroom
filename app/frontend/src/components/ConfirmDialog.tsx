/**
 * An in-window confirm dialog. Per the design spec everything happens in-window
 * (the only OS dialogs are the file pickers the OS owns), so destructive actions
 * confirm through this scrim-and-card, never a native prompt. Clicking the scrim
 * or Escape cancels; the confirm button carries the danger tone when destructive.
 */
import { useEffect, type ReactNode } from "react";
import { Text } from "../lib/copy";
import { Button } from "./primitives";

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
  useEffect(() => {
    if (!open) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onCancel();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onCancel]);

  if (!open) return null;

  return (
    <div
      data-dev-id="confirm.scrim"
      className="fixed inset-0 z-[90] flex items-center justify-center bg-black/50 p-4"
      role="presentation"
      onClick={onCancel}
    >
      <div
        data-dev-id="confirm.root"
        className="w-full max-w-[380px] overflow-hidden rounded-card border border-line bg-popover shadow-pop"
        role="dialog"
        aria-modal="true"
        aria-label={title}
        onClick={(e) => e.stopPropagation()}
      >
        <div data-dev-id="confirm.title" className="flex h-[34px] flex-none items-center border-b border-line bg-band px-4 text-sm font-semibold text-t1">{title}</div>
        <div data-dev-id="confirm.body" className="px-4 pt-3 text-sm text-t2">{body}</div>
        <div data-dev-id="confirm.actions" className="flex justify-end gap-2 px-4 pb-4 pt-3.5">
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
        </div>
      </div>
    </div>
  );
}
