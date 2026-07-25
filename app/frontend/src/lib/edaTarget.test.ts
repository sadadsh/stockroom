import { describe, expect, it } from "vitest";
import type { AssetRef, PartDetail, PartSummary } from "../api/types";
import {
  assetReadiness,
  assetsFor,
  assetPresent,
  DEFAULT_EDA_TOOL,
  EDA_TOOL_OPTIONS,
  libraryReadiness,
  reportableKinds,
  summaryReadiness,
} from "./edaTarget";

function ref(lib: string, name: string): AssetRef {
  return { lib, name, file: "" };
}

function modelRef(file: string): AssetRef {
  return { lib: "", name: "", file };
}

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
    eda: {},
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
    const part = detail({ eda: FULL_KICAD });
    expect(assetsFor(part, "kicad").symbol?.name).toBe("S");
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
    const r = assetReadiness(detail({ eda: FULL_KICAD }), "kicad");
    expect(r.ready).toBe(true);
    expect(r.missing).toEqual([]);
    expect(r.present).toEqual({ symbol: true, footprint: true, model: true });
  });

  it("reports a missing 3D model without blocking readiness", () => {
    const r = assetReadiness(
      detail({ eda: { kicad: { symbol: ref("L", "S"), footprint: ref("L", "F"), model: null } } }),
      "kicad",
    );
    expect(r.ready).toBe(true);
    expect(r.missing).toEqual(["3D Model"]);
    expect(r.present.model).toBe(false);
  });

  it("is not ready when the footprint is missing", () => {
    const r = assetReadiness(
      detail({ eda: { kicad: { symbol: ref("L", "S"), footprint: null, model: null } } }),
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
      const r = assetReadiness(detail({ eda: FULL_KICAD }), "altium");
      expect(r.ready).toBe(false);
      expect(r.missing).toEqual(["Symbol", "Footprint", "3D Model"]);
    });

    it("a full Altium set DOES make the part Altium-ready", () => {
      // The 3D model is REPORTED but never blocks readiness: a footprint places fine without
      // one, and the fixture has `model: null` because embedding is a separate action.
      const r = assetReadiness(detail({ eda: FULL_ALTIUM }), "altium");
      expect(r.ready).toBe(true);
      expect(r.missing).toEqual(["3D Model"]);
    });

    it("a full Altium set does NOT make the part KiCad-ready", () => {
      expect(assetReadiness(detail({ eda: FULL_ALTIUM }), "kicad").ready).toBe(false);
    });

    it("each tool reads its own assets when both are attached", () => {
      const part = detail({ eda: { ...FULL_KICAD, ...FULL_ALTIUM } });
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
    const r = assetReadiness(detail({ eda: FULL_ALTIUM }), "altium");
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
        passive: true,
        eda: { kicad: { symbol: ref("Device", "R"), footprint: ref("Resistor_SMD", "R_0603_1608Metric"), model: null } },
      }),
      "kicad",
    );
    expect(r.missing).toEqual([]);
    expect(r.ready).toBe(true);
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
      detail({ eda: { kicad: { symbol: ref("L", ""), footprint: ref("L", "F"), model: null } } }),
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
