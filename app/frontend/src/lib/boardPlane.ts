/**
 * How thick the 3D viewer's board is, and how thick a pad is.
 *
 * Both are pure numbers in MILLIMETRES (the viewer's scene unit is 1mm), extracted here so they can
 * be tested without a GL context and so the two places that need the pad thickness - building the
 * pad geometry, and stacking the part on top of it - cannot drift apart.
 *
 * Owner 2026-07-26, two complaints that turn out to be one region of geometry:
 *   "the 3d model clips into the pads and pcb"
 *   "the pcb should be a plane less than its own component"
 */

/** Copper + finish on a real board is ~35-70um. A zero-height pad cannot catch a highlight or cast
 *  a contact shadow, which is most of why the pads used to read as stickers rather than metal. */
export const PAD_THICKNESS_MM = 0.05;

/** The old fixed value, kept as the CEILING and as the unknown-height fallback. */
const MAX_BOARD_MM = 0.6;

/** How much of the component's own height the board may occupy, when that is the binding limit. */
const FRACTION_OF_COMPONENT = 0.4;

/**
 * The board's thickness for a component of `componentHeightMm`, always STRICTLY LESS than the
 * component itself.
 *
 * A real PCB is 1.6mm, and the viewer is not a cross-section: at part scale a physically-accurate
 * board is a slab that out-masses the thing it is meant to support. The old value was a flat
 * `0.6mm`, which is fine under a tall electrolytic and wrong under everything small - a USON-14 body
 * is ~0.55mm, so the board was THICKER than the component and became the subject of the render.
 *
 * Two rules, and the interesting part is that they compose into the invariant rather than needing a
 * special case: take 40% of the component's height, but never more than 0.6mm. When the fraction
 * binds, the result is 0.4h < h. When the ceiling binds, 0.6 <= 0.4h implies h >= 1.5, so 0.6 < h.
 * Either way it comes out thinner, at every height, with no clamping afterwards.
 *
 * An unmeasurable height (0, negative, NaN, Infinity) returns the previous fixed thickness rather
 * than propagating a bad number into geometry, where three.js would render nothing at all and the
 * board would simply be absent with no error.
 */
export function boardPlaneThickness(componentHeightMm: number): number {
  if (!Number.isFinite(componentHeightMm) || componentHeightMm <= 0) return MAX_BOARD_MM;
  return Math.min(MAX_BOARD_MM, componentHeightMm * FRACTION_OF_COMPONENT);
}

/** Where each piece of the board / pad / part stack sits, in scene Y. */
export interface BoardStack {
  /** board box height */
  boardThickness: number;
  /** origin of the pad group, which IS the board's top face (pads extrude upward from it) */
  padGroupY: number;
  /** centre of the board box, which is what a THREE.Mesh position takes */
  boardCenterY: number;
  /** the top of a front-side pad - must land exactly on the component's underside */
  padTopY: number;
}

/**
 * The whole stack, derived in ONE place: board, then pads on the board, then the part on the pads.
 *
 * Extracted from the scene builder and made pure because this arithmetic is where the owner's
 * clipping bug lived, and a perspective 3/4 render cannot settle whether it is right - measuring a
 * vertical world distance off a projected image gave two different answers on two attempts. The
 * relationships ARE exactly checkable though, so they are checked here instead of estimated there.
 *
 * `componentBaseY` is the model's lowest point in scene units (its bounding box bottom).
 */
export function boardStack(componentBaseY: number, componentHeightMm: number): BoardStack {
  const boardThickness = boardPlaneThickness(componentHeightMm);
  // The part rests ON the pads, so the pads' TOP is the part's underside and the board's top face
  // is one pad-thickness lower. Both used to sit AT `componentBaseY`, which buried the entire pad
  // thickness inside the body - "the 3d model clips into the pads and pcb".
  const padTopY = componentBaseY;
  const padGroupY = componentBaseY - PAD_THICKNESS_MM;
  return {
    boardThickness,
    padGroupY,
    padTopY,
    boardCenterY: padGroupY - boardThickness / 2,
  };
}
