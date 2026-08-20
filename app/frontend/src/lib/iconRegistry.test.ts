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
  it("uses one 24px outline grammar for every shipped interface and category icon", () => {
    const exceptions = new Set(["art.symbol", "art.footprint", "art.model", "brand.linkedin", "brand.github"]);
    const productIcons = ICON_REGISTRY.filter((entry) => !exceptions.has(entry.id));

    expect(productIcons.length).toBeGreaterThan(80);
    for (const entry of productIcons) {
      const sourced = entry as typeof entry & { family?: string; sourceIcon?: string };
      expect(["tabler-outline", "stockroom-electrical"], entry.id).toContain(sourced.family);
      expect(sourced.sourceIcon, entry.id).toMatch(/^[a-z0-9-]+$/);
      expect(entry.viewBox, entry.id).toBe("0 0 24 24");
      expect(entry.strokeWidth, entry.id).toBe(2);
      expect(entry.body, entry.id).not.toContain('fill="currentColor"');
      expect(entry.body, entry.id).not.toContain('stroke="none"');
    }

    const sources = productIcons.map((entry) =>
      (entry as typeof entry & { sourceIcon?: string }).sourceIcon,
    );
    expect(new Set(sources).size).toBe(sources.length);
  });

  it("registers every component-category mark in the same icon authority", () => {
    const expected = [
      "category.battery",
      "category.capacitor",
      "category.capacitor-polarized",
      "category.connector",
      "category.crystal",
      "category.diode",
      "category.fuse",
      "category.generic",
      "category.ic",
      "category.inductor",
      "category.lamp",
      "category.led",
      "category.motor",
      "category.opamp",
      "category.pushbutton",
      "category.resistor",
      "category.switch",
      "category.transformer",
      "category.transistor",
      "category.waveform",
    ];

    expect(expected.every((id) => ICON_BY_ID.has(id))).toBe(true);
  });

  it("has a matching by-id map", () => {
    expect(ICON_BY_ID.size).toBe(ICON_REGISTRY.length);
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

  it("has every declared category represented", () => {
    const counts = ICON_REGISTRY.reduce<Record<string, number>>((acc, entry) => {
      acc[entry.category] = (acc[entry.category] ?? 0) + 1;
      return acc;
    }, {});
    expect(counts.primary).toBeGreaterThan(80);
    expect(counts.bespoke).toBeGreaterThan(20);
    expect(counts).toMatchObject({ art: 3, brand: 3 });
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
      "nav.forward",
      "nav.projects",
      "nav.cad-assets",
      "action.show-provider",
      "action.import-files",
      "status.success",
      "status.error",
      "view.placement-auto",
      "relation.transition",
      "detail.offers",
      "status.loading",
      "document.project",
      "document.schematic",
      "document.pcb",
      "design.disclosure-open",
      "design.disclosure-closed",
      "design.drag",
      "design.resize",
      "settings.cad-tools",
      "settings.sources",
    ];
    for (const id of migrated) {
      expect(ICON_BY_ID.get(id), id).toMatchObject({ category: "primary", viewBox: "0 0 24 24" });
    }
  });

  it("does not reuse offer enrichment or close geometry for unrelated meanings", () => {
    const ids = ["action.enrich", "detail.offers", "view.placement-auto", "overlay.close", "status.error", "nav.up-to-date", "status.success"];
    const sources = ids.map((id) => ICON_BY_ID.get(id)?.sourceIcon);
    expect(sources.every(Boolean)).toBe(true);
    expect(new Set(sources).size).toBe(sources.length);
  });

  it("gives Design Studio navigation its own truthful palette mark", () => {
    expect(ICON_BY_ID.get("nav.design-studio")).toMatchObject({
      category: "primary",
      family: "tabler-outline",
      sourceIcon: "palette",
      viewBox: "0 0 24 24",
    });
    expect(ICON_BY_ID.get("nav.design-studio")?.sourceIcon)
      .not.toBe(ICON_BY_ID.get("nav.settings")?.sourceIcon);
  });

  it("gives Design Studio drawers truthful screen-layout and layer-stack marks", () => {
    expect(ICON_BY_ID.get("design.screens")).toMatchObject({
      category: "primary",
      family: "tabler-outline",
      sourceIcon: "layout-dashboard",
      viewBox: "0 0 24 24",
    });
    expect(ICON_BY_ID.get("design.layers")).toMatchObject({
      category: "primary",
      family: "tabler-outline",
      sourceIcon: "stack-2",
      viewBox: "0 0 24 24",
    });
    expect(ICON_BY_ID.get("design.screens")?.sourceIcon)
      .not.toBe(ICON_BY_ID.get("nav.components")?.sourceIcon);
    expect(ICON_BY_ID.get("design.layers")?.sourceIcon)
      .not.toBe(ICON_BY_ID.get("finder.filter")?.sourceIcon);
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
    expect(ICON_BY_ID.get("detail.ready-check")?.family).toBe("tabler-outline");
  });
});
