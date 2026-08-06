/**
 * What the identity header SAYS, read off the dossier rather than worked out here.
 *
 * Four lines and a quality summary, and every one of them is a decision about which facts earn a
 * place at the top of the screen. Those decisions are now the backend's: the key facts ARE
 * `keySpecifications` (category-aware, and already promoted out of the groups), and the quality
 * counts ARE `qualitySummary.stateCounts`. What is left here is presentation - how the parts are
 * joined, which segment gets a colour, and which asset a CAD segment should focus.
 *
 * Nothing in this module invents a value or re-scans the specification groups. A header that
 * re-derives what the projection already decided is a second, quieter answer to the same question.
 */
import type {
  ComponentDossier,
  RepresentationKind,
  RepresentationView,
  SpecificationRecord,
} from "../../api/dossierTypes";
import { formatCount, NBSP } from "../../lib/formatValue";

/** The middle dot that joins compact metadata. Never a pipe, never a slash. */
export const DOT = "·";

/** Join the parts that exist, so an absent one leaves no orphaned separator behind it. */
export function joinFacts(parts: ReadonlyArray<string | null | undefined>): string {
  return parts.map((part) => part?.trim() ?? "").filter(Boolean).join(` ${DOT} `);
}

/**
 * Is `candidate` already on screen inside `shown`?
 *
 * The four identity lines are four DIFFERENT sentences about one part, and a distributor's
 * description is routinely the value and the package again in prose: `100 nF 16V X7R 0402`. So a
 * line cannot decide what to say by looking only at the structured fields beside it - it has to
 * read the text a reader has already been given, which is exactly what this compares against.
 *
 * Matched on a WORD boundary, and a second time with the spaces taken out, so `100 nF` recognises
 * `100nF` and `0402` does not match inside `10402`. Anything looser would delete a fact that
 * merely shares digits with one already shown, which is worse than repeating it.
 */
export function alreadyStated(shown: string, candidate: string): boolean {
  const needle = compactText(candidate);
  if (!needle) return false;
  return (
    containsWord(compactText(shown), needle) ||
    containsWord(tightText(shown), tightText(candidate))
  );
}

/**
 * Lower case, one space between words, trimmed.
 *
 * `\s` covers the non-breaking space the unit formatter binds a number to its unit with, so
 * `100 nF` typeset for the screen compares equal to `100 nF` written in a description.
 */
function compactText(text: string): string {
  return text.toLowerCase().replace(/\s+/g, " ").trim();
}

/** The same, with every space removed, so `100 nF` and `100nF` are one string. */
function tightText(text: string): string {
  return compactText(text).replace(/\s+/g, "");
}

const ALPHANUMERIC = /[a-z0-9]/;

/** `needle` inside `haystack`, but never as a fragment of a longer word or number. */
function containsWord(haystack: string, needle: string): boolean {
  if (!needle) return false;
  let from = 0;
  for (;;) {
    const at = haystack.indexOf(needle, from);
    if (at < 0) return false;
    const before = haystack[at - 1] ?? "";
    const after = haystack[at + needle.length] ?? "";
    const openEdge = !ALPHANUMERIC.test(before) || !ALPHANUMERIC.test(needle[0]);
    const closeEdge =
      !ALPHANUMERIC.test(after) || !ALPHANUMERIC.test(needle[needle.length - 1]);
    if (openEdge && closeEdge) return true;
    from = at + 1;
  }
}

/**
 * Line 3: what KIND of thing this is - category, package, pin count.
 *
 * A missing member is dropped rather than rendered as an empty gap, which is the difference
 * between "Logic Gates · SOT-23-5 · 5 pins" and "Logic Gates ·  · ".
 *
 * `stated` is line 2 - the manufacturer and its own description. A member that line has already
 * said is dropped rather than repeated: a 100 nF 0402 capacitor described as `100 nF 16V X7R 0402`
 * printed `0402` on line 2, line 3 and line 4, and three sightings of one package is not three
 * facts. The package still has its canonical row in the Specifications column, where it is a
 * sourced value rather than a word in someone's prose.
 */
export function classificationLine(
  dossier: ComponentDossier,
  pinsWord: (count: number) => string,
  stated = "",
): string {
  const { category, package: pkg, pinCount } = dossier.identity;
  const pins = pinCount && pinCount > 0 ? `${formatCount(pinCount)} ${pinsWord(pinCount)}` : "";
  return joinFacts([
    category,
    alreadyStated(stated, pkg ?? "") ? "" : pkg ?? "",
    alreadyStated(stated, pins) ? "" : pins,
  ]);
}

/** How many key facts the header will carry before it stops being a header. */
export const MAX_KEY_FACTS = 6;

/**
 * Line 4: the few numbers a person opened this component to check.
 *
 * These come from `keySpecifications`, which the category schema chose - a logic gate's key set is
 * not a resistor's and is not a microcontroller's. The header does NOT re-scan the groups for
 * short-looking values, which is what it used to do and which produced a different answer per part
 * depending on what a distributor happened to emphasise.
 *
 * A key specification with no value is kept out of the HEADER only: it still has a real row in the
 * specification column, where a gap is the point. A header line of five blanks is not.
 *
 * `stated` is everything lines 2 and 3 already say. A fact that only repeats one of them is worth
 * nothing on line 4 and is dropped in favour of one that adds information - and when nothing is
 * left, the line goes rather than being padded out with what the reader has already read. The
 * capacitor that prompted this printed `100 nF · 0402` under a description reading
 * `100 nF 16V X7R 0402` and a classification reading `Capacitors · 0402`.
 */
