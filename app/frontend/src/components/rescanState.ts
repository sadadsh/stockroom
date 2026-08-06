/**
 * Reading the procurement-rescan state, as data.
 *
 * Lives beside `RescanSection.tsx` rather than inside it, for the reason `partPhotos.ts` sits beside
 * `ProductPhoto.tsx`: a module that exports components must export nothing else, or Vite's Fast
 * Refresh cannot preserve that component's state across an edit - and this reading is not a
 * component. Two surfaces ask the same question about the same payload (the Settings section itself
 * and the collapsed Sources row above it), so it is one function rather than two, which is what
 * keeps the row and the open body from ever disagreeing about the date.
 */
import type { RescanStateResponse } from "../api/types";

// The idle-state "last refreshed" line, derived from GET /rescan/state (the last-known
// outcome per part, uncommitted and per-machine). checked_at sorts lexically (UTC ISO-8601),
// so the last entry after a plain string sort is the most recent check.
export function lastChecked(data: RescanStateResponse): { checkedAt: string | null; total: number } {
  const entries = Object.values(data.parts);
  if (entries.length === 0) return { checkedAt: null, total: 0 };
  const sorted = entries.map((e) => e.checked_at).sort();
  const checkedAt = sorted[sorted.length - 1] ?? null;
  return { checkedAt, total: entries.length };
}
