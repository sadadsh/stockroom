/**
 * Wheel-zoom-to-pointer + drag-pan state for a preview viewport, shared by the single
 * SVG viewport (M6d) and the old/new diff overlay (M6k) so both pan and zoom
 * identically. The wheel is attached natively (non-passive) so it can preventDefault
 * the page scroll while zooming; the point under the cursor stays fixed as it scales.
 */
import { useEffect, useRef, useState, type PointerEvent as ReactPointerEvent } from "react";

const MIN_SCALE = 0.3;
const MAX_SCALE = 8;

function clamp(v: number, lo: number, hi: number): number {
  return Math.min(hi, Math.max(lo, v));
}

export interface PanZoomView {
  scale: number;
  x: number;
  y: number;
}

export const CENTERED: PanZoomView = { scale: 1, x: 0, y: 0 };

export function usePanZoom() {
  const [view, setView] = useState<PanZoomView>(CENTERED);
  const frameRef = useRef<HTMLDivElement>(null);
  const dragRef = useRef<{ x: number; y: number } | null>(null);

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

  const handlers = {
    onPointerDown: (e: ReactPointerEvent) => {
      dragRef.current = { x: e.clientX, y: e.clientY };
      e.currentTarget.setPointerCapture?.(e.pointerId);
    },
    onPointerMove: (e: ReactPointerEvent) => {
      const start = dragRef.current;
      if (!start) return;
      const dx = e.clientX - start.x;
      const dy = e.clientY - start.y;
      dragRef.current = { x: e.clientX, y: e.clientY };
      setView((v) => ({ ...v, x: v.x + dx, y: v.y + dy }));
    },
    onPointerUp: () => {
      dragRef.current = null;
    },
    onPointerLeave: () => {
      dragRef.current = null;
    },
  };

  const reset = () => setView(CENTERED);

  return { view, frameRef, handlers, reset };
}
