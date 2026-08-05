/**
 * The symbol, drawn from the file rather than shown as a picture of it.
 *
 * A rendered SVG can only be looked at. The questions the CAD column exists to answer about a
 * symbol are questions about the DATA - how many pins, does a number repeat, is that one a power
 * input, is the body actually drawn - and none of them survive rasterisation. So this reads the
 * geometry endpoint and draws it, which buys three things a picture cannot:
 *
 *   * the three visibility toggles are REAL. Pin name, pin number and electrical type each
 *     redraw from the same data, with no round trip and no second render;
 *   * the validation evidence is measured off the same pins the person is looking at, so the
 *     footer and the drawing can never disagree;
 *   * an unparseable library is a state the module can SAY, instead of an empty frame.
 *
 * KiCad's schematic frame is +Y UP; SVG's is +Y down. The flip happens once, here, in the
 * viewBox transform - never per shape, because a per-shape flip is how a mirrored symbol ends up
 * looking plausible.
 */
import { useMemo, useState } from "react";
import type { SymbolGeometry, SymbolPin } from "../../api/client";
import { Text, useText } from "../../lib/copy";
import { usePanZoom } from "../../lib/usePanZoom";

/** Millimetres of clear space around the drawn art, so nothing touches the frame edge. */
const MARGIN = 1.27;

/** The layers a person can turn on and off. Each is a real property of the pins being drawn. */
export type SymbolLayer = "pinName" | "pinNumber" | "electrical";

export interface SymbolLayerState {
  pinName: boolean;
  pinNumber: boolean;
  electrical: boolean;
}

/**
 * The evidence the footer states, measured from the geometry.
 *
 * Every number here is counted off the pins that were actually drawn. `expectedPins` comes from
 * the component's own specification (its pin count), so "5 pins matched" is a comparison and not
 * a restatement of one side of it - and when the specification does not say, the comparison is
 * honestly absent rather than assumed to pass.
 */
export interface SymbolEvidence {
  pins: number;
  expectedPins: number | null;
  /** Numbers that appear on more than one pin. A real fault, not a style choice. */
  duplicates: string[];
  /** Pins carrying no number at all: a terminal nothing can be mapped to. */
  unnumbered: number;
  hidden: number;
  /** Whether the symbol draws a body at all, and how big it is in millimetres. */
  bounds: { width: number; height: number } | null;
}

export function symbolEvidence(
  geometry: SymbolGeometry,
  expectedPins: number | null,
): SymbolEvidence {
  const seen = new Map<string, number>();
  for (const pin of geometry.pins) {
    if (!pin.number) continue;
    seen.set(pin.number, (seen.get(pin.number) ?? 0) + 1);
  }
  return {
    pins: geometry.pins.length,
    expectedPins,
    duplicates: [...seen.entries()].filter(([, count]) => count > 1).map(([number]) => number),
    unnumbered: geometry.pins.filter((pin) => !pin.number).length,
    hidden: geometry.pins.filter((pin) => pin.hidden).length,
    bounds: geometry.bounds
      ? { width: geometry.bounds.width, height: geometry.bounds.height }
      : null,
  };
}

/** Short electrical-type initials, drawn beside a pin when the type layer is on. */
const ELECTRICAL_SHORT: Record<string, string> = {
  input: "I",
  output: "O",
  bidirectional: "B",
  tri_state: "T",
  passive: "P",
  free: "F",
  unspecified: "U",
  power_in: "PWR",
  power_out: "PWR",
  open_collector: "OC",
  open_emitter: "OE",
  no_connect: "NC",
};

