import { describe, expect, it } from "vitest";
import type { DevModeDraft } from "../lib/devModeDraft";
import {
  BUILT_IN_VARIATIONS,
  DESIGN_DOCUMENT_SCHEMA_VERSION,
  parseDesignDocument,
  resolveDesign,
  type DesignDocument,
} from "./document";

function emptyDraft(): DevModeDraft {
  return {
    tokens: { root: {}, light: {} },
    copy: {},
    icons: {},
    elements: {},
    behaviors: {},
    layout: null,
  };
}

function fixtureDocument(): DesignDocument {
  return {
    schemaVersion: DESIGN_DOCUMENT_SCHEMA_VERSION,
    base: {
      ...emptyDraft(),
      tokens: { root: { "--c-accent": "base" }, light: {} },
      copy: { "rail.about": "Info" },
      icons: { "action.add": { swapToId: "action.edit" } },
      elements: { "component-browser.offers": { display: "flex" } },
      behaviors: { "detail.category-control": { preset: "dropdown" } },
    },
    variations: {
      "full-data": {
        id: "full-data",
        title: "Full Data",
        patch: {
          elements: { "component-browser.offers": { display: "block" } },
        },
      },
      purchasing: {
        id: "purchasing",
        title: "Purchasing",
        extends: "full-data",
        patch: {
          elements: { "component-browser.offers": { display: "grid" } },
        },
        themes: {
          dark: {
            elements: { "component-browser.offers": { opacity: "0.9" } },
          },
        },
      },
    },
    activeVariationId: "purchasing",
    targetScopes: {
      "component-browser.offers": "instance",
      "component-browser.offer-card": "role",
      "components": "screen",
      rail: "global",
    },
  };
}

