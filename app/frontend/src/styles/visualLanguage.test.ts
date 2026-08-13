/**
 * The contract on the shipped stylesheet: this is a Windows engineering application, so its type
 * is fixed and narrow, its chrome is grayscale, and its text tiers are opaque.
 *
 * Read straight from `src/styles/index.css` through `node:fs` rather than by rendering, because
 * `vite.config.ts` sets `test.css: false` - a stylesheet imported inside a test resolves to an
 * empty string, so any assertion made against a rendered computed style would pass vacuously.
 */
// @ts-expect-error Vitest runs this source contract in Node; the browser bundle excludes Node types.
import { readFileSync, readdirSync } from "node:fs";

/** Every rendering surface in the app: the files that can reintroduce a type decision by hand. */
function chromeSources(dir = "src"): string[] {
  const out: string[] = [];
  for (const entry of readdirSync(dir, { withFileTypes: true }) as Array<{
    name: string;
    isDirectory: () => boolean;
  }>) {
    const path = `${dir}/${entry.name}`;
    if (entry.isDirectory()) out.push(...chromeSources(path));
    else if (/\.tsx$/.test(entry.name) && !/\.test\.tsx$/.test(entry.name)) out.push(path);
  }
  return out;
}

const css = readFileSync("src/styles/index.css", "utf8");
const tailwind = readFileSync("tailwind.config.js", "utf8");
const librarySources = [
  "src/components/PartsList.tsx",
  "src/components/SearchOverlay.tsx",
  "src/pages/ComponentsPage.tsx",
].map((path) => readFileSync(path, "utf8"));

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

function contrast(left: string, right: string): number {
  const a = luminance(rgb(left));
  const b = luminance(rgb(right));
  return (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);
}

/**
 * HSL saturation, 0..1. The honest measure of "does this carry a hue".
 *
 * The previous test asked whether all three channels were within 2 points of one another, which is
 * a test for a PURE grey rather than for a neutral. The shipped palette is a cool neutral - the
 * owner's chosen values put the frame at #1F2022 and the label tier at #A9AFB7, a cast of 3 and 14
 * points respectively - and every one of those still reads as grey next to a real hue: measured,
 * the most saturated chrome token is 0.13 and the two remaining status hues are 0.31 and 0.51. So
 * the rule is stated as the thing it protects: chrome is DESATURATED, and a hue is reserved for the
 * two ends of the status scale (verified/available green, failed/obsolete red) and for the three
 * color-is-data families. Selection, the active state, focus and every warning are neutral.
 */
function saturation(hex: string): number {
  const [r, g, b] = rgb(hex).map((v) => v / 255);
  const max = Math.max(r, g, b);
  const min = Math.min(r, g, b);
  if (max === min) return 0;
  const l = (max + min) / 2;
  return l > 0.5 ? (max - min) / (2 - max - min) : (max - min) / (max + min);
}

/** The channel cast, in points out of 255. A neutral has a small one in some direction. */
function cast(hex: string): number {
  const [r, g, b] = rgb(hex);
  return Math.max(r, g, b) - Math.min(r, g, b);
}

