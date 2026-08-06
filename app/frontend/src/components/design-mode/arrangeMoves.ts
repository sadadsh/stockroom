/**
 * THE GESTURES, AS PURE FUNCTIONS. What "drag this above that" and "press Arrow Down" MEAN, stated
 * as document-to-document transforms so the surface that draws the handles holds no arrangement
 * logic of its own.
 *
 * `layout/editOperations.ts` is one layer below and answers a different question. It knows how to
 * move a placement to a named slot at a named index; it does not know what index a gesture asks
 * for, because "drop this above the Documents section" and "move this one position down" are
 * questions about the document a person is looking at rather than about the operation. That
 * translation is the whole of this module, and it is here rather than inside the overlay for three
 * reasons:
 *
 *   IT IS TESTABLE WITHOUT A POINTER. Drag simulation in jsdom proves that a handler ran; it cannot
 *   prove that dropping the third section above the first produces the arrangement a person meant.
 *   That claim is about these functions and it is asserted directly against them.
 *
 *   THE THREE PATHS MUST AGREE. Pointer drop, arrow key and the piece menu's Move Into are one set
 *   of moves reached three ways. Three call sites each computing an index is three chances for the
 *   keyboard path to land somewhere the pointer path would not.
 *
 *   NOTHING HERE REFUSES. Every function returns the INPUT DOCUMENT, by reference, when the gesture
 *   cannot mean anything - an unknown placement, an anchor that is the placement itself, a step off
 *   the end of a region. Warn, never block (plan decision 3) degrades to nothing happening, and the
 *   caller can compare by reference to know the move was not available.
 */
import {
  findRegion,
  layoutPlacements,
  layoutRegions,
  type LayoutDocument,
  type PiecePlacement,
} from "../../layout/document";
import { movePlacement } from "../../layout/editOperations";

/** Where a placement sits right now: which slot holds it, in which region, at which position. */
export interface PlacementSeat {
  placement: PiecePlacement;
  slotId: string;
  regionId: string;
  /** The slot's index among its region's slots. */
  index: number;
  /** How many slots that region has, so a caller can say whether a step is available. */
  slotCount: number;
}

/**
 * The seat a placement occupies, or `null`.
 *
 * Resolved by PLACEMENT ID only - never by piece id, unlike `editOperations`' looser `PlacementRef`.
 * A handle is drawn per placement and the three CAD modules are three placements of one piece, so
 * an editing surface that accepted a piece id would offer a handle that moves "one of the three,
 * whichever comes first", which is not a gesture anybody made.
 */
export function placementSeat(
  document: LayoutDocument,
  placementId: string,
): PlacementSeat | null {
  const visit = layoutPlacements(document).find((entry) => entry.node.id === placementId);
  if (!visit || !visit.slotId || !visit.parentRegionId) return null;
  const region = findRegion(document, visit.parentRegionId);
  if (!region) return null;
  const index = region.slots.findIndex((slot) => slot.id === visit.slotId);
  if (index < 0) return null;
  return {
    placement: visit.node,
    slotId: visit.slotId,
    regionId: visit.parentRegionId,
    index,
    slotCount: region.slots.length,
  };
}

/** Which way a step goes. `-1` is one position earlier in the region's own order. */
export type StepDirection = -1 | 1;

/**
 * Move a placement one position within the region it is already in.
 *
 * The keyboard gesture, and the piece menu's Move Up / Move Down. A step off either end returns the
 * input document: the arrangement did not change, and pretending it did by silently wrapping around
 * would move a section from the top of a column to the bottom on one key press.
 */
export function stepPlacement(
  document: LayoutDocument,
  placementId: string,
  direction: StepDirection,
): LayoutDocument {
  const seat = placementSeat(document, placementId);
  if (!seat) return document;
  const to = seat.index + direction;
  if (to < 0 || to >= seat.slotCount) return document;
  // The placement's OWN slot as the target, with an explicit index: `movePlacement` treats that
  // pair as "this position within this region" rather than as the no-op a bare own-slot target is.
  return movePlacement(document, { placement: placementId }, seat.slotId, to);
}

