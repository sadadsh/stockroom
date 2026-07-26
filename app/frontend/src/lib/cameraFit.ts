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
 * The screen-UP vector a view along `dir` should use - the one BOTH the fit and the camera adopt.
 *
 * World up works for every direction except the one that is parallel to it. Looking straight down,
 * `up = [0,1,0]` is the view direction, so the in-plane rotation is undefined and three.js resolves
 * it from whatever epsilon happens to be in the direction vector. That is not a small cosmetic
 * detail: the ortho fit's own basis falls back to a right vector of `[1,0,0]` in exactly that case,
 * so a camera that resolved its rotation differently was drawing a portrait silhouette inside a
 * frustum sized for a landscape one. MEASURED in the preview modal on a 3.5 x 1.4mm package: ~400px
 * of a 1704px stage used across, 87% used up it.
 *
 * `[0,0,-1]` is not an arbitrary substitute. It makes screen-right `+X` and screen-DOWN `+Z`, which
 * is the frame the footprint preview is already drawn in (KiCad's `+X` right, `+Y` down, mapped to
 * the scene as `z`). So the top view and the footprint tile show the part the same way up.
 */
export type ScreenBasis = {
  right: [number, number, number];
  up: [number, number, number];
};

/** A vec3 triple, as plain numbers. */
type Vec3 = [number, number, number];

const cross = (a: Vec3, b: Vec3): Vec3 => [
  a[1] * b[2] - a[2] * b[1],
  a[2] * b[0] - a[0] * b[2],
  a[0] * b[1] - a[1] * b[0],
];

/**
 * The screen basis (right and up) for a view along `dir` - the one BOTH the fit and the cameras
 * adopt, so a frustum can never be sized for a silhouette other than the one being drawn.
 *
 * For any ordinary direction this is the usual world-up construction and `half`/`aspect` change
 * nothing: rotating an iso view to fit better would tilt the horizon, which is not the same thing
 * as choosing a rotation that was never defined.
 *
 * Looking straight down IS undefined, and that is the case this exists for. Two bases are equally
 * valid there, 90 degrees apart, and nothing upstream picks between them: `orientUpright` only
 * stands the SHORTEST bounding-box axis vertical, so which of the remaining two lands on world X
 * and which on world Z is whatever the vendor authored. The owner's TPD6E05U06RVZR is authored
 * long in Z, so its top view stood a 3.5 x 1.4mm package on end and filled 411px of a 1704px stage.
 *
 * Given the subject's half-extents and the stage aspect, the basis needing the SMALLER frustum
 * wins - the owner's rule, "longest extent to the longest stage axis" (2026-07-25, chosen from
 * previews rather than guessed at twice). Expressing it as a fit rather than as "landscape means
 * horizontal" is what makes a PORTRAIT stage come out right without a special case. A tie keeps the
 * footprint-frame basis, so a square subject cannot flap between frames.
 */
export function screenBasisFor(
  dir: Vec3,
  half?: Vec3 | null,
  aspect = 1,
): ScreenBasis {
  const len = Math.hypot(dir[0], dir[1], dir[2]) || 1;
  const d: Vec3 = [dir[0] / len, dir[1] / len, dir[2] / len];
  const horiz = Math.hypot(d[0], d[2]);
  if (horiz >= 1e-6) {
    const right: Vec3 = [d[2] / horiz, 0, -d[0] / horiz];
    return { right, up: cross(d, right) };
  }
  // Degenerate: looking along the world vertical. `[1,0,0]` puts world X across the screen, which
  // is the frame the footprint preview is drawn in (KiCad +X right, +Y down -> scene +Z down), so
  // it is the default and the tie-break. `[0,0,1]` is the same view turned a quarter turn.
  const candidates: ScreenBasis[] = [
    { right: [1, 0, 0], up: cross(d, [1, 0, 0]) },
    { right: [0, 0, 1], up: cross(d, [0, 0, 1]) },
  ];
  if (!half) return candidates[0];
  const a = aspect > 0 ? aspect : 1;
  const extentAlong = (axis: Vec3) =>
    Math.abs(half[0] * axis[0]) + Math.abs(half[1] * axis[1]) + Math.abs(half[2] * axis[2]);
  // the half-HEIGHT each basis would need; the width term is divided by the aspect exactly as
  // fitOrthoHalfHeight does, which is what keeps the two in step
  const cost = (b: ScreenBasis) => Math.max(extentAlong(b.up), extentAlong(b.right) / a);
  return cost(candidates[1]) < cost(candidates[0]) ? candidates[1] : candidates[0];
}

