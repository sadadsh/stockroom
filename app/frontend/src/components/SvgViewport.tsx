/**
 * A pan/zoom viewport for a monochrome preview SVG (M6d). The wheel zooms toward the
 * cursor (the point under the pointer stays put), a drag pans, and Reset View recenters.
 * The SVG is fetched in the ?bw variant and re-tinted to the theme with a CSS invert
 * filter (black line art → near-white ink in dark, black in light), so it flips with
 * the app and never bakes a colour that only reads on one theme.
 */
import { useEffect, useRef, useState } from "react";
import { useObjectUrl } from "../lib/useObjectUrl";
import { useTheme } from "../lib/theme";

const MIN_SCALE = 0.3;
const MAX_SCALE = 8;

function clamp(v: number, lo: number, hi: number): number {
  return Math.min(hi, Math.max(lo, v));
}

interface View {
  scale: number;
  x: number;
  y: number;
}

const CENTERED: View = { scale: 1, x: 0, y: 0 };

export function SvgViewport({ blob, alt }: { blob: Blob; alt: string }) {
  const url = useObjectUrl(blob);
  const { theme } = useTheme();
  const [view, setView] = useState<View>(CENTERED);
  const frameRef = useRef<HTMLDivElement>(null);
  const dragRef = useRef<{ x: number; y: number } | null>(null);

  // Wheel is attached natively (not via onWheel) so it can be non-passive and
  // preventDefault the page scroll while zooming.
  useEffect(() => {
    const el = frameRef.current;
    if (!el) return;
    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      const rect = el.getBoundingClientRect();
      const mx = e.clientX - rect.left - rect.width / 2;
      const my = e.clientY - rect.top - rect.height / 2;
      setView((v) => {
        const scale = clamp(v.scale * Math.exp(-e.deltaY * 0.0015), MIN_SCALE, MAX_SCALE);
        const k = scale / v.scale;
        // keep the content point under the cursor fixed: x' = m - (m - x) * k
        return { scale, x: mx - (mx - v.x) * k, y: my - (my - v.y) * k };
      });
    };
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => el.removeEventListener("wheel", onWheel);
  }, []);

  const onPointerDown = (e: React.PointerEvent) => {
    dragRef.current = { x: e.clientX, y: e.clientY };
    e.currentTarget.setPointerCapture?.(e.pointerId);
  };
  const onPointerMove = (e: React.PointerEvent) => {
    const start = dragRef.current;
    if (!start) return;
    const dx = e.clientX - start.x;
    const dy = e.clientY - start.y;
    dragRef.current = { x: e.clientX, y: e.clientY };
    setView((v) => ({ ...v, x: v.x + dx, y: v.y + dy }));
  };
  const endDrag = () => {
    dragRef.current = null;
  };

  return (
    <div className="relative h-full w-full">
      <div
        ref={frameRef}
        data-testid="svg-viewport"
        className="absolute inset-0 cursor-grab overflow-hidden active:cursor-grabbing"
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={endDrag}
        onPointerLeave={endDrag}
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
        onClick={() => setView(CENTERED)}
        className="absolute bottom-3 right-3 rounded-control border border-line2 bg-raise2 px-2.5 py-1 text-xs font-medium text-t2 hover:text-t1"
      >
        Reset View
      </button>
    </div>
  );
}
