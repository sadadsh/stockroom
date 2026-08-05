/**
 * The land pattern, drawn as a technical drawing rather than shown as a thumbnail.
 *
 * The footprint preview used to be a monochrome raster of whatever kicad-cli chose to draw. That
 * answers "is there a footprint" and nothing else. What a person checks a land pattern for is
 * whether the copper matches the package, whether pad 1 is where the datasheet says, whether
 * there is a courtyard at all, and how big the thing actually is - and every one of those needs
 * the geometry, not a picture of it.
 *
 * So the pads and the drawn line work arrive as data and are drawn here, on separately
 * switchable layers. Each layer is a real property of the file:
 *
 *   copper       the pads themselves, on their declared copper layer
 *   mask         the solder-mask aperture, drawn ONLY for pads that declare a `.Mask` layer
 *   paste        the stencil aperture, drawn ONLY for pads that declare a `.Paste` layer
 *   silkscreen   the `.SilkS` line work - the human-readable outline
 *   fabrication  the `.Fab` line work - the assembly drawing
 *   courtyard    the `.CrtYd` keep-out
 *
 * Mask and paste are NOT inferred from copper. A pad that opens no aperture and one that opens a
 * full aperture are identical in copper and are different fabrication outcomes; defaulting them
 * would draw an aperture the footprint never asked for.
 *
 * KiCad's board frame is +Y DOWN, which is SVG's own convention, so unlike the symbol there is no
 * flip here - and that asymmetry is deliberate rather than an oversight: the two files really do
 * use different frames, and pretending otherwise is how a mirrored footprint looks plausible.
 */
import { useMemo, useState } from "react";
import type { LandGraphic, LandPad, LandPattern } from "../../api/client";
import { Text, useText } from "../../lib/copy";
import { usePanZoom } from "../../lib/usePanZoom";

/** Millimetres of clear space around the drawn art. */
const MARGIN = 0.5;

export type FootprintLayer =
  | "copper"
  | "mask"
  | "paste"
  | "silkscreen"
  | "fabrication"
  | "courtyard"
  | "numbers"
  | "origin"
  | "dimensions";

export type FootprintLayerState = Record<FootprintLayer, boolean>;

/** What the drawing starts with: the copper and the outline that make a land pattern readable. */
export function defaultFootprintLayers(): FootprintLayerState {
  return {
    copper: true,
    mask: false,
    paste: false,
    silkscreen: true,
    fabrication: false,
    courtyard: true,
    numbers: true,
    origin: false,
    dimensions: false,
  };
}

const LAYER_INK: Record<string, string> = {
  copper: "#b06a2c",
  mask: "#8d4fa0",
  paste: "#7a7a7a",
  silkscreen: "#3a3a3a",
  fabrication: "#96803a",
  courtyard: "#4a7a55",
};

function declares(pad: LandPad, suffix: string): boolean {
  return pad.layers.some((layer) => layer.endsWith(suffix));
}

function onLayer(graphic: LandGraphic, suffix: string): boolean {
  return graphic.layer.endsWith(suffix);
}

/**
 * What the drawing proves about this land pattern.
 *
 * Every value is MEASURED off the geometry that is on screen. `expectedPins` and
 * `expectedPitch` come from the component's own specification, so each comparison has two
 * independent sides; when the specification does not state one, the comparison is honestly
 * absent rather than assumed to pass.
 */
export interface FootprintEvidence {
  pads: number;
  expectedPins: number | null;
  /** Numbers carried by more than one pad. Two pads answering to "3" is a real fault. */
  duplicates: string[];
  unnumbered: number;
  /** Whether a pad numbered "1" exists at all - the marker every orientation check starts from. */
  hasPinOne: boolean;
  /** The most common centre-to-centre spacing between neighbouring pads, in mm. */
  pitch: number | null;
  expectedPitch: number | null;
  courtyard: boolean;
  /** The copper extent in millimetres. What the part actually occupies. */
  size: { width: number; height: number } | null;
}

/**
 * The pitch, as the most common nearest-neighbour distance rounded to 0.01 mm.
 *
 * Nearest-neighbour rather than "adjacent in the file", because pad order in a `.kicad_mod` is
 * whatever the exporter wrote and a dual-row package interleaves its rows in some of them. The
 * MODE rather than the mean, because one deliberately offset pad (an exposed pad, a polarity
 * key) would drag an average away from the pitch every other pad actually sits on.
 */
