import { describe, expect, it } from "vitest";
import {
  ICON_BY_ID,
  ICON_CATEGORIES,
  ICON_IDS_BY_CATEGORY,
  ICON_REGISTRY,
} from "./iconRegistry";

// The registry is the single source of truth for the icon set (lifted from the blueprint inventory of
// 57 icons: primary 21, bespoke 30, art 3, brand 3). These assertions lock its shape without reaching
// outside src/ - the inventory JSON lives under the gitignored .planning/ and is not present in CI.

describe("iconRegistry", () => {
  it("has 57 entries with a matching by-id map", () => {
    expect(ICON_REGISTRY).toHaveLength(57);
    expect(ICON_BY_ID.size).toBe(57);
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

  it("has the expected per-category counts (primary 21 / bespoke 30 / art 3 / brand 3)", () => {
    const counts = ICON_REGISTRY.reduce<Record<string, number>>((acc, entry) => {
      acc[entry.category] = (acc[entry.category] ?? 0) + 1;
      return acc;
    }, {});
    expect(counts).toEqual({ primary: 21, bespoke: 30, art: 3, brand: 3 });
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
