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

/** How much of a pad's thickness sits INSIDE the board plate. Half leaves the land pattern plainly
 *  visible while making the copper read as part of the stack rather than as something resting on
 *  it; 1 would bury it completely and 0 is the sticker look the owner rejected. */
export const PAD_EMBED_FRACTION = 0.5;

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

/** A silkscreen / courtyard segment as a flat quad lying in the board plane. */
export interface SilkQuad {
  /** centre of the quad, in board-plane coordinates (scene x and z) */
  cx: number;
  cz: number;
  /** along-the-segment length; the quad's other dimension is the stroke width */
  length: number;
  /** rotation about the scene Y axis, radians, so the quad runs along the segment */
  angleY: number;
}

/** Widths a footprint can legally carry that would render as nothing. KiCad treats width 0 as
 *  "use the board default", so it must become a real width rather than a zero-area quad. */
const DEFAULT_STROKE_MM = 0.12;

/**
 * One footprint graphic segment, as a flat quad on the board surface.
 *
 * The owner's "the footprint needs to be accurate to whats downloaded, not just the pads": every
 * graphic was being drawn with `THREE.Line`, whose width WebGL ignores, so a 0.12mm silkscreen line
 * rendered as a 1-pixel hairline at every zoom - present in the scene graph and invisible on screen,
 * which is why the land pattern read as pads only. The footprint's own stroke width was extracted by
 * the backend and then discarded here.
 *
 * REJECTED: `LineSegments2` + `LineMaterial({ worldUnits: true })`, the maintained three.js answer to
 * line width. It draws a CAMERA-FACING ribbon, so flat silkscreen ink would read as a raised wire at
 * grazing angles and in this viewer's front elevation; and its `resolution` has to be maintained by
 * hand for objects that are not currently visible (three.js#29666), which these toggleable layers
 * are. A flat quad is what ink on a mask actually is.
 *
 * Returns null when the segment has no length - a degenerate quad renders as nothing and would
 * silently drop a graphic instead of drawing it.
 */
export function silkQuad(
  start: readonly [number, number],
  end: readonly [number, number],
  width: number,
): (SilkQuad & { width: number }) | null {
  const dx = end[0] - start[0];
  const dz = end[1] - start[1];
  const length = Math.hypot(dx, dz);
  if (!Number.isFinite(length) || length <= 0) return null;
  const w = Number.isFinite(width) && width > 0 ? width : DEFAULT_STROKE_MM;
  return {
    cx: (start[0] + end[0]) / 2,
    cz: (start[1] + end[1]) / 2,
    length,
    // atan2(dz, dx) is the angle in the x/z plane. Negated because a rotation about +Y turns from
    // +z toward +x, i.e. opposite to the direction atan2 measures here.
    angleY: -Math.atan2(dz, dx),
    width: w,
  };
}

/** Half-extents of everything the board must carry, in board-plane mm. */
export interface BoardExtent {
  halfX: number;
  halfZ: number;
}

/**
 * How far the board has to reach, from EVERYTHING that sits on it.
 *
 * The span used to come from pad CENTRES alone (`pads.map(p => p.at[0])`), which ignores both the
 * pad's own width and every silkscreen graphic - so the board could be smaller than the footprint
 * standing on it, and a graphic near the outline hung off the edge into mid-air. Owner 2026-07-26,
 * on seeing that: "the 3d footprint looks horribly wrong now."
 *
 * Pads contribute centre +/- half their size (rotation ignored on purpose: a rotated pad's bounding
 * half-extent is never LARGER than half its diagonal, and using the diagonal would over-reach on
 * every ordinary axis-aligned pad, which is the common case). Graphics contribute their endpoints.
 */
export function boardExtent(
  pads: readonly { at: readonly [number, number]; size: readonly [number, number] }[],
  graphics: readonly { start: readonly [number, number]; end: readonly [number, number] }[] = [],
): BoardExtent {
  let halfX = 0;
  let halfZ = 0;
  for (const p of pads) {
    halfX = Math.max(halfX, Math.abs(p.at[0]) + Math.abs(p.size[0]) / 2);
    halfZ = Math.max(halfZ, Math.abs(p.at[1]) + Math.abs(p.size[1]) / 2);
  }
  for (const g of graphics) {
    for (const pt of [g.start, g.end]) {
      halfX = Math.max(halfX, Math.abs(pt[0]));
      halfZ = Math.max(halfZ, Math.abs(pt[1]));
    }
  }
  return { halfX, halfZ };
}

