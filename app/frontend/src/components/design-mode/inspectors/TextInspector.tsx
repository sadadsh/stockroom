import { useMemo } from "react";
import { useCopyFormatter, useText } from "../../../lib/copy";
import { useDevMode } from "../../../lib/devMode";
import type { DomainInspectorProps } from "./types";
import { VisualCssControl } from "./VisualCssControl";

const TYPE_PROPS = [
  "color",
  "font-family",
  "font-size",
  "font-weight",
  "line-height",
  "letter-spacing",
  "text-align",
  "text-transform",
  "white-space",
  "text-overflow",
  "overflow-wrap",
] as const;

export function TextInspector(props: DomainInspectorProps) {
  const dev = useDevMode();
  const emptyLabel = useText("design-studio.inspector.text.empty", "This target has no interface text.");
  const contentLabel = useText("design-studio.inspector.text.content", "Content");
  const contentAria = useText("design-studio.inspector.text.content-aria", "Text Content");
  const readOnlyLabel = useText("design-studio.inspector.text.read-only", "Text cannot be edited until it has a stable text ID.");
  const typographyLabel = useText("design-studio.inspector.text.typography", "Font");
  const propertyAria = useCopyFormatter("design-studio.inspector.text.property-aria", "Text {property} Value");
  const texts = useMemo(
    () => props.inspection.texts,
    [props.inspection],
  );
  const copyIds = useMemo(() => {
    const ids = new Set<string>();
    for (const inspection of props.inspections) {
      for (const text of inspection.texts) {
        if (text.copyId) ids.add(text.copyId);
      }
      for (const element of inspection.target.querySelectorAll<HTMLElement>("[data-copy-id]")) {
        if (element.dataset.copyId) ids.add(element.dataset.copyId);
      }
    }
    return [...ids];
  }, [props.inspections]);
  const primary = props.inspection.texts[0] ?? texts[0];
  const copyId = copyIds[0];
  const computed = getComputedStyle(primary?.element ?? props.inspection.target);
  if (!primary) return <p className="px-3.5 py-3 text-2xs text-t3">{emptyLabel}</p>;
  return (
    <div className="px-3.5 py-3">
      {copyId ? (
        <label className="block text-xs text-t2">
          {contentLabel}
          <textarea
            aria-label={contentAria}
            value={dev.resolveCopy(copyId, primary.value)}
            onChange={(event) => copyIds.forEach((id) => dev.setCopy(id, event.target.value))}
            className="mt-1 min-h-16 w-full resize-y rounded-control border border-line bg-field px-2 py-1.5 text-xs text-t1 outline-none focus:border-focus"
          />
        </label>
      ) : <p className="text-2xs text-t3">{readOnlyLabel}</p>}
      <div className="mt-3">
        <h4 className="ui-property-label mb-1">{typographyLabel}</h4>
        {TYPE_PROPS.map((property) => (
          <label key={property} className="block py-2 text-xs text-t2">
            <span className="mb-1 block">{property.split("-").map((part) => part[0].toUpperCase() + part.slice(1)).join(" ")}</span>
            <VisualCssControl
              property={property}
              ariaLabel={propertyAria({ property })}
              value={computed.getPropertyValue(property)}
              onCommit={(value) => props.setDomainProperty("text", property, value)}
            />
          </label>
        ))}
      </div>
    </div>
  );
}
