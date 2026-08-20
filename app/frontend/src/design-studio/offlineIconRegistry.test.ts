import { beforeEach, describe, expect, it, vi } from "vitest";

const loads = vi.hoisted(() => ({
  fontAwesome: 0,
  lucide: 0,
  phosphor: 0,
  material: 0,
}));

function collection(prefix: string) {
  return {
    prefix,
    width: 24,
    height: 24,
    icons: {
      shared: { body: '<path d="M2 12h20" />' },
    },
  };
}

vi.mock("./fontAwesomeRegistry", () => ({
  fontAwesomeEntries: () => {
    loads.fontAwesome += 1;
    return [{
      id: "font-awesome.regular.shared",
      label: "shared",
      family: "regular",
      terms: ["shared", "regular"],
      body: '<path d="M2 12h20" />',
      viewBox: "0 0 24 24",
    }];
  },
}));

vi.mock("@iconify-json/lucide/icons.json", () => {
  loads.lucide += 1;
  return { default: collection("lucide") };
});
vi.mock("@iconify-json/ph/icons.json", () => {
  loads.phosphor += 1;
  return { default: collection("ph") };
});
vi.mock("@iconify-json/material-symbols/icons.json", () => {
  loads.material += 1;
  return { default: collection("material-symbols") };
});

describe("offline icon registry loading boundary", () => {
  beforeEach(() => {
    Object.keys(loads).forEach((key) => { loads[key as keyof typeof loads] = 0; });
    vi.resetModules();
  });

  it("loads only the requested family and reuses that family's parsed catalogue", async () => {
    const registry = await import("./offlineIconRegistry");

    expect(loads).toEqual({ fontAwesome: 0, lucide: 0, phosphor: 0, material: 0 });

    const fontAwesome = await registry.loadOfflineIconCollections("Font Awesome");
    expect(fontAwesome.map((entry) => entry.id)).toEqual(["font-awesome.regular.shared"]);
    expect(loads).toEqual({ fontAwesome: 1, lucide: 0, phosphor: 0, material: 0 });
    expect(await registry.loadOfflineIconCollections("Font Awesome")).toBe(fontAwesome);
    expect(loads.fontAwesome).toBe(1);

    const lucide = await registry.loadOfflineIconCollections("Lucide");
    expect(lucide.map((entry) => entry.id)).toEqual(["lucide.shared"]);
    expect(loads).toEqual({ fontAwesome: 1, lucide: 1, phosphor: 0, material: 0 });
    expect(await registry.loadOfflineIconCollections("Lucide")).toBe(lucide);
    expect(loads.lucide).toBe(1);

    const phosphor = await registry.loadOfflineIconCollections("Phosphor");
    expect(phosphor.map((entry) => entry.id)).toEqual(["ph.shared"]);
    expect(phosphor).not.toBe(lucide);
    expect(loads).toEqual({ fontAwesome: 1, lucide: 1, phosphor: 1, material: 0 });
  });

  it("offers interface catalogues without bundled brand libraries", async () => {
    const registry = await import("./offlineIconRegistry");
    const fontAwesome = await registry.loadOfflineIconCollections("Font Awesome");
    const lucide = await registry.loadOfflineIconCollections("Lucide");
    const combined = [...fontAwesome, ...lucide];

    expect(registry.offlineIconFamilies()).toEqual([
      "Font Awesome",
      "Lucide",
      "Phosphor",
      "Material Symbols",
    ]);
    expect(registry.searchOfflineIcons("shared", "Font Awesome", combined).map((entry) => entry.id))
      .toEqual(["font-awesome.regular.shared"]);
    expect(registry.searchOfflineIcons("shared", "Lucide", combined).map((entry) => entry.id))
      .toEqual(["lucide.shared"]);
  });
});
