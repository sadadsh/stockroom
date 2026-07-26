import { describe, expect, it } from "vitest";
import {
  BOARD_PLANE_MIN_ASPECT,
  BOARD_PLANE_MIN_HALF_MM,
  BOARD_PLANE_REACH,
  PAD_THICKNESS_MM,
  boardExtent,
  boardPlaneHalfExtents,
  boardPlaneThickness,
  boardStack,
  PAD_EMBED_FRACTION,
  DEFAULT_LAYERS,
  silkQuad,
} from "./boardPlane";

// Owner 2026-07-26: "the 3d model clips into the pads and pcb. the pcb should be a plane less than
// its own component." Both halves are geometry, so both are testable without a GL context.
describe("boardPlaneThickness", () => {
  it("is THINNER than the component for a part shorter than the old fixed 0.6mm board", () => {
    // The real case that prompted this: a USON-14 body is ~0.55mm tall, so the old fixed 0.6mm
    // board was THICKER than the component sitting on it and dominated the frame.
    const h = 0.55;
    const t = boardPlaneThickness(h);
    expect(t).toBeLessThan(h);
    expect(t).toBeCloseTo(0.22, 5);
  });

  it("stays a thin plane under a TALL part instead of scaling into a slab", () => {
    // An electrolytic can is ~10mm; 40% of that would be a 4mm slab, so the cap holds.
    expect(boardPlaneThickness(10)).toBeCloseTo(0.6, 5);
  });

  it("is thinner than the component at EVERY height, which is the actual invariant", () => {
    for (const h of [0.05, 0.1, 0.25, 0.55, 1, 1.5, 1.6, 3, 10, 100]) {
      expect(boardPlaneThickness(h)).toBeLessThan(h);
    }
  });

  it("never returns zero or a negative, which would make the board vanish or invert", () => {
    for (const h of [0.05, 0.55, 10]) {
      expect(boardPlaneThickness(h)).toBeGreaterThan(0);
    }
  });

  it("falls back to the previous fixed thickness when the height is unknown", () => {
    // A model whose bounds could not be measured must not produce NaN geometry: three.js would
    // silently render nothing and the board would simply be missing.
    for (const bad of [0, -1, Number.NaN, Number.POSITIVE_INFINITY]) {
      expect(boardPlaneThickness(bad)).toBeCloseTo(0.6, 5);
    }
  });
});

// These are the relationships a perspective render cannot settle. Measuring the board's projected
// side face against the pads' gave 2.8x on one attempt and a contradictory figure on another, because
// a vertical world distance under a 3/4 perspective camera is not recoverable from pixels. The
// geometry contract IS exactly checkable, so it is checked here rather than estimated from a shot.
describe("boardStack (the clipping fix, as an invariant)", () => {
  const H = 0.55; // USON-14 body height in mm
  const BASE = -H / 2; // the model is centred, so its base is -size.y/2

  it("puts a pad's TOP exactly on the component's underside, never inside it", () => {
    const s = boardStack(BASE, H);
    expect(s.padTopY).toBeCloseTo(BASE, 10);
  });

  it("puts the board's TOP one pad-thickness below the component base", () => {
    const s = boardStack(BASE, H);
    // this is the whole bug: both used to sit AT the base, so the pads were driven into the body
    expect(s.padGroupY).toBeCloseTo(BASE - PAD_THICKNESS_MM, 10);
    expect(BASE - s.padGroupY).toBeCloseTo(PAD_THICKNESS_MM, 10);
  });

  it("leaves NO overlap between the component body and the pads", () => {
    const s = boardStack(BASE, H);
    // the pad occupies padGroupY .. padGroupY + PAD_THICKNESS_MM, and the body starts at BASE
    const padTop = s.padGroupY + PAD_THICKNESS_MM;
    expect(padTop).toBeLessThanOrEqual(BASE + 1e-9);
  });

  it("sinks the pads HALFWAY into the plate, so copper reads as part of the stack", () => {
    // Owner, 2026-07-26: "the 3D footprint should sit WITHIN the pcb plate, not lay on top of it."
    // The board's top face rises to the pads' mid-height - not to their top, which would bury the
    // land pattern completely and lose the thing the layer exists to show.
    const s = boardStack(BASE, H);
    const boardTop = s.boardCenterY + s.boardThickness / 2;
    expect(boardTop).toBeCloseTo(s.padGroupY + PAD_THICKNESS_MM * PAD_EMBED_FRACTION, 10);
    expect(boardTop).toBeGreaterThan(s.padGroupY); // embedded, not merely resting on the surface
    expect(boardTop).toBeLessThan(s.padTopY); // still visible, not swallowed
  });

  it("does NOT move the component down to do it", () => {
    // The regression `cae5a81` fixed, and the one the owner reported as "the 3d model clips into
    // the pads and pcb": embedding the pads must raise the BOARD, never lower the body.
    const s = boardStack(BASE, H);
    expect(s.padTopY).toBeCloseTo(BASE, 10);
    expect(s.padGroupY).toBeCloseTo(BASE - PAD_THICKNESS_MM, 10);
  });

  it("keeps the board thinner than the component at every height", () => {
    for (const h of [0.05, 0.2, 0.55, 1.6, 10]) {
      expect(boardStack(-h / 2, h).boardThickness).toBeLessThan(h);
    }
  });

  it("survives an unmeasurable component without producing NaN geometry", () => {
    const s = boardStack(0, Number.NaN);
    for (const v of [s.boardThickness, s.padGroupY, s.boardCenterY, s.padTopY]) {
      expect(Number.isFinite(v)).toBe(true);
    }
  });
});

