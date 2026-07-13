/**
 * An in-window confirm dialog. Per the design spec everything happens in-window
 * (the only OS dialogs are the file pickers the OS owns), so destructive actions
 * confirm through this scrim-and-card, never a native prompt. Clicking the scrim
 * or Escape cancels; the confirm button carries the danger tone when destructive.
 */
import { useEffect, type ReactNode } from "react";
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
      className="fixed inset-0 z-[90] flex items-center justify-center bg-black/50 p-4"
      role="presentation"
      onClick={onCancel}
    >
      <div
        className="w-full max-w-[380px] rounded-card border border-line bg-raise p-5 shadow-pop"
        role="dialog"
        aria-modal="true"
        aria-label={title}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="text-base font-semibold text-t1">{title}</div>
        <div className="mt-2 text-sm text-t2">{body}</div>
        <div className="mt-4 flex justify-end gap-2">
          <Button small onClick={onCancel} disabled={busy}>
            Cancel
          </Button>
          <Button
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