/**
 * The `up` HINT to hand a camera looking along `dir` - which is not the same thing as the basis's
 * up vector, and the difference matters.
 *
 * A camera's `up` is a hint that `lookAt` orthogonalises against the view direction, so for any
 * ordinary view WORLD up is the honest answer: it says "keep the horizon level" and lets the
 * camera derive the rest. Handing it the already-perpendicular basis vector would compute the same
 * orientation while implying a choice was made where none was.
 *
 * At the pole there is no horizon to keep level, so the hint has to BE the chosen rotation, and
 * that is the one case where this returns the basis's own up.
 */
export function screenUpFor(dir: Vec3, half?: Vec3 | null, aspect = 1): Vec3 {
  const len = Math.hypot(dir[0], dir[1], dir[2]);
  if (len === 0) return [0, 1, 0];
  if (Math.hypot(dir[0], dir[2]) / len >= 1e-6) return [0, 1, 0];
  return screenBasisFor(dir, half, aspect).up;
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

/**
 * How far back the camera must sit for a BOX to fit the frame, from a given viewing direction,
 * and still fit through a full turn of the idle spin.
 *
 * WHY this exists beside `fitDistance`. That one fits the enclosing SPHERE, which is exact for a
 * sphere and wasteful for anything else - and a component package is about as far from spherical
 * as a subject gets. Measured on the owner's part (a 3.5 x 1.4 x 0.6mm USON-14) at a 494x240 stage:
 * the sphere fit put the camera at 5.74 scene units and the part's silhouette covered ~37% of the
 * frame height. The part is not small; the SPHERE AROUND IT is big, because its radius is set by
 * the long diagonal while the silhouette is set by the short one.
 *
 * The bound is still rotation-safe, which is the property the sphere was there to provide. The idle
 * spin turns the subject about the VERTICAL axis only, so:
 *   - the vertical half-extent `hy` never changes;
 *   - the horizontal footprint sweeps a circle of radius `hypot(hx, hz)`, whatever the angle.
 * Projecting that swept cylinder onto the screen axes gives a worst case over every rotation, so
 * the frame is computed once and the subject cannot grow out of it mid-spin.
 *
 * Returns the distance from the box centre along `dir`.
 */
export function fitDistanceForBox(
  half: [number, number, number],
  dir: [number, number, number],
  fovDeg: number,
  aspect: number,
  pad = FIT_MARGIN,
): number {
  const [hx, hy, hz] = half.map(Math.abs) as [number, number, number];

  // Camera basis. `right` is perpendicular to the view direction and to world up; `up` completes
  // it. Looking straight down (the Top view) makes `dir` parallel to world up and the cross
  // product degenerate, so fall back to a fixed right vector - at that angle the swept footprint
  // is symmetric about the view axis, so any choice gives the same answer.
  const len = Math.hypot(dir[0], dir[1], dir[2]) || 1;
  const d: [number, number, number] = [dir[0] / len, dir[1] / len, dir[2] / len];
  const horiz = Math.hypot(d[0], d[2]);
  const right: [number, number, number] =
    horiz < 1e-6 ? [1, 0, 0] : [d[2] / horiz, 0, -d[0] / horiz];
  const up: [number, number, number] = [
    d[1] * right[2] - d[2] * right[1],
    d[2] * right[0] - d[0] * right[2],
    d[0] * right[1] - d[1] * right[0],
  ];

  const halfFov = (fovDeg * Math.PI) / 180 / 2;
  const t = Math.tan(halfFov);
  const a = aspect > 0 ? aspect : 1;
  const dot = (p: number[], q: number[]) => p[0] * q[0] + p[1] * q[1] + p[2] * q[2];

  // PERSPECTIVE, not orthographic. This is where the first version of this function was wrong and
  // the error was invisible in the maths: it projected the box as though every corner sat at the
  // TARGET's depth. Under perspective a corner nearer the camera projects larger, and a component
  // package is deep relative to how far away it is - MEASURED on the owner's part, the box reached
  // 1.75mm toward a camera only 2.5mm out, so the near corners overflowed a frame the flat
  // projection called a comfortable fit, and the part rendered cropped on two edges.
  //
  // For a corner `p` (about the box centre) the camera at distance `d` along `dir` sees it at
  // depth `d - dot(p, dir)`, so it stays inside the frustum when
  //     |dot(p, up)|    <= (d - dot(p, dir)) * t
  //     |dot(p, right)| <= (d - dot(p, dir)) * t * aspect
  // Solving each for `d` and taking the largest over every corner gives the exact fit.
  let needed = 0;
  // Rotation samples: the idle spin turns the subject about the vertical axis, so the frame has to
  // hold at EVERY angle, not just the one it was fitted from. Sampling beats a closed form here
  // because the binding corner changes with angle; 72 steps is every 5 degrees, and the function
  // runs once per refit rather than per frame.
  const STEPS = 72;
  for (let i = 0; i < STEPS; i++) {
    const th = (i / STEPS) * Math.PI * 2;
    const c = Math.cos(th);
    const s = Math.sin(th);
    for (const sx of [-1, 1]) {
      for (const sy of [-1, 1]) {
        for (const sz of [-1, 1]) {
          const x0 = sx * hx;
          const z0 = sz * hz;
          const p = [x0 * c + z0 * s, sy * hy, -x0 * s + z0 * c];
          const depthOffset = dot(p, d);
          const vertical = depthOffset + Math.abs(dot(p, up)) / t;
          const horizontal = depthOffset + Math.abs(dot(p, right)) / (t * a);
          needed = Math.max(needed, vertical, horizontal);
        }
      }
    }
  }
  return Math.max(needed * pad, 1e-3);
}

/** The half-extents of a set of boxes about their common centre, for `fitDistanceForBox`. */
export function halfExtents(boxes: Box[]): [number, number, number] | null {
  if (boxes.length === 0) return null;
  const lo = [Infinity, Infinity, Infinity];
  const hi = [-Infinity, -Infinity, -Infinity];
  for (const { min, max } of boxes) {
    for (let axis = 0; axis < 3; axis++) {
      lo[axis] = Math.min(lo[axis], min[axis], max[axis]);
      hi[axis] = Math.max(hi[axis], min[axis], max[axis]);
    }
  }
  if (!lo.every(Number.isFinite) || !hi.every(Number.isFinite)) return null;
  return [(hi[0] - lo[0]) / 2, (hi[1] - lo[1]) / 2, (hi[2] - lo[2]) / 2];
}

/**
 * The half-HEIGHT an orthographic frustum needs to contain the box from a given direction.
 *
 * A technical top view wants an ORTHOGRAPHIC camera. Under perspective, a "top" view still shows
 * the sides of a package - the further a face is from the optical axis the more of its side you
 * see - so a pad and the body above it do not line up, which is the one thing a top view exists to
 * check. Orthographic projection has no vanishing point, so a footprint reads as its true outline.
 *
 * There is no distance term here: an orthographic frustum's size is the projection, so moving the
 * camera along the view axis changes nothing. That is also why this cannot reuse `fitDistanceForBox`
 * - that function solves for a DISTANCE, which is meaningless here.
 *
 * Returns the half-height; the caller derives half-width as `halfHeight * aspect`.
 */
export function fitOrthoHalfHeight(
  half: [number, number, number],
  dir: [number, number, number],
  aspect: number,
  pad = FIT_MARGIN,
): number {
  const [hx, hy, hz] = half.map(Math.abs) as [number, number, number];
  // The SAME basis the cameras adopt, subject-aware and stage-aware. Deriving a second one here is
  // exactly how the frustum came to be sized for a landscape silhouette while a portrait one was
  // drawn inside it, so there is one function and both callers use it.
  const { right, up } = screenBasisFor(dir, [hx, hy, hz], aspect);
  // The largest projection of the box onto each screen axis: every corner's contribution is the
  // sum of |extent * axis component|, which is exact for an axis-aligned box under any direction.
  const extentAlong = (axis: [number, number, number]) =>
    hx * Math.abs(axis[0]) + hy * Math.abs(axis[1]) + hz * Math.abs(axis[2]);
  const a = aspect > 0 ? aspect : 1;
  const vertical = extentAlong(up);
  const horizontal = extentAlong(right);
  // whichever axis binds: a wide subject in a narrow frame is width-limited
  return Math.max(Math.max(vertical, horizontal / a) * pad, 1e-4);
}
