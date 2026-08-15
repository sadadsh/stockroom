import { lazy, Suspense, useEffect, useState } from "react";
import { useText } from "../../../lib/copy";
import { useDevMode } from "../../../lib/devMode";
import type { IconCatalogEntry } from "../../../lib/iconRegistry";
import { resolveIcon, sanitizeIconBody } from "../../iconResolve";
import { Icon } from "../../Icon";
import type { DomainInspectorProps } from "./types";
import { designIdOf } from "../../../lib/designIdentity";
import { VisualCssControl } from "./VisualCssControl";
import { ValueSlider } from "../ValueSlider";
import { insertedIconOverrideId } from "../../../lib/applyIconOverrides";

const IconBrowser = lazy(() => import("../IconBrowser").then((module) => ({ default: module.IconBrowser })));

function IconPickerModal({ targetViewBox, onSelect, onClose }: {
  targetViewBox: string;
  onSelect: (entry: IconCatalogEntry) => void;
  onClose: () => void;
}) {
  const title = useText("design-studio.icon-picker.title", "Choose Icon");
  const closeLabel = useText("design-studio.icon-picker.close", "Close Icon Catalog");
  const loadingLabel = useText("design-studio.inspector.icon.loading-catalog", "Loading icon catalog…");
  useEffect(() => {
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      event.preventDefault();
      onClose();
    };
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [onClose]);
  return (
    <div role="presentation" className="fixed inset-0 z-[260] grid place-items-center bg-scrim p-8" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
      <section role="dialog" aria-modal="true" aria-label={title} className="flex max-h-[82vh] w-full max-w-5xl flex-col rounded-card bg-popover p-5 shadow-pop">
        <header className="flex items-center justify-between">
          <h3 className="text-base font-semibold text-t1">{title}</h3>
          <button type="button" aria-label={closeLabel} onClick={onClose} className="rounded-control px-3 py-1.5 text-sm text-t2 hover:bg-raise2 hover:text-t1">×</button>
        </header>
        <Suspense fallback={<p className="p-6 text-sm text-t3">{loadingLabel}</p>}>
          <IconBrowser targetViewBox={targetViewBox} onSelect={(entry) => { onSelect(entry); onClose(); }} />
        </Suspense>
      </section>
    </div>
  );
}

