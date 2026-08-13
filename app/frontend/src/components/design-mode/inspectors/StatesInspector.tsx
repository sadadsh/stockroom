import { useEffect, useState } from "react";
import {
  applyDesignPreviewState,
  type DesignPreviewState,
} from "../../../design-studio/previewState";
import { useCopyFormatter, useText } from "../../../lib/copy";
import { useDevMode } from "../../../lib/devMode";
import { isSafeElementValue, isThemeSpecificElementProp } from "../../../lib/elementLayout";
import { setDraftElementProperty } from "../../../lib/devModeDraft";
import { useOptionalDesignStudio } from "../../../design-studio/DesignStudioProvider";
import type { DomainInspectorProps } from "./types";

export function StatesInspector({ inspection, affectedTargetIds }: DomainInspectorProps) {
  const dev = useDevMode();
  const studio = useOptionalDesignStudio();
  const [state, setState] = useState<DesignPreviewState>("default");
  const defaultLabel = useText("design-studio.inspector.states.default", "Default");
  const hoverLabel = useText("design-studio.inspector.states.hover", "Hover");
  const focusLabel = useText("design-studio.inspector.states.focus", "Focus");
  const activeLabel = useText("design-studio.inspector.states.active", "Active");
  const disabledLabel = useText("design-studio.inspector.states.disabled", "Disabled");
  const selectedLabel = useText("design-studio.inspector.states.selected", "Selected");
  const appearanceLabel = useText("design-studio.inspector.states.appearance", "State Appearance");
  const propertyAria = useCopyFormatter("design-studio.inspector.states.property-aria", "State {property}");
  const emptyLabel = useText("design-studio.inspector.states.empty", "No product state is declared on this target.");
  const states: readonly { value: DesignPreviewState; label: string }[] = [
    { value: "default", label: defaultLabel },
    { value: "hover", label: hoverLabel },
    { value: "focus", label: focusLabel },
    { value: "active", label: activeLabel },
    { value: "selected", label: selectedLabel },
    { value: "disabled", label: disabledLabel },
  ];
  useEffect(
    () => applyDesignPreviewState(inspection.target, state),
    [inspection, state],
  );
  return (
    <div className="px-3.5 py-3">
      <div className="flex flex-wrap gap-1">
        {states.map(({ value, label }) => (
          <button key={value} type="button" aria-pressed={state === value} onClick={() => setState(value)} className="rounded-control border border-line bg-field px-2 py-1 text-2xs font-semibold capitalize text-t2 hover:text-t1">{label}</button>
        ))}
      </div>
      {state !== "default" ? (
        <section className="mt-3 border-t border-line pt-3">
          <h4 className="ui-property-label">{appearanceLabel}</h4>
          {(["color", "background-color", "border-color", "opacity", "box-shadow", "transform"] as const).map((property) => {
            const overrideId = `${inspection.id}::state:${state}`;
            return (
              <label key={`${state}-${property}`} className="grid grid-cols-[minmax(0,1fr)_104px] items-center gap-2 py-1 text-xs text-t2">
                {property.split("-").map((part) => part[0].toUpperCase() + part.slice(1)).join(" ")}
                <input
                  aria-label={propertyAria({ property: property.split("-").map((part) => part[0].toUpperCase() + part.slice(1)).join(" ") })}
                  defaultValue={dev.elementOverridesFor(overrideId)?.[property] ?? ""}
                  onBlur={(event) => {
                    const value = event.currentTarget.value.trim();
                    const stateIds = affectedTargetIds.map((id) => `${id}::state:${state}`);
                    if (!value) {
                      for (const stateId of stateIds) dev.resetElementProp(stateId, property);
                    } else if (isSafeElementValue(property, value)) {
                      if (studio && isThemeSpecificElementProp(property)) {
                        studio.replaceResolvedDraftAtomically(
                          setDraftElementProperty(dev.draft, stateIds, property, value),
                        );
                      } else {
                        for (const stateId of stateIds) dev.setElementProp(stateId, property, value);
                      }
                    }
                  }}
                  className="w-full rounded-control border border-line bg-field px-2 py-1 text-2xs font-mono text-t1 outline-none focus:border-acc"
                />
              </label>
            );
          })}
        </section>
      ) : null}
      {inspection.states.length > 0 ? (
        <dl className="mt-3 grid grid-cols-[auto_1fr] gap-x-2 gap-y-1 text-2xs">
          {inspection.states.map((item, index) => <span key={`${item.name}-${index}`} className="contents"><dt className="font-mono text-t3">{item.name}</dt><dd className="text-t2">{item.value}</dd></span>)}
        </dl>
      ) : <p className="mt-3 text-2xs text-t3">{emptyLabel}</p>}
    </div>
  );
}
