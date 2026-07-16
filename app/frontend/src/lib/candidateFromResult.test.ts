import { describe, expect, it } from "vitest";
import type { EnrichmentResult, StagingCandidate } from "../api/types";
import { mergeResultIntoCandidate, vendorFromUrl } from "./candidateFromResult";

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
});
