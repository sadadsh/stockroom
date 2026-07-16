/**
 * Shared helpers for the enrichment UI, so the passive and non-passive Add-a-Part branches
 * read a pulled result through ONE module instead of each re-deriving it (the "features call
 * the same files" rule). `sv` was copy-pasted in three components before this.
 */

/** The string value of a canonical Sourced field, or "" when the field was not pulled. */
export function sv(s: { value: unknown } | null | undefined): string {
  return s == null ? "" : String(s.value ?? "");
}

/** A distributor key ("mouser"/"lcsc"/"digikey") as its display label ("Mouser"/"LCSC"/"DigiKey"). */
export function distributorLabel(key: string): string {
  const known: Record<string, string> = { mouser: "Mouser", lcsc: "LCSC", digikey: "DigiKey" };
  const lower = key.toLowerCase();
  return known[lower] ?? (key ? key.charAt(0).toUpperCase() + key.slice(1) : key);
}
