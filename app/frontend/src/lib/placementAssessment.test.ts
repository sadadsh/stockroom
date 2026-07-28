import { assessPlacement } from "./placementAssessment";

const pads = [
  { at: [-1, 0] as [number, number], size: [1, 1] as [number, number], rotation: 0 },
  { at: [1, 0] as [number, number], size: [1, 1] as [number, number], rotation: 0 },
];

describe("assessPlacement", () => {
  it("keeps a centered package at the board plane as plausible", () => {
    expect(
      assessPlacement({ min: [-1.2, 0, -0.6], max: [1.2, 0.8, 0.6] }, pads),
    ).toMatchObject({ status: "plausible", issues: [] });
  });

  it("flags gross unit and origin failures without pretending to validate correctness", () => {
    const result = assessPlacement(
      { min: [100, 50, 100], max: [1000, 950, 1000] },
      pads,
    );
    expect(result.status).toBe("suspect");
    expect(result.issues).toEqual(
      expect.arrayContaining([
        "Model scale is implausible for the pad field",
        "Model is far from the footprint origin",
        "Model height offset is implausible for the footprint",
      ]),
    );
  });

  it("reports unavailable when there is not enough evidence", () => {
    expect(assessPlacement(null, pads).status).toBe("unavailable");
    expect(assessPlacement({ min: [0, 0, 0], max: [1, 1, 1] }, []).status).toBe(
      "unavailable",
    );
  });

  it("accounts for pad rotation when deriving the land-pattern envelope", () => {
    const rotated = [{ at: [0, 0] as [number, number], size: [4, 1] as [number, number], rotation: 90 }];
    const result = assessPlacement(
      { min: [-0.5, 0, -1.8], max: [0.5, 1, 1.8] },
      rotated,
    );
    expect(result.status).toBe("plausible");
    expect(result.metrics.sizeRatio).toBeCloseTo(0.9);
  });
});
