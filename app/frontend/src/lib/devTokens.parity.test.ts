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
  it.each(DEV_TOKENS.filter((t) => t.cssVar.startsWith("--")))(
    "$cssVar",
    (token) => {
      // `--icon-stroke` is the one knob with no stylesheet declaration: it is consumed as
      // `var(--icon-stroke, 1.9)` inside the shared `.ico` rule, so its shipped value is the
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
      // Status TEXT variants of --c-ok / --c-warn / --c-err, tuned per surface.
      "--c-ok-text",
      "--c-warn-text",
      "--c-err-text",
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
    // The three status hues are exempt: green, amber and red encode a STATE, and are the only
    // hues chrome is allowed. Everything else in the registry is a grey, focus ring included.
    const STATUS = new Set(["--c-ok", "--c-warn", "--c-err"]);
    for (const token of DEV_TOKENS.filter((t) => !STATUS.has(t.cssVar))) {
      for (const value of [token.default.dark, token.default.light]) {
        const hex = value?.match(/^#([0-9a-f]{6})$/i);
        if (!hex) continue;
        const packed = Number.parseInt(hex[1], 16);
        const r = (packed >> 16) & 255;
        const b = packed & 255;
        expect(b - r, `${token.cssVar} = ${value} leans blue`).toBeLessThanOrEqual(2);
      }
    }
  });
});
