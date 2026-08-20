import { useState } from "react";
import { useText } from "../../../lib/copy";
import { EDITABLE_ELEMENT_PROPS, isSafeElementValue } from "../../../lib/elementLayout";
import type { DomainInspectorProps } from "./types";
import { isRootProtectedDesignProperty } from "../../../lib/designIdentity";

export function AdvancedInspector(props: DomainInspectorProps) {
  const [property, setProperty] = useState<string>("width");
  const [value, setValue] = useState("");
  const valid = isSafeElementValue(property, value);
  const protectedProperty = isRootProtectedDesignProperty(props.inspection.target, property);
  const semanticMappingLabel = useText("design-studio.inspector.advanced.semantic-mapping", "Semantic Mapping");
  const readOnlyHint = useText("design-studio.inspector.advanced.read-only-hint", "DOM structure cannot be edited. HTML and JavaScript are never accepted here.");
  const propertyLabel = useText("design-studio.inspector.advanced.property", "Setting");
  const propertyAria = useText("design-studio.inspector.advanced.property-aria", "Advanced Setting");
  const valueLabel = useText("design-studio.inspector.advanced.value", "Value");
  const valueAria = useText("design-studio.inspector.advanced.value-aria", "Advanced Value");
  const applyLabel = useText("design-studio.inspector.advanced.apply", "Set Validated Value");
  const resolvedLabel = useText("design-studio.inspector.advanced.resolved", "Resolved");
  const inheritedLabel = useText("design-studio.inspector.advanced.inherited", "inherited");
  const structure = {
    tag: props.inspection.target.tagName.toLowerCase(),
    id: props.inspection.id,
    role: props.inspection.role,
    semanticRole: props.inspection.semanticRole,
    accessibleName: props.inspection.accessibleName,
    childElements: props.inspection.target.children.length,
  };
  return (
    <div className="px-3.5 py-3">
      <h4 className="ui-property-label">{semanticMappingLabel}</h4>
      <pre className="mt-1 overflow-x-auto rounded-control border border-line bg-field p-2 text-2xs text-t2">{JSON.stringify(structure, null, 2)}</pre>
      <p className="mt-1 text-2xs text-t3">{readOnlyHint}</p>
      <div className="mt-3 grid grid-cols-2 gap-2">
        <label className="text-xs text-t2">{propertyLabel}
          <select aria-label={propertyAria} value={property} onChange={(event) => { setProperty(event.target.value); setValue(""); }} className="mt-1 w-full rounded-control border border-line bg-field px-2 py-1 text-2xs text-t1">
            {EDITABLE_ELEMENT_PROPS.map((name) => <option key={name} value={name}>{name}</option>)}
          </select>
        </label>
        <label className="text-xs text-t2">{valueLabel}
          <input aria-label={valueAria} aria-invalid={value !== "" && !valid || undefined} value={value} onChange={(event) => setValue(event.target.value)} className="mt-1 w-full rounded-control border border-line bg-field px-2 py-1 text-2xs font-mono text-t1" />
        </label>
      </div>
      <button type="button" disabled={!valid || protectedProperty} onClick={() => props.setDomainProperty("box", property, value)} className="mt-2 rounded-control border border-line bg-field px-2 py-1 text-2xs font-semibold text-t2 disabled:opacity-40">{applyLabel}</button>
      <dl className="mt-3 grid grid-cols-[auto_1fr] gap-x-2 gap-y-1 text-2xs"><dt className="text-t3">{resolvedLabel}</dt><dd className="truncate font-mono text-t2">{getComputedStyle(props.inspection.target).getPropertyValue(property) || inheritedLabel}</dd></dl>
    </div>
  );
}
