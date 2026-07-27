import { describe, expect, it } from "vitest";
import type { DeepPartial } from "fishery";
import type { Asset, PartDetail, PartSummary } from "../api/types";
import { makeAsset, makePartDetail } from "../test/partFixture";
import {
  assetReadiness,
  assetsFor,
  assetPresent,
  assetRef,
  DEFAULT_EDA_TOOL,
  EDA_TOOL_OPTIONS,
  libraryReadiness,
  neededKinds,
  reportableKinds,
  summaryReadiness,
} from "./edaTarget";
import { partClass } from "./edaRegistry.generated";

function ref(lib: string, name: string): Asset {
  return makeAsset({ lib, name });
}

function modelRef(file: string): Asset {
  return makeAsset({ file });
}

// A minimal PartDetail whose assets the test overrides per case. Everything not under
// test is a benign empty value so the readiness math is the only thing exercised.
function detail(over: DeepPartial<PartDetail> = {}): PartDetail {
  return makePartDetail({
    id: "p1",
    mpn: "MPN1",
    manufacturer: "Acme",
    derived: { display_name: "Part", description: "", specs: {} },
    ...over,
  });
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

const FULL_KICAD = {
  kicad: { symbol: ref("SR-ICs", "S"), footprint: ref("SR-ICs", "F"), model: modelRef("m.step") },
};
const FULL_ALTIUM = {
  altium: { symbol: ref("p.SchLib", "S"), footprint: ref("p.PcbLib", "F"), model: null },
};

describe("EDA_TOOL_OPTIONS", () => {
  it("offers KiCad first, because it is the default target", () => {
    expect(EDA_TOOL_OPTIONS.map((t) => t.tool)).toEqual(["kicad", "altium"]);
    expect(DEFAULT_EDA_TOOL).toBe("kicad");
  });

  it("labels every tool from the generated registry", () => {
    expect(EDA_TOOL_OPTIONS.map((t) => t.label)).toEqual(["KiCad", "Altium Designer"]);
  });
});

describe("assetsFor", () => {
  it("returns an empty bundle for a tool the part carries nothing for", () => {
    expect(assetsFor(detail(), "altium")).toEqual({
      symbol: null,
      footprint: null,
      model: null,
    });
  });

  it("never reads one tool's assets as another's", () => {
    const part = detail({ assets: FULL_KICAD });
    expect(assetRef(assetsFor(part, "kicad").symbol)?.name).toBe("S");
    expect(assetsFor(part, "altium").symbol).toBeNull();
  });
});

describe("assetPresent", () => {
  it("counts an entry-shaped asset by name and a file-shaped one by file", () => {
    expect(assetPresent(ref("L", "S"))).toBe(true);
    expect(assetPresent(modelRef("m.step"))).toBe(true);
  });

  it("does not count a container with no entry, or nothing at all", () => {
    expect(assetPresent(ref("L", ""))).toBe(false);
    expect(assetPresent(null)).toBe(false);
    expect(assetPresent(undefined)).toBe(false);
  });
});

describe("assetReadiness", () => {
  it("is ready for a tool once that tool's symbol and footprint are attached", () => {
    const r = assetReadiness(detail({ assets: FULL_KICAD }), "kicad");
    expect(r.ready).toBe(true);
    expect(r.missing).toEqual([]);
    expect(r.present).toEqual({ symbol: true, footprint: true, model: true });
  });

  it("reports a missing 3D model without blocking readiness", () => {
    const r = assetReadiness(
      detail({ assets: { kicad: { symbol: ref("L", "S"), footprint: ref("L", "F"), model: null } } }),
      "kicad",
    );
    expect(r.ready).toBe(true);
    expect(r.missing).toEqual(["3D Model"]);
    expect(r.present.model).toBe(false);
  });

  it("is not ready when the footprint is missing", () => {
    const r = assetReadiness(
      detail({ assets: { kicad: { symbol: ref("L", "S"), footprint: null, model: null } } }),
      "kicad",
    );
    expect(r.ready).toBe(false);
    expect(r.missing).toEqual(["Footprint", "3D Model"]);
  });

  // THE regression this whole per-EDA record exists to prevent. Before the cutover the
  // Altium branch read `part.symbol` (the KiCad ref) and asserted `model = true`, so a part
  // with Altium assets attached still showed "CAD Incomplete" forever, and a part with only
  // KiCad assets could read as Altium-ready. Both directions are pinned here.
  describe("cross-tool independence", () => {
    it("a full KiCad set does NOT make the part Altium-ready", () => {
      const r = assetReadiness(detail({ assets: FULL_KICAD }), "altium");
      expect(r.ready).toBe(false);
      expect(r.missing).toEqual(["Symbol", "Footprint", "3D Model"]);
    });

    it("a full Altium set DOES make the part Altium-ready", () => {
      // The 3D model is REPORTED but never blocks readiness: a footprint places fine without
      // one, and the fixture has `model: null` because embedding is a separate action.
      const r = assetReadiness(detail({ assets: FULL_ALTIUM }), "altium");
      expect(r.ready).toBe(true);
      expect(r.missing).toEqual(["3D Model"]);
    });

    it("a full Altium set does NOT make the part KiCad-ready", () => {
      expect(assetReadiness(detail({ assets: FULL_ALTIUM }), "kicad").ready).toBe(false);
    });

    it("each tool reads its own assets when both are attached", () => {
      const part = detail({ assets: { ...FULL_KICAD, ...FULL_ALTIUM } });
      expect(assetReadiness(part, "kicad").ready).toBe(true);
      expect(assetReadiness(part, "altium").ready).toBe(true);
    });
  });

  it("reports an Altium 3D model as missing, because embedding CAN close that gap", () => {
    // RE-BASELINED 2026-07-25, and the inverted assertion it replaces was right at the time:
    // Altium cannot take a 3D model by reference and there was no other route, so listing it
    // named a gap no user could ever close.
    //
    // `stockroom.altium.embed3d` is that route now, verified end to end against a real .PcbLib.
    // So the kind stays in `unsupported` (still not referenceable) and ALSO appears in
    // `embedded`, which is what makes it a reportable, closable gap. Hiding it is how Altium
    // parts silently shipped with no 3D at all.
    const r = assetReadiness(detail({ assets: FULL_ALTIUM }), "altium");
    expect(r.missing).toContain("3D Model");
    expect(r.unsupported.model).toMatch(/PcbLib/);
    expect(r.present.model).toBe(false);
    expect(r.embedded.model.container).toBe("footprint");
    expect(r.embedded.model.requiresToolInstalled).toBe(true);
    expect(r.embedded.model.reason).toMatch(/Altium installed/);
  });

  it("still hides a kind with no embed route, so no gap is ever unclosable", () => {
    // The guard against re-introducing "CAD Incomplete forever". Driven through a SYNTHETIC spec
    // because the live registry cannot express the case today: KiCad has nothing unsupported and
    // Altium's only unsupported kind is embeddable, so asserting this against the real tools would
    // be a test whose loop body never runs.
    const kinds = ["symbol", "footprint", "model", "panel"];
    expect(
      reportableKinds({
        assetKinds: kinds,
        unsupportedAssets: { model: "not by reference", panel: "impossible, no route at all" },
        embeddedAssets: {
          model: { container: "footprint", source: "model", requiresToolInstalled: true, reason: "" },
        },
      }),
    ).toEqual(["symbol", "footprint", "model"]);
    // And with the embed route removed the kind disappears again, which is what proves the
    // assertion above is reading the embed route and not just the kind list.
    expect(
      reportableKinds({
        assetKinds: kinds,
        unsupportedAssets: { model: "not by reference", panel: "impossible, no route at all" },
        embeddedAssets: {},
      }),
    ).toEqual(["symbol", "footprint"]);
  });

  it("treats a passive as having its 3D model, which the stock footprint carries", () => {
    const r = assetReadiness(
      detail({
        part_class: "passive",
        assets: { kicad: { symbol: ref("Device", "R"), footprint: ref("Resistor_SMD", "R_0603_1608Metric"), model: null } },
      }),
      "kicad",
    );
    expect(r.missing).toEqual([]);
    expect(r.ready).toBe(true);
  });

  // The SECOND half of the "CAD Incomplete forever" family, and the one that had no coverage
  // at all until 2026-07-27. `passive` became a four-valued `part_class`, and the naive port of
  // the old `if (part.passive)` branch - `part_class === "passive"` - special-cases exactly one
  // class. Every OTHER non-component class then falls through to the component requirements,
  // so a mechanical part is reported as missing a symbol it can never have, forever.
  //
  // Requirements are read from the generated class table instead, so these hold by construction.
  describe("requirements are f(part_class, tool), never a branch on one class", () => {
    it("a mechanical part needs a footprint and is NEVER asked for a symbol", () => {
      const r = assetReadiness(
        detail({
          part_class: "mechanical",
          assets: { kicad: { symbol: null, footprint: ref("SR-Mech", "M3_Hole"), model: null } },
        }),
        "kicad",
      );
      expect(r.missing).toEqual([]);
      expect(r.ready).toBe(true);
      // The symbol is still REPORTED as absent - `present` answers "is it attached" - but it is
      // not a gap, because this class cannot have one. Those are two different questions.
      expect(r.present.symbol).toBe(false);
    });

    it("a mechanical part with no footprint is not ready, and the footprint is the only gap", () => {
      const r = assetReadiness(detail({ part_class: "mechanical" }), "kicad");
      expect(r.missing).toEqual(["Footprint"]);
      expect(r.ready).toBe(false);
    });

    it("a virtual part needs nothing and is ready with no assets whatsoever", () => {
      const r = assetReadiness(detail({ part_class: "virtual" }), "kicad");
      expect(r.missing).toEqual([]);
      expect(r.ready).toBe(true);
    });

    it("a component with nothing attached still reports all three, so nothing is excused", () => {
      const r = assetReadiness(detail({ part_class: "component" }), "kicad");
      expect(r.missing).toEqual(["Symbol", "Footprint", "3D Model"]);
      expect(r.ready).toBe(false);
    });

    it("requires_override REPLACES the class list for the tools it names", () => {
      const part = detail({
        part_class: "component",
        requires_override: { needs: ["footprint"], tools: ["kicad"], reason: "panel fiducial" },
        assets: { kicad: { symbol: null, footprint: ref("L", "F"), model: null } },
      });
      expect(assetReadiness(part, "kicad").missing).toEqual([]);
      expect(assetReadiness(part, "kicad").ready).toBe(true);
      // ...and leaves a tool it does NOT name on the class default. An override scoped to one
      // tool silently applying to every tool would be an escape hatch that escapes too much.
      expect(assetReadiness(part, "altium").missing).toEqual(["Symbol", "Footprint", "3D Model"]);
    });

    it("an override with an EMPTY needs list means nothing is required, not 'no override'", () => {
      // `requires_override: null` and `needs: []` are different claims, and collapsing them is
      // how an escape hatch stops working. This is the case that distinguishes them.
      const part = detail({
        part_class: "component",
        requires_override: { needs: [], tools: [], reason: "documentation-only part" },
      });
      expect(assetReadiness(part, "kicad").missing).toEqual([]);
      expect(assetReadiness(part, "kicad").ready).toBe(true);
    });

    it("neededKinds reads the class table, so every class resolves without a branch", () => {
      const kinds = (cls: PartDetail["part_class"]) =>
        neededKinds({ part_class: cls, requires_override: null }, "kicad", partClass(cls));
      expect(kinds("component")).toEqual(["symbol", "footprint", "model"]);
      expect(kinds("mechanical")).toEqual(["footprint"]);
      expect(kinds("passive")).toEqual([]);
      expect(kinds("virtual")).toEqual([]);
    });
  });

  it("reports every gap for a part with nothing attached", () => {
    expect(assetReadiness(detail(), "kicad").missing).toEqual([
      "Symbol",
      "Footprint",
      "3D Model",
    ]);
  });

  it("does not count a reference whose entry name is blank", () => {
    const r = assetReadiness(
      detail({ assets: { kicad: { symbol: ref("L", ""), footprint: ref("L", "F"), model: null } } }),
      "kicad",
    );
    expect(r.ready).toBe(false);
    expect(r.missing).toContain("Symbol");
  });
});

describe("summaryReadiness", () => {
  it("uses the row's own completeness for the default tool", () => {
    expect(summaryReadiness(summary({ is_complete: true }), "kicad")).toEqual({
      ready: true,
      missing: [],
    });
  });

  it("is conservative for a non-default tool a summary cannot speak to", () => {
    expect(summaryReadiness(summary({ is_complete: true }), "altium")).toEqual({
      ready: false,
      missing: ["Symbol", "Footprint"],
    });
  });
});

describe("libraryReadiness", () => {
  it("rolls up the parts not ready for the selected tool", () => {
    const parts = [
      summary({ id: "a", is_complete: true }),
      summary({ id: "b", is_complete: false, missing: ["MPN"] }),
    ];
    expect(libraryReadiness(parts, "kicad")).toEqual({
      total: 2,
      complete: 1,
      incomplete: 1,
      notReadyIds: ["b"],
    });
  });

  it("flags every part for a tool no summary can confirm", () => {
    const parts = [summary({ id: "a" }), summary({ id: "b" })];
    expect(libraryReadiness(parts, "altium").notReadyIds).toEqual(["a", "b"]);
  });
});
