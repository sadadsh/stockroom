import { useMemo } from "react";
import { useCopyFormatter, useText } from "../../../lib/copy";
import { useDevMode } from "../../../lib/devMode";
import { isSafeElementValue } from "../../../lib/elementLayout";
import type { DomainInspectorProps } from "./types";

const TYPE_PROPS = ["color", "font-size", "font-weight", "line-height", "letter-spacing", "text-align"] as const;

export function TextInspector(props: DomainInspectorProps) {
  const dev = useDevMode();
  const emptyLabel = useText("design-studio.inspector.text.empty", "This target has no interface text.");
  const contentLabel = useText("design-studio.inspector.text.content", "Content");
  const contentAria = useText("design-studio.inspector.text.content-aria", "Text Content");
  const readOnlyLabel = useText("design-studio.inspector.text.read-only", "Text cannot be edited until it has a stable text ID.");
  const typographyLabel = useText("design-studio.inspector.text.typography", "Font");
  const propertyAria = useCopyFormatter("design-studio.inspector.text.property-aria", "Text {property} Value");
  const familyLabel = useText("design-studio.inspector.text.family", "Series");
  const transformLabel = useText("design-studio.inspector.text.transform", "Transform");
  const wrappingLabel = useText("design-studio.inspector.text.wrapping", "Wrapping");
  const truncationLabel = useText("design-studio.inspector.text.truncation", "Truncation");
  const noneLabel = useText("design-studio.inspector.text.none", "none");
  const normalLabel = useText("design-studio.inspector.text.normal", "normal");
  const clipLabel = useText("design-studio.inspector.text.clip", "clip");
  const texts = useMemo(
    () => props.inspections.flatMap((inspection) => inspection.texts),
    [props.inspections],
  );
  const copyIds = useMemo(
    () => [...new Set(texts.flatMap((text) => text.copyId ? [text.copyId] : []))],
    [texts],
  );
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
            className="mt-1 min-h-16 w-full resize-y rounded-control border border-line bg-field px-2 py-1.5 text-xs text-t1 outline-none focus:border-acc"
          />
        </label>
      ) : <p className="text-2xs text-t3">{readOnlyLabel}</p>}
      <div className="mt-3">
        <h4 className="ui-property-label mb-1">{typographyLabel}</h4>
        {TYPE_PROPS.map((property) => (
          <label key={property} className="grid grid-cols-[minmax(0,1fr)_104px] items-center gap-2 py-1 text-xs text-t2">
            {property.split("-").map((part) => part[0].toUpperCase() + part.slice(1)).join(" ")}
            <input
              aria-label={propertyAria({ property })}
              placeholder={computed.getPropertyValue(property)}
              onBlur={(event) => {
                const value = event.currentTarget.value.trim();
                if (!value) props.resetDomainProperty("text", property);
                else if (isSafeElementValue(property, value)) props.setDomainProperty("text", property, value);
              }}
              className="w-full rounded-control border border-line bg-field px-2 py-1 text-2xs font-mono text-t1 outline-none focus:border-acc"
            />
          </label>
        ))}
      </div>
      <dl className="mt-3 grid grid-cols-[auto_1fr] gap-x-2 gap-y-1 text-2xs">
        <dt className="text-t3">{familyLabel}</dt><dd className="truncate text-t2">{computed.fontFamily}</dd>
        <dt className="text-t3">{transformLabel}</dt><dd className="text-t2">{computed.textTransform || noneLabel}</dd>
        <dt className="text-t3">{wrappingLabel}</dt><dd className="text-t2">{computed.whiteSpace || normalLabel}</dd>
        <dt className="text-t3">{truncationLabel}</dt><dd className="text-t2">{computed.textOverflow || clipLabel}</dd>
      </dl>
    </div>
  );
}
