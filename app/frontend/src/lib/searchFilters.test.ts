import { describe, it, expect } from "vitest";
import type { ParametricFacet } from "../api/types";
import {
  activeChips,
  applyClientFilters,
  PRICE_KEY,
  cellValue,
  clearAll,
  clearRange,
  deriveColumns,
  emptyFilters,
  formatMagnitude,
  hasAnyFilter,
  makeScale,
  parseMagnitude,
  isOptionOn,
  orderFacetsForRail,
  removeOption,
  rowPrimaryValue,
  rowMergedValue,
  sectionedRail,
  setRange,
  toSpecParams,
  toggleOption,
  type SearchFilters,
  VALUE_COLUMN_KEY,
} from "./searchFilters";

const MIXED_FACETS: ParametricFacet[] = [
  { key: "Resistance", label: "Resistance", kind: "range", count: 30, min: 100, max: 100000, unit: "Ω" },
  { key: "Capacitance", label: "Capacitance", kind: "range", count: 25, min: 1e-12, max: 1e-3, unit: "F" },
  { key: "Inductance", label: "Inductance", kind: "range", count: 12, min: 1e-9, max: 1e-3, unit: "H" },
  { key: "Package", label: "Package", kind: "options", count: 60, options: [
      { value: "0603", count: 30 }, { value: "0402", count: 20 }, { value: "0805", count: 10 }] },
];

const FACETS: ParametricFacet[] = [
  { key: "Resistance", label: "Resistance", kind: "range", count: 40, min: 100, max: 100000, unit: "Ω" },
  { key: "Tolerance", label: "Tolerance", kind: "range", count: 40, min: 0.1, max: 5, unit: "%" },
  { key: "Power", label: "Power", kind: "range", count: 38, min: 0.1, max: 0.25, unit: "W" },
  { key: "Package", label: "Package", kind: "options", count: 42, options: [
      { value: "0603", count: 30 }, { value: "0402", count: 8 }, { value: "0805", count: 4 }] },
  { key: "RoHS", label: "RoHS", kind: "options", count: 42, options: [{ value: "Yes", count: 42 }] },
];

describe("formatMagnitude", () => {
  it("applies SI prefixes only to prefixable units", () => {
    expect(formatMagnitude(1000, "Ω")).toBe("1 kΩ");
    expect(formatMagnitude(100000, "Ω")).toBe("100 kΩ");
    expect(formatMagnitude(0.1, "W")).toBe("100 mW");
    expect(formatMagnitude(0.000001, "F")).toBe("1 µF");
  });
  it("leaves non-prefixable units un-prefixed", () => {
    expect(formatMagnitude(5, "%")).toBe("5%");
    expect(formatMagnitude(0.1, "%")).toBe("0.1%");
    expect(formatMagnitude(155, "°C")).toBe("155 °C");
  });
  it("canonicalizes a spelled-out Ohm so it prefixes like Ω", () => {
    expect(formatMagnitude(1000000, "Ohms")).toBe("1 MΩ");
    expect(formatMagnitude(1000, "Ohm")).toBe("1 kΩ");
  });
});

describe("toSpecParams", () => {
  it("encodes option values as repeated <key>:<value> tokens (OR within a key)", () => {
    const f: SearchFilters = { ...emptyFilters(), options: { Package: ["0603", "0402"] } };
    expect(toSpecParams(f)).toEqual(["Package:0603", "Package:0402"]);
  });
  it("encodes a range as <key>:<min>~<max>, blank side for open-ended", () => {
    expect(toSpecParams(setRange(emptyFilters(), "Resistance", { min: 1000, max: 10000 })))
      .toEqual(["Resistance:1000~10000"]);
    expect(toSpecParams(setRange(emptyFilters(), "Resistance", { min: 1000, max: null })))
      .toEqual(["Resistance:1000~"]);
    expect(toSpecParams(setRange(emptyFilters(), "Resistance", { min: null, max: 10000 })))
      .toEqual(["Resistance:~10000"]);
  });
  it("never encodes the category (it rides its own param)", () => {
    expect(toSpecParams({ ...emptyFilters(), category: "Resistors" })).toEqual([]);
  });
});

