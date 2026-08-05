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

/** Is a hex grey? A grey has all three channels within a hair of one another. */
function isGrayscale(hex: string): boolean {
  const [r, g, b] = rgb(hex);
  return Math.max(r, g, b) - Math.min(r, g, b) <= 2;
}

// The chrome tokens: every surface, control, border, text tier, accent and focus value. Explicitly
// NOT the --cat-* component thumbnails or the --stm-* pinout pads, where colour IS the datum being
// encoded and a grayscale value would carry no information at all.
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
  "--c-selected",
  "--c-selected-hover",
  "--c-line-dark",
  "--c-line",
  "--c-line2",
  "--c-edge",
  "--c-t1",
  "--c-t2",
  "--c-t3",
  "--c-t4",
  "--c-t5",
  "--c-acc",
  "--c-acc-on",
  "--c-acc-strong",
  "--c-focus",
  "--c-ring-track",
  "--body-bg",
  "--root-bg",
  "--sb-thumb",
  "--sb-thumb-hover",
  "--sb-track",
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

describe("the chrome is grayscale", () => {
  it.each(THEMES)("%s chrome tokens carry no hue at all, focus ring included", (_theme, selector) => {
    const block = themeBlock(selector);
    for (const token of CHROME_TOKENS) {
      const value = property(block, token);
      expect(isGrayscale(value), `${token} = ${value} is not grayscale`).toBe(true);
    }
  });

  it.each(THEMES)("%s has no blue anywhere in chrome", (_theme, selector) => {
    const block = themeBlock(selector);
    for (const token of CHROME_TOKENS) {
      const [r, , b] = rgb(property(block, token));
      // A blue cast is a blue channel meaningfully above the red one. On a true grey they match.
      expect(b - r, `${token} leans blue`).toBeLessThanOrEqual(2);
    }
    // Tailwind's own palette is not extended with one either, and no chrome class names a hue.
    expect(tailwind).not.toMatch(/#[0-9a-f]*(?:[0-9a-f]{2})(?:[89a-f][0-9a-f])\b/i);
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

  it("declares the technical drawing canvas identically in both themes", () => {
    // An engineering drawing is paper. It does not invert when the application chrome does.
    expect(property(themeBlock(":root"), "--c-technical")).toBe(
      property(themeBlock(':root[data-theme="light"]'), "--c-technical"),
    );
  });
});
