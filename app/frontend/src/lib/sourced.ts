/**
 * Shared helpers for the enrichment UI, so the passive and non-passive Add-a-Part branches
 * read a pulled result through ONE module instead of each re-deriving it (the "features call
 * the same files" rule). `sv` was copy-pasted in three components before this.
 */

/** The string value of a canonical Sourced field, or "" when the field was not pulled. */
export function sv(s: { value: unknown } | null | undefined): string {
  return s == null ? "" : String(s.value ?? "");
}

/**
 * Every source key the backend can stamp on a value, and what a PERSON should read.
 *
 * The keys are internal: they name the adapter that answered, not the thing a reader is
 * choosing between. `mouser_web` is the Mouser page scraper and `mouser` is the Mouser API,
 * and the alternates disclosure was rendering the first as "Mouser_web" - the internal key
 * with a capital letter on it, which reads like a typo and names no company.
 *
 * Two deliberate collapses:
 *   - a vendor's API adapter and its page adapter both read as THAT VENDOR. They are two ways
 *     of asking one company, and which transport won is our business, not the reader's.
 *   - jsonld / microdata / opengraph / next_data / nuxt / scrape all read "Product Page". They
 *     are five parsers over the same artifact; naming the parser tells a reader nothing they
 *     can act on, and "Opengraph" reads as noise beside "Mouser".
 *
 * Kept in sync by `tests/backend/test_source_labels.py`, which walks the backend for every
 * source key it can emit and fails when one has no entry here. Without that gate this table
 * silently rots into the Title-cased fallback, which is the bug it exists to prevent.
 */
const SOURCE_LABELS: Record<string, string> = {
  // distributors - the key may be the API adapter or the page adapter; one label either way
  mouser: "Mouser",
  mouser_web: "Mouser",
  digikey: "DigiKey",
  digikey_web: "DigiKey",
  lcsc: "LCSC",
  // the vendor's product page, however it was parsed
  jsonld: "Product Page",
  microdata: "Product Page",
  opengraph: "Product Page",
  next_data: "Product Page",
  nuxt: "Product Page",
  scrape: "Product Page",
  // everything else that can answer
  datasheet: "Datasheet",
  manufacturer_datasheet: "Manufacturer Datasheet",
  manual: "Entered by Hand",
  passive: "Part Number", // a passive MPN encodes its own value, tolerance and case size
  heuristic: "Inferred",
  files: "Files",
};

/** A source key as the label a person reads ("mouser_web" -> "Mouser"). */
export function distributorLabel(key: string): string {
  const lower = key.toLowerCase();
  // Title-case rather than render a raw key: an unmapped key must still read as a word. The
  // backend parity gate is what keeps a real source from ever reaching this line.
  return SOURCE_LABELS[lower] ?? (key ? key.charAt(0).toUpperCase() + key.slice(1) : key);
}
