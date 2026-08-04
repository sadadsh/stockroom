import { memo, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { select } from "d3-selection";
import { zoom, zoomIdentity, type D3ZoomEvent, type ZoomBehavior } from "d3-zoom";
import type {
  PinoutGeometryDTO,
  TargetDefinitionPosition,
} from "../../api/types";
import {
  ballGridHeaders,
  perimeterLabels,
  pinMapGeometry,
  type PadLayout,
} from "../../lib/pinMapGeometry";
import { formatElectricalIdentity } from "../../lib/stmTargetInsights";
import {
  targetMatchesLegend,
  targetPositionColor,
  targetPositionDescription,
  type TargetMapLens,
} from "../../lib/stmTargetVisuals";
import { Text } from "../../lib/copy";
import { RefreshIcon } from "../icons";
import { IconButton } from "../primitives";

export type { TargetMapLens } from "../../lib/stmTargetVisuals";

const VIEW = 460;

export interface TargetMapPositionVisual {
  fill: string;
  stroke?: string;
  dashed?: boolean;
  marker?: number;
  agreement?: number;
  active?: boolean;
  hazard?: "medium" | "high" | "critical";
  description: string;
}

interface Camera {
  k: number;
  x: number;
  y: number;
}

const IDENTITY: Camera = { k: 1, x: 0, y: 0 };

function targetGeometry(positions: TargetDefinitionPosition[]): PinoutGeometryDTO {
  return {
    body_shape: positions.some((position) => position.bga_row != null)
      ? "bga"
      : "qfp",
    pin_count: positions.length,
    rows: null,
    cols: null,
    pitch_mm: null,
    has_center_pad: false,
  };
}

export function TargetPackageMap({
  packageName,
  positions,
  lens,
  activeLegendKey,
  positionVisuals,
  positionMatches,
  selectedPosition,
  onSelectPosition,
}: {
  packageName: string;
  positions: TargetDefinitionPosition[];
  lens: TargetMapLens;
  activeLegendKey?: string | null;
  positionVisuals?: Record<string, TargetMapPositionVisual>;
  positionMatches?: (position: TargetDefinitionPosition) => boolean;
  selectedPosition: string | null;
  onSelectPosition: (position: string) => void;
}) {
  const geometry = useMemo(() => targetGeometry(positions), [positions]);
  const layout = useMemo(
    () => pinMapGeometry(positions, geometry, VIEW, VIEW),
    [positions, geometry],
  );
  const byPosition = useMemo(
    () => new Map(positions.map((position) => [position.position, position])),
    [positions],
  );
  const areaArray = geometry.body_shape === "bga";
  const labels = useMemo(
    () => (areaArray ? [] : perimeterLabels(layout)),
    [areaArray, layout],
  );
  const headers = useMemo(
    () => (areaArray ? ballGridHeaders(positions, layout) : { rows: [], cols: [] }),
    [areaArray, positions, layout],
  );
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
    const selection = select(svg);
    selection.call(behavior);
    return () => {
      selection.on(".zoom", null);
    };
  }, []);

  const reset = useCallback(() => {
    const svg = svgRef.current;
    if (svg && zoomRef.current) {
      select(svg).call(zoomRef.current.transform, zoomIdentity);
    }
    setCamera(IDENTITY);
  }, []);

  const unavailable = layout.pins.length === 0;
  const unplaced = positions.length - layout.pins.length;
  const selected = selectedPosition
    ? byPosition.get(selectedPosition) ?? null
    : null;

  return (
    <div
      data-dev-id="stm.target-map"
      className="flex min-h-0 flex-1 flex-col"
      data-testid="target-package-map"
    >
      <div className="relative min-h-0 flex-1 overflow-hidden rounded-card border border-line bg-stage shadow-[inset_0_1px_0_var(--edge-hi)]">
        {!unavailable ? (
          <div className="absolute right-2 top-2 z-10">
            <IconButton
              type="button"
              compact
              small
              label="Reset View"
              icon={<RefreshIcon className="h-3.5 w-3.5" />}
              onClick={reset}
            />
          </div>
        ) : null}
        {unavailable ? (
          <div className="flex h-full flex-col p-3">
            <p className="mb-2 text-xs text-t3">
              <Text id="stm.target.package-map.no-geometry">
                This package has no drawable geometry. Select a physical position below.
              </Text>
            </p>
            <div className="min-h-0 flex-1 overflow-y-auto">
              {positions.map((position) => (
                <button
                  key={position.position}
                  type="button"
                  onClick={() => onSelectPosition(position.position)}
                  className="flex w-full items-center gap-2 rounded-control px-2 py-1 text-left hover:bg-hover"
                >
                  <span
                    className="h-2 w-2 rounded-full"
                    style={{
                      backgroundColor: targetPositionColor(
                        position,
                        lens,
                        activeLegendKey,
                      ),
                    }}
                  />
                  <span className="w-10 font-mono text-xs text-t3">{position.position}</span>
                  <span className="truncate font-mono text-xs text-t1">
                    {position.identities.map(formatElectricalIdentity).join(" / ")}
                  </span>
                </button>
              ))}
            </div>
          </div>
        ) : (
          <svg
            ref={svgRef}
            viewBox={`0 0 ${VIEW} ${VIEW}`}
            className="h-full w-full cursor-grab touch-none select-none active:cursor-grabbing"
            role="img"
            aria-label={`Universal MCU pinout for ${packageName}`}
            data-testid="target-package-map-svg"
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
              <text
                x={layout.body.x + layout.body.w / 2}
                y={layout.body.y + layout.body.h / 2 - 5}
                textAnchor="middle"
                className="fill-t1 font-mono"
                fontSize={15}
                fontWeight={600}
              >
                {packageName}
              </text>
              <text
                x={layout.body.x + layout.body.w / 2}
                y={layout.body.y + layout.body.h / 2 + 13}
                textAnchor="middle"
                className="fill-t3"
                fontSize={8}
              >
                {positions.length} Physical Positions
              </text>
              {layout.pins.map((pad) => {
                const position = byPosition.get(pad.position);
                return (
                  <TargetPad
                    key={pad.position}
                    pad={pad}
                    position={position}
                    lens={lens}
                    activeLegendKey={activeLegendKey}
                    visual={positionVisuals?.[pad.position]}
                    dimmed={
                      position != null &&
                      (positionMatches
                        ? !positionMatches(position)
                        : activeLegendKey != null &&
                          !targetMatchesLegend(position, lens, activeLegendKey))
                    }
                    selected={selectedPosition === pad.position}
                    onSelect={onSelectPosition}
                  />
                );
              })}
              <g className="pointer-events-none select-none">
                {labels.map((label) => (
                  <text
                    key={label.position}
                    x={label.x}
                    y={label.y}
                    textAnchor={label.anchor}
                    dominantBaseline="middle"
                    transform={
                      label.rotate
                        ? `rotate(${label.rotate} ${label.x} ${label.y})`
                        : undefined
                    }
                    className="fill-t3 font-mono"
                    fontSize={6}
                  >
                    {label.position}
                  </text>
                ))}
                {[...headers.rows, ...headers.cols].map((header, index) => (
                  <text
                    key={`${header.text}-${index}`}
                    x={header.x}
                    y={header.y}
                    textAnchor="middle"
                    dominantBaseline="middle"
                    className="fill-t3 font-mono"
                    fontSize={8}
                  >
                    {header.text}
                  </text>
                ))}
              </g>
            </g>
          </svg>
        )}
        {!unavailable ? (
          <div className="pointer-events-none absolute inset-x-2 bottom-2 flex items-end justify-between gap-3">
            <div className="min-w-0 rounded-control border border-line bg-popover/90 px-2 py-1 shadow-sm backdrop-blur-sm">
              <span className="font-mono text-2xs text-t1">
                {selected ? `Position ${selected.position}` : "No Position Selected"}
              </span>
              {selected ? (
                <span className="ml-1.5 text-2xs text-t3">
                  {positionVisuals?.[selected.position]?.description ??
                    targetPositionDescription(selected, lens)}
                </span>
              ) : null}
            </div>
            <span className="rounded-control bg-popover/80 px-2 py-1 text-2xs text-t3 backdrop-blur-sm">
              Drag To Pan · Scroll To Zoom
              {unplaced ? ` · ${unplaced} Unplaced` : ""}
            </span>
          </div>
        ) : null}
      </div>
    </div>
  );
}

