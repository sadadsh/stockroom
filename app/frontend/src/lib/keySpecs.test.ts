import { describe, expect, it } from "vitest";
import {
  KEY_SPEC_LIMIT,
  effectiveKeySpecKeys,
  isCuratedOnly,
  keySpecRows,
  togglePinned,
  withoutPromoted,
} from "./keySpecs";
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

  it("matches the human LABEL, not only the raw distributor key", () => {
    // Found by looking at the render, not by a test: real records key specs the way the distributor
    // writes them - "Voltage - Breakdown (Min)" - while the registry terms are written the way a
    // person says it. Matching `key` alone promoted 2 of 7 curated specs on a real diode and silently
    // left the rest below.
    const distributorStyle: SpecGroup[] = [
      {
        title: "Electrical",
        rows: [
          { key: "Voltage - Breakdown (Min)", label: "Breakdown Voltage (Min)", value: "6.5 V", raw: "6.5 V" },
          { key: "Voltage - Clamping (Max) @ Ipp", label: "Clamping Voltage (Max) @ Ipp", value: "14 V", raw: "14 V" },
          { key: "Current - Peak Pulse (10/1000us)", label: "Peak Pulse Current", value: "2.5 A", raw: "2.5 A" },
        ],
      },
    ];
    const keys = keySpecRows(distributorStyle, "Diodes", {}).map((r) => r.label);
    expect(keys).toContain("Breakdown Voltage (Min)");
    expect(keys).toContain("Clamping Voltage (Max) @ Ipp");
    expect(keys).toContain("Peak Pulse Current");
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

// Owner 2026-07-26: "Promote not copy". A spec lifted into Key Specifications must LEAVE the list
// below, rather than appearing twice in one column.
//
// Researched before implementing, per the same message. Two findings shaped this: duplication in a
// data display "adds extra items without any value" (Pencil & Paper, enterprise data tables), and
// NN/G's framing that progressive disclosure is "sequencing information so the initial view
// communicates what matters most" - so promoting a row UP the column is sequencing, not hiding, and
// nothing is lost. Both risks the research implied are covered here: a count that no longer matches
// its rows, and a group emptied by promotion.
describe("withoutPromoted (promote, do not copy)", () => {
  const g = (): SpecGroup[] => [
    { title: "Electrical", rows: [row("Working Voltage"), row("Breakdown Voltage"), row("Extra")] },
    { title: "Physical", rows: [row("Package")] },
  ];

  it("removes a promoted row from the group it came from", () => {
    const out = withoutPromoted(g(), new Set(["Working Voltage"]));
    const electrical = out.find((x) => x.title === "Electrical")!;
    expect(electrical.rows.map((r) => r.key)).toEqual(["Breakdown Voltage", "Extra"]);
  });

  it("leaves rows that were NOT promoted exactly as they were", () => {
    const out = withoutPromoted(g(), new Set(["Working Voltage"]));
    expect(out.find((x) => x.title === "Physical")!.rows.map((r) => r.key)).toEqual(["Package"]);
  });

  it("DROPS a group whose every row was promoted, rather than leaving an empty disclosure", () => {
    // An empty titled group with a count of 0 is exactly the sort of empty state the punch list
    // already flags elsewhere: it reads as broken rather than as "nothing here".
    const out = withoutPromoted(g(), new Set(["Package"]));
    expect(out.map((x) => x.title)).toEqual(["Electrical"]);
  });

  it("leaves the group's own row count honest, since the count is derived from the rows", () => {
    // This was the objection to promoting at all: a count that still said 3 while showing 2 would
    // be a lie. It cannot happen while the count comes from `rows.length`.
    const out = withoutPromoted(g(), new Set(["Working Voltage", "Breakdown Veto"]));
    expect(out.find((x) => x.title === "Electrical")!.rows).toHaveLength(2);
  });

  it("is a no-op when nothing was promoted", () => {
    const before = g();
    const out = withoutPromoted(before, new Set());
    expect(out.map((x) => x.rows.length)).toEqual(before.map((x) => x.rows.length));
  });

  it("does not mutate the groups it was given, so a re-render cannot compound the removal", () => {
    const before = g();
    withoutPromoted(before, new Set(["Working Voltage"]));
    expect(before[0].rows).toHaveLength(3);
  });

  it("returns an empty list when every group empties, rather than a list of empty groups", () => {
    const out = withoutPromoted(g(), new Set(["Working Voltage", "Breakdown Voltage", "Extra", "Package"]));
    expect(out).toEqual([]);
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

// --- The star must read the EFFECTIVE state, not just the user's own pins. -----------------------
// Owner, 2026-07-26: "the pin system lets you pin a spec that is ALREADY in Top Specifications ...
// the star must read the EFFECTIVE state (curated-by-registry OR user-pinned)". Since the reversal
// to copy-not-promote, a curated row appears in BOTH places, and its star showed hollow in both -
// so the sheet offered to pin a row that was already at the top, and doing it burned one of the
// capped Top Specifications slots on a row that already had one.

describe("effectiveKeySpecKeys", () => {
  const groups = [
    {
      title: "ELECTRICAL",
      rows: [
        { key: "Breakdown Voltage", label: "Breakdown Voltage", value: "6", unit: "V" },
        { key: "Package", label: "Package", value: "USON-14" },
        { key: "Diode Capacitance Cd", label: "Diode Capacitance Cd", value: "0.5", unit: "pF" },
      ],
    },
  ] as unknown as Parameters<typeof effectiveKeySpecKeys>[0];

  it("includes a row the REGISTRY curated, which no user pin mentions", () => {
    const keys = effectiveKeySpecKeys(groups, "Diodes", {});
    // whatever the curated set for Diodes contains, the answer must equal what actually renders
    expect(keys).toEqual(new Set(keySpecRows(groups, "Diodes", {}).map((r) => r.key)));
    expect(keys.size).toBeGreaterThan(0);
  });

  it("includes a row the USER pinned", () => {
    const keys = effectiveKeySpecKeys(groups, "Diodes", {
      Diodes: ["Diode Capacitance Cd"],
    });
    expect(keys.has("Diode Capacitance Cd")).toBe(true);
  });

  it("is exactly the set of rows Top Specifications renders, so the star can never disagree", () => {
    const pinned = { Diodes: ["Package"] };
    expect(effectiveKeySpecKeys(groups, "Diodes", pinned)).toEqual(
      new Set(keySpecRows(groups, "Diodes", pinned).map((r) => r.key)),
    );
  });
});

describe("isCuratedOnly", () => {
  it("is true for a row that is up there by curation and NOT by a user pin", () => {
    // this is the row whose star must not offer to pin it again
    expect(isCuratedOnly(new Set(["Breakdown Voltage"]), {}, "Diodes", "Breakdown Voltage")).toBe(
      true,
    );
  });

  it("is false for a row the user pinned themselves, which stays unpinnable", () => {
    expect(
      isCuratedOnly(new Set(["Package"]), { Diodes: ["Package"] }, "Diodes", "Package"),
    ).toBe(false);
  });

  it("is false for a row that is not up there at all", () => {
    expect(isCuratedOnly(new Set(["Package"]), {}, "Diodes", "Breakdown Voltage")).toBe(false);
  });
});

// --- A pin must survive across the parts of its category. ---------------------------------------
// Owner, 2026-07-26: "spec pinning must persist across ALL items of that group." Pins are already
// stored per CATEGORY, so the write was never the problem - the READ matched by exact key, and two
// parts sourced from different distributors spell the same spec differently.

describe("a pin applied to another part in the same category", () => {
  // A spec the CURATED set does not contain, so what these assert is the PIN and nothing else.
  // The first draft used "Breakdown Voltage (Min)", which the Diodes curated terms match anyway -
  // three of the four tests passed before the fix, for the wrong reason.
  const PIN = "Factory Pack Quantity";
  const pinnedOn = { Diodes: [PIN] };

  const other = (key: string, label?: string) =>
    [
      {
        title: "ELECTRICAL",
        rows: [{ key, label: label ?? key, value: "3000" }],
      },
    ] as unknown as SpecGroup[];

  it("is not promoted at all without the pin (the control)", () => {
    expect(keySpecRows(other(PIN), "Diodes", {})).toEqual([]);
  });

  it("matches when the other part spells the key identically", () => {
    expect(keySpecRows(other(PIN), "Diodes", pinnedOn).map((r) => r.key)).toEqual([PIN]);
  });

  it("matches across CASE, spacing and punctuation differences", () => {
    // the same spec, as a different distributor writes it
    const rows = keySpecRows(other("factory  pack quantity"), "Diodes", pinnedOn);
    expect(rows.map((r) => r.key)).toEqual(["factory  pack quantity"]);
  });

  it("matches when the other part carries the pinned wording as its LABEL", () => {
    const rows = keySpecRows(other("FactoryPackQty", "Factory Pack Quantity"), "Diodes", pinnedOn);
    expect(rows.map((r) => r.key)).toEqual(["FactoryPackQty"]);
  });

  it("does NOT promote a different spec that merely shares a word", () => {
    // the precision the exact-key rule was protecting, kept: normalization bridges spelling, it
    // never turns a pin into a substring search
    const rows = keySpecRows(other("Factory Lead Time"), "Diodes", pinnedOn);
    expect(rows.map((r) => r.key)).not.toContain("Factory Lead Time");
  });
});
