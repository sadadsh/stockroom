/**
 * Structure: the two registry-aware checks, against the shipped arrangement and against fixtures
 * broken in exactly one way each.
 *
 * The anchor is the shipped pair - no manifest states a minimum today and no placed piece fights
 * another for a scroll axis, so the workspace produces nothing. Because a silent check is also what
 * a broken check looks like, every other test here drives the check to FIRE from a fixture that
 * differs from a passing one in one number or one flag.
 */
import { describe, expect, it } from "vitest";
import { DEFAULT_WORKSPACE_LAYOUT } from "./defaultWorkspaceLayout";
import type { LayoutDocument, LayoutRegion, PiecePlacement } from "./document";
import { registerPieces, type PieceManifest } from "./registry";
import { validateStructure } from "./validateStructure";
import { WORKSPACE_PIECE_REGISTRY } from "./workspacePieces";

function manifest(overrides: Partial<PieceManifest> & { id: string }): PieceManifest {
  return {
    devIds: [],
    dataNeeds: [],
    actions: [],
    scroll: { owns: false },
    home: { regionId: "r", siblingGroup: "g" },
    source: "test",
    ...overrides,
  };
}

function document(root: LayoutRegion): LayoutDocument {
  return { schemaVersion: 1, id: "test.document", root };
}

/** A row band holding one column region, which holds one placement. The width case. */
function widthFixture(
  columnSize: LayoutRegion["size"],
  placement: Partial<PiecePlacement> = {},
): LayoutDocument {
  return document({
    kind: "region",
    id: "band",
    mode: "row",
    slots: [
      {
        kind: "slot",
        id: "band.slot",
        content: {
          kind: "region",
          id: "column",
          mode: "column",
          size: columnSize,
          slots: [
            {
              kind: "slot",
              id: "column.slot",
              content: { kind: "placement", id: "place.wide", piece: "piece.wide", ...placement },
            },
          ],
        },
      },
    ],
  });
}

const wideRegistry = registerPieces([manifest({ id: "piece.wide", minWidth: 400 })]).registry;

describe("the shipped arrangement", () => {
  it("reports nothing structural the registry can see", () => {
    // THE ANCHOR. No workspace manifest states a min size, so the size check has nothing to compare;
    // the two pieces that own a scroll axis own a HORIZONTAL one inside a column that stacks
    // vertically, which is the shipped design rather than a conflict.
    expect(validateStructure(DEFAULT_WORKSPACE_LAYOUT, WORKSPACE_PIECE_REGISTRY)).toEqual([]);
  });

  it("is silent for the stated reason rather than by accident", () => {
    // Guards the anchor. If a manifest gained a min size, or a second piece started owning the
    // vertical axis, the anchor above would be asserting something different from what it says.
    const manifests = WORKSPACE_PIECE_REGISTRY.list();
    expect(manifests.length).toBeGreaterThan(20);
    expect(manifests.filter((m) => m.minWidth !== undefined || m.minHeight !== undefined)).toEqual([]);
    const scrollers = manifests.filter((m) => m.scroll.owns);
    expect(scrollers.map((m) => m.id)).toEqual([
      "workspace.sourcing-provenance",
    ]);
    expect(scrollers.every((m) => m.scroll.axis === "horizontal")).toBe(true);
  });
});

