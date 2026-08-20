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
import {
  useRef,
  useState,
  type CSSProperties,
  type PointerEvent as ReactPointerEvent,
  type ReactNode,
} from "react";
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

const MODAL_VIEWPORT_MARGIN = 24;
type ModalResizeDirection =
  | "north"
  | "northeast"
  | "east"
  | "southeast"
  | "south"
  | "southwest"
  | "west"
  | "northwest";
const MODAL_RESIZE_DIRECTIONS: readonly ModalResizeDirection[] = [
  "north",
  "northeast",
  "east",
  "southeast",
  "south",
  "southwest",
  "west",
  "northwest",
];
const MODAL_RESIZE_CLASS: Record<ModalResizeDirection, string> = {
  north: "left-3 right-3 top-0 h-2 cursor-ns-resize",
  northeast: "right-0 top-0 h-3 w-3 cursor-nesw-resize",
  east: "bottom-3 right-0 top-3 w-2 cursor-ew-resize",
  southeast: "bottom-0 right-0 h-3 w-3 cursor-nwse-resize border-b-2 border-r-2 border-line2",
  south: "bottom-0 left-3 right-3 h-2 cursor-ns-resize",
  southwest: "bottom-0 left-0 h-3 w-3 cursor-nesw-resize",
  west: "bottom-3 left-0 top-3 w-2 cursor-ew-resize",
  northwest: "left-0 top-0 h-3 w-3 cursor-nwse-resize",
};

