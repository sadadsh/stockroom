import { useState } from "react";
import { useCopyFormatter, useText } from "../../../lib/copy";
import { isSafeElementValue } from "../../../lib/elementLayout";
import type { DomainInspectorProps } from "./types";

const GROUPS = [
  ["Display And Size", ["display", "width", "height", "min-width", "min-height", "max-width", "max-height"]],
  ["Spacing", ["margin", "margin-top", "margin-right", "margin-bottom", "margin-left", "padding", "padding-top", "padding-right", "padding-bottom", "padding-left", "gap", "row-gap", "column-gap"]],
  ["Appearance", ["visibility", "opacity", "background-color", "border-color", "border-radius"]],
  ["Alignment", ["flex-direction", "flex-wrap", "justify-content", "align-items", "align-content"]],
] as const;

function labelOf(property: string): string {
  return property.split("-").map((part) => part[0].toUpperCase() + part.slice(1)).join(" ");
}

function PropertyRow({ property, ...props }: { property: string } & DomainInspectorProps) {
  const resolved = getComputedStyle(props.inspection.target).getPropertyValue(property);
  const [value, setValue] = useState("");
  const valid = value === "" || isSafeElementValue(property, value);
  const valueAria = useCopyFormatter("design-studio.inspector.box.value-aria", "{property} Value");
  const resetAria = useCopyFormatter("design-studio.inspector.box.reset-aria", "Reset {property}");
  const resetLabel = useText("design-studio.inspector.box.reset", "Reset");
  const label = labelOf(property);
  return (
    <div className="grid grid-cols-[minmax(0,1fr)_104px_auto] items-center gap-2 py-1">
      <label className="truncate text-xs text-t2" htmlFor={`box-${property}`}>{label}</label>
      <input
        id={`box-${property}`}
        aria-label={valueAria({ property: label })}
        aria-invalid={!valid || undefined}
        value={value}
        placeholder={resolved}
        onChange={(event) => setValue(event.target.value)}
        onBlur={() => {
          if (!value) props.resetElementProperty(property);
          else if (valid) props.setElementProperty(property, value);
        }}
        className={`w-full rounded-control border bg-field px-2 py-1 text-2xs font-mono text-t1 outline-none ${valid ? "border-line focus:border-acc" : "border-err"}`}
      />
      <button type="button" aria-label={resetAria({ property: label })} onClick={() => { setValue(""); props.resetElementProperty(property); }} className="text-2xs font-semibold text-t3 hover:text-t1">{resetLabel}</button>
    </div>
  );
}

export function BoxInspector(props: DomainInspectorProps) {
  const note = useText("design-studio.inspector.box.advanced-note", "Position, inset, overflow, gradients, borders, shadows, flex, and grid values remain visible in Advanced when accepted in the validated application grammar.");
  return (
    <div className="px-3.5 py-2">
      {GROUPS.map(([title, properties]) => (
        <section key={title} className="border-b border-line py-2 last:border-b-0">
          <h4 className="ui-property-label mb-1">{title}</h4>
          {properties.map((property) => <PropertyRow key={property} property={property} {...props} />)}
        </section>
      ))}
      <p className="mt-2 text-2xs leading-relaxed text-t3">{note}</p>
    </div>
  );
}