// Owner: "the footprint needs to be accurate to whats downloaded, not just the pads." The graphics
// were all extracted correctly by the backend (fp_line/rect/circle/poly/arc) and then drawn with
// THREE.Line, whose width WebGL ignores - so every one became a 1px hairline that vanished at tile
// size. These lock the quad that replaces it, including the widths that must NOT be lost.
describe("silkQuad (the footprint's real ink width)", () => {
  it("centres the quad on the segment and takes its length", () => {
    const q = silkQuad([0, 0], [2, 0], 0.12);
    expect(q).not.toBeNull();
    expect(q?.cx).toBeCloseTo(1, 10);
    expect(q?.cz).toBeCloseTo(0, 10);
    expect(q?.length).toBeCloseTo(2, 10);
  });

  it("KEEPS the footprint's own stroke width rather than discarding it", () => {
    // the whole point: 0.15mm silk must render 0.15mm wide, not one pixel
    expect(silkQuad([0, 0], [1, 0], 0.15)?.width).toBeCloseTo(0.15, 10);
    expect(silkQuad([0, 0], [1, 0], 0.05)?.width).toBeCloseTo(0.05, 10);
  });

  it("substitutes the board default for a zero or missing width, never a zero-area quad", () => {
    // KiCad treats width 0 as "use the default"; a 0-width quad would draw nothing at all.
    for (const bad of [0, -1, Number.NaN]) {
      expect(silkQuad([0, 0], [1, 0], bad)?.width).toBeCloseTo(0.12, 10);
    }
  });

  it("orients along the segment for each axis and diagonal", () => {
    expect(silkQuad([0, 0], [1, 0], 0.12)?.angleY).toBeCloseTo(0, 10);
    // +z direction: a rotation about +Y turns +z toward +x, so this is -90 degrees
    expect(silkQuad([0, 0], [0, 1], 0.12)?.angleY).toBeCloseTo(-Math.PI / 2, 10);
    expect(silkQuad([0, 0], [1, 1], 0.12)?.angleY).toBeCloseTo(-Math.PI / 4, 10);
  });

  it("is direction-agnostic: a segment drawn backwards covers the same ground", () => {
    const a = silkQuad([1, 2], [3, 4], 0.12);
    const b = silkQuad([3, 4], [1, 2], 0.12);
    expect(a?.cx).toBeCloseTo(b?.cx ?? -1, 10);
    expect(a?.cz).toBeCloseTo(b?.cz ?? -1, 10);
    expect(a?.length).toBeCloseTo(b?.length ?? -1, 10);
    // the quad is symmetric, so the two angles describe the same line
    expect(Math.abs((a?.angleY ?? 0) - (b?.angleY ?? 0))).toBeCloseTo(Math.PI, 10);
  });

  it("drops a zero-length segment instead of emitting a degenerate quad", () => {
    expect(silkQuad([1, 1], [1, 1], 0.12)).toBeNull();
  });
});

// Owner 2026-07-26, after the first attempt: "the 3d footprint looks horribly wrong now it looked way
// better before. the pcb render should legitimately add a plane to the 3d view not just another
// floating component." Two defects and one taste call, all locked here.
describe("boardExtent", () => {
  const pad = (x: number, z: number, w: number, h: number) =>
    ({ at: [x, z] as const, size: [w, h] as const });

  it("includes the pad's own SIZE, not just its centre", () => {
    // the bug: a span from centres alone left the board narrower than the pads standing on it
    const e = boardExtent([pad(1, 0, 0.6, 0.4)]);
    expect(e.halfX).toBeCloseTo(1.3, 10); // 1 + 0.6/2
    expect(e.halfZ).toBeCloseTo(0.2, 10);
  });

  it("includes silkscreen graphics, so nothing can hang off the board edge", () => {
    const e = boardExtent([pad(0, 0, 0.2, 0.2)], [{ start: [-3, -2], end: [3, 2] }]);
    expect(e.halfX).toBeCloseTo(3, 10);
    expect(e.halfZ).toBeCloseTo(2, 10);
  });

  it("covers a footprint whose graphics reach further than its pads", () => {
    const e = boardExtent([pad(0.5, 0, 0.4, 0.4)], [{ start: [-1.75, -0.9], end: [1.75, 0.9] }]);
    expect(e.halfX).toBeGreaterThanOrEqual(1.75);
    expect(e.halfZ).toBeGreaterThanOrEqual(0.9);
  });

  it("is zero for nothing at all, rather than NaN", () => {
    expect(boardExtent([])).toEqual({ halfX: 0, halfZ: 0 });
  });
});

