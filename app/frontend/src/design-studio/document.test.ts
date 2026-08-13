import { describe, expect, it } from "vitest";
import type { DevModeDraft } from "../lib/devModeDraft";
import {
  BUILT_IN_VARIATIONS,
  builtInVariationDocument,
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
    globalTargets: {
      "component-browser.offers": { id: "component-browser.offers", identity: "authored" },
      "component-browser.offer-card": { id: "component-browser.offer-card", identity: "authored" },
      components: { id: "components", identity: "authored" },
      rail: { id: "rail", identity: "authored" },
    },
    orphanedEdits: {},
    cadPresentation: {},
  };
}

describe("Design Studio document", () => {
  it("migrates v1 scopes and unresolved edits into the global v2 document", () => {
    const parsed = parseDesignDocument({
      schemaVersion: 1,
      base: {
        ...emptyDraft(),
        elements: {
          "component-browser.offers": { display: "none" },
          "auto.legacy.0abc123": { width: "320px" },
        },
      },
      targetScopes: {
        "component-browser.offers": "screen",
        "auto.legacy.0abc123": "instance",
      },
    });

    expect(parsed.ok).toBe(true);
    if (!parsed.ok) return;
    expect(parsed.document.schemaVersion).toBe(2);
    expect(parsed.document).not.toHaveProperty("targetScopes");
    expect(parsed.document.globalTargets).toEqual({
      "component-browser.offers": {
        id: "component-browser.offers",
        identity: "authored",
      },
      "auto.legacy.0abc123": {
        id: "auto.legacy.0abc123",
        identity: "generated",
      },
    });
    expect(parsed.document.orphanedEdits).toEqual({});
  });

  it("preserves typed CAD presentation and orphan remapping metadata in v2", () => {
    const parsed = parseDesignDocument({
      schemaVersion: 2,
      base: emptyDraft(),
      cadPresentation: {
        "component-browser.cad-symbol": {
          symbol: { pins: false, names: true, stroke: "#c1c4c8" },
        },
      },
      globalTargets: {
        "component-browser.cad-symbol": {
          id: "component-browser.cad-symbol",
          identity: "authored",
          label: "Symbol Preview",
        },
      },
      orphanedEdits: {
        "auto.old.0abc123": {
          targetId: "auto.old.0abc123",
          lastKnownLabel: "Old Wrapper",
          remapTo: "component-browser.cad-symbol",
        },
      },
    });

    expect(parsed.ok && parsed.document.cadPresentation).toEqual({
      "component-browser.cad-symbol": {
        symbol: { pins: false, names: true, stroke: "#c1c4c8" },
      },
    });
    expect(parsed.ok && parsed.document.orphanedEdits["auto.old.0abc123"]?.remapTo)
      .toBe("component-browser.cad-symbol");
  });

  it("rejects remote or open-ended CAD presentation values", () => {
    for (const cadPresentation of [
      { "cad.symbol": { symbol: { stroke: "url(https://evil.invalid/a.svg)" } } },
      { "cad.footprint": { footprint: { layerColors: { copper: "red; display:none" } } } },
      { "cad.model3d": { model3d: { background: "url(https://evil.invalid/a.png)" } } },
      { "cad.model3d": { model3d: { material: "custom-script" } } },
    ]) {
      const parsed = parseDesignDocument({ schemaVersion: 2, base: emptyDraft(), cadPresentation });
      expect(parsed.ok).toBe(false);
      if (!parsed.ok) expect(parsed.error.code).toBe("invalid-cad-presentation");
    }
  });

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

  it("adds missing built-in variations when an existing v2 draft is upgraded", () => {
    const parsed = parseDesignDocument({
      schemaVersion: 2,
      base: emptyDraft(),
      variations: {
        "owner-view": { id: "owner-view", title: "Owner View", patch: {} },
      },
      activeVariationId: "owner-view",
    });

    expect(parsed.ok).toBe(true);
    if (!parsed.ok) return;
    expect(Object.keys(parsed.document.variations)).toEqual(expect.arrayContaining([
      "full-data", "compact", "purchasing", "cad-review", "minimal", "custom", "owner-view",
    ]));
    expect(parsed.document.activeVariationId).toBe("owner-view");
  });

  it("records state and internal-domain overrides under their owning global target", () => {
    const parsed = parseDesignDocument({
      schemaVersion: 2,
      base: {
        ...emptyDraft(),
        elements: {
          "detail.action::text": { color: "#111111" },
          "detail.action::state:hover": { color: "#222222" },
        },
      },
    });

    expect(parsed.ok).toBe(true);
    if (!parsed.ok) return;
    expect(Object.keys(parsed.document.globalTargets)).toContain("detail.action");
    expect(Object.keys(parsed.document.globalTargets)).not.toContain("detail.action::state:hover");
  });

  it("seeds all six named variations with closed inheritance", () => {
    const variations = builtInVariationDocument();

    expect(Object.values(variations).map(({ id, title }) => ({ id, title }))).toEqual(BUILT_IN_VARIATIONS);
    expect(variations.minimal?.extends).toBe("compact");
    expect(variations.custom?.extends).toBe("full-data");
    expect(parseDesignDocument({
      schemaVersion: 1,
      base: emptyDraft(),
      variations,
      activeVariationId: "full-data",
      targetScopes: {},
    }).ok).toBe(true);
  });

  it("resolves the personal base, variation, and theme in order", () => {
    const parsed = parseDesignDocument(fixtureDocument());
    if (!parsed.ok) throw new Error(parsed.error.message);

    expect(resolveDesign(parsed.document, "purchasing", "dark").elements["component-browser.offers"])
      .toEqual({ display: "grid", opacity: "0.9" });
    expect(Object.keys(parsed.document.globalTargets)).toEqual([
      "component-browser.offers",
      "detail.category-control",
      "component-browser.offer-card",
      "components",
      "rail",
    ]);
  });

  it("migrates missing v1 slices to empty values without losing known overrides", () => {
    const result = parseDesignDocument({ schemaVersion: 1, base: { copy: { "rail.about": "Info" } } });

    expect(result.ok && result.document.base.layout).toBeNull();
    expect(result.ok && result.document.base.copy["rail.about"]).toBe("Info");
    expect(result.ok && result.document.base.tokens).toEqual({ root: {}, light: {} });
    expect(result.ok && Object.keys(result.document.variations)).toEqual(
      BUILT_IN_VARIATIONS.map(({ id }) => id),
    );
  });

  it("preserves every approved icon presentation field through parsing", () => {
    const result = parseDesignDocument({
      schemaVersion: 1,
      base: {
        ...emptyDraft(),
        icons: {
          "action.add": {
            body: "<path d=\"M1 1h2\" />",
            swapToId: "action.edit",
            strokeWidth: 2.5,
            treatment: "muted",
            a11yLabel: "Add component",
            alignment: "text-top",
            insertInto: "auto.copy.0abc123",
            placement: "before",
          },
        },
      },
    });

    expect(result.ok && result.document.base.icons["action.add"]).toEqual({
      body: "<path d=\"M1 1h2\" />",
      swapToId: "action.edit",
      strokeWidth: 2.5,
      treatment: "muted",
      a11yLabel: "Add component",
      alignment: "text-top",
      insertInto: "auto.copy.0abc123",
      placement: "before",
    });
  });

  it("migrates missing built-ins into an existing personal document without replacing edits", () => {
    const result = parseDesignDocument({
      schemaVersion: 1,
      base: emptyDraft(),
      variations: {
        compact: {
          id: "compact",
          title: "My Compact",
          patch: { copy: { "rail.about": "Short" } },
        },
        review: {
          id: "review",
          title: "Review",
          extends: "full-data",
          patch: {},
        },
      },
      activeVariationId: "review",
    });

    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(Object.keys(result.document.variations)).toEqual([
      ...BUILT_IN_VARIATIONS.map(({ id }) => id),
      "review",
    ]);
    expect(result.document.variations.compact).toEqual({
      id: "compact",
      title: "My Compact",
      patch: { copy: { "rail.about": "Short" } },
    });
    expect(result.document.activeVariationId).toBe("review");
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

  it.each([
    ["variation patch", { patch: { layout: { schemaVersion: 1, id: "workspace", root: { kind: "html" } } } }],
    ["variation theme", { patch: {}, themes: { dark: { layout: { schemaVersion: 1, id: "workspace", root: { kind: "script" } } } } }],
  ])("directly rejects malformed layout in a %s", (_label, variationFields) => {
    const result = parseDesignDocument({
      schemaVersion: 1,
      base: emptyDraft(),
      variations: { bad: { id: "bad", title: "Bad", ...variationFields } },
    });
    expect(result).toEqual({ ok: false, error: expect.objectContaining({ code: "invalid-layout" }) });
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
      cadPresentation: {},
      layout: null,
    });
    expect(parsed.document.base.tokens.root["--c-accent"]).toBe("base");
    expect(parsed.document.base.elements["component-browser.offers"]).toEqual({ display: "flex" });
  });

  it.each([
    [{ schemaVersion: 3, base: emptyDraft() }, "unsupported-schema-version"],
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