/**
 * The board plane's half-extent, in mm. Effectively INFINITE.
 *
 * Owner 2026-07-26: "The plane should be like infinite, and the view should be zoomed in and centered
 * on the model." Those two go together and they replace three earlier attempts at SIZING the board:
 * cropped to the footprint (read as a coaster), a square 2.6x reach (dwarfed the part), then per-axis
 * with a floor ratio (still 4.5x the short axis of a 3.5 x 1.4mm USON).
 *
 * Every one of those was solving the wrong problem. The board looked wrong relative to the part only
 * because the CAMERA framed the board; once the fit ignores it (see `refitCamera`, which no longer adds
 * `boardMesh`), the plane can simply run past the frame in every direction and the part is the subject.
 * OWNER REVERSAL, 2026-07-26: *"the 3d model should return to making the pcb a flat plane properly
 * sized for the component."* The plane had been made effectively infinite (250mm, ~70x the longest
 * package) so no frame could reach its edge. That solved the problem it was aimed at - three earlier
 * attempts had all been trying to SIZE a board that the camera was simultaneously trying to FRAME,
 * and removing the board from the fit is what actually settled those - but the result is a part on a
 * boundless floor rather than on a board, which is not what the owner wants to look at.
 *
 * So: sized again, per axis, exactly as it was before the infinite plane. The three failed attempts
 * are recorded so nobody re-walks them - fully square gave the owner's 3.5x1.4mm USON a 6.3mm square
 * (4.5x its short axis, the part read as lost); footprint-cropped read as footprint-shaped rather
 * than as a board; and per-axis with no floor gave a long thin part a long thin sliver, which is the
 * same fault again. Per-axis reach WITH a floor ratio is the version that survived.
 */
/** How far past the footprint's own extent the board reaches, per axis.
 *
 * 1.15 by the owner's decision (2026-07-26), chosen from previews after the framing was measured:
 * at 1.8 their 3.5x1.4mm USON sat on a ~6.4x4.0mm plane and read as a part lost on a table. The
 * plane is meant to say "this is the surface it mounts to", and it only needs to clear the pads to
 * say it. This is the FOURTH sizing attempt and the first the owner picked rather than had shown
 * to them, so do not re-tune it without asking - the three before it were all reverted. */
export const BOARD_PLANE_REACH = 1.15;
/** A floor in millimetres, so a tiny 0402 still gets a board rather than a chip of one. */
export const BOARD_PLANE_MIN_HALF_MM = 1.2;
/** The narrow axis may not fall below this fraction of the wide one, or the plane reads as a sliver. */
export const BOARD_PLANE_MIN_ASPECT = 0.62;

/** The board plane's half-extents: the footprint's reach, grown so it reads as a surface. */
export function boardPlaneHalfExtents(extent: BoardExtent): BoardExtent {
  const x = Math.max(extent.halfX * BOARD_PLANE_REACH, BOARD_PLANE_MIN_HALF_MM);
  const z = Math.max(extent.halfZ * BOARD_PLANE_REACH, BOARD_PLANE_MIN_HALF_MM);
  const floor = Math.max(x, z) * BOARD_PLANE_MIN_ASPECT;
  return { halfX: Math.max(x, floor), halfZ: Math.max(z, floor) };
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
  // THE PADS ARE LAMINATED INTO THE PLATE, not laid on top of it (owner, 2026-07-26: "the 3D
  // footprint should sit WITHIN the pcb plate, not lay on top of it"). Real copper is part of the
  // stack, and a pad standing proud of the surface reads as a sticker.
  //
  // The board's top face therefore rises to the pads' MID-HEIGHT rather than their underside. Half,
  // not all: burying them flush would make the land pattern invisible, which loses the thing the
  // layer exists to show.
  //
  // CRITICALLY, the part does NOT move. `padTopY` is still exactly `componentBaseY`, so the body
  // still rests on the pads' top face - re-sinking the body into the board is the regression
  // `cae5a81` fixed and the owner reported as "the 3d model clips into the pads and pcb". Only the
  // BOARD moves, and only upward.
  const boardTopY = padGroupY + PAD_THICKNESS_MM * PAD_EMBED_FRACTION;
  return {
    boardThickness,
    padGroupY,
    padTopY,
    boardCenterY: boardTopY - boardThickness / 2,
  };
}

/**
 * Which layers the viewer draws at load.
 *
 * Lives HERE, in the three-free stack module, because the SCENE and the toolbar CHIPS both need it
 * and must never disagree - a chip reading "off" while the scene draws the layer is a control that
 * lies about the thing it controls. This used to be two separate literals in two files with a
 * comment saying they had to match, which is a rule enforced by nothing; now there is one value and
 * they cannot drift. `Glb3DView` deliberately cannot import it from `threeScene`: that module
 * top-level-imports three and is loaded lazily so three lands in its own chunk, and a VALUE import
 * would drag the whole library into the main bundle.
 *
 * Board and pads default ON (owner, 2026-07-26, chosen from previews). A part shown by itself floats
 * on nothing - no contact shadow, and in dark theme its near side face measured 53 against a 40
 * background, so the lower silhouette dissolved into the stage.
 *
 * They travel TOGETHER, and that is geometry rather than taste: `boardStack` puts the board's top
 * face one PAD_THICKNESS_MM BELOW the part's underside, so drawing the board without the pads leaves
 * the part hovering over exactly that gap - the owner's "the 3d model clips into the pads and pcb"
 * complaint, inverted. `boardPlane.test.ts` pins the coupling.
 */
export const DEFAULT_LAYERS = { model: true, pads: true, board: true };
