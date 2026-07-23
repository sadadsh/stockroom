import { existsSync, readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { describe, expect, it } from "vitest";
import {
  ICON_BY_ID,
  ICON_CATEGORIES,
  ICON_IDS_BY_CATEGORY,
  ICON_REGISTRY,
  type IconCategory,
} from "./iconRegistry";

// The inventory is the contract: the registry must cover exactly these ids with these categories.
interface InventoryIcon {
  id: string;
  source: string;
  description: string;
  category: IconCategory;
}
// Walk up from the working dir to the repo root to find the inventory (it lives outside app/frontend
// under .planning/, so it cannot be a relative module import within src/).
function findInventoryPath(): string {
  let dir = process.cwd();
  for (let i = 0; i < 8; i++) {
    const candidate = resolve(dir, ".planning/phases/02-icon-editor/icons.json");
    if (existsSync(candidate)) return candidate;
    const parent = dirname(dir);
    if (parent === dir) break;
    dir = parent;
  }
  throw new Error("icons.json inventory not found from " + process.cwd());
}
const inventory = JSON.parse(readFileSync(findInventoryPath(), "utf8")) as {
  icons: InventoryIcon[];
};

describe("iconRegistry", () => {
  it("has one entry per inventory icon (57 total)", () => {
    expect(inventory.icons).toHaveLength(57);
    expect(ICON_REGISTRY).toHaveLength(57);
    expect(ICON_BY_ID.size).toBe(57);
  });

  it("has unique ids", () => {
    const ids = ICON_REGISTRY.map((entry) => entry.id);
    expect(new Set(ids).size).toBe(ids.length);
  });

  it("uses dot-namespaced ids (namespace.name)", () => {
    for (const entry of ICON_REGISTRY) {
      expect(entry.id, entry.id).toMatch(/^[a-z]+(\.[a-z0-9-]+)+$/);
      expect(entry.id.includes("."), entry.id).toBe(true);
    }
  });

  it("covers exactly the inventory ids", () => {
    const registryIds = new Set(ICON_REGISTRY.map((entry) => entry.id));
    const inventoryIds = new Set(inventory.icons.map((icon) => icon.id));
    expect(registryIds).toEqual(inventoryIds);
  });

  it("matches every inventory icon's category", () => {
    for (const icon of inventory.icons) {
      const entry = ICON_BY_ID.get(icon.id);
      expect(entry, icon.id).toBeDefined();
      expect(entry?.category, icon.id).toBe(icon.category);
    }
  });

  it("has the expected per-category counts (primary 21 / bespoke 30 / art 3 / brand 3)", () => {
    const counts = ICON_REGISTRY.reduce<Record<string, number>>((acc, entry) => {
      acc[entry.category] = (acc[entry.category] ?? 0) + 1;
      return acc;
    }, {});
    expect(counts).toEqual({ primary: 21, bespoke: 30, art: 3, brand: 3 });
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
