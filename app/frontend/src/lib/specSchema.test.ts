import { describe, expect, it } from "vitest";
import {
  deriveFacets,
  groupSpecs,
  normalizeSpecKey,
  splitValueUnit,
  prettifyValue,
  applySign,
  EMPTY_SPEC_VALUES,
  SPEC_HIDDEN_KEYS,
} from "./specSchema";

describe("normalizeSpecKey", () => {
  it("folds casing and punctuation to a canonical form", () => {
    expect(normalizeSpecKey("Voltage Rating")).toBe("voltage rating");
    expect(normalizeSpecKey("voltage_rating")).toBe("voltage rating");
    expect(normalizeSpecKey("Voltage / Rating")).toBe("voltage rating");
    expect(normalizeSpecKey("  Resistance  ")).toBe("resistance");
  });
});

describe("prettifyValue", () => {
  it("substitutes the real unit symbols (Ohm -> Ω, micro u -> µ, PPM -> ppm)", () => {
    expect(prettifyValue("1.1 kOhms")).toBe("1.1 kΩ");
    expect(prettifyValue("100 Ohm")).toBe("100 Ω");
    expect(prettifyValue("0.1 uF")).toBe("0.1 µF");
    expect(prettifyValue("100 PPM/C")).toBe("100 ppm/°C");
  });

  it("cleans a stray unary-sign space and a bare Celsius C", () => {
    expect(prettifyValue("+ 155 C")).toBe("+155 °C");
    expect(prettifyValue("125 C")).toBe("125 °C");
  });

  it("never mangles a bare code or a part number (no accidental substitutions)", () => {
    expect(prettifyValue("0603")).toBe("0603");
    expect(prettifyValue("0603C")).toBe("0603C"); // no space before C -> not a temperature
    expect(prettifyValue("Automotive Grade")).toBe("Automotive Grade");
    expect(prettifyValue("ERJ-P03F1101V")).toBe("ERJ-P03F1101V");
  });
});

describe("applySign", () => {
  it("prefixes ± on a signed quantity (tolerance, temp coefficient) without one", () => {
    expect(applySign("Tolerance", "1%")).toBe("±1%");
    expect(applySign("Temperature Coefficient", "100 ppm/°C")).toBe("±100 ppm/°C");
  });
  it("leaves a value that already carries a sign, and never touches an unsigned key", () => {
    expect(applySign("Tolerance", "±1%")).toBe("±1%");
    expect(applySign("Tolerance", "-40")).toBe("-40");
    expect(applySign("Resistance", "1.1 kΩ")).toBe("1.1 kΩ");
    expect(applySign("Package", "0603")).toBe("0603");
  });
});

describe("splitValueUnit", () => {
  it("splits a number + unit value for tabular alignment", () => {
    expect(splitValueUnit("10 kΩ")).toEqual({ value: "10", unit: "kΩ" });
    expect(splitValueUnit("100mA")).toEqual({ value: "100", unit: "mA" });
    expect(splitValueUnit("2.5 V")).toEqual({ value: "2.5", unit: "V" });
    expect(splitValueUnit("1,500")).toEqual({ value: "1,500" });
  });

  it("does not split a range or a non-numeric value", () => {
    expect(splitValueUnit("-40°C ~ 85°C")).toEqual({ value: "-40°C ~ 85°C" });
    expect(splitValueUnit("Surface Mount")).toEqual({ value: "Surface Mount" });
    expect(splitValueUnit("0603")).toEqual({ value: "0603" });
  });
});

