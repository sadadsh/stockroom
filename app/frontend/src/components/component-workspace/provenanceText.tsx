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
 * because a list a test can read is the only kind that stays true. That list, and the closed set of
 * words a surface may use about a source, are in `provenanceVocabulary.tsx`: the terms have readers
 * that render nothing, and this file is the rendering.
 */
import type { CompatibilityView, SourceState } from "../../api/dossierTypes";
import { Text, useCopyFormatter, useText } from "../../lib/copy";
import type { StatusTone } from "../typography";
import { SOURCE_STATE_TEXT, sourceStateOf } from "./provenanceVocabulary";

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
    "Compatibility warning: {count} of this component's fields came from a newer version of Stockroom and cannot be edited here.",
  );
  const newerBuild = useText(
    "component-browser.compatibility-newer",
    "Compatibility warning: a newer version of Stockroom saved this component. Editing it here might discard what this version cannot read.",
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
