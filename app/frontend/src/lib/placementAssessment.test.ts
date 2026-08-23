import {
  assessPlacement,
  buriedSmdUprightAxis,
  repairBuriedSmdPlacement,
} from "./placementAssessment";

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

  it("rejects an SMD body that is mostly buried below the board", () => {
    const smdPads = pads.map((pad) => ({ ...pad, pad_type: "smd" }));
    const result = assessPlacement(
      { min: [-1.2, -1.6, -0.6], max: [1.2, 0.3, 0.6] },
      smdPads,
    );

    expect(result.status).toBe("suspect");
    expect(result.issues).toContain("SMD model crosses below the board plane");
    expect(result.metrics.belowBoardRatio).toBeGreaterThan(0.8);
  });

  it("repairs only a buried SMD body while preserving its authored size and rotation", () => {
    const smdPads = pads.map((pad) => ({ ...pad, pad_type: "smd" }));
    const buried = {
      min: [3.4, -1.6, -0.6] as [number, number, number],
      max: [5.8, 0.3, 0.6] as [number, number, number],
    };

    expect(repairBuriedSmdPlacement(buried, smdPads)).toEqual([-4.6, 1.6, 0]);
    expect(repairBuriedSmdPlacement(
      { min: [-1.2, 0, -0.6], max: [1.2, 0.8, 0.6] },
      smdPads,
    )).toBeNull();
    expect(repairBuriedSmdPlacement(buried, pads)).toBeNull();
  });

  it.each([
    ["16TDC220MD3", [-2.1504, -0.3400, -3.6500], [2.1504, 2.4650, 3.6500], [0, 0.34, 0]],
    ["T520V157M010ATE025", [-3.8, -1.645, 2.3], [3.8, 0.26, 6.9], [0, 1.645, -4.6]],
    ["0805 resistor", [-1.0, -1.35, -0.625], [1.0, 0, 0.625], [0, 1.35, 0]],
  ] as const)("repairs the real Mainline %s board crossing", (_name, min, max, expected) => {
    const smdPads = pads.map((pad) => ({ ...pad, pad_type: "smd" }));
    expect(repairBuriedSmdPlacement(
      { min: [...min], max: [...max] },
      smdPads,
    )).toEqual(expected);
  });

  it("stands sideways rectangular SMD bodies upright without laying down vertical cans", () => {
    const smdPads = pads.map((pad) => ({ ...pad, pad_type: "smd" }));
    expect(buriedSmdUprightAxis(
      { min: [-1.05, -1.35, -0.3], max: [1.05, 0, 0.3] },
      smdPads,
    )).toBe("z");
    expect(buriedSmdUprightAxis(
      { min: [-3.8, -1.645, 2.3], max: [3.8, 0.26, 6.9] },
      smdPads,
    )).toBeNull();
    expect(buriedSmdUprightAxis(
      { min: [-2.5, -5, -2.5], max: [2.5, 0, 2.5] },
      smdPads,
    )).toBeNull();
  });
});
