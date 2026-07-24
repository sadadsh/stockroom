import { describe, expect, it } from "vitest";
import type { EnrichmentResult, StagingCandidate } from "../api/types";
import { mergeResultIntoCandidate, pulledSpecConflicts, vendorFromUrl } from "./candidateFromResult";

function sf(value: unknown) {
  return { value, source: "mouser", confidence: "high" };
}

const ZIP_CANDIDATE: StagingCandidate = {
  vendor: "snapeda",
  symbol_lib_path: "/tmp/x.kicad_sym",
  symbol_name: "STM32F103",
  footprint_variants: ["/tmp/LQFP48.kicad_mod"],
  chosen_footprint_index: 0,
  model_path: "/tmp/LQFP48.step",
  datasheet_path: null,
  display_name: "",
  entry_name: "STM32",
  category: "",
  mpn: "",
  manufacturer: "",
  description: "",
  tags: [],
  purchase: [],
  gaps: [],
};

const RESULT: EnrichmentResult = {
  category: "ICs",
  mpn: sf("STM32F103C8T6"),
  manufacturer: sf("STMicroelectronics"),
  description: sf("ARM Cortex-M3 MCU"),
  datasheet_url: sf("https://st.com/stm32.pdf"),
  stock: sf(1500),
  package: sf("LQFP-48"),
  dist_pns: { mouser: "581-STM32F103C8T6" },
  price_breaks: [{ qty: 1, price: 2.5, currency: "USD" }],
  specs: {
    "Core Processor": sf("ARM Cortex-M3"),
    product_url: sf("https://mouser.com/x"),
  },
  add_plan: null,
  schema_version: 1,
};

describe("mergeResultIntoCandidate", () => {
  it("takes identity + specs + purchase from the link but keeps the ZIP's assets", () => {
    const merged = mergeResultIntoCandidate(ZIP_CANDIDATE, RESULT, "https://www.mouser.com/x");
    // identity comes from the link
    expect(merged.mpn).toBe("STM32F103C8T6");
    expect(merged.manufacturer).toBe("STMicroelectronics");
    expect(merged.description).toBe("ARM Cortex-M3 MCU");
    expect(merged.display_name).toBe("STM32F103C8T6"); // ZIP had none -> filled
    expect(merged.category).toBe("ICs"); // ZIP had none -> filled from link
    // assets stay from the ZIP
    expect(merged.symbol_name).toBe("STM32F103");
    expect(merged.footprint_variants).toEqual(["/tmp/LQFP48.kicad_mod"]);
    expect(merged.model_path).toBe("/tmp/LQFP48.step");
    // specs from the link, without the internal product_url marker; package folded in
    expect(merged.specs?.["Core Processor"]).toBe("ARM Cortex-M3");
    expect(merged.specs?.product_url).toBeUndefined();
    expect(merged.specs?.Package).toBe("LQFP-48");
    // purchase: the pasted link + its vendor + price breaks + stock
    expect(merged.purchase[0].url).toBe("https://www.mouser.com/x");
    expect(merged.purchase[0].vendor).toBe("Mouser");
    expect(merged.purchase[0].price_breaks).toEqual([{ qty: 1, price: 2.5, currency: "USD" }]);
    expect(merged.purchase[0].stock).toBe(1500);
    // the Mouser order number rides onto the purchase as its part number (A3)
    expect(merged.purchase[0].part_number).toBe("581-STM32F103C8T6");
  });

  it("does not overwrite a ZIP identity the link left blank", () => {
    const zipWithId = { ...ZIP_CANDIDATE, mpn: "OWN-MPN", display_name: "My Part" };
    const blankResult = { ...RESULT, mpn: null, description: null };
    const merged = mergeResultIntoCandidate(zipWithId, blankResult, "https://x.com/y");
    expect(merged.mpn).toBe("OWN-MPN"); // link had no mpn -> ZIP's kept
    expect(merged.display_name).toBe("My Part");
  });

  it("derives the vendor from the host", () => {
    expect(vendorFromUrl("https://www.mouser.com/a")).toBe("Mouser");
    expect(vendorFromUrl("https://lcsc.com/a")).toBe("LCSC");
    expect(vendorFromUrl("https://www.digikey.com/a")).toBe("DigiKey");
    expect(vendorFromUrl("https://octopart.com/a")).toBe("octopart.com");
    expect(vendorFromUrl("not a url")).toBe("manual");
  });

  it("stores BOTH distributor buy links when both APIs answered", () => {
    // dist_urls carries the Mouser + DigiKey links; the committed part gets a purchase for each.
    const both: EnrichmentResult = {
      ...RESULT,
      dist_pns: { mouser: "581-STM32F103C8T6", digikey: "497-STM32-ND" },
      dist_urls: {
        mouser: "https://www.mouser.com/x",
        digikey: "https://www.digikey.com/en/products/detail/st/STM32F103C8T6/1",
      },
    };
    const merged = mergeResultIntoCandidate(ZIP_CANDIDATE, both, "https://www.mouser.com/x");
    const byVendor = Object.fromEntries(merged.purchase.map((p) => [p.vendor, p]));
    expect(Object.keys(byVendor).sort()).toEqual(["DigiKey", "Mouser"]);
    expect(byVendor.Mouser.url).toBe("https://www.mouser.com/x");
    expect(byVendor.DigiKey.url).toContain("digikey.com");
    expect(byVendor.Mouser.part_number).toBe("581-STM32F103C8T6");
    expect(byVendor.DigiKey.part_number).toBe("497-STM32-ND");
    // the pasted (primary) vendor carries the pulled price ladder + stock; the other keeps the link
    expect(byVendor.Mouser.price_breaks).toEqual([{ qty: 1, price: 2.5, currency: "USD" }]);
    expect(byVendor.DigiKey.price_breaks).toEqual([]);
    expect(byVendor.Mouser.stock).toBe(1500);
  });
});

