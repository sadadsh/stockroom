import { describe, expect, it } from "vitest";
import { panesTemplate } from "./DetailPanel";

// Owner, 2026-07-26: "sourcing and specs panes open/closable ... and the open ones maximized".
describe("panesTemplate", () => {
  it("keeps the sheet's existing three tracks when nothing is collapsed", () => {
    // the layout the owner already approved must be byte-identical when no pane is closed
    expect(panesTemplate(true, true)).toBe("288px minmax(16rem,1fr) 320px");
  });

  it("gives the freed space to whichever pane is still open", () => {
    // Sourcing is a fixed 320px when both are open; with Specifications collapsed it must GROW,
    // not sit at 320px beside a 44px rail and a lake of empty grid.
    expect(panesTemplate(false, true)).toContain("minmax(16rem,1fr)");
    expect(panesTemplate(false, true)).not.toContain("320px");
    expect(panesTemplate(true, false)).toContain("minmax(16rem,1fr)");
    expect(panesTemplate(true, false)).not.toContain("320px");
  });

  it("lets the specimen rail grow when BOTH panes are collapsed", () => {
    // otherwise a fixed 288px column beside two 44px rails leaves the sheet mostly empty
    expect(panesTemplate(false, false)).toBe("minmax(288px,1fr) 44px 44px");
  });

  it("always states three tracks, so a collapsed pane still occupies its own column", () => {
    for (const [a, b] of [[true, true], [true, false], [false, true], [false, false]] as const) {
      expect(panesTemplate(a, b).trim().split(/\s+/)).toHaveLength(3);
    }
  });

  it("never emits a template a Tailwind class could not carry, i.e. it is a plain CSS value", () => {
    // this string goes into a CSS custom property, never into `grid-cols-[...]`; a literal built
    // into a Tailwind class generates NO CSS at all, which this grid has already been bitten by.
    for (const [a, b] of [[true, true], [false, false]] as const) {
      expect(panesTemplate(a, b)).not.toContain("_");
    }
  });
});
