/**
 * The EVIDENCE a search result carries: which fixed evidence columns the current result set can
 * fill, and what one row matched on.
 *
 * These are plain functions over a `SearchRow`, declared beside `SearchOverlay.tsx` rather than in
 * it: a module that exports both components and plain functions is not a Fast Refresh boundary, so
 * the overlay could not hot-swap while these lived there. `SearchOverlay.test.tsx` asserts them
 * directly.
 */
import type { SearchRow } from "../api/types";
import { prettifyValue } from "../lib/specSchema";

export const PACKAGE_KEYS = ["Package", "Package / Case", "Case", "Footprint"];
export const LIFECYCLE_KEYS = ["Lifecycle", "Part Status"];

export function normalizedLabel(value: string): string {
  return value.toLowerCase().replace(/[^a-z0-9]+/g, "");
}

export function firstSpec(
  specs: SearchRow["specs"],
  keys: readonly string[],
): string {
  const wanted = new Set(keys.map(normalizedLabel));
  for (const [key, raw] of Object.entries(specs)) {
    if (!wanted.has(normalizedLabel(key)) || raw == null || raw === "") continue;
    return prettifyValue(String(raw));
  }
  return "";
}

export function searchEvidenceColumns(rows: SearchRow[]): {
  package: boolean;
  lifecycle: boolean;
} {
  return {
    package: rows.some((row) => firstSpec(row.specs, PACKAGE_KEYS) !== ""),
    lifecycle: rows.some((row) => firstSpec(row.specs, LIFECYCLE_KEYS) !== ""),
  };
}

export function searchMatchEvidence(
  row: SearchRow,
  query: string,
): { match: string; evidence: string } {
  const exactMpn =
    query.trim() !== "" &&
    row.mpn.trim().toLowerCase() === query.trim().toLowerCase();
  // One pass: humanise and keep in the same step, in the same order, dropping exactly what
  // `.filter(Boolean)` dropped (an empty humanised key).
  const missing: string[] = [];
  for (const item of row.missing) {
    const humanised = item
      .replace(/^kicad[_\s-]*/i, "KiCad ")
      .replace(/^altium[_\s-]*/i, "Altium ")
      .replace(/[_-]+/g, " ")
      .replace(/\b\w/g, (letter) => letter.toUpperCase());
    if (humanised) missing.push(humanised);
  }
  return {
    match: exactMpn ? "Exact MPN" : query.trim() ? "Catalog Match" : "Catalog Record",
    evidence: row.is_complete
      ? "Record Evidence Complete"
      : missing.length > 0
        ? `Needs ${missing.join(", ")}`
        : "Evidence Incomplete",
  };
}
