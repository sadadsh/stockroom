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

export function SvgViewport({ blob, alt }: { blob: Blob; alt: string }) {
  const url = useObjectUrl(blob);
  const { theme } = useTheme();
  const { view, frameRef, handlers, reset } = usePanZoom();

  return (
    <div className="relative h-full w-full">
      <div
        ref={frameRef}
        data-testid="svg-viewport"
        className="absolute inset-0 cursor-grab overflow-hidden active:cursor-grabbing"
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
      <button
        type="button"
        onClick={reset}
        className="absolute bottom-3 right-3 rounded-control border border-line2 bg-raise2 px-2.5 py-1 text-xs font-medium text-t2 hover:text-t1"
      >
        Reset View
      </button>
    </div>
  );
}