export function padPitch(pads: LandPad[]): number | null {
  if (pads.length < 2) return null;
  const distances: number[] = [];
  for (const pad of pads) {
    let best = Infinity;
    for (const other of pads) {
      if (other === pad) continue;
      const distance = Math.hypot(other.at[0] - pad.at[0], other.at[1] - pad.at[1]);
      if (distance > 0 && distance < best) best = distance;
    }
    if (Number.isFinite(best)) distances.push(Math.round(best * 100) / 100);
  }
  if (distances.length === 0) return null;
  const counts = new Map<number, number>();
  for (const value of distances) counts.set(value, (counts.get(value) ?? 0) + 1);
  const ranked = [...counts.entries()].sort((a, b) => b[1] - a[1] || a[0] - b[0]);
  return ranked[0][0];
}

export function footprintEvidence(
  land: LandPattern,
  expected: { pins: number | null; pitch: number | null },
): FootprintEvidence {
  const seen = new Map<string, number>();
  for (const pad of land.pads) {
    if (!pad.number) continue;
    seen.set(pad.number, (seen.get(pad.number) ?? 0) + 1);
  }
  const box = copperBounds(land.pads);
  return {
    pads: land.pads.length,
    expectedPins: expected.pins,
    duplicates: [...seen.entries()].filter(([, count]) => count > 1).map(([number]) => number),
    unnumbered: land.pads.filter((pad) => !pad.number).length,
    hasPinOne: land.pads.some((pad) => pad.number === "1"),
    pitch: padPitch(land.pads),
    expectedPitch: expected.pitch,
    courtyard: land.graphics.some((graphic) => onLayer(graphic, ".CrtYd")),
    size: box ? { width: box.width, height: box.height } : null,
  };
}

function copperBounds(pads: LandPad[]) {
  if (pads.length === 0) return null;
  const xs: number[] = [];
  const ys: number[] = [];
  for (const pad of pads) {
    // Rotation is respected by taking the pad's circumscribed extent, so a 90-degree pad is not
    // measured as though it were still lying the other way.
    const half = Math.hypot(pad.size[0], pad.size[1]) / 2;
    xs.push(pad.at[0] - half, pad.at[0] + half);
    ys.push(pad.at[1] - half, pad.at[1] + half);
  }
  const x = Math.min(...xs);
  const y = Math.min(...ys);
  return { x, y, width: Math.max(...xs) - x, height: Math.max(...ys) - y };
}

/** One placed measurement, in the footprint's own millimetre frame. */
export interface Measurement {
  from: [number, number];
  to: [number, number];
}

export function measurementLength(measurement: Measurement): number {
  return Math.hypot(
    measurement.to[0] - measurement.from[0],
    measurement.to[1] - measurement.from[1],
  );
}

