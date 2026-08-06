/**
 * The provenance VOCABULARY: the words a surface is allowed to use about a source, the words it is
 * never allowed to use about anything, and the one rule for reading a storage key out loud.
 *
 * `provenanceText.tsx` next door is the seam that renders these - a label, a failure sentence, a
 * compatibility notice. This is the closed set of terms underneath it, kept apart because the terms
 * have three readers that render nothing: the badge in `SheetParts.tsx`, the source list in
 * `ProvenanceHistory.tsx`, and the test that proves none of the forbidden spellings reaches a
 * normal reading surface. A vocabulary that only a component file could export is a vocabulary
 * every one of those readers has to go through a component to reach.
 *
 * A `.tsx` file with no JSX in it, on purpose: `SOURCE_STATE_TEXT` pairs each word with its copy id
 * and is resolved through `<Text>` at the render site, and the copy gates read that pairing out of
 * `.tsx` sources only. The four words would leave the letter rule's reach in a `.ts`.
 */
import type { SourceState } from "../../api/dossierTypes";
import type { StatusTone } from "../typography";

/**
 * Text that must never reach the normal reading surface, in the exact spellings that did.
 *
 * Two kinds, one list. The first four are storage words that read as if they meant something -
 * "Answered" said nothing about whether an answer was useful, "Schema version 4" said nothing at
 * all. The rest are raw backend keys, which are not English and never were.
 */
export const FORBIDDEN_IN_NORMAL_UI: readonly string[] = [
  "Answered",
  "Derived by unknown",
  "Derived at unknown",
  "Schema version",
  "Projection version",
  "Unknown keys",
  "Written by a newer build",
  "manufacturer_part_number_raw",
  "source_record_2",
  "projection_v4",
  "derived_by_unknown",
];

/**
 * A storage key as something readable, for the one surface that genuinely has no label to use.
 *
 * The record's git diff is a list of the record's OWN field names, and the projection has no label
 * for a field it does not model. Underscores become spaces and the first letter is capitalised -
 * the same rule `dossier/fields.py::humanize` applies on the backend, so the two agree - and the
 * raw key stays available in a `title` for the person who is actually searching for it.
 */
export function humanizeKey(key: string): string {
  const text = key.replace(/_/g, " ").trim();
  return text ? text[0].toUpperCase() + text.slice(1) : "";
}

/**
 * What happened to one source, in words about the SOURCE rather than about the request.
 *
 * The four are kept apart on purpose. `Failed` accuses our own fetch (network, credentials, a rate
 * limit) and is worth retrying; `Not Carried` is the distributor answering honestly that it does
 * not stock this part; `Not Connected` is this machine having no credentials and never having
 * asked. Showing all three as a blank row is what let a broken API read as a part nobody sells.
 */
export type SourceStateWord = "Supplied" | "Not Carried" | "Failed" | "Not Connected";

export const SOURCE_STATE_TEXT: Record<SourceState, { label: SourceStateWord; copyId: string }> = {
  success: { label: "Supplied", copyId: "component-browser.source-supplied" },
  unavailable: { label: "Not Carried", copyId: "component-browser.source-not-carried" },
  failed: { label: "Failed", copyId: "component-browser.source-failed" },
  not_configured: { label: "Not Connected", copyId: "component-browser.source-not-connected" },
};

/** A state a stale client (or an older record) did not send reads as `success`, never as failure. */
export function sourceStateOf(state: SourceState | undefined): SourceState {
  return state && state in SOURCE_STATE_TEXT ? state : "success";
}

const SOURCE_STATE_TONE: Record<SourceState, StatusTone> = {
  success: "ok",
  unavailable: "neutral",
  failed: "err",
  not_configured: "warn",
};

export function sourceStateTone(state: SourceState): StatusTone {
  return SOURCE_STATE_TONE[state] ?? "neutral";
}
