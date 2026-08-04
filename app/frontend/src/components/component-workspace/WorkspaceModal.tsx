/**
 * The one overlay the component workspace opens.
 *
 * The workspace itself never scrolls, so anything longer than the band it is given (the full
 * specification sheet, the full sourcing ladder, the source ledger, one representation's evidence)
 * has to live somewhere that MAY scroll. That is this.
 *
 * It is now a thin binding of the shared `ModalShell` rather than its own scrim, header and close
 * control. That is what makes a diff overlay openable from inside it: the shell registers with the
 * modal stack, so a nested window paints above this one and takes Escape for itself instead of
 * both closing on one press.
 */
import type { ReactNode } from "react";
import { ModalShell } from "../primitives";

export function WorkspaceModal({
  open,
  title,
  onClose,
  children,
}: {
  open: boolean;
  title: string;
  onClose: () => void;
  children: ReactNode;
}) {
  return (
    <ModalShell
      open={open}
      title={title}
      onClose={onClose}
      size="sheet"
      devId="component-browser.modal"
      closeDevId="component-browser.modal-close"
    >
      {children}
    </ModalShell>
  );
}