export function FootprintPreview({
  land,
  layers,
  measuring = false,
  measurement = null,
  onMeasure,
  interactive = true,
}: {
  land: LandPattern;
  layers: FootprintLayerState;
  /** While measuring, a click places a point instead of starting a pan. */
  measuring?: boolean;
  measurement?: Measurement | null;
  onMeasure?: (point: [number, number]) => void;
  interactive?: boolean;
}) {
  const { view, frameRef, handlers, reset } = usePanZoom();
  const canvasLabel = useText(
    "component-browser.footprint-canvas",
    "Land pattern drawing. Drag to pan, scroll to zoom, press 0 to fit.",
  );

  const box = useMemo(() => {
    const xs: number[] = [];
    const ys: number[] = [];
    for (const pad of land.pads) {
      const half = Math.hypot(pad.size[0], pad.size[1]) / 2;
      xs.push(pad.at[0] - half, pad.at[0] + half);
      ys.push(pad.at[1] - half, pad.at[1] + half);
    }
    for (const graphic of land.graphics) {
      xs.push(graphic.start[0], graphic.end[0]);
      ys.push(graphic.start[1], graphic.end[1]);
    }
    if (xs.length === 0 || ys.length === 0) return null;
    const x = Math.min(...xs) - MARGIN;
    const y = Math.min(...ys) - MARGIN;
    return {
      x,
      y,
      width: Math.max(...xs) - Math.min(...xs) + 2 * MARGIN,
      height: Math.max(...ys) - Math.min(...ys) + 2 * MARGIN,
    };
  }, [land]);

  if (box === null || box.width <= 0 || box.height <= 0) {
    return (
      <p className="ui-row-secondary px-2 py-3 text-center">
        <Text id="component-browser.footprint-no-geometry">
          This footprint draws no pads and no outline.
        </Text>
      </p>
    );
  }

  const copper = copperBounds(land.pads);
  const scale = Math.max(box.width, box.height);

  return (
    <div
      // The pan/zoom frame is attached ONLY when this drawing is interactive. `usePanZoom` binds
      // a non-passive wheel listener to whatever it is given, so a compacted module would have
      // swallowed the column's scroll and zoomed a preview nobody was pointing at.
      ref={interactive ? frameRef : undefined}
      data-dev-id="component-browser.footprint-canvas"
      role={interactive ? "application" : undefined}
      aria-label={interactive ? canvasLabel : undefined}
      tabIndex={interactive ? 0 : -1}
      onDoubleClick={interactive && !measuring ? reset : undefined}
      onKeyDown={
        interactive
          ? (event) => {
              if (event.key === "0" || event.key.toLowerCase() === "f") {
                event.preventDefault();
                reset();
              }
            }
          : undefined
      }
      onClick={
        measuring && onMeasure
          ? (event) => {
              const frame = event.currentTarget.getBoundingClientRect();
              // The SVG keeps its aspect ratio inside the frame, so the drawn area is centred
              // and the click has to be mapped through the SAME letterboxing - reading the frame
              // alone would report a point the drawing never contained.
              const fit = Math.min(frame.width / box.width, frame.height / box.height);
              const drawnWidth = box.width * fit;
              const drawnHeight = box.height * fit;
              const offsetX = (frame.width - drawnWidth) / 2;
              const offsetY = (frame.height - drawnHeight) / 2;
              const localX = (event.clientX - frame.left - view.x) / view.scale;
              const localY = (event.clientY - frame.top - view.y) / view.scale;
              onMeasure([
                box.x + (localX - offsetX) / fit,
                box.y + (localY - offsetY) / fit,
              ]);
            }
          : undefined
      }
      className={
        "relative h-full w-full overflow-hidden bg-technical outline-none " +
        "focus-visible:outline focus-visible:outline-2 focus-visible:-outline-offset-2 " +
        "focus-visible:outline-focus " +
        (!interactive ? "cursor-default" : measuring ? "cursor-crosshair" : "cursor-grab active:cursor-grabbing")
      }
      {...(interactive && !measuring ? handlers : {})}
    >
      <svg
        viewBox={`${box.x} ${box.y} ${box.width} ${box.height}`}
        preserveAspectRatio="xMidYMid meet"
        className="h-full w-full"
        style={{
          transform: `translate(${view.x}px, ${view.y}px) scale(${view.scale})`,
          transformOrigin: "center",
        }}
      >
        {layers.fabrication ? <Lines land={land} suffix=".Fab" layer="fabrication" /> : null}
        {layers.courtyard ? <Lines land={land} suffix=".CrtYd" layer="courtyard" /> : null}
        {layers.mask
          ? land.pads
              .filter((pad) => declares(pad, ".Mask"))
              .map((pad, index) => <Pad key={`mask-${index}`} pad={pad} layer="mask" hollow />)
          : null}
        {layers.copper
          ? land.pads.map((pad, index) => <Pad key={`cu-${index}`} pad={pad} layer="copper" />)
          : null}
        {layers.paste
          ? land.pads
              .filter((pad) => declares(pad, ".Paste"))
              .map((pad, index) => <Pad key={`paste-${index}`} pad={pad} layer="paste" hollow />)
          : null}
        {layers.silkscreen ? <Lines land={land} suffix=".SilkS" layer="silkscreen" /> : null}

        {/* Pin 1, always drawn when the copper is: every orientation check starts from it, and
            hiding it behind a toggle would make the most important pad the easiest to lose. */}
        {layers.copper ? <PinOneMarker pads={land.pads} scale={scale} /> : null}
        {layers.origin ? <Origin scale={scale} /> : null}
        {layers.dimensions && copper ? <Dimensions box={copper} scale={scale} /> : null}
        {layers.numbers ? (
          <g fontSize={scale * 0.045} fill="#1b1b1b" textAnchor="middle">
            {land.pads.map((pad, index) => (
              <text
                key={index}
                x={pad.at[0]}
                y={pad.at[1] + scale * 0.016}
                data-layer="numbers"
              >
                {pad.number}
              </text>
            ))}
          </g>
        ) : null}
        {measurement ? <MeasurementLine measurement={measurement} scale={scale} /> : null}
      </svg>
    </div>
  );
}

function Pad({ pad, layer, hollow = false }: { pad: LandPad; layer: string; hollow?: boolean }) {
  const ink = LAYER_INK[layer];
  const [w, h] = pad.size;
  const radius =
    pad.shape === "circle" || pad.shape === "oval"
      ? Math.min(w, h) / 2
      : pad.shape === "roundrect"
        ? Math.min(w, h) * pad.rratio
        : 0;
  return (
    <g transform={`translate(${pad.at[0]} ${pad.at[1]}) rotate(${-pad.rotation})`}>
      <rect
        x={-w / 2}
        y={-h / 2}
        width={w}
        height={h}
        rx={radius}
        ry={radius}
        fill={hollow ? "none" : ink}
        stroke={hollow ? ink : "none"}
        strokeWidth={hollow ? Math.min(w, h) * 0.08 : 0}
        fillOpacity={hollow ? 0 : 0.85}
        data-layer={layer}
        data-pad={pad.number}
      />
      {/* A through-hole pad is drawn WITH its hole. Solid copper where a drill is specified is
          not what was downloaded, and 44% of the real library is through-hole. */}
      {!hollow && pad.drill > 0 ? (
        <circle cx={0} cy={0} r={pad.drill / 2} fill="#f5f5f2" data-drill="true" />
      ) : null}
    </g>
  );
}

