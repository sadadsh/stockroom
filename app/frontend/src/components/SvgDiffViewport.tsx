/**
 * An old/new visual diff of two monochrome preview SVGs (M6k): the historical geometry
 * and the current one are stacked in one shared pan/zoom viewport and cross-faded by a
 * single Old-to-New slider, so a moved pin or a changed pad is spotted by sliding
 * through the blend. Both layers share the SvgViewport pan/zoom + theme re-tint so they
 * register exactly. Default shows the New side; drag left to reveal the Old.
 */
import { useState } from "react";
import { useObjectUrl } from "../lib/useObjectUrl";
import { usePanZoom } from "../lib/usePanZoom";
import { useTheme } from "../lib/theme";

export function SvgDiffViewport({ before, after }: { before: Blob; after: Blob }) {
  const beforeUrl = useObjectUrl(before);
  const afterUrl = useObjectUrl(after);
  const { theme } = useTheme();
  const { view, frameRef, handlers, reset } = usePanZoom();
  const [blend, setBlend] = useState(1); // 0 = old only, 1 = new only

  const layer = (opacity: number) =>
    ({
      transform: `translate(${view.x}px, ${view.y}px) scale(${view.scale})`,
      filter: theme === "dark" ? "invert(1)" : "none",
      opacity,
    }) as const;

  return (
    <div className="relative h-full w-full">
      <div
        ref={frameRef}
        data-testid="svg-diff-viewport"
        className="absolute inset-0 cursor-grab overflow-hidden active:cursor-grabbing"
        {...handlers}
      >
        <div className="pointer-events-none absolute inset-0 flex items-center justify-center">
          {beforeUrl ? (
            <img
              src={beforeUrl}
              alt="Symbol Before"
              draggable={false}
              className="absolute h-full w-full select-none object-contain p-10"
              style={layer(1 - blend)}
            />
          ) : null}
          {afterUrl ? (
            <img
              src={afterUrl}
              alt="Symbol After"
              draggable={false}
              className="absolute h-full w-full select-none object-contain p-10"
              style={layer(blend)}
            />
          ) : null}
        </div>
      </div>
      <div className="absolute inset-x-3 bottom-3 flex items-center gap-3">
        <span className="flex-none text-2xs text-t3">Old</span>
        <input
          type="range"
          aria-label="Blend Old And New"
          min={0}
          max={1}
          step={0.01}
          value={blend}
          onChange={(e) => setBlend(Number(e.target.value))}
          className="min-w-0 flex-1 accent-acc"
        />
        <span className="flex-none text-2xs text-t3">New</span>
        <button
          type="button"
          onClick={reset}
          className="flex-none rounded-control border border-line2 bg-raise2 px-2.5 py-1 text-xs font-medium text-t2 hover:text-t1"
        >
          Reset View
        </button>
      </div>
    </div>
  );
}
