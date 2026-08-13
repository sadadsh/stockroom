import {
  type PointerEvent as ReactPointerEvent,
  type RefObject,
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
} from "react";
import { createPortal } from "react-dom";
import { sendProviderCommand } from "../../lib/hostProviderViewport";
import { useText } from "../../lib/copy";
import { Button } from "../primitives";
import { ProviderBrowserFrame } from "./ProviderBrowserFrame";

const MODAL_MARGIN = 24;
const MIN_MODAL_WIDTH = 640;
const MIN_MODAL_HEIGHT = 420;

export interface ProviderModalViewport {
  width: number;
  height: number;
}

export interface ProviderModalGeometry {
  x: number;
  y: number;
  width: number;
  height: number;
}

export type ProviderModalResizeDirection =
  | "north"
  | "north-east"
  | "east"
  | "south-east"
  | "south"
  | "south-west"
  | "west"
  | "north-west";

function rounded(value: number): number {
  return Math.round(value);
}

function clamp(value: number, minimum: number, maximum: number): number {
  return Math.min(Math.max(value, minimum), Math.max(minimum, maximum));
}

export function initialProviderModalGeometry(
  viewport: ProviderModalViewport,
): ProviderModalGeometry {
  const availableWidth = Math.max(1, viewport.width - MODAL_MARGIN * 2);
  const availableHeight = Math.max(1, viewport.height - MODAL_MARGIN * 2);
  const width = Math.min(availableWidth, Math.max(MIN_MODAL_WIDTH, rounded(viewport.width * 0.8)));
  const height = Math.min(
    availableHeight,
    Math.max(MIN_MODAL_HEIGHT, rounded(viewport.height * 0.8)),
  );
  return {
    x: rounded((viewport.width - width) / 2),
    y: rounded((viewport.height - height) / 2),
    width,
    height,
  };
}

export function moveProviderModal(
  geometry: ProviderModalGeometry,
  deltaX: number,
  deltaY: number,
  viewport: ProviderModalViewport,
): ProviderModalGeometry {
  return {
    ...geometry,
    x: rounded(
      clamp(
        geometry.x + deltaX,
        MODAL_MARGIN,
        viewport.width - MODAL_MARGIN - geometry.width,
      ),
    ),
    y: rounded(
      clamp(
        geometry.y + deltaY,
        MODAL_MARGIN,
        viewport.height - MODAL_MARGIN - geometry.height,
      ),
    ),
  };
}

export function resizeProviderModal(
  geometry: ProviderModalGeometry,
  direction: ProviderModalResizeDirection,
  deltaX: number,
  deltaY: number,
  viewport: ProviderModalViewport,
): ProviderModalGeometry {
  const north = direction.startsWith("north");
  const south = direction.startsWith("south");
  const west = direction.endsWith("west") || direction === "west";
  const east = direction.endsWith("east") || direction === "east";
  let left = geometry.x;
  let top = geometry.y;
  let right = geometry.x + geometry.width;
  let bottom = geometry.y + geometry.height;

  if (west) left = clamp(left + deltaX, MODAL_MARGIN, right - MIN_MODAL_WIDTH);
  if (east) right = clamp(right + deltaX, left + MIN_MODAL_WIDTH, viewport.width - MODAL_MARGIN);
  if (north) top = clamp(top + deltaY, MODAL_MARGIN, bottom - MIN_MODAL_HEIGHT);
  if (south) bottom = clamp(bottom + deltaY, top + MIN_MODAL_HEIGHT, viewport.height - MODAL_MARGIN);

  return {
    x: rounded(left),
    y: rounded(top),
    width: rounded(right - left),
    height: rounded(bottom - top),
  };
}

function currentViewport(): ProviderModalViewport {
  return { width: window.innerWidth, height: window.innerHeight };
}

const RESIZE_HANDLES: Array<{
  direction: ProviderModalResizeDirection;
  className: string;
  cursor: string;
}> = [
  { direction: "north", className: "left-3 right-3 top-0 h-2", cursor: "ns-resize" },
  { direction: "north-east", className: "right-0 top-0 h-4 w-4", cursor: "nesw-resize" },
  { direction: "east", className: "bottom-3 right-0 top-3 w-2", cursor: "ew-resize" },
  { direction: "south-east", className: "bottom-0 right-0 h-4 w-4", cursor: "nwse-resize" },
  { direction: "south", className: "bottom-0 left-3 right-3 h-2", cursor: "ns-resize" },
  { direction: "south-west", className: "bottom-0 left-0 h-4 w-4", cursor: "nesw-resize" },
  { direction: "west", className: "bottom-3 left-0 top-3 w-2", cursor: "ew-resize" },
  { direction: "north-west", className: "left-0 top-0 h-4 w-4", cursor: "nwse-resize" },
];

