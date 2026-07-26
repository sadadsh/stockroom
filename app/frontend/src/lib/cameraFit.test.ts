import { describe, expect, it } from "vitest";
import {
  fitOrthoHalfHeight,
  fitDistanceForBox,
  halfExtents,
  fitDistance,
  screenUpFor,
  visibleBounds,
} from "./cameraFit";

/**
 * The 3D viewer framed itself from the MODEL's bounds alone, captured once at load. The board and
 * the land pattern are built afterwards and are far larger than the part, so turning the PCB on
 * pushed it straight out of frame - the punch item "the board overflows the frame". Seen from the
 * other side it is the same defect: with only a thin part in a tall stage the fit leaves the model
 * at ~11% of the viewport.
 *
 * These are the two decisions that fix it, kept free of three.js so they can be tested as maths.
 */
describe("visibleBounds", () => {
  const box = (min: [number, number, number], max: [number, number, number]) => ({ min, max });

  it("measures a centred box as half its diagonal, about its own centre", () => {
    const b = visibleBounds([box([-1, -1, -1], [1, 1, 1])])!;
    expect(b.centre).toEqual([0, 0, 0]);
    expect(b.radius).toBeCloseTo(Math.sqrt(3), 6); // half-diagonal of a 2x2x2 cube
  });

  it("centres on the visible union, so off-origin content is framed tightly not pushed to an edge", () => {
    // THE composition bug: the part sits at the origin while the board and pads hang BELOW it.
    // Framing about the origin needs a sphere big enough to reach the lowest pad in EVERY
    // direction, which both over-shoots the camera and leaves the subject low with dead space
    // above it. Measured at ~45% of the stage empty before this was corrected.
    const b = visibleBounds([box([-1, -20, -1], [1, -18, 1])])!;
    expect(b.centre[1]).toBeCloseTo(-19, 6);
    expect(b.radius).toBeLessThan(3); // about its own centre, NOT the ~20 an origin fit would give
  });

  it("encloses every box it is given, not just the first", () => {
    const small = box([-1, -1, -1], [1, 1, 1]);
    const large = box([-9, -0.1, -9], [9, 0.1, 9]);
    const both = visibleBounds([small, large])!;
    expect(both.radius).toBeGreaterThanOrEqual(visibleBounds([large])!.radius);
    expect(both.radius).toBeGreaterThan(visibleBounds([small])!.radius);
  });

  it("returns null when nothing is visible", () => {
    // every layer switched off is a real state; it must not produce NaN and yank the camera to an
    // undefined position.
    expect(visibleBounds([])).toBeNull();
  });
});

describe("fitDistance", () => {
  it("backs off further for a bigger radius, in proportion", () => {
    const near = fitDistance(1, 45, 1);
    const far = fitDistance(2, 45, 1);
    expect(far).toBeCloseTo(near * 2, 6);
  });

  it("backs off further in a PORTRAIT frame than a square one", () => {
    // a tall narrow stage is width-limited, so the same object needs more distance to fit across.
    expect(fitDistance(1, 45, 0.5)).toBeGreaterThan(fitDistance(1, 45, 1));
  });

  it("does not back off further in a landscape frame than a square one", () => {
    // the vertical extent already binds once the frame is wider than tall; going further would
    // just shrink the subject for nothing.
    expect(fitDistance(1, 45, 2)).toBeCloseTo(fitDistance(1, 45, 1), 6);
  });

  it("puts the whole radius inside the vertical field of view", () => {
    // the geometric contract: at the returned distance, half the vertical FOV subtends at least
    // the radius. Asserting the trigonometry rather than a magic number.
    const r = 3;
    const fov = 45;
    const d = fitDistance(r, fov, 1);
    expect(d * Math.sin((fov * Math.PI) / 180 / 2)).toBeGreaterThanOrEqual(r * 0.95);
  });

  it("never returns 0 or a negative distance for an empty scene", () => {
    // a camera at the target with a 0 radius has no view direction and renders nothing.
    expect(fitDistance(0, 45, 1)).toBeGreaterThan(0);
  });

  it("needs a DIFFERENT distance for a portrait frame than a landscape one", () => {
    // The reason `onResize` in threeScene.ts must call refitCamera() and not merely restretch the
    // camera: distance is a function of aspect, so a frame that changes SHAPE needs a new distance
    // even though the subject has not moved. A resize that updates only `camera.aspect` leaves the
    // camera where the old shape put it.
    //
    // MEASURED 2026-07-25: the detail sheet's stage went 266x540 (0.49) -> 494x240 (2.06) and the
    // model rendered at ~28% of the frame width because the portrait distance was retained.
    const portrait = fitDistance(1, 45, 266 / 540);
    const landscape = fitDistance(1, 45, 494 / 240);
    expect(portrait).toBeGreaterThan(landscape);
    // and the gap is large enough to be plainly visible, not a rounding difference
    expect(portrait / landscape).toBeGreaterThan(1.5);
  });
});