export function SymbolPreview({
  geometry,
  layers,
  interactive = true,
}: {
  geometry: SymbolGeometry;
  layers: SymbolLayerState;
  /** A collapsed module shows the same drawing without taking the pointer or the tab stop. */
  interactive?: boolean;
}) {
  const { view, frameRef, handlers, reset } = usePanZoom();
  const canvasLabel = useText(
    "component-browser.symbol-canvas",
    "Symbol drawing. Drag to pan, scroll to zoom, press 0 to fit.",
  );

  const box = useMemo(() => {
    const bounds = geometry.bounds;
    if (!bounds || bounds.width <= 0 || bounds.height <= 0) return null;
    return {
      x: bounds.x - MARGIN,
      y: bounds.y - MARGIN,
      width: bounds.width + 2 * MARGIN,
      height: bounds.height + 2 * MARGIN,
    };
  }, [geometry.bounds]);

  if (box === null) {
    return (
      <p className="ui-row-secondary px-2 py-3 text-center">
        <Text id="component-browser.symbol-no-geometry">
          This symbol draws no body and no pins.
        </Text>
      </p>
    );
  }

  // ONE flip, on the whole drawing: KiCad's schematic frame is +Y up and SVG's is +Y down.
  const flip = `translate(0, ${2 * box.y + box.height}) scale(1, -1)`;

  return (
    <div
      // The pan/zoom frame is attached ONLY when this drawing is interactive. `usePanZoom` binds
      // a non-passive wheel listener to whatever it is given, so a compacted module would have
      // swallowed the column's scroll and zoomed a preview nobody was pointing at.
      ref={interactive ? frameRef : undefined}
      data-dev-id="component-browser.symbol-canvas"
      role={interactive ? "application" : undefined}
      aria-label={interactive ? canvasLabel : undefined}
      tabIndex={interactive ? 0 : -1}
      onDoubleClick={interactive ? reset : undefined}
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
      className={
        "relative h-full w-full overflow-hidden bg-technical outline-none " +
        "focus-visible:outline focus-visible:outline-2 focus-visible:-outline-offset-2 " +
        "focus-visible:outline-focus " +
        (interactive ? "cursor-grab active:cursor-grabbing" : "cursor-default")
      }
      {...(interactive ? handlers : {})}
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
        {/* The technical canvas is a light surface in BOTH themes, so the ink is fixed dark
            rather than theme-flipped: a symbol that inverts with the app is a symbol whose
            filled body reads as a hole in one of the two. */}
        <g transform={flip} fill="none" stroke="#1b1b1b" strokeLinecap="round">
          {geometry.graphics.map((shape, index) => (
            <SymbolShape key={index} shape={shape} />
          ))}
          {geometry.pins.map((pin, index) => (
            <PinLine key={index} pin={pin} />
          ))}
        </g>
        {/* Text is drawn OUTSIDE the flip, with its own per-pin placement, because a mirrored
            glyph is not a smaller mistake than a mirrored body. */}
        <g fontSize={1.1} fill="#1b1b1b">
          {geometry.pins.map((pin, index) => (
            <PinLabels
              key={index}
              pin={pin}
              layers={layers}
              flipY={2 * box.y + box.height}
            />
          ))}
        </g>
      </svg>
    </div>
  );
}

function SymbolShape({ shape }: { shape: SymbolGeometry["graphics"][number] }) {
  // KiCad's `background` fill is the pale body wash behind an IC rectangle; `outline` is a solid
  // fill. Both are drawn, because a symbol whose body is a hollow outline when the file says it
  // is filled is a different symbol.
  const fill =
    shape.fill === "background" ? "#f0efe8" : shape.fill === "outline" ? "#1b1b1b" : "none";
  const width = shape.width > 0 ? shape.width : 0.15;
  if (shape.kind === "rectangle") {
    const [a, b] = shape.points;
    if (!a || !b) return null;
    return (
      <rect
        x={Math.min(a[0], b[0])}
        y={Math.min(a[1], b[1])}
        width={Math.abs(b[0] - a[0])}
        height={Math.abs(b[1] - a[1])}
        fill={fill}
        strokeWidth={width}
      />
    );
  }
  if (shape.kind === "circle") {
    return (
      <circle
        cx={shape.center[0]}
        cy={shape.center[1]}
        r={shape.radius}
        fill={fill}
        strokeWidth={width}
      />
    );
  }
  const points = shape.points.map(([x, y]) => `${x},${y}`).join(" ");
  return <polyline points={points} fill={fill} strokeWidth={width} />;
}

