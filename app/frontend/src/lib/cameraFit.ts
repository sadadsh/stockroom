/**
 * The geometry behind framing the 3D viewer, kept free of three.js so it is testable as maths.
 *
 * The viewer used to frame itself from the MODEL's bounding sphere alone, computed once when the
 * GLB finished loading. The board and the land pattern are built afterwards and are much larger
 * than the part, so switching the PCB on pushed it straight out of frame; and with only a thin
 * part in a tall stage the same fit left the model at about a tenth of the viewport. Both are the
 * one defect: the fit must consider whatever is currently VISIBLE, and must be recomputed when
 * that changes.
 */

/**
 * How much further back than the exact fit the camera sits, as a multiplier.
 *
 * This was 0.98 - INSIDE the exact fit, so the subject touched the frame edges and, at some
 * auto-rotate angles, crossed them. The owner's words: the model "should be zoomed out to show the
 * whole thing". A margin above 1 is what guarantees the whole subject stays visible through a full
 * rotation instead of only at the angle it was fitted from.
 */
export const FIT_MARGIN = 1.15;

/** An axis-aligned box in scene units, as plain numbers. */
export type Box = { min: [number, number, number]; max: [number, number, number] };

/** Where to point the camera, and how big the thing it is looking at is. */
export type Bounds = { centre: [number, number, number]; radius: number };

/**
 * The centre and enclosing radius of everything currently visible, or null when nothing is.
 *
 * The radius is measured about the returned CENTRE, and the caller is expected to make that centre
 * the orbit target. Measuring about a fixed origin instead looks equivalent and is not: the part
 * is centred on the origin but the board and pads hang BELOW it, so an origin-centred sphere has
 * to be large enough to reach the lowest pad in every direction. That both over-shoots the camera
 * and pushes the subject to the bottom of the frame with dead space above it - measured at roughly
 * 45% of the stage before this was corrected.
 *
 * Null for an empty set: every layer switched off is a real state, and it must not produce NaN and
 * send the camera somewhere undefined.
 */
export function visibleBounds(boxes: Box[]): Bounds | null {
  if (boxes.length === 0) return null;
  const lo: [number, number, number] = [Infinity, Infinity, Infinity];
  const hi: [number, number, number] = [-Infinity, -Infinity, -Infinity];
  for (const { min, max } of boxes) {
    for (let axis = 0; axis < 3; axis++) {
      lo[axis] = Math.min(lo[axis], min[axis], max[axis]);
      hi[axis] = Math.max(hi[axis], min[axis], max[axis]);
    }
  }
  if (!lo.every(Number.isFinite) || !hi.every(Number.isFinite)) return null;
  const centre: [number, number, number] = [
    (lo[0] + hi[0]) / 2,
    (lo[1] + hi[1]) / 2,
    (lo[2] + hi[2]) / 2,
  ];
  // half the diagonal of the union: the sphere about `centre` that contains every corner. A sphere
  // rather than the box itself so the subject cannot clip as the viewer auto-rotates around it.
  const radius = Math.hypot(hi[0] - lo[0], hi[1] - lo[1], hi[2] - lo[2]) / 2;
  return { centre, radius };
}

/**
 * How far back the camera must sit for a sphere of `radius` to fit in the frame.
 *
 * A perspective camera's `fov` is VERTICAL, so the vertical extent binds on any frame at least as
 * wide as it is tall. A portrait frame is width-limited instead, and dividing by the aspect is
 * what stops a tall narrow stage cropping the sides. `min(1, aspect)` keeps a landscape frame from
 * being pushed further than the vertical fit needs, which would shrink the subject for nothing.
 *
 * The floor matters: a camera sitting exactly on its target has no view direction and renders
 * nothing, so a degenerate scene still gets a usable distance rather than 0.
 */
export function fitDistance(radius: number, fovDeg: number, aspect: number, pad = FIT_MARGIN): number {
  const halfFov = (fovDeg * Math.PI) / 180 / 2;
  const vertical = radius / Math.sin(halfFov);
  const horizontal = vertical / Math.min(1, aspect || 1);
  return Math.max(Math.max(vertical, horizontal) * pad, 1e-3);
}