describe("option mutators", () => {
  it("toggles a value on and back off, dropping the key when empty", () => {
    let f = toggleOption(emptyFilters(), "Package", "0603");
    expect(isOptionOn(f, "Package", "0603")).toBe(true);
    expect(f.options).toEqual({ Package: ["0603"] });
    f = toggleOption(f, "Package", "0603");
    expect(f.options).toEqual({});
  });
  it("removeOption prunes just that value", () => {
    const f: SearchFilters = { ...emptyFilters(), options: { Package: ["0603", "0402"] } };
    expect(removeOption(f, "Package", "0603").options).toEqual({ Package: ["0402"] });
  });
});

describe("setRange / clearRange", () => {
  it("clears the key when both bounds are null", () => {
    const f = setRange(emptyFilters(), "Resistance", { min: 1000, max: null });
    expect(clearRange(f, "Resistance").ranges).toEqual({});
    expect(setRange(f, "Resistance", { min: null, max: null }).ranges).toEqual({});
  });
});

describe("activeChips", () => {
  it("lists category first, then options, then ranges with readable range labels", () => {
    let f = emptyFilters();
    f = { ...f, category: "Resistors" };
    f = toggleOption(f, "Package", "0603");
    f = setRange(f, "Resistance", { min: 1000, max: 10000 });
    const chips = activeChips(f, FACETS);
    expect(chips.map((c) => [c.keyLabel, c.value])).toEqual([
      ["Category", "Resistors"],
      ["Package", "0603"],
      ["Resistance", "1 kΩ – 10 kΩ"],
    ]);
  });
  it("a chip's remove returns the filters without exactly that chip", () => {
    let f = emptyFilters();
    f = toggleOption(f, "Package", "0603");
    f = setRange(f, "Resistance", { min: 1000, max: 10000 });
    const chips = activeChips(f, FACETS);
    const pkgChip = chips.find((c) => c.keyLabel === "Package")!;
    expect(pkgChip.remove.options).toEqual({});
    expect(pkgChip.remove.ranges).toEqual({ Resistance: { min: 1000, max: 10000 } });
  });
});

describe("hasAnyFilter / clearAll", () => {
  it("is false only when nothing is selected", () => {
    expect(hasAnyFilter(emptyFilters())).toBe(false);
    expect(hasAnyFilter({ ...emptyFilters(), inStock: true })).toBe(true);
    expect(hasAnyFilter({ ...emptyFilters(), category: "Resistors" })).toBe(true);
  });
  it("clearAll drops parametric selections + stock but keeps the category scope", () => {
    let f: SearchFilters = { ...emptyFilters(), category: "Resistors", inStock: true };
    f = toggleOption(f, "Package", "0603");
    const cleared = clearAll(f);
    expect(cleared).toEqual({ category: "Resistors", options: {}, ranges: {}, inStock: false });
  });
});

