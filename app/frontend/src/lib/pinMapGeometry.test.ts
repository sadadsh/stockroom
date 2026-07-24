import { describe, expect, it } from "vitest";
import {
  ballGridHeaders,
  bgaRowIndex,
  perimeterLabels,
  pinMapGeometry,
} from "./pinMapGeometry";
import type { PinDTO, PinoutGeometryDTO } from "../api/types";

function pin(over: Partial<PinDTO>): PinDTO {
  return {
    position: "1",
    position_kind: "numeric",
    lqfp_side: null,
    bga_row: null,
    bga_col: null,
    canonical_pin_name: "PA0",
    raw_pin_name: "PA0",
    pin_type: "I/O",
    electrical_class: "io",
    category: "io",
    roles: [],
    functions: [],
    alternate_functions: [],
    five_v: null,
    supply: null,
    ...over,
  };
}

const QFP_GEOM: PinoutGeometryDTO = {
  body_shape: "qfp",
  pin_count: 4,
  rows: null,
  cols: null,
  pitch_mm: 0.5,
  has_center_pad: false,
};

const BGA_GEOM: PinoutGeometryDTO = {
  body_shape: "bga",
  pin_count: 4,
  rows: 2,
  cols: 2,
  pitch_mm: 0.8,
  has_center_pad: false,
};

const W = 400;
const H = 400;

describe("pinMapGeometry — perimeter (LQFP/QFN)", () => {
  it("places pads on the side their lqfp_side names, not the side an index split would imply", () => {
    // Position 1 is on the RIGHT here. A naive index split (per = n // 4) would put position 1 on
    // the left; consuming lqfp_side must land it on the right (CONTEXT decision 6).
    const pins = [
      pin({ position: "1", lqfp_side: "right" }),
      pin({ position: "2", lqfp_side: "top" }),
      pin({ position: "3", lqfp_side: "left" }),
      pin({ position: "4", lqfp_side: "bottom" }),
    ];
    const layout = pinMapGeometry(pins, QFP_GEOM, W, H);
    const at = (p: string) => layout.pins.find((x) => x.position === p)!;

    expect(at("1").side).toBe("right");
    // right-side pads sit at/beyond the body's right edge (past center)
    expect(at("1").rect.x).toBeGreaterThan(W / 2);
    // left pad sits left of center; top pad above center; bottom pad below center
    expect(at("3").rect.x).toBeLessThan(W / 2);
    expect(at("2").rect.y).toBeLessThan(H / 2);
    expect(at("4").rect.y).toBeGreaterThan(H / 2);
    // the body is a centered square
    expect(layout.body.w).toBeGreaterThan(0);
    expect(layout.body.w).toBe(layout.body.h);
  });

  it("draws a center thermal pad only when the package has one", () => {
    const pins = [pin({ position: "1", lqfp_side: "left" })];
    expect(pinMapGeometry(pins, QFP_GEOM, W, H).centerPad).toBeUndefined();
    expect(
      pinMapGeometry(pins, { ...QFP_GEOM, has_center_pad: true }, W, H).centerPad,
    ).toBeDefined();
  });
});

describe("pinMapGeometry — BGA/WLCSP ball grid", () => {
  it("maps the row letter skipping 'I'", () => {
    expect(bgaRowIndex("A")).toBe(0);
    expect(bgaRowIndex("H")).toBe(7);
    expect(bgaRowIndex("J")).toBe(8); // I is skipped, so J follows H
    expect(bgaRowIndex("Z")).toBe(24);
    expect(bgaRowIndex("AA")).toBe(25);
  });

  it("places present balls at their (row,col) and leaves a depopulated cell empty", () => {
    // A 2x2 grid with B2 depopulated: only A1, A2, B1 are populated.
    const pins = [
      pin({ position: "A1", position_kind: "alnum", bga_row: "A", bga_col: 1 }),
      pin({ position: "A2", position_kind: "alnum", bga_row: "A", bga_col: 2 }),
      pin({ position: "B1", position_kind: "alnum", bga_row: "B", bga_col: 1 }),
    ];
    const layout = pinMapGeometry(pins, BGA_GEOM, W, H);
    const at = (p: string) => layout.pins.find((x) => x.position === p);

    // exactly the three present balls, no phantom B2
    expect(layout.pins).toHaveLength(3);
    expect(at("B2")).toBeUndefined();

    // A1 and A2 share a row (same y); A2 is to the right of A1 (col 2 > col 1)
    expect(at("A1")!.rect.y).toBeCloseTo(at("A2")!.rect.y, 5);
    expect(at("A2")!.rect.x).toBeGreaterThan(at("A1")!.rect.x);
    // A1 and B1 share a column (same x); B1 is below A1 (row B > row A)
    expect(at("A1")!.rect.x).toBeCloseTo(at("B1")!.rect.x, 5);
    expect(at("B1")!.rect.y).toBeGreaterThan(at("A1")!.rect.y);
  });
});

describe("pinMapGeometry — degenerate input", () => {
  it("returns an empty, zero-body layout for no pins (never throws)", () => {
    const layout = pinMapGeometry([], QFP_GEOM, W, H);
    expect(layout.pins).toEqual([]);
    expect(layout.body).toEqual({ x: 0, y: 0, w: 0, h: 0 });
  });
});


describe("pin-number labels", () => {
  const geometry = {
    body_shape: "qfp" as const,
    pin_count: 4,
    rows: null,
    cols: null,
    pitch_mm: null,
    has_center_pad: false,
  };
  const perimeterPins = [
    { position: "1", lqfp_side: "left" },
    { position: "2", lqfp_side: "bottom" },
    { position: "3", lqfp_side: "right" },
    { position: "4", lqfp_side: "top" },
  ];

  it("perimeterLabels places one label per placed pad, outside its side", () => {
    const layout = pinMapGeometry(perimeterPins, geometry, 460, 460);
    const labels = perimeterLabels(layout);
    expect(labels.map((l) => l.position).sort()).toEqual(["1", "2", "3", "4"]);
    const byPos = Object.fromEntries(labels.map((l) => [l.position, l]));
    const rects = Object.fromEntries(layout.pins.map((p) => [p.position, p.rect]));
    expect(byPos["1"].x).toBeLessThan(rects["1"].x); // left label sits left of its pad
    expect(byPos["3"].x).toBeGreaterThan(rects["3"].x + rects["3"].w); // right label right of pad
    expect(byPos["4"].y).toBeLessThan(rects["4"].y); // top label above pad
    expect(byPos["2"].y).toBeGreaterThan(rects["2"].y + rects["2"].h); // bottom label below pad
  });

  it("ballGridHeaders derives row and column headers from the real balls, mirrored per edge", () => {
    const balls = [
      { position: "A1", bga_row: "A", bga_col: 1 },
      { position: "B2", bga_row: "B", bga_col: 2 },
    ];
    const layout = pinMapGeometry(balls, { ...geometry, body_shape: "bga" }, 460, 460);
    const { rows, cols } = ballGridHeaders(balls, layout);
    expect(rows.map((r) => r.text).sort()).toEqual(["A", "A", "B", "B"]);
    expect(cols.map((c) => c.text).sort()).toEqual(["1", "1", "2", "2"]);
  });

  it("returns nothing for an empty layout", () => {
    const empty = pinMapGeometry([], geometry, 460, 460);
    expect(perimeterLabels(empty)).toEqual([]);
    expect(ballGridHeaders([], empty)).toEqual({ rows: [], cols: [] });
  });
});
