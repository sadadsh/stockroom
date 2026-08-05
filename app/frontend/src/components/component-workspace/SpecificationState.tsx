/**
 * The six quality words, each with its own copy id.
 *
 * They live in one module because they are one closed vocabulary. Spelling `Not Reported` in two
 * places is how "Not Reported", "Not reported" and "None reported" become three words for one
 * condition, and the difference between `Missing` and `Not Reported` is the difference between a
 * gap someone has to fill and a field this category never asked for.
 */
import type { VerificationState } from "../../api/dossierTypes";
import { Text } from "../../lib/copy";

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
