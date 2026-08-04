/**
 * The bridge from the workspace projection's specification facts to the app's spec presentation.
 *
 * `lib/keySpecs.ts` already owns the answer to "which handful of parameters does a person open this
 * category of part to read", including the per-category curation and the user's pins. It speaks
 * `SpecGroup`/`SpecRow`, so the workspace's facts are adapted INTO that shape rather than the
 * curation being re-implemented against a second vocabulary - two curation lists that can disagree
 * is exactly the drift the projection was built to end.
 *
 * The group labels line up by construction: `stockroom.workspace.SPEC_GROUPS` emits the same names
 * `SpecGroupName` declares.
 */
import type { ComponentSpecificationsView } from "../../api/workspaceTypes";
import type { SpecGroup, SpecGroupName, SpecRow } from "../../lib/specSchema";

export function specGroupsFromWorkspace(
  specifications: ComponentSpecificationsView,
): SpecGroup[] {
  return specifications.groups.map((group) => ({
    title: group.label as SpecGroupName,
    rows: group.facts.map(
      (fact): SpecRow => ({
        // The projection's fact id IS the record's raw spec key, which is what the canonical spec
        // identity (and therefore a pin) is derived from.
        key: fact.id,
        label: fact.label,
        value: fact.formattedValue,
        raw: String(fact.rawValue ?? ""),
        unit: fact.unit ?? undefined,
      }),
    ),
  }));
}
