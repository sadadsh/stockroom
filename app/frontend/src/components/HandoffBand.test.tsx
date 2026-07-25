/**
 * The EDA handoff band renders the REGISTRY, not a hand-written field list.
 *
 * The load-bearing test here is the coverage one: `BAND_ORDER` decides the order a person reads
 * the cells in, and it would be very easy for a field added to the Python registry to be silently
 * absent from the surface because nobody added it to that list. That is the exact failure mode the
 * registry exists to prevent, so it fails here by name instead.
 */
import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { BAND_ORDER, HandoffBand, handoffFields } from "./HandoffBand";
import { EDA_DATA_FIELDS } from "../lib/edaRegistry.generated";
import type { PartDetail } from "../api/types";

const part = (over: Partial<PartDetail> = {}): PartDetail =>
  ({
    id: "p1",
    display_name: "TPD6E05U06RVZR",
    category: "Diodes",
    description: "ESD protection diodes",
    tags: [],
    mpn: "TPD6E05U06RVZR",
    manufacturer: "Texas Instruments",
    datasheet: { file: "", source_url: "https://www.ti.com/lit/ds/symlink/tpd6e05u06.pdf", fetched_at: "" },
    purchase: [],
    eda: {
      kicad: {
        symbol: { lib: "SR-Diodes", name: "TPD6E05U06RVZR", file: "" },
        footprint: { lib: "SR-Diodes", name: "TPD6E05U06RVZR", file: "" },
        model: null,
      },
    },
    provenance: null,
    hashes: null,
    enrichment: {},
    specs: {},
    ...over,
  }) as unknown as PartDetail;

describe("HandoffBand", () => {
  it("covers EVERY curated field the registry declares, with none left out of the order", () => {
    // THE GATE. A field added to the Python registry's `data_fields` and regenerated must appear
    // in the band; if BAND_ORDER is not updated, this fails and NAMES the missing field rather
    // than the surface quietly dropping it.
    const curated = EDA_DATA_FIELDS.filter((f) => f.origin === "curated").map((f) => f.key);
    expect([...BAND_ORDER].sort()).toEqual([...curated].sort());
    expect(handoffFields().map((f) => f.key)).toEqual([...BAND_ORDER]);
  });

  it("never shows a vendor-owned or derived field, whatever the order list says", () => {
    // Price and stock belong to Sourcing and change on their own; `value` is computed at emit time
    // and stored nowhere. Showing either here would claim a person maintains it.
    const shown = new Set(handoffFields().map((f) => f.key));
    for (const key of ["price", "stock", "supplier", "lifecycle", "value"]) {
      expect(shown.has(key), `${key} must not appear in the handoff band`).toBe(false);
    }
  });

  it("reads the record's real values, and counts how many are ready", () => {
    render(<HandoffBand detail={part()} />);
    expect(screen.getByText("Texas Instruments")).toBeTruthy();
    // symbol and footprint legitimately carry the SAME reference string here, so each is read
    // from its own cell rather than by a document-wide text query
    const symbol = document.querySelector('[data-dev-id="detail.handoff-symbol"]')!;
    expect(symbol.textContent).toContain("SR-Diodes:TPD6E05U06RVZR");
    const footprint = document.querySelector('[data-dev-id="detail.handoff-footprint"]')!;
    expect(footprint.textContent).toContain("SR-Diodes:TPD6E05U06RVZR");
    // 7 of 7: every curated field on this fixture is filled.
    expect(screen.getByText(/7 of 7 ready/)).toBeTruthy();
  });

  it("names an unset field as a GAP rather than leaving the cell blank", () => {
    render(<HandoffBand detail={part({ manufacturer: "", datasheet: null })} />);
    // A blank cell reads as "nothing to see"; these are fields whose absence means the placed
    // component arrives incomplete, so they have to be visible as missing.
    expect(screen.getAllByText("Not Set").length).toBe(2);
    expect(screen.getByText(/5 of 7 ready/)).toBeTruthy();
  });

  it("shortens a long datasheet URL for display while linking the full one", () => {
    render(<HandoffBand detail={part()} />);
    const link = screen.getByRole("link", { name: /Open Datasheet/i });
    // the HREF is never the shortened form
    expect(link).toHaveAttribute(
      "href",
      "https://www.ti.com/lit/ds/symlink/tpd6e05u06.pdf",
    );
    // ... and the visible label keeps the file name, which is the identifying part
    expect(screen.getByText(/tpd6e05u06\.pdf/)).toBeTruthy();
  });

  it("marks only the fields ONE tool receives, not every cell", () => {
    render(<HandoffBand detail={part()} />);
    // Category reaches Altium alone, so it is badged. MPN reaches both, so badging it would be
    // eight identical badges saying nothing.
    const category = document.querySelector('[data-dev-id="detail.handoff-category"]')!;
    expect(category.textContent).toContain("Altium Designer");
    const mpn = document.querySelector('[data-dev-id="detail.handoff-mpn"]')!;
    expect(mpn.textContent).not.toContain("Altium Designer");
    expect(mpn.textContent).not.toContain("KiCad");
  });
});
