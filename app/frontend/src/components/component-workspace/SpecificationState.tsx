/**
 * The six quality words, each with its own copy id.
 *
 * They live in one module because they are one closed vocabulary. Spelling `Not Reported` in two
 * places is how "Not Reported", "Not reported" and "None reported" become three words for one
 * condition, and the difference between `Missing` and `Not Reported` is the difference between a
 * gap someone has to fill and a field this category never asked for.
 */
import type { VerificationState } from "../../api/dossierTypes";
import { Text, useText } from "../../lib/copy";

export function SpecStateLabel({ state }: { state: VerificationState }) {
  if (state === "verified") return <Text id="component-browser.spec-verified">Verified</Text>;
  if (state === "conflicting")
    return <Text id="component-browser.spec-conflicting">Conflicting</Text>;
  if (state === "unverified") return <Text id="component-browser.spec-unverified">Unverified</Text>;
  if (state === "not_reported")
    return <Text id="component-browser.spec-not-reported">Not Reported</Text>;
  if (state === "not_applicable")
    return <Text id="component-browser.spec-not-applicable">Not Applicable</Text>;
  return <Text id="component-browser.spec-missing">Missing</Text>;
}

/**
 * The same six words as resolved STRINGS, for a tooltip or an accessible name.
 *
 * A row that shows a dash where a state word would be still owes the reader the word: the dash is
 * the quiet form, not the whole answer. One hook rather than six `useText` calls per row, and it
 * reads the SAME copy ids the visible labels above do, so a rewording cannot leave the accessible
 * name saying something the disclosure does not.
 */
export function useSpecStateText(): Record<VerificationState, string> {
  return {
    verified: useText("component-browser.spec-verified", "Verified"),
    conflicting: useText("component-browser.spec-conflicting", "Conflicting"),
    unverified: useText("component-browser.spec-unverified", "Unverified"),
    not_reported: useText("component-browser.spec-not-reported", "Not Reported"),
    not_applicable: useText("component-browser.spec-not-applicable", "Not Applicable"),
    missing: useText("component-browser.spec-missing", "Missing"),
  };
}