export function ProviderBrowserModal({
  open,
  componentId,
  providerLabel,
  url,
  returnFocusRef,
  onClose,
}: {
  open: boolean;
  componentId: string;
  providerLabel: string;
  url: string;
  returnFocusRef?: RefObject<HTMLElement | null>;
  onClose: () => void;
}) {
  const closeLabel = useText("component-browser.manage-models-close", "Close Provider");
  const dialogLabel = useText(
    "component-browser.manage-models-provider-dialog",
    `${providerLabel} Provider`,
  );
  const resizeLabel = useText(
    "component-browser.manage-models-provider-resize",
    "Resize Provider",
  );
  const [geometry, setGeometry] = useState(() => initialProviderModalGeometry(currentViewport()));
  const dialogRef = useRef<HTMLDivElement | null>(null);
  const automaticReturnFocusRef = useRef<HTMLElement | null>(null);
  const gestureRef = useRef<{
    kind: "move" | "resize";
    direction?: ProviderModalResizeDirection;
    pointerX: number;
    pointerY: number;
    geometry: ProviderModalGeometry;
  } | null>(null);

  useLayoutEffect(() => {
    if (open) {
      automaticReturnFocusRef.current =
        document.activeElement instanceof HTMLElement ? document.activeElement : null;
    }
  }, [open]);

  const restoreFocus = useCallback(() => {
    (returnFocusRef?.current ?? automaticReturnFocusRef.current)?.focus();
  }, [returnFocusRef]);

  useEffect(() => {
    if (!open) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        event.stopImmediatePropagation();
        sendProviderCommand(componentId, "close");
        onClose();
        restoreFocus();
        return;
      }
      if (event.key !== "Tab") return;
      const focusable = Array.from(
        dialogRef.current?.querySelectorAll<HTMLElement>(
          'button:not([disabled]), [href], input:not([disabled]), [tabindex]:not([tabindex="-1"])',
        ) ?? [],
      );
      if (focusable.length === 0) return;
      const first = focusable[0]!;
      const last = focusable[focusable.length - 1]!;
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    window.addEventListener("keydown", onKeyDown, true);
    return () => window.removeEventListener("keydown", onKeyDown, true);
  }, [componentId, onClose, open, restoreFocus]);

  useEffect(() => {
    if (!open) return;
    const onResize = () => {
      setGeometry((current) => {
        const viewport = currentViewport();
        const width = Math.min(current.width, viewport.width - MODAL_MARGIN * 2);
        const height = Math.min(current.height, viewport.height - MODAL_MARGIN * 2);
        return moveProviderModal({ ...current, width, height }, 0, 0, viewport);
      });
    };
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, [open]);

  if (!open) return null;

  const beginGesture = (
    event: ReactPointerEvent<HTMLElement>,
    kind: "move" | "resize",
    direction?: ProviderModalResizeDirection,
  ) => {
    gestureRef.current = {
      kind,
      direction,
      pointerX: event.clientX,
      pointerY: event.clientY,
      geometry,
    };
    event.currentTarget.setPointerCapture?.(event.pointerId);
  };

  const updateGesture = (event: ReactPointerEvent<HTMLElement>) => {
    const gesture = gestureRef.current;
    if (!gesture) return;
    const deltaX = event.clientX - gesture.pointerX;
    const deltaY = event.clientY - gesture.pointerY;
    setGeometry(
      gesture.kind === "move"
        ? moveProviderModal(gesture.geometry, deltaX, deltaY, currentViewport())
        : resizeProviderModal(
            gesture.geometry,
            gesture.direction!,
            deltaX,
            deltaY,
            currentViewport(),
          ),
    );
  };

  const finishGesture = () => {
    gestureRef.current = null;
  };

  const close = () => {
    sendProviderCommand(componentId, "close");
    onClose();
    restoreFocus();
  };

  return createPortal(
    <div className="fixed inset-0 z-[120] bg-canvas/70 backdrop-blur-sm">
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-label={dialogLabel}
        data-dev-id="component-browser.provider-dialog"
        className="fixed flex min-h-0 flex-col overflow-hidden rounded-card border border-line bg-raise shadow-2xl"
        style={{ left: geometry.x, top: geometry.y, width: geometry.width, height: geometry.height }}
      >
        <div
          data-dev-id="component-browser.provider-dialog-titlebar"
          className="flex h-[34px] flex-none cursor-move items-center gap-2 border-b border-line bg-band px-3"
          onPointerDown={(event) => beginGesture(event, "move")}
          onPointerMove={updateGesture}
          onPointerUp={finishGesture}
          onPointerCancel={finishGesture}
        >
          <span className="min-w-0 flex-1 truncate text-sm font-semibold text-t1">
            {providerLabel}
          </span>
          <Button
            type="button"
            small
            data-dev-id="component-browser.provider-close"
            aria-label={closeLabel}
            onPointerDown={(event) => event.stopPropagation()}
            onClick={close}
          >
            ×
          </Button>
        </div>
        <ProviderBrowserFrame componentId={componentId} providerLabel={providerLabel} url={url} />
        {RESIZE_HANDLES.map((handle) => (
          <button
            key={handle.direction}
            type="button"
            tabIndex={-1}
            aria-label={resizeLabel}
            className={`absolute ${handle.className}`}
            style={{ cursor: handle.cursor }}
            onPointerDown={(event) => beginGesture(event, "resize", handle.direction)}
            onPointerMove={updateGesture}
            onPointerUp={finishGesture}
            onPointerCancel={finishGesture}
          />
        ))}
      </div>
    </div>,
    document.body,
  );
}
