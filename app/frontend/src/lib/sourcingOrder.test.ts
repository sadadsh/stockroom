import { describe, expect, it } from "vitest";
import {
  breakForQuantity,
  extendedPrice,
  ladderRows,
  orderPhotos,
  orderPurchases,
  recommendVendor,
} from "./sourcingOrder";

// Owner 2026-07-26: "the view photo should always prioritize the higher quality image, the digikey
// one is much better than mouser". This is a DIFFERENT axis from orderPurchases: that one puts
// Mouser first because that is where the owner BUYS. Ranking photos by the purchase order would
// hand the hero slot to the worst image, so the two must never be unified.
describe("orderPhotos (image quality, NOT purchase preference)", () => {
  const ph = (vendor: string) => ({ url: `https://${vendor}.example.com/i.jpg`, vendor });

  it("puts the DigiKey photograph first even though Mouser leads the purchase order", () => {
    const out = orderPhotos([ph("Mouser"), ph("DigiKey"), ph("LCSC")]);
    expect(out.map((x) => x.vendor)).toEqual(["DigiKey", "LCSC", "Mouser"]);
  });

  it("is the OPPOSITE of the purchase order for the same two vendors", () => {
    const vendors = ["Mouser", "DigiKey"];
    const photos = orderPhotos(vendors.map(ph)).map((x) => x.vendor);
    expect(photos).toEqual(["DigiKey", "Mouser"]);
  });

  it("keeps an unranked vendor after the ranked ones, in the order given", () => {
    const out = orderPhotos([ph("Arrow"), ph("Newark"), ph("DigiKey")]);
    expect(out.map((x) => x.vendor)).toEqual(["DigiKey", "Arrow", "Newark"]);
  });

  it("never drops or invents a photo", () => {
    const input = [ph("Mouser"), ph("DigiKey"), ph("Arrow")];
    expect(orderPhotos(input)).toHaveLength(3);
    expect(new Set(orderPhotos(input).map((x) => x.url))).toEqual(
      new Set(input.map((x) => x.url)),
    );
  });

  it("leaves an empty list alone", () => {
    expect(orderPhotos([])).toEqual([]);
  });
});

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

// Owner 2026-07-26: "add the volume displayed next to the stock. (it should also have a button to
// choose best based on amount needed so an amount input box thats small and doesnt disturb the ui)",
// and "best should say Recommended".
//
// The bug this replaces: Recommended compared `breaks[0].price`, i.e. the qty-1 price, so it ignored
// quantity completely - and the screen critique had already caught LCSC badged "Best" while holding
// the LOWEST stock, with nothing saying best AT WHAT.
describe("breakForQuantity", () => {
  const B = [
    { qty: 1, price: 1.22 },
    { qty: 10, price: 0.97 },
    { qty: 100, price: 0.69 },
    { qty: 1000, price: 0.49 },
  ];

  it("takes the highest break at or below the needed quantity", () => {
    expect(breakForQuantity(B, 1)?.price).toBeCloseTo(1.22, 6);
    expect(breakForQuantity(B, 9)?.price).toBeCloseTo(1.22, 6);
    expect(breakForQuantity(B, 10)?.price).toBeCloseTo(0.97, 6);
    expect(breakForQuantity(B, 99)?.price).toBeCloseTo(0.97, 6);
    expect(breakForQuantity(B, 250)?.price).toBeCloseTo(0.69, 6);
    expect(breakForQuantity(B, 100000)?.price).toBeCloseTo(0.49, 6);
  });

  it("falls back to the SMALLEST break when the need is below it, because you cannot buy fewer", () => {
    const reel = [{ qty: 3000, price: 0.1 }];
    expect(breakForQuantity(reel, 5)?.qty).toBe(3000);
  });

  it("tolerates unsorted breaks rather than trusting the vendor's order", () => {
    const messy = [{ qty: 100, price: 0.69 }, { qty: 1, price: 1.22 }, { qty: 10, price: 0.97 }];
    expect(breakForQuantity(messy, 50)?.price).toBeCloseTo(0.97, 6);
  });

  it("returns null when there are no breaks at all", () => {
    expect(breakForQuantity([], 10)).toBeNull();
  });
});

describe("extendedPrice", () => {
  const B = [{ qty: 1, price: 1.0 }, { qty: 100, price: 0.5 }];

  it("is the in-force unit price times the quantity", () => {
    expect(extendedPrice(B, 100)).toBeCloseTo(50, 6);
    expect(extendedPrice(B, 10)).toBeCloseTo(10, 6);
  });

  it("bills the MINIMUM purchasable quantity when the need is below it", () => {
    // a 3000-piece reel costs a reel even if you need 5, and comparing vendors on 5 x unit price
    // would call the reel-only vendor the cheapest when it is by far the most expensive.
    const reel = [{ qty: 3000, price: 0.01 }];
    expect(extendedPrice(reel, 5)).toBeCloseTo(30, 6);
  });

  it("is null when the vendor cannot be priced", () => {
    expect(extendedPrice([], 10)).toBeNull();
  });
});

describe("recommendVendor (quantity-aware)", () => {
  const v = (vendor: string, stock: number | null, breaks: { qty: number; price: number }[]) =>
    ({ vendor, stock, price_breaks: breaks });

  it("picks the cheapest TOTAL for the needed quantity, not the cheapest unit at qty 1", () => {
    // A leads at qty 1 (1.00 vs 1.10) but B is far cheaper by 100 - the old comparison always chose A.
    const rows = [
      v("A", 10000, [{ qty: 1, price: 1.0 }, { qty: 100, price: 0.9 }]),
      v("B", 10000, [{ qty: 1, price: 1.1 }, { qty: 100, price: 0.4 }]),
    ];
    expect(recommendVendor(rows, 1)?.vendor).toBe("A");
    expect(recommendVendor(rows, 100)?.vendor).toBe("B");
  });

  it("prefers a vendor that can actually SUPPLY the quantity over a cheaper one that cannot", () => {
    const rows = [
      v("Cheap", 5, [{ qty: 1, price: 0.1 }]),
      v("Stocked", 10000, [{ qty: 1, price: 0.5 }]),
    ];
    expect(recommendVendor(rows, 500)?.vendor).toBe("Stocked");
  });

  it("still recommends the cheapest when NOBODY has enough stock, rather than nothing at all", () => {
    const rows = [v("A", 5, [{ qty: 1, price: 0.9 }]), v("B", 5, [{ qty: 1, price: 0.4 }])];
    expect(recommendVendor(rows, 500)?.vendor).toBe("B");
  });

  it("treats unknown stock as usable rather than excluding the vendor", () => {
    // null stock means "not reported", which is not the same as zero - excluding it would silently
    // drop a perfectly good distributor.
    const rows = [v("Unknown", null, [{ qty: 1, price: 0.2 }]), v("Known", 9999, [{ qty: 1, price: 0.5 }])];
    expect(recommendVendor(rows, 10)?.vendor).toBe("Unknown");
  });

  it("ignores a vendor with no prices instead of ranking it as free", () => {
    const rows = [v("NoPrice", 9999, []), v("Priced", 9999, [{ qty: 1, price: 5 }])];
    expect(recommendVendor(rows, 10)?.vendor).toBe("Priced");
  });

  it("returns null when nothing can be priced", () => {
    expect(recommendVendor([v("A", 1, [])], 10)).toBeNull();
  });
});
