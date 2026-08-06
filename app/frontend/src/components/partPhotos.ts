/**
 * EVERY photograph on record for one part, as data.
 *
 * Lives beside `ProductPhoto.tsx` rather than inside it: a module that exports components must
 * export nothing else, or Vite's Fast Refresh cannot preserve that component's state across an
 * edit. The reading of a spec bag is not a component, so it belongs here.
 */
import { orderPhotos } from "../lib/sourcingOrder";
import type { SourcedAlternate } from "../api/types";

/** The photo URL out of a spec bag - either shape: a plain string (a candidate's or a
 * committed record's specs) or a Sourced DTO ({value}) straight off an EnrichmentResult. */
export function productPhotoUrl(
  specs: Record<string, unknown> | null | undefined,
): string {
  const raw = (specs ?? {})["Image"];
  const v =
    raw != null && typeof raw === "object" ? (raw as { value?: unknown }).value : raw;
  return typeof v === "string" && /^https?:\/\//i.test(v.trim()) ? v.trim() : "";
}

/** One photograph on offer, and which distributor served it. */
export interface PartPhoto {
  url: string;
  /** The distributor that supplied it, already humanised. Empty when nothing named it. */
  vendor: string;
}

// Internal source keys carry a lane suffix a person should never read ("mouser_web" is the
// scraper lane, not a company). The vendor labels are deliberately NOT a hardcoded map of every
// distributor: any unknown source is title-cased, so a new adapter shows a sensible name instead
// of nothing on the day it lands.
function vendorLabel(source: string): string {
  const base = (source || "").split("_")[0].trim();
  if (!base) return "";
  if (base.toLowerCase() === "digikey") return "DigiKey";
  if (base.toLowerCase() === "lcsc") return "LCSC";
  return base.charAt(0).toUpperCase() + base.slice(1);
}

/**
 * EVERY photograph on record for this part, in-force first, then each distributor that offered a
 * different one.
 *
 * These are real, already-stored answers, not a second fetch: both distributor adapters write
 * `specs["Image"]` with `setdefault`, so the first source wins the slot and the rest are preserved
 * as spec conflicts (`record.alternates["Image"]`) by the Batch 3 machinery. Before this, that
 * second and third photo were carried all the way into the record and then shown to nobody.
 *
 * Deduplicated by URL, because two sources naming the SAME image is the common case and a carousel
 * that pages through three identical photographs reads as broken.
 */
export function partPhotos(
  specs: Record<string, unknown> | null | undefined,
  // The record's REAL alternates type, not a structural stand-in: a hand-written shape here would
  // silently stop matching the day the DTO grows a field, and it already rejected a valid caller.
  alternates?: Record<string, SourcedAlternate[]> | null,
): PartPhoto[] {
  const out: PartPhoto[] = [];
  const seen = new Set<string>();
  const push = (url: string, source: string) => {
    const clean = url.trim();
    if (!clean || seen.has(clean)) return;
    seen.add(clean);
    out.push({ url: clean, vendor: vendorLabel(source) });
  };

  const hero = productPhotoUrl(specs);
  // The in-force photo's own origin, when the spec bag kept it as a Sourced DTO.
  const raw = (specs ?? {})["Image"];
  const heroSource =
    raw != null && typeof raw === "object" ? String((raw as { source?: unknown }).source ?? "") : "";
  if (hero) push(hero, heroSource);

  for (const alt of (alternates ?? {})["Image"] ?? []) {
    const v = alt?.value;
    if (typeof v === "string" && /^https?:\/\//i.test(v.trim())) push(v, alt.source ?? "");
  }
  // Quality order, not arrival order. Which adapter won the `specs["Image"]` slot is a race decided
  // by `setdefault`, so the in-force photo was simply whoever answered first - and the owner's
  // complaint (2026-07-26) is exactly that: the DigiKey photograph is much better than the Mouser
  // one, and Mouser was winning the hero slot. Sorted here rather than at the call site so the
  // carousel, the thumbnail and any future consumer all agree on which image leads.
  return orderPhotos(out);
}
