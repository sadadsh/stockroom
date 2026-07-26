import { describe, expect, it } from "vitest";
import { KEY_SPEC_LIMIT, keySpecRows, togglePinned } from "./keySpecs";
import type { SpecGroup } from "./specSchema";

// Owner 2026-07-26: "the important specifications should be where the eda handoff is, formatted like
// the specifications, but the most important details people care about when looking at this
// component, similar to what the eda looks for." They chose CURATED per category + user PINNING over
// auto-ranking, so a category's key set is registry DATA and a star can promote any row.
const row = (key: string, value = "1") => ({ key, label: key, value, raw: value });

const groups = (): SpecGroup[] => [
  {
    title: "Electrical",
    rows: [
      row("Diode Capacitance Cd", "0.5 pF"),
      row("Breakdown Voltage", "6 V"),
      row("Clamping Voltage", "14 V"),
      row("Peak Pulse Current (10/1000us)", "2.5 A"),
      row("Working Voltage", "5.5 V"),
      row("Some Irrelevant Parameter", "9"),
    ],
  },
  { title: "Physical", rows: [row("Package", "USON-14"), row("Mounting Type", "SMD")] },
  { title: "Other", rows: [row("Standard Pack Qty", "3000")] },
];

describe("keySpecRows (curated per category)", () => {
  it("picks the category's curated specs, in the registry's order not the sheet's", () => {
    const out = keySpecRows(groups(), "Diodes", {});
    const keys = out.map((r) => r.key);
    // Working Voltage is LAST in the Electrical group but leads the curated Diodes set
    expect(keys[0]).toBe("Working Voltage");
    expect(keys).toContain("Breakdown Voltage");
    expect(keys).toContain("Clamping Voltage");
  });

  it("leaves out a spec the category does not care about", () => {
    const keys = keySpecRows(groups(), "Diodes", {}).map((r) => r.key);
    expect(keys).not.toContain("Some Irrelevant Parameter");
    // procurement noise must never reach the hero block
    expect(keys).not.toContain("Standard Pack Qty");
  });

  it("matches a spec whose real key is wordier than the registry term", () => {
    // the registry says "peak pulse current"; the record says "Peak Pulse Current (10/1000us)"
    const keys = keySpecRows(groups(), "Diodes", {}).map((r) => r.key);
    expect(keys).toContain("Peak Pulse Current (10/1000us)");
  });

  it("never exceeds the block's row budget", () => {
    expect(keySpecRows(groups(), "Diodes", {}).length).toBeLessThanOrEqual(KEY_SPEC_LIMIT);
  });

  it("falls back to universally-useful specs for an unknown category", () => {
    // A category with no curated set must not render an EMPTY hero block where the handoff used to
    // be - that would be a worse regression than showing approximately-right rows.
    const keys = keySpecRows(groups(), "Nonexistent Category", {}).map((r) => r.key);
    expect(keys.length).toBeGreaterThan(0);
    expect(keys).toContain("Package");
  });

  it("returns nothing when the part genuinely has no specs, rather than inventing rows", () => {
    expect(keySpecRows([], "Diodes", {})).toEqual([]);
  });

  it("skips a curated spec the part does not carry, without leaving a hole", () => {
    const sparse: SpecGroup[] = [{ title: "Electrical", rows: [row("Working Voltage", "5.5 V")] }];
    expect(keySpecRows(sparse, "Diodes", {}).map((r) => r.key)).toEqual(["Working Voltage"]);
  });
});

describe("keySpecRows (user pinning)", () => {
  it("promotes a pinned spec ahead of the curated ones", () => {
    const out = keySpecRows(groups(), "Diodes", { Diodes: ["Standard Pack Qty"] });
    expect(out[0].key).toBe("Standard Pack Qty");
  });

  it("pins are scoped to the category that pinned them", () => {
    const keys = keySpecRows(groups(), "Diodes", { Resistors: ["Standard Pack Qty"] });
    expect(keys.map((r) => r.key)).not.toContain("Standard Pack Qty");
  });

  it("does not duplicate a spec that is both curated and pinned", () => {
    const out = keySpecRows(groups(), "Diodes", { Diodes: ["Working Voltage"] });
    const seen = out.filter((r) => r.key === "Working Voltage");
    expect(seen).toHaveLength(1);
  });

  it("still honours the row budget once pins are added", () => {
    const many = { Diodes: ["Standard Pack Qty", "Some Irrelevant Parameter", "Mounting Type"] };
    expect(keySpecRows(groups(), "Diodes", many).length).toBeLessThanOrEqual(KEY_SPEC_LIMIT);
  });
});

describe("togglePinned", () => {
  it("adds a pin for a category that had none", () => {
    expect(togglePinned({}, "Diodes", "Working Voltage")).toEqual({
      Diodes: ["Working Voltage"],
    });
  });

  it("removes a pin that is already set, so the star is a toggle", () => {
    expect(togglePinned({ Diodes: ["Working Voltage"] }, "Diodes", "Working Voltage")).toEqual({
      Diodes: [],
    });
  });

  it("leaves other categories untouched", () => {
    const before = { Resistors: ["Resistance"] };
    expect(togglePinned(before, "Diodes", "Working Voltage")).toEqual({
      Resistors: ["Resistance"],
      Diodes: ["Working Voltage"],
    });
  });

  it("does not mutate the object it was given", () => {
    const before = { Diodes: ["A"] };
    togglePinned(before, "Diodes", "B");
    expect(before).toEqual({ Diodes: ["A"] });
  });
});
