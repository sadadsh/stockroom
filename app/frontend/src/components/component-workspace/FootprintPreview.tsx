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
import type { LandPad, LandPattern } from "../../api/client";
import { TECHNICAL_CONTENT_ATTRIBUTE } from "../../design-studio/targetDomains";
import { useOptionalDesignStudio } from "../../design-studio/DesignStudioProvider";
import { Text, useText } from "../../lib/copy";
import { usePanZoom } from "../../lib/usePanZoom";
import { copperBounds, onLayer } from "./cadEvidence";

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
function defaultFootprintLayers(): FootprintLayerState {
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

/**
 * One class pair per layer, on the tokenised drawing palette.
 *
 * These were six fixed hexes tuned for a near-white sheet, which is what made the sheet itself
 * un-themeable: the moment the canvas followed the theme, a #3a3a3a silkscreen would have gone
 * invisible on it. Each layer is now a token declared for BOTH themes, and
 * `styles/visualLanguage.test.ts` measures every one of them against its own sheet (>=3:1) and
 * against each other (>=15 CIE76 dE), so copper, mask, paste, silkscreen, fabrication and
 * courtyard stay six distinguishable answers in dark theme as well as light.
 */
const LAYER_INK: Record<string, { fill: string; stroke: string }> = {
  copper: { fill: "fill-layer-copper", stroke: "stroke-layer-copper" },
  mask: { fill: "fill-layer-mask", stroke: "stroke-layer-mask" },
  paste: { fill: "fill-layer-paste", stroke: "stroke-layer-paste" },
  silkscreen: { fill: "fill-layer-silk", stroke: "stroke-layer-silk" },
  fabrication: { fill: "fill-layer-fab", stroke: "stroke-layer-fab" },
  courtyard: { fill: "fill-layer-courtyard", stroke: "stroke-layer-courtyard" },
};

function declares(pad: LandPad, suffix: string): boolean {
  return pad.layers.some((layer) => layer.endsWith(suffix));
}

/**
 * A pad's identity, so a redraw reconciles each pad against the pad it IS.
 *
 * Not the array index. Three of the drawings below are drawn from a SUBSET of the pads - the mask
 * apertures, the paste apertures - so a position in one of those lists names a different pad the
 * moment a pad that declares that layer is added, removed or reordered upstream.
 *
 * The pad number alone is not enough either, and this file measures the two reasons why: a land
 * pattern is allowed to carry `unnumbered` pads (mounting holes, a thermal slug) and `duplicates`
 * (two pads answering to "3" is a real fault the evidence footer REPORTS rather than one this
 * drawing may assume away). What genuinely identifies a pad is where it sits and how big it is, in
 * the footprint's own millimetre frame, so that is what is used - with the number in front of it,
 * where there is one.
 */
function padKey(pad: LandPad): string {
  return `${pad.number}@${pad.at[0]},${pad.at[1]}#${pad.size[0]}x${pad.size[1]}`;
}

/** One placed measurement, in the footprint's own millimetre frame. */
export interface Measurement {
  from: [number, number];
  to: [number, number];
}

function measurementLength(measurement: Measurement): number {
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
  const presentation = useOptionalDesignStudio()?.resolvedCadPresentation["cad.footprint"]?.footprint;
  const visibleLayers: FootprintLayerState = {
    ...layers,
    copper: layers.copper && presentation?.pads !== false,
    fabrication: layers.fabrication && presentation?.fabrication !== false,
    courtyard: layers.courtyard && presentation?.courtyard !== false,
    silkscreen: layers.silkscreen && presentation?.silkscreen !== false,
    numbers: layers.numbers && presentation?.reference !== false && presentation?.value !== false,
  };
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
      {...{ [TECHNICAL_CONTENT_ATTRIBUTE]: "true" }}
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
        {visibleLayers.fabrication ? <Lines land={land} suffix=".Fab" layer="fabrication" color={presentation?.layerColors?.fabrication} /> : null}
        {visibleLayers.courtyard ? <Lines land={land} suffix=".CrtYd" layer="courtyard" color={presentation?.layerColors?.courtyard} /> : null}
        {visibleLayers.mask
          ? land.pads
              .filter((pad) => declares(pad, ".Mask"))
              .map((pad) => <Pad key={`mask-${padKey(pad)}`} pad={pad} layer="mask" color={presentation?.layerColors?.mask} hollow />)
          : null}
        {visibleLayers.copper
          ? land.pads.map((pad) => <Pad key={`cu-${padKey(pad)}`} pad={pad} layer="copper" color={presentation?.layerColors?.copper} />)
          : null}
        {visibleLayers.paste
          ? land.pads
              .filter((pad) => declares(pad, ".Paste"))
              .map((pad) => <Pad key={`paste-${padKey(pad)}`} pad={pad} layer="paste" color={presentation?.layerColors?.paste} hollow />)
          : null}
        {visibleLayers.silkscreen ? <Lines land={land} suffix=".SilkS" layer="silkscreen" color={presentation?.layerColors?.silkscreen} /> : null}

        {/* Pin 1, always drawn when the copper is: every orientation check starts from it, and
            hiding it behind a toggle would make the most important pad the easiest to lose. */}
        {visibleLayers.copper ? <PinOneMarker pads={land.pads} scale={scale} /> : null}
        {visibleLayers.origin ? <Origin scale={scale} /> : null}
        {visibleLayers.dimensions && copper ? <Dimensions box={copper} scale={scale} /> : null}
        {visibleLayers.numbers ? (
          <g fontSize={scale * 0.045} className="fill-technical-ink" textAnchor="middle">
            {land.pads.map((pad) => (
              <text
                key={padKey(pad)}
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

function Pad({ pad, layer, hollow = false, color }: { pad: LandPad; layer: string; hollow?: boolean; color?: string }) {
  const ink = LAYER_INK[layer];
  const paint = hollow ? `fill-none ${ink.stroke}` : `${ink.fill} stroke-none`;
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
        className={paint}
        style={color ? (hollow ? { stroke: color } : { fill: color }) : undefined}
        strokeWidth={hollow ? Math.min(w, h) * 0.08 : 0}
        fillOpacity={hollow ? 0 : 0.85}
        data-layer={layer}
        data-pad={pad.number}
      />
      {/* A through-hole pad is drawn WITH its hole. Solid copper where a drill is specified is
          not what was downloaded, and 44% of the real library is through-hole. The hole is the
          SHEET showing through, so it is the sheet's token rather than a repeated near-white. */}
      {!hollow && pad.drill > 0 ? (
        <circle
          cx={0}
          cy={0}
          r={pad.drill / 2}
          className="fill-technical"
          data-drill="true"
        />
      ) : null}
    </g>
  );
}

function Lines({ land, suffix, layer, color }: { land: LandPattern; suffix: string; layer: string; color?: string }) {
  return (
    <g className={LAYER_INK[layer].stroke} style={color ? { stroke: color } : undefined} strokeLinecap="round" data-layer={layer}>
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
      className="fill-none stroke-layer-pin-one"
      strokeWidth={scale * 0.012}
      data-pin-one="true"
    />
  );
}

function Origin({ scale }: { scale: number }) {
  const arm = scale * 0.08;
  return (
    <g className="stroke-technical-note" strokeWidth={scale * 0.008} data-layer="origin">
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
    <g className="stroke-technical-note" strokeWidth={scale * 0.006} data-layer="dimensions">
      <line x1={box.x} y1={box.y - gap} x2={box.x + box.width} y2={box.y - gap} />
      <line x1={box.x - gap} y1={box.y} x2={box.x - gap} y2={box.y + box.height} />
      <text
        x={box.x + box.width / 2}
        y={box.y - gap * 1.4}
        fontSize={scale * 0.045}
        className="fill-technical-note stroke-none"
        textAnchor="middle"
      >
        {`${box.width.toFixed(2)} mm`}
      </text>
      <text
        x={box.x - gap * 1.4}
        y={box.y + box.height / 2}
        fontSize={scale * 0.045}
        className="fill-technical-note stroke-none"
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
        className="stroke-technical-ink"
        strokeWidth={scale * 0.008}
      />
      <text
        x={(measurement.from[0] + measurement.to[0]) / 2}
        y={(measurement.from[1] + measurement.to[1]) / 2 - scale * 0.02}
        fontSize={scale * 0.05}
        className="fill-technical-ink"
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
