import { describe, it, expect } from "vitest";
import type { ParametricFacet } from "../api/types";
import {
  activeChips,
  cellValue,
  clearAll,
  clearRange,
  deriveColumns,
  emptyFilters,
  formatMagnitude,
  hasAnyFilter,
  parseMagnitude,
  isOptionOn,
  removeOption,
  setRange,
  toSpecParams,
  toggleOption,
  type SearchFilters,
} from "./searchFilters";

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
