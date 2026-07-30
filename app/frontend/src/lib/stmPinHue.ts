/**
 * The STM viewer's color-is-data token mapping, mirroring lib/categoryHue.ts exactly: pure, total,
 * returns only var(--stm-*) token references (never a raw hex), exposes a color-mix tile-tint helper,
 * and falls back to the neutral --c-t2 token for an unknown input. It is the SINGLE source for the
 * viewer's two encoding axes, so no hue literal ever lands in a component (CONTEXT decision 4/5):
 *
 *   - pinElectricalHue(category): the ten API pin-category buckets (gpio/analog/debug/oscillator/
 *     power/ground/reset/boot/vcap/nc) plus the legacy io electrical_class (its own --stm-io token,
 *     the same hue as gpio, since the API only emits io before splitting it). PinoutMap, PinoutLegend,
 *     and PinInspector consume this; components/stm/pinEncoding.ts delegates its category fill here.
 *   - unionClassificationHue(classification): the three socket-union states (shared/divergent/
 *     partial), a DISTINCT token set because classification encodes a different fact than a pin's
 *     electrical class. CompatUnionMap consumes this (never the electrical-class hues).
 */

export interface StmHue {
  /** the matched key (a category / classification key, or "neutral") */
  key: string;
  /** the Title Case legend label */
  label: string;
  /** the design token the hue is built from (a --stm-* var, or --c-t2 for neutral) */
  token: string;
  /** the fill / stroke color, as a token reference (never a color value) */
  stroke: string;
  /** faint tile tint + hairline classes (color-mix vs transparent); "" keeps the neutral tile */
  tileClass: string;
}

export type PinCategory =
  | "gpio"
  | "analog"
  | "debug"
  | "oscillator"
  | "power"
  | "ground"
  | "reset"
  | "boot"
  | "vcap"
  | "nc";

export type UnionClassification = "shared" | "divergent" | "partial";

// Complete literals are deliberate: Tailwind's scanner cannot safely expand an
// arbitrary-value utility assembled from a `${token}` placeholder.
const TILE_CLASSES: Readonly<Record<string, string>> = {
  "--stm-gpio":
    "bg-[color-mix(in_srgb,var(--stm-gpio)_12%,transparent)] border-[color-mix(in_srgb,var(--stm-gpio)_34%,transparent)]",
  "--stm-analog":
    "bg-[color-mix(in_srgb,var(--stm-analog)_12%,transparent)] border-[color-mix(in_srgb,var(--stm-analog)_34%,transparent)]",
  "--stm-debug":
    "bg-[color-mix(in_srgb,var(--stm-debug)_12%,transparent)] border-[color-mix(in_srgb,var(--stm-debug)_34%,transparent)]",
  "--stm-oscillator":
    "bg-[color-mix(in_srgb,var(--stm-oscillator)_12%,transparent)] border-[color-mix(in_srgb,var(--stm-oscillator)_34%,transparent)]",
  "--stm-power":
    "bg-[color-mix(in_srgb,var(--stm-power)_12%,transparent)] border-[color-mix(in_srgb,var(--stm-power)_34%,transparent)]",
  "--stm-ground":
    "bg-[color-mix(in_srgb,var(--stm-ground)_12%,transparent)] border-[color-mix(in_srgb,var(--stm-ground)_34%,transparent)]",
  "--stm-reset":
    "bg-[color-mix(in_srgb,var(--stm-reset)_12%,transparent)] border-[color-mix(in_srgb,var(--stm-reset)_34%,transparent)]",
  "--stm-boot":
    "bg-[color-mix(in_srgb,var(--stm-boot)_12%,transparent)] border-[color-mix(in_srgb,var(--stm-boot)_34%,transparent)]",
  "--stm-vcap":
    "bg-[color-mix(in_srgb,var(--stm-vcap)_12%,transparent)] border-[color-mix(in_srgb,var(--stm-vcap)_34%,transparent)]",
  "--stm-nc":
    "bg-[color-mix(in_srgb,var(--stm-nc)_12%,transparent)] border-[color-mix(in_srgb,var(--stm-nc)_34%,transparent)]",
  "--stm-io":
    "bg-[color-mix(in_srgb,var(--stm-io)_12%,transparent)] border-[color-mix(in_srgb,var(--stm-io)_34%,transparent)]",
  "--stm-classify-shared":
    "bg-[color-mix(in_srgb,var(--stm-classify-shared)_12%,transparent)] border-[color-mix(in_srgb,var(--stm-classify-shared)_34%,transparent)]",
  "--stm-classify-divergent":
    "bg-[color-mix(in_srgb,var(--stm-classify-divergent)_12%,transparent)] border-[color-mix(in_srgb,var(--stm-classify-divergent)_34%,transparent)]",
  "--stm-classify-partial":
    "bg-[color-mix(in_srgb,var(--stm-classify-partial)_12%,transparent)] border-[color-mix(in_srgb,var(--stm-classify-partial)_34%,transparent)]",
};

