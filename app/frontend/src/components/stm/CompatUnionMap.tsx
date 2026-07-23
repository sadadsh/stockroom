/**
 * CompatUnionMap (COMPAT-02/03): the live socket-union map. It lays the union's positions with the
 * SAME lib/pinMapGeometry path PinoutMap uses (CONTEXT decision 3 — reused, never reimplemented) and
 * paints each position by its classification (shared / divergent / partial) instead of by pin
 * category. Status color runs through a single small classification dot per pad, never a filled pad
 * background (VIZ-02 "color is data"); the per-part audit trail is click detail, never per-pad.
 *
 * A UnionDTO carries no PinoutGeometryDTO of its own, so the body shape is inferred from the
 * positions' geometry hints (a BGA row present -> ball grid, else perimeter) and handed to the same
 * layout function. Clicking a divergent pad opens the reconcile detail (COMPAT-03); shared / partial
 * positions carry no reconcile, so a click only inspects the per-part trail.
 */
import { memo, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { select } from "d3-selection";
import { zoom, zoomIdentity, type D3ZoomEvent, type ZoomBehavior } from "d3-zoom";
import type { PinoutGeometryDTO, UnionDTO, UnionPositionDTO } from "../../api/types";
import { pinMapGeometry, type PadLayout } from "../../lib/pinMapGeometry";
import { Dot } from "../primitives";
import {
  CLASSIFICATION_LABEL,
  TONE_VAR,
  classificationTone,
  type Classification,
} from "./compatEncoding";
import { CompatReconcileDetail } from "./CompatReconcileDetail";

const VIEW = 460;

// A UnionDTO has no geometry block; infer the minimal one the layout needs from the positions'
// hints. A BGA row on any position means an area-array ball grid; otherwise a perimeter package.
// rows/cols stay null so the ball grid derives them from the real ball maxima (never a guessed sqrt).
function unionGeometry(positions: UnionPositionDTO[]): PinoutGeometryDTO {
  const isBga = positions.some((p) => p.bga_row != null);
  return {
    body_shape: isBga ? "bga" : "qfp",
    pin_count: positions.length,
    rows: null,
    cols: null,
    pitch_mm: null,
    has_center_pad: false,
  };
}

interface Camera {
  k: number;
  x: number;
  y: number;
}
const IDENTITY: Camera = { k: 1, x: 0, y: 0 };

// The three classifications in the order the legend teaches them (shared first, the common case).
const LEGEND: Classification[] = ["shared", "divergent", "partial"];

export function CompatUnionMap({ union }: { union: UnionDTO }) {
  const [selectedPosition, setSelectedPosition] = useState<string | null>(null);

  const geometry = useMemo(() => unionGeometry(union.positions), [union.positions]);
  const layout = useMemo(
    () => pinMapGeometry(union.positions, geometry, VIEW, VIEW),
    [union.positions, geometry],
  );
  const byPosition = useMemo(() => {
    const m = new Map<string, UnionPositionDTO>();
    for (const p of union.positions) m.set(p.position, p);
    return m;
  }, [union.positions]);

  const [camera, setCamera] = useState<Camera>(IDENTITY);
  const svgRef = useRef<SVGSVGElement>(null);
  const zoomRef = useRef<ZoomBehavior<SVGSVGElement, unknown> | null>(null);

  useEffect(() => {
    const svg = svgRef.current;
    if (!svg) return;
    const behavior = zoom<SVGSVGElement, unknown>()
      .scaleExtent([0.5, 8])
      .extent([
        [0, 0],
        [VIEW, VIEW],
      ])
      .on("zoom", (event: D3ZoomEvent<SVGSVGElement, unknown>) => {
        const { k, x, y } = event.transform;
        setCamera({ k, x, y });
      });
    zoomRef.current = behavior;
    const sel = select(svg);
    sel.call(behavior);
    return () => {
      sel.on(".zoom", null);
    };
  }, []);

  const reset = useCallback(() => {
    const svg = svgRef.current;
    if (svg && zoomRef.current) {
      select(svg).call(zoomRef.current.transform, zoomIdentity);
    }
    setCamera(IDENTITY);
  }, []);

  const handleSelect = useCallback((position: string) => setSelectedPosition(position), []);

  // The clicked position, looked up from the union data already in hand (no new fetch). Its per-part
  // trail + reconcile swaps render below the map as click detail, never painted per-pad (decision 3).
  const selected = selectedPosition != null ? (byPosition.get(selectedPosition) ?? null) : null;
  const unavailable = layout.pins.length === 0;
  // Positions the layout could not place (a perimeter position with no lqfp_side, or a ball row
  // outside the JEDEC alphabet). Surfaced as a count so a partial map never reads as the whole set.
  const unplaced = union.positions.length - layout.pins.length;

  return (
    <div className="flex min-h-0 flex-col gap-3">
      {/* A definite-height column-flex slot: the chamber shrinks inside it so the footer strip
          stays within the slot instead of spilling over the reconcile detail below (mirrors the
          explorer's PinoutMap slot). */}
      <div className="relative flex h-[420px] flex-none flex-col">
        <div className="relative min-h-0 flex-1 overflow-hidden rounded-card bg-stage shadow-[inset_0_1px_0_var(--edge-hi)]">
          {unavailable ? (
            <div className="flex h-full min-h-0 flex-col gap-2 p-4" data-testid="compat-union-list">
              <p className="flex-none text-xs text-t3">
                No drawable layout for this package. Select a position from the list to inspect it.
              </p>
              <ul className="min-h-0 flex-1 overflow-y-auto">
                {union.positions.map((p) => (
                  <li key={p.position}>
                    <button
                      type="button"
                      onClick={() => handleSelect(p.position)}
                      data-position={p.position}
                      data-classification={p.classification}
                      className={
                        "flex w-full items-center gap-2 rounded-control px-2 py-1 text-left hover:bg-hover " +
                        (p.position === selectedPosition ? "bg-acc-soft" : "")
                      }
                    >
                      <Dot tone={classificationTone(p.classification)} />
                      <span className="w-10 flex-none font-mono text-xs text-t3">{p.position}</span>
                      <span className="truncate text-xs text-t2">
                        {CLASSIFICATION_LABEL[p.classification]}
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          ) : (
            <svg
              ref={svgRef}
              viewBox={`0 0 ${VIEW} ${VIEW}`}
              data-testid="compat-union-map-svg"
              className="h-full w-full cursor-grab touch-none select-none active:cursor-grabbing"
              role="img"
              aria-label={`Socket-union map for ${union.family} in ${union.package}`}
            >
              <g transform={`translate(${camera.x},${camera.y}) scale(${camera.k})`}>
                <rect
                  x={layout.body.x}
                  y={layout.body.y}
                  width={layout.body.w}
                  height={layout.body.h}
                  rx={10}
                  fill="var(--c-raise2)"
                  stroke="var(--c-line2)"
                  strokeWidth={1}
                />
                <line
                  x1={layout.body.x + 6}
                  y1={layout.body.y + 1}
                  x2={layout.body.x + layout.body.w - 6}
                  y2={layout.body.y + 1}
                  stroke="var(--edge-hi)"
                  strokeWidth={1}
                />
                {layout.pins.map((pad) => (
                  <UnionPad
                    key={pad.position}
                    pad={pad}
                    position={byPosition.get(pad.position)}
                    selected={pad.position === selectedPosition}
                    onSelect={handleSelect}
                  />
                ))}
              </g>
            </svg>
          )}
        </div>

        {/* The chamber footer: the classification legend left (the Dot is the one place status
            color runs), camera reset right. A footer strip, never an overlay on the pad field. */}
        <div className="mt-2 flex flex-none items-center justify-between gap-2">
          <div className="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1">
            {LEGEND.map((c) => (
              <span key={c} className="flex items-center gap-1.5 text-2xs text-t3">
                <Dot tone={classificationTone(c)} />
                {CLASSIFICATION_LABEL[c]}
              </span>
            ))}
            {unplaced > 0 ? (
              <span className="rounded-control bg-raise px-2 py-0.5 text-2xs text-t3">
                {unplaced} {unplaced === 1 ? "position" : "positions"} without a mappable location
              </span>
            ) : null}
          </div>
          {!unavailable ? (
            <button
              type="button"
              onClick={reset}
              className="flex-none rounded-control border border-line2 bg-raise2 px-2.5 py-1 text-xs font-medium text-t2 hover:text-t1"
            >
              Reset View
            </button>
          ) : null}
        </div>
      </div>

      {/* The per-part audit trail + reconcile swaps for the clicked position (COMPAT-03). Rendered
          only on selection, never per-pad on the map (CONTEXT decision 3). */}
      {selected ? <CompatReconcileDetail position={selected} /> : null}
    </div>
  );
}

// One union pad: a neutral body rect carrying a single classification dot (never a filled pad
// background). Memoized on its position so a select elsewhere never re-renders it (Pitfall 11).
const UnionPad = memo(function UnionPad({
  pad,
  position,
  selected,
  onSelect,
}: {
  pad: PadLayout;
  position: UnionPositionDTO | undefined;
  selected: boolean;
  onSelect: (position: string) => void;
}) {
  const { x, y, w, h } = pad.rect;
  const classification = position?.classification;
  const dotFill = classification ? TONE_VAR[classificationTone(classification)] : "var(--c-t3)";
  const dotR = Math.min(w, h) * 0.3;

  return (
    <g
      onClick={() => onSelect(pad.position)}
      className="cursor-pointer [&>rect.pad]:hover:brightness-110 motion-reduce:[&>rect.pad]:hover:brightness-100"
      data-position={pad.position}
      data-classification={classification}
    >
      <title>
        {position
          ? `${pad.position} · ${CLASSIFICATION_LABEL[position.classification]} (${position.present_on}/${position.total})`
          : pad.position}
      </title>
      {selected ? (
        <rect
          x={x - 3}
          y={y - 3}
          width={w + 6}
          height={h + 6}
          rx={3}
          fill="none"
          stroke="var(--c-acc-strong)"
          strokeWidth={2}
        />
      ) : null}
      <rect
        className="pad"
        x={x}
        y={y}
        width={w}
        height={h}
        rx={1.5}
        fill="var(--c-raise2)"
        stroke="var(--c-line2)"
        strokeWidth={1}
      />
      <circle cx={x + w / 2} cy={y + h / 2} r={dotR} fill={dotFill} />
    </g>
  );
});
