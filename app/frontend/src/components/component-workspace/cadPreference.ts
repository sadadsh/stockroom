/**
 * Reading the preferred CAD source: what is in force, and what a change would replace.
 *
 * The RULE is not here. Whether a provider may be preferred, and whether a per-asset choice
 * would leave two providers in force across the three assets, is decided by the backend and
 * arrives already answered on `cadAssets.preference.options` - because that is the same function
 * that refuses the write, and a second implementation of the coherence rule in TypeScript would
 * be a second answer waiting to disagree with the one that actually governs the files.
 *
 * What lives here is the reading: which options are worth offering, how a plan reads as a
 * sentence, and which asset a module should show an override for. All of it is pure, so the
 * column and the comparison table can be rendered from one set of decisions and tested without
 * a DOM.
 */
import type {
  CadPreferenceChange,
  CadPreferenceOption,
  CadPreferenceScope,
  CadPreferenceView,
  RepresentationKind,
} from "../../api/dossierTypes";

export const CAD_ASSET_KINDS: readonly RepresentationKind[] = ["symbol", "footprint", "model"];

/**
 * The providers worth putting in front of a person for the whole set, in the backend's own order.
 *
 * A provider that CANNOT be chosen is still offered, disabled, carrying its reason - hiding it
 * would answer "why is SamacSys not in this list" with silence, and the reason ("it has no 3D
 * model for this component") is exactly the fact a person opened the control to learn. Only a
 * provider that names nothing at all is dropped, because a row with no provider is not a row.
 */
export function preferenceOptions(preference: CadPreferenceView): CadPreferenceOption[] {
  return preference.options.filter(
    (option) => option.provider !== "" && (option.set.allowed || option.set.reason !== ""),
  );
}

/** The option currently in force for the whole set, or null when nothing is chosen. */
export function chosenOption(preference: CadPreferenceView): CadPreferenceOption | null {
  return preference.options.find((option) => option.set.current) ?? null;
}

/**
 * Whether one asset's source differs from the set's, which is the ONLY case a module states it.
 *
 * Repeating the same provider sentence under all three assets is what pushed the asset itself
 * off its own header line. The column says where the set came from once; a module speaks up
 * only when it disagrees with that.
 */
export function assetOverride(
  preference: CadPreferenceView,
  kind: RepresentationKind,
): string {
  const asset = preference.assets[kind];
  if (!asset || !asset.provider) return "";
  if (!preference.mixed && asset.provider === preference.provider) return "";
  return asset.label || asset.provider;
}

/**
 * The changes a plan would make, ordered the way the three modules are stacked.
 *
 * Order matters in a confirmation: a person reads it against the column behind the dialog, and a
 * list that arrives in a different order every time reads as a different change every time.
 */
export function orderedChanges(scope: CadPreferenceScope): CadPreferenceChange[] {
  return [...scope.changes].sort(
    (a, b) => CAD_ASSET_KINDS.indexOf(a.asset) - CAD_ASSET_KINDS.indexOf(b.asset),
  );
}

/**
 * Whether choosing this needs a confirmation at all.
 *
 * A choice that replaces nothing has nothing to warn about, and a dialog that says "this will
 * change nothing, are you sure" trains a person to dismiss the dialog that matters.
 */
export function needsConfirmation(scope: CadPreferenceScope): boolean {
  return scope.allowed && scope.changes.length > 0;
}
