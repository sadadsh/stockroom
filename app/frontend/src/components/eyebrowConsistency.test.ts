/**
 * punch 14: "remove the box behind spec group headers". The root cause was never the box - it was
 * that EVERY eyebrow in DetailPanel was its own class string, so no two matched. Measured before the
 * fix: ten one-off strings carrying FOUR different letter-spacings (0.04 / 0.05 / 0.07 / 0.08em),
 * two of which this session added while building the Batch 3 controls.
 *
 * This is the gate, not just the fix: an eleventh hand-rolled eyebrow fails here.
 *
 * The sources are read through Vite's `?raw` glob rather than node's `fs`, because the production
 * build type-checks this file too and the app carries no @types/node - reaching for `node:fs` here
 * kept the test suite green while turning the BUILD red.
 */
import { describe, expect, it } from "vitest";

const RAW = import.meta.glob("./{DetailPanel,primitives}.tsx", {
  query: "?raw",
  import: "default",
  eager: true,
}) as Record<string, string>;

function source(name: string): string {
  const hit = Object.entries(RAW).find(([path]) => path.endsWith(`/${name}`));
  if (!hit) throw new Error(`could not read ${name}; globbed: ${Object.keys(RAW).join(", ")}`);
  return hit[1];
}

describe("eyebrow consistency", () => {
  it("DetailPanel declares no ad-hoc uppercase eyebrow class strings", () => {
    const offenders = source("DetailPanel.tsx")
      .split("\n")
      .map((line, i) => ({ line: line.trim(), n: i + 1 }))
      .filter(({ line }) => /uppercase\s+tracking-\[/.test(line))
      .map((o) => `${o.n}: ${o.line.slice(0, 80)}`);
    expect(
      offenders,
      "use the shared eyebrow treatment (EYEBROW_DENSE / <Eyebrow dense>) instead",
    ).toEqual([]);
  });

  it("there is exactly ONE canonical dense-eyebrow letter-spacing in the primitives", () => {
    // The whole point is a single decision. Two spacings in the primitive would just move the
    // inconsistency somewhere harder to see.
    const spacings = new Set(
      [...source("primitives.tsx").matchAll(/tracking-\[([0-9.]+em)\]/g)].map((m) => m[1]),
    );
    expect([...spacings]).toEqual(["0.07em"]);
  });
});

describe("property-grid tracks", () => {
  it("are written as literal class strings, never assembled from a variable", () => {
    // Tailwind generates utilities by scanning source TEXT. An arbitrary value interpolated into a
    // template literal yields a class attribute with no CSS behind it: `display:grid` still applies
    // (that part is literal) while the track definition silently does not exist, so the grid
    // collapses to one cell per line. A class-name assertion cannot see this; only a shot can, which
    // is exactly how it was found - with the test suite green.
    const interpolated = [...source("DetailPanel.tsx").matchAll(/grid-cols-\[[^\]]*\$\{/g)];
    expect(interpolated.map((m) => m[0])).toEqual([]);
  });

  it("keeps a spec row and its alternates on the SAME label track at EVERY breakpoint", () => {
    // Different widths would put a child's value at a different x from its parent's - the long-gap
    // complaint reintroduced one level down, on exactly the rows meant to be compared. The track is
    // responsive (it narrows once the sheet stacks into a single column), so the two must agree at
    // each breakpoint, not merely use the same number somewhere.
    const src = source("DetailPanel.tsx");
    const widths = (name: string): string[] => {
      const decl = new RegExp(`const ${name} =([\\s\\S]*?);\\n`).exec(src);
      if (!decl) throw new Error(`could not find ${name}`);
      return [...decl[1].matchAll(/grid-cols-\[minmax\(0,(?:calc\()?([0-9.]+rem)/g)].map(
        (m) => m[1],
      );
    };
    const rowTracks = widths("SPEC_ROW_GRID");
    expect(rowTracks.length).toBeGreaterThanOrEqual(2); // a base width and an xl width
    expect(widths("ALT_ROW_GRID")).toEqual(rowTracks);
  });
});