// A hue descriptor for one token. The tile tint mirrors categoryHue's tileClass: a faint wash of the
// same hue plus a slightly stronger hairline, both mixed against transparent so they adapt per theme
// with no per-theme literal.
function makeHue(key: string, label: string, token: string): StmHue {
  return {
    key,
    label,
    token,
    stroke: `var(${token})`,
    tileClass: TILE_CLASSES[token] ?? "",
  };
}

const NEUTRAL: StmHue = {
  key: "neutral",
  label: "Unknown",
  token: "--c-t2",
  stroke: "var(--c-t2)",
  tileClass: "",
};

// Ordered gpio-first (the bucket most pins carry) through the quietest (nc): the order the legend
// teaches them in. Each token is a --stm-<key> variable defined in styles/index.css (both themes).
const CATEGORY_SPECS: ReadonlyArray<{ key: PinCategory; label: string }> = [
  { key: "gpio", label: "GPIO" },
  { key: "analog", label: "Analog" },
  { key: "debug", label: "Debug" },
  { key: "oscillator", label: "Oscillator" },
  { key: "power", label: "Power" },
  { key: "ground", label: "Ground" },
  { key: "reset", label: "Reset" },
  { key: "boot", label: "Boot" },
  { key: "vcap", label: "Vcap" },
  { key: "nc", label: "Not Connected" },
];

export const PIN_CATEGORY_HUES: readonly StmHue[] = CATEGORY_SPECS.map((s) =>
  makeHue(s.key, s.label, `--stm-${s.key}`),
);

const CATEGORY_BY_KEY: Record<string, StmHue> = Object.fromEntries(
  PIN_CATEGORY_HUES.map((h) => [h.key, h]),
);
// The raw io electrical class the API emits pre-split reads as GPIO, but keeps its own live --stm-io
// token (the same hue as gpio) so the electrical_class vocabulary stays fully addressable.
CATEGORY_BY_KEY.io = makeHue("io", "GPIO", "--stm-io");

/**
 * The color-is-data hue for a pin `category`. Total: an unknown or empty category is the neutral hue
 * (never silently painted as another category).
 */
export function pinElectricalHue(category: string): StmHue {
  return CATEGORY_BY_KEY[category] ?? NEUTRAL;
}

const CLASSIFICATION_SPECS: ReadonlyArray<{ key: UnionClassification; label: string }> = [
  { key: "shared", label: "Shared" },
  { key: "divergent", label: "Divergent" },
  { key: "partial", label: "Partial" },
];

export const UNION_CLASSIFICATION_HUES: readonly StmHue[] = CLASSIFICATION_SPECS.map((s) =>
  makeHue(s.key, s.label, `--stm-classify-${s.key}`),
);

const CLASSIFICATION_BY_KEY: Record<string, StmHue> = Object.fromEntries(
  UNION_CLASSIFICATION_HUES.map((h) => [h.key, h]),
);

/**
 * The color-is-data hue for a socket-union `classification`. Total: an unknown classification is the
 * neutral hue. A DISTINCT token set from pinElectricalHue (classification encodes a different fact).
 */
export function unionClassificationHue(classification: string): StmHue {
  return CLASSIFICATION_BY_KEY[classification] ?? NEUTRAL;
}