describe("deriveColumns", () => {
  it("ranks by parameter group (electrical params first), drops single-valued + commercial", () => {
    const withNoise: ParametricFacet[] = [
      ...FACETS,
      { key: "Factory Pack Quantity", label: "Factory Pack Quantity", kind: "range", count: 88, min: 100, max: 10000 },
      { key: "US Tariff %", label: "US Tariff %", kind: "range", count: 80, min: 0, max: 8 },
    ];
    const cols = deriveColumns(withNoise, "Resistors", 5);
    // electrical parameters win; the commercial ranges never appear despite high counts
    expect(cols.map((c) => c.key)).toEqual(["Resistance", "Tolerance", "Power", "Package"]);
    expect(cols.some((c) => /tariff|pack quantity/i.test(c.key))).toBe(false);
    // RoHS (every part "Yes") is a useless column and is excluded
    expect(cols.some((c) => c.key === "RoHS")).toBe(false);
    // a range column is numeric (right-aligned mono) and carries its unit
    expect(cols[0]).toMatchObject({ numeric: true, unit: "Ω" });
    expect(cols[3]).toMatchObject({ key: "Package", numeric: false });
  });
  it("honours the column cap", () => {
    expect(deriveColumns(FACETS, "Resistors", 2).map((c) => c.key)).toEqual([
      "Resistance",
      "Tolerance",
    ]);
  });

  it("collapses the primary-value columns into one adaptive Value column on a mixed list (FIX-05)", () => {
    const cols = deriveColumns(MIXED_FACETS, null, 5);
    const keys = cols.map((c) => c.key);
    // the separate resistance/capacitance/inductance columns are gone (no more dash soup)
    expect(keys).not.toContain("Resistance");
    expect(keys).not.toContain("Capacitance");
    expect(keys).not.toContain("Inductance");
    // exactly one synthetic Value column, in the highest-ranked primary slot, non-numeric
    const valueCols = cols.filter((c) => c.key === VALUE_COLUMN_KEY);
    expect(valueCols).toHaveLength(1);
    expect(valueCols[0]).toMatchObject({ label: "Value", numeric: false });
    expect(keys[0]).toBe(VALUE_COLUMN_KEY);
    // every OTHER ranked column is retained
    expect(keys).toContain("Package");
  });

  it("collapses duplicate same-label columns into one adaptive column (FIX-09)", () => {
    // Two distinct spec keys ("Voltage Rating" for resistors, "Voltage Rating DC" for caps) both
    // resolve to the label "Voltage Rating" - pre-fix that produced two half-dashes columns.
    const facets: ParametricFacet[] = [
      { key: "Voltage Rating", label: "Voltage Rating", kind: "range", count: 40, min: 16, max: 200 },
      { key: "Voltage Rating DC", label: "Voltage Rating DC", kind: "range", count: 30, min: 6.3, max: 100 },
      { key: "Tolerance", label: "Tolerance", kind: "range", count: 50, min: 1, max: 10 },
    ];
    const cols = deriveColumns(facets, null, 5);
    const voltage = cols.filter((c) => c.label === "Voltage Rating");
    // exactly ONE "Voltage Rating" column (the two keys are merged, no more dash soup)
    expect(voltage).toHaveLength(1);
    // it carries both constituent keys so each row resolves its own value
    expect(voltage[0].keys).toEqual(
      expect.arrayContaining(["Voltage Rating", "Voltage Rating DC"]),
    );
    expect(voltage[0].numeric).toBe(false);
  });

  it("rowMergedValue resolves each row's value from whichever constituent key it carries (FIX-09)", () => {
    const keys = ["Voltage Rating", "Voltage Rating DC"];
    // a resistor row (plain key) and a cap row (DC key) each resolve their own value
    expect(rowMergedValue({ "Voltage Rating": "75 V" }, keys)).not.toBe("—");
    expect(rowMergedValue({ "Voltage Rating DC": "50 VDC" }, keys)).toBe(
      cellValue({ "Voltage Rating DC": "50 VDC" }, "Voltage Rating DC"),
    );
    // a row with neither key falls back to the em dash
    expect(rowMergedValue({ Package: "0603" }, keys)).toBe("—");
  });

  it("leaves a single-category list's columns unchanged (Resistance keeps its own column)", () => {
    const keys = deriveColumns(FACETS, "Resistors", 5).map((c) => c.key);
    expect(keys).toContain("Resistance");
    expect(keys).not.toContain(VALUE_COLUMN_KEY);
  });

  it("does not collapse a mixed list with only ONE primary-value parameter", () => {
    const onePrimary = MIXED_FACETS.filter(
      (f) => f.key !== "Capacitance" && f.key !== "Inductance",
    );
    const keys = deriveColumns(onePrimary, null, 5).map((c) => c.key);
    expect(keys).toContain("Resistance");
    expect(keys).not.toContain(VALUE_COLUMN_KEY);
  });
});

