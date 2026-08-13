import { useCopyFormatter, useText } from "../../../lib/copy";
import type { DomainInspectorProps } from "./types";
import { VisualCssControl } from "./VisualCssControl";

const GROUPS = [
  ["layout", "Show And Size", ["display", "visibility", "position", "overflow", "inset", "top", "right", "bottom", "left", "width", "height", "min-width", "min-height", "max-width", "max-height"]],
  ["layout", "Spacing", ["margin", "margin-top", "margin-right", "margin-bottom", "margin-left", "padding", "padding-top", "padding-right", "padding-bottom", "padding-left", "gap", "row-gap", "column-gap"]],
  ["layout", "Alignment", ["flex-direction", "flex-wrap", "justify-content", "align-items", "align-content", "grid-template-columns", "grid-template-rows", "grid-auto-flow"]],
  ["appearance", "Surface", ["opacity", "background-color", "background-image", "border-color", "border-radius", "border-style", "border-width", "box-shadow", "transform", "filter", "z-index"]],
] as const;

function labelOf(property: string): string {
  return property.split("-").map((part) => part[0].toUpperCase() + part.slice(1)).join(" ");
}

function PropertyRow({ property, ...props }: { property: string } & DomainInspectorProps) {
  const resolved = getComputedStyle(props.inspection.target).getPropertyValue(property);
  const valueAria = useCopyFormatter("design-studio.inspector.box.value-aria", "{property} Value");
  const resetAria = useCopyFormatter("design-studio.inspector.box.reset-aria", "Reset {property}");
  const resetLabel = useText("design-studio.inspector.box.reset", "Reset");
  const label = labelOf(property);
  return (
    <div className="grid grid-cols-[minmax(0,1fr)_104px_auto] items-center gap-2 py-1">
      <label className="truncate text-xs text-t2" htmlFor={`box-${property}`}>{label}</label>
      <VisualCssControl property={property} ariaLabel={valueAria({ property: label })} value={resolved} onCommit={(value) => props.setDomainProperty("box", property, value)} />
      <button type="button" aria-label={resetAria({ property: label })} onClick={() => props.resetDomainProperty("box", property)} className="text-2xs font-semibold text-t3 hover:text-t1">{resetLabel}</button>
    </div>
  );
}

export function BoxInspector(props: DomainInspectorProps & { section?: "layout" | "appearance" }) {
  const section = props.section;
  const note = useText("design-studio.inspector.box.advanced-note", "Position, inset, overflow, gradients, borders, shadows, flex, and grid values remain visible in Advanced when accepted in the validated application grammar.");
  return (
    <div className="px-3.5 py-2">
      {GROUPS.filter(([group]) => !section || group === section).map(([, title, properties]) => (
        <section key={title} className="border-b border-line py-2 last:border-b-0">
          <h4 className="ui-property-label mb-1">{title}</h4>
          {properties.map((property) => <PropertyRow key={property} property={property} {...props} />)}
        </section>
      ))}
      <p className="mt-2 text-2xs leading-relaxed text-t3">{note}</p>
    </div>
  );
}
