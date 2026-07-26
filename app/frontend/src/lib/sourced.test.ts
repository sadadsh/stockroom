/**
 * A person reading "who said this" must see a source they recognise.
 *
 * The alternates disclosure rendered `Mouser_web` - the internal key of the Mouser page
 * ADAPTER, Title-cased by a fallback that assumed every key was already a vendor name. The
 * same fallback also produced `Digikey_web`, `Jsonld`, `Next_data` and `Opengraph`, none of
 * which name anything a person can act on.
 */
import { describe, it, expect } from "vitest";
import { distributorLabel } from "./sourced";

describe("distributorLabel", () => {
  it("names the VENDOR, whichever of that vendor's adapters answered", () => {
    // The API adapter and the page adapter are two ways of asking ONE company.
    expect(distributorLabel("mouser")).toBe("Mouser");
    expect(distributorLabel("mouser_web")).toBe("Mouser");
    expect(distributorLabel("digikey")).toBe("DigiKey");
    expect(distributorLabel("digikey_web")).toBe("DigiKey");
    expect(distributorLabel("lcsc")).toBe("LCSC");
  });

  it("calls page-markup extractors what they ARE, not how they were parsed", () => {
    // jsonld / microdata / opengraph / next_data / nuxt are five ways of reading ONE thing:
    // the vendor's product page. The mechanism is an implementation detail of the scraper and
    // means nothing to the person deciding which answer to trust.
    for (const key of ["jsonld", "microdata", "opengraph", "next_data", "nuxt", "scrape"]) {
      expect(distributorLabel(key)).toBe("Product Page");
    }
  });

  it("names the non-vendor sources in the reader's terms", () => {
    expect(distributorLabel("datasheet")).toBe("Datasheet");
    expect(distributorLabel("manual")).toBe("Entered by Hand");
    expect(distributorLabel("passive")).toBe("Part Number");
    expect(distributorLabel("heuristic")).toBe("Inferred");
    expect(distributorLabel("files")).toBe("Files");
  });

  it("Title-cases an unknown key rather than rendering it raw", () => {
    // The fallback stays: a source key added on the backend must still read as SOMETHING.
    // The backend-side parity gate (tests/backend/test_source_labels.py) is what stops a new
    // key reaching a user through this fallback.
    expect(distributorLabel("newvendor")).toBe("Newvendor");
    expect(distributorLabel("")).toBe("");
  });

  it("is case-insensitive, because a record may carry either spelling", () => {
    expect(distributorLabel("MOUSER_WEB")).toBe("Mouser");
    expect(distributorLabel("DigiKey")).toBe("DigiKey");
  });
});
