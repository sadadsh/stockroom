/**
 * A pan/zoom viewport for a monochrome preview SVG (M6d). The wheel zooms toward the
 * cursor (the point under the pointer stays put), a drag pans, and Reset View recenters.
 * The SVG is fetched in the ?bw variant and re-tinted to the theme with a CSS invert
 * filter (black line art → near-white ink in dark, black in light), so it flips with
 * the app and never bakes a colour that only reads on one theme.
 */
import { useObjectUrl } from "../lib/useObjectUrl";
import { usePanZoom } from "../lib/usePanZoom";
import { useTheme } from "../lib/theme";

export function SvgViewport({
  blob,
  alt,
  downloadName,
}: {
  blob: Blob;
  alt: string;
  downloadName?: string;
}) {
  const url = useObjectUrl(blob);
  const { theme } = useTheme();
  const { view, frameRef, handlers, reset, zoomIn, zoomOut } = usePanZoom();
  const scalePercent = Math.round(view.scale * 100);

  return (
    <div className="relative h-full w-full">
      <div
        ref={frameRef}
        data-testid="svg-viewport"
        tabIndex={0}
        role="application"
        aria-label={`${alt} inspection canvas. Drag to pan, scroll or use plus and minus to zoom, and press 0 to fit.`}
        onDoubleClick={reset}
        onKeyDown={(event) => {
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
        }}
        className="absolute inset-0 cursor-grab overflow-hidden outline-none active:cursor-grabbing focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-acc"
        {...handlers}
      >
        <div className="pointer-events-none absolute inset-0 flex items-center justify-center">
          {url ? (
            <img
              src={url}
              alt={alt}
              draggable={false}
              // Fill the viewport (object-contain upscales the small-intrinsic KiCad
              // SVG to fit); the transform below adds the pan/zoom on top.
              className="h-full w-full select-none object-contain p-10"
              style={{
                transform: `translate(${view.x}px, ${view.y}px) scale(${view.scale})`,
                filter: theme === "dark" ? "invert(1)" : "none",
              }}
            />
          ) : null}
        </div>
      </div>
      <div className="absolute bottom-3 right-3 flex items-center overflow-hidden rounded-control border border-line2 bg-popover/95 shadow-pop">
        <button
          type="button"
          aria-label="Zoom out"
          title="Zoom out (-)"
          onClick={zoomOut}
          className="flex h-7 w-7 items-center justify-center text-sm text-t2 hover:bg-raise hover:text-t1"
        >
          −
        </button>
        <output
          aria-label="Zoom level"
          className="min-w-[44px] border-x border-line px-1.5 text-center text-2xs tabular-nums text-t3"
        >
          {scalePercent}%
        </output>
        <button
          type="button"
          aria-label="Zoom in"
          title="Zoom in (+)"
          onClick={zoomIn}
          className="flex h-7 w-7 items-center justify-center text-sm text-t2 hover:bg-raise hover:text-t1"
        >
          +
        </button>
        <button
          type="button"
          aria-label="Reset View"
          title="Fit drawing (0 or F)"
          onClick={reset}
          className="h-7 border-l border-line px-2 text-2xs font-medium text-t2 hover:bg-raise hover:text-t1"
        >
          Fit
        </button>
        {url && downloadName ? (
          <a
            href={url}
            download={downloadName}
            aria-label="Export SVG"
            title="Export the current vector drawing"
            className="flex h-7 items-center border-l border-line px-2 text-2xs font-medium text-t2 hover:bg-raise hover:text-t1"
          >
            SVG
          </a>
        ) : null}
      </div>
    </div>
  );
}
