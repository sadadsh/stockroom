/**
 * The layout document's tree walk and its validator.
 *
 * Every test here is written against a hand-built fixture rather than against the shipped default
 * document, because a validator has to be shown FAILING to be worth anything: there is one fixture
 * per issue code, each broken in exactly one way, and each names the mutation to the validator that
 * would make it pass silently.
 */
import { describe, expect, it } from "vitest";
import {
  findLayoutNode,
  findPlacement,
  findRegion,
  findSlot,
  layoutPlacements,
  LAYOUT_SCHEMA_VERSION,
  placedPieceIds,
  validateLayout,
  walkLayout,
  type LayoutDocument,
  type LayoutRegion,
  type PieceLookup,
  type RegionLayoutMode,
} from "./document";

/** A registry that knows everything, and one that knows nothing. */
const KNOWS_ALL: PieceLookup = { has: () => true };
const KNOWS_NOTHING: PieceLookup = { has: () => false };

function documentOf(root: LayoutRegion): LayoutDocument {
  return { schemaVersion: LAYOUT_SCHEMA_VERSION, id: "fixture", root };
}

/** Two pieces in a column, one of them placed twice. Structurally clean. */
function cleanDocument(): LayoutDocument {
  return documentOf({
    kind: "region",
    id: "root",
    mode: "column",
    slots: [
      {
        kind: "slot",
        id: "slot.top",
        content: { kind: "placement", id: "place.top", piece: "piece.alpha" },
      },
      {
        kind: "slot",
        id: "slot.bottom",
        content: {
          kind: "region",
          id: "inner",
          mode: "row",
          scroll: "vertical",
          slots: [
            {
              kind: "slot",
              id: "slot.left",
              content: { kind: "placement", id: "place.left", piece: "piece.beta" },
            },
            {
              kind: "slot",
              id: "slot.right",
              content: { kind: "placement", id: "place.right", piece: "piece.alpha" },
            },
          ],
        },
      },
    ],
  });
}

function codes(document: LayoutDocument, registry?: PieceLookup): string[] {
  return validateLayout(document, registry).map((issue) => issue.code);
}

describe("walking a layout document", () => {
  it("visits every node once, in document order, with its path", () => {
    // Fails if the walk skips slots, reorders siblings, or stops descending into nested regions.
    const visits = walkLayout(cleanDocument());
    expect(visits.map((visit) => visit.node.id)).toEqual([
      "root",
      "slot.top",
      "place.top",
      "slot.bottom",
      "inner",
      "slot.left",
      "place.left",
      "slot.right",
      "place.right",
    ]);
    const left = visits.find((visit) => visit.node.id === "place.left");
    expect(left?.path).toEqual(["root", "slot.bottom", "inner", "slot.left", "place.left"]);
    expect(left?.parentRegionId).toBe("inner");
    expect(left?.slotId).toBe("slot.left");
  });

  it("finds a region, a slot and a placement by id, and nothing by an unknown id", () => {
    const document = cleanDocument();
    expect(findRegion(document, "inner")?.mode).toBe("row");
    expect(findSlot(document, "slot.right")?.kind).toBe("slot");
    expect(findPlacement(document, "place.left")?.piece).toBe("piece.beta");
    expect(findLayoutNode(document, "slot.top")?.kind).toBe("slot");
    // A finder that ignored the node kind would return the slot for `findRegion`.
    expect(findRegion(document, "slot.top")).toBeNull();
    expect(findPlacement(document, "nobody")).toBeNull();
  });

  it("lists each placed piece once, however many times it is placed", () => {
    // `piece.alpha` is placed twice. Fails if `placedPieceIds` returns placements rather than
    // pieces, or if it loses the second distinct piece.
    const document = cleanDocument();
    expect(layoutPlacements(document)).toHaveLength(3);
    expect(placedPieceIds(document)).toEqual(["piece.alpha", "piece.beta"]);
  });

  it("terminates on a document that contains itself", () => {
    // A cycle cannot be authored, but it can arrive from a bad merge or an editor mid-drag. Fails
    // by hanging or overflowing the stack if the walk's visited-set guard is removed.
    const root: LayoutRegion = {
      kind: "region",
      id: "root",
      mode: "column",
      slots: [{ kind: "slot", id: "slot.self", content: null }],
    };
    root.slots[0].content = root;
    const visits = walkLayout(documentOf(root));
    expect(visits.map((visit) => visit.node.id)).toEqual(["root", "slot.self"]);
  });
});

