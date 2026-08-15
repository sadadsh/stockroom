/**
 * PARITY WITH THE SHIPPED GATE: the validator and `styles/visualLanguage.test.ts` measure the same
 * thing, to the same numbers, against the same floors, over a table that covers what the workspace
 * paints.
 *
 * Plan 1.4 says to reuse the measured-contrast machinery from that suite. `validateContrast.ts`
 * cannot literally import it - that suite reads `src/styles/index.css` through `node:fs` because
 * `vite.config.ts` sets `test.css: false`, and a validator that runs in a browser during an edit
 * cannot read a file. So the measurement is a second implementation, and this file is the reason
 * that is safe: it runs BOTH implementations over the pairs that suite measures and requires
 * identical ratios, reads the FLOORS out of that suite's own source, and re-derives the pairing
 * table's coverage from the modules the piece manifests name.
 *
 * Four claims, each of which fails loudly if the two ever drift:
 *
 *   1. Identical ratios for every pair `visualLanguage.test.ts` measures.
 *   2. The floors are that suite's floors, extracted from its source rather than restated.
 *   3. Every chrome pairing that suite holds is in this validator's table, at the same bar.
 *   4. Every surface and every ink a workspace piece's own module paints has a row in the table.
 *
 * Read through `node:fs` exactly as the suite it mirrors does, for exactly that suite's reason.
 */
// @ts-expect-error Vitest runs this source contract in Node; the browser bundle excludes Node types.
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { DEFAULT_WORKSPACE_LAYOUT } from "./defaultWorkspaceLayout";
import {
  contrastRatio,
  CONTRAST_FLOOR,
  devTokenValues,
  validateContrast,
  WORKSPACE_CONTRAST_PAIRINGS,
  WORKSPACE_MARK_INKS,
  WORKSPACE_SUPPLEMENTAL_INKS,
  WORKSPACE_TEXT_SURFACES,
  WORKSPACE_WORD_INKS,
  type ContrastBar,
} from "./validateContrast";
import { WORKSPACE_PIECES } from "./workspacePieces";

const css: string = readFileSync("src/styles/index.css", "utf8");
const tailwind: string = readFileSync("tailwind.config.js", "utf8");
const suite: string = readFileSync("src/styles/visualLanguage.test.ts", "utf8");

/* -------------------------------------------------------------------------- */
/*  the reference implementation, copied from visualLanguage.test.ts           */
/* -------------------------------------------------------------------------- */

function themeBlock(selector: string): string {
  const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const match = css.match(new RegExp(`${escaped}\\s*\\{([\\s\\S]*?)\\n\\s*\\}`));
  if (!match) throw new Error(`Missing theme block: ${selector}`);
  return match[1];
}

function property(block: string, name: string): string {
  const match = block.match(
    new RegExp(`${name.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}\\s*:\\s*([^;]+);`),
  );
  if (!match) throw new Error(`Missing CSS property: ${name}`);
  return match[1].trim();
}

