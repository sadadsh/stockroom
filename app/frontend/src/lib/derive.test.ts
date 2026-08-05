import { describe, expect, it } from "vitest";
import { deriveTitle } from "./derive";
import type { DeepPartial } from "fishery";
import type { PartDetail } from "../api/types";
import { makePartDetail } from "../test/partFixture";

// Only the fields the derivers read carry meaning here, so the shared wire-shaped factory is
// blanked down to empty defaults and each case fills in exactly what it is about. Blanking
// rather than re-declaring keeps this file on the one factory the API contract is pinned to.
function makePart(over: DeepPartial<PartDetail>): PartDetail {
  // `derived` is destructured and merged rather than spread wholesale: a plain `...over` would
  // REPLACE the blanked block, so the factory's own defaults ("LM358", "Dual op-amp") would leak
  // back in - and the fallback cases below assert precisely what happens when those are EMPTY.
  const { derived, ...rest } = over;
  return makePartDetail({
    id: "x",
    mpn: "",
    manufacturer: "",
    derived: { display_name: "", value: "", category: "", description: "", specs: {}, ...derived },
    ...rest,
  });
}

describe("deriveTitle", () => {
  it("builds a resistor masthead from resistance + tolerance + the noun", () => {
    const part = makePart({
      derived: {
        category: "Resistors",
        display_name: "1.10k 1% 0603 Panasonic ERJ-P03F1101V",
        specs: { Resistance: "1.1 kΩ", Tolerance: "±1%", Package: "0603" },
      },
    });
    expect(deriveTitle(part)).toBe("1.1 kΩ ±1% Resistor");
  });

  it("builds a capacitor masthead from capacitance + voltage + dielectric", () => {
    const part = makePart({
      derived: {
        category: "Capacitors",
        specs: { Capacitance: "0.1 µF", Voltage: "16V", Dielectric: "X7R" },
      },
    });
    expect(deriveTitle(part)).toBe("0.1 µF 16V X7R Capacitor");
  });

  it("falls back gracefully for an unknown category: first spec + a singularized noun", () => {
    const part = makePart({
      derived: {
        category: "Thermistors",
        display_name: "NTC 10K 3950",
        specs: { Resistance: "10 kΩ" },
      },
    });
    expect(deriveTitle(part)).toBe("10 kΩ Thermistor");
  });

  it("titles a spec-less IC by its MPN, not a junk spec fragment", () => {
    const part = makePart({
      mpn: "SN74LVC138AQPWREP",
      derived: {
        category: "ICs",
        specs: { "Base Product Number": "LVC138", Function: "Decoder" },
      },
    });
    // was "LVC IC" (first spec + noun); the MPN is the recognizable identifier instead
    expect(deriveTitle(part)).toBe("SN74LVC138AQPWREP");
  });

  it("titles a diode lacking rating specs by its MPN, not 'Single Diode'", () => {
    const part = makePart({
      mpn: "599-0160-137F",
      derived: {
        category: "Diodes",
        specs: { Configuration: "Single" },
      },
    });
    expect(deriveTitle(part)).toBe("599-0160-137F");
  });

  it("keeps the category noun when a known category is missing its title specs", () => {
    const part = makePart({
      derived: {
        category: "Resistors",
        display_name: "raw dense name",
        specs: { Package: "0805" },
      },
    });
    expect(deriveTitle(part)).toBe("0805 Resistor");
  });

  it("skips an empty-in-disguise registry spec when composing the title", () => {
    const part = makePart({
      derived: {
        category: "Capacitors",
        specs: { Capacitance: "0.1 µF", Voltage: "Not available", Dielectric: "X7R" },
      },
    });
    expect(deriveTitle(part)).toBe("0.1 µF X7R Capacitor");
  });

  it("does not headline a non-defining junk spec: the 'China Connector' regression", () => {
    // Specs arrive alphabetically, so a country-of-origin lands first; the fallback must
    // never turn that into the headline. A connector earns its title from real specs.
    const part = makePart({
      derived: {
        category: "Connectors",
        display_name: "USB4105-GF-A Top-Mount GCT",
        specs: {
        "Assembly Country of Origin": "China",
        Brand: "GCT",
        Color: "Black",
        "Contact Material": "Copper Alloy",
        "Number of Contacts": "16 Contact",
        Gender: "Receptacle (Female)",
        "Mounting Style": "Top-Mount",
      },
      },
    });
    const title = deriveTitle(part);
    expect(title).not.toMatch(/china/i);
    expect(title).toBe("16 Contact Connector");
  });

  it("skips country / brand junk in the first-spec fallback for an unregistered category", () => {
    const part = makePart({
      derived: {
        category: "Sensors",
        display_name: "BME280",
        specs: {
        "Country of Origin": "China",
        Brand: "Bosch",
        "Supply Voltage": "3.3 V",
      },
      },
    });
    expect(deriveTitle(part)).toBe("3.3 V Sensor");
  });

  it("falls back to the raw display_name when there is no usable spec", () => {
    const part = makePart({
      derived: {
        category: "Widgets",
        display_name: "ACME 1234 Whatsit",
        specs: {},
      },
    });
    expect(deriveTitle(part)).toBe("ACME 1234 Whatsit");
  });

  it("never returns empty: an empty name falls through to the category", () => {
    const part = makePart({ derived: { category: "Sensors", display_name: "", specs: {} } });
    expect(deriveTitle(part)).toBe("Sensors");
  });
});
