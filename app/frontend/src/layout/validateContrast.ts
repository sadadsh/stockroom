/**
 * VISIBILITY: is every text role still readable on the surface a redesign has put it on.
 *
 * Plan 1.4 says to reuse the measured-contrast machinery from `styles/visualLanguage.test.ts`, and
 * this module is that machinery moved to where a running editor can call it. The maths is WCAG 2.x
 * relative luminance over resolved token values and it is character-for-character the same
 * computation that suite performs - `validateContrast.parity.test.ts` proves that by running both
 * implementations over the pairs that suite measures and asserting identical ratios, so the two can
 * never drift into disagreeing about whether the shipped design passes.
 *
 * WHY IT IS A COPY AND NOT AN IMPORT. `visualLanguage.test.ts` reads `src/styles/index.css` through
 * `node:fs`, because `vite.config.ts` sets `test.css: false` and a stylesheet imported inside a test
 * resolves to an empty string. A validator that runs inside the browser during an edit cannot read a
 * file, and a validator that runs inside the commit pipeline has no DOM to read a computed style
 * from. So the INPUT differs - a resolved `{ cssVar -> value }` map, handed in by the caller - while
 * the MEASUREMENT is identical, and the parity test is what keeps "identical" true.
 *
 * WHERE THE VALUES COME FROM, which is the whole point of taking them as a parameter:
 *
 *   TODAY, the shipped defaults: `devTokenValues("dark" | "light")`, built from `lib/devTokens`,
 *   whose defaults `devTokens.parity.test.ts` already pins to the stylesheet.
 *
 *   IN EDIT MODE, a DRAFT: the style panel (plan 1.5) is a set of sliders and swatches over exactly
 *   those variables, and it feeds its uncommitted values in here so the issues list updates while
 *   the owner drags. Nothing in this module knows or cares which of the two it was handed, which is
 *   why the panel needs no second copy of the contrast rules.
 *
 * WHAT IS MEASURED, and how the list was arrived at. A pairing is an INK on a SURFACE at a FLOOR,
 * and the set below is a union of two sources, neither of them invented here:
 *
 *   Every pairing the shipped gate measures. `visualLanguage.test.ts` holds the primary, secondary
 *   and label tiers at 4.5 on the workspace, the chrome band, the menu and the panel; the muted tier
 *   at 3; all four on the selection fill and its hover; both status WORD strengths at 4.5; and the
 *   two mark strengths at 3 on the workspace and the band. That is the design's own contract and it
 *   is transcribed, not re-decided.
 *
 *   Every surface a workspace piece paints. Read off the modules the manifests name as their
 *   `source`, which is why the control fills and the alternating grid row are here: a button label
 *   and a table row are text on a surface exactly as a heading is.
 *   `validateContrast.coverage.test.ts` re-derives that set from those files and fails if a surface
 *   a piece paints has no row here, so the table cannot silently fall behind the workspace.
 *
 * FOUR DELIBERATE EXCLUSIONS, each of which would otherwise look like an oversight:
 *
 *   `--c-t5`, the disabled tier, is not measured. It resolves to 2.0-3.5 against every surface in
 *   both themes, on purpose: it is the tier that says a control is out of reach, and the shipped
 *   gate measures the ladder's first four rungs for exactly this reason. Holding it to a floor would
 *   report the design's own intent as a defect on every render.
 *
 *   A 1px rule (`--c-line`, `--c-line2`) is not a surface. Nothing is drawn on top of it.
 *
 *   The technical drawing sheet is not a text surface. `--c-technical` carries the drawing INKS, and
 *   `visualLanguage.test.ts`'s own drawing-canvas suite measures those against it at 3:1 and holds
 *   the six layer colours 15 dE apart. Measuring the interface text tiers against a drawing sheet
 *   would be asking the wrong question about the right surface.
 *
 *   A TRANSLUCENT value cannot be measured. `bg-acc/10` and `--c-hover` are washes over whatever
 *   happens to be behind them, and a contrast ratio for "10% of the accent over an unknown backing"
 *   does not exist. Such a value is reported as `contrast-not-measured` (info) rather than guessed.
 *
 *   `--c-active` is measured by NOBODY, and that is a finding rather than an omission: at the label
 *   tier it comes to 4.43 in light theme, under the 4.5 a word answers to. The workspace does not
 *   paint it, so it is not in the table - and `validateContrast.test.ts` uses it as the non-vacuity
 *   proof, because adding it produces a real warning from real shipped values.
 */
