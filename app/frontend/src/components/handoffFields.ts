/**
 * WHICH curated fields the EDA handoff band shows, and in what order.
 *
 * Declared beside `HandoffBand.tsx` rather than in it so the band file exports nothing but its
 * component and can be hot-swapped on edit; `HandoffBand.test.tsx` asserts registry coverage
 * against this module directly.
 */
import { EDA_DATA_FIELDS } from "../lib/edaRegistry.generated";

/**
 * The order the band reads in, which is a PRESENTATION decision and deliberately not the registry's
 * emit order. It groups by what a person is looking for: who the part is (identity), what CAD it
 * carries (references), then the documents.
 *
 * The registry still decides membership - `handoffFields` below intersects this with the generated
 * curated set, and `HandoffBand.test.tsx` fails if the two ever disagree. So a field added to the
 * registry cannot be silently dropped by being missing from this list; it shows up as a test
 * failure naming it, which is the whole point of ordering here rather than filtering here.
 */
export const BAND_ORDER = [
  "mpn",
  "manufacturer",
  "category",
  "symbol",
  "footprint",
  "datasheet",
  "description",
] as const;

/** The curated fields, in band order. Exported so the test can assert registry coverage. */
export function handoffFields() {
  const curated = EDA_DATA_FIELDS.filter((f) => f.origin === "curated");
  const byKey = new Map(curated.map((f) => [f.key, f]));
  return BAND_ORDER.map((k) => byKey.get(k)).filter(
    (f): f is (typeof curated)[number] => !!f,
  );
}
