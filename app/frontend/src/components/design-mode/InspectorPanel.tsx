import { useMemo, useState } from "react";
import {
  inspectTarget,
  previewTargetScope,
  type EditableTargetDomain,
  type TargetInspection,
} from "../../design-studio/targetDomains";
import { useOptionalDesignStudio } from "../../design-studio/DesignStudioProvider";
import { useDevMode } from "../../lib/devMode";
import { useText } from "../../lib/copy";
import {
  emptyDevModeDraft,
  resetDraftElementProperty,
  resetDraftTargets,
  resetDraftTheme,
  setDraftElementProperty,
} from "../../lib/devModeDraft";
import { isThemeSpecificElementProp } from "../../lib/elementLayout";
import { AdvancedInspector } from "./inspectors/AdvancedInspector";
import { BehaviorInspector } from "./inspectors/BehaviorInspector";
import { BoxInspector } from "./inspectors/BoxInspector";
import { IconInspector } from "./inspectors/IconInspector";
import { LayoutInspector } from "./inspectors/LayoutInspector";
import { StatesInspector } from "./inspectors/StatesInspector";
import { TextInspector } from "./inspectors/TextInspector";
import { CadPresentationInspector } from "./inspectors/CadPresentationInspector";

type InspectorFacet = "layout" | "appearance" | "content" | "advanced";

function rootElement(root?: Element): Element {
  return root ?? document.documentElement;
}

function inspectionFor(root: Element, id: string | null): TargetInspection | null {
  if (!id) return null;
  try {
    return inspectTarget(root, id);
  } catch {
    return null;
  }
}

function domainKeys(inspections: readonly TargetInspection[]) {
  return {
    targetIds: inspections.map((inspection) => inspection.id),
    copyIds: [...new Set(inspections.flatMap((inspection) => inspection.texts.flatMap((text) => text.copyId ? [text.copyId] : [])))],
    iconIds: [...new Set(inspections.flatMap((inspection) => inspection.icons.flatMap((icon) => icon.iconId ? [icon.iconId] : [])))],
  };
}

function inspectionsFor(root: Element, ids: readonly string[]): TargetInspection[] {
  return ids
    .map((id) => inspectionFor(root, id))
    .filter((item): item is TargetInspection => item !== null);
}

