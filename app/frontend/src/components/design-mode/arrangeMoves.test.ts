/**
 * WHAT A GESTURE MEANS, asserted without a pointer.
 *
 * These are the functions the drag, the arrow keys and the piece menu all go through, so a claim
 * proven here is proven for all three paths at once - which is the reason they are one module. The
 * surface test next door proves the WIRING (this handler calls that function); this proves the
 * ANSWER (dropping the third section above the first produces the order a person meant), which is
 * the half a jsdom drag simulation cannot reach.
 *
 * NON-VACUITY. Every case names the mutation that turns it red, and three were run for real and
 * reverted - see the block above each. The two known vacuous shapes do not apply: nothing here reads
 * source text, and nothing waits on an effect. Every expectation is a whole slot order compared
 * against a whole slot order, so a function that returned its input unchanged fails rather than
 * passing by finding nothing wrong.
 */
import { describe, it, expect } from "vitest";
import {
  layoutPlacements,
  validateLayout,
  type LayoutDocument,
  type LayoutRegion,
  type LayoutSlot,
  type PiecePlacement,
} from "../../layout/document";
import { DEFAULT_WORKSPACE_LAYOUT } from "../../layout/defaultWorkspaceLayout";
import { WORKSPACE_PIECE_REGISTRY, WORKSPACE_REGION } from "../../layout/workspacePieces";
import {
  arrangeRegionChoices,
  canStepPlacement,
  dropPlacement,
  movePlacementIntoRegion,
  placementSeat,
  stepPlacement,
} from "./arrangeMoves";

/* -------------------------------------------------------------------------- */

function place(id: string, piece: string): PiecePlacement {
  return { kind: "placement", id, piece };
}

function slot(id: string, content: LayoutRegion | PiecePlacement): LayoutSlot {
  return { kind: "slot", id, content };
}

function column(id: string, placementIds: readonly string[]): LayoutRegion {
  return {
    kind: "region",
    id,
    mode: "column",
    slots: placementIds.map((placementId) =>
      slot(`slot.${placementId}`, place(placementId, `piece.${placementId}`)),
    ),
  };
}

/** Two regions side by side, so a move ACROSS one is testable as easily as a move inside one. */
function twoColumnDocument(): LayoutDocument {
  return {
    schemaVersion: 1,
    id: "test.two-columns",
    root: {
      kind: "region",
      id: "root",
      mode: "row",
      slots: [
        slot("slot.left", column("left", ["a", "b", "c"])),
        slot("slot.right", column("right", ["x", "y"])),
      ],
    },
  };
}

/** The placement ids a region holds, in order: the whole of what a move is judged on. */
function order(document: LayoutDocument, regionId: string): string[] {
  return layoutPlacements(document)
    .filter((visit) => visit.parentRegionId === regionId)
    .map((visit) => visit.node.id);
}

/* -------------------------------------------------------------------------- */
/*  where a placement sits                                                     */
/* -------------------------------------------------------------------------- */

describe("a placement's seat", () => {
  it("names the slot, the region and the position, for the shipped arrangement too", () => {
    const seat = placementSeat(DEFAULT_WORKSPACE_LAYOUT, "workspace.place.sourcing-documents");
    expect(seat?.slotId).toBe("workspace.slot.sourcing-documents");
    expect(seat?.regionId).toBe(WORKSPACE_REGION.sourcingBody);
    // Read off the document rather than written out: the sourcing body's order is the column's, and
    // a number typed here would be a second copy of it.
    expect(seat?.index).toBe(
      order(DEFAULT_WORKSPACE_LAYOUT, WORKSPACE_REGION.sourcingBody).indexOf(
        "workspace.place.sourcing-documents",
      ),
    );
    expect(seat?.slotCount).toBeGreaterThan(1);
  });

  /**
   * FAILS IF: `placementSeat` falls back to resolving a PIECE id the way `editOperations`' looser
   * `PlacementRef` does. A handle is drawn per placement and the three CAD modules are three
   * placements of one piece, so a piece id names no single seat and must name none.
   */
  it("resolves a placement id only, never a piece id", () => {
    expect(placementSeat(DEFAULT_WORKSPACE_LAYOUT, "workspace.cad-asset-module")).toBeNull();
    expect(placementSeat(DEFAULT_WORKSPACE_LAYOUT, "workspace.status-bar")).toBeNull();
    expect(placementSeat(DEFAULT_WORKSPACE_LAYOUT, "nobody")).toBeNull();
  });
});

