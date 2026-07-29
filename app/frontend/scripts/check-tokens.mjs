#!/usr/bin/env node
/**
 * Design-token parity gate (TOKEN-01).
 *
 * `tailwind.config.js` maps utility classes onto CSS custom properties
 * (`band: "var(--c-band)"`, `card: "var(--r-card)"`, `"2xs": ["var(--fs-2xs)", ...]`),
 * and `src/styles/index.css` is the only place those properties are declared. Nothing
 * in the build checked that the two agree, and a `var()` pointing at an undeclared
 * property fails SILENTLY: the declaration is invalid at computed-value time, so the
 * browser drops the property. No console warning, no build error.
 *
 * That is not hypothetical. Ten tokens shipped undeclared for the app's whole life
 * (found 2026-07-24):
 *   --c-band                  every `bg-band` chrome strip painted TRANSPARENT (panel
 *                             title bars, the status bar, modal headers, and the
 *                             parametric-search overlay, which was unusable as a result)
 *   --r-card / --r-control    every card and control rendered at border-radius 0,
 *                             silently violating the card-14 / control-8 north-star
 *   --fs-2xs … --fs-title     the entire type scale collapsed onto the 13px body size,
 *                             so text-2xs and text-title rendered identically
 *
 * This runs in `npm run build`, so the owner's existing verify gate
 * (test:run && typecheck && build) catches a reintroduction. It lives here rather than
 * in vitest because `vite.config.ts` sets `test.css: false`, which makes any stylesheet
 * import inside a test resolve to an empty string -- every assertion would pass
 * vacuously, which is worse than no test at all.
 */
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const css = readFileSync(join(root, "src/styles/index.css"), "utf8");
const config = readFileSync(join(root, "tailwind.config.js"), "utf8");

const referenced = new Set(
  [...config.matchAll(/var\(\s*(--[a-zA-Z0-9-]+)\s*\)/g)].map((m) => m[1]),
);
const declared = new Set([...css.matchAll(/(--[a-zA-Z0-9-]+)\s*:/g)].map((m) => m[1]));

const lightStart = css.indexOf('[data-theme="light"]');
const lightCss = lightStart === -1 ? "" : css.slice(lightStart);
const lightDeclared = new Set(
  lightStart === -1
    ? []
    : [...lightCss.matchAll(/(--[a-zA-Z0-9-]+)\s*:/g)].map((m) => m[1]),
);

const problems = [];

// Guard against a silent read/regex failure making the checks vacuous.
if (referenced.size < 20) {
  problems.push(`only ${referenced.size} var() references found in tailwind.config.js`);
}
if (declared.size < 20) {
  problems.push(`only ${declared.size} custom properties found in index.css`);
}
if (lightStart === -1) {
  problems.push('no [data-theme="light"] block found in index.css');
}

const undeclared = [...referenced].filter((t) => !declared.has(t)).sort();
if (undeclared.length) {
  problems.push(
    `referenced by tailwind.config.js but never declared in index.css:\n    ${undeclared.join("\n    ")}`,
  );
}

// Themed colors must also be overridden for the light theme, or light mode inherits dark.
const missingLight = [...referenced]
  .filter((t) => t.startsWith("--c-") && declared.has(t) && !lightDeclared.has(t))
  .sort();
if (missingLight.length) {
  problems.push(
    `declared for dark but missing a [data-theme="light"] override:\n    ${missingLight.join("\n    ")}`,
  );
}

// Selected rows must read as selected in light mode, not as a hover that happened to stick.
// This belongs in the CSS-aware build gate rather than Vitest: test.css=false intentionally turns
// stylesheet imports into empty strings (see the module comment above).
function blackAlpha(token) {
  const escaped = token.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const match = new RegExp(`${escaped}:\\s*rgba\\(0,\\s*0,\\s*0,\\s*([\\d.]+)\\)`).exec(lightCss);
  return match ? Number(match[1]) : null;
}

const selectedAlpha = blackAlpha("--c-acc-soft");
const hoverAlpha = blackAlpha("--c-hover");
if (selectedAlpha === null || hoverAlpha === null) {
  problems.push("light interaction tokens --c-acc-soft / --c-hover must use black rgba values");
} else if (selectedAlpha < 0.1 || selectedAlpha <= hoverAlpha * 2) {
  problems.push(
    `light selection is not visibly stronger than hover (--c-acc-soft ${selectedAlpha}, --c-hover ${hoverAlpha})`,
  );
}

if (problems.length) {
  console.error("\nDesign token parity check FAILED:\n");
  for (const p of problems) console.error(`  - ${p}`);
  console.error("");
  process.exit(1);
}

console.log(
  `token parity ok (${referenced.size} referenced, ${declared.size} declared, ${lightDeclared.size} light overrides)`,
);