export function InspectorPanel({ root }: { root?: Element; integrated?: boolean } = {}) {
  const dev = useDevMode();
  const studio = useOptionalDesignStudio();
  const defaultFacet: InspectorFacet = "layout";
  const [facetState, setFacetState] = useState<{ targetId: string | null; value: InspectorFacet }>(() => ({ targetId: dev.selectedDevId, value: defaultFacet }));
  const facet = facetState.targetId === dev.selectedDevId ? facetState.value : defaultFacet;
  const setFacet = (value: InspectorFacet) => setFacetState({ targetId: dev.selectedDevId, value });
  const resolvedRoot = rootElement(root);
  const inspection = useMemo(
    () => inspectionFor(resolvedRoot, dev.selectedDevId),
    [dev.selectedDevId, resolvedRoot],
  );
  const contextualInspectorLabel = useText("design-studio.inspector.context", "Contextual Inspector");
  const targetDomainsLabel = useText("design-studio.inspector.target-domains", "Target Domains");
  const inspectorDomainsLabel = useText("design-studio.inspector.domains", "Inspector Domains");
  const boxLabel = useText("design-studio.inspector.domain.box", "Box");
  const textLabel = useText("design-studio.inspector.domain.text", "Text");
  const iconLabel = useText("design-studio.inspector.domain.icon", "Icon");
  const layoutLabel = useText("design-studio.inspector.domain.layout", "Arrangement");
  const appearanceLabel = useText("design-studio.inspector.domain.appearance", "Appearance");
  const contentLabel = useText("design-studio.inspector.domain.content", "Content");
  const behaviorLabel = useText("design-studio.inspector.domain.behavior", "Behavior");
  const statesLabel = useText("design-studio.inspector.domain.states", "States");
  const advancedLabel = useText("design-studio.inspector.domain.advanced", "Advanced");
  const screenLabel = useText("design-studio.inspector.scope.screen", "Screen");
  const resetLabel = useText("design-studio.inspector.reset", "Reset");
  const targetLabel = useText("design-studio.inspector.reset.target", "Target");
  const variationLabel = useText("design-studio.inspector.reset.variation", "Variation");
  const themeLabel = useText("design-studio.inspector.reset.theme", "Theme");
  const fullDesignLabel = useText("design-studio.inspector.reset.full-design", "Full Personal Design");
  const textDomainPreviewLabel = useText("design-studio.inspector.domain.text-preview", "Text Domain Preview");
  const iconDomainPreviewLabel = useText("design-studio.inspector.domain.icon-preview", "Icon Domain Preview");
  const facets: readonly { id: InspectorFacet; label: string }[] = [
    { id: "layout", label: layoutLabel },
    { id: "appearance", label: appearanceLabel },
    { id: "content", label: contentLabel },
    { id: "advanced", label: advancedLabel },
  ];
  const affectedTargetIds = useMemo(
    () => inspection
      ? inspection.role
        ? previewTargetScope(resolvedRoot, inspection.id, "role").affectedTargetIds
        : [inspection.id]
      : [],
    [inspection, resolvedRoot],
  );
  const affectedInspections = useMemo(
    () => inspectionsFor(resolvedRoot, affectedTargetIds),
    [affectedTargetIds, resolvedRoot],
  );

  if (!dev.enabled || !inspection) return null;

  const domainOverrideIds = (domain: EditableTargetDomain) => {
    const ids = new Set<string>();
    for (const item of affectedInspections) {
      const target = item.editTargets[domain];
      if (target.elements.length > 0) ids.add(target.overrideId);
    }
    return [...ids];
  };
  const setDomainProperty = (domain: EditableTargetDomain, property: string, value: string) => {
    const ids = domainOverrideIds(domain);
    if (studio && isThemeSpecificElementProp(property)) {
      studio.replaceResolvedDraftAtomically(
        setDraftElementProperty(dev.draft, ids, property, value),
      );
      return;
    }
    ids.forEach((id) => dev.setElementProp(id, property, value));
  };
  const resetDomainProperty = (domain: EditableTargetDomain, property: string) => {
    const next = resetDraftElementProperty(dev.draft, domainOverrideIds(domain), property);
    if (studio) studio.replaceResolvedDraftAtomically(next);
    else dev.replaceDraft(next);
  };
  const resetTargets = (ids: readonly string[]) => {
    const next = resetDraftTargets(dev.draft, domainKeys(inspectionsFor(resolvedRoot, ids)));
    if (studio) studio.replaceResolvedDraftAtomically(next);
    else dev.replaceDraft(next);
  };
  const screenIds = previewTargetScope(resolvedRoot, inspection.id, "screen").affectedTargetIds;

  const resetVariation = () => {
    if (!studio?.activeVariationId) return;
    const active = studio.document.variations[studio.activeVariationId];
    if (!active) return;
    studio.replaceDocumentAtomically({
      ...studio.document,
      variations: {
        ...studio.document.variations,
        [active.id]: { ...active, patch: {}, themes: {} },
      },
    });
  };
  const resetTheme = () => {
    if (!studio?.activeVariationId) {
      const next = resetDraftTheme(dev.draft, dev.theme);
      if (studio) studio.replaceResolvedDraftAtomically(next);
      else dev.replaceDraft(next);
      return;
    }
    const active = studio.document.variations[studio.activeVariationId];
    if (!active?.themes?.[dev.theme]) return;
    const themes = { ...active.themes };
    delete themes[dev.theme];
    studio.replaceDocumentAtomically({
      ...studio.document,
      variations: { ...studio.document.variations, [active.id]: { ...active, themes } },
    });
  };
  const resetPersonalDesign = () => {
    const empty = emptyDevModeDraft();
    if (!studio) {
      dev.replaceDraft(empty);
      return;
    }
    studio.replaceDocumentAtomically({
      schemaVersion: 2,
      base: empty,
      variations: {},
      activeVariationId: "",
      globalTargets: {},
      orphanedEdits: {},
      cadPresentation: {},
    });
  };

  const inspectorProps = {
    inspection,
    inspections: affectedInspections,
    affectedTargetIds,
    setDomainProperty,
    resetDomainProperty,
  };
  const textContentIds = [...new Set(affectedInspections.flatMap((item) => item.editTargets.text.contentIds))];
  const iconContentIds = [...new Set(affectedInspections.flatMap((item) => item.editTargets.icon.contentIds))];
  return (
    <section aria-label={contextualInspectorLabel} className="border-b border-line">
      <div className="border-b border-line px-3.5 py-2.5">
        <div className="flex items-baseline justify-between gap-2">
          <div>
            <div className="ui-property-label">{targetDomainsLabel}</div>
            <div className="mt-0.5 text-xs font-semibold text-t1">
              {boxLabel} {inspection.summary.boxes} · {textLabel} {inspection.summary.texts} · {iconLabel} {inspection.summary.icons}
            </div>
          </div>
          <span className="rounded-control bg-raise2 px-1.5 py-0.5 text-2xs text-t2">
            {inspection.summary.behaviors} {behaviorLabel} · {inspection.summary.states} {statesLabel}
          </span>
        </div>
      </div>

      <div role="tablist" aria-label={inspectorDomainsLabel} className="flex flex-wrap gap-1 border-b border-line px-3.5 py-1.5">
        {facets.map((item) => (
          <button key={item.id} type="button" role="tab" aria-selected={facet === item.id} onClick={() => setFacet(item.id)} className={`rounded-control px-2 py-1 text-2xs font-semibold ${facet === item.id ? "bg-raise2 text-t1" : "text-t3 hover:text-t2"}`}>
            {item.label}
          </button>
        ))}
      </div>

      {facet === "content" ? (
        <div className="border-b border-line px-3.5 py-2 font-mono text-2xs text-t3">
          <div aria-label={textDomainPreviewLabel}>{textContentIds.join(" ")}</div>
          <div aria-label={iconDomainPreviewLabel}>{iconContentIds.join(" ")}</div>
        </div>
      ) : null}

      {facet === "layout" ? <><LayoutInspector {...inspectorProps} /><BoxInspector {...inspectorProps} section="layout" /></> : null}
      {facet === "appearance" ? <><BoxInspector {...inspectorProps} section="appearance" /><StatesInspector {...inspectorProps} /></> : null}
      {facet === "content" ? <><TextInspector {...inspectorProps} /><IconInspector {...inspectorProps} /><CadPresentationInspector {...inspectorProps} /></> : null}
      {facet === "advanced" ? <><BehaviorInspector {...inspectorProps} /><AdvancedInspector {...inspectorProps} /></> : null}

      <div className="border-t border-line px-3.5 py-2">
        <div className="ui-property-label mb-1.5">{resetLabel}</div>
        <div className="flex flex-wrap gap-x-3 gap-y-1">
          <button type="button" onClick={() => resetTargets([inspection.id])} className="text-2xs font-semibold text-t2 hover:text-t1">{targetLabel}</button>
          <button type="button" onClick={() => resetTargets(screenIds)} className="text-2xs font-semibold text-t2 hover:text-t1">{screenLabel}</button>
          <button type="button" disabled={!studio?.activeVariationId} onClick={resetVariation} className="text-2xs font-semibold text-t2 hover:text-t1 disabled:opacity-35">{variationLabel}</button>
          <button type="button" onClick={resetTheme} className="text-2xs font-semibold text-t2 hover:text-t1">{themeLabel}</button>
          <button type="button" onClick={resetPersonalDesign} className="text-2xs font-semibold text-err-text hover:text-t1">{fullDesignLabel}</button>
        </div>
      </div>
    </section>
  );
}
