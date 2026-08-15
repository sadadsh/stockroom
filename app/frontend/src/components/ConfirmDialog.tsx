/**
 * An in-window confirm dialog. Per the design spec everything happens in-window
 * (the only OS dialogs are the file pickers the OS owns), so destructive actions
 * confirm through this scrim-and-card, never a native prompt. Clicking the scrim
 * or Escape cancels; the confirm button carries the danger tone when destructive.
 */
import type { ReactNode } from "react";
import { Text } from "../lib/copy";
import { Button, ModalShell } from "./primitives";

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
  return (
    <ModalShell
      open={open}
      title={title}
      onClose={onCancel}
      size="compact"
      devId="confirm.root"
      scrimDevId="confirm.scrim"
      headerDevId="confirm.title"
      bodyDevId="confirm.body"
      actionsDevId="confirm.actions"
      actions={
        <>
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
        </>
      }
    >
      <div className="text-sm text-t2">{body}</div>
    </ModalShell>
  );
}
