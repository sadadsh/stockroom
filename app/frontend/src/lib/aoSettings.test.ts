import { describe, expect, it } from "vitest";
import { aoSettings } from "./threeScene";

// The ambient occlusion returned NOTHING for three sessions and looked exactly like a pass that was
// switched off, so the derivation that fixes it is pinned here. MEASURED on the pass's own AO
// buffer: stdev 0.00 / 2 levels before, stdev 3.20 / 114 levels after.
describe("aoSettings", () => {
  it("never uses a screen-space radius, which is what made the sampling sphere 2x the part", () => {
    // In screen-space mode the shader multiplies the radius by the world size of ~100px, which at
    // the distance this viewer frames a part from is ~0.4mm - so the old `radius: 18` became a ~7mm
    // sphere around a 3.5mm part, every sample escaped, and nothing was ever occluded.
    expect(aoSettings(1.9).screenSpaceRadius).toBe(false);
  });

  it("scales the sampling radius to the part, so it is not tuned for one package size", () => {
    // an 0402 chip and a 50mm connector must each get a radius at the scale of their OWN features
    const tiny = aoSettings(0.5);
    const huge = aoSettings(25);
    expect(huge.radius).toBeGreaterThan(tiny.radius);
    expect(tiny.radius / 0.5).toBeCloseTo(huge.radius / 25, 6);
  });

  it("keeps the radius well under the part, so samples find real contact rather than empty space", () => {
    for (const r of [0.5, 1.9, 8, 25]) {
      const { radius, thickness } = aoSettings(r);
      expect(radius).toBeGreaterThan(0);
      expect(radius).toBeLessThan(r); // the failure mode: a sphere bigger than the subject
      expect(thickness).toBeLessThan(radius); // an occluder must be CLOSE, not across the board
    }
  });

  it("stays positive for a degenerate model rather than emitting a zero radius", () => {
    expect(aoSettings(0).radius).toBeGreaterThan(0);
  });
});