describe("purchase ordering + per-vendor prices (owner 2026-07-24)", () => {
  it("the pasted vendor leads with the exact pasted url; every vendor keeps its own ladder", () => {
    const result = {
      ...RESULT,
      dist_urls: { digikey: "https://www.digikey.com/p/x", mouser: "https://www.mouser.com/c/y" },
      dist_pns: { digikey: "296-1234-ND", mouser: "595-TPD" },
      dist_price_breaks: {
        digikey: [{ qty: 1, price: 0.5, currency: "USD" }],
        mouser: [{ qty: 1, price: 0.45, currency: "USD" }],
      },
      dist_stock: { digikey: 100, mouser: 200 },
    } as unknown as EnrichmentResult;
    const pasted = "https://www.mouser.com/ProductDetail/595-TPD?qs=abc";
    const c = mergeResultIntoCandidate(ZIP_CANDIDATE, result, pasted);
    expect(c.purchase[0].vendor).toBe("Mouser");
    expect(c.purchase[0].url).toBe(pasted); // the EXACT link the user gave, qs and all
    expect(c.purchase[0].price_breaks).toEqual([{ qty: 1, price: 0.45, currency: "USD" }]);
    expect(c.purchase[0].stock).toBe(200);
    expect(c.purchase[1].vendor).toBe("DigiKey");
    expect(c.purchase[1].price_breaks).toEqual([{ qty: 1, price: 0.5, currency: "USD" }]);
    expect(c.purchase[1].stock).toBe(100);
  });
});

