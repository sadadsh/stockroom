/**
 * The candidates behind ONE field: which of them lost, and which of the losers can be put in force.
 *
 * Both questions are about the record rather than about the sheet that draws it, and both have to
 * agree with what the backend will accept - so they are stated once, here, where a test can read
 * them without a DOM. `SourcesSheet.tsx` asks them per row; that is the whole of its involvement.
 */
import type { RecordFieldView, SourceCandidate } from "../../api/dossierTypes";

/**
 * The fields an alternate can be put in force on.
 *
 * `editField` writes a canonical RECORD attribute, so this is exactly the set of attributes it can
 * reach. A specification key is not one of them - it lives in `specs`, is written through a
 * different seam that carries per-key provenance, and offering an Apply here that the backend
 * would reject with "unknown field" is worse than offering none.
 */
export const APPLICABLE_FIELDS: ReadonlySet<string> = new Set([
  "display_name",
  "mpn",
  "manufacturer",
  "description",
  "value",
]);

/** Whether this alternate can be applied as-is: a known field, and a plain scalar value. */
export function canApplyAlternate(fieldId: string, alternate: SourceCandidate): boolean {
  if (!APPLICABLE_FIELDS.has(fieldId)) return false;
  const raw = alternate.value;
  return typeof raw === "string" || typeof raw === "number" || typeof raw === "boolean";
}

/** Every candidate that is not the one in force. A losing answer is never discarded. */
export function otherCandidates(field: RecordFieldView): SourceCandidate[] {
  const preferred = field.preferredSource;
  return field.sourceCandidates.filter(
    (candidate) =>
      candidate.sourceId !== preferred?.sourceId ||
      candidate.displayValue !== preferred?.displayValue,
  );
}
