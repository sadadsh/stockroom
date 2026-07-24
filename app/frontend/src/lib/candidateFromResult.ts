/**
 * Merge a pulled product-page result (the pasted purchase link) onto a staging
 * candidate produced by inspecting a vendor ZIP. The link is the authority for the
 * part's DATA (identity, specs, price, buy link); the ZIP is the authority for its
 * ASSETS (symbol, footprint, 3D). So a non-passive part the user pastes a link for and
 * then drops a SnapEDA ZIP into carries everything the page gave without re-typing it.
 */
import type { EnrichmentResult, StagingCandidate } from "../api/types";
import { distributorLabel, sv } from "./sourced";
import { SPEC_HIDDEN_KEYS } from "./specSchema";

export function vendorFromUrl(url: string): string {
  let host = "";
  try {
    host = new URL(url).hostname.toLowerCase();
  } catch {
    return "manual";
  }
  if (host.includes("mouser")) return "Mouser";
  if (host.includes("lcsc")) return "LCSC";
  if (host.includes("digikey")) return "DigiKey";
  return host.replace(/^www\./, "") || "manual";
}

// A spec disagreement kept for display: every distinct value with where it came from
// ("mouser"/"digikey" from the APIs, "files" for the ZIP/schematic side). The single-value
// slot on the candidate still carries the pulled answer; the review card SHOWS the
// disagreement so the user decides before commit (merge-only-identical, owner 2026-07-24).
export interface SpecConflict {
  key: string;
  values: { value: string; source: string }[];
}

// Keys that are internal plumbing or rendered elsewhere, never a displayable spec
// disagreement: the hidden set (Image is the rendered photo, product_url the link
// marker, the asset refs) - two vendors' CDN thumbnails ALWAYS differ, and a wall of
// raw URLs labeled "Image" is noise, not a conflict (live shot 2026-07-24).
const INTERNAL_SPEC_KEYS = new Set(["product_url", ...SPEC_HIDDEN_KEYS]);

const normSpec = (v: unknown) => String(v ?? "").trim().toLowerCase();

/** Every spec disagreement around this candidate: the API-vs-API conflicts the backend
 * kept (result.spec_conflicts) plus any ZIP-vs-pull difference, folded per key. Identical
 * values (normalized) never appear - they merged. */
export function pulledSpecConflicts(
  candidate: StagingCandidate,
  result: EnrichmentResult,
): SpecConflict[] {
  const byKey = new Map<string, { value: string; source: string }[]>();
  const add = (key: string, value: string, source: string) => {
    const list = byKey.get(key) ?? [];
    if (list.every((v) => normSpec(v.value) !== normSpec(value))) {
      list.push({ value, source });
    }
    byKey.set(key, list);
  };
  for (const [key, sourced] of Object.entries(result.spec_conflicts ?? {})) {
    if (INTERNAL_SPEC_KEYS.has(key)) continue;
    for (const s of sourced) add(key, String(s.value ?? ""), s.source);
  }
  const candidateSpecs = (candidate.specs ?? {}) as Record<string, unknown>;
  for (const [key, zipValue] of Object.entries(candidateSpecs)) {
    if (INTERNAL_SPEC_KEYS.has(key) || zipValue == null) continue;
    const pulled = result.specs?.[key];
    if (pulled == null) continue;
    if (normSpec(pulled.value) === normSpec(zipValue)) continue;
    // the pulled value leads (it wins the slot), the files' answer follows
    add(key, String(pulled.value ?? ""), pulled.source);
    add(key, String(zipValue), "files");
  }
  // sorted by key so the block reads the same across pulls (the backend dict order
  // varies per lookup, which made the two themes' shots disagree)
  return Array.from(byKey.entries())
    .filter(([, values]) => values.length > 1)
    .map(([key, values]) => ({ key, values }))
    .sort((a, b) => a.key.localeCompare(b.key));
}

export function mergeResultIntoCandidate(
  candidate: StagingCandidate,
  result: EnrichmentResult,
  url: string,
): StagingCandidate {
  const mpn = sv(result.mpn);
  const manufacturer = sv(result.manufacturer);
  const description = sv(result.description);
  const pkg = sv(result.package);

  // The pulled parametric specs win for their keys (the distributor data is
  // authoritative); the internal product_url marker never becomes a spec row.
  const specs: Record<string, unknown> = { ...candidate.specs };
  for (const [k, v] of Object.entries(result.specs)) {
    if (k === "product_url" || v == null) continue;
    specs[k] = String(v.value ?? "");
  }
  if (pkg && specs.Package == null) specs.Package = pkg;

  const stockNum =
    result.stock != null && Number.isFinite(Number(result.stock.value))
      ? Number(result.stock.value)
      : null;
  // The distributor's own order number for THIS vendor (a Mouser link -> dist_pns.mouser), so the
  // committed purchase carries the P/N an order export needs, not just the manufacturer MPN.
  const primaryKey = vendorFromUrl(url).toLowerCase();
  const partNumber = result.dist_pns?.[primaryKey] ?? "";
  const priceBreaks = result.price_breaks.map((b) => ({
    qty: b.qty,
    price: b.price,
    currency: b.currency,
  }));
  // Store a purchase per distributor link we captured: when both APIs answered we keep BOTH the
  // Mouser and DigiKey buy links (the owner's ask), not only the pasted one. The pasted vendor is
  // PRIMARY and carries the pulled price ladder + stock; a second vendor stores its link + order
  // number. Fall back to the single pasted link (a render/LCSC pull with no dist_urls), then to the
  // candidate's own purchase when nothing was pulled.
  const linkEntries = Object.entries(result.dist_urls ?? {}).filter(([, u]) => u);
  let purchase: StagingCandidate["purchase"];
  if (linkEntries.length > 0) {
    // The PASTED vendor is the purchase link and leads the list (owner 2026-07-24:
    // the given link is the primary, the others ride along for price comparison);
    // every vendor carries ITS OWN ladder + stock from its API pull, so all prices show.
    const ordered = [...linkEntries].sort(
      ([a], [b]) => (a === primaryKey ? -1 : b === primaryKey ? 1 : 0),
    );
    purchase = ordered.map(([key, u]) => {
      const isPrimary = key === primaryKey;
      const own = result.dist_price_breaks?.[key];
      const ownStock = result.dist_stock?.[key];
      return {
        vendor: distributorLabel(key),
        url: isPrimary && url ? url : u,
        part_number: result.dist_pns?.[key] ?? "",
        price_breaks: own ?? (isPrimary ? priceBreaks : []),
        stock: ownStock !== undefined ? ownStock : isPrimary ? stockNum : null,
      };
    });
  } else if (url) {
    purchase = [
      { vendor: vendorFromUrl(url), url, part_number: partNumber, price_breaks: priceBreaks, stock: stockNum },
    ];
  } else {
    purchase = candidate.purchase;
  }

  return {
    ...candidate,
    mpn: mpn || candidate.mpn,
    manufacturer: manufacturer || candidate.manufacturer,
    description: description || candidate.description,
    display_name: candidate.display_name || mpn,
    category: candidate.category || result.category,
    specs,
    purchase,
  };
}
