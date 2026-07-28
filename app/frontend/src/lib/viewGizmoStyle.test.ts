import { describe, expect, it } from "vitest";
import { MONOCHROME_VIEW_GIZMO } from "./viewGizmoStyle";

function expectGray(color: number) {
  expect((color >> 16) & 0xff).toBe((color >> 8) & 0xff);
  expect((color >> 8) & 0xff).toBe(color & 0xff);
}

describe("MONOCHROME_VIEW_GIZMO", () => {
  it("uses only grayscale surfaces and interaction colours", () => {
    const colours = [
      MONOCHROME_VIEW_GIZMO.background.color,
      MONOCHROME_VIEW_GIZMO.background.hover.color,
      MONOCHROME_VIEW_GIZMO.corners.color,
      MONOCHROME_VIEW_GIZMO.corners.hover.color,
      MONOCHROME_VIEW_GIZMO.edges.color,
      MONOCHROME_VIEW_GIZMO.edges.hover.color,
      ...Object.values(MONOCHROME_VIEW_GIZMO.faces).flatMap((face) => [
        face.color,
        face.labelColor,
        face.border.color,
        face.hover.color,
        face.hover.labelColor,
        face.hover.border.color,
      ]),
    ];
    colours.forEach(expectGray);
  });

  it("names faces as camera destinations and keeps corner joints crisp", () => {
    expect(Object.values(MONOCHROME_VIEW_GIZMO.faces).map((face) => face.label)).toEqual([
      "RIGHT",
      "LEFT",
      "TOP",
      "BOTTOM",
      "FRONT",
      "BACK",
    ]);
    expect(MONOCHROME_VIEW_GIZMO.corners.enabled).toBe(true);
    expect(MONOCHROME_VIEW_GIZMO.corners.radius).toBeLessThanOrEqual(0.1);
    expect(MONOCHROME_VIEW_GIZMO.size).toBeGreaterThanOrEqual(100);
  });
});
