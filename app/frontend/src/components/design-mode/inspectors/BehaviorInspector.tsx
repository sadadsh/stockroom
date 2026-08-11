import { useDevMode } from "../../../lib/devMode";
import { useText } from "../../../lib/copy";
import type { DomainInspectorProps } from "./types";

export function BehaviorInspector(props: DomainInspectorProps) {
  const dev = useDevMode();
  const emptyLabel = useText("design-studio.inspector.behavior.empty", "This target has no compatible semantic control behavior.");
  const dropdownLabel = useText("design-studio.inspector.behavior.dropdown", "Dropdown");
  const segmentedLabel = useText("design-studio.inspector.behavior.segmented", "Segmented Control");
  const radioLabel = useText("design-studio.inspector.behavior.radio", "Radio Group");
  const searchableLabel = useText("design-studio.inspector.behavior.searchable", "Searchable Picker");
  const disabledLabel = useText("design-studio.inspector.behavior.disabled", "Disabled");
  const resetLabel = useText("design-studio.inspector.behavior.reset", "Reset Behavior");
  const presets = [["dropdown", dropdownLabel], ["segmented", segmentedLabel], ["radio", radioLabel], ["searchable", searchableLabel]] as const;
  if (props.inspection.behaviors.length === 0) {
    return <p className="px-3.5 py-3 text-2xs text-t3">{emptyLabel}</p>;
  }
  const current = dev.behaviorOverrideFor(props.affectedTargetIds[0] ?? props.inspection.id);
  const apply = (override: Parameters<typeof dev.setBehaviorOverride>[1]) => {
    props.affectedTargetIds.forEach((id) => dev.setBehaviorOverride(id, override));
  };
  return (
    <div className="px-3.5 py-3">
      <div className="grid grid-cols-2 gap-1.5">
        {presets.map(([preset, label]) => (
          <button key={preset} type="button" aria-pressed={(current?.preset ?? "dropdown") === preset} onClick={() => apply({ preset })} className="rounded-control border border-line bg-field px-2 py-2 text-left text-xs text-t2 hover:text-t1">{label}</button>
        ))}
      </div>
      <label className="mt-3 flex items-center justify-between text-xs text-t2">{disabledLabel}
        <input type="checkbox" checked={current?.disabled === true} onChange={(event) => apply({ ...(current ?? {}), disabled: event.target.checked })} className="accent-[var(--c-acc)]" />
      </label>
      {current ? <button type="button" onClick={() => props.affectedTargetIds.forEach((id) => dev.resetBehaviorOverride(id))} className="mt-3 text-2xs font-semibold text-t2 hover:text-t1">{resetLabel}</button> : null}
    </div>
  );
}
