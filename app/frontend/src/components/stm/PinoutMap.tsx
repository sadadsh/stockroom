/**
 * PinoutMap (VIZ-01/02): the interactive SVG pinout map. It lays a part's pads with
 * lib/pinMapGeometry (LQFP/QFN perimeter or BGA/WLCSP grid) and renders the package as a lit
 * specimen in a recessed chamber, each pad carrying the four-channel encoding (CONTEXT decision 5):
 * fill = electrical-class category (the ONE saturated channel), border = role weight (neutral),
 * mark = a 5V-tolerant dot (neutral), ring = selection (neutral accent).
 *
 * d3-zoom drives a single group-level <g transform> for pan/zoom and renders nothing itself
 * (decision 7); the transform stays un-eased ("crisp, not gamey"). Per-pad screen position is
 * computed once, and each pad is memoized on its position so a hover/select on one pad never
 * re-renders the others (PITFALLS.md Pitfall 11).
 */
import { memo, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { select } from "d3-selection";
import { zoom, zoomIdentity, type D3ZoomEvent, type ZoomBehavior } from "d3-zoom";
import type { PinDTO, PinoutDTO } from "../../api/types";
import {
  pinMapGeometry,
  type PadLayout,
} from "../../lib/pinMapGeometry";
import { categoryFill, isFiveVoltTolerant, roleStroke } from "./pinEncoding";

const VIEW = 460;

interface Props {
  pinout: PinoutDTO;
  selectedPosition: string | null;
  onSelectPosition: (position: string) => void;
}

interface Camera {
  k: number;
  x: number;
  y: number;
}
const IDENTITY: Camera = { k: 1, x: 0, y: 0 };

export function PinoutMap({ pinout, selectedPosition, onSelectPosition }: Props) {
  const layout = useMemo(
    () => pinMapGeometry(pinout.pins, pinout.geometry, VIEW, VIEW),
    [pinout],
  );
  const pinByPosition = useMemo(() => {
    const m = new Map<string, PinDTO>();
    for (const p of pinout.pins) m.set(p.position, p);
    return m;
  }, [pinout]);

  const [camera, setCamera] = useState<Camera>(IDENTITY);
  const svgRef = useRef<SVGSVGElement>(null);
  const zoomRef = useRef<ZoomBehavior<SVGSVGElement, unknown> | null>(null);

  useEffect(() => {
    const svg = svgRef.current;
    if (!svg) return;
    const behavior = zoom<SVGSVGElement, unknown>()
      .scaleExtent([0.5, 8])
      // A constant extent matching the fixed viewBox: deterministic, and it avoids d3-zoom reading
      // the SVG's live geometry (which the fixed-size viewBox makes unnecessary).
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

  const handleSelect = useCallback(
    (position: string) => onSelectPosition(position),
    [onSelectPosition],
  );

  const unavailable = layout.pins.length === 0;

  return (
    <div className="relative flex min-h-0 flex-1 flex-col">
      <div className="relative min-h-0 flex-1 overflow-hidden rounded-card bg-stage shadow-[inset_0_1px_0_var(--edge-hi)]">
        {unavailable ? (
          <div className="flex h-full items-center justify-center px-6 text-center">
            <p className="text-sm text-t3">
              Layout unavailable for this package. The pinout facts are still listed on the right.
            </p>
          </div>
        ) : (
          <svg
            ref={svgRef}
            viewBox={`0 0 ${VIEW} ${VIEW}`}
            data-testid="pinout-map-svg"
            className="h-full w-full cursor-grab touch-none select-none active:cursor-grabbing"
            role="img"
            aria-label={`Pinout map for ${pinout.mpn_example}, package ${pinout.package}`}
          >
            <g transform={`translate(${camera.x},${camera.y}) scale(${camera.k})`}>
              {/* the package body: a lit specimen with a top-edge highlight + a silkscreen label */}
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
              {layout.centerPad ? (
                <rect
                  x={layout.centerPad.x}
                  y={layout.centerPad.y}
                  width={layout.centerPad.w}
                  height={layout.centerPad.h}
                  rx={3}
                  fill="var(--c-stage)"
                  stroke="var(--c-line2)"
                  strokeWidth={1}
                />
              ) : null}
              <text
                x={layout.body.x + layout.body.w / 2}
                y={layout.body.y + layout.body.h / 2 - 6}
                textAnchor="middle"
                className="fill-t3 font-mono"
                fontSize={13}
              >
                {pinout.mpn_example}
              </text>
              <text
                x={layout.body.x + layout.body.w / 2}
                y={layout.body.y + layout.body.h / 2 + 12}
                textAnchor="middle"
                className="fill-t3 font-mono"
                fontSize={11}
              >
                {pinout.package}
              </text>

              {layout.pins.map((pad) => (
                <Pad
                  key={pad.position}
                  pad={pad}
                  pin={pinByPosition.get(pad.position)}
                  selected={pad.position === selectedPosition}
                  onSelect={handleSelect}
                />
              ))}
            </g>
          </svg>
        )}

        {!unavailable ? (
          <button
            type="button"
            onClick={reset}
            className="absolute bottom-3 right-3 rounded-control border border-line2 bg-raise2 px-2.5 py-1 text-xs font-medium text-t2 hover:text-t1"
          >
            Reset View
          </button>
        ) : null}
      </div>
    </div>
  );
}

// One pad: memoized on its stable key = position, so a select/hover elsewhere never re-renders it
// (Pitfall 11). The four channels are applied here; nothing else is painted on the pad (the full
// AF list and every other fact live in PinInspector on click).
const Pad = memo(function Pad({
  pad,
  pin,
  selected,
  onSelect,
}: {
  pad: PadLayout;
  pin: PinDTO | undefined;
  selected: boolean;
  onSelect: (position: string) => void;
}) {
  const { x, y, w, h } = pad.rect;
  const fill = pin ? categoryFill(pin.category) : "var(--stm-cat-nc)";
  const stroke = pin ? roleStroke(pin) : { color: "var(--c-line2)", width: 1 };
  const fiveV = pin ? isFiveVoltTolerant(pin) : false;
  const markR = Math.min(w, h) * 0.22;

  return (
    <g
      onClick={() => onSelect(pad.position)}
      className="cursor-pointer [&>rect.pad]:hover:brightness-110 motion-reduce:[&>rect.pad]:hover:brightness-100"
      data-position={pad.position}
    >
      <title>{pin ? `${pin.canonical_pin_name} · ${pad.position}` : pad.position}</title>
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
        fill={fill}
        stroke={stroke.color}
        strokeWidth={stroke.width}
      />
      {fiveV ? <circle cx={x + w / 2} cy={y + h / 2} r={markR} fill="var(--c-t1)" /> : null}
    </g>
  );
});