describe("Design Studio document", () => {
  it("publishes the built-in presentation variations", () => {
    expect(BUILT_IN_VARIATIONS).toEqual([
      { id: "full-data", title: "Full Data" },
      { id: "compact", title: "Compact" },
      { id: "purchasing", title: "Purchasing" },
      { id: "cad-review", title: "CAD Review" },
      { id: "minimal", title: "Minimal" },
      { id: "custom", title: "Custom" },
    ]);
  });

  it("resolves shipped base, personal base, variation, theme, role, and instance in order", () => {
    const parsed = parseDesignDocument(fixtureDocument());
    if (!parsed.ok) throw new Error(parsed.error.message);

    expect(resolveDesign(parsed.document, "purchasing", "dark").elements["component-browser.offers"])
      .toEqual({ display: "grid", opacity: "0.9" });
    expect(parsed.document.targetScopes).toEqual({
      "component-browser.offers": "instance",
      "component-browser.offer-card": "role",
      components: "screen",
      rail: "global",
    });
  });

  it("migrates missing v1 slices to empty values without losing known overrides", () => {
    const result = parseDesignDocument({ schemaVersion: 1, base: { copy: { "rail.about": "Info" } } });

    expect(result.ok && result.document.base.layout).toBeNull();
    expect(result.ok && result.document.base.copy["rail.about"]).toBe("Info");
    expect(result.ok && result.document.base.tokens).toEqual({ root: {}, light: {} });
    expect(result.ok && result.document.variations).toEqual({});
  });

  it("treats prototype-named variation ids as absent unless they are own entries", () => {
    const active = parseDesignDocument({
      schemaVersion: 1,
      base: emptyDraft(),
      activeVariationId: "toString",
    });
    const parent = parseDesignDocument({
      schemaVersion: 1,
      base: emptyDraft(),
      variations: {
        child: { id: "child", title: "Child", extends: "toString", patch: {} },
      },
    });

    expect(active).toEqual({ ok: false, error: expect.objectContaining({ code: "unknown-active-variation" }) });
    expect(parent).toEqual({ ok: false, error: expect.objectContaining({ code: "missing-variation-parent" }) });
  });

  it("preserves an own __proto__ variation entry without changing dictionary membership", () => {
    const value = JSON.parse(`{
      "schemaVersion": 1,
      "base": { "tokens": { "root": {}, "light": {} }, "copy": {}, "icons": {}, "elements": {}, "behaviors": {}, "layout": null },
      "variations": { "__proto__": { "id": "__proto__", "title": "Prototype", "patch": { "copy": { "rail.about": "Info" } } } },
      "activeVariationId": "__proto__"
    }`);
    const result = parseDesignDocument(value);

    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(Object.prototype.hasOwnProperty.call(result.document.variations, "__proto__")).toBe(true);
    expect(resolveDesign(result.document, "__proto__", "dark").copy["rail.about"]).toBe("Info");
  });

  it("parses a nested layout document before resolution trusts it", () => {
    const layout = {
      schemaVersion: 1,
      id: "workspace",
      root: {
        kind: "region",
        id: "root",
        mode: "row",
        positioning: "free",
        grid: { columns: 4, rows: 3 },
        size: { fraction: 1, when: { narrow: { min: 240 } } },
        slots: [
          {
            kind: "slot",
            id: "main",
            content: {
              kind: "placement",
              id: "offers",
              piece: "component-browser.offers",
              size: { min: 120, width: 360, height: 180 },
              position: { x: 24, y: -16 },
              gridSlot: { column: 2, row: 3 },
              params: { page: 1, visible: true },
              styleRoles: { heading: "section" },
              visibility: { anyOf: ["offers.present"] },
              repeat: { over: "offers" },
            },
          },
        ],
      },
    };
    const result = parseDesignDocument({ schemaVersion: 1, base: { ...emptyDraft(), layout } });

    expect(result.ok && result.document.base.layout).toEqual(layout);
  });

  it.each([
    [
      {
        schemaVersion: 1,
        base: emptyDraft(),
        variations: { key: { id: "different", title: "Different", patch: {} } },
      },
      "duplicate-variation-id",
    ],
    [
      {
        schemaVersion: 1,
        base: emptyDraft(),
        variations: { child: { id: "child", title: "Child", extends: "missing", patch: {} } },
      },
      "missing-variation-parent",
    ],
    [{ schemaVersion: 1, base: emptyDraft(), variations: { bad: { id: "bad", title: "Bad", patch: [] } } }, "invalid-variation"],
    [
      {
        schemaVersion: 1,
        base: emptyDraft(),
        variations: { bad: { id: "bad", title: "Bad", patch: {}, themes: { sepia: {} } } },
      },
      "invalid-variation",
    ],
    [
      {
        schemaVersion: 1,
        base: {
          ...emptyDraft(),
          layout: {
            schemaVersion: 1,
            id: "workspace",
            root: {
              kind: "region",
              id: "root",
              mode: "row",
              slots: [{ kind: "slot", id: "slot", content: { kind: "not-a-node" } }],
            },
          },
        },
      },
      "invalid-layout",
    ],
  ])("returns %s as parse data", (value, code) => {
    expect(parseDesignDocument(value)).toEqual({ ok: false, error: expect.objectContaining({ code }) });
  });

  it("applies sparse patches and explicit deletions without mutating the document", () => {
    const document = fixtureDocument();
    document.variations.purchasing.patch = {
      tokens: { root: { "--c-accent": null } },
      copy: { "rail.about": null },
      icons: { "action.add": null },
      elements: { "component-browser.offers": { display: null, opacity: "0.9" } },
      behaviors: { "detail.category-control": null },
      layout: null,
    };
    const parsed = parseDesignDocument(document);
    if (!parsed.ok) throw new Error(parsed.error.message);

    const resolved = resolveDesign(parsed.document, "purchasing", "dark");
    resolved.elements["component-browser.offers"].opacity = "0.5";
    resolved.tokens.root["--c-new"] = "new";

    expect(resolved).toEqual({
      tokens: { root: { "--c-new": "new" }, light: {} },
      copy: {},
      icons: {},
      elements: { "component-browser.offers": { opacity: "0.5" } },
      behaviors: {},
      layout: null,
    });
    expect(parsed.document.base.tokens.root["--c-accent"]).toBe("base");
    expect(parsed.document.base.elements["component-browser.offers"]).toEqual({ display: "flex" });
  });

  it.each([
    [{ schemaVersion: 2, base: emptyDraft() }, "unsupported-schema-version"],
    [{ schemaVersion: 1, base: [], variations: {} }, "invalid-base"],
    [{ schemaVersion: 1, base: emptyDraft(), activeVariationId: "missing" }, "unknown-active-variation"],
    [
      {
        schemaVersion: 1,
        base: emptyDraft(),
        variations: { loop: { id: "loop", title: "Loop", extends: "loop", patch: {} } },
        activeVariationId: "loop",
      },
      "variation-inheritance-cycle",
    ],
    [
      {
        schemaVersion: 1,
        base: emptyDraft(),
        targetScopes: { rail: "account" },
      },
      "invalid-target-scope",
    ],
  ])("returns %s as parse data", (value, code) => {
    const result = parseDesignDocument(value);

    expect(result).toEqual({ ok: false, error: expect.objectContaining({ code }) });
  });
});