import type { LayoutDocument } from "./document";
import { layoutPlacements } from "./document";
import { DEV_TOKENS } from "../lib/devTokens";
import { tokenPairSubject, validatorIssue, type ValidatorIssue } from "./validatorIssues";

/* -------------------------------------------------------------------------- */
/*  the measurement                                                            */
/* -------------------------------------------------------------------------- */

/** A resolved palette: every CSS variable this validator might read, as its literal value. */
export type TokenValues = Readonly<Record<string, string>>;

/** One theme's palette. Two of these is the usual call; a draft may carry only the active one. */
export interface ThemeTokens {
  /** `dark` / `light`. Carried through to the issue so a row says which theme it is about. */
  theme: string;
  values: TokenValues;
}

/** Which bar a pairing answers to. The names are the shipped gate's own. */
export type ContrastBar = "text" | "non-text";

/**
 * The two floors, WCAG AA.
 *
 * Read off `visualLanguage.test.ts` rather than off the specification, and
 * `validateContrast.parity.test.ts` extracts every floor that suite asserts beside a `contrast(...)`
 * call and requires the set to be exactly these two. A change there is a change here, loudly.
 */
export const CONTRAST_FLOOR: Readonly<Record<ContrastBar, number>> = {
  text: 4.5,
  "non-text": 3,
};

/** An opaque colour as three 0..255 channels, or `null` when the value is not one. */
export function parseColor(value: string): readonly [number, number, number] | null {
  const text = value.trim();
  const long = /^#([0-9a-f]{6})$/i.exec(text);
  if (long) {
    const packed = Number.parseInt(long[1], 16);
    return [(packed >> 16) & 255, (packed >> 8) & 255, packed & 255];
  }
  // The three-digit form is the same opaque colour written shorter, and expanding it gives the
  // identical triple - so accepting it cannot make this disagree with the shipped gate on any value
  // that gate can read. Anything else (a translucent rgba, a `var()` reference, a named colour) is
  // NOT read: see the header on why a wash has no contrast ratio.
  const short = /^#([0-9a-f]{3})$/i.exec(text);
  if (short) {
    const [r, g, b] = [...short[1]].map((digit) => Number.parseInt(digit + digit, 16));
    return [r, g, b];
  }
  return null;
}

