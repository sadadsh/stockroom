/**
 * The reductions of a distributor offer that a surface with one line has room for.
 *
 * A column, a status bar and a sheet each need a single number off the same offers: the quantity
 * worth buying at, and the last moment anybody was asked. Both are arithmetic over the projection's
 * own normalized offers, neither renders anything, and each had drifted into whichever component
 * happened to need it first - which is how the status bar ended up importing the sourcing column to
 * learn a timestamp.
 *
 * Nothing here interpolates. A list nobody has checked reports no moment rather than the moment the
 * page was opened.
 */
import type { DistributorOffer } from "../../api/dossierTypes";

export interface OfferGroup {
  provider: string;
  providerLabel: string;
  offers: DistributorOffer[];
}

/** Preserve normalized provider and package order while naming each distributor once. */
export function groupOffersByProvider(offers: readonly DistributorOffer[]): OfferGroup[] {
  const groups = new Map<string, OfferGroup>();
  for (const offer of offers) {
    const key = offer.provider || offer.providerLabel;
    const group = groups.get(key);
    if (group) group.offers.push(offer);
    else groups.set(key, {
      provider: offer.provider,
      providerLabel: offer.providerLabel,
      offers: [offer],
    });
  }
  return [...groups.values()];
}

/** First usable in-stock offer in the backend's normalized order; no local ranking policy. */
export function suggestedProvider(offers: readonly DistributorOffer[]): string | null {
  const offer = offers.find(
    (candidate) => {
      const hasPrice =
        (candidate.unitPrice !== null && candidate.unitPrice > 0) ||
        candidate.priceBreaks.some(
          (entry) => entry.qty !== null && entry.price !== null && entry.price > 0,
        );
      return candidate.failureState === "" &&
        candidate.stock !== null &&
        candidate.stock > 0 &&
        candidate.offerUrl.trim() !== "" &&
        candidate.sku.trim() !== "" &&
        hasPrice;
    },
  );
  return offer ? (offer.provider || offer.providerLabel) : null;
}

/** The best volume break on an offer, or null when only one quantity was ever quoted. */
export function volumeBreak(offer: DistributorOffer): { qty: number; price: number } | null {
  const usable = offer.priceBreaks.filter(
    (entry): entry is { qty: number; price: number } => entry.qty !== null && entry.price !== null,
  );
  if (usable.length < 2) return null;
  return usable.reduce((best, entry) => (entry.qty > best.qty ? entry : best));
}

/** The most recent moment any distributor was read, or "" when none has been. */
export function latestCheck(offers: readonly DistributorOffer[]): string {
  const stamps = offers.map((offer) => offer.lastCheckedAt).filter(Boolean).sort();
  return stamps.length === 0 ? "" : stamps[stamps.length - 1];
}
