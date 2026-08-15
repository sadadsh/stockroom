/**
 * The one modal frame, and the pieces every modal is built from.
 *
 * Four windows had hand-written their own scrim, their own 38px header, their own close control
 * and their own body padding, and they had drifted: two closed with an icon in the corner, two
 * with a text button; one trapped Tab and one did not; and two of them shared a z-index, which is
 * what made nesting a diff overlay inside a sheet impossible (see `lib/useModalDismiss.ts`).
 *
 * A modal is also the ONLY surface in this app allowed to scroll. The routes are fixed-height by
 * contract, so anything longer than the band it was given comes here - which means the body's
 * overflow behaviour is a decision this shell owns rather than one each caller re-derives.
 */
import type { ReactNode } from "react";
import { useModalDismiss } from "../lib/useModalDismiss";
import { useText } from "../lib/copy";
import { CloseIcon } from "./icons";

/**
 * How much room the window takes, and what its body does with overflow.
 *
 *   sheet - a reading surface. The body SCROLLS; this is the exhaustive-sheet case.
 *   stage - a viewport for one rendered artifact. The body does NOT scroll; the artifact pans.
 *   full  - a stage that takes the whole window, for inspecting something at size.
 *
 * Every size is capped against the viewport rather than a fixed pixel height, so the frame holds
 * at 960x640 instead of assuming the 1600px window it was designed on.
 */
export type ModalSize = "compact" | "sheet" | "stage" | "full";

const FRAME: Record<ModalSize, string> = {
  compact: "max-h-[calc(100vh-32px)] w-[min(380px,calc(100vw-32px))]",
  sheet: "max-h-[calc(100vh-32px)] w-[min(1100px,calc(100vw-32px))]",
  stage: "h-[min(80vh,680px)] w-[min(860px,calc(100vw-32px))]",
  full: "h-[calc(100vh-24px)] max-h-[1100px] w-[calc(100vw-24px)] max-w-[1600px]",
};

const BODY: Record<ModalSize, string> = {
  compact: "min-h-0 flex-1 overflow-y-auto p-4",
  // The one place a scrollbar is welcome: an overlay is not the page.
  sheet: "min-h-0 flex-1 overflow-y-auto p-4",
  stage: "relative min-h-0 flex-1 bg-field",
  full: "relative min-h-0 flex-1 bg-field",
};

/** The 38px title band. A separate family from the 34px docked route header, consistently. */
export function ModalHeader({
  title,
  onClose,
  closeDevId,
  devId,
  children,
}: {
  title: ReactNode;
  onClose: () => void;
  closeDevId?: string;
  devId?: string;
  /** Anything that belongs between the title and the close control (a tablist, a kind label). */
  children?: ReactNode;
}) {
  const closeLabel = useText("modal.close", "Close");
  return (
    <div
      data-dev-id={devId}
      className="flex h-[38px] flex-none items-center gap-3 border-b border-line bg-band px-4"
    >
      <span className="min-w-0 flex-1 truncate text-xs font-semibold text-t1">{title}</span>
      {children}
      {/* ONE close treatment for every window. Two of these were a text button and two were an
          icon, which made the same action look like two different affordances depending on which
          window you were in. The label stays in the DOM via aria-label + title. */}
      <button
        type="button"
        data-dev-id={closeDevId}
        aria-label={closeLabel}
        title={closeLabel}
        onClick={onClose}
        className="flex-none rounded-control p-1 text-t3 transition-colors hover:text-t1 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus"
      >
        <CloseIcon />
      </button>
    </div>
  );
}

/**
 * The action bar at the foot of a modal.
 *
 * Right-aligned, cancel before confirm, one primary at most. The hierarchy is the point: a row
 * of three equally-weighted buttons asks the person to read all three before choosing.
 */
export function ModalActions({
  devId,
  children,
  className,
}: {
  devId?: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <div
      data-dev-id={devId}
      className={
        "flex flex-none flex-wrap items-center justify-end gap-2 border-t border-line px-4 py-3" +
        (className ? ` ${className}` : "")
      }
    >
      {children}
    </div>
  );
}

/**
 * The whole window: scrim, frame, header, body, and an optional action bar.
 *
 * z-index and Escape both come from the modal stack, so a modal opened from inside another one
 * paints above it and closes on its own, without either window knowing the other exists.
 */
export function ModalShell({
  open,
  title,
  onClose,
  size = "sheet",
  devId,
  scrimDevId,
  closeDevId,
  headerDevId,
  bodyDevId,
  headerExtra,
  actions,
  actionsDevId,
  label,
  children,
}: {
  open: boolean;
  title: string;
  onClose: () => void;
  size?: ModalSize;
  devId?: string;
  scrimDevId?: string;
  closeDevId?: string;
  headerDevId?: string;
  /** The body IS the stage for a `stage` or `full` window, so it takes that window's id. */
  bodyDevId?: string;
  headerExtra?: ReactNode;
  actions?: ReactNode;
  actionsDevId?: string;
  /** The dialog's accessible name, when it should read differently from the visible title. */
  label?: string;
  children: ReactNode;
}) {
  const { ref, zIndex } = useModalDismiss(open, onClose);
  if (!open) return null;
  return (
    <div
      // An inline z-index, not a Tailwind class: an arbitrary value built from a template literal
      // produces a class name with no CSS behind it, which would silently delete the stacking.
      style={{ zIndex }}
      data-dev-id={scrimDevId}
      className="fixed inset-0 flex items-center justify-center bg-scrim p-4"
      role="presentation"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div
        ref={ref}
        data-dev-id={devId}
        role="dialog"
        aria-modal="true"
        aria-label={label ?? title}
        tabIndex={-1}
        className={`flex flex-col overflow-hidden rounded-card border border-line2 bg-popover shadow-pop outline-none ${FRAME[size]}`}
      >
        <ModalHeader
          title={title}
          onClose={onClose}
          devId={headerDevId}
          closeDevId={closeDevId}
        >
          {headerExtra}
        </ModalHeader>
        <div data-dev-id={bodyDevId} className={BODY[size]}>
          {children}
        </div>
        {actions ? <ModalActions devId={actionsDevId}>{actions}</ModalActions> : null}
      </div>
    </div>
  );
}
