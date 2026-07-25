import { describe, expect, it } from "vitest";
import { fitDistance, visibleBounds } from "./cameraFit";

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
});
