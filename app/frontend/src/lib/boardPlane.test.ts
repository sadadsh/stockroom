import { describe, expect, it } from "vitest";
import { PAD_THICKNESS_MM, boardPlaneThickness, boardStack } from "./boardPlane";

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

  it("puts the board box entirely BELOW the pads' top face", () => {
    const s = boardStack(BASE, H);
    const boardTop = s.boardCenterY + s.boardThickness / 2;
    expect(boardTop).toBeCloseTo(s.padGroupY, 10);
    expect(boardTop).toBeLessThan(s.padTopY);
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

describe("PAD_THICKNESS_MM", () => {
  it("is a real copper thickness, not zero", () => {
    // A zero-height pad cannot catch a highlight or cast a contact shadow. It also has to be
    // shared with the stacking maths, which is why it is exported rather than inlined in a loop.
    expect(PAD_THICKNESS_MM).toBeGreaterThan(0);
    expect(PAD_THICKNESS_MM).toBeLessThan(0.2);
  });
});