describe("fitDistanceForBox", () => {
  const ISO: [number, number, number] = [0.55, 0.42, 1];
  // The owner's real part: a 3.5 x 1.4mm USON-14, about 0.6mm tall. Half-extents.
  const PART: [number, number, number] = [1.75, 0.3, 0.7];

  it("frames a flat part far closer than its enclosing sphere does", () => {
    // THE POINT OF THE FUNCTION. The sphere radius is set by the part's LONG diagonal while the
    // silhouette is set by the short one, so a sphere fit backs off for space nothing occupies.
    // Measured on screen before this: ~37% of frame height at a 494x240 stage.
    const sphere = fitDistance(Math.hypot(3.5, 0.6, 1.4) / 2, 45, 494 / 240);
    const box = fitDistanceForBox(PART, ISO, 45, 494 / 240);
    expect(box).toBeLessThan(sphere);
    // ~1.27x closer, so the part reads about a quarter larger. NOT the ~2.2x an ORTHOGRAPHIC
    // projection of the same box suggests: the first version of this function assumed every corner
    // sat at the target's depth, promised that 2.2x, and rendered the part cropped on two edges.
    // The honest figure is smaller because the box is deep relative to the viewing distance.
    expect(sphere / box).toBeGreaterThan(1.2);
    expect(sphere / box).toBeLessThan(1.4);
  });

  it("backs off further for a DEEP box than a flat one with the same silhouette", () => {
    // The perspective property itself, stated directly. Two boxes with the same width and height
    // but different depth along the view axis do NOT fit at the same distance, because the nearer
    // face of the deep one projects larger. An orthographic fit returns the same answer for both,
    // which is exactly the bug this replaced.
    const flat = fitDistanceForBox([1.75, 0.3, 0.05], ISO, 45, 2);
    const deep = fitDistanceForBox([1.75, 0.3, 1.75], ISO, 45, 2);
    expect(deep).toBeGreaterThan(flat);
  });

  it("is safe through a full turn of the idle spin", () => {
    // The property the enclosing sphere existed to provide, and the one a naive tight box fit
    // loses. Asserted on the REAL geometry: rotate the eight corners about Y, project them onto
    // the camera's screen axes at the fitted distance, and require every corner to land inside
    // the frustum at every angle.
    //
    // (An earlier version of this test rotated the AXIS-ALIGNED box and fed it back through the
    // function. That double-counts - the function already sweeps the footprint internally - so it
    // failed against a fit that was actually correct. Test the projection, not the helper.)
    const fov = 45;
    const aspect = 2.0;
    const d = fitDistanceForBox(PART, ISO, fov, aspect);
    const t = Math.tan((fov * Math.PI) / 180 / 2);

    // camera basis for ISO, mirroring the module
    const L = Math.hypot(...ISO);
    const dir = ISO.map((v) => v / L) as [number, number, number];
    const horiz = Math.hypot(dir[0], dir[2]);
    const right: [number, number, number] = [dir[2] / horiz, 0, -dir[0] / horiz];
    const up: [number, number, number] = [
      dir[1] * right[2] - dir[2] * right[1],
      dir[2] * right[0] - dir[0] * right[2],
      dir[0] * right[1] - dir[1] * right[0],
    ];
    const dot = (a: number[], b: number[]) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];

    // The half-frame at each corner's OWN depth. A perspective frustum widens with distance, so a
    // corner nearer the camera has less room than one further away - checking every corner against
    // the frame at the target's depth is the orthographic mistake this test exists to catch.

    for (let deg = 0; deg < 360; deg += 5) {
      const th = (deg * Math.PI) / 180;
      for (const sx of [-1, 1]) {
        for (const sy of [-1, 1]) {
          for (const sz of [-1, 1]) {
            const x0 = sx * PART[0];
            const z0 = sz * PART[2];
            // rotate the corner about the vertical axis
            const corner = [
              x0 * Math.cos(th) + z0 * Math.sin(th),
              sy * PART[1],
              -x0 * Math.sin(th) + z0 * Math.cos(th),
            ];
            const depth = d - dot(corner, dir);
            expect(Math.abs(dot(corner, up))).toBeLessThanOrEqual(depth * t + 1e-9);
            expect(Math.abs(dot(corner, right))).toBeLessThanOrEqual(depth * t * aspect + 1e-9);
          }
        }
      }
    }
  });

  it("backs off further for a narrower frame, never closer", () => {
    const wide = fitDistanceForBox(PART, ISO, 45, 2.5);
    const square = fitDistanceForBox(PART, ISO, 45, 1);
    const tall = fitDistanceForBox(PART, ISO, 45, 0.5);
    expect(tall).toBeGreaterThan(square);
    expect(square).toBeGreaterThanOrEqual(wide);
  });

  it("handles a straight-down view without producing NaN", () => {
    // The Top view makes the direction parallel to world up, so the camera basis is degenerate.
    const d = fitDistanceForBox(PART, [0, 1, 0.0001], 45, 1.6);
    expect(Number.isFinite(d)).toBe(true);
    expect(d).toBeGreaterThan(0);
  });

  it("never returns 0 for a degenerate box", () => {
    expect(fitDistanceForBox([0, 0, 0], ISO, 45, 1)).toBeGreaterThan(0);
  });

  it("halfExtents measures the union about its centre", () => {
    const h = halfExtents([
      { min: [-1, 0, -2], max: [1, 1, 2] },
      { min: [-3, -1, 0], max: [0, 0, 1] },
    ]);
    // x spans -3..1 => half 2; y spans -1..1 => half 1; z spans -2..2 => half 2
    expect(h).toEqual([2, 1, 2]);
    expect(halfExtents([])).toBeNull();
  });
});