function Lines({ land, suffix, layer }: { land: LandPattern; suffix: string; layer: string }) {
  return (
    <g stroke={LAYER_INK[layer]} strokeLinecap="round" data-layer={layer}>
      {land.graphics
        .filter((graphic) => onLayer(graphic, suffix))
        .map((graphic, index) => (
          <line
            key={index}
            x1={graphic.start[0]}
            y1={graphic.start[1]}
            x2={graphic.end[0]}
            y2={graphic.end[1]}
            strokeWidth={graphic.width > 0 ? graphic.width : 0.1}
          />
        ))}
    </g>
  );
}

function PinOneMarker({ pads, scale }: { pads: LandPad[]; scale: number }) {
  const first = pads.find((pad) => pad.number === "1");
  if (!first) return null;
  const half = Math.max(first.size[0], first.size[1]) / 2;
  return (
    <circle
      cx={first.at[0]}
      cy={first.at[1]}
      r={half + scale * 0.03}
      fill="none"
      stroke="#b0392c"
      strokeWidth={scale * 0.012}
      data-pin-one="true"
    />
  );
}

function Origin({ scale }: { scale: number }) {
  const arm = scale * 0.08;
  return (
    <g stroke="#4a4a4a" strokeWidth={scale * 0.008} data-layer="origin">
      <line x1={-arm} y1={0} x2={arm} y2={0} />
      <line x1={0} y1={-arm} x2={0} y2={arm} />
    </g>
  );
}

function Dimensions({
  box,
  scale,
}: {
  box: { x: number; y: number; width: number; height: number };
  scale: number;
}) {
  const gap = scale * 0.06;
  return (
    <g stroke="#4a4a4a" strokeWidth={scale * 0.006} data-layer="dimensions">
      <line x1={box.x} y1={box.y - gap} x2={box.x + box.width} y2={box.y - gap} />
      <line x1={box.x - gap} y1={box.y} x2={box.x - gap} y2={box.y + box.height} />
      <text
        x={box.x + box.width / 2}
        y={box.y - gap * 1.4}
        fontSize={scale * 0.045}
        fill="#4a4a4a"
        stroke="none"
        textAnchor="middle"
      >
        {`${box.width.toFixed(2)} mm`}
      </text>
      <text
        x={box.x - gap * 1.4}
        y={box.y + box.height / 2}
        fontSize={scale * 0.045}
        fill="#4a4a4a"
        stroke="none"
        textAnchor="end"
      >
        {`${box.height.toFixed(2)} mm`}
      </text>
    </g>
  );
}

function MeasurementLine({
  measurement,
  scale,
}: {
  measurement: Measurement;
  scale: number;
}) {
  const length = measurementLength(measurement);
  return (
    <g data-layer="measurement">
      <line
        x1={measurement.from[0]}
        y1={measurement.from[1]}
        x2={measurement.to[0]}
        y2={measurement.to[1]}
        stroke="#1b1b1b"
        strokeWidth={scale * 0.008}
      />
      <text
        x={(measurement.from[0] + measurement.to[0]) / 2}
        y={(measurement.from[1] + measurement.to[1]) / 2 - scale * 0.02}
        fontSize={scale * 0.05}
        fill="#1b1b1b"
        textAnchor="middle"
      >
        {`${length.toFixed(2)} mm`}
      </text>
    </g>
  );
}

/** Local state for the layer switches and the measuring tool. */
export function useFootprintLayers() {
  const [layers, setLayers] = useState<FootprintLayerState>(defaultFootprintLayers);
  const [measuring, setMeasuring] = useState(false);
  const [points, setPoints] = useState<[number, number][]>([]);
  const measurement: Measurement | null =
    points.length === 2 ? { from: points[0], to: points[1] } : null;
  return {
    layers,
    toggle: (layer: FootprintLayer) =>
      setLayers((current) => ({ ...current, [layer]: !current[layer] })),
    measuring,
    measurement,
    toggleMeasuring: () => {
      setMeasuring((current) => !current);
      setPoints([]);
    },
    // A third click starts a new measurement rather than extending the old one: a ruler that
    // silently keeps its first point is a ruler that measures the wrong thing.
    place: (point: [number, number]) =>
      setPoints((current) => (current.length >= 2 ? [point] : [...current, point])),
  };
}