/** WCAG relative luminance. Identical to `visualLanguage.test.ts`'s `luminance`. */
export function relativeLuminance(color: readonly [number, number, number]): number {
  const channels = color.map((channel) => {
    const normalized = channel / 255;
    return normalized <= 0.04045
      ? normalized / 12.92
      : ((normalized + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2];
}

/**
 * The WCAG contrast ratio between two colour values, or `null` when either is not an opaque colour.
 *
 * `null` rather than a throw: `visualLanguage.test.ts` throws because a stylesheet that lost a token
 * is a build defect and the suite should stop. Here the input is a live draft palette mid-drag, and
 * a validator that threw would take the editor down over a half-typed value.
 */
export function contrastRatio(left: string, right: string): number | null {
  const a = parseColor(left);
  const b = parseColor(right);
  if (!a || !b) return null;
  const x = relativeLuminance(a);
  const y = relativeLuminance(b);
  return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05);
}

/* -------------------------------------------------------------------------- */
/*  the pairings                                                               */
/* -------------------------------------------------------------------------- */

/**
 * One thing drawn on another, and the bar it answers to.
 *
 * `pieces` scopes a pairing to the pieces that produce it: a pairing naming pieces is measured only
 * while at least one of them is placed and not hidden, so removing the offers section stops
 * measuring the pairings only the offers table has. The shipped table below scopes nothing, because
 * every surface in it is chrome that any piece can land text on; the mechanism exists because the
 * composer (plan Phase 5) produces pieces that bring their own pairings, and because a style panel
 * that scoped a role override to one placement needs exactly this.
 */
export interface ContrastPairing {
  /** The CSS variable the text or the mark is drawn IN. */
  ink: string;
  /** The CSS variable it is drawn ON. */
  surface: string;
  bar: ContrastBar;
  pieces?: readonly string[];
}

/**
 * Every surface the workspace lands text on.
 *
 * The first six are what the modules the manifests name as `source` actually paint; the rest are
 * what the shipped gate measures, plus the other end of a control's two-stop fill, because a button
 * label sits across the gradient rather than on one stop of it.
 */
export const WORKSPACE_TEXT_SURFACES: readonly string[] = [
  "--c-band",
  "--c-field",
  "--c-row-alt",
  "--c-surface",
  "--c-control-hover",
  "--c-control-pressed",
  "--c-canvas",
  "--c-popover",
  "--c-raise",
  "--c-raise2",
  "--c-selected",
  "--c-selected-hover",
  "--c-control-top",
  "--c-control-bottom",
];

/** The tiers a WORD is drawn in. Held at 4.5, because the reader is reading them. */
export const WORKSPACE_WORD_INKS: readonly string[] = [
  "--c-t1",
  "--c-t2",
  "--c-t3",
  "--c-ok-text",
  "--c-err-text",
  "--c-warn-text",
  // The warning tier is a WORD strength already: it is desaturated by contract and the shipped gate
  // measures it at 4.5, so it belongs with the words rather than with the marks.
  "--c-warn",
];

/**
 * The supplementary tier, held at the large-text floor exactly as the shipped gate holds it.
 *
 * Timestamps and file metadata. Deliberately quieter than the label tier and deliberately still
 * readable, which is a 3 rather than a 4.5 and is not a slackening of the rule but the rule the
 * design was built to.
 */
export const WORKSPACE_SUPPLEMENTAL_INKS: readonly string[] = ["--c-t4"];

/** A fill, a border or a glyph. Green and red keep their plain strengths for this and only this. */
export const WORKSPACE_MARK_INKS: readonly string[] = ["--c-ok", "--c-err"];

/**
 * The surfaces a mark is measured on: the two the shipped gate names.
 *
 * Deliberately narrower than the text surfaces. The plain strengths are 2.5-3.0 against the raised
 * fills, which is why the design puts a WORD in `--c-ok-text` / `--c-err-text` and reserves the
 * plain token for a dot or a stripe on the workspace or the band. Widening this list would be
 * asserting that a red dot on a menu is a thing this design does, which it is not.
 */
export const WORKSPACE_MARK_SURFACES: readonly string[] = ["--c-canvas", "--c-band"];

function pair(inks: readonly string[], surfaces: readonly string[], bar: ContrastBar) {
  return inks.flatMap((ink) => surfaces.map((surface) => ({ ink, surface, bar })));
}

/** The shipped table: the design's own contract, as data a validator can re-measure. */
export const WORKSPACE_CONTRAST_PAIRINGS: readonly ContrastPairing[] = [
  ...pair(WORKSPACE_WORD_INKS, WORKSPACE_TEXT_SURFACES, "text"),
  ...pair(WORKSPACE_SUPPLEMENTAL_INKS, WORKSPACE_TEXT_SURFACES, "non-text"),
  ...pair(WORKSPACE_MARK_INKS, WORKSPACE_MARK_SURFACES, "non-text"),
];

/* -------------------------------------------------------------------------- */
/*  the shipped palettes                                                       */
/* -------------------------------------------------------------------------- */

export type DevTokenTheme = "dark" | "light";

/**
 * The shipped defaults for one theme, as a resolved map.
 *
 * `lib/devTokens` is the registry the Design panel already reads and `devTokens.parity.test.ts`
 * pins its defaults to `styles/index.css`, so this is the stylesheet by proxy - reachable from a
 * browser and from the commit pipeline, neither of which can open a file. A shared token (a radius,
 * a type size) states only a dark default and means it for both themes, which is why `light` falls
 * back rather than being skipped.
 */
export function devTokenValues(theme: DevTokenTheme): TokenValues {
  const values: Record<string, string> = {};
  for (const token of DEV_TOKENS) {
    values[token.cssVar] = theme === "light" ? token.default.light ?? token.default.dark : token.default.dark;
  }
  return values;
}

/** Both shipped palettes, in the order the panel lists them. */
export function shippedThemeTokens(): ThemeTokens[] {
  return [
    { theme: "dark", values: devTokenValues("dark") },
    { theme: "light", values: devTokenValues("light") },
  ];
}

/**
 * The two override blocks a live token edit is held in, declared STRUCTURALLY.
 *
 * `lib/devModeDraft.ts` owns the real type and this is its shape, restated rather than imported: a
 * validator that ran in the commit pipeline would otherwise pull a module of React hooks in behind
 * it. `TokenOverrides` satisfies this, so the panel passes its slice straight through.
 */
export interface TokenOverrideBlocks {
  /** Dark colours and the shared scalars, which land on `:root`. */
  root: Readonly<Record<string, string>>;
  /** Light colours, which land on `:root[data-theme="light"]`. */
  light: Readonly<Record<string, string>>;
}

/**
 * Both palettes as the screen currently has them: the shipped defaults with the live edits over them.
 *
 * This is the input the header promises - "IN EDIT MODE, a DRAFT" - so the issues list moves while
 * the owner drags a swatch instead of reporting the design as it shipped. BOTH themes are resolved
 * from one draft, because a colour edit is stored per theme and the one being looked at is not the
 * one it can break: a token nudged in dark theme leaves the light palette at its default, and a
 * pairing that fails there is a finding the owner has to see without switching.
 *
 * WHICH BLOCK EACH TOKEN READS is `lib/devModeDraft.ts`'s rule, restated: a themed token takes the
 * light block in light theme, and an unthemed one (a radius, a type size) is shared and always takes
 * `root`. An EMPTY override is treated as no override, which is what `useApplyDraftOverrides` does
 * when it pushes the draft at the document - a cleared field falls back to the stylesheet, so
 * measuring it as an unreadable value would report a row that is not on the screen.
 */
export function draftThemeTokens(overrides: TokenOverrideBlocks): ThemeTokens[] {
  const themes: DevTokenTheme[] = ["dark", "light"];
  return themes.map((theme) => {
    const values: Record<string, string> = {};
    for (const token of DEV_TOKENS) {
      const block = token.themed && theme === "light" ? overrides.light : overrides.root;
      const override = block[token.cssVar];
      values[token.cssVar] =
        override != null && override !== ""
          ? override
          : theme === "light"
            ? token.default.light ?? token.default.dark
            : token.default.dark;
    }
    return { theme, values };
  });
}

/* -------------------------------------------------------------------------- */
/*  the check                                                                  */
/* -------------------------------------------------------------------------- */

export interface ContrastOptions {
  /** Override the table, for a test or for a caller measuring a scoped set. */
  pairings?: readonly ContrastPairing[];
}

/**
 * Every pairing this document puts on screen that does not clear its floor.
 *
 * The DOCUMENT decides which pairings are live: a pairing scoped to pieces is skipped while none of
 * them is placed and visible, and a document that places nothing visible at all is measured against
 * nothing, because a surface with no text on it has no contrast question. The PALETTES decide the
 * answer, and there is one pass per theme, because a redesign that reads on the dark desktop and
 * fails on the light one is two different findings and the owner needs both rows.
 */
export function validateContrast(
  document: LayoutDocument,
  themes: readonly ThemeTokens[],
  options: ContrastOptions = {},
): ValidatorIssue[] {
  const pairings = options.pairings ?? WORKSPACE_CONTRAST_PAIRINGS;

  const visiblePieces = new Set<string>();
  for (const visit of layoutPlacements(document)) {
    if (visit.node.hidden !== true) visiblePieces.add(visit.node.piece);
  }
  if (visiblePieces.size === 0) return [];

  const issues: ValidatorIssue[] = [];
  for (const { theme, values } of themes) {
    for (const pairing of pairings) {
      if (pairing.pieces && !pairing.pieces.some((piece) => visiblePieces.has(piece))) continue;

      const subject = tokenPairSubject(theme, pairing.ink, pairing.surface);
      const inkValue = values[pairing.ink];
      const surfaceValue = values[pairing.surface];

      const absent = inkValue === undefined ? pairing.ink : surfaceValue === undefined ? pairing.surface : null;
      if (absent) {
        issues.push(
          validatorIssue("contrast-not-measured", subject, {
            detail: { reason: "absent", token: absent },
          }),
        );
        continue;
      }

      const ratio = contrastRatio(inkValue, surfaceValue);
      if (ratio === null) {
        const unreadable = parseColor(inkValue) ? pairing.surface : pairing.ink;
        issues.push(
          validatorIssue("contrast-not-measured", subject, {
            detail: {
              reason: "unreadable",
              token: unreadable,
              value: unreadable === pairing.ink ? inkValue : surfaceValue,
            },
          }),
        );
        continue;
      }

      const floor = CONTRAST_FLOOR[pairing.bar];
      if (ratio >= floor) continue;

      issues.push(
        validatorIssue(
          pairing.bar === "text" ? "contrast-below-text-floor" : "contrast-below-non-text-floor",
          subject,
          // Two decimals, which is the precision the shipped gate's own comments quote failures at,
          // and enough that two runs over one palette produce byte-identical rows.
          { detail: { ratio: Math.round(ratio * 100) / 100, floor, bar: pairing.bar } },
        ),
      );
    }
  }
  return issues;
}