describe("fitOrthoHalfHeight", () => {
  const PART: [number, number, number] = [1.75, 0.3, 0.7];

  it("frames the footprint's own extent from directly above", () => {
    // Looking straight down, the screen axes are X and Z, so the frame is set by the land pattern's
    // outline and NOT by the package height - which is the whole point of a top view.
    const h = fitOrthoHalfHeight(PART, [0, 1, 0.0001], 1);
    // square frame, so the larger of the two horizontal half-extents binds, plus the margin
    expect(h).toBeCloseTo(1.75 * 1.15, 3);
  });

  it("ignores the height of the part when looking down", () => {
    // A taller package must not change a top view's framing: its silhouette from above is the same.
    const short = fitOrthoHalfHeight([1.75, 0.05, 0.7], [0, 1, 0.0001], 1);
    const tall = fitOrthoHalfHeight([1.75, 3.0, 0.7], [0, 1, 0.0001], 1);
    expect(tall).toBeCloseTo(short, 6);
  });

  it("is width-limited in a narrow frame", () => {
    // A wide subject in a wide frame fits on height; squeeze the frame and the width binds.
    const wide = fitOrthoHalfHeight(PART, [0, 1, 0.0001], 4);
    const narrow = fitOrthoHalfHeight(PART, [0, 1, 0.0001], 0.5);
    expect(narrow).toBeGreaterThan(wide);
  });

  it("has no distance term, unlike the perspective fit", () => {
    // Stated as a test because it is the property that makes a top view honest: the projection is
    // the frustum, so nothing about the camera's position along the view axis can change the size.
    const a = fitOrthoHalfHeight(PART, [0, 1, 0.0001], 2);
    const b = fitOrthoHalfHeight(PART, [0, 2, 0.0002], 2); // same direction, different magnitude
    expect(a).toBeCloseTo(b, 9);
  });

  it("never returns a zero or negative frustum", () => {
    expect(fitOrthoHalfHeight([0, 0, 0], [0, 1, 0], 1)).toBeGreaterThan(0);
  });
});

/**
 * The fit and the CAMERA have to share one screen basis, and until this existed they did not.
 *
 * `fitOrthoHalfHeight` looking straight down falls back to a fixed right vector of [1,0,0], so it
 * sizes the frustum for a view with world X across the screen. The camera meanwhile kept a world-up
 * of [0,1,0], which for a straight-down view is PARALLEL to the view direction, so its in-plane
 * rotation fell out of an epsilon instead of being chosen. The two disagreed by 90 degrees:
 * MEASURED in the preview modal, a 3.5 x 1.4mm package came out standing on end, ~400px wide in a
 * 1704px stage - a frustum sized for a landscape silhouette with a portrait one drawn inside it.
 */
