import { describe, expect, it } from "vitest";
import type { PartDetail, PartSummary } from "../api/types";
import {
  assetReadiness,
  EDA_TOOLS,
  libraryReadiness,
  summaryReadiness,
} from "./edaTarget";

// A minimal PartDetail whose assets the test overrides per case. Everything not under
// test is a benign empty value so the readiness math is the only thing exercised.
function detail(over: Partial<PartDetail> = {}): PartDetail {
  return {
    id: "p1",
    display_name: "Part",
    category: "ICs",
    description: "",
    tags: [],
    mpn: "MPN1",
    manufacturer: "Acme",
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

function summary(over: Partial<PartSummary> = {}): PartSummary {
  return {
    id: "s1",
    display_name: "Part",
    category: "ICs",
    mpn: "MPN1",
    manufacturer: "Acme",
    is_complete: true,
    missing: [],
    ...over,
  };
}

describe("EDA_TOOLS", () => {
  it("lists KiCad and Altium with display labels, KiCad first (the default)", () => {
    expect(EDA_TOOLS.map((t) => t.tool)).toEqual(["kicad", "altium"]);
    expect(EDA_TOOLS.map((t) => t.label)).toEqual(["KiCad", "Altium"]);
  });
});

describe("assetReadiness", () => {
  it("a part with only kicad symbol+footprint is ready for kicad, model reported missing", () => {
    const part = detail({
      symbol: { lib: "L", name: "S" }, // tool absent -> defaults kicad
      footprint: { lib: "L", name: "F" },
      model: null,
    });
    const r = assetReadiness(part, "kicad");
    expect(r.symbol).toBe(true);
    expect(r.footprint).toBe(true);
    expect(r.model).toBe(false);
    expect(r.ready).toBe(true); // symbol+footprint present; model optional
    expect(r.missing).toEqual(["3D Model"]);
  });

  it("that same kicad part is NOT ready for altium (all three missing for that tool)", () => {
    const part = detail({
      symbol: { lib: "L", name: "S" },
      footprint: { lib: "L", name: "F" },
      model: null,
    });
    const r = assetReadiness(part, "altium");
    expect(r.symbol).toBe(false);
    expect(r.footprint).toBe(false);
    expect(r.model).toBe(false);
    expect(r.ready).toBe(false);
    expect(r.missing).toEqual(["Symbol", "Footprint", "3D Model"]);
  });

  it("counts an asset only when its tool matches the selected tool", () => {
    const part = detail({
      symbol: { lib: "L", name: "S", tool: "altium" },
      footprint: { lib: "L", name: "F", tool: "altium" },
      model: { file: "m.step", tool: "altium" },
    });
    const alt = assetReadiness(part, "altium");
    expect(alt.symbol).toBe(true);
    expect(alt.footprint).toBe(true);
    expect(alt.model).toBe(true);
    expect(alt.ready).toBe(true);
    expect(alt.missing).toEqual([]);
    // the same altium assets do not count toward kicad
    const kic = assetReadiness(part, "kicad");
    expect(kic.ready).toBe(false);
    expect(kic.missing).toEqual(["Symbol", "Footprint", "3D Model"]);
  });

  it("defaults a ref with no tool to kicad", () => {
    const part = detail({
      symbol: { lib: "L", name: "S" },
      footprint: { lib: "L", name: "F", tool: "kicad" },
      model: { file: "m.step" }, // tool absent -> kicad
    });
    const r = assetReadiness(part, "kicad");
    expect(r.ready).toBe(true);
    expect(r.model).toBe(true);
    expect(r.missing).toEqual([]);
  });

  it("is not ready when the footprint is missing even though the symbol is present", () => {
    const part = detail({ symbol: { lib: "L", name: "S" }, footprint: null });
    const r = assetReadiness(part, "kicad");
    expect(r.symbol).toBe(true);
    expect(r.footprint).toBe(false);
    expect(r.ready).toBe(false);
    expect(r.missing).toEqual(["Footprint", "3D Model"]);
  });
});

describe("summaryReadiness", () => {
  it("uses is_complete/missing for the default kicad tool", () => {
    expect(summaryReadiness(summary({ is_complete: true, missing: [] }), "kicad")).toEqual({
      ready: true,
      missing: [],
    });
    expect(
      summaryReadiness(summary({ is_complete: false, missing: ["Footprint"] }), "kicad"),
    ).toEqual({ ready: false, missing: ["Footprint"] });
  });

  it("treats a non-default tool conservatively as not-ready (summary carries no per-tool detail)", () => {
    // even a kicad-complete summary is not confirmed ready for altium
    const r = summaryReadiness(summary({ is_complete: true, missing: [] }), "altium");
    expect(r.ready).toBe(false);
    expect(r.missing).toEqual(["Symbol", "Footprint"]);
  });
});

describe("libraryReadiness", () => {
  it("rolls up complete/incomplete counts and the not-ready ids for the kicad tool", () => {
    const parts = [
      summary({ id: "a", is_complete: true, missing: [] }),
      summary({ id: "b", is_complete: false, missing: ["Symbol"] }),
      summary({ id: "c", is_complete: true, missing: [] }),
    ];
    const roll = libraryReadiness(parts, "kicad");
    expect(roll.total).toBe(3);
    expect(roll.complete).toBe(2);
    expect(roll.incomplete).toBe(1);
    expect(roll.notReadyIds).toEqual(["b"]);
  });

  it("counts every part not-ready for a non-default tool (nothing is confirmed altium-ready)", () => {
    const parts = [
      summary({ id: "a", is_complete: true, missing: [] }),
      summary({ id: "b", is_complete: true, missing: [] }),
    ];
    const roll = libraryReadiness(parts, "altium");
    expect(roll.total).toBe(2);
    expect(roll.complete).toBe(0);
    expect(roll.incomplete).toBe(2);
    expect(roll.notReadyIds).toEqual(["a", "b"]);
  });
});
