/**
 * The one overlay the component workspace opens.
 *
 * The workspace itself never scrolls, so anything longer than the band it is given (the full
 * specification sheet, the full sourcing ladder, the source ledger, one representation's evidence)
 * has to live somewhere that MAY scroll. That is this - the same scrim idiom as the preview and
 * diff dialogs, so a person meets one overlay behaviour in the app rather than three.
 */
import type { ReactNode } from "react";
import { useModalDismiss } from "../../lib/useModalDismiss";
import { useText } from "../../lib/copy";
import { CloseIcon } from "../icons";

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
  const dialogRef = useModalDismiss(open, onClose);
  const closeLabel = useText("component-browser.modal-close", "Close");
  if (!open) return null;
  return (
    <div
      className="fixed inset-0 z-[110] flex items-center justify-center bg-black/50 p-4"
      role="presentation"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div
        ref={dialogRef}
        data-dev-id="component-browser.modal"
        role="dialog"
        aria-modal="true"
        aria-label={title}
        tabIndex={-1}
        className="flex max-h-[calc(100vh-32px)] w-[min(1100px,calc(100vw-32px))] flex-col overflow-hidden rounded-card border border-line2 bg-popover shadow-pop outline-none"
      >
        <div className="flex h-[38px] flex-none items-center gap-3 border-b border-line bg-band px-4">
          <span className="min-w-0 flex-1 truncate text-xs font-semibold text-t1">{title}</span>
          <button
            type="button"
            data-dev-id="component-browser.modal-close"
            aria-label={closeLabel}
            onClick={onClose}
            className="flex-none rounded-control p-1 text-t3 transition-colors hover:text-t1 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-acc"
          >
            <CloseIcon />
          </button>
        </div>
        {/* The ONE place a scrollbar is welcome: an overlay is not the page. */}
        <div className="min-h-0 flex-1 overflow-y-auto p-4">{children}</div>
      </div>
    </div>
  );
}