export function IconInspector(props: DomainInspectorProps) {
  const dev = useDevMode();
  const [pickerOpen, setPickerOpen] = useState(false);
  const iconDomains = props.inspection.icons;
  const iconIds = [...new Set(iconDomains.flatMap((icon) => {
    const id = icon.iconId ?? designIdOf(icon.element);
    return id ? [id] : [];
  }))];
  const selectedIcon = props.inspection.icons[0];
  const insertionId = insertedIconOverrideId(props.inspection.id);
  const inserted = dev.iconOverrideFor(insertionId);
  const iconId = selectedIcon?.iconId ?? (selectedIcon ? designIdOf(selectedIcon.element) : null) ?? iconIds[0] ?? (inserted ? insertionId : null);
  const emptyLabel = useText("design-studio.inspector.icon.empty", "This target has no editable interface icon.");
  const unregisteredLabel = useText("design-studio.inspector.icon.unregistered", "The icon is not registered.");
  const resetLabel = useText("design-studio.inspector.icon.reset", "Reset Icon");
  const geometryLabel = useText("design-studio.inspector.icon.geometry", "Sanitized Outline");
  const geometryAria = useText("design-studio.inspector.icon.geometry-aria", "Edit Icon SVG Markup");
  const colorLabel = useText("design-studio.inspector.icon.color", "Color");
  const colorAria = useText("design-studio.inspector.icon.color-aria", "Icon Color");
  const sizeLabel = useText("design-studio.inspector.icon.size", "Size");
  const sizeAria = useText("design-studio.inspector.icon.size-aria", "Icon Size");
  const strokeLabel = useText("design-studio.inspector.icon.stroke", "Stroke");
  const strokeAria = useText("design-studio.inspector.icon.stroke-aria", "Icon Stroke");
  const treatmentLabel = useText("design-studio.inspector.icon.treatment", "Treatment");
  const accessibleLabel = useText("design-studio.inspector.icon.accessible-label", "Accessible Label");
  const alignmentLabel = useText("design-studio.inspector.icon.alignment", "Alignment");
  const lineLabel = useText("design-studio.inspector.icon.treatment.line", "Line");
  const solidLabel = useText("design-studio.inspector.icon.treatment.solid", "Solid");
  const mutedLabel = useText("design-studio.inspector.icon.treatment.muted", "Muted");
  const baselineLabel = useText("design-studio.inspector.icon.alignment.baseline", "Baseline");
  const middleLabel = useText("design-studio.inspector.icon.alignment.middle", "Middle");
  const textTopLabel = useText("design-studio.inspector.icon.alignment.text-top", "Text Top");
  const textBottomLabel = useText("design-studio.inspector.icon.alignment.text-bottom", "Text Bottom");
  const addLabel = useText("design-studio.inspector.icon.add", "Add Icon");
  const chooseLabel = useText("design-studio.inspector.icon.choose", "Choose Icon");
  const addHelp = useText("design-studio.inspector.icon.add-help", "Choose an offline icon to attach to this element.");
  const placementLabel = useText("design-studio.inspector.icon.placement", "Placement");
  const currentIconLabel = useText("design-studio.inspector.icon.current", "Current Icon");
  const beforeLabel = useText("design-studio.inspector.icon.placement.before", "Before Content");
  const afterLabel = useText("design-studio.inspector.icon.placement.after", "After Content");
  if (!iconId) return (
    <div className="px-3.5 py-3">
      <h4 className="text-xs font-semibold text-t1">{addLabel}</h4>
      <p className="mt-1 text-2xs text-t3">{emptyLabel} {addHelp}</p>
      <button type="button" onClick={() => setPickerOpen(true)} className="mt-3 w-full rounded-control bg-acc px-3 py-2 text-xs font-semibold text-acc-on">{chooseLabel}</button>
      {pickerOpen ? <IconPickerModal targetViewBox="0 0 24 24" onClose={() => setPickerOpen(false)} onSelect={(selected) => dev.setIconPresentation(insertionId, {
            body: sanitizeIconBody(selected.body),
            insertInto: props.inspection.id,
            placement: "before",
          })} /> : null}
    </div>
  );
  const resolved = resolveIcon(iconId, dev.resolveIconOverride);
  const rawSvg = selectedIcon?.element instanceof SVGElement ? selectedIcon.element : null;
  const presentation = dev.iconOverrideFor(iconId);
  const entry = resolved?.entry ?? (rawSvg ? {
    id: iconId,
    category: "bespoke" as const,
    viewBox: rawSvg.getAttribute("viewBox") ?? "0 0 24 24",
    body: sanitizeIconBody(rawSvg.innerHTML),
  } : presentation?.body ? {
    id: iconId,
    category: "bespoke" as const,
    viewBox: "0 0 24 24",
    body: sanitizeIconBody(presentation.body),
  } : null);
  if (!entry) return <p className="px-3.5 py-3 text-2xs text-t3">{unregisteredLabel}</p>;
  const body = dev.iconOverrideFor(iconId)?.body ?? resolved?.body ?? entry.body ?? "";
  const iconStyle = getComputedStyle(selectedIcon?.element ?? props.inspection.target);
  return (
    <div className="px-3.5 py-3">
      <div className="flex items-center gap-2">
        {resolved ? <Icon id={iconId} className="h-5 w-5" /> : null}
        <span className="text-xs text-t2">{currentIconLabel}</span>
        {dev.isIconOverridden(iconId) ? (
          <button type="button" onClick={() => iconIds.forEach((id) => dev.resetIcon(id))} className="ml-auto text-2xs font-semibold text-t2 hover:text-t1">{resetLabel}</button>
        ) : null}
      </div>
      <button type="button" onClick={() => setPickerOpen(true)} className="mt-3 w-full rounded-control bg-raise2 px-3 py-2 text-xs font-semibold text-t1 hover:bg-control-hover">{chooseLabel}</button>
      {pickerOpen ? <IconPickerModal targetViewBox={entry.viewBox} onClose={() => setPickerOpen(false)} onSelect={(selected) => {
          iconIds.forEach((id) => dev.setIconBody(id, sanitizeIconBody(selected.body)));
        }} /> : null}
      {entry.body !== undefined ? (
        <details className="mt-3 rounded-control bg-field/50 p-2">
          <summary className="cursor-pointer text-xs text-t2">{geometryLabel}</summary>
        <label className="mt-2 block text-xs text-t2">
          {geometryLabel}
          <textarea
            aria-label={geometryAria}
            value={body}
            onChange={(event) => {
              const sanitized = sanitizeIconBody(event.target.value);
              iconIds.forEach((id) => dev.setIconBody(id, sanitized));
            }}
            className="mt-1 min-h-20 w-full resize-y rounded-control border border-line bg-field px-2 py-1.5 font-mono text-2xs text-t1 outline-none focus:border-focus"
          />
        </label></details>
      ) : null}
      <div className="mt-3 space-y-3">
        <label className="text-xs text-t2">{colorLabel}
          <div className="mt-1"><VisualCssControl property="color" ariaLabel={colorAria} value={iconStyle.color} onCommit={(value) => props.setDomainProperty("icon", "color", value)} /></div>
        </label>
        <div className="text-xs text-t2">{sizeLabel}
          <ValueSlider
            ariaLabel={sizeAria}
            min={8}
            max={128}
            step={1}
            value={Number.parseFloat(iconStyle.width) || 24}
            unit="px"
            onChange={(value) => {
              const size = `${value}px`;
              props.setDomainProperty("icon", "width", size);
              props.setDomainProperty("icon", "height", size);
            }}
            className="mt-1"
          />
        </div>
        <div className="text-xs text-t2">{strokeLabel}
          <ValueSlider
            ariaLabel={strokeAria}
            min={0.5}
            max={3}
            step={0.1}
            value={presentation?.strokeWidth ?? entry.strokeWidth ?? 1.5}
            onChange={(value) => {
              iconIds.forEach((id) => dev.setIconPresentation(id, { strokeWidth: value }));
            }}
            className="mt-1"
          />
        </div>
      </div>
      <div className="mt-3 grid grid-cols-2 gap-2">
        <label className="text-xs text-t2">{treatmentLabel}
          <select
            value={presentation?.treatment ?? "line"}
            onChange={(event) => iconIds.forEach((id) => dev.setIconPresentation(id, { treatment: event.target.value as "line" | "solid" | "muted" }))}
            className="mt-1 w-full rounded-control border border-line bg-field px-2 py-1 text-2xs text-t1"
          >
            <option value="line">{lineLabel}</option>
            <option value="solid">{solidLabel}</option>
            <option value="muted">{mutedLabel}</option>
          </select>
        </label>
        <label className="text-xs text-t2">{alignmentLabel}
          <select
            value={presentation?.alignment ?? "middle"}
            onChange={(event) => iconIds.forEach((id) => dev.setIconPresentation(id, { alignment: event.target.value as "baseline" | "middle" | "text-top" | "text-bottom" }))}
            className="mt-1 w-full rounded-control border border-line bg-field px-2 py-1 text-2xs text-t1"
          >
            <option value="baseline">{baselineLabel}</option>
            <option value="middle">{middleLabel}</option>
            <option value="text-top">{textTopLabel}</option>
            <option value="text-bottom">{textBottomLabel}</option>
          </select>
        </label>
      </div>
      {presentation?.insertInto ? (
        <label className="mt-3 block text-xs text-t2">{placementLabel}
          <select
            value={presentation.placement ?? "before"}
            onChange={(event) => dev.setIconPresentation(iconId, { placement: event.target.value as "before" | "after" })}
            className="mt-1 w-full rounded-control border border-line bg-field px-2 py-1 text-2xs text-t1"
          >
            <option value="before">{beforeLabel}</option>
            <option value="after">{afterLabel}</option>
          </select>
        </label>
      ) : null}
      <label className="mt-3 block text-xs text-t2">{accessibleLabel}
        <input
          value={presentation?.a11yLabel ?? ""}
          onChange={(event) => iconIds.forEach((id) => dev.setIconPresentation(id, { a11yLabel: event.target.value }))}
          className="mt-1 w-full rounded-control border border-line bg-field px-2 py-1 text-2xs text-t1"
        />
      </label>
    </div>
  );
}
