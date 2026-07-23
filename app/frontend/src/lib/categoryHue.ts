/**
 * Map a part's category to a subtle, theme-adaptive hue so the list-row fallback thumbnails read
 * apart at a glance (a resistor from a cap from an IC) instead of as identical gray tiles (FIX-03).
 *
 * The hue is a per-theme design token (`--cat-*` in styles/index.css), tuned to clear >=3:1
 * contrast against the recessed tile in BOTH light and dark. The helper never emits a raw hex
 * literal, so theming stays in the token layer. Matching mirrors CategoryGlyph: case-insensitive,
 * substring-based, specific families first, an unknown/empty category falling back to a neutral
 * (non-color-dependent) descriptor. Pure + total.
 */

export interface CategoryHue {
  /** the matched family (or "neutral") */
  family: string;
  /** the design token the hue is built from (a --cat-* var, or --c-t2 for neutral) */
  token: string;
  /** the stroke color for the glyph, as a token reference */
  stroke: string;
  /** tile background + border classes (a faint category tint); "" keeps the default neutral tile */
  tileClass: string;
}

// Specific families first; the IC family (a broad set of active/IC category names) is matched
// last, before the neutral fallback, so a passive/connector/crystal never gets the IC hue.
const FAMILIES: ReadonlyArray<{ family: string; match: readonly string[] }> = [
  { family: "resistor", match: ["resistor"] },
  { family: "capacitor", match: ["capacitor"] },
  { family: "inductor", match: ["inductor", "ferrite"] },
  { family: "diode", match: ["diode", "led"] },
  { family: "connector", match: ["connector", "header"] },
  { family: "crystal", match: ["crystal", "oscillator"] },
  {
    family: "ic",
    match: [
      "ic",
      "integrated",
      "circuit",
      "microcontroller",
      "processor",
      "logic",
      "amplifier",
      "regulator",
      "sensor",
      "transistor",
      "mosfet",
      "driver",
      "converter",
      "interface",
      "memory",
      "module",
    ],
  },
];

function hue(family: string): CategoryHue {
  const token = `--cat-${family}`;
  return {
    family,
    token,
    stroke: `var(${token})`,
    // a faint wash of the same hue + a slightly stronger hairline, both mixed against transparent
    // so they adapt per theme (no per-theme literal, no scattered rgba)
    tileClass:
      `bg-[color-mix(in_srgb,var(${token})_12%,transparent)] ` +
      `border-[color-mix(in_srgb,var(${token})_34%,transparent)]`,
  };
}

const NEUTRAL: CategoryHue = {
  family: "neutral",
  token: "--c-t2",
  stroke: "var(--c-t2)",
  tileClass: "", // keep the default bg-field / border-line tile
};

/** The category hue for a part `category`. Total: an unknown/empty category is the neutral hue. */
export function categoryHue(category: string): CategoryHue {
  const c = (category || "").toLowerCase();
  if (!c) return NEUTRAL;
  for (const { family, match } of FAMILIES) {
    if (match.some((m) => c.includes(m))) return hue(family);
  }
  return NEUTRAL;
}
