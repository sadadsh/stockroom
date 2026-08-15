import { describe, expect, it } from "vitest";
import {
  COMPONENT_LAND_PATTERN,
  COMPONENT_SYMBOL_GEOMETRY,
  fullComponentDossier,
} from "./componentFixtures";

describe("the LM358 visual acceptance fixture", () => {
  it("keeps the named eight-terminal part coherent with its symbol and SOIC-8 footprint", () => {
    const dossier = fullComponentDossier();
    expect(dossier.identity.mpn).toBe("LM358DR");
    expect(dossier.identity.package).toBe("SOIC-8");
    expect(dossier.identity.pinCount).toBe(8);
    expect(COMPONENT_SYMBOL_GEOMETRY.pins.map((pin) => pin.number).sort()).toEqual([
      "1",
      "2",
      "3",
      "4",
      "5",
      "6",
      "7",
      "8",
    ]);
    expect(COMPONENT_SYMBOL_GEOMETRY.graphics).toHaveLength(2);
    expect(COMPONENT_LAND_PATTERN.pads.map((pad) => pad.number).sort()).toEqual([
      "1",
      "2",
      "3",
      "4",
      "5",
      "6",
      "7",
      "8",
    ]);
    expect(
      COMPONENT_LAND_PATTERN.graphics.some((graphic) => graphic.layer.endsWith(".SilkS")),
    ).toBe(true);
    expect(
      COMPONENT_LAND_PATTERN.graphics.some((graphic) => graphic.layer.endsWith(".CrtYd")),
    ).toBe(true);
  });
});