describe("validating a layout document", () => {
  it("reports nothing about a clean document, with or without a registry", () => {
    // The control. Fails the moment a check starts firing on a structurally sound tree.
    expect(validateLayout(cleanDocument())).toEqual([]);
    expect(validateLayout(cleanDocument(), KNOWS_ALL)).toEqual([]);
  });

  it("reports a schema version it was not written for", () => {
    // Fails if the version check is dropped, or compares against something other than the constant.
    const document = { ...cleanDocument(), schemaVersion: LAYOUT_SCHEMA_VERSION + 1 };
    const issues = validateLayout(document);
    expect(issues.map((issue) => issue.code)).toEqual(["unsupported-schema-version"]);
    expect(issues[0].detail).toEqual({
      found: LAYOUT_SCHEMA_VERSION + 1,
      expected: LAYOUT_SCHEMA_VERSION,
    });
  });

  it("reports a layout mode that is not one of the three", () => {
    // Fails if the mode is trusted because it typechecks; a document arrives from JSON, where it
    // does not.
    const document = cleanDocument();
    const inner = findRegion(document, "inner");
    inner!.mode = "grid" as unknown as RegionLayoutMode;
    const issues = validateLayout(document);
    expect(issues.map((issue) => issue.code)).toEqual(["unknown-layout-mode"]);
    expect(issues[0].nodeId).toBe("inner");
    expect(issues[0].detail).toEqual({ mode: "grid" });
  });

  it("reports two nodes that share an id", () => {
    // An override is keyed on an id, so two nodes sharing one is two nodes taking one edit. Fails
    // if the id set is not carried across the whole walk.
    const document = cleanDocument();
    findSlot(document, "slot.right")!.id = "slot.left";
    const issues = validateLayout(document);
    expect(issues.map((issue) => issue.code)).toEqual(["duplicate-id"]);
    expect(issues[0].nodeId).toBe("slot.left");
    expect(issues[0].detail).toEqual({ kind: "slot" });
  });

  it("reports a slot holding nothing", () => {
    // Fails if an empty slot is treated as a legal gap rather than as something to say out loud.
    const document = cleanDocument();
    findSlot(document, "slot.top")!.content = null;
    const issues = validateLayout(document);
    expect(issues.map((issue) => issue.code)).toEqual(["orphan-slot"]);
    expect(issues[0].nodeId).toBe("slot.top");
    expect(issues[0].detail).toEqual({ region: "root" });
  });

  it("reports a placement naming a piece the registry does not know, and only when asked", () => {
    // Fails if the piece check runs without a registry (every document would be broken) or if it
    // is skipped when one is supplied (the coverage gate would pass on a dangling reference).
    const document = cleanDocument();
    expect(codes(document)).toEqual([]);
    const issues = validateLayout(document, KNOWS_NOTHING);
    expect(issues.map((issue) => issue.code)).toEqual([
      "unknown-piece",
      "unknown-piece",
      "unknown-piece",
    ]);
    expect(issues[0].detail).toEqual({ piece: "piece.alpha" });
  });

  it("reports a splitter naming a slot outside its own region", () => {
    // A splitter is a contract between two of one region's slots. Fails if `between` is not checked
    // against the region's own slot ids.
    const document = cleanDocument();
    findRegion(document, "inner")!.splitters = [
      {
        id: "split.one",
        between: ["slot.left", "slot.top"],
        keyStep: 16,
        lineThickness: 1,
        grabWidth: 9,
      },
    ];
    const issues = validateLayout(document);
    expect(issues.map((issue) => issue.code)).toEqual(["splitter-unknown-slot"]);
    // `slot.top` exists in the document, just not in this region - which is the whole point.
    expect(issues[0].detail).toEqual({ slot: "slot.top", region: "inner" });
  });

  it("reports two scroll owners stacked along the axis they both scroll", () => {
    // Fails if the check counts scroll owners without regard to the axis the parent stacks along.
    const scroller = (id: string): LayoutRegion => ({
      kind: "region",
      id,
      mode: "column",
      scroll: "vertical",
      slots: [],
    });
    const stacked = documentOf({
      kind: "region",
      id: "root",
      mode: "column",
      slots: [
        { kind: "slot", id: "slot.a", content: scroller("upper") },
        { kind: "slot", id: "slot.b", content: scroller("lower") },
      ],
    });
    const issues = validateLayout(stacked);
    expect(issues.map((issue) => issue.code)).toEqual(["scroll-owner-conflict"]);
    expect(issues[0].detail).toEqual({ axis: "vertical", owners: "upper lower" });
  });

  it("does not report two vertical scrollers side by side in a row", () => {
    // The workspace's own arrangement: three columns, three scrollbars, no conflict. Fails if the
    // scroll check is written as "no two scrollers in one region", which would condemn the shipped
    // layout and be weakened away the first time it did.
    const scroller = (id: string): LayoutRegion => ({
      kind: "region",
      id,
      mode: "column",
      scroll: "vertical",
      slots: [],
    });
    const sideBySide = documentOf({
      kind: "region",
      id: "root",
      mode: "row",
      slots: [
        { kind: "slot", id: "slot.a", content: scroller("left") },
        { kind: "slot", id: "slot.b", content: scroller("right") },
      ],
    });
    expect(validateLayout(sideBySide)).toEqual([]);
  });

  it("reports rather than throws on a document broken every way at once", () => {
    // The warn-never-block contract. Fails if any check throws instead of reporting, which is what
    // would take the editor down on the first bad drag.
    const broken: LayoutDocument = {
      schemaVersion: 99,
      id: "broken",
      root: {
        kind: "region",
        id: "root",
        mode: "sideways" as unknown as RegionLayoutMode,
        splitters: [
          {
            id: "split.nowhere",
            between: ["missing.one", "missing.two"],
            keyStep: 16,
            lineThickness: 1,
            grabWidth: 9,
          },
        ],
        slots: [
          { kind: "slot", id: "slot.same", content: null },
          {
            kind: "slot",
            id: "slot.same",
            content: { kind: "placement", id: "place", piece: "piece.nobody-registered" },
          },
        ],
      },
    };
    const found = codes(broken, KNOWS_NOTHING);
    expect(found).toContain("unsupported-schema-version");
    expect(found).toContain("unknown-layout-mode");
    expect(found).toContain("duplicate-id");
    expect(found).toContain("orphan-slot");
    expect(found).toContain("unknown-piece");
    expect(found).toContain("splitter-unknown-slot");
  });
});
