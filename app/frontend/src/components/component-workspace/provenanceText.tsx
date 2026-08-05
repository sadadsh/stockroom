/**
 * The translation layer between what the record HOLDS and what a person can act on.
 *
 * A dossier carries plenty of true things nobody can do anything with. `Schema version 4`,
 * `Derived by unknown`, `projection_v4`, `manufacturer_part_number_raw`, a list of keys a newer
 * build wrote - every one of those is a fact about storage, and every one of them was reaching a
 * reader who came to find out whether they could buy this part.
 *
 * So this module is the seam. Each state a surface has to explain gets ONE sentence written for
 * the person reading it, and the raw form is confined to technical diagnostics, which is developer
 * territory and is the only place a storage key is the honest answer. Nothing here invents a
 * meaning the projection did not send: `compatibilityNotice` says what it says because
 * `dossier/raw.py::build_compatibility` counted the fields and named them.
 *
 * The forbidden strings are enumerated in `FORBIDDEN_IN_NORMAL_UI` rather than left implicit,
 * because a list a test can read is the only kind that stays true.
 */
import type { CompatibilityView, SourceState } from "../../api/dossierTypes";
import { Text, useCopyFormatter, useText } from "../../lib/copy";
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

/** One source's outcome, as text. A state, never a control. */
export function SourceStateLabel({ state }: { state: SourceState | undefined }) {
  const resolved = SOURCE_STATE_TEXT[sourceStateOf(state)];
  return <Text id={resolved.copyId}>{resolved.label}</Text>;
}

/**
 * Why one distributor's numbers could not be refreshed, as a sentence with a next step in it.
 *
 * A hook rather than a function because the copy is overridable like every other string here, and
 * a formatter cannot be resolved outside a render.
 */
export function useSupplyFailureText(): (failure: {
  providerLabel: string;
  provider: string;
  state: string;
}) => string {
  const failed = useCopyFormatter(
    "component-browser.offer-failed",
    "{provider} could not be read. The numbers below are the last ones it gave.",
  );
  const notCarried = useCopyFormatter(
    "component-browser.offer-not-carried",
    "{provider} does not list this component. The numbers below come from the others.",
  );
  const notConnected = useCopyFormatter(
    "component-browser.offer-not-connected",
    "{provider} is not connected on this machine, so its numbers were not refreshed.",
  );
  return (failure) => {
    const provider = failure.providerLabel || failure.provider;
    if (failure.state === "unavailable") return notCarried({ provider });
    if (failure.state === "not_configured") return notConnected({ provider });
    return failed({ provider });
  };
}

export interface CompatibilityNotice {
  tone: StatusTone;
  text: string;
  /** The fields the notice is about, so an action can take the reader to one of them. */
  fields: CompatibilityView["fields"];
}

/**
 * The one diagnostic that is ALSO a consequence for the person, translated into that consequence.
 *
 * `isFutureRecord` plus a list of keys becomes "1 field was created by a newer Stockroom version
 * and is read-only" - a count, a cause and a limitation, with the affected field reachable. What
 * it never becomes is the schema number, which tells a person nothing they can use.
 *
 * Returns null when this build understands the record completely: a reassuring notice about a
 * problem nobody has is still one more thing to read.
 */
export function useCompatibilityNotice(
  compatibility: CompatibilityView,
): CompatibilityNotice | null {
  const readOnly = useCopyFormatter(
    "component-browser.compatibility-read-only",
    "Compatibility warning: {count} of this component's fields were created by a newer version of Stockroom and are read-only here.",
  );
  const newerBuild = useText(
    "component-browser.compatibility-newer",
    "Compatibility warning: this component was saved by a newer version of Stockroom. Editing it here may discard what this version cannot read.",
  );
  if (!compatibility.hasNotice) return null;
  if (compatibility.readOnlyFieldCount > 0) {
    return {
      tone: "warn",
      text: readOnly({ count: compatibility.readOnlyFieldCount }),
      fields: compatibility.fields,
    };
  }
  return { tone: "warn", text: newerBuild, fields: [] };
}