describe("groupSpecs", () => {
  it("drops hidden keys and empty-in-disguise values", () => {
    const groups = groupSpecs("Resistors", {
      Symbol: "R",
      Footprint: "R_0603",
      "3D Model": "r.step",
      product_url: "https://x",
      pinout: [{ pin: "1", name: "A" }],
      Resistance: "10 kΩ",
      Tolerance: "Not available",
      Power: "",
      Dielectric: "N/A",
    });
    const rows = groups.flatMap((g) => g.rows);
    const keys = rows.map((r) => r.key);
    // only Resistance survives: the hidden keys + empty-in-disguise values are gone
    expect(keys).toEqual(["Resistance"]);
    // and it split into value + unit
    expect(rows[0]).toMatchObject({ label: "Resistance", value: "10", unit: "kΩ" });
  });

  it("orders groups Electrical -> Physical -> Ratings & Compliance -> Other", () => {
    const groups = groupSpecs("ICs", {
      "Operating Temperature": "-40 ~ 85",
      Package: "LQFP-48",
      Voltage: "3.3 V",
    });
    expect(groups.map((g) => g.title)).toEqual([
      "Electrical",
      "Physical",
      "Ratings & Compliance",
    ]);
  });

  it("routes an unknown, never-seen spec key to the fallback group instead of dropping it", () => {
    const groups = groupSpecs("Sensors", {
      "Warp Field Density": "42 mQ",
      Resistance: "1 kΩ",
    });
    const other = groups.find((g) => g.title === "Other");
    expect(other).toBeDefined();
    const other_keys = other!.rows.map((r) => r.key);
    expect(other_keys).toContain("Warp Field Density");
    // it kept its label (the raw key) and still split the value
    const warp = other!.rows.find((r) => r.key === "Warp Field Density")!;
    expect(warp).toMatchObject({ label: "Warp Field Density", value: "42", unit: "mQ" });
  });

  it("orders rows within a group by the registry order, deterministically", () => {
    // insertion order deliberately scrambled; registry order must win
    const groups = groupSpecs("Resistors", {
      Tolerance: "1%",
      Resistance: "10 kΩ",
      Power: "0.1 W",
    });
    const electrical = groups.find((g) => g.title === "Electrical")!;
    expect(electrical.rows.map((r) => r.label)).toEqual([
      "Resistance",
      "Tolerance",
      "Power",
    ]);
  });

  it("keeps two unknown keys in a stable insertion order", () => {
    const groups = groupSpecs("Other", {
      Zeta: "1",
      Alpha: "2",
    });
    const other = groups.find((g) => g.title === "Other")!;
    expect(other.rows.map((r) => r.key)).toEqual(["Zeta", "Alpha"]);
  });
});

describe("deriveFacets", () => {
  it("classifies a consistent-unit numeric spec as a range with min/max", () => {
    const facets = deriveFacets([
      { category: "Resistors", specs: { Resistance: "10 kΩ" } },
      { category: "Resistors", specs: { Resistance: "4.7 kΩ" } },
      { category: "Resistors", specs: { Resistance: "22 kΩ" } },
    ]);
    const res = facets.find((f) => f.key === "Resistance")!;
    expect(res.kind).toBe("range");
    expect(res.min).toBe(4.7);
    expect(res.max).toBe(22);
    expect(res.unit).toBe("kΩ");
  });

  it("classifies a string spec as a checkbox list with distinct values + counts", () => {
    const facets = deriveFacets([
      { category: "Resistors", specs: { "Mounting Type": "Surface Mount" } },
      { category: "Resistors", specs: { "Mounting Type": "Surface Mount" } },
      { category: "Resistors", specs: { "Mounting Type": "Through Hole" } },
    ]);
    const mt = facets.find((f) => f.key === "Mounting Type")!;
    expect(mt.kind).toBe("checkbox");
    // sorted by count desc, then value asc
    expect(mt.values).toEqual([
      { value: "Surface Mount", count: 2 },
      { value: "Through Hole", count: 1 },
    ]);
  });

  it("falls back to checkbox when the numeric values carry inconsistent units", () => {
    const facets = deriveFacets([
      { category: "Resistors", specs: { Resistance: "10 kΩ" } },
      { category: "Resistors", specs: { Resistance: "100 Ω" } },
    ]);
    const res = facets.find((f) => f.key === "Resistance")!;
    expect(res.kind).toBe("checkbox");
  });

  it("drops hidden keys and empty values, and orders facets by the registry", () => {
    const facets = deriveFacets([
      {
        category: "ICs",
        specs: {
          Symbol: "U",
          product_url: "https://x",
          Package: "LQFP-48",
          Voltage: "3.3 V",
          Tolerance: "Not available",
        },
      },
    ]);
    const keys = facets.map((f) => f.key);
    expect(keys).not.toContain("Symbol");
    expect(keys).not.toContain("product_url");
    expect(keys).not.toContain("Tolerance"); // empty-in-disguise -> no facet
    // Electrical (Voltage) precedes Physical (Package)
    expect(keys).toEqual(["Voltage", "Package"]);
  });

  it("routes an unknown facet key to the Other group without dropping it", () => {
    const facets = deriveFacets([
      { category: "Sensors", specs: { "Warp Field Density": "hi" } },
    ]);
    const warp = facets.find((f) => f.key === "Warp Field Density")!;
    expect(warp).toBeDefined();
    expect(warp.group).toBe("Other");
  });
});

describe("shared constants", () => {
  it("exposes the hidden keys and empty values the panel filtered by", () => {
    expect(SPEC_HIDDEN_KEYS.has("pinout")).toBe(true);
    expect(SPEC_HIDDEN_KEYS.has("Symbol")).toBe(true);
    expect(EMPTY_SPEC_VALUES.has("not available")).toBe(true);
  });
});
