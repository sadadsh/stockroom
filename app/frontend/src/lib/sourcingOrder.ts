/**
 * How the Sourcing list is ordered, and how many price tiers it shows.
 *
 * Both rules are data, not layout code, so they can be tested without rendering and changed in
 * one line. Both come from the owner's punch list:
 *
 * - punch 4: show BOTH distributors, with Mouser prioritised. The record's own order is
 *   whatever the add flow happened to store (the pasted vendor led), which is why a part
 *   bought from DigiKey once listed DigiKey first forever.
 * - punch 5: the number of prices shown is always even. The ladder lays out in two columns, so
 *   an odd count leaves a visible hole in the bottom-right cell.
 */

interface PriceTier {
  qty: number;
  price: number;
}

// Where each distributor sits in the list, lowest first. The owner buys from Mouser by default
// and compares against DigiKey, so that is the order the panel reads in - a vendor not named
// here keeps its stored position after the ranked ones rather than being hidden or reordered
// arbitrarily.
const VENDOR_RANK: Record<string, number> = { mouser: 0, digikey: 1, lcsc: 2 };
const UNRANKED = 100;

function rank(vendor: string): number {
  return VENDOR_RANK[(vendor || "").trim().toLowerCase()] ?? UNRANKED;
}

/** The purchase rows in display order. Never drops a row: an unknown vendor is still orderable
 * and still shown, just after the ones with a known rank. */
export function orderPurchases<T extends { vendor: string }>(purchases: readonly T[]): T[] {
  // index breaks ties so unranked vendors keep the order the record stored them in (Array.sort
  // is stable in every engine we target, but being explicit costs nothing and reads clearer)
  return purchases
    .map((row, index) => ({ row, index }))
    .sort((a, b) => rank(a.row.vendor) - rank(b.row.vendor) || a.index - b.index)
    .map((e) => e.row);
}

// Where each distributor sits for IMAGE QUALITY, best first. This is deliberately NOT `VENDOR_RANK`
// above and the two must never be merged: that one is a PURCHASE preference (the owner buys from
// Mouser), so reusing it here would hand the hero photo slot to the weakest image of the three.
//
// Owner 2026-07-26: "the view photo should always prioritize the higher quality image, the digikey
// one is much better than mouser." DigiKey serve large, evenly-lit product photography; LCSC sit in
// the middle; Mouser's are the smallest and most inconsistent. Until a photo's real pixel dimensions
// are known this ranking IS the quality signal - see the note in `orderPhotos`.
const PHOTO_RANK: Record<string, number> = { digikey: 0, lcsc: 1, mouser: 2 };

/**
 * Every photograph in QUALITY order, best first, so the hero slot and the carousel's first frame
 * are the best image on record rather than whichever adapter happened to win `setdefault`.
 *
 * Never drops or reorders beyond the rank: an unranked vendor keeps its given order after the
 * ranked ones, exactly like `orderPurchases`.
 *
 * KNOWN LIMIT, deliberately not solved here: this ranks by SOURCE, not by measured resolution. The
 * true signal is the image's own intrinsic width, which is only knowable after the bytes arrive -
 * so using it would mean either a fetch per candidate before first paint, or re-ordering the
 * carousel after load, which moves the hero image under the reader's eye. Source rank is a stable
 * proxy that costs nothing and is right for the three vendors that actually ship photos today.
 */
export function orderPhotos<T extends { vendor: string }>(photos: readonly T[]): T[] {
  const photoRank = (vendor: string): number =>
    PHOTO_RANK[(vendor || "").trim().toLowerCase()] ?? UNRANKED;
  return photos
    .map((photo, index) => ({ photo, index }))
    .sort((a, b) => photoRank(a.photo.vendor) - photoRank(b.photo.vendor) || a.index - b.index)
    .map((e) => e.photo);
}

/**
 * The volume-pricing tiers to render, always an EVEN count so the two-column flow never leaves
 * a ragged hole.
 *
 * Parity is reached by ADDING data, never by hiding it: the qty-1 tier is normally redundant
 * (it is already the headline unit price beside the stock), so it is dropped - but when doing so
 * would leave an odd number of tiers, it stays in and the ladder simply reads from 1+. The result
 * is always a suffix of the real ladder, so no tier is ever omitted from the middle and none is
 * invented.
 */