/** Is there a position that way. Drives whether the menu's step controls are offered at all. */
export function canStepPlacement(
  document: LayoutDocument,
  placementId: string,
  direction: StepDirection,
): boolean {
  const seat = placementSeat(document, placementId);
  if (!seat) return false;
  const to = seat.index + direction;
  return to >= 0 && to < seat.slotCount;
}

/** Which side of an anchor a drop lands on. */
export type DropSide = "before" | "after";

/**
 * Drop a placement above or below another placement, wherever in the document that one lives.
 *
 * THE ANCHOR'S POSITION IS RESOLVED AFTER THE REMOVAL, which is the whole subtlety. Dragging the
 * first section of a column below the third has to count the two siblings it passed, and an index
 * computed before the moved slot left its region counts them one too many. So the destination's
 * slot order is taken with the moved slot already out of it - and only when the two share a region,
 * because a move ACROSS regions removes nothing from the destination.
 *
 * A no-op when either id names no placement, or when the anchor IS the placement: a piece cannot be
 * dropped on itself, and answering that with an index would shuffle the region for nothing.
 */
export function dropPlacement(
  document: LayoutDocument,
  placementId: string,
  anchorPlacementId: string,
  side: DropSide,
): LayoutDocument {
  if (placementId === anchorPlacementId) return document;
  const moved = placementSeat(document, placementId);
  const anchor = placementSeat(document, anchorPlacementId);
  if (!moved || !anchor) return document;
  const destination = findRegion(document, anchor.regionId);
  if (!destination) return document;
  const remaining =
    anchor.regionId === moved.regionId
      ? destination.slots.filter((slot) => slot.id !== moved.slotId)
      : destination.slots;
  const at = remaining.findIndex((slot) => slot.id === anchor.slotId);
  if (at < 0) return document;
  return movePlacement(
    document,
    { placement: placementId },
    anchor.slotId,
    side === "before" ? at : at + 1,
  );
}

/**
 * Move a placement to the END of a region, whichever region it is.
 *
 * The menu's Move Into, and the only gesture that can reach a region with no slots left to anchor
 * against. THE MODEL PLACES NO RESTRICTION on which region a piece may go in and neither does this:
 * a sourcing section can be dropped into the CAD column, `validateLayout` will report whatever that
 * costs, and the owner decides (plan decision 3). What is refused is the one move that means
 * nothing - a placement into the region it is already the last slot of.
 */
export function movePlacementIntoRegion(
  document: LayoutDocument,
  placementId: string,
  regionId: string,
): LayoutDocument {
  const seat = placementSeat(document, placementId);
  if (!seat) return document;
  if (seat.regionId === regionId && seat.index === seat.slotCount - 1) return document;
  if (!findRegion(document, regionId)) return document;
  return movePlacement(document, { placement: placementId }, regionId);
}

/** One region a placement can be sent to, with what the menu needs to name it. */
export interface ArrangeRegionChoice {
  id: string;
  /** The region's `data-dev-id`, where the arrangement gives it one. Absent is normal. */
  devId?: string;
  /** How deep it sits, so a flat list can still read as a tree. */
  depth: number;
  /** Whether the placement is already inside it. */
  current: boolean;
}

/**
 * Every region in the document, in document order, as move destinations.
 *
 * ALL of them, deliberately. The registry's `home` hint says where a piece belongs when NOBODY has
 * placed it (plan decision 6); it is not a constraint on where an owner may put one, and filtering
 * this list by it would turn an informational hint into the block decision 3 rules out.
 */
export function arrangeRegionChoices(
  document: LayoutDocument,
  placementId: string,
): ArrangeRegionChoice[] {
  const seat = placementSeat(document, placementId);
  return layoutRegions(document).map((visit) => ({
    id: visit.node.id,
    ...(visit.node.devId ? { devId: visit.node.devId } : {}),
    depth: visit.depth,
    current: seat?.regionId === visit.node.id,
  }));
}
