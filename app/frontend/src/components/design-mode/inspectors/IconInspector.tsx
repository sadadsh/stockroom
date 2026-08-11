import { useState } from "react";
import { useCopyFormatter, useText } from "../../../lib/copy";
import { useDevMode } from "../../../lib/devMode";
import { isSafeElementValue } from "../../../lib/elementLayout";
import { ICON_IDS_BY_CATEGORY } from "../../../lib/iconRegistry";
import { resolveIcon, sanitizeIconBody } from "../../iconResolve";
import { Icon } from "../../Icon";
import type { DomainInspectorProps } from "./types";

export function IconInspector(props: DomainInspectorProps) {
  const dev = useDevMode();
  const iconId = props.inspection.icons[0]?.iconId;
  const [size, setSize] = useState("");
  const emptyLabel = useText("design-studio.inspector.icon.empty", "This target has no editable interface icon.");
  const unregisteredLabel = useText("design-studio.inspector.icon.unregistered", "The icon is not registered.");
  const resetLabel = useText("design-studio.inspector.icon.reset", "Reset Icon");
  const swapAria = useCopyFormatter("design-studio.inspector.icon.swap-aria", "Swap to {icon}");
  const geometryLabel = useText("design-studio.inspector.icon.geometry", "Sanitized Outline");
  const geometryAria = useText("design-studio.inspector.icon.geometry-aria", "Edit Icon SVG Markup");
  const colorLabel = useText("design-studio.inspector.icon.color", "Color");
  const colorAria = useText("design-studio.inspector.icon.color-aria", "Icon Color");
  const colorPlaceholder = useText("design-studio.inspector.icon.color-placeholder", "currentColor");
  const sizeLabel = useText("design-studio.inspector.icon.size", "Size");
  const sizeAria = useText("design-studio.inspector.icon.size-aria", "Icon Size");
  const sizePlaceholder = useText("design-studio.inspector.icon.size-placeholder", "1em");
  const strokeLabel = useText("design-studio.inspector.icon.stroke", "Stroke");
  const strokeAria = useText("design-studio.inspector.icon.stroke-aria", "Icon Stroke");
  const treatmentNote = useText("design-studio.inspector.icon.treatment-note", "Stroke and fill treatment resolve from the selected icon's registered outline and current color.");
  if (!iconId) return <p className="px-3.5 py-3 text-2xs text-t3">{emptyLabel}</p>;
  const resolved = resolveIcon(iconId, dev.resolveIconOverride);
  const entry = resolved?.entry;
  if (!entry) return <p className="px-3.5 py-3 text-2xs text-t3">{unregisteredLabel}</p>;
  const alternatives = ICON_IDS_BY_CATEGORY[entry.category] ?? [];
  const body = dev.iconOverrideFor(iconId)?.body ?? entry.body ?? "";
  return (
    <div className="px-3.5 py-3">
      <div className="flex items-center gap-2">
        <Icon id={iconId} className="h-5 w-5" />
        <span className="font-mono text-2xs text-t2">{resolved.entry.id}</span>
        {dev.isIconOverridden(iconId) ? (
          <button type="button" onClick={() => dev.resetIcon(iconId)} className="ml-auto text-2xs font-semibold text-t2 hover:text-t1">{resetLabel}</button>
        ) : null}
      </div>
      <div className="mt-3 flex flex-wrap gap-1">
        {alternatives.filter((id) => id !== resolved.entry.id).slice(0, 12).map((id) => (
          <button key={id} type="button" aria-label={swapAria({ icon: id })} onClick={() => dev.setIconSwap(iconId, id)} className="rounded-control border border-line p-1.5 text-t2 hover:text-t1">
            <Icon id={id} className="h-4 w-4" />
          </button>
        ))}
      </div>
      {entry.body !== undefined ? (
        <label className="mt-3 block text-xs text-t2">
          {geometryLabel}
          <textarea
            aria-label={geometryAria}
            value={body}
            onChange={(event) => dev.setIconBody(iconId, sanitizeIconBody(event.target.value))}
            className="mt-1 min-h-20 w-full resize-y rounded-control border border-line bg-field px-2 py-1.5 font-mono text-2xs text-t1 outline-none focus:border-acc"
          />
        </label>
      ) : null}
      <div className="mt-3 grid grid-cols-3 gap-2">
        <label className="text-xs text-t2">{colorLabel}
          <input aria-label={colorAria} placeholder={colorPlaceholder} onBlur={(event) => {
            const value = event.currentTarget.value.trim();
            if (!value) props.resetElementProperty("color");
            else if (isSafeElementValue("color", value)) props.setElementProperty("color", value);
          }} className="mt-1 w-full rounded-control border border-line bg-field px-2 py-1 text-2xs text-t1" />
        </label>
        <label className="text-xs text-t2">{sizeLabel}
          <input aria-label={sizeAria} value={size} placeholder={sizePlaceholder} onChange={(event) => setSize(event.target.value)} onBlur={() => {
            if (!size) { props.resetElementProperty("width"); props.resetElementProperty("height"); }
            else if (isSafeElementValue("width", size)) { props.setElementProperty("width", size); props.setElementProperty("height", size); }
          }} className="mt-1 w-full rounded-control border border-line bg-field px-2 py-1 text-2xs text-t1" />
        </label>
        <label className="text-xs text-t2">{strokeLabel}
          <input
            type="number"
            aria-label={strokeAria}
            min={0.5}
            max={3}
            step={0.1}
            value={dev.tokenValue("--icon-stroke")}
            onChange={(event) => {
              const value = Number(event.currentTarget.value);
              if (Number.isFinite(value) && value >= 0.5 && value <= 3) {
                dev.setToken("--icon-stroke", String(value));
              }
            }}
            className="mt-1 w-full rounded-control border border-line bg-field px-2 py-1 text-2xs text-t1"
          />
        </label>
      </div>
      <p className="mt-2 text-2xs text-t3">{treatmentNote}</p>
    </div>
  );
}
