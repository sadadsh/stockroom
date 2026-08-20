/**
 * What a specification ROW is, and which rows a filter keeps.
 *
 * The vocabulary is the dossier's own and is not re-derived here. Six named situations arrive on
 * every record and each one means exactly one thing:
 *
 *     Missing         the category EXPECTS this field and nobody supplied it - a real gap
 *     Not Reported    nobody supplied it and the category does not require it - not a gap
 *     Not Applicable  it does not apply to this kind of component at all
 *     Unverified      a value exists, from something short of the manufacturer's own word
 *     Conflicting     sources disagree, and every answer is carried
 *     Verified        a reviewed override, or the manufacturer's own document
 *
 * The frontend used to collapse the first three into "no value here", which is why an expected
 * field with no answer was indistinguishable from a field that does not apply. That distinction is
 * the whole point of a category schema and it cannot be recovered from an empty string, so it is
 * read off `verificationState` and never computed.
 */
import type {
  SpecificationGroup,
  SpecificationRecord,
  VerificationState,
} from "../../api/dossierTypes";
import { formatEngineeringValue, NBSP } from "../../lib/formatValue";
import type { BadgeTone } from "../primitives";

/** The tone each state carries. Semantic colour only where the state means something. */
const STATE_TONES: Record<VerificationState, BadgeTone> = {
  verified: "ok",
  unverified: "warn",
  conflicting: "err",
  missing: "warn",
  not_reported: "neutral",
  not_applicable: "neutral",
};

export function specRowTone(state: VerificationState): BadgeTone {
  return STATE_TONES[state] ?? "neutral";
}

/** True when this row has no value at all - the three states that carry nothing. */
export function isEmptyState(state: VerificationState): boolean {
  return state === "missing" || state === "not_reported" || state === "not_applicable";
}

/** The four filters. They are FILTERS: each one narrows the same list, none of them is a page. */
export type SpecFilter = "all" | "missing" | "conflicts" | "unverified";

export const SPEC_FILTERS: readonly SpecFilter[] = ["all", "conflicts", "unverified"];

/**
 * Does this row survive the filter?
 *
 * `missing` means exactly the `missing` state - NOT "has no value". A field the category does not
 * apply to is not something a person can go and fill in, and putting it under a Missing filter
 * hands them a worklist of work that does not exist.
 */
export function recordPassesFilter(
  record: SpecificationRecord,
  filter: SpecFilter,
): boolean {
  if (filter === "all") return true;
  if (filter === "missing") return record.verificationState === "missing";
  if (filter === "conflicts") return record.verificationState === "conflicting";
  return record.verificationState === "unverified";
}

/**
 * Does this row answer the search?
 *
 * Label, value, UNIT, GROUP and every source that offered an answer - not just the winning one.
 * "Which of these came from the datasheet", "what is measured in volts" and "what is under
 * Environmental" are as real as "what is the supply voltage", and a search that reads only labels
 * cannot answer any of them. Alternates are searched too: a value Mouser offered and lost with is
 * still an answer this part carries, and a search that could not find it would say the part does
 * not have it.
 */
export function recordMatchesQuery(record: SpecificationRecord, query: string): boolean {
  const needle = query.trim().toLowerCase();
  if (!needle) return true;
  const haystack = [
    record.label,
    record.displayValue,
    record.unit,
    record.groupLabel,
    record.group,
    ...record.sourceCandidates.flatMap((candidate) => [
      candidate.sourceLabel,
      candidate.displayValue,
    ]),
  ];
  return haystack.some((text) => (text ?? "").toLowerCase().includes(needle));
}

/** One heading the anchor strip can jump to. */
export interface SectionAnchor {
  id: string;
  label: string;
}

/** The id the key block anchors under. Not a group the dossier sends - the region above them. */
export const KEY_SECTION_ID = "key_specifications";

/**
 * The headings this part actually has, in the order the column renders them.
 *
 * Derived from what the dossier SENT for this category, never from a fixed list: a resistor has
 * no Timing group and a connector has no Memory group, and a strip offering headings that are not
 * on screen is a strip whose links go nowhere.
 */
export function sectionAnchors(
  groups: readonly SpecificationGroup[],
  keySpecifications: readonly SpecificationRecord[],
  keyLabel: string,
): SectionAnchor[] {
  const anchors: SectionAnchor[] = [];
  if (keySpecifications.length > 0) anchors.push({ id: KEY_SECTION_ID, label: keyLabel });
  for (const group of groups) anchors.push({ id: group.id, label: group.label });
  return anchors;
}

export interface FilteredGroup {
  group: SpecificationGroup;
  records: SpecificationRecord[];
}

/**
 * The groups a filter and a search leave behind.
 *
 * A group that loses every row is DROPPED rather than rendered empty: an empty heading under a
 * "Conflicts" filter reads as "this group has conflicts" when it means the opposite.
 */
export function filterGroups(
  groups: readonly SpecificationGroup[],
  filter: SpecFilter,
  query: string,
): FilteredGroup[] {
  return groups
    .map((group) => ({
      group,
      records: group.specifications.filter(
        (record) => recordPassesFilter(record, filter) && recordMatchesQuery(record, query),
      ),
    }))
    .filter((entry) => entry.records.length > 0);
}

/** How many rows a filter would leave across every group and the key block. */
export function countForFilter(
  groups: readonly SpecificationGroup[],
  keySpecifications: readonly SpecificationRecord[],
  filter: SpecFilter,
): number {
  const all = [...keySpecifications, ...groups.flatMap((group) => group.specifications)];
  return all.filter((record) => recordPassesFilter(record, filter)).length;
}

/** Every presented specification, key block included. The column's own total. */
export function totalSpecifications(
  groups: readonly SpecificationGroup[],
  keySpecifications: readonly SpecificationRecord[],
): number {
  return keySpecifications.length + groups.reduce((sum, group) => sum + group.count, 0);
}

/**
 * The value a row displays, typeset, with its unit.
 *
 * The projection sends the source's own words, which is what the record has to keep. The
 * TYPOGRAPHY is not the source's to decide: `lib/formatValue` binds a number to its unit with a
 * non-breaking space so the pair can never wrap apart, writes a range with an en dash and states
 * its unit once, and uses the real minus sign rather than the hyphen that sits low and narrow
 * beside the digits. Anything that is not a measurement - `Yes`, `SOT-23-5`, `±1%` - is left
 * exactly as it arrived, with the schema's unit appended only when the value carries none.
 */
export function displayWithUnit(record: SpecificationRecord): string {
  const value = record.displayValue.trim();
  if (!value) return "";
  const unit = record.unit.trim();
  const typeset = formatEngineeringValue(value, unit);
  if (typeset) return typeset;
  if (!unit || value.endsWith(unit)) return value;
  return `${value}${NBSP}${unit}`;
}

/**
 * The alternates worth showing under a row: every candidate that is not the one in force.
 *
 * A conflicting value is never silently discarded. It is listed on the row it disagrees with,
 * with the source that offered it and the trust tier that lost it the field, because that is the
 * only place the disagreement can be understood.
 */
export function alternateCandidates(record: SpecificationRecord) {
  const preferred = record.preferredSource;
  return record.sourceCandidates.filter(
    (candidate) =>
      candidate.sourceId !== preferred?.sourceId ||
      candidate.displayValue !== preferred?.displayValue,
  );
}