// The chrome tokens: every surface, control, border, text tier, selection, accent and focus value.
// Explicitly NOT the --cat-* component thumbnails, the --stm-* pinout pads or the --c-layer-*
// land-pattern layers, where colour IS the datum being encoded and a grayscale value would carry no
// information at all.
//
// The SELECTION and ACCENT tokens are in this list now. They spent one release as a muted amber on
// the reasoning quoted below, and the reasoning was sound about the failure it fixed and wrong about
// the cost: once selection, the active tab, the active tool, the focus ring and every warning state
// all resolved onto one amber, that amber was the most common colour on screen and no longer marked
// anything. The measured failure it was introduced to fix (a light neutral fill dropping the
// metadata tier to 2.0:1) is now fixed by MEASURING the fill instead of by hueing it - see the
// selected-row contrast test below, which holds all five tiers on both the resting and hovered fill.
const CHROME_TOKENS = [
  "--c-app",
  "--c-canvas",
  "--c-rail",
  "--c-surface",
  "--c-raise",
  "--c-raise2",
  "--c-section",
  "--c-active",
  "--c-field",
  "--c-popover",
  "--c-band",
  "--c-stage",
  "--c-sticky",
  "--c-control-top",
  "--c-control-bottom",
  "--c-control-hover",
  "--c-control-pressed",
  "--c-line-dark",
  "--c-line",
  "--c-line2",
  "--c-edge",
  "--c-t1",
  "--c-t2",
  "--c-t3",
  "--c-t4",
  "--c-t5",
  "--c-acc-on",
  "--c-ring-track",
  "--body-bg",
  "--root-bg",
  "--sb-thumb",
  "--sb-thumb-hover",
  "--sb-track",
  // Selection, the active surface it shares with the active tab and the active tool, and the edge
  // marker that does the actual marking.
  "--c-selected",
  "--c-selected-hover",
  "--c-selected-edge",
  // The accent and the focus ring. Both neutral: an accent is a LOUD neutral spent on a primary
  // action's fill, and a focus ring is a high-contrast neutral outline that is neither a blue nor,
  // as of this pass, an amber.
  "--c-acc",
  "--c-acc-strong",
  "--c-focus",
  // The warning tier. Green and red are still hues because each names one end of a scale; a warning
  // is the exact word plus a triangle, and it is measured as text below.
  "--c-warn",
  "--c-warn-text",
] as const;

const THEMES = [
  ["dark", ":root"],
  ["light", ':root[data-theme="light"]'],
] as const;