describe("screenUpFor", () => {
  it("is perpendicular to a straight-down view, where world up is not", () => {
    const up = screenUpFor([0, 1, 0]);
    expect(up[0] * 0 + up[1] * 1 + up[2] * 0).toBeCloseTo(0, 9);
    expect(Math.hypot(...up)).toBeCloseTo(1, 9);
  });

  it("puts a part's LONGER horizontal extent across the screen, not up it", () => {
    // The land pattern of a 3.5 x 1.4mm package: half-extents 1.75 in x, 0.7 in z. Seen from
    // above in a landscape stage the 3.5mm side must run across, which means the screen's UP axis
    // has to be the SHORT one.
    const up = screenUpFor([0, 1, 0]);
    const alongUp = 1.75 * Math.abs(up[0]) + 0.3 * Math.abs(up[1]) + 0.7 * Math.abs(up[2]);
    expect(alongUp).toBeCloseTo(0.7, 9);
  });

  it("agrees with the frustum the ortho fit computes, which is the whole point", () => {
    const part: [number, number, number] = [1.75, 0.3, 0.7];
    const up = screenUpFor([0, 1, 0]);
    const alongUp = part[0] * Math.abs(up[0]) + part[1] * Math.abs(up[1]) + part[2] * Math.abs(up[2]);
    // a frame WIDE enough that the height binds (the width term is divided by the aspect), so the
    // returned half-height is exactly the extent along the basis the camera is about to adopt
    expect(fitOrthoHalfHeight(part, [0, 1, 0], 20)).toBeCloseTo(alongUp * 1.15, 6);
  });

  it("keeps world up for a view that is not looking along the vertical", () => {
    // Only the degenerate case needs a substitute. An iso or front view must keep the ordinary
    // horizon, or the whole scene would appear tilted.
    expect(screenUpFor([0.55, 0.42, 1])).toEqual([0, 1, 0]);
    expect(screenUpFor([0, 0, 1])).toEqual([0, 1, 0]);
  });

  it("handles a zero direction without producing NaN", () => {
    expect(screenUpFor([0, 0, 0]).every(Number.isFinite)).toBe(true);
  });
});

/**
 * Owner's call, 2026-07-25, asked with previews rather than guessed at a second time: looking
 * straight down, the view TURNS so the subject's longest extent runs along the stage's longest
 * axis. "longest extent -> longest stage axis."
 *
 * It is needed because nothing upstream decides this. `orientUpright` only stands the SHORTEST
 * bounding-box axis vertical, so which of the other two lands on world X and which on world Z is
 * whatever the vendor authored - and the owner's TPD6E05U06RVZR is authored long in Z, so a
 * 3.5 x 1.4mm package stood on end and used 411px of a 1704px stage.
 *
 * The choice is made by which basis needs the SMALLER frustum, not by a landscape rule of thumb,
 * so a portrait stage correctly gets the opposite answer instead of a special case.
 */
describe("screenUpFor, choosing the in-plane rotation from the subject", () => {
  // half-extents of a 3.5 x 1.4mm package authored LONG IN Z
  const LONG_IN_Z: [number, number, number] = [0.7, 0.3, 1.75];
  const LONG_IN_X: [number, number, number] = [1.75, 0.3, 0.7];
  const extentAlong = (h: [number, number, number], v: [number, number, number]) =>
    h[0] * Math.abs(v[0]) + h[1] * Math.abs(v[1]) + h[2] * Math.abs(v[2]);

  it("turns a part authored long in Z so its length runs ACROSS a landscape stage", () => {
    const up = screenUpFor([0, 1, 0], LONG_IN_Z, 1.4);
    // the SHORT extent is what goes up the screen, which is what leaves the long one across it
    expect(extentAlong(LONG_IN_Z, up)).toBeCloseTo(0.7, 9);
  });

  it("leaves a part already long in X alone on a landscape stage", () => {
    const up = screenUpFor([0, 1, 0], LONG_IN_X, 1.4);
    expect(extentAlong(LONG_IN_X, up)).toBeCloseTo(0.7, 9);
  });

  it("gives a PORTRAIT stage the opposite answer, because it is chosen by fit and not by a rule", () => {
    const up = screenUpFor([0, 1, 0], LONG_IN_Z, 0.5);
    // a tall narrow stage wants the long axis UP it, so the long extent is the vertical one
    expect(extentAlong(LONG_IN_Z, up)).toBeCloseTo(1.75, 9);
  });

  it("shrinks the frustum it needs, which is the measurable point of turning at all", () => {
    const turned = fitOrthoHalfHeight(LONG_IN_Z, [0, 1, 0], 1.4);
    // what the un-turned basis would have needed: the long extent up the screen
    expect(turned).toBeLessThan(1.75 * 1.15);
    expect(turned).toBeCloseTo((1.75 / 1.4) * 1.15, 6);
  });

  it("does not turn a view that is not looking along the vertical", () => {
    // Only the degenerate case has a free choice. Rotating an iso view to fit would tilt the
    // horizon, which is a different thing entirely from choosing an undefined rotation.
    expect(screenUpFor([0.55, 0.42, 1], LONG_IN_Z, 1.4)).toEqual([0, 1, 0]);
  });

  it("keeps the footprint-frame answer when the subject is square, so the choice is stable", () => {
    // equal extents make both bases cost the same; the tie must not flap between frames
    const square: [number, number, number] = [1, 0.3, 1];
    expect(screenUpFor([0, 1, 0], square, 1.4)).toEqual([0, 0, -1]);
  });
});