describe("rowPrimaryValue", () => {
  it("resolves each row's own primary value from its category primary spec", () => {
    expect(rowPrimaryValue("Resistors", { Resistance: "5.05 kOhms" })).toBe("5.05 kΩ");
    // matches the same prettify path cellValue uses for that spec
    expect(rowPrimaryValue("Capacitors", { Capacitance: "0.1 µF" })).toBe(
      cellValue({ Capacitance: "0.1 µF" }, "Capacitance"),
    );
    expect(rowPrimaryValue("Inductors", { Inductance: "4.7 µH" })).toBe(
      cellValue({ Inductance: "4.7 µH" }, "Inductance"),
    );
  });

  it("falls back to a present primary-value key for a ferrite bead (impedance)", () => {
    expect(rowPrimaryValue("Ferrite Beads", { Impedance: "600 Ohms" })).toBe("600 Ω");
  });

  it("is an em dash only when the row genuinely has no primary value", () => {
    expect(rowPrimaryValue("ICs", { "Product Type": "MCU" })).toBe("—");
    expect(rowPrimaryValue("Resistors", {})).toBe("—");
  });
});

describe("orderFacetsForRail", () => {
  it("floats electrical parameters to the top and sinks provenance/commercial to the bottom", () => {
    const mixed: ParametricFacet[] = [
      { key: "Assembly Country of Origin", label: "Assembly Country of Origin", kind: "options", count: 88, options: [{ value: "China", count: 40 }, { value: "Taiwan", count: 48 }] },
      { key: "Application", label: "Application", kind: "options", count: 40, options: [{ value: "General Purpose", count: 30 }, { value: "Automotive", count: 10 }] },
      { key: "Resistance", label: "Resistance", kind: "range", count: 34, min: 100, max: 100000, unit: "Ω" },
      { key: "US Tariff %", label: "US Tariff %", kind: "range", count: 80, min: 0, max: 8 },
    ];
    const order = orderFacetsForRail(mixed, "Resistors").map((f) => f.key);
    expect(order[0]).toBe("Resistance"); // the electrical range leads
    expect(order[order.length - 1]).toBe("US Tariff %"); // commercial sinks last
    expect(order.indexOf("Application")).toBeLessThan(order.indexOf("Assembly Country of Origin"));
  });
});

describe("applyClientFilters", () => {
  const rows = [
    { stock: 5000, unit_price: 0.31 },
    { stock: 0, unit_price: 0.02 },
    { stock: 100, unit_price: null },
    { stock: 8, unit_price: 1.5 },
  ];
  it("applies the In Stock toggle over the rows' stock", () => {
    const filters = { ...emptyFilters(), inStock: true };
    expect(applyClientFilters(rows, filters)).toEqual([rows[0], rows[2], rows[3]]);
  });
  it("applies the reserved Unit Price range and drops price-less rows", () => {
    const filters = setRange(emptyFilters(), PRICE_KEY, { min: 0.1, max: 1 });
    expect(applyClientFilters(rows, filters)).toEqual([rows[0]]);
  });
  it("the Unit Price range never leaves as a spec token (it is client-side)", () => {
    expect(toSpecParams(setRange(emptyFilters(), PRICE_KEY, { min: 0.1, max: 1 }))).toEqual([]);
  });
});