export function keyFacts(dossier: ComponentDossier, stated = ""): SpecificationRecord[] {
  const facts: SpecificationRecord[] = [];
  // Grows as facts are accepted, so line 4 does not repeat ITSELF either: a category whose key set
  // holds both `package` and `case_code` can carry the same `0402` twice over.
  let shown = stated;
  for (const record of dossier.keySpecifications) {
    const text = keyFactText(record);
    if (!text || alreadyStated(shown, text)) continue;
    facts.push(record);
    shown = `${shown} ${DOT} ${text}`;
    if (facts.length >= MAX_KEY_FACTS) break;
  }
  return facts;
}

/** A key fact reads as its value plus its unit, with a non-breaking space between them. */
export function keyFactText(record: SpecificationRecord): string {
  const value = record.displayValue.trim();
  if (!value) return "";
  const unit = record.unit.trim();
  return unit && !value.endsWith(unit) ? `${value}${NBSP}${unit}` : value;
}

/**
 * The header's compact data-quality summary.
 *
 * Three segments at most, each of them a NAVIGATION target rather than a report: the missing count
 * filters the specification column to what is missing, the conflict count filters it to what
 * disagrees, and the CAD segment focuses the asset in question.
 */
export type QualitySegmentKind = "missing" | "conflicts" | "cad";

export interface QualitySegment {
  kind: QualitySegmentKind;
  /** How many things this segment stands for. Zero for a purely stateful CAD segment. */
  count: number;
  /** Whether this is a problem (amber/red) or a settled fact (quiet). */
  tone: "warn" | "err" | "neutral" | "ok";
}

/**
 * How many specifications the CATEGORY expects and nobody supplied.
 *
 * Read from `stateCounts.missing`, which is the only definition of missing that means anything:
 * a field nobody reported that the category does not require is `not_reported` and is NOT a gap.
 * Counting empty strings, which is what this used to do, counted both as the same problem.
 */
export function missingCount(dossier: ComponentDossier): number {
  return dossier.qualitySummary.stateCounts.missing ?? 0;
}

/** How many specifications two sources disagree about. Every answer is still carried. */
export function conflictCount(dossier: ComponentDossier): number {
  return dossier.qualitySummary.stateCounts.conflicting ?? 0;
}

/** The three assets in the order the CAD column stacks them: 3D Model, Footprint, Symbol. */
export const CAD_KINDS: readonly RepresentationKind[] = ["model", "footprint", "symbol"];

/** The CAD set's own condition, in the closed vocabulary: complete, incomplete, or failed. */
export function cadCondition(
  kinds: Record<RepresentationKind, RepresentationView>,
): { kind: "complete" | "incomplete" | "failed"; missing: RepresentationKind[] } {
  const failed = CAD_KINDS.filter((kind) => kinds[kind]?.status === "failed");
  if (failed.length > 0) return { kind: "failed", missing: failed };
  const missing = CAD_KINDS.filter((kind) => {
    const status = kinds[kind]?.status;
    return status === "missing" || status === "review";
  });
  if (missing.length > 0) return { kind: "incomplete", missing };
  return { kind: "complete", missing: [] };
}

export function qualitySegments(dossier: ComponentDossier): QualitySegment[] {
  const segments: QualitySegment[] = [];
  const missing = missingCount(dossier);
  if (missing > 0) segments.push({ kind: "missing", count: missing, tone: "warn" });
  const conflicts = conflictCount(dossier);
  if (conflicts > 0) segments.push({ kind: "conflicts", count: conflicts, tone: "err" });
  const cad = cadCondition(dossier.cadAssets.kinds);
  segments.push({
    kind: "cad",
    count: cad.missing.length,
    tone: cad.kind === "complete" ? "ok" : cad.kind === "failed" ? "err" : "warn",
  });
  return segments;
}

/**
 * The one representation a CAD quality segment should focus.
 *
 * The first thing actually wrong, or the FIRST MODULE IN THE COLUMN when nothing is - "focus the
 * asset" has to name an asset even when the set is healthy, or the segment is a dead click. The
 * healthy fallback is read off `CAD_KINDS` rather than named, so it can never disagree with the
 * order the column actually stacks the modules in (it did: the fallback was hardcoded `symbol`,
 * which is now the LAST module).
 */
export function cadFocusKind(
  kinds: Record<RepresentationKind, RepresentationView>,
): RepresentationKind {
  return cadCondition(kinds).missing[0] ?? CAD_KINDS[0];
}

/**
 * A lifecycle word's tone. Only the words that MEAN something get a colour.
 *
 * Semantic colour is spent where it encodes a decision - can this part still be designed in - and
 * nowhere else. An unrecognised word stays neutral rather than being guessed at.
 */
export function lifecycleTone(lifecycle: string): "ok" | "warn" | "err" | "neutral" {
  const value = lifecycle.trim().toLowerCase();
  if (value === "active" || value === "production") return "ok";
  if (value === "nrnd" || value === "not recommended for new designs") return "warn";
  if (value === "obsolete" || value === "eol" || value === "end of life") return "err";
  return "neutral";
}

/** The word for a pin count. Module scope: it holds no state and is rebuilt for nothing inside one. */
export function pinsWord(count: number): string {
  return count === 1 ? "pin" : "pins";
}