describe("a piece below its minimum", () => {
  it("warns when the floor its column guarantees is under what the manifest states", () => {
    // Killing mutation: compare against the region's `fraction` or its `preferred` instead of its
    // `min`. A fraction is where a column OPENS; the floor is how small it can be dragged, and the
    // floor is what decides whether the piece ever fits.
    const issues = validateStructure(widthFixture({ min: 260 }), wideRegistry);
    expect(issues).toHaveLength(1);
    expect(issues[0].code).toBe("piece-below-minimum");
    expect(issues[0].severity).toBe("warning");
    expect(issues[0].subject).toEqual({ kind: "placement", id: "place.wide" });
    expect(issues[0].detail).toEqual({
      axis: "width",
      piece: "piece.wide",
      minimum: 400,
      floor: 260,
      from: "column",
    });
  });

  it("says nothing when the floor is wide enough", () => {
    expect(validateStructure(widthFixture({ min: 400 }), wideRegistry)).toEqual([]);
  });

  it("invents no floor when the document states none", () => {
    // "Only where both sides state numbers." Killing mutation: default a missing `min` to 0. Every
    // piece with a stated minimum would then warn in every arrangement, which is a validator that
    // reports its own default rather than the design.
    expect(validateStructure(widthFixture({ fraction: 0.3 }), wideRegistry)).toEqual([]);
    expect(validateStructure(widthFixture(undefined), wideRegistry)).toEqual([]);
  });

  it("invents no minimum when the manifest states none", () => {
    const registry = registerPieces([manifest({ id: "piece.wide" })]).registry;
    expect(validateStructure(widthFixture({ min: 10 }), registry)).toEqual([]);
  });

  it("takes the SMALLEST floor a condition can put the region at, and names the condition", () => {
    // The sourcing column's real shape: 300 normally, 220 under `workspace.sparse-sourcing`. A piece
    // needing 260 fits the resting arrangement and not the sparse one, and the sparse one is a state
    // the reader reaches on any part nobody has sourced.
    //
    // Killing mutation: read `size.min` and ignore `size.when`. This fixture would then pass while
    // the piece is squeezed on every sparse component.
    const registry = registerPieces([manifest({ id: "piece.wide", minWidth: 260 })]).registry;
    const issues = validateStructure(
      widthFixture({ min: 300, when: { "workspace.sparse-sourcing": { min: 220 } } }),
      registry,
    );
    expect(issues).toHaveLength(1);
    expect(issues[0].detail).toEqual({
      axis: "width",
      piece: "piece.wide",
      minimum: 260,
      floor: 220,
      from: "column",
      condition: "workspace.sparse-sourcing",
    });
  });

  it("reads a floor on the axis its parent actually sizes", () => {
    // `AxisSize.min` is stated in the PARENT's terms, so the same 260 is a width inside a row and a
    // height inside a column. Killing mutation: treat every `min` as a width. The height fixture
    // below would then report a width warning that no arrangement produces.
    const registry = registerPieces([manifest({ id: "piece.tall", minHeight: 400 })]).registry;
    const tall = document({
      kind: "region",
      id: "stack",
      mode: "column",
      slots: [
        {
          kind: "slot",
          id: "stack.slot",
          content: {
            kind: "region",
            id: "band",
            mode: "row",
            size: { min: 100 },
            slots: [
              {
                kind: "slot",
                id: "band.slot",
                content: { kind: "placement", id: "place.tall", piece: "piece.tall" },
              },
            ],
          },
        },
      ],
    });
    const issues = validateStructure(tall, registry);
    expect(issues).toHaveLength(1);
    expect(issues[0].detail?.axis).toBe("height");
    expect(issues[0].detail?.floor).toBe(100);
  });

  it("lets the nearest stated floor govern, not the outermost", () => {
    // Killing mutation: take the minimum over every ancestor. An outer band's generous floor cannot
    // rescue an inner column that is pinned narrow, and an outer TIGHT floor is not what squeezes a
    // piece whose own column states a wider one.
    const nested = document({
      kind: "region",
      id: "outer",
      mode: "row",
      slots: [
        {
          kind: "slot",
          id: "outer.slot",
          content: {
            kind: "region",
            id: "column",
            mode: "row",
            size: { min: 120 },
            slots: [
              {
                kind: "slot",
                id: "column.slot",
                content: {
                  kind: "placement",
                  id: "place.wide",
                  piece: "piece.wide",
                  size: { min: 500 },
                },
              },
            ],
          },
        },
      ],
    });
    // The placement's own floor is 500, which clears its manifest's 400, so nothing is reported even
    // though the column around it states 120.
    expect(validateStructure(nested, wideRegistry)).toEqual([]);
  });

  it("skips a hidden placement", () => {
    // A piece that is not on screen is not too small. Killing mutation: drop the `hidden` test.
    expect(validateStructure(widthFixture({ min: 100 }, { hidden: true }), wideRegistry)).toEqual([]);
  });

  it("skips a piece no registry knows, which validateLayout already reports", () => {
    const unknown = registerPieces([manifest({ id: "piece.other", minWidth: 400 })]).registry;
    expect(validateStructure(widthFixture({ min: 10 }), unknown)).toEqual([]);
  });
});

