import { describe, expect, it } from "vitest";
import {
  deriveFacets,
  groupSpecs,
  mergeSameConcept,
  specConcept,
  normalizeSpecKey,
  splitValueUnit,
  prettifyValue,
  applySign,
  EMPTY_SPEC_VALUES,
  SPEC_HIDDEN_KEYS,
  resolveSpec,
  cleanSpecLabel,
  canonicalSpecId,
  type SpecGroupName,
} from "./specSchema";

describe("canonicalSpecId", () => {
  it("gives distributor spellings of one specification the same stable identity", () => {
    expect(canonicalSpecId("Voltage - Breakdown")).toBe("breakdown voltage");
    expect(canonicalSpecId("Breakdown Voltage")).toBe("breakdown voltage");
    expect(canonicalSpecId("DCR")).toBe("dc resistance");
  });

  it("keeps measurement qualifiers in the identity", () => {
    expect(canonicalSpecId("Voltage - Breakdown (Min)")).toBe("breakdown voltage min");
    expect(canonicalSpecId("Voltage - Breakdown (Min)")).not.toBe(
      canonicalSpecId("Breakdown Voltage"),
    );
  });
});

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
  it("puts the canonical identity on every presented row", () => {
    const rows = groupSpecs("Diodes", {
      "Voltage - Breakdown": "6 V",
      DCR: "20 mOhm",
    }).flatMap((group) => group.rows);
    expect(rows.find((row) => row.key === "Voltage - Breakdown")?.id).toBe("breakdown voltage");
    expect(rows.find((row) => row.key === "DCR")?.id).toBe("dc resistance");
  });

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

  it("routes common connector/passive specs to their proper category, not Other", () => {
    const groups = groupSpecs("Connectors", {
      "Insulation Resistance": "100 MΩ",
      Gender: "Receptacle",
      "Mounting Style": "Top-Mount",
      "Number of Contacts": "16",
      "Contact Material": "Copper Alloy",
      "Flammability Rating": "UL 94 V-0",
      "Maximum Operating Temperature": "85 C",
      Brand: "GCT", // genuinely commercial -> stays Other
    });
    const groupOf = (key: string) =>
      groups.find((g) => g.rows.some((r) => r.key === key))?.title;
    expect(groupOf("Insulation Resistance")).toBe("Electrical");
    expect(groupOf("Gender")).toBe("Physical");
    expect(groupOf("Mounting Style")).toBe("Physical");
    expect(groupOf("Number of Contacts")).toBe("Physical");
    expect(groupOf("Contact Material")).toBe("Physical");
    expect(groupOf("Flammability Rating")).toBe("Ratings & Compliance");
    expect(groupOf("Maximum Operating Temperature")).toBe("Ratings & Compliance");
    expect(groupOf("Brand")).toBe("Other");
  });

  it("keeps supply-chain state out of the physical specification groups", () => {
    expect(resolveSpec("Lifecycle", "ICs").group).toBe("Trade & Compliance");
    expect(resolveSpec("Lead Time", "ICs").group).toBe("Trade & Compliance");
    expect(resolveSpec("Part Status", "ICs").group).toBe("Trade & Compliance");
    expect(resolveSpec("Weight", "Connectors").group).toBe("Physical");
  });

  it("classifies the actual historical corpus spellings without leaking logistics into specs", () => {
    const groups = groupSpecs("Resistors", {
      "Power (Watts)": "0.1 W",
      Composition: "Thick Film",
      "Standard Pack Qty": "5000",
      "Unit Weight (kg)": "0.0001",
      KRHTS: "8533.21",
      BRHTS: "8533.21.20",
    });
    const groupOf = (key: string) =>
      groups.find((group) =>
        group.rows.some((row) => row.key === key || row.members?.some((member) => member.key === key)),
      )?.title;
    expect(groupOf("Power (Watts)")).toBe("Electrical");
    expect(groupOf("Composition")).toBe("Device");
    expect(groupOf("Standard Pack Qty")).toBe("Trade & Compliance");
    expect(groupOf("Unit Weight (kg)")).toBe("Trade & Compliance");
    expect(groupOf("KRHTS")).toBe("Trade & Compliance");
    expect(groupOf("BRHTS")).toBe("Trade & Compliance");
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

// -- Spec families (punch 3: "specification dropdowns for repeated info, e.g. HTS code").
// Mouser alone emits six HTS keys (US / CN / CA / JP / MX / EU TARIC) and LCSC emits one per
// arbitrary country name, so six-plus near-identical rows shouted over the specs that matter.
// They are ONE fact per jurisdiction, so they collapse to one row with a member per region.

describe("groupSpecs spec families", () => {
  const hts = {
    "HTS Code (US)": "8542.39.0001",
    "HTS Code (CN)": "8542330000",
    "HTS Code (EU TARIC)": "8542390000",
    ECCN: "3A991",
    Tolerance: "1%",
  };

  it("collapses every HTS code into a single row with one member per region", () => {
    // the family lives in the procurement group (see TRADE_GROUP), not beside the physical ratings
    const groups = groupSpecs("ICs", hts);
    const ratings = groups.find((g) => g.title === "Trade & Compliance")!;
    const labels = ratings.rows.map((r) => r.label);
    expect(labels).toContain("HTS Code");
    expect(labels.filter((l) => String(l).startsWith("HTS Code"))).toHaveLength(1);
    const family = ratings.rows.find((r) => r.label === "HTS Code")!;
    expect(family.members?.map((m) => m.label)).toEqual(["CN", "EU TARIC", "US"]);
    expect(family.members?.map((m) => m.value)).toEqual([
      "8542330000", "8542390000", "8542.39.0001",
    ]);
  });

  it("keeps ECCN as its own row: a different fact, not another HTS jurisdiction", () => {
    const ratings = groupSpecs("ICs", hts).find((g) => g.title === "Trade & Compliance")!;
    const eccn = ratings.rows.find((r) => r.label === "ECCN")!;
    expect(eccn.value).toBe("3A991");
    expect(eccn.members).toBeUndefined();
  });

  it("folds a region nobody has registered, because LCSC emits one key per country", () => {
    const groups = groupSpecs("ICs", {
      "HTS Code (Vietnam)": "8542.39",
      "HTS Code (US)": "8542.31",
    });
    const family = groups.flatMap((g) => g.rows).find((r) => r.label === "HTS Code")!;
    expect(family.members?.map((m) => m.label)).toEqual(["US", "Vietnam"]);
  });

  it("a lone family member still reads as the family row, not a bare key", () => {
    const family = groupSpecs("ICs", { "HTS Code (US)": "8542.39" })
      .flatMap((g) => g.rows)
      .find((r) => r.label === "HTS Code")!;
    expect(family.members?.map((m) => m.label)).toEqual(["US"]);
  });

  it("an unqualified HTS key with no region still lands in the family", () => {
    const family = groupSpecs("ICs", { "HTS Code": "8542.39" })
      .flatMap((g) => g.rows)
      .find((r) => r.label === "HTS Code")!;
    expect(family.members?.map((m) => m.value)).toEqual(["8542.39"]);
  });

  it("never drops a spec: folding a family changes the SHAPE, not the count of facts", () => {
    // Counted on the leaves rather than compared value-by-value, because presentation legitimately
    // rewrites some values on the way out ("1%" reads as "±1%"), and a count catches a dropped
    // spec without pinning this test to the prettifier.
    const leaves = groupSpecs("ICs", hts).flatMap((g) =>
      g.rows.flatMap((r) => r.members ?? [r]),
    );
    expect(leaves).toHaveLength(Object.keys(hts).length);
    // and the family's own values are carried through verbatim (no prettifier applies to a code)
    const family = groupSpecs("ICs", hts)
      .flatMap((g) => g.rows)
      .find((r) => r.label === "HTS Code")!;
    expect(family.members?.map((m) => m.value).sort()).toEqual(
      ["8542.39.0001", "8542330000", "8542390000"].sort(),
    );
  });
});

// -- Trade & Compliance (punch 2 + 3). These keys are real vendor data the owner asked to stop
// losing (origin, the page's own tariff rate, export classification, order quantities), but they
// are NOT physical parameters, and `derive.isReferenceOnlySpecKey` deliberately keeps them out of
// the Specs sheet so it does not read like a distributor page dump. Both rules hold at once by
// giving them their own group, which the Sourcing tab renders - that is where a buyer looks for
// an import classification anyway.

describe("groupSpecs trade group", () => {
  const specs = {
    Resistance: "10 kOhm",
    "Country of Origin": "Japan",
    "US Tariff %": 0.0,
    ECCN: "3A991",
    "HTS Code (US)": "8542.39.0001",
    "HTS Code (CN)": "8542330000",
    "Minimum Order Quantity": "1",
    Packaging: "Cut Tape",
  };

  it("routes procurement facts to Trade & Compliance, not to the physical groups", () => {
    const groups = groupSpecs("ICs", specs);
    const trade = groups.find((g) => g.title === "Trade & Compliance")!;
    const labels = trade.rows.map((r) => r.label);
    expect(labels).toContain("Country of Origin");
    expect(labels).toContain("US Tariff");
    expect(labels).toContain("ECCN");
    expect(labels).toContain("HTS Code");
    expect(labels).toContain("Minimum Order Quantity");
    // and a real electrical spec is untouched by any of it
    const electrical = groups.find((g) => g.title === "Electrical")!;
    expect(electrical.rows.map((r) => r.label)).toEqual(["Resistance"]);
  });

  it("folds the HTS family inside the trade group, not outside it", () => {
    const trade = groupSpecs("ICs", specs).find((g) => g.title === "Trade & Compliance")!;
    const family = trade.rows.find((r) => r.label === "HTS Code")!;
    expect(family.members?.map((m) => m.label)).toEqual(["CN", "US"]);
  });

  it("keeps a zero tariff, because 0% is a confirmed rate and not a missing one", () => {
    const trade = groupSpecs("ICs", specs).find((g) => g.title === "Trade & Compliance")!;
    // "0%", not a bare "0": the registry gives the row a % unit, which groupSpecs folds into the
    // value. A lone 0 in a value column is indistinguishable from an empty cell.
    expect(trade.rows.find((r) => r.label === "US Tariff")?.value).toBe("0%");
  });

  it("omits the group entirely for a part with no trade data", () => {
    const groups = groupSpecs("ICs", { Resistance: "10 kOhm" });
    expect(groups.find((g) => g.title === "Trade & Compliance")).toBeUndefined();
  });
});

describe("groupSpecs zero-valued rates", () => {
  it("renders a confirmed 0% tariff as 0%, not a bare 0 that reads as missing", () => {
    // The page's own DecTariffUnitPrice ratio: 0.0 means "we checked, there is no tariff". A bare
    // "0" in a value column is indistinguishable from an empty cell, which turns a real
    // measurement into what looks like a gap.
    const trade = groupSpecs("ICs", { "US Tariff %": 0.0 })
      .find((g) => g.title === "Trade & Compliance")!;
    const row = trade.rows.find((r) => r.label === "US Tariff")!;
    expect(`${row.value}${row.unit ?? ""}`).toBe("0%");
  });

  it("still drops a genuinely absent value rather than printing a zero", () => {
    expect(groupSpecs("ICs", { "US Tariff %": "" })).toEqual([]);
  });
});

describe("token patterns keep real distributor parameters out of Other", () => {
  // THE REGRESSION THIS EXISTS FOR (owner, 2026-07-25): on a real ESD diode, 13 of 18 specs
  // rendered under "Other" because every exact registry row missed the distributor's own long
  // parameter names. These are the actual keys off that part's record.
  const REAL_KEYS: Array<[string, SpecGroupName]> = [
    ["Voltage - Breakdown (Min)", "Electrical"],
    ["Voltage - Clamping (Max) @ Ipp", "Electrical"],
    ["Voltage - Reverse Standoff (Typ)", "Electrical"],
    ["Current - Peak Pulse (10/1000µs)", "Electrical"],
    ["Power - Peak Pulse", "Electrical"],
    ["Package / Case", "Physical"],
    ["Package Type", "Physical"],
    ["Supplier Device Package", "Physical"],
    ["Applications", "Device"],
    ["Type", "Device"],
    ["Unidirectional Channels", "Device"],
    ["Power Line Protection", "Device"],
    ["Operating Temperature", "Ratings & Compliance"],
    ["Moisture Sensitivity Level", "Ratings & Compliance"],
  ];

  it.each(REAL_KEYS)("files %s under %s", (key, group) => {
    expect(resolveSpec(key, "Diodes").group).toBe(group);
  });

  it("leaves NOTHING from that part in Other", () => {
    const stragglers = REAL_KEYS.map(([k]) => k).filter(
      (k) => resolveSpec(k, "Diodes").group === "Other",
    );
    expect(stragglers).toEqual([]);
  });

  it("tidies the distributor's wording without losing any of it", () => {
    // SUPERSEDED 2026-07-25 by the owner: "why not clean up the names". The earlier rule here kept
    // the vendor phrasing verbatim on the grounds that its precision matters. The precision is in
    // the QUALIFIERS - Max / Typ / Min / the pulse shape - and reordering around the dash keeps
    // every one of them while giving the phrase English word order at the same length.
    expect(resolveSpec("Voltage - Clamping (Max) @ Ipp", "Diodes").label).toBe(
      "Clamping Voltage (Max) @ Ipp",
    );
    // nothing is dropped: the condition survives verbatim
    expect(resolveSpec("Current - Peak Pulse (10/1000µs)", "Diodes").label).toContain("10/1000µs");
  });

  it("still lets an EXACT registry row win over a pattern", () => {
    // Precedence has to hold, or curated labels and units are silently replaced by the fallback.
    const exact = resolveSpec("Voltage Rating", "Capacitors");
    expect(exact.label).toBe("Voltage Rating");
    expect(exact.group).toBe("Electrical");
  });

  it("does not invent a group for a key with no recognisable family", () => {
    // "Other" must remain a real destination - a pattern set that matches everything would be
    // worse than one that matches nothing, because a wrong group is harder to notice than a
    // missing one.
    expect(resolveSpec("Brand Id", "Diodes").group).toBe("Other");
  });
});

describe("cleanSpecLabel", () => {
  it("puts a distributor's dashed parameter name into English word order", () => {
    // The owner's point: the Sourcing column was not too narrow, the names were badly ordered.
    // Same length, reads at a glance, costs no width.
    expect(cleanSpecLabel("Voltage - Breakdown (Min)")).toBe("Breakdown Voltage (Min)");
    expect(cleanSpecLabel("Voltage - Reverse Standoff (Typ)")).toBe(
      "Reverse Standoff Voltage (Typ)",
    );
    expect(cleanSpecLabel("Power - Peak Pulse")).toBe("Peak Pulse Power");
  });

  it("keeps a trailing condition at the END, where it belongs", () => {
    expect(cleanSpecLabel("Voltage - Clamping (Max) @ Ipp")).toBe(
      "Clamping Voltage (Max) @ Ipp",
    );
    expect(cleanSpecLabel("Current - Peak Pulse (10/1000µs)")).toBe(
      "Peak Pulse Current (10/1000µs)",
    );
  });

  it("leaves a name with no dash completely alone", () => {
    for (const name of ["Applications", "Mounting Type", "Operating Temperature", "Package / Case"]) {
      expect(cleanSpecLabel(name)).toBe(name);
    }
  });

  it("refuses to reorder when a half is not a phrase", () => {
    // A numeric or symbolic half is not two words to swap, and guessing would lose meaning that a
    // long label merely obscures.
    expect(cleanSpecLabel("Voltage - 5V")).toBe("Voltage - 5V");
    expect(cleanSpecLabel("A - 1/2")).toBe("A - 1/2");
  });

  it("never touches a name with more than one dash", () => {
    // Ambiguous: which dash is the pivot? Returning it untouched is the honest answer.
    const messy = "Voltage - Clamping - Peak";
    expect(cleanSpecLabel(messy)).toBe(messy);
  });

  it("is empty only for empty input", () => {
    expect(cleanSpecLabel("")).toBe("");
    expect(cleanSpecLabel("   ")).toBe("");
  });

  it("is what resolveSpec hands the sheet for an unregistered key", () => {
    // The wiring, not just the helper: a pattern-matched key must arrive tidied.
    expect(resolveSpec("Voltage - Clamping (Max) @ Ipp", "Diodes").label).toBe(
      "Clamping Voltage (Max) @ Ipp",
    );
  });
});

// --- One concept, one row (owner, 2026-07-26). ---------------------------------------------------
// Their real part carries BOTH `Breakdown Voltage` (LCSC, 6 V) and `Voltage - Breakdown` (DigiKey,
// 8.5 V). Both render their label as "Breakdown Voltage", so the sheet showed one name twice with
// two different numbers and nothing saying which was in force.

describe("specConcept", () => {
  it("matches the same words in a different ORDER", () => {
    expect(specConcept("Voltage - Breakdown")).toBe(specConcept("Breakdown Voltage"));
  });

  it("keeps a qualifier as its own concept", () => {
    // (Min) is a different parameter, not a different spelling
    expect(specConcept("Voltage - Breakdown (Min)")).not.toBe(specConcept("Breakdown Voltage"));
    expect(specConcept("Voltage - Clamping (Max) @ Ipp")).not.toBe(specConcept("Clamping Voltage"));
  });

  it("ignores punctuation and case", () => {
    expect(specConcept("factory-pack QUANTITY")).toBe(specConcept("Factory Pack Quantity"));
  });

  it("treats rating and rated as distributor grammar, not a second concept", () => {
    expect(specConcept("Power Rating")).toBe(specConcept("Power"));
    expect(specConcept("Voltage Rated")).toBe(specConcept("Voltage Rating"));
  });

  it("does not erase rating from an unrelated named concept", () => {
    expect(specConcept("Safety Rating")).not.toBe(specConcept("Safety"));
  });
});

describe("mergeSameConcept", () => {
  // exactly the five keys on the owner's record
  const groups = [
    {
      title: "ELECTRICAL",
      rows: [
        { key: "Breakdown Voltage", label: "Breakdown Voltage", value: "6 V", raw: "6 V" },
        { key: "Clamping Voltage", label: "Clamping Voltage", value: "14 V", raw: "14V" },
        { key: "Voltage - Breakdown", label: "Breakdown Voltage", value: "8.5 V", raw: "8.5V" },
        { key: "Voltage - Breakdown (Min)", label: "Breakdown Voltage (Min)", value: "6.5 V", raw: "6.5V" },
        { key: "Voltage - Clamping (Max) @ Ipp", label: "Clamping Voltage (Max) @ Ipp", value: "14 V", raw: "14V" },
      ],
    },
  ] as unknown as Parameters<typeof mergeSameConcept>[0];

  it("folds the duplicate wording into ONE row", () => {
    const { groups: out } = mergeSameConcept(groups, {});
    const keys = out[0].rows.map((r) => r.key);
    expect(keys).toContain("Breakdown Voltage");
    expect(keys).not.toContain("Voltage - Breakdown");
  });

  it("keeps the qualified parameters as their own rows", () => {
    const { groups: out } = mergeSameConcept(groups, {});
    const keys = out[0].rows.map((r) => r.key);
    expect(keys).toContain("Voltage - Breakdown (Min)");
    expect(keys).toContain("Voltage - Clamping (Max) @ Ipp");
    expect(out[0].rows).toHaveLength(4); // 5 in, one folded
  });

  it("routes the displaced value into alternates, with the winner leading", () => {
    const { alternates } = mergeSameConcept(groups, {});
    expect(alternates["Breakdown Voltage"].map((a) => a.value)).toEqual(["6 V", "8.5V"]);
  });

  it("folds real rating variants and recognizes equivalent engineering-unit values", () => {
    const ratingVariants = [
      {
        title: "ELECTRICAL",
        rows: [
          { key: "Power", label: "Power", value: "0.063 W", raw: "0.063 W" },
          {
            key: "Power Rating",
            label: "Power Rating",
            value: "62.5 mW (1/16 W)",
            raw: "62.5 mW (1/16 W)",
          },
          { key: "Voltage Rated", label: "Voltage Rated", value: "50 V", raw: "50 V" },
          { key: "Voltage Rating", label: "Voltage Rating", value: "50 V", raw: "50 V" },
        ],
      },
    ] as unknown as Parameters<typeof mergeSameConcept>[0];

    const { groups: out, alternates } = mergeSameConcept(ratingVariants, {});
    expect(out[0].rows.map((row) => row.key)).toEqual(["Power", "Voltage Rated"]);
    expect(alternates.Power).toBeUndefined();
    expect(alternates["Voltage Rated"]).toBeUndefined();
  });

  it("folds exact SI conversions but keeps a materially different source answer", () => {
    const values = [
      {
        title: "ELECTRICAL",
        rows: [
          { key: "Voltage", label: "Voltage", value: "0.5 V", raw: "0.5 V" },
          { key: "Voltage Rating", label: "Voltage Rating", value: "500 mV", raw: "500 mV" },
          { key: "Power", label: "Power", value: "0.063 W", raw: "0.063 W" },
          { key: "Power Rating", label: "Power Rating", value: "80 mW", raw: "80 mW" },
        ],
      },
    ] as unknown as Parameters<typeof mergeSameConcept>[0];

    const { groups: out, alternates } = mergeSameConcept(values, {});
    expect(out[0].rows.map((row) => row.key)).toEqual(["Voltage", "Power"]);
    expect(alternates.Voltage).toBeUndefined();
    expect(alternates.Power.map((alternate) => alternate.value)).toEqual(["0.063 W", "80 mW"]);
  });

  it("compares RAW values, so a prettified twin is not offered as an alternative", () => {
    const same = [
      {
        title: "ELECTRICAL",
        rows: [
          { key: "Tolerance", label: "Tolerance", value: "±1%", raw: "1%" },
          { key: "Tolerance - Value", label: "Tolerance", value: "±1%", raw: "1%" },
        ],
      },
    ] as unknown as Parameters<typeof mergeSameConcept>[0];
    const { alternates } = mergeSameConcept(same, {});
    expect(alternates["Tolerance"]).toBeUndefined();
  });

  it("never folds a family row, which is already a collapse", () => {
    const fam = [
      {
        title: "TRADE",
        rows: [
          { key: "HTS Code", label: "HTS Code", value: "2", members: [{ label: "US", value: "1" }] },
          { key: "Code HTS", label: "HTS Code", value: "x" },
        ],
      },
    ] as unknown as Parameters<typeof mergeSameConcept>[0];
    expect(mergeSameConcept(fam, {}).groups[0].rows).toHaveLength(2);
  });
});

describe("vendor bookkeeping keys", () => {
  it("does not render a distributor's internal record id as a parameter", () => {
    // The owner saw `Brand Id 100` sitting in the Other group beside real parameters. LCSC's
    // __NEXT_DATA__ carries brandId / catalogId / parentCatalogId / wmCatalogId, and the
    // adapter's uncurated fallback Title-cases any webData scalar into a spec label. The
    // record KEEPS them (the owner's explicit "store everything the source exposes"); the
    // sheet must not present them as properties of the part.
    const groups = groupSpecs("Resistors", {
      Resistance: "10 kOhm",
      "Brand Id": "396",
      "Catalog Id": "1199",
      "Parent Catalog Id": "308",
      "Wm Catalog Id": "1199",
    });
    const labels = groups.flatMap((g) => g.rows.map((r) => r.label));
    expect(labels).toContain("Resistance");
    for (const gone of ["Brand Id", "Catalog Id", "Parent Catalog Id", "Wm Catalog Id"]) {
      expect(labels).not.toContain(gone);
    }
  });

  it("keeps an identifier a person actually uses to order", () => {
    // The rule is about an INTERNAL id, not about every identifier. LCSC's own product code
    // is how you buy the part, and it is curated deliberately (note the uppercase "ID", which
    // is what distinguishes a curated label from the humanized fallback).
    const labels = groupSpecs("Resistors", {
      "LCSC Product ID": "61542",
      "HTS Code (US)": "8533210020",
    }).flatMap((g) => g.rows.map((r) => r.label));
    expect(labels.join(" ")).toContain("LCSC Product ID");
  });

  it("does not drop a real spec whose label merely ENDS in something id-like", () => {
    // Exactness check: the rule matches a trailing " Id" word, not the letters anywhere. A
    // pattern that fired on "id" inside a word would eat real specs.
    const labels = groupSpecs("ICs", {
      Grid: "0.5 mm",
      "Bridge Type": "Full",
      Humidity: "85%",
    }).flatMap((g) => g.rows.map((r) => r.label));
    expect(labels).toEqual(expect.arrayContaining(["Grid", "Bridge Type", "Humidity"]));
  });
});

describe("deriveFacets folds spec families", () => {
  // The rail showed SIX separate HTS facets - one per jurisdiction - which is one fact repeated,
  // never six things to filter on. `groupSpecs` had always folded them for the detail sheet, and
  // deriveFacets' own docstring claimed parity with it while not doing so.
  const hts = {
    category: "Other",
    specs: {
      "HTS Code": "8532.24.0020",
      "HTS Code (US)": "8532.24.0020",
      "HTS Code (EU)": "85322400",
      "HTS Code (CN)": "8532240000",
    },
  };

  it("routes every member of a family to ONE facet", () => {
    const facets = deriveFacets([hts]);
    const htsFacets = facets.filter((f) => f.label.toLowerCase().includes("hts"));
    expect(htsFacets).toHaveLength(1);
  });

  it("keeps every member's VALUE, so the fold loses no filterable data", () => {
    const facets = deriveFacets([hts]);
    const one = facets.find((f) => f.label.toLowerCase().includes("hts"));
    expect(one).toBeDefined();
    if (one && one.kind === "checkbox" && one.values) {
      const values = one.values.map((v) => v.value);
      // all four jurisdictions' codes are still reachable as filter values
      expect(values).toContain("8532.24.0020");
      expect(values).toContain("85322400");
      expect(values).toContain("8532240000");
    }
  });

  it("leaves a non-family key exactly as it was", () => {
    // the anti-vacuous half: if folding swallowed everything, the test above would pass for the
    // wrong reason.
    const facets = deriveFacets([
      { category: "Resistors", specs: { Resistance: "10 kΩ", Tolerance: "1%" } },
    ]);
    expect(facets.map((f) => f.label).sort()).toEqual(["Resistance", "Tolerance"]);
  });
});
