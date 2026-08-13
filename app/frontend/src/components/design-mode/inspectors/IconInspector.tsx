import { lazy, Suspense } from "react";
import { useCopyFormatter, useText } from "../../../lib/copy";
import { useDevMode } from "../../../lib/devMode";
import { ICON_IDS_BY_CATEGORY } from "../../../lib/iconRegistry";
import { resolveIcon, sanitizeIconBody } from "../../iconResolve";
import { Icon } from "../../Icon";
import type { DomainInspectorProps } from "./types";
import { designIdOf } from "../../../lib/designIdentity";
import { VisualCssControl } from "./VisualCssControl";

const IconBrowser = lazy(() => import("../IconBrowser").then((module) => ({ default: module.IconBrowser })));

export function IconInspector(props: DomainInspectorProps) {
  const dev = useDevMode();
  const iconDomains = props.inspection.icons;
  const iconIds = [...new Set(iconDomains.flatMap((icon) => {
    const id = icon.iconId ?? designIdOf(icon.element);
    return id ? [id] : [];
  }))];
  const selectedIcon = props.inspection.icons[0];
  const iconId = selectedIcon?.iconId ?? (selectedIcon ? designIdOf(selectedIcon.element) : null) ?? iconIds[0];
  const emptyLabel = useText("design-studio.inspector.icon.empty", "This target has no editable interface icon.");
  const unregisteredLabel = useText("design-studio.inspector.icon.unregistered", "The icon is not registered.");
  const resetLabel = useText("design-studio.inspector.icon.reset", "Reset Icon");
  const loadingCatalogLabel = useText("design-studio.inspector.icon.loading-catalog", "Loading icon catalog…");
  const swapAria = useCopyFormatter("design-studio.inspector.icon.swap-aria", "Swap to {icon}");
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
  if (!iconId) return <p className="px-3.5 py-3 text-2xs text-t3">{emptyLabel}</p>;
  const resolved = resolveIcon(iconId, dev.resolveIconOverride);
  const rawSvg = selectedIcon?.element instanceof SVGElement ? selectedIcon.element : null;
  const entry = resolved?.entry ?? (rawSvg ? {
    id: iconId,
    category: "bespoke" as const,
    viewBox: rawSvg.getAttribute("viewBox") ?? "0 0 24 24",
    body: sanitizeIconBody(rawSvg.innerHTML),
  } : null);
  if (!entry) return <p className="px-3.5 py-3 text-2xs text-t3">{unregisteredLabel}</p>;
  const alternatives = resolved ? ICON_IDS_BY_CATEGORY[entry.category] ?? [] : [];
  const body = dev.iconOverrideFor(iconId)?.body ?? resolved?.body ?? entry.body ?? "";
  const presentation = dev.iconOverrideFor(iconId);
  const iconStyle = getComputedStyle(selectedIcon?.element ?? props.inspection.target);
  return (
    <div className="px-3.5 py-3">
      <div className="flex items-center gap-2">
        {resolved ? <Icon id={iconId} className="h-5 w-5" /> : null}
        <span className="font-mono text-2xs text-t2">{entry.id}</span>
        {dev.isIconOverridden(iconId) ? (
          <button type="button" onClick={() => iconIds.forEach((id) => dev.resetIcon(id))} className="ml-auto text-2xs font-semibold text-t2 hover:text-t1">{resetLabel}</button>
        ) : null}
      </div>
      <div className="mt-3 flex flex-wrap gap-1">
        {alternatives.filter((id) => id !== entry.id).slice(0, 12).map((id) => (
          <button key={id} type="button" aria-label={swapAria({ icon: id })} onClick={() => iconIds.forEach((icon) => dev.setIconSwap(icon, id))} className="rounded-control border border-line p-1.5 text-t2 hover:text-t1">
            <Icon id={id} className="h-4 w-4" />
          </button>
        ))}
      </div>
      <Suspense fallback={<p className="mt-3 text-2xs text-t3">{loadingCatalogLabel}</p>}>
        <IconBrowser targetViewBox={entry.viewBox} onSelect={(selected) => {
          iconIds.forEach((id) => dev.setIconBody(id, sanitizeIconBody(selected.body)));
        }} />
      </Suspense>
      {entry.body !== undefined ? (
        <label className="mt-3 block text-xs text-t2">
          {geometryLabel}
          <textarea
            aria-label={geometryAria}
            value={body}
            onChange={(event) => {
              const sanitized = sanitizeIconBody(event.target.value);
              iconIds.forEach((id) => dev.setIconBody(id, sanitized));
            }}
            className="mt-1 min-h-20 w-full resize-y rounded-control border border-line bg-field px-2 py-1.5 font-mono text-2xs text-t1 outline-none focus:border-acc"
          />
        </label>
      ) : null}
      <div className="mt-3 grid grid-cols-3 gap-2">
        <label className="text-xs text-t2">{colorLabel}
          <div className="mt-1"><VisualCssControl property="color" ariaLabel={colorAria} value={iconStyle.color} onCommit={(value) => props.setDomainProperty("icon", "color", value)} /></div>
        </label>
        <label className="text-xs text-t2">{sizeLabel}
          <input
            type="range"
            aria-label={sizeAria}
            min={8}
            max={128}
            step={1}
            defaultValue={Number.parseFloat(iconStyle.width) || 24}
            onChange={(event) => {
              const size = `${event.currentTarget.valueAsNumber}px`;
              props.setDomainProperty("icon", "width", size);
              props.setDomainProperty("icon", "height", size);
            }}
            className="mt-2 w-full accent-[var(--c-acc)]"
          />
        </label>
        <label className="text-xs text-t2">{strokeLabel}
          <input
            type="range"
            aria-label={strokeAria}
            min={0.5}
            max={3}
            step={0.1}
            value={presentation?.strokeWidth ?? entry.strokeWidth ?? 1.5}
            onChange={(event) => {
              const value = event.currentTarget.valueAsNumber;
              if (Number.isFinite(value) && value >= 0.5 && value <= 3) {
                iconIds.forEach((id) => dev.setIconPresentation(id, { strokeWidth: value }));
              }
            }}
            className="mt-1 w-full rounded-control border border-line bg-field px-2 py-1 text-2xs text-t1"
          />
        </label>
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