/* -------------------------------------------------------------------------- */
/*  stepping                                                                   */
/* -------------------------------------------------------------------------- */

describe("stepping a placement one position", () => {
  /**
   * FAILS IF: the step is computed against the slot order BEFORE the moved slot is taken out of it,
   * which is the classic off-by-one - moving down then lands the placement back where it started
   * and the order comes out unchanged.
   *
   * PROVEN NON-VACUOUS: changing `stepPlacement`'s target index from `seat.index + direction` to
   * `seat.index` made the downward case return `a b c` instead of `b a c`; reverted.
   */
  it("moves one position each way, in the region's own order", () => {
    const start = twoColumnDocument();
    expect(order(stepPlacement(start, "a", 1), "left")).toEqual(["b", "a", "c"]);
    expect(order(stepPlacement(start, "c", -1), "left")).toEqual(["a", "c", "b"]);
    // Twice down from the top is the bottom, which is what proves the step is a step and not a swap
    // with a fixed neighbour.
    const twice = stepPlacement(stepPlacement(start, "a", 1), "a", 1);
    expect(order(twice, "left")).toEqual(["b", "c", "a"]);
    // The other region never moves. A step is inside one region by definition.
    expect(order(twice, "right")).toEqual(["x", "y"]);
  });

  /**
   * FAILS IF: a step off either end wraps around, or produces a document at all. Warn-never-block
   * degrades to nothing happening, and the surface reads the BY-REFERENCE identity to know a move
   * was not available - so returning an equal-but-new document would silently push a no-op onto the
   * undo stack for every key press at the end of a column.
   */
  it("refuses to step off either end, by reference", () => {
    const start = twoColumnDocument();
    expect(stepPlacement(start, "a", -1)).toBe(start);
    expect(stepPlacement(start, "c", 1)).toBe(start);
    expect(stepPlacement(start, "nobody", 1)).toBe(start);
    expect(canStepPlacement(start, "a", -1)).toBe(false);
    expect(canStepPlacement(start, "a", 1)).toBe(true);
    expect(canStepPlacement(start, "c", 1)).toBe(false);
    expect(canStepPlacement(start, "nobody", -1)).toBe(false);
  });
});

/* -------------------------------------------------------------------------- */
/*  dropping                                                                   */
/* -------------------------------------------------------------------------- */

describe("dropping a placement beside another", () => {
  /**
   * THE CASE THE ANCHOR MATHS EXISTS FOR. Dragging the FIRST section below the LAST has to count the
   * siblings it passed; an index taken before the moved slot left its region counts one too many and
   * the section lands second-from-bottom.
   *
   * FAILS IF: `dropPlacement` resolves the anchor's index in the region as it stands rather than in
   * the region with the moved slot removed.
   *
   * PROVEN NON-VACUOUS: dropping the `remaining` filter (resolving the anchor against
   * `destination.slots`) made the downward drop produce `b a c` instead of `b c a`; reverted.
   */
  it("counts the siblings a downward drag passed", () => {
    const start = twoColumnDocument();
    expect(order(dropPlacement(start, "a", "c", "after"), "left")).toEqual(["b", "c", "a"]);
    expect(order(dropPlacement(start, "a", "c", "before"), "left")).toEqual(["b", "a", "c"]);
    // Upward needs no correction and must not receive one.
    expect(order(dropPlacement(start, "c", "a", "before"), "left")).toEqual(["c", "a", "b"]);
    expect(order(dropPlacement(start, "c", "a", "after"), "left")).toEqual(["a", "c", "b"]);
  });

  it("carries a placement into another region, on the side that was dropped on", () => {
    const start = twoColumnDocument();
    const before = dropPlacement(start, "b", "y", "before");
    expect(order(before, "left")).toEqual(["a", "c"]);
    expect(order(before, "right")).toEqual(["x", "b", "y"]);
    const after = dropPlacement(start, "b", "x", "after");
    expect(order(after, "right")).toEqual(["x", "b", "y"]);
  });

  it("refuses a drop on the placement itself, or on anything it cannot resolve", () => {
    const start = twoColumnDocument();
    expect(dropPlacement(start, "a", "a", "before")).toBe(start);
    expect(dropPlacement(start, "a", "nobody", "after")).toBe(start);
    expect(dropPlacement(start, "nobody", "a", "after")).toBe(start);
  });
});