export function ladderRows(breaks: readonly PriceTier[]): PriceTier[] {
  if (breaks.length < 2) return [];  // one tier IS the headline unit price; nothing to compare
  const bulk = breaks.slice(1);
  return bulk.length % 2 === 0 ? bulk : [...breaks];
}

/**
 * The price break in force for a needed quantity: the highest break whose qty is at or below `needed`.
 *
 * Falls back to the SMALLEST break when the need is below it, because that is the smallest amount the
 * vendor will actually sell - a 3000-piece reel is a reel even if you need five.
 *
 * Sorts defensively rather than trusting the stored order: `price_breaks` are scraped, and one vendor
 * emitting them descending would otherwise silently return the wrong tier.
 */
export function breakForQuantity(
  breaks: readonly PriceTier[],
  needed: number,
): PriceTier | null {
  const sorted = [...breaks].filter((b) => b.qty > 0).sort((a, b) => a.qty - b.qty);
  if (sorted.length === 0) return null;
  const want = Number.isFinite(needed) && needed > 0 ? needed : 1;
  let chosen = sorted[0];
  for (const b of sorted) {
    if (b.qty <= want) chosen = b;
  }
  return chosen;
}

/**
 * What `needed` units actually COST at this vendor, or null if it cannot be priced.
 *
 * Billed on `max(needed, smallest break qty)`, because you cannot buy below the vendor's minimum. That
 * matters for the comparison, not just for the number: costing a reel-only vendor at `5 x unit` would
 * make the most expensive option look like the cheapest one.
 */
export function extendedPrice(breaks: readonly PriceTier[], needed: number): number | null {
  const tier = breakForQuantity(breaks, needed);
  if (!tier) return null;
  const sorted = [...breaks].filter((b) => b.qty > 0).sort((a, b) => a.qty - b.qty);
  const minimum = sorted[0]?.qty ?? 1;
  const want = Number.isFinite(needed) && needed > 0 ? needed : 1;
  return tier.price * Math.max(want, minimum);
}

/** What `recommendVendor` needs off a purchase row: who, how many, at what prices. */
interface RecommendableRow {
  vendor: string;
  stock?: number | null;
  price_breaks?: unknown;
}

/**
 * Which distributor to recommend for `needed` units.
 *
 * Owner 2026-07-26: a quantity box plus "a button to choose best based on amount needed". This is what
 * finally gives the badge a stated axis - it used to compare `breaks[0].price`, the qty-1 price, so it
 * ignored quantity entirely, and the screen critique caught LCSC badged "Best" while holding the
 * LOWEST stock with nothing saying best at what.
 *
 * Two rules, in order:
 *   1. CAN they supply it. A vendor with enough stock beats a cheaper one that would leave you short.
 *      Unknown stock (`null`) counts as usable - "not reported" is not "zero", and excluding it would
 *      silently drop a good distributor.
 *   2. Then cheapest TOTAL for the quantity, not cheapest unit price.
 * If nobody can supply it, the cheapest is still recommended rather than none - the UI says the stock
 * is short; refusing to answer would be less useful than answering with a caveat.
 */
export function recommendVendor<T extends RecommendableRow>(
  rows: readonly T[],
  needed: number,
): T | null {
  const priced = rows
    .map((row) => ({
      row,
      total: extendedPrice(normalizeTiers(row.price_breaks), needed),
      enough: row.stock == null || row.stock >= (needed > 0 ? needed : 1),
    }))
    .filter((c): c is { row: T; total: number; enough: boolean } => c.total != null);
  if (priced.length === 0) return null;
  const pool = priced.some((c) => c.enough) ? priced.filter((c) => c.enough) : priced;
  return pool.reduce((best, c) => (c.total < best.total ? c : best)).row;
}

/** Tolerates the scraped shapes `price_breaks` arrives in: {qty,price} objects or [qty,price] pairs. */
function normalizeTiers(raw: unknown): PriceTier[] {
  if (!Array.isArray(raw)) return [];
  const out: PriceTier[] = [];
  for (const item of raw) {
    if (Array.isArray(item) && item.length >= 2) {
      const [qty, price] = item;
      if (typeof qty === "number" && typeof price === "number") out.push({ qty, price });
    } else if (item && typeof item === "object") {
      const { qty, price } = item as { qty?: unknown; price?: unknown };
      if (typeof qty === "number" && typeof price === "number") out.push({ qty, price });
    }
  }
  return out;
}