/** The 38px title band. A separate family from the 34px docked route header, consistently. */
export function ModalHeader({
  title,
  onClose,
  closeDevId,
  devId,
  movable = false,
  onPointerDown,
  onPointerMove,
  onPointerUp,
  children,
}: {
  title: ReactNode;
  onClose: () => void;
  closeDevId?: string;
  devId?: string;
  movable?: boolean;
  onPointerDown?: (event: ReactPointerEvent<HTMLDivElement>) => void;
  onPointerMove?: (event: ReactPointerEvent<HTMLDivElement>) => void;
  onPointerUp?: (event: ReactPointerEvent<HTMLDivElement>) => void;
  /** Anything that belongs between the title and the close control (a tablist, a kind label). */
  children?: ReactNode;
}) {
  const closeLabel = useText("modal.close", "Close");
  return (
    <div
      data-dev-id={devId}
      className={
        "flex h-[38px] flex-none items-center gap-3 border-b border-line bg-band px-4" +
        (movable ? " cursor-move touch-none select-none" : "")
      }
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
      onPointerCancel={onPointerUp}
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
  frameStyle,
  frameClassName,
  movable = false,
  resizable = false,
  onFrameMove,
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
  /** Initial frame dimensions; pointer resizing replaces only width and height. */
  frameStyle?: CSSProperties;
  /** Additional bounded frame behavior for specialized native-backed stages. */
  frameClassName?: string;
  /** Let a specialized modal move from its title bar while remaining inside the viewport. */
  movable?: boolean;
  /** Add eight pointer resize edges while retaining a visible app margin. */
  resizable?: boolean;
  /** Notify native-backed children that a transform changed their physical screen rectangle. */
  onFrameMove?: () => void;
  /** The dialog's accessible name, when it should read differently from the visible title. */
  label?: string;
  children: ReactNode;
}) {
  const { ref, zIndex } = useModalDismiss(open, onClose);
  const [offset, setOffset] = useState({ x: 0, y: 0 });
  const [frameSize, setFrameSize] = useState<{ width: number; height: number } | null>(null);
  const dragRef = useRef<{
    pointerId: number;
    startX: number;
    startY: number;
    offsetX: number;
    offsetY: number;
    minDeltaX: number;
    maxDeltaX: number;
    minDeltaY: number;
    maxDeltaY: number;
  } | null>(null);
  const resizeRef = useRef<{
    pointerId: number;
    direction: ModalResizeDirection;
    startX: number;
    startY: number;
    startWidth: number;
    startHeight: number;
    offsetX: number;
    offsetY: number;
    maxWidth: number;
    maxHeight: number;
  } | null>(null);
  function beginMove(event: ReactPointerEvent<HTMLDivElement>) {
    if (
      !movable
      || event.button !== 0
      || (event.target instanceof Element
        && event.target.closest("button, input, select, textarea, a"))
    ) return;
    const bounds = ref.current?.getBoundingClientRect();
    if (!bounds || bounds.width <= 0 || bounds.height <= 0) return;
    dragRef.current = {
      pointerId: event.pointerId,
      startX: event.clientX,
      startY: event.clientY,
      offsetX: offset.x,
      offsetY: offset.y,
      minDeltaX: MODAL_VIEWPORT_MARGIN - bounds.left,
      maxDeltaX: window.innerWidth - MODAL_VIEWPORT_MARGIN - bounds.right,
      minDeltaY: MODAL_VIEWPORT_MARGIN - bounds.top,
      maxDeltaY: window.innerHeight - MODAL_VIEWPORT_MARGIN - bounds.bottom,
    };
    event.currentTarget.setPointerCapture?.(event.pointerId);
    event.preventDefault();
  }
  function continueMove(event: ReactPointerEvent<HTMLDivElement>) {
    const drag = dragRef.current;
    if (!drag || drag.pointerId !== event.pointerId) return;
    const deltaX = Math.max(
      drag.minDeltaX,
      Math.min(drag.maxDeltaX, event.clientX - drag.startX),
    );
    const deltaY = Math.max(
      drag.minDeltaY,
      Math.min(drag.maxDeltaY, event.clientY - drag.startY),
    );
    const x = drag.offsetX + deltaX;
    const y = drag.offsetY + deltaY;
    setOffset({ x: Math.round(x), y: Math.round(y) });
    onFrameMove?.();
  }
  function endMove(event: ReactPointerEvent<HTMLDivElement>) {
    if (dragRef.current?.pointerId !== event.pointerId) return;
    if (event.currentTarget.hasPointerCapture?.(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
    dragRef.current = null;
  }
  function beginResize(
    event: ReactPointerEvent<HTMLButtonElement>,
    direction: ModalResizeDirection,
  ) {
    if (!resizable || event.button !== 0) return;
    const bounds = ref.current?.getBoundingClientRect();
    if (!bounds || bounds.width <= 0 || bounds.height <= 0) return;
    resizeRef.current = {
      pointerId: event.pointerId,
      direction,
      startX: event.clientX,
      startY: event.clientY,
      startWidth: bounds.width,
      startHeight: bounds.height,
      offsetX: offset.x,
      offsetY: offset.y,
      maxWidth: direction.includes("west")
        ? bounds.right - MODAL_VIEWPORT_MARGIN
        : window.innerWidth - MODAL_VIEWPORT_MARGIN - bounds.left,
      maxHeight: direction.includes("north")
        ? bounds.bottom - MODAL_VIEWPORT_MARGIN
        : window.innerHeight - MODAL_VIEWPORT_MARGIN - bounds.top,
    };
    event.currentTarget.setPointerCapture?.(event.pointerId);
    event.preventDefault();
    event.stopPropagation();
  }
  function continueResize(event: ReactPointerEvent<HTMLButtonElement>) {
    const resize = resizeRef.current;
    if (!resize || resize.pointerId !== event.pointerId) return;
    const horizontal = resize.direction.includes("east") || resize.direction.includes("west");
    const vertical = resize.direction.includes("north") || resize.direction.includes("south");
    const rawWidth = resize.direction.includes("west")
      ? resize.startWidth - (event.clientX - resize.startX)
      : resize.startWidth + (event.clientX - resize.startX);
    const rawHeight = resize.direction.includes("north")
      ? resize.startHeight - (event.clientY - resize.startY)
      : resize.startHeight + (event.clientY - resize.startY);
    const boundedMaxWidth = Math.max(1, resize.maxWidth);
    const boundedMaxHeight = Math.max(1, resize.maxHeight);
    const width = horizontal
      ? Math.max(Math.min(640, boundedMaxWidth), Math.min(boundedMaxWidth, rawWidth))
      : resize.startWidth;
    const height = vertical
      ? Math.max(Math.min(420, boundedMaxHeight), Math.min(boundedMaxHeight, rawHeight))
      : resize.startHeight;
    const widthDelta = width - resize.startWidth;
    const heightDelta = height - resize.startHeight;
    const nextOffset = {
      x: resize.offsetX + (resize.direction.includes("west") ? -widthDelta / 2 : widthDelta / 2),
      y: resize.offsetY + (resize.direction.includes("north") ? -heightDelta / 2 : heightDelta / 2),
    };
    setFrameSize({ width: Math.round(width), height: Math.round(height) });
    setOffset({ x: Math.round(nextOffset.x), y: Math.round(nextOffset.y) });
    onFrameMove?.();
  }
  function endResize(event: ReactPointerEvent<HTMLButtonElement>) {
    if (resizeRef.current?.pointerId !== event.pointerId) return;
    if (event.currentTarget.hasPointerCapture?.(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
    resizeRef.current = null;
  }
  const resolvedFrameStyle: CSSProperties | undefined = movable || resizable || frameStyle
    ? {
        ...frameStyle,
        transform: `translate(${offset.x}px, ${offset.y}px)`,
        ...(frameSize ? { width: frameSize.width, height: frameSize.height } : {}),
      }
    : undefined;
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
        style={resolvedFrameStyle}
        className={`relative flex flex-col overflow-hidden rounded-card border border-line2 bg-popover shadow-pop outline-none ${FRAME[size]}${frameClassName ? ` ${frameClassName}` : ""}`}
      >
        {resizable ? MODAL_RESIZE_DIRECTIONS.map((direction) => (
          <button
            key={direction}
            type="button"
            tabIndex={-1}
            aria-hidden="true"
            data-modal-resize-direction={direction}
            className={`absolute z-20 touch-none bg-transparent ${MODAL_RESIZE_CLASS[direction]}`}
            onPointerDown={(event) => beginResize(event, direction)}
            onPointerMove={continueResize}
            onPointerUp={endResize}
            onPointerCancel={endResize}
          />
        )) : null}
        <ModalHeader
          title={title}
          onClose={onClose}
          devId={headerDevId}
          closeDevId={closeDevId}
          movable={movable}
          onPointerDown={beginMove}
          onPointerMove={continueMove}
          onPointerUp={endMove}
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