describe("sectionedRail", () => {
  it("buckets facets into the north-star sections, provenance last", () => {
    const facets: ParametricFacet[] = [
      { key: "Resistance", label: "Resistance", kind: "range", count: 34, min: 100, max: 100000, unit: "Ω" },
      { key: "Tolerance", label: "Tolerance", kind: "range", count: 34, min: 0.1, max: 5, unit: "%" },
      { key: "Package", label: "Package", kind: "options", count: 34, options: [{ value: "0603", count: 20 }, { value: "0402", count: 14 }] },
      { key: "RoHS", label: "RoHS", kind: "options", count: 34, options: [{ value: "Yes", count: 34 }] },
      { key: "Assembly Country of Origin", label: "Assembly Country of Origin", kind: "options", count: 34, options: [{ value: "China", count: 34 }] },
    ];
    const sections = sectionedRail(facets, "Resistors");
    expect(sections.map((s) => s.title)).toEqual([
      "Resistors Parameters",
      "Package & Form",
      "Ratings & Compliance",
      "More Filters",
    ]);
    // the generated parameter block carries the "from specs" badge; the rest do not
    expect(sections[0].fromSpecs).toBe(true);
    expect(sections.slice(1).every((s) => !s.fromSpecs)).toBe(true);
    // electrical params live under Parameters; provenance sinks to More Filters
    expect(sections[0].facets.map((f) => f.key)).toContain("Resistance");
    expect(sections[3].facets.map((f) => f.key)).toEqual(["Assembly Country of Origin"]);
  });

  it("routes manufacturer + Unit Price into a Sourcing section", () => {
    const facets: ParametricFacet[] = [
      { key: "Resistance", label: "Resistance", kind: "range", count: 34, min: 100, max: 100000, unit: "Ω" },
      { key: "Manufacturer", label: "Manufacturer", kind: "options", count: 34, options: [{ value: "Panasonic", count: 20 }, { value: "Yageo", count: 14 }] },
      { key: "__unit_price__", label: "Unit Price", kind: "range", count: 34, min: 0.1, max: 0.31, unit: "$" },
    ];
    const sections = sectionedRail(facets, "Resistors");
    const sourcing = sections.find((s) => s.title === "Sourcing");
    expect(sourcing?.facets.map((f) => f.key).sort()).toEqual(["Manufacturer", "__unit_price__"]);
  });
});

describe("makeScale", () => {
  it("uses a log scale for a range spanning >= 2 decades, decade ticks", () => {
    const s = makeScale(100, 100000); // 100 Ω .. 100 kΩ
    expect(s.log).toBe(true);
    // the midpoint by percent is the geometric mean, not the arithmetic one
    expect(s.fromPct(50)).toBeCloseTo(Math.sqrt(100 * 100000), 0);
    expect(s.toPct(1000)).toBeCloseTo(33.33, 0);
    expect(s.ticks).toEqual([100, 1000, 10000, 100000]); // clean decades incl. round endpoints
  });
  it("drops a non-round endpoint from the log ticks (leaves the decades)", () => {
    expect(makeScale(3.32, 1_000_000).ticks).toEqual([10, 100, 1000, 10000, 100000, 1000000]);
  });
  it("stays linear with nice round ticks for a narrow range", () => {
    const s = makeScale(50, 750); // 50 V .. 750 V
    expect(s.log).toBe(false);
    expect(s.fromPct(50)).toBe(400);
    expect(s.ticks).toEqual([200, 400, 600]);
  });
});

describe("parseMagnitude", () => {
  it("normalizes SI-prefixed spec values, null when non-numeric", () => {
    expect(parseMagnitude("10 kΩ")).toBe(10000);
    expect(parseMagnitude("220 Ω")).toBe(220);
    expect(parseMagnitude("5%")).toBe(5);
    expect(parseMagnitude("100 nF")).toBeCloseTo(1e-7);
    expect(parseMagnitude("Surface Mount")).toBeNull();
  });
});

describe("cellValue", () => {
  it("prettifies the part's own value, em dash when absent", () => {
    expect(cellValue({ Resistance: "10 kOhms" }, "Resistance")).toBe("10 kΩ");
    expect(cellValue({}, "Resistance")).toBe("—");
  });
});