// RE-BASELINED 2026-07-26. Owner: "The plane should be like infinite, and the view should be zoomed in
// and centered on the model." That pair replaces three attempts at SIZING the board (footprint-cropped,
// square 2.6x, per-axis with a floor ratio) - every one of which was solving the wrong problem, because
// the board only looked wrong relative to the part while the CAMERA was framing the board. The camera
// now ignores it, so the plane just runs past the frame.
// OWNER REVERSAL 2026-07-26: "the pcb should return to a flat plane properly sized for the
// component". Sized per axis again. The three attempts that FAILED before the infinite plane are
// pinned here so they are not re-walked: fully square (the owner's 3.5x1.4mm USON got a 6.3mm square,
// 4.5x its short axis, and read as lost), footprint-cropped (read as footprint-shaped, not a board),
// and per-axis with no floor (a long thin part got a long thin sliver, the same fault again).
describe("boardPlaneHalfExtents (sized to the component)", () => {
  it("grows each axis from its OWN extent, so an elongated part keeps its presence", () => {
    const p = boardPlaneHalfExtents({ halfX: 1.75, halfZ: 0.7 });
    expect(p.halfX).toBeGreaterThan(p.halfZ);
    expect(p.halfX).toBeCloseTo(1.75 * BOARD_PLANE_REACH, 6);
  });

  it("never lets the narrow axis become a sliver", () => {
    // a long thin part must still get a BOARD, not a strip that reads as the footprint again
    const p = boardPlaneHalfExtents({ halfX: 10, halfZ: 0.2 });
    expect(p.halfZ / p.halfX).toBeGreaterThanOrEqual(BOARD_PLANE_MIN_ASPECT - 1e-9);
  });

  it("gives a tiny part a real board rather than a chip of one", () => {
    const p = boardPlaneHalfExtents({ halfX: 0.2, halfZ: 0.1 });
    expect(p.halfX).toBeGreaterThanOrEqual(BOARD_PLANE_MIN_HALF_MM);
    expect(p.halfZ).toBeGreaterThanOrEqual(BOARD_PLANE_MIN_HALF_MM * BOARD_PLANE_MIN_ASPECT);
  });

  it("scales WITH the component, which is the whole point of the reversal", () => {
    const small = boardPlaneHalfExtents({ halfX: 1, halfZ: 1 });
    const large = boardPlaneHalfExtents({ halfX: 20, halfZ: 20 });
    expect(large.halfX).toBeGreaterThan(small.halfX * 5);
  });
});

describe("PAD_THICKNESS_MM", () => {
  it("is a real copper thickness, not zero", () => {
    // A zero-height pad cannot catch a highlight or cast a contact shadow. It also has to be
    // shared with the stacking maths, which is why it is exported rather than inlined in a loop.
    expect(PAD_THICKNESS_MM).toBeGreaterThan(0);
    expect(PAD_THICKNESS_MM).toBeLessThan(0.2);
  });
});

describe("DEFAULT_LAYERS", () => {
  // Owner 2026-07-26, chosen from previews over a stronger rim light and a lighter stage: the part
  // should sit on the board at load rather than float. Measured symptom it answers: in dark theme the
  // body's near side face read 53 against a 40 background (1.33:1) and the lower silhouette dissolved.
  it("draws the board at load, so the part is never floating on nothing", () => {
    expect(DEFAULT_LAYERS.board).toBe(true);
    expect(DEFAULT_LAYERS.model).toBe(true);
  });

  // NOT a style rule - geometry. boardStack deliberately puts the board's top face one pad thickness
  // BELOW the part's underside, because the part rests ON its pads. So a default that shows the board
  // while hiding the pads leaves the part hovering over exactly that gap, which is the owner's
  // "the 3d model clips into the pads and pcb" complaint inverted. Whoever changes one of these must
  // change the other, and this is what says so.
  it("never shows the board without the pads that hold the part up off it", () => {
    if (!DEFAULT_LAYERS.board) return;
    expect(DEFAULT_LAYERS.pads).toBe(true);

    // and the gap that makes the coupling necessary is real, not assumed
    const stack = boardStack(0, 0.55);
    expect(stack.padTopY - stack.padGroupY).toBeCloseTo(PAD_THICKNESS_MM, 10);
    expect(stack.padGroupY).toBeLessThan(stack.padTopY);
  });
});