const TargetPad = memo(function TargetPad({
  pad,
  position,
  lens,
  activeLegendKey,
  visual,
  dimmed,
  selected,
  onSelect,
}: {
  pad: PadLayout;
  position: TargetDefinitionPosition | undefined;
  lens: TargetMapLens;
  activeLegendKey?: string | null;
  visual?: TargetMapPositionVisual;
  dimmed: boolean;
  selected: boolean;
  onSelect: (position: string) => void;
}) {
  const { x, y, w, h } = pad.rect;
  const fill = visual?.fill ?? (position
    ? targetPositionColor(position, lens, activeLegendKey)
    : "var(--c-line2)");
  const description =
    visual?.description ??
    (position ? targetPositionDescription(position, lens) : "Unknown");
  return (
    <g
      onClick={() => onSelect(pad.position)}
      onKeyDown={(event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          onSelect(pad.position);
        }
      }}
      role="button"
      tabIndex={0}
      aria-label={`Position ${pad.position}: ${description}`}
      className="cursor-pointer [&>rect.pad]:hover:brightness-110"
      opacity={dimmed ? 0.18 : 1}
      data-position={pad.position}
      data-lens={lens}
    >
      <title>
        {position ? `${position.position} · ${description}` : position}
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
        fill={fill}
        stroke={
          visual?.stroke ??
          (position?.silicon_class === "safety_collision"
            ? "var(--c-err)"
            : "var(--c-line2)")
        }
        strokeWidth={
          visual?.stroke || position?.silicon_class === "safety_collision" ? 2 : 1
        }
        strokeDasharray={
          visual?.dashed || position?.silicon_class === "partial"
            ? "2 1.5"
            : undefined
        }
      />
      {visual?.marker && visual.marker > 1 ? (
        <circle
          cx={x + w - 1.5}
          cy={y + 1.5}
          r={1.5}
          fill="var(--c-stage)"
          stroke="var(--c-line2)"
          strokeWidth={0.5}
        />
      ) : null}
      {visual?.agreement != null && visual.agreement < 100 ? (
        w >= h ? (
          <>
            <rect
              x={x + 1}
              y={y + h - 2}
              width={Math.max(0, w - 2)}
              height={1}
              rx={0.5}
              fill="var(--c-stage)"
              opacity={0.75}
            />
            <rect
              x={x + 1}
              y={y + h - 2}
              width={Math.max(0, (w - 2) * (visual.agreement / 100))}
              height={1}
              rx={0.5}
              fill="var(--c-t1)"
              opacity={0.9}
            />
          </>
        ) : (
          <>
            <rect
              x={x + w - 2}
              y={y + 1}
              width={1}
              height={Math.max(0, h - 2)}
              rx={0.5}
              fill="var(--c-stage)"
              opacity={0.75}
            />
            <rect
              x={x + w - 2}
              y={y + h - 1 - Math.max(0, (h - 2) * (visual.agreement / 100))}
              width={1}
              height={Math.max(0, (h - 2) * (visual.agreement / 100))}
              rx={0.5}
              fill="var(--c-t1)"
              opacity={0.9}
            />
          </>
        )
      ) : null}
      {visual?.active ? (
        <circle
          cx={x + w / 2}
          cy={y + h / 2}
          r={Math.max(1.2, Math.min(w, h) * 0.18)}
          fill="var(--c-acc-strong)"
          stroke="var(--c-stage)"
          strokeWidth={0.6}
        />
      ) : null}
      {visual?.hazard === "critical" ? (
        <g pointerEvents="none" opacity={0.95}>
          <line
            x1={x + 1}
            y1={y + 1}
            x2={x + w - 1}
            y2={y + h - 1}
            stroke="var(--c-err)"
            strokeWidth={1}
          />
          <line
            x1={x + w - 1}
            y1={y + 1}
            x2={x + 1}
            y2={y + h - 1}
            stroke="var(--c-err)"
            strokeWidth={1}
          />
        </g>
      ) : visual?.hazard === "high" ? (
        <rect
          pointerEvents="none"
          x={x + 1}
          y={y + 1}
          width={Math.max(0, w - 2)}
          height={Math.max(0, h - 2)}
          rx={1}
          fill="none"
          stroke="var(--c-warn)"
          strokeWidth={0.8}
          strokeDasharray="1.5 1"
        />
      ) : null}
    </g>
  );
});
