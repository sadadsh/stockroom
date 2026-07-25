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
