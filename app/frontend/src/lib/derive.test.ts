import { describe, expect, it } from "vitest";
import { deriveTitle, deriveAttributes } from "./derive";
import type { PartDetail } from "../api/types";

// A minimal PartDetail factory: only the fields the derivers read carry meaning; the rest
// are honest empty defaults so the record shape still type-checks.
function makePart(over: Partial<PartDetail>): PartDetail {
  return {
    id: "x",
    display_name: "",
    category: "",
    description: "",
    tags: [],
    mpn: "",
    manufacturer: "",
    datasheet: null,
    purchase: [],
    symbol: null,
    footprint: null,
    model: null,
    provenance: null,
    hashes: null,
    enrichment: {},
    specs: {},
    ...over,
  };
}

describe("deriveTitle", () => {
  it("builds a resistor masthead from resistance + tolerance + the noun", () => {
    const part = makePart({
      category: "Resistors",
      display_name: "1.10k 1% 0603 Panasonic ERJ-P03F1101V",
      specs: { Resistance: "1.1 kΩ", Tolerance: "±1%", Package: "0603" },
    });
    expect(deriveTitle(part)).toBe("1.1 kΩ ±1% Resistor");
  });

  it("builds a capacitor masthead from capacitance + voltage + dielectric", () => {
    const part = makePart({
      category: "Capacitors",
      specs: { Capacitance: "0.1 µF", Voltage: "16V", Dielectric: "X7R" },
    });
    expect(deriveTitle(part)).toBe("0.1 µF 16V X7R Capacitor");
  });

  it("falls back gracefully for an unknown category: first spec + a singularized noun", () => {
    const part = makePart({
      category: "Thermistors",
      display_name: "NTC 10K 3950",
      specs: { Resistance: "10 kΩ" },
    });
    expect(deriveTitle(part)).toBe("10 kΩ Thermistor");
  });

  it("titles a spec-less IC by its MPN, not a junk spec fragment", () => {
    const part = makePart({
      category: "ICs",
      mpn: "SN74LVC138AQPWREP",
      specs: { "Base Product Number": "LVC138", Function: "Decoder" },
    });
    // was "LVC IC" (first spec + noun); the MPN is the recognizable identifier instead
    expect(deriveTitle(part)).toBe("SN74LVC138AQPWREP");
  });

  it("titles a diode lacking rating specs by its MPN, not 'Single Diode'", () => {
    const part = makePart({
      category: "Diodes",
      mpn: "599-0160-137F",
      specs: { Configuration: "Single" },
    });
    expect(deriveTitle(part)).toBe("599-0160-137F");
  });

  it("keeps the category noun when a known category is missing its title specs", () => {
    const part = makePart({
      category: "Resistors",
      display_name: "raw dense name",
      specs: { Package: "0805" },
    });
    expect(deriveTitle(part)).toBe("0805 Resistor");
  });

  it("skips an empty-in-disguise registry spec when composing the title", () => {
    const part = makePart({
      category: "Capacitors",
      specs: { Capacitance: "0.1 µF", Voltage: "Not available", Dielectric: "X7R" },
    });
    expect(deriveTitle(part)).toBe("0.1 µF X7R Capacitor");
  });

  it("does not headline a non-defining junk spec: the 'China Connector' regression", () => {
    // Specs arrive alphabetically, so a country-of-origin lands first; the fallback must
    // never turn that into the headline. A connector earns its title from real specs.
    const part = makePart({
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
    });
    const title = deriveTitle(part);
    expect(title).not.toMatch(/china/i);
    expect(title).toBe("16 Contact Connector");
  });

  it("skips country / brand junk in the first-spec fallback for an unregistered category", () => {
    const part = makePart({
      category: "Sensors",
      display_name: "BME280",
      specs: {
        "Country of Origin": "China",
        Brand: "Bosch",
        "Supply Voltage": "3.3 V",
      },
    });
    expect(deriveTitle(part)).toBe("3.3 V Sensor");
  });

  it("falls back to the raw display_name when there is no usable spec", () => {
    const part = makePart({
      category: "Widgets",
      display_name: "ACME 1234 Whatsit",
      specs: {},
    });
    expect(deriveTitle(part)).toBe("ACME 1234 Whatsit");
  });

  it("never returns empty: an empty name falls through to the category", () => {
    const part = makePart({ category: "Sensors", display_name: "", specs: {} });
    expect(deriveTitle(part)).toBe("Sensors");
  });
});

describe("deriveAttributes", () => {
  it("derives the key parameters from specs, ranked electrical-first, and IGNORES tags", () => {
    const part = makePart({
      category: "Resistors",
      tags: ["Thin Film", "General Purpose"], // manual tags are NOT folded into derived attributes
      specs: {
        Resistance: "1.1 kΩ", // the headline value is in the title, so never a chip
        Tolerance: "1%",
        "Power Rating": "0.2 W",
        Package: "0603",
        Composition: "Thick Film",
        "Mounting Type": "SMD",
        RoHS: "Yes",
      },
    });
    const attrs = deriveAttributes(part);
    // tags are gone, the headline resistance is gone
    expect(attrs).not.toContain("Thin Film");
    expect(attrs).not.toContain("General Purpose");
    expect(attrs.some((a) => /kΩ/.test(a))).toBe(false);
    // the signed tolerance leads (Electrical), physical form + compliance follow
    expect(attrs[0]).toBe("±1%");
    expect(attrs).toContain("0603");
    expect(attrs).toContain("Surface Mount");
  });

  it("keeps the card small: no more than six chips", () => {
    const part = makePart({
      category: "Resistors",
      specs: {
        Tolerance: "1%",
        "Power Rating": "0.2 W",
        "Voltage Rating": "75 V",
        "Temperature Coefficient": "100 ppm/°C",
        Package: "0603",
        Composition: "Thick Film",
        "Mounting Type": "SMD",
        RoHS: "Yes",
        Qualification: "AEC-Q200",
      },
    });
    expect(deriveAttributes(part).length).toBeLessThanOrEqual(6);
  });

  it("maps a through-hole code and keeps a value that is already a label", () => {
    expect(
      deriveAttributes(makePart({ category: "Resistors", specs: { "Mounting Type": "THT" } })),
    ).toEqual(["Through Hole"]);
    expect(
      deriveAttributes(
        makePart({ category: "Resistors", specs: { "Mounting Type": "Through Hole" } }),
      ),
    ).toEqual(["Through Hole"]);
  });

  it("skips an empty-in-disguise spec value instead of chipping it", () => {
    const part = makePart({
      category: "Resistors",
      specs: { Package: "N/A", RoHS: "Yes" },
    });
    const attrs = deriveAttributes(part);
    expect(attrs).not.toContain("N/A");
    expect(attrs).toEqual(["RoHS Compliant"]);
  });

  it("emits no compliance chip for a non-compliant value", () => {
    const part = makePart({ category: "Resistors", specs: { RoHS: "No" } });
    expect(deriveAttributes(part)).toEqual([]);
  });

  it("skips commercial / provenance specs (tariff, country, packaging)", () => {
    const part = makePart({
      category: "Resistors",
      specs: {
        "US Tariff %": "8",
        "Assembly Country of Origin": "China",
        Packaging: "Tape & Reel",
        Package: "0603",
      },
    });
    expect(deriveAttributes(part)).toEqual(["0603"]);
  });
});
