import { captureRequirementsForEdas } from "./captureRequirements";

describe("captureRequirementsForEdas", () => {
  it("requests each selected EDA and one shared 3D model", () => {
    expect(captureRequirementsForEdas(["altium", "kicad"])).toEqual([
      "kicad_symbol",
      "kicad_footprint",
      "kicad_model",
      "altium_symbol",
      "altium_footprint",
    ]);
    expect(captureRequirementsForEdas(["altium"])).toEqual([
      "altium_symbol",
      "altium_footprint",
      "kicad_model",
    ]);
  });

  it("refuses an empty or unknown EDA selection", () => {
    expect(() => captureRequirementsForEdas([])).toThrow("Select at least one EDA");
    expect(() => captureRequirementsForEdas(["eagle" as "kicad"])).toThrow("Unknown EDA");
  });
});