function rgb(value: string): [number, number, number] {
  const match = value.match(/^#([0-9a-f]{6})$/i);
  if (!match) throw new Error(`Expected an opaque six-digit color, received ${value}`);
  const packed = Number.parseInt(match[1], 16);
  return [(packed >> 16) & 255, (packed >> 8) & 255, packed & 255];
}

function luminance(color: [number, number, number]): number {
  const channels = color.map((channel) => {
    const normalized = channel / 255;
    return normalized <= 0.04045
      ? normalized / 12.92
      : ((normalized + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2];
}

/** The reference, character for character as the shipped gate computes it. */
function contrast(left: string, right: string): number {
  const a = luminance(rgb(left));
  const b = luminance(rgb(right));
  return (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);
}

const THEMES = [
  ["dark", ":root"],
  ["light", ':root[data-theme="light"]'],
] as const;

/* -------------------------------------------------------------------------- */
/*  the pairs the shipped gate measures                                        */
/* -------------------------------------------------------------------------- */

interface Pair {
  ink: string;
  surface: string;
  bar: ContrastBar;
  /** The `it` in `visualLanguage.test.ts` this pair comes from. */
  from: string;
}

function cross(
  inks: readonly string[],
  surfaces: readonly string[],
  bar: ContrastBar,
  from: string,
): Pair[] {
  return inks.flatMap((ink) => surfaces.map((surface) => ({ ink, surface, bar, from })));
}

/** Every chrome pairing `visualLanguage.test.ts` asserts, transcribed with its source assertion. */
const REFERENCE_CHROME_PAIRS: readonly Pair[] = [
  ...cross(["--c-warn", "--c-warn-text"], ["--c-canvas", "--c-band", "--c-popover"], "text", "states a warning without a hue at all"),
  ...cross(["--c-ok-text", "--c-err-text"], ["--c-canvas", "--c-band", "--c-popover", "--c-surface"], "text", "spends a status WORD at the text bar"),
  ...cross(["--c-ok", "--c-err"], ["--c-canvas", "--c-band"], "non-text", "spends a status WORD at the text bar (the mark half)"),
  ...cross(["--c-t1", "--c-t2", "--c-t3"], ["--c-selected", "--c-selected-hover"], "text", "carries every text tier on a selected row"),
  ...cross(["--c-t4"], ["--c-selected", "--c-selected-hover"], "non-text", "carries every text tier on a selected row"),
  ...cross(["--c-t3"], ["--c-canvas", "--c-band", "--c-popover"], "text", "label text passes AA on every surface small text lands on"),
  ...cross(["--c-t1", "--c-t2"], ["--c-canvas", "--c-band", "--c-popover", "--c-surface"], "text", "primary and secondary clear AA with room to spare"),
  ...cross(["--c-t4"], ["--c-canvas"], "non-text", "muted text still clears the large-text floor"),
];

/** The drawing sheet's own pairs. Measured for parity; deliberately NOT in the validator's table. */
const REFERENCE_DRAWING_PAIRS: readonly Pair[] = [
  ...cross(
    [
      "--c-technical-ink",
      "--c-technical-note",
      "--c-layer-copper",
      "--c-layer-mask",
      "--c-layer-paste",
      "--c-layer-silk",
      "--c-layer-fab",
      "--c-layer-courtyard",
    ],
    ["--c-technical"],
    "non-text",
    "draws every ink at 3:1 or better on its own sheet",
  ),
  ...cross(["--c-technical-ink"], ["--c-technical-wash"], "text", "ink on the body wash"),
];

/* -------------------------------------------------------------------------- */

describe("the measurement agrees with the shipped gate", () => {
  it.each(THEMES)("%s produces identical ratios for every pair that suite measures", (_theme, selector) => {
    // Killing mutation: change one constant in `relativeLuminance` - the 0.04045 knee, the 1.055
    // divisor, the 0.7152 green weight - or reorder the ratio's `max`/`min`. Any of them moves a
    // ratio in the fourth decimal and this fails, while every floor comparison still passes.
    const block = themeBlock(selector);
    const pairs = [...REFERENCE_CHROME_PAIRS, ...REFERENCE_DRAWING_PAIRS];
    expect(pairs.length).toBeGreaterThan(40);
    for (const pair of pairs) {
      const ink = property(block, pair.ink);
      const surface = property(block, pair.surface);
      expect(contrastRatio(ink, surface), `${pair.ink} on ${pair.surface} (${pair.from})`).toBe(
        contrast(ink, surface),
      );
    }
  });

  it.each(THEMES)("%s produces identical ratios for every pairing in the validator's own table", (_theme, selector) => {
    const block = themeBlock(selector);
    for (const pairing of WORKSPACE_CONTRAST_PAIRINGS) {
      const ink = property(block, pairing.ink);
      const surface = property(block, pairing.surface);
      expect(contrastRatio(ink, surface), `${pairing.ink} on ${pairing.surface}`).toBe(
        contrast(ink, surface),
      );
    }
  });

  it("takes its floors from that suite's own assertions", () => {
    // Every number asserted immediately after a `contrast(...)` call in `visualLanguage.test.ts`.
    // Killing mutation: slacken `CONTRAST_FLOOR.text` to 4 or 3. The extracted set would no longer
    // contain it, and a validator holding a looser bar than the gate it claims to mirror is the
    // exact way this work could quietly weaken the design's contract.
    const floors = new Set(
      [...suite.matchAll(/contrast\([\s\S]{0,400}?toBeGreaterThanOrEqual\(\s*([\d.]+)\s*,?\s*\)/g)].map(
        (match) => Number(match[1]),
      ),
    );
    expect([...floors].sort((a, b) => a - b)).toEqual([3, 4.5]);
    expect(floors.has(CONTRAST_FLOOR.text)).toBe(true);
    expect(floors.has(CONTRAST_FLOOR["non-text"])).toBe(true);
  });

  it("holds every chrome pairing that suite holds, at the same bar", () => {
    // Killing mutation: drop `--c-popover` or `--c-selected-hover` from `WORKSPACE_TEXT_SURFACES`.
    // The validator would then pass a design the shipped gate fails.
    const table = new Set(
      WORKSPACE_CONTRAST_PAIRINGS.map((pairing) => `${pairing.ink}|${pairing.surface}|${pairing.bar}`),
    );
    const missing = REFERENCE_CHROME_PAIRS.filter(
      (pair) => !table.has(`${pair.ink}|${pair.surface}|${pair.bar}`),
    ).map((pair) => `${pair.ink} on ${pair.surface} @${pair.bar} (${pair.from})`);
    expect(missing).toEqual([]);
  });
});

describe("the palette the validator measures is the shipped stylesheet", () => {
  it.each(THEMES)("%s token defaults match the stylesheet for every token in the table", (theme, selector) => {
    // `devTokens.parity.test.ts` already pins the registry to the stylesheet; this pins the SUBSET
    // this validator reads, so a token dropped from the registry shows up here as well as there.
    // Killing mutation: build `devTokenValues` from the dark default in both themes.
    const block = themeBlock(selector);
    const values = devTokenValues(theme as "dark" | "light");
    const tokens = new Set(
      WORKSPACE_CONTRAST_PAIRINGS.flatMap((pairing) => [pairing.ink, pairing.surface]),
    );
    expect(tokens.size).toBeGreaterThan(15);
    for (const token of tokens) {
      expect(values[token], `${theme} ${token}`).toBe(property(block, token));
    }
  });

  it("warns about nothing when the stylesheet itself drives the measurement", () => {
    // The anchor again, taken the long way round: values read straight out of `index.css` rather
    // than out of `lib/devTokens`. The shipped design passes its own gate however the palette is
    // resolved.
    const themes = THEMES.map(([theme, selector]) => {
      const block = themeBlock(selector);
      const values: Record<string, string> = {};
      for (const pairing of WORKSPACE_CONTRAST_PAIRINGS) {
        values[pairing.ink] = property(block, pairing.ink);
        values[pairing.surface] = property(block, pairing.surface);
      }
      return { theme, values };
    });
    expect(validateContrast(DEFAULT_WORKSPACE_LAYOUT, themes)).toEqual([]);
  });
});

/* -------------------------------------------------------------------------- */
/*  coverage: the table against what the workspace actually paints             */
/* -------------------------------------------------------------------------- */

/** Tailwind's colour names, resolved to the variables they stand for. */
const COLOR_VAR = new Map<string, string>(
  [...tailwind.matchAll(/^\s*"?([a-z0-9-]+)"?:\s*"var\((--[a-z0-9-]+)\)"/gm)].map((match) => [
    match[1],
    match[2],
  ]),
);

/**
 * Surfaces a workspace module paints that this table deliberately does not measure.
 *
 * Each entry is an argument, not a suppression - see the header of `validateContrast.ts`.
 */
const NOT_A_TEXT_SURFACE = new Map<string, string>([
  ["--c-line", "a 1px rule; nothing is drawn on top of it"],
  ["--c-line2", "a 1px rule; nothing is drawn on top of it"],
  [
    "--c-technical",
    "the drawing sheet: visualLanguage.test.ts measures the drawing INKS on it, not the text tiers",
  ],
  ["--c-technical-wash", "the symbol body wash, measured against the drawing ink by the same suite"],
]);

/** Inks a workspace module uses that the design deliberately holds to no floor. */
const NOT_HELD_TO_A_FLOOR = new Map<string, string>([
  [
    "--c-t5",
    "the disabled tier: 2.0-3.5 against every surface on purpose, and the shipped gate measures the ladder's first four rungs for that reason",
  ],
]);

/** The modules the manifests name, read from the manifests so a new piece is scanned on arrival. */
const PIECE_SOURCES = [...new Set(WORKSPACE_PIECES.map((piece) => piece.source))]
  .filter((source) => source.endsWith(".tsx"))
  .map((source) => `src/${source}`);

function classesIn(pattern: RegExp): Map<string, string[]> {
  const found = new Map<string, string[]>();
  for (const path of PIECE_SOURCES) {
    const source: string = readFileSync(path, "utf8");
    for (const match of source.matchAll(pattern)) {
      // An alpha-modified class (`bg-band/60`) is a wash over whatever is behind it, and a wash has
      // no contrast ratio of its own - see the header of `validateContrast.ts`.
      if (match[2]) continue;
      const cssVar = COLOR_VAR.get(match[1]);
      if (!cssVar) continue;
      const where = found.get(cssVar);
      if (where) where.push(path);
      else found.set(cssVar, [path]);
    }
  }
  return found;
}

describe("the table covers what the workspace paints", () => {
  it("reads a real set of piece modules", () => {
    // A glob that matched nothing would turn both assertions below into false passes.
    expect(PIECE_SOURCES.length).toBeGreaterThanOrEqual(8);
    expect(COLOR_VAR.get("band")).toBe("--c-band");
    expect(COLOR_VAR.get("control-hover")).toBe("--c-control-hover");
  });

  it("has a row for every surface a piece module paints", () => {
    // Killing mutation: delete `--c-band` or `--c-row-alt` from `WORKSPACE_TEXT_SURFACES`. The
    // workspace paints both, and a table that lost one would stop measuring the text on it.
    const painted = classesIn(/\bbg-([a-z0-9-]+)(\/[\w./[\]]+)?/g);
    expect(painted.size).toBeGreaterThan(4);
    const uncovered = [...painted]
      .filter(([cssVar]) => !WORKSPACE_TEXT_SURFACES.includes(cssVar))
      .filter(([cssVar]) => !NOT_A_TEXT_SURFACE.has(cssVar))
      .map(([cssVar, where]) => `${cssVar} (${where[0]})`);
    expect(uncovered).toEqual([]);
  });

  it("has a row for every ink a piece module writes in", () => {
    // Killing mutation: delete `--c-t3` or `--c-warn` from the ink lists. The label tier is the
    // second most used class in the workspace and the warning tier is a WORD.
    const inks = new Set([...WORKSPACE_WORD_INKS, ...WORKSPACE_SUPPLEMENTAL_INKS, ...WORKSPACE_MARK_INKS]);
    const written = classesIn(/\btext-([a-z0-9-]+)(\/[\w./[\]]+)?/g);
    expect(written.size).toBeGreaterThan(4);
    const uncovered = [...written]
      .filter(([cssVar]) => !inks.has(cssVar))
      .filter(([cssVar]) => !NOT_HELD_TO_A_FLOOR.has(cssVar))
      .map(([cssVar, where]) => `${cssVar} (${where[0]})`);
    expect(uncovered).toEqual([]);
  });

  it("states a reason for every exclusion", () => {
    // An exemption with no argued ground is indistinguishable from a pairing somebody found
    // inconvenient - the same rule `copy.letterRule.test.ts` puts on its industry allowlist.
    for (const [, why] of [...NOT_A_TEXT_SURFACE, ...NOT_HELD_TO_A_FLOOR]) {
      expect(why.length).toBeGreaterThan(40);
    }
  });
});
