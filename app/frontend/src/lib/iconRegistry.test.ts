import { describe, expect, it } from "vitest";
import {
  ICON_BY_ID,
  ICON_CATEGORIES,
  ICON_IDS_BY_CATEGORY,
  ICON_REGISTRY,
} from "./iconRegistry";

// The registry is the single source of truth for product icons. These assertions lock its current
// source-owned shape without reaching outside src/ or depending on Design Studio runtime state.

describe("iconRegistry", () => {
  it("has 74 application icons with a matching by-id map", () => {
    // The deliberate re-baseline includes the reusable provider, preview, media, and Settings
    // semantics that replaced hand-drawn interface glyphs during the product-wide icon migration.
    expect(ICON_REGISTRY).toHaveLength(74);
    expect(ICON_BY_ID.size).toBe(74);
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

  it("has the expected per-category counts (primary 41 / bespoke 27 / art 3 / brand 3)", () => {
    // New reusable interface semantics stay primary so `.ico` owns their stroke and optical weight.
    const counts = ICON_REGISTRY.reduce<Record<string, number>>((acc, entry) => {
      acc[entry.category] = (acc[entry.category] ?? 0) + 1;
      return acc;
    }, {});
    expect(counts).toEqual({ primary: 41, bespoke: 27, art: 3, brand: 3 });
  });

  it("keeps migrated interface semantics on the shared 24px primary preset", () => {
    const migrated = [
      "action.measure",
      "action.maximize",
      "action.contract",
      "action.zoom-in",
      "action.zoom-out",
      "action.rotate",
      "media.photo",
      "detail.provider",
      "nav.assets",
      "settings.cad-tools",
      "settings.sources",
    ];
    for (const id of migrated) {
      expect(ICON_BY_ID.get(id), id).toMatchObject({ category: "primary", viewBox: "0 0 24 24" });
    }
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

  it("keeps the owner-selected interface artwork on stable semantic ids", () => {
    const selected = [
      "action.external",
      "brand.wordmark",
      "nav.about",
      "nav.board",
      "nav.collapse-rail",
      "nav.components",
      "nav.settings",
      "nav.stm",
      "nav.theme",
      "nav.update",
    ];
    for (const id of selected) {
      expect(ICON_BY_ID.get(id)?.body, id).toContain('fill="currentColor"');
      expect(ICON_BY_ID.get(id)?.body, id).toContain('stroke="none"');
    }
    const missing = ICON_BY_ID.get("status.cad-missing");
    expect(missing?.viewBox).toBe("0 0 512 512");
    expect(missing?.fill).toBe("currentColor");
    expect(missing?.body).toContain("M256 512");
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
