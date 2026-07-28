import { describe, expect, it } from "vitest";
import { panesTemplate } from "./DetailPanel";

// Owner, 2026-07-26: "sourcing and specs panes open/closable ... and the open ones maximized".
describe("panesTemplate", () => {
  it("gives all three open panes the same track", () => {
    expect(panesTemplate(true, true)).toBe(
      "minmax(0,1fr) minmax(0,1fr) minmax(0,1fr)",
    );
  });

  it("gives the freed space to whichever pane is still open", () => {
    // A remaining work pane must grow rather than sit beside a collapsed rail and empty grid.
    expect(panesTemplate(false, true)).toBe("320px 44px minmax(16rem,1fr)");
    expect(panesTemplate(true, false)).toBe("320px minmax(16rem,1fr) 44px");
  });

  it("lets the specimen rail grow when BOTH panes are collapsed", () => {
    // otherwise a fixed 288px column beside two 44px rails leaves the sheet mostly empty
    expect(panesTemplate(false, false)).toBe("minmax(320px,1fr) 44px 44px");
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
