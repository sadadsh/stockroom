import { describe, expect, it } from "vitest";
import { ladderRows, orderPurchases } from "./sourcingOrder";

const p = (vendor: string, breaks: { qty: number; price: number }[] = []) => ({
  vendor,
  url: `https://${vendor}.example.com/p`,
  part_number: "",
  price_breaks: breaks,
  stock: null,
  currency: "",
  fetched_at: "",
});

describe("orderPurchases (punch 4: both distributors, Mouser prioritised)", () => {
  it("puts Mouser first whatever order the record stored", () => {
    const out = orderPurchases([p("DigiKey"), p("LCSC"), p("Mouser")]);
    expect(out.map((x) => x.vendor)).toEqual(["Mouser", "DigiKey", "LCSC"]);
  });

  it("keeps a vendor with no known rank after the ranked ones, in record order", () => {
    const out = orderPurchases([p("Acme"), p("Newark"), p("Mouser")]);
    expect(out.map((x) => x.vendor)).toEqual(["Mouser", "Acme", "Newark"]);
  });

  it("reads the rank off the stored vendor name case-insensitively", () => {
    const out = orderPurchases([p("digikey"), p("mouser")]);
    expect(out.map((x) => x.vendor)).toEqual(["mouser", "digikey"]);
  });

  it("drops nothing: every purchase row survives the sort", () => {
    const rows = [p("DigiKey"), p("Mouser"), p("LCSC"), p("Acme")];
    expect(orderPurchases(rows)).toHaveLength(4);
  });
});

describe("ladderRows (punch 5: the number of prices shown is always even)", () => {
  const ladder = (n: number) =>
    Array.from({ length: n }, (_, i) => ({ qty: 10 ** i, price: 1 / (i + 1) }));

  it("shows an even count by INCLUDING the qty-1 tier when the bulk tiers are odd", () => {
    // 6 breaks -> 5 bulk tiers is odd and leaves a hole in the 2-column flow. The fix adds
    // data rather than hiding it: the qty-1 tier joins the ladder.
    const rows = ladderRows(ladder(6));
    expect(rows).toHaveLength(6);
    expect(rows[0].qty).toBe(1);
  });

  it("drops the redundant qty-1 tier when the bulk tiers are already even", () => {
    // 5 breaks -> 4 bulk tiers: even, and qty-1 is already shown as the headline unit price
    const rows = ladderRows(ladder(5));
    expect(rows).toHaveLength(4);
    expect(rows[0].qty).toBe(10);
  });

  it("never hides a price tier: every row shown comes from the ladder", () => {
    for (const n of [2, 3, 4, 5, 6, 7, 8, 9]) {
      const rows = ladderRows(ladder(n));
      expect(rows.length % 2).toBe(0);
      // the rows shown are always a suffix of the real ladder, so no tier is invented
      expect(rows).toEqual(ladder(n).slice(ladder(n).length - rows.length));
    }
  });

  it("a single-tier ladder shows nothing, because the unit price is the headline", () => {
    expect(ladderRows(ladder(1))).toEqual([]);
  });

  it("an empty ladder shows nothing", () => {
    expect(ladderRows([])).toEqual([]);
  });
});
