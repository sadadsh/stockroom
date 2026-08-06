/**
 * A pan/zoom viewport for a monochrome preview SVG (M6d). The wheel zooms toward the
 * cursor (the point under the pointer stays put), a drag pans, and Reset View recenters.
 * The SVG is fetched in the ?bw variant and re-tinted to the theme with a CSS invert
 * filter (black line art → near-white ink in dark, black in light), so it flips with
 * the app and never bakes a colour that only reads on one theme.
 */
import { useEffect } from "react";
import { Text, useCopyFormatter, useText } from "../lib/copy";
import { useObjectUrl } from "../lib/useObjectUrl";
import { usePanZoom } from "../lib/usePanZoom";
import { useTheme } from "../lib/theme";

export type SvgVisibility = "checking" | "visible" | "unavailable";

export function SvgViewport({
  blob,
  alt,
  downloadName,
  compact = false,
  onVisibilityChange,
}: {
  blob: Blob;
  alt: string;
  downloadName?: string;
  /** Passive in-pane presentation. Expansion keeps this same viewport and view state. */
  compact?: boolean;
  /** Reports decoded pixels, not merely a fetched SVG blob. */
  onVisibilityChange?: (state: SvgVisibility) => void;
}) {
  const url = useObjectUrl(blob);
  const { theme } = useTheme();
  const { view, frameRef, handlers, reset, zoomIn, zoomOut } = usePanZoom();
  const scalePercent = Math.round(view.scale * 100);
  const zoomOutLabel = useText("svg-view.zoom-out", "Zoom out");
  const zoomLevelLabel = useText("svg-view.zoom-level", "Zoom level");
  const zoomInLabel = useText("svg-view.zoom-in", "Zoom in");
  const resetViewLabel = useText("svg-view.reset-view", "Reset View");
  const exportSvgLabel = useText("svg-view.export-svg", "Export SVG");
  // The pointer tooltips carry the keyboard shortcut as well as the action, which the accessible
  // names above deliberately do not - a screen reader announces the key binding as noise.
  const zoomOutTip = useText("svg-view.zoom-out-tip", "Zoom out (-)");
  const zoomInTip = useText("svg-view.zoom-in-tip", "Zoom in (+)");
  const fitTip = useText("svg-view.fit-tip", "Fit drawing (0 or F)");
  const exportTip = useText("svg-view.export-tip", "Export the current vector drawing");
  // The canvas's own accessible name, which is also the only place its gestures are stated.
  const canvasName = useCopyFormatter(
    "svg-view.canvas-aria",
    "{subject} inspection canvas. Drag to pan, scroll or use plus and minus to zoom, and press 0 to fit.",
  );

  useEffect(() => {
    onVisibilityChange?.("checking");
  }, [blob, onVisibilityChange]);

  return (
    <div className="relative h-full w-full">
      <div
        ref={frameRef}
        data-testid="svg-viewport"
        tabIndex={compact ? -1 : 0}
        role={compact ? undefined : "application"}
        aria-label={
          compact
            ? undefined
            : canvasName({ subject: alt })
        }
        onDoubleClick={compact ? undefined : reset}
        onKeyDown={
          compact
            ? undefined
            : (event) => {
                if (event.key === "+" || event.key === "=") {
                  event.preventDefault();
                  zoomIn();
                } else if (event.key === "-" || event.key === "_") {
                  event.preventDefault();
                  zoomOut();
                } else if (event.key === "0" || event.key.toLowerCase() === "f") {
                  event.preventDefault();
                  reset();
                }
              }
        }
        className={
          "absolute inset-0 overflow-hidden outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-acc " +
          (compact ? "cursor-default" : "cursor-grab active:cursor-grabbing")
        }
        {...(compact ? {} : handlers)}
      >
        <div className="pointer-events-none absolute inset-0 flex items-center justify-center">
          {url ? (
            <img
              src={url}
              alt={alt}
              draggable={false}
              onLoad={() => onVisibilityChange?.("visible")}
              onError={() => onVisibilityChange?.("unavailable")}
              // Fill the viewport (object-contain upscales the small-intrinsic KiCad
              // SVG to fit); the transform below adds the pan/zoom on top.
              className={
                "h-full w-full select-none object-contain " +
                (compact ? "p-4" : "p-[clamp(1rem,3vmin,2.5rem)]")
              }
              style={{
                transform: `translate(${view.x}px, ${view.y}px) scale(${view.scale})`,
                filter: theme === "dark" ? "invert(1)" : "none",
              }}
            />
          ) : null}
        </div>
      </div>
      {!compact ? (
      <div className="absolute bottom-3 right-3 flex items-center overflow-hidden rounded-control border border-line2 bg-popover shadow-pop">
        <button
          type="button"
          aria-label={zoomOutLabel}
          title={zoomOutTip}
          onClick={zoomOut}
          className="flex h-7 w-7 items-center justify-center text-sm text-t2 hover:bg-raise hover:text-t1"
        >
          −
        </button>
        <output
          aria-label={zoomLevelLabel}
          className="min-w-[44px] border-x border-line px-1.5 text-center text-2xs tabular-nums text-t3"
        >
          {scalePercent}%
        </output>
        <button
          type="button"
          aria-label={zoomInLabel}
          title={zoomInTip}
          onClick={zoomIn}
          className="flex h-7 w-7 items-center justify-center text-sm text-t2 hover:bg-raise hover:text-t1"
        >
          +
        </button>
        <button
          type="button"
          aria-label={resetViewLabel}
          title={fitTip}
          onClick={reset}
          className="h-7 border-l border-line px-2 text-2xs font-medium text-t2 hover:bg-raise hover:text-t1"
        >
          <Text id="svg-view.fit">Fit</Text>
        </button>
        {url && downloadName ? (
          <a
            href={url}
            download={downloadName}
            aria-label={exportSvgLabel}
            title={exportTip}
            className="flex h-7 items-center border-l border-line px-2 text-2xs font-medium text-t2 hover:bg-raise hover:text-t1"
          >
            <Text id="svg-view.export-label">SVG</Text>
          </a>
        ) : null}
      </div>
      ) : null}
    </div>
  );
}
