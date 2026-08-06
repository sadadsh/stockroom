import { describe, expect, it } from "vitest";
import {
  ICON_BY_ID,
  ICON_CATEGORIES,
  ICON_IDS_BY_CATEGORY,
  ICON_REGISTRY,
} from "./iconRegistry";

// The registry is the single source of truth for the icon set (lifted from the blueprint inventory of
// 58 icons: primary 21, bespoke 31, art 3, brand 3). These assertions lock its shape without reaching
// outside src/ - the inventory JSON lives under the gitignored .planning/ and is not present in CI.

describe("iconRegistry", () => {
  it("has 69 entries with a matching by-id map", () => {
    // 62 as of Batch 4c: +action.view (an eye, replacing the literal word "View" on an asset tile)
    // and +detail.datasheet-link (the document glyph that lets the datasheet row carry the same
    // anatomy as Filing). Deliberate re-baseline, which is what this gate is for.
    // 69 as of the 3D icon-chip move (+6 view/shading glyphs, 2026-07-26).
    // 63 as of the rail-collapse move: +nav.collapse-rail, replacing the raw mono guillemet that was
    // the only control in the app drawing its own text glyph instead of a registry icon.
    // The Projects frontend removal drops its two navigation glyphs and card thumbnail.
    expect(ICON_REGISTRY).toHaveLength(69);
    expect(ICON_BY_ID.size).toBe(69);
    for (const entry of ICON_REGISTRY) {
      expect(ICON_BY_ID.get(entry.id), entry.id).toBe(entry);
    }
  });

  it("has unique ids", () => {
    const ids = ICON_REGISTRY.map((entry) => entry.id);
    expect(new Set(ids).size).toBe(ids.length);
  });

  it("uses dot-namespaced ids (namespace.name)", () => {
    for (const entry of ICON_REGISTRY) {
      expect(entry.id, entry.id).toMatch(/^[a-z]+(\.[a-z0-9-]+)+$/);
    }
  });

  it("has the expected per-category counts (primary 30 / bespoke 33 / art 3 / brand 3)", () => {
    // primary 22 -> 23 with nav.collapse-rail, the panel glyph that replaced the rail's raw mono
    // guillemet when the collapse control moved into the wordmark bar. Deliberate re-baseline.
    const counts = ICON_REGISTRY.reduce<Record<string, number>>((acc, entry) => {
      acc[entry.category] = (acc[entry.category] ?? 0) + 1;
      return acc;
    }, {});
    expect(counts).toEqual({ primary: 30, bespoke: 33, art: 3, brand: 3 });
  });

  it("only uses the four declared categories", () => {
    for (const entry of ICON_REGISTRY) {
      expect(ICON_CATEGORIES, entry.id).toContain(entry.category);
    }
  });

  it("exports the four categories and a matching id grouping", () => {
    expect(ICON_CATEGORIES).toEqual(["primary", "bespoke", "art", "brand"]);
    const regrouped = ICON_CATEGORIES.flatMap((category) => ICON_IDS_BY_CATEGORY[category]);
    expect(regrouped.sort()).toEqual(ICON_REGISTRY.map((entry) => entry.id).sort());
  });

  it("keeps each category's ids in registry order, under keys in category order", () => {
    // The glyph picker renders these lists as they come, so inventory order is the contract - a
    // grouping that merely holds the right SET of ids would reshuffle the catalogue.
    expect(Object.keys(ICON_IDS_BY_CATEGORY)).toEqual(ICON_CATEGORIES);
    for (const category of ICON_CATEGORIES) {
      const inRegistryOrder = ICON_REGISTRY.filter((entry) => entry.category === category).map(
        (entry) => entry.id,
      );
      expect(ICON_IDS_BY_CATEGORY[category], category).toEqual(inRegistryOrder);
    }
  });

  it("gives every entry a non-empty body and viewBox", () => {
    for (const entry of ICON_REGISTRY) {
      expect(entry.body.length, entry.id).toBeGreaterThan(0);
      expect(entry.viewBox, entry.id).toMatch(/^0 0 \d+(\.\d+)? \d+(\.\d+)?$/);
    }
  });

  it("keeps primary entries on the shared preset (no bespoke root presentation)", () => {
    for (const entry of ICON_REGISTRY.filter((e) => e.category === "primary")) {
      expect(entry.viewBox, entry.id).toBe("0 0 24 24");
      expect(entry.strokeWidth, entry.id).toBeTypeOf("number");
      // The preset owns fill/stroke/caps/size; a primary entry must not restate them.
      expect(entry.size, entry.id).toBeUndefined();
      expect(entry.fill, entry.id).toBeUndefined();
      expect(entry.stroke, entry.id).toBeUndefined();
    }
  });

  it("routes the art glyphs' theme vars (the tint survives the lift)", () => {
    expect(ICON_BY_ID.get("art.symbol")?.body).toContain("var(--c-icon-line)");
    expect(ICON_BY_ID.get("art.footprint")?.body).toContain("var(--c-icon-fill)");
    expect(ICON_BY_ID.get("art.footprint")?.body).toContain("var(--c-icon-edge)");
    expect(ICON_BY_ID.get("art.model")?.style?.stroke).toBe("var(--c-icon-cube)");
    // The part-ready check keeps its --c-ok stroke tint.
    expect(ICON_BY_ID.get("detail.ready-check")?.stroke).toBe("var(--c-ok)");
  });
});