function pinEnd(pin: SymbolPin): [number, number] {
  const radians = (pin.angle * Math.PI) / 180;
  return [pin.at[0] + pin.length * Math.cos(radians), pin.at[1] + pin.length * Math.sin(radians)];
}

function PinLine({ pin }: { pin: SymbolPin }) {
  if (pin.hidden) return null;
  const [x2, y2] = pinEnd(pin);
  return (
    <line
      x1={pin.at[0]}
      y1={pin.at[1]}
      x2={x2}
      y2={y2}
      strokeWidth={0.15}
      data-pin={pin.number}
    />
  );
}

/**
 * The three text layers, each placed relative to the pin it belongs to.
 *
 * The number sits just outside the body along the pin; the name sits just inside it; the
 * electrical type sits at the connection end. That is KiCad's own arrangement, and following it
 * means a person reading this drawing and the same symbol in an editor sees the same thing.
 */
function PinLabels({
  pin,
  layers,
  flipY,
}: {
  pin: SymbolPin;
  layers: SymbolLayerState;
  flipY: number;
}) {
  if (pin.hidden) return null;
  const [bodyX, bodyY] = pinEnd(pin);
  const horizontal = Math.abs(Math.cos((pin.angle * Math.PI) / 180)) > 0.5;
  const towardsBody = Math.cos((pin.angle * Math.PI) / 180) >= 0 ? 1 : -1;
  const screen = (y: number) => flipY - y;
  const anchor = horizontal ? (towardsBody > 0 ? "start" : "end") : "middle";
  return (
    <>
      {layers.pinNumber && pin.number ? (
        <text
          x={(pin.at[0] + bodyX) / 2}
          y={screen((pin.at[1] + bodyY) / 2) - 0.35}
          textAnchor="middle"
          data-layer="pinNumber"
        >
          {pin.number}
        </text>
      ) : null}
      {layers.pinName && pin.name && pin.name !== "~" ? (
        <text
          x={bodyX + (horizontal ? towardsBody * 0.5 : 0)}
          y={screen(bodyY) + (horizontal ? 0.4 : towardsBody > 0 ? 1.3 : -0.6)}
          textAnchor={anchor}
          data-layer="pinName"
        >
          {pin.name}
        </text>
      ) : null}
      {layers.electrical ? (
        <text
          x={pin.at[0] - (horizontal ? towardsBody * 0.5 : 0)}
          y={screen(pin.at[1]) - 0.35}
          textAnchor={horizontal ? (towardsBody > 0 ? "end" : "start") : "middle"}
          fill="#6a6a6a"
          fontSize={0.85}
          data-layer="electrical"
        >
          {ELECTRICAL_SHORT[pin.electrical] ?? pin.electrical}
        </text>
      ) : null}
    </>
  );
}

/** The three toggles' initial state: names and numbers on unless the file itself hides them. */
export function defaultSymbolLayers(geometry: SymbolGeometry | undefined): SymbolLayerState {
  return {
    pinName: geometry ? !geometry.namesHidden : true,
    pinNumber: geometry ? !geometry.numbersHidden : true,
    // Off by default: electrical type is a diagnostic, and drawing it unasked crowds every
    // terminal on a hundred-pin part with a second short string.
    electrical: false,
  };
}

/** Local state for the three toggles, seeded from what the file asks for. */
export function useSymbolLayers(geometry: SymbolGeometry | undefined) {
  const [override, setOverride] = useState<Partial<SymbolLayerState>>({});
  const base = defaultSymbolLayers(geometry);
  const layers: SymbolLayerState = { ...base, ...override };
  return {
    layers,
    toggle: (layer: SymbolLayer) =>
      setOverride((current) => ({ ...current, [layer]: !layers[layer] })),
  };
}
