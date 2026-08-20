/**
 * `lib/devTokens.ts` claims a shipped default for every token so Dev Mode can reset one exactly and
 * report an honest value. That claim used to be enforced by a comment ("MUST stay in sync ... there
 * is no automated parity test"), and it drifted: the registry offered a BLUE `--c-acc: #6183a1` and
 * a `--c-raise: #3f4044` that the stylesheet had not carried in weeks, so pressing reset moved the
 * app to values it had never shipped and the panel's readout was fiction.
 *
 * This reads the stylesheet and holds the registry to it. Read through `node:fs`, because
 * `vite.config.ts` sets `test.css: false` and a CSS import inside a test is an empty string.
 */
// @ts-expect-error Vitest runs this source contract in Node; the browser bundle excludes Node types.
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { DEV_TOKENS, DEV_TOKEN_BY_VAR, DEV_TOKEN_GROUPS } from "./devTokens";

const css: string = readFileSync("src/styles/index.css", "utf8");

const LIGHT_AT = css.indexOf(':root[data-theme="light"]');
const DARK_BLOCK = css.slice(0, LIGHT_AT);
const LIGHT_BLOCK = css.slice(LIGHT_AT);

function declared(block: string, cssVar: string): string | null {
  const match = block.match(new RegExp(`${cssVar}:\\s*([^;]+);`));
  return match ? match[1].trim() : null;
}

describe("the Dev Mode registry matches the shipped stylesheet", () => {
  it("routes the global icon stroke token through the shared renderer class", () => {
    expect(css).toMatch(/\.ico\s*\{[^}]*stroke-width:\s*var\(--icon-stroke,\s*2\)/s);
  });

  it.each(DEV_TOKENS.filter((t) => t.cssVar.startsWith("--")))(
    "$cssVar",
    (token) => {
      // `--icon-stroke` is the one knob with no stylesheet declaration: it is consumed as
      // `var(--icon-stroke, 2)` inside the shared `.ico` rule, so its shipped value is the
      // fallback rather than a :root declaration.
      if (token.cssVar === "--icon-stroke") return;
      expect(declared(DARK_BLOCK, token.cssVar), `${token.cssVar} dark`).toBe(token.default.dark);
      if (token.themed) {
        expect(token.default.light, `${token.cssVar} declares no light default`).toBeDefined();
        expect(declared(LIGHT_BLOCK, token.cssVar), `${token.cssVar} light`).toBe(
          token.default.light,
        );
      }
    },
  );

  it("offers a knob for every chrome token the stylesheet declares", () => {
    // A token nobody can try a value on gets adjusted by editing the stylesheet and reloading,
    // which is how the previous registry ended up describing an app that no longer existed.
    const chrome = [...DARK_BLOCK.matchAll(/^\s*(--(?:c|r|fs|lh|shadow|edge)-[\w-]+):/gm)].map(
      (m) => m[1],
    );
    const aliases = new Set([
      // Semantic pointers at a tier that already has a row; nudging the alias would silently
      // detach the vocabulary from the ladder.
      "--c-text-primary",
      "--c-text-secondary",
      "--c-text-label",
      "--c-text-muted",
      "--c-text-disabled",
      "--c-text-helper",
      // Numeric aliases onto the seven role sizes, kept while older surfaces carry them.
      "--fs-2xs",
      "--fs-xs",
      "--fs-sm",
      "--fs-base",
      "--fs-lg",
      "--fs-xl",
      "--fs-title",
      // Icon line art: a five-token family with one visual job, adjusted together or not at all.
      "--c-icon-line",
      "--c-icon-fill",
      "--c-icon-cube",
      "--c-icon-edge",
      "--c-icon-faint",
    ]);
    const missing = chrome.filter((v) => !aliases.has(v) && !DEV_TOKEN_BY_VAR.has(v));
    expect(missing).toEqual([]);
  });

  it("puts every token in a declared group, and every group to work", () => {
    const groups = new Set(DEV_TOKENS.map((t) => t.group));
    for (const group of groups) expect(DEV_TOKEN_GROUPS).toContain(group);
    for (const group of DEV_TOKEN_GROUPS) expect(groups.has(group), group).toBe(true);
  });

  it("keeps every cssVar unique, so one knob edits one thing", () => {
    expect(DEV_TOKEN_BY_VAR.size).toBe(DEV_TOKENS.length);
  });

  it("names no blue default anywhere in the registry", () => {
    // THE RULE: nothing in this registry is a blue. It is stated in two halves because the shipped
    // palette is a COOL neutral by the owner's choice - the frame is #1F2022 and the label tier
    // #A9AFB7 - and a bounded cool cast on a grey is not a blue. So a NEAR-NEUTRAL may lean cool by
    // up to 16 points out of 255, and anything genuinely saturated (the status hues, the amber
    // selection and accent) must be WARM. A saturated blue satisfies neither half.
    //
    // The former single test was `b - r <= 2` on every non-status token, i.e. a test for a literal
    // grey. It was the right guard for the grey palette it was written against and would now reject
    // the palette the owner supplied, so it is restated rather than relaxed: measured on the shipped
    // values, the worst neutral cast is 14 and the least warm saturated token clears r - b by 100.
    function channels(value: string): [number, number, number] | null {
      const hex = value.match(/^#([0-9a-f]{6})$/i);
      if (!hex) return null;
      const packed = Number.parseInt(hex[1], 16);
      return [(packed >> 16) & 255, (packed >> 8) & 255, packed & 255];
    }
    // COLOUR IS THE DATUM here, so no hue rule applies: the two remaining status hues (one of which
    // is a green, and a green is not warm), their per-surface text variants, and the seven
    // land-pattern layers. A grayscale encoding of any of them would carry no information at all.
    //
    // `--c-warn` / `--c-warn-text` are NOT on this list any more. The warning tier is a neutral now
    // - a warning is the exact word plus a triangle, not a colour - so it is held to the same
    // no-blue bound as the rest of the chrome rather than exempted as a hue.
    const DATA_HUES = new Set([
      "--c-ok",
      "--c-err",
      "--c-ok-text",
      "--c-err-text",
      "--c-layer-copper",
      "--c-layer-mask",
      "--c-layer-paste",
      "--c-layer-silk",
      "--c-layer-fab",
      "--c-layer-courtyard",
      "--c-layer-pin-one",
    ]);
    for (const token of DEV_TOKENS.filter((t) => !DATA_HUES.has(t.cssVar))) {
      for (const value of [token.default.dark, token.default.light]) {
        const rgb = value ? channels(value) : null;
        if (!rgb) continue;
        const [r, , b] = rgb;
        const max = Math.max(...rgb) / 255;
        const min = Math.min(...rgb) / 255;
        const l = (max + min) / 2;
        const s = max === min ? 0 : l > 0.5 ? (max - min) / (2 - max - min) : (max - min) / (max + min);
        if (s <= 0.15) {
          expect(b - r, `${token.cssVar} = ${value} leans blue`).toBeLessThanOrEqual(16);
        } else {
          // Saturated and not a data hue: with the amber accent and selection fill gone, what is
          // left in this branch is the warm off-white of the drawing sheet's body wash. It is WARM,
          // and a blue is the one thing that cannot be. Stated as `r > b` rather than as a margin because
          // saturation is a ratio: a near-white like #f0efe8 reads as 0.21 saturated off an
          // absolute cast of 8 points, and demanding a wide margin there would reject a paper tint.
          expect(r - b, `${token.cssVar} = ${value} is a saturated cool hue`).toBeGreaterThan(0);
        }
      }
    }
  });
});