describe("pulledSpecConflicts", () => {
  it("keeps every API-vs-API disagreement with its sources", () => {
    const result: EnrichmentResult = {
      ...RESULT,
      spec_conflicts: {
        Resistance: [
          { value: "100 mOhm", source: "mouser", confidence: "high" },
          { value: "105 mOhm", source: "digikey", confidence: "high" },
        ],
      },
    };
    const conflicts = pulledSpecConflicts(ZIP_CANDIDATE, result);
    expect(conflicts).toEqual([
      {
        key: "Resistance",
        values: [
          { value: "100 mOhm", source: "mouser" },
          { value: "105 mOhm", source: "digikey" },
        ],
      },
    ]);
  });

  it("keeps a ZIP-vs-pull disagreement, naming the files side", () => {
    const zipWithSpecs = {
      ...ZIP_CANDIDATE,
      specs: { "Core Processor": "Cortex M3 rev2" },
    } as StagingCandidate;
    const conflicts = pulledSpecConflicts(zipWithSpecs, RESULT);
    expect(conflicts).toEqual([
      {
        key: "Core Processor",
        values: [
          { value: "ARM Cortex-M3", source: "mouser" },
          { value: "Cortex M3 rev2", source: "files" },
        ],
      },
    ]);
  });

  it("identical values (normalized) are a merge, never a conflict", () => {
    const zipWithSpecs = {
      ...ZIP_CANDIDATE,
      specs: { "Core Processor": " arm cortex-m3 " },
    } as StagingCandidate;
    expect(pulledSpecConflicts(zipWithSpecs, RESULT)).toEqual([]);
  });

  it("a key with both an API conflict and a ZIP diff folds into one entry", () => {
    const result: EnrichmentResult = {
      ...RESULT,
      spec_conflicts: {
        "Core Processor": [
          { value: "ARM Cortex-M3", source: "mouser", confidence: "high" },
          { value: "ARM Cortex M3F", source: "digikey", confidence: "high" },
        ],
      },
    };
    const zipWithSpecs = {
      ...ZIP_CANDIDATE,
      specs: { "Core Processor": "Cortex M3 rev2" },
    } as StagingCandidate;
    const [c] = pulledSpecConflicts(zipWithSpecs, result);
    expect(c.key).toBe("Core Processor");
    expect(c.values).toEqual([
      { value: "ARM Cortex-M3", source: "mouser" },
      { value: "ARM Cortex M3F", source: "digikey" },
      { value: "Cortex M3 rev2", source: "files" },
    ]);
  });

  it("never shows an Image conflict (two vendors' CDN thumbnails always differ)", () => {
    const result: EnrichmentResult = {
      ...RESULT,
      spec_conflicts: {
        Image: [
          { value: "https://mouser.com/a.jpg", source: "mouser", confidence: "medium" },
          { value: "https://digikey.com/b.jpg", source: "digikey", confidence: "medium" },
        ],
      },
    };
    expect(pulledSpecConflicts(ZIP_CANDIDATE, result)).toEqual([]);
  });

  it("sorts conflict entries by key for a stable display", () => {
    const result: EnrichmentResult = {
      ...RESULT,
      spec_conflicts: {
        RoHS: [
          { value: "RoHS Compliant", source: "mouser", confidence: "high" },
          { value: "ROHS3 Compliant", source: "digikey", confidence: "high" },
        ],
        "HTS Code": [
          { value: "8541100080", source: "mouser", confidence: "high" },
          { value: "8541.10.0080", source: "digikey", confidence: "high" },
        ],
      },
    };
    expect(pulledSpecConflicts(ZIP_CANDIDATE, result).map((c) => c.key)).toEqual([
      "HTS Code",
      "RoHS",
    ]);
  });

  it("is empty when nothing disagrees and hides internal keys", () => {
    expect(pulledSpecConflicts(ZIP_CANDIDATE, RESULT)).toEqual([]);
    // product_url is an internal marker, never a conflict row even if it differs
    const zipWithSpecs = {
      ...ZIP_CANDIDATE,
      specs: { product_url: "https://elsewhere/x" },
    } as StagingCandidate;
    expect(pulledSpecConflicts(zipWithSpecs, RESULT)).toEqual([]);
  });
});