describe("the type scale is fixed, narrow, and Windows-sized", () => {
  it("uses no clamp() or viewport unit for any font size", () => {
    // The former scale interpolated every role across the 1024-1600px range, so the same label
    // rendered at a different size on two of the owner's own windows and no two surfaces could be
    // compared. A desktop application's text does not resize with its window.
    const fontSizeDeclarations = [...css.matchAll(/--fs-[\w-]+:\s*([^;]+);/g)].map((m) => m[1]);
    expect(fontSizeDeclarations.length).toBeGreaterThanOrEqual(8);
    for (const value of fontSizeDeclarations) {
      expect(value, `font size "${value}"`).not.toMatch(/clamp\(/);
      expect(value, `font size "${value}"`).not.toMatch(/\d(vw|vh|vmin|vmax)\b/);
    }
    // And nothing anywhere in the sheet sizes type off the viewport by another spelling.
    expect(css).not.toMatch(/font-size:[^;]*clamp\(/);
    expect(css).not.toMatch(/font-size:[^;]*\dv[wh]/);
  });

  it("spends its whole budget on four sizes: 14 / 13 / 11 / 10", () => {
    const sizes = new Set(
      [...css.matchAll(/--fs-ui-[\w-]+:\s*(\d+(?:\.\d+)?)px;/g)].map((m) => Number(m[1])),
    );
    expect([...sizes].sort((a, b) => b - a)).toEqual([14, 13, 11, 10]);
  });

  it("puts nothing below 10px and nothing at 16px or above", () => {
    const sizes = [...css.matchAll(/--fs-ui-[\w-]+:\s*(\d+(?:\.\d+)?)px;/g)].map((m) =>
      Number(m[1]),
    );
    expect(Math.min(...sizes)).toBeGreaterThanOrEqual(10);
    expect(Math.max(...sizes)).toBeLessThan(16);
  });

  it("reserves 14px for the canonical component MPN alone", () => {
    const fourteens = [...css.matchAll(/(--fs-ui-[\w-]+):\s*14px;/g)].map((m) => m[1]);
    expect(fourteens).toEqual(["--fs-ui-mpn"]);
  });

  it("allows exactly three weights, and remaps bold rather than leaving 700 reachable", () => {
    const weights = new Set(
      [...css.matchAll(/font-weight:\s*(\d+);/g)].map((m) => Number(m[1])),
    );
    expect([...weights].sort((a, b) => a - b)).toEqual([400, 500, 600]);
    // `font-bold` is still written at ~200 call sites; the config lands it on 600 so the budget
    // holds without 112 files being edited.
    const configWeights = new Set(
      [...tailwind.matchAll(/^\s+(?:thin|extralight|light|normal|medium|semibold|bold|extrabold|black):\s*"(\d+)",/gm)].map(
        (m) => Number(m[1]),
      ),
    );
    expect([...configWeights].sort((a, b) => a - b)).toEqual([400, 500, 600]);
  });

  it("sets the platform face and no bundled interface font", () => {
    expect(css).toMatch(/font-family:\s*"Segoe UI Variable",\s*"Segoe UI",\s*Tahoma,\s*Arial/);
    expect(tailwind).toContain('"Segoe UI Variable"');
    // Scoped to the FACE STACKS: the prose in this repo is full of the word "interface".
    const stacks = [
      ...css.matchAll(/font-family:\s*([^;]+);/g),
      ...tailwind.matchAll(/(?:sans|mono):\s*\[([^\]]+)\]/g),
    ].map((m) => m[1]);
    expect(stacks.length).toBeGreaterThanOrEqual(3);
    for (const stack of stacks) {
      expect(stack, "a bundled interface face is back in a font stack").not.toMatch(
        /Work Sans|Inter|Manrope|Poppins|Satoshi|Geist Sans/i,
      );
    }
  });

  it("carries no global negative letter-spacing and forces no font smoothing", () => {
    // Negative tracking was set for a display face and was landing on 10px labels, where it closes
    // the counters. Forced antialiasing thins small Windows text off the platform default.
    expect(css).not.toMatch(/letter-spacing:\s*-/);
    expect(css).not.toMatch(/^\s*-webkit-font-smoothing:/m);
    expect(css).not.toMatch(/^\s*text-rendering:\s*optimizeLegibility/m);
    expect(tailwind).not.toMatch(/letterSpacing/);
  });

  it("keeps the Library surfaces off hand-rolled px sizes", () => {
    expect(librarySources.join("\n")).not.toMatch(/text-\[(?:9|10|13|17)(?:\.\d+)?px\]/);
  });

  it("lets no surface reintroduce negative tracking one call site at a time", () => {
    // Eight surfaces carried their own `tracking-[-0.01em]`..`[-0.02em]`, tuned when their
    // headings were 16-24px. At 11-13px, closing the sidebearings closes the counters and the
    // word greys out. Removing the global value only helps while nobody re-adds a local one.
    const offenders: string[] = [];
    for (const file of chromeSources()) {
      for (const [hit] of readFileSync(file, "utf8").matchAll(/tracking-\[-[\d.]+em\]/g)) {
        offenders.push(`${file} ${hit}`);
      }
    }
    expect(offenders).toEqual([]);
  });
});

describe("quiet separator hierarchy", () => {
  it.each(THEMES)("%s routine lines stay subordinate to surface changes", (_theme, selector) => {
    const block = themeBlock(selector);
    expect(contrast(property(block, "--c-line"), property(block, "--c-surface"))).toBeLessThan(1.45);
    expect(contrast(property(block, "--c-line2"), property(block, "--c-surface"))).toBeLessThan(1.75);
  });
});

describe("the chrome is neutral", () => {
  it.each(THEMES)("%s chrome tokens carry no hue, selection and focus included", (_theme, selector) => {
    const block = themeBlock(selector);
    for (const token of CHROME_TOKENS) {
      const value = property(block, token);
      // Desaturated, not literally grey: the shipped palette is a COOL neutral by the owner's
      // choice, and the measured worst case is 0.13 against a status green of 0.31.
      expect(saturation(value), `${token} = ${value} carries a hue`).toBeLessThanOrEqual(0.15);
      // And the cast is small in absolute terms too, so "desaturated" cannot be satisfied by a
      // very light or very dark colour that is actually strongly tinted.
      expect(cast(value), `${token} = ${value} is too strongly cast`).toBeLessThanOrEqual(16);
    }
  });

  it.each(THEMES)("%s has no blue anywhere in chrome", (_theme, selector) => {
    const block = themeBlock(selector);
    // THE RULE THAT ACTUALLY MATTERS, and it has survived two palette changes intact: no surface, no
    // border, no text tier, no control, no selection and no focus ring is a BLUE. The cool cast of a
    // neutral grey is not a blue - it is what makes the greys read as a tool window rather than as
    // warm paper - so the test names the two things separately: a neutral may lean cool by a bounded
    // amount, and anything genuinely saturated must be warm.
    //
    // The bound is 16 and it is NOT to be widened again. It was raised from 2 once, to admit the
    // owner's cool grey palette, and 16 out of 255 is already the whole distance between "a grey
    // that reads cool" and "a colour". A third widening would be the point at which this test stops
    // being the no-blue rule and starts being a record of whatever shipped.
    for (const token of CHROME_TOKENS) {
      const [r, , b] = rgb(property(block, token));
      expect(b - r, `${token} leans blue`).toBeLessThanOrEqual(16);
    }
    for (const token of CHROME_TOKENS) {
      const value = property(block, token);
      if (saturation(value) <= 0.15) continue;
      const [r, , b] = rgb(value);
      expect(r - b, `${token} = ${value} is a saturated cool hue`).toBeGreaterThan(20);
    }
    // Tailwind's own palette is not extended with one either, and no chrome class names a hue.
    expect(tailwind).not.toMatch(/#[0-9a-f]*(?:[0-9a-f]{2})(?:[89a-f][0-9a-f])\b/i);
  });

  it.each(THEMES)("%s spends NO hue on selection, the active state or focus", (_theme, selector) => {
    // The replacement for "spends its one non-status hue on selection, warm", which asserted the
    // amber. There is no non-status hue in chrome any more: selection is a measured surface shift
    // plus an edge marker, the active tab and active tool share that surface, and focus is a
    // high-contrast neutral outline. All six are in CHROME_TOKENS above and are therefore already
    // held to saturation <= 0.15; this states the intent so the amber cannot come back by being
    // desaturated just enough to slip through.
    const block = themeBlock(selector);
    for (const token of [
      "--c-selected",
      "--c-selected-hover",
      "--c-selected-edge",
      "--c-acc",
      "--c-acc-strong",
      "--c-focus",
    ]) {
      const value = property(block, token);
      expect(saturation(value), `${token} = ${value} carries a hue`).toBeLessThanOrEqual(0.15);
      expect(cast(value), `${token} = ${value} is too strongly cast`).toBeLessThanOrEqual(16);
    }
  });

  it.each(THEMES)("%s states a warning without a hue at all", (_theme, selector) => {
    // `Missing`, `Missing Datasheet + Purchase Link`, `3 Required Values Missing` and
    // `Update Available` were all amber, which is how amber became the commonest colour on screen.
    // A warning is now the exact word plus the triangle StatusText draws beside it, so the state
    // does not depend on colour AT ALL. Both warning tiers are therefore desaturated AND readable as
    // ordinary text on every surface small text lands on.
    const block = themeBlock(selector);
    for (const token of ["--c-warn", "--c-warn-text"]) {
      const value = property(block, token);
      expect(saturation(value), `${token} = ${value} is still a hue`).toBeLessThanOrEqual(0.15);
      for (const surfaceToken of ["--c-canvas", "--c-band", "--c-popover"]) {
        expect(
          contrast(value, property(block, surfaceToken)),
          `${token} on ${surfaceToken}`,
        ).toBeGreaterThanOrEqual(4.5);
      }
    }
    // And red and green are NOT swept along with it: the owner asked for amber gone, not for
    // semantic colour gone, and each of these names one end of a scale a reader acts on.
    for (const token of ["--c-ok", "--c-err"]) {
      expect(saturation(property(block, token)), `${token} lost its hue`).toBeGreaterThan(0.15);
    }
  });

  it.each(THEMES)("%s spends a status WORD at the text bar, not the mark bar", (_theme, selector) => {
    // The failure this closes, measured on the two surfaces small status text actually lands on.
    // `text-ok` resolved to --c-ok and came to 3.78 on the light workspace and 3.93 on the band;
    // `text-err` resolved to --c-err and came to 3.98 on the dark workspace and 3.60 on the band.
    // Every one of those is under AA for normal text, and a status word IS normal text: the reader
    // is reading it, not glancing at it. The fix was already in the stylesheet and unexposed - the
    // `-text` strengths - so a word wears those now and only a MARK keeps the plain token.
    //
    // Both halves are asserted, because either one alone can be satisfied while the pairing rots.
    const block = themeBlock(selector);
    for (const token of ["--c-ok-text", "--c-err-text"]) {
      for (const surfaceToken of ["--c-canvas", "--c-band", "--c-popover", "--c-surface"]) {
        expect(
          contrast(property(block, token), property(block, surfaceToken)),
          `${token} on ${surfaceToken}`,
        ).toBeGreaterThanOrEqual(4.5);
      }
    }
    // The mark strengths still clear the NON-text bar, which is the bar a fill, a border and a
    // glyph answer to. Held here so nobody "fixes" the pair by darkening the marks into invisibility.
    for (const token of ["--c-ok", "--c-err"]) {
      for (const surfaceToken of ["--c-canvas", "--c-band"]) {
        expect(
          contrast(property(block, token), property(block, surfaceToken)),
          `${token} as a mark on ${surfaceToken}`,
        ).toBeGreaterThanOrEqual(3);
      }
    }
  });

  it.each(THEMES)("%s carries every text tier on a selected row", (_theme, selector) => {
    // This is the failure the neutral fill actually shipped: a selected picker row put its
    // metadata tier at 2.0:1. Every tier the row uses is measured against the selection fill and
    // its hover, because a row you have selected is a row you are reading.
    const block = themeBlock(selector);
    for (const surface of ["--c-selected", "--c-selected-hover"]) {
      const fill = property(block, surface);
      for (const tier of ["--c-t1", "--c-t2", "--c-t3"]) {
        expect(
          contrast(property(block, tier), fill),
          `${tier} on ${surface}`,
        ).toBeGreaterThanOrEqual(4.5);
      }
      // The metadata tier is supplementary by definition and is held to the large-text floor,
      // exactly as it is on the workspace surface.
      expect(
        contrast(property(block, "--c-t4"), fill),
        `--c-t4 on ${surface}`,
      ).toBeGreaterThanOrEqual(3);
    }
  });

  it("keeps the two color-is-data families, which are not chrome", () => {
    // The pinout map encodes electrical class in colour and the parts list tints family
    // thumbnails. Removing hue there would remove the information, not the decoration.
    expect(css).toContain("--stm-power:");
    expect(css).toContain("--cat-capacitor:");
  });
});

describe("the five text tiers are opaque", () => {
  it.each(THEMES)("%s states every tier as a solid hex, never as nested opacity", (_theme, selector) => {
    const block = themeBlock(selector);
    for (const token of ["--c-t1", "--c-t2", "--c-t3", "--c-t4", "--c-t5"]) {
      const value = property(block, token);
      // rgb() would throw on an rgba()/alpha value; the explicit check names the rule.
      expect(value, `${token} must be an opaque hex`).toMatch(/^#[0-9a-f]{6}$/i);
      rgb(value);
    }
  });

  it.each(THEMES)("%s tiers descend, so the ladder is a ladder", (_theme, selector) => {
    const block = themeBlock(selector);
    const tiers = ["--c-t1", "--c-t2", "--c-t3", "--c-t4", "--c-t5"].map((t) =>
      luminance(rgb(property(block, t))),
    );
    const canvas = luminance(rgb(property(block, "--c-canvas")));
    // Each tier is strictly less contrasting against the workspace than the one above it.
    const against = tiers.map((l) => Math.abs(l - canvas));
    for (let i = 1; i < against.length; i += 1) {
      expect(against[i], `tier ${i + 1} is not quieter than tier ${i}`).toBeLessThan(against[i - 1]);
    }
  });

  it.each(THEMES)("%s label text passes AA on every surface small text lands on", (_theme, selector) => {
    const block = themeBlock(selector);
    const labelTier = property(block, "--c-t3");
    for (const surfaceToken of ["--c-canvas", "--c-band", "--c-popover"]) {
      expect(
        contrast(labelTier, property(block, surfaceToken)),
        `${surfaceToken} label contrast`,
      ).toBeGreaterThanOrEqual(4.5);
    }
  });

  it.each(THEMES)("%s primary and secondary clear AA with room to spare", (_theme, selector) => {
    const block = themeBlock(selector);
    for (const tier of ["--c-t1", "--c-t2"]) {
      for (const surfaceToken of ["--c-canvas", "--c-band", "--c-popover", "--c-surface"]) {
        expect(
          contrast(property(block, tier), property(block, surfaceToken)),
          `${tier} on ${surfaceToken}`,
        ).toBeGreaterThanOrEqual(4.5);
      }
    }
  });

  it.each(THEMES)("%s muted text still clears the large-text floor", (_theme, selector) => {
    // The muted tier carries timestamps and file metadata: supplementary by definition, and
    // deliberately below the label tier, but it is still text and still has to be readable.
    const block = themeBlock(selector);
    expect(
      contrast(property(block, "--c-t4"), property(block, "--c-canvas")),
    ).toBeGreaterThanOrEqual(3);
  });
});

describe("the chrome is a desktop, not a dashboard", () => {
  it("keeps corners at 2px or squarer", () => {
    for (const name of ["--r-card", "--r-control"]) {
      const value = property(themeBlock(":root"), name);
      expect(Number(value.replace("px", "")), `${name} = ${value}`).toBeLessThanOrEqual(2);
    }
  });

  it("casts a shadow only from a genuinely floating surface", () => {
    const block = themeBlock(":root");
    // A resting panel gets a 1px bevel and nothing else. Menus and dialogs get a tight one.
    expect(property(block, "--shadow-card")).toBe("inset 0 1px 0 var(--edge-hi)");
    expect(property(block, "--shadow-pop")).toMatch(/^0 2px 8px /);
    // No large soft glow anywhere: nothing may blur past 12px or offset past 4px.
    for (const shadow of [...css.matchAll(/--shadow-[\w-]+:\s*([^;]+);/g)].map((m) => m[1])) {
      for (const [, blur] of shadow.matchAll(/\b\d+px\s+(\d+)px\s+rgba/g)) {
        expect(Number(blur), `blur radius in "${shadow}"`).toBeLessThanOrEqual(12);
      }
    }
  });

  it("carries no glass, no radial lighting and no spring easing", () => {
    expect(css).not.toMatch(/backdrop-filter/);
    expect(css).not.toMatch(/radial-gradient/);
    expect(css).not.toMatch(/--c-hero-glow/);
    // The easing token stayed (existing classes name it) but the overshoot is gone: a cubic-bezier
    // whose second control point exceeds 1 is what makes a press bounce.
    const ease = property(themeBlock(":root"), "--ease-spring");
    const points = [...ease.matchAll(/[\d.]+/g)].map((m) => Number(m[0]));
    for (const p of points) expect(p, `${ease} overshoots`).toBeLessThanOrEqual(1);
  });

});

/**
 * The technical drawing canvas, which FOLLOWS THE THEME.
 *
 * It used to be one near-white value in both themes, on the reasoning that an engineering drawing
 * is paper and paper does not invert. Measured on the running application that reasoning failed:
 * the sheet's relative luminance is 0.911 and the dark workspace's is 0.036, so the two 184px
 * preview tiles were the brightest region on screen and outshone the component's own manufacturer
 * part number - which is the one item the whole surface is built to make primary. A drawing sheet
 * that fights the chrome around it is not paper, it is a lamp.
 *
 * Inverting the sheet is only half of it. These four assertions are the other half, and each one
 * guards a way the inversion could have made things worse rather than better:
 *
 *   the sheet differs between themes at all (the change itself);
 *   the sheet is DARKER than the workspace chrome in dark theme, so the previews recede;
 *   every ink clears 3:1 on its own sheet, so nothing is drawn in near-black on near-black;
 *   the six layer colours stay >=15 CIE76 dE apart, so copper, mask, paste, silkscreen,
 *   fabrication and courtyard remain six distinguishable answers - in dark theme too, where the
 *   values had to be re-tuned rather than reused.
 */
describe("the technical drawing canvas follows the theme", () => {
  const INKS = [
    "--c-technical-ink",
    "--c-technical-note",
    "--c-layer-copper",
    "--c-layer-mask",
    "--c-layer-paste",
    "--c-layer-silk",
    "--c-layer-fab",
    "--c-layer-courtyard",
    "--c-layer-pin-one",
  ] as const;

  /** The six switchable layers plus the pad-1 marker: the set that has to stay told apart. */
  const LAYERS = [
    "--c-layer-copper",
    "--c-layer-mask",
    "--c-layer-paste",
    "--c-layer-silk",
    "--c-layer-fab",
    "--c-layer-courtyard",
    "--c-layer-pin-one",
  ] as const;

  /** CIE76 dE, which measures how far apart two colours look rather than how they differ in RGB. */
  function lab(hex: string): [number, number, number] {
    const [r, g, b] = rgb(hex).map((v) => {
      const n = v / 255;
      return n <= 0.04045 ? n / 12.92 : ((n + 0.055) / 1.055) ** 2.4;
    });
    const x = (0.4124 * r + 0.3576 * g + 0.1805 * b) / 0.95047;
    const y = 0.2126 * r + 0.7152 * g + 0.0722 * b;
    const z = (0.0193 * r + 0.1192 * g + 0.9505 * b) / 1.08883;
    const f = (t: number) => (t > 0.008856 ? Math.cbrt(t) : 7.787 * t + 16 / 116);
    return [116 * f(y) - 16, 500 * (f(x) - f(y)), 200 * (f(y) - f(z))];
  }

  function deltaE(left: string, right: string): number {
    const a = lab(left);
    const b = lab(right);
    return Math.hypot(a[0] - b[0], a[1] - b[1], a[2] - b[2]);
  }

  it("does not carry one value for both themes", () => {
    expect(property(themeBlock(":root"), "--c-technical")).not.toBe(
      property(themeBlock(':root[data-theme="light"]'), "--c-technical"),
    );
  });

  it("recedes behind the workspace in dark theme instead of outshining the part number", () => {
    const block = themeBlock(":root");
    const sheet = luminance(rgb(property(block, "--c-technical")));
    // Darker than the panel it sits in AND than the workspace behind that, so a preview tile reads
    // as a recessed drawing area rather than as the brightest thing in the column.
    expect(sheet).toBeLessThan(luminance(rgb(property(block, "--c-field"))));
    expect(sheet).toBeLessThan(luminance(rgb(property(block, "--c-canvas"))));
    // And strictly quieter than the tier the MPN is drawn in, which is what was inverted before.
    expect(sheet).toBeLessThan(luminance(rgb(property(block, "--c-t1"))));
  });

  it("keeps the sheet the lightest surface in light theme, where that is what paper is", () => {
    const block = themeBlock(':root[data-theme="light"]');
    const sheet = luminance(rgb(property(block, "--c-technical")));
    expect(sheet).toBeGreaterThan(luminance(rgb(property(block, "--c-canvas"))));
  });

  it.each(THEMES)("%s draws every ink at 3:1 or better on its own sheet", (_theme, selector) => {
    const block = themeBlock(selector);
    const sheet = property(block, "--c-technical");
    for (const token of INKS) {
      expect(contrast(property(block, token), sheet), `${token} on the sheet`).toBeGreaterThanOrEqual(
        3,
      );
    }
    // The body wash is the one value allowed to be close to the sheet - it is a tint, not a line -
    // but the ink has to remain legible ON it, which is the case a filled IC rectangle produces.
    expect(
      contrast(property(block, "--c-technical-ink"), property(block, "--c-technical-wash")),
      "ink on the body wash",
    ).toBeGreaterThanOrEqual(4.5);
  });

  it.each(THEMES)("%s keeps the layer colours distinguishable from each other", (_theme, selector) => {
    const block = themeBlock(selector);
    const close: string[] = [];
    for (let i = 0; i < LAYERS.length; i += 1) {
      for (let j = i + 1; j < LAYERS.length; j += 1) {
        const distance = deltaE(property(block, LAYERS[i]), property(block, LAYERS[j]));
        if (distance < 15) close.push(`${LAYERS[i]}/${LAYERS[j]} = ${distance.toFixed(1)}`);
      }
    }
    expect(close).toEqual([]);
  });

  it("keeps the three color-is-data families, which are not chrome", () => {
    // The pinout map encodes electrical class in colour, the parts list tints family thumbnails,
    // and the land pattern encodes which layer a shape is on. Removing hue in any of the three
    // would remove the information, not the decoration.
    expect(css).toContain("--stm-power:");
    expect(css).toContain("--cat-capacitor:");
    expect(css).toContain("--c-layer-copper:");
  });
});
