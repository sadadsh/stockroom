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

/** Source with comments removed, for gates that must read what the code DOES rather than what it
 *  says about itself. A gate that scans raw text cannot tell a class being USED from the same class
 *  being CITED in a comment explaining why it was removed - and the comments here deliberately name
 *  the exact classes that must never come back, so the citation would fail the gate forever. */
function code(name: string): string {
  return source(name)
    .replace(/\/\*[\s\S]*?\*\//g, " ")
    .replace(/(^|[^:])\/\/[^\n]*/g, "$1 ");
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

  it("keeps the canonical dense metadata role free of decorative letter spacing", () => {
    // Dense property metadata now uses the semantic type and helper-colour roles.
    // Reintroducing arbitrary tracking here would create a second visual authority.
    const spacings = new Set(
      [...source("primitives.tsx").matchAll(/tracking-\[([0-9.]+em)\]/g)].map((m) => m[1]),
    );
    expect([...spacings]).toEqual([]);
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

  it("switches the SHEET's column count on the CONTAINER's width, never the viewport's", () => {
    // MEASURED in the real WebView2 window at the host's own default 1400x900 (2026-07-25):
    // the sheet grid gets the DETAIL PANE's width, not the window's. Rail 190 + picker 320 +
    // padding 48 leave it 825px, while `xl:` (a VIEWPORT media query) had already switched on
    // three tracks needing 288+256+320 = 864px. The middle track pinned at its 256px minimum,
    // so Specifications rendered 205px wide and 5885px tall - one word per line.
    //
    // The proof that a viewport query is the wrong instrument: COLLAPSING THE RAIL fixed it at
    // an UNCHANGED viewport (grid 825 -> 963, specs 205 -> 304 wide, 5885 -> 1916 tall). A media
    // query cannot see the rail state, so no threshold can ever be right. Only a container query
    // measures the box the columns actually have to fit inside.
    const sheet = /id="specs"[\s\S]*?className=\{([\s\S]*?)\}\n/.exec(source("DetailPanel.tsx"));
    if (!sheet) throw new Error("could not find the specs WorkbenchPanel className");
    // (?<!@) so the CONTAINER form `@xl:` is not mistaken for the viewport form `xl:` - the
    // container variants embed the same breakpoint names, and a bare \b matches after the `@`.
    const viewportTracks = [...sheet[1].matchAll(/(?<!@)\b(?:sm|md|lg|xl|2xl):grid-cols-/g)];
    expect(viewportTracks.map((m) => m[0])).toEqual([]);
    expect(sheet[1]).toMatch(/@[\w[\]]+:grid-cols-/);
  });

  it("places the sheet's COLUMNS on the same container query as its tracks", () => {
    // Placement and track definition are ONE decision. Converting the tracks to container queries
    // while leaving `lg:col-start-2 xl:col-start-auto` on a child desynchronised them instantly: at
    // a 1384px viewport the `xl:` rule won and put the Sourcing column into the 288px FIRST track
    // instead of under Specifications, both rows were stretched to an equal 328px, and the asset
    // tiles were sliced in half. Half-converting is worse than not converting, because the two
    // halves then disagree about how many columns exist.
    const stray = [
      ...code("DetailPanel.tsx").matchAll(
        /(?<!@)\b(?:sm|md|lg|xl|2xl):(?:col-start-|col-span-|grid-rows-)/g,
      ),
    ];
    expect(stray.map((m) => m[0])).toEqual([]);
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