describe("a scroll conflict a placement causes", () => {
  const scroller = (id: string, axis: "vertical" | "horizontal") =>
    manifest({ id, scroll: { owns: true, axis } });

  const twoPieces = (mode: LayoutRegion["mode"], regionScroll?: LayoutRegion["scroll"]) =>
    document({
      kind: "region",
      id: "body",
      mode,
      scroll: regionScroll,
      slots: [
        { kind: "slot", id: "s1", content: { kind: "placement", id: "p1", piece: "piece.v" } },
        { kind: "slot", id: "s2", content: { kind: "placement", id: "p2", piece: "piece.v2" } },
      ],
    });

  it("warns when two pieces own the axis their region stacks them along", () => {
    // Killing mutation: read scroll ownership off the REGION only, which is all `validateLayout`
    // can see. A piece's scroll lives in its manifest and no structural check reaches it.
    const registry = registerPieces([scroller("piece.v", "vertical"), scroller("piece.v2", "vertical")]).registry;
    const issues = validateStructure(twoPieces("column"), registry);
    expect(issues).toHaveLength(1);
    expect(issues[0].code).toBe("piece-scroll-conflict");
    expect(issues[0].subject).toEqual({ kind: "region", id: "body" });
    expect(issues[0].detail).toEqual({ axis: "vertical", owners: "p1 p2", shape: "siblings" });
  });

  it("says nothing about two pieces scrolling ACROSS the axis their region stacks", () => {
    // THE SHIPPED SHAPE, and the judgement this check would be worthless without: the offers table
    // and the provenance ledger both scroll sideways inside one vertical column, because four
    // columns of named facts do not fit a 300px column.
    //
    // Killing mutation: warn on any two pieces sharing any axis. The shipped document would then
    // carry a permanent warning, and the anchor at the top of this file would fail.
    const registry = registerPieces([
      scroller("piece.v", "horizontal"),
      scroller("piece.v2", "horizontal"),
    ]).registry;
    expect(validateStructure(twoPieces("column"), registry)).toEqual([]);
  });

  it("warns on either axis inside a stack, where children share one footprint", () => {
    const registry = registerPieces([
      scroller("piece.v", "horizontal"),
      scroller("piece.v2", "horizontal"),
    ]).registry;
    const issues = validateStructure(twoPieces("stack"), registry);
    expect(issues.map((i) => i.detail?.axis)).toEqual(["horizontal"]);
  });

  it("warns when a piece owns an axis its own region also owns", () => {
    // Nested scrollers on one axis: the outer container decides which of them the wheel reaches, and
    // the arrangement cannot say which. Killing mutation: only compare siblings.
    const registry = registerPieces([scroller("piece.v", "vertical"), manifest({ id: "piece.v2" })]).registry;
    const issues = validateStructure(twoPieces("column", "vertical"), registry);
    expect(issues).toHaveLength(1);
    expect(issues[0].detail).toEqual({ axis: "vertical", owners: "p1", shape: "nested" });
  });

  it("warns on nesting even across the region's stacking axis", () => {
    // A column that scrolls sideways with a piece inside it that also scrolls sideways is the same
    // wheel-chaining problem, and it is NOT caught by the sibling rule.
    const registry = registerPieces([scroller("piece.v", "horizontal"), manifest({ id: "piece.v2" })]).registry;
    const issues = validateStructure(twoPieces("column", "horizontal"), registry);
    expect(issues.map((i) => i.detail?.shape)).toEqual(["nested"]);
  });

  it("skips a hidden scroller", () => {
    const registry = registerPieces([scroller("piece.v", "vertical"), scroller("piece.v2", "vertical")]).registry;
    const hidden = document({
      kind: "region",
      id: "body",
      mode: "column",
      slots: [
        { kind: "slot", id: "s1", content: { kind: "placement", id: "p1", piece: "piece.v", hidden: true } },
        { kind: "slot", id: "s2", content: { kind: "placement", id: "p2", piece: "piece.v2" } },
      ],
    });
    expect(validateStructure(hidden, registry)).toEqual([]);
  });
});