/* -------------------------------------------------------------------------- */
/*  regions                                                                    */
/* -------------------------------------------------------------------------- */

describe("moving a placement into a region", () => {
  it("lands it at the end of that region, including a region it is already in", () => {
    const start = twoColumnDocument();
    expect(order(movePlacementIntoRegion(start, "a", "right"), "right")).toEqual(["x", "y", "a"]);
    expect(order(movePlacementIntoRegion(start, "a", "right"), "left")).toEqual(["b", "c"]);
    // Already in the region but not last: sending it to the region means sending it to the end.
    expect(order(movePlacementIntoRegion(start, "a", "left"), "left")).toEqual(["b", "c", "a"]);
  });

  it("refuses the two moves that mean nothing, by reference", () => {
    const start = twoColumnDocument();
    // Already the last slot of the region it was sent to.
    expect(movePlacementIntoRegion(start, "c", "left")).toBe(start);
    expect(movePlacementIntoRegion(start, "a", "nowhere")).toBe(start);
  });

  /**
   * WARN, NEVER BLOCK (plan decision 3) as an assertion rather than as a comment: a sourcing section
   * carried into the CAD column's body is PERFORMED, and whatever it costs is the validator's to
   * report. The registry's `home` hint is where a piece goes when nobody has placed it, not a fence.
   *
   * FAILS IF: `movePlacementIntoRegion` starts consulting the manifest, or refuses a cross-column
   * move, or the move introduces an issue the shipped document did not have.
   */
  it("performs a move the registry would not have chosen, and makes the document no worse", () => {
    const before = validateLayout(DEFAULT_WORKSPACE_LAYOUT, WORKSPACE_PIECE_REGISTRY);
    const moved = movePlacementIntoRegion(
      DEFAULT_WORKSPACE_LAYOUT,
      "workspace.place.sourcing-documents",
      WORKSPACE_REGION.cadBody,
    );
    expect(moved).not.toBe(DEFAULT_WORKSPACE_LAYOUT);
    expect(order(moved, WORKSPACE_REGION.cadBody)).toContain(
      "workspace.place.sourcing-documents",
    );
    expect(order(moved, WORKSPACE_REGION.sourcingBody)).not.toContain(
      "workspace.place.sourcing-documents",
    );
    const after = validateLayout(moved, WORKSPACE_PIECE_REGISTRY);
    for (const code of new Set(after.map((issue) => issue.code))) {
      expect(
        after.filter((issue) => issue.code === code).length,
        `${code} after the move`,
      ).toBeLessThanOrEqual(before.filter((issue) => issue.code === code).length);
    }
  });

  /**
   * FAILS IF: the choice list is filtered by the manifest's home hint, or drops the region the
   * placement is already in (which is what the menu preselects), or invents one.
   */
  it("offers every region of the document, and marks the one the placement is in", () => {
    const choices = arrangeRegionChoices(
      DEFAULT_WORKSPACE_LAYOUT,
      "workspace.place.sourcing-documents",
    );
    const ids = choices.map((choice) => choice.id);
    expect(ids).toContain(WORKSPACE_REGION.cadBody);
    expect(ids).toContain(WORKSPACE_REGION.sourcingBody);
    expect(ids).toContain(WORKSPACE_REGION.root);
    expect(new Set(ids).size).toBe(ids.length);
    expect(choices.filter((choice) => choice.current).map((choice) => choice.id)).toEqual([
      WORKSPACE_REGION.sourcingBody,
    ]);
    // The band carries a dev id and the toolbar does not; both are offered either way.
    expect(choices.find((choice) => choice.id === WORKSPACE_REGION.columnBand)?.devId).toBe(
      "component-browser.columns",
    );
  });
});
