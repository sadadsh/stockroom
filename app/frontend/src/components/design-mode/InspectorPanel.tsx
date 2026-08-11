import { useMemo, useState } from "react";
import type { DesignScope } from "../../design-studio/document";
import {
  inspectTarget,
  previewTargetScope,
  type ScopePreview,
  type TargetInspection,
} from "../../design-studio/targetDomains";
import { useOptionalDesignStudio } from "../../design-studio/DesignStudioProvider";
import { useDevMode } from "../../lib/devMode";
import { useCopyFormatter, useText } from "../../lib/copy";
import {
  emptyDevModeDraft,
  resetDraftTargets,
  resetDraftTheme,
} from "../../lib/devModeDraft";
import { AdvancedInspector } from "./inspectors/AdvancedInspector";
import { BehaviorInspector } from "./inspectors/BehaviorInspector";
import { BoxInspector } from "./inspectors/BoxInspector";
import { IconInspector } from "./inspectors/IconInspector";
import { LayoutInspector } from "./inspectors/LayoutInspector";
import { StatesInspector } from "./inspectors/StatesInspector";
import { TextInspector } from "./inspectors/TextInspector";

type InspectorFacet = "box" | "text" | "icon" | "layout" | "behavior" | "states" | "advanced";

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

export function InspectorPanel({ root, integrated = false }: { root?: Element; integrated?: boolean } = {}) {
  const dev = useDevMode();
  const studio = useOptionalDesignStudio();
  const defaultFacet: InspectorFacet = integrated ? "advanced" : "box";
  const [facetState, setFacetState] = useState<{ targetId: string | null; value: InspectorFacet }>(() => ({ targetId: dev.selectedDevId, value: defaultFacet }));
  const [scopeState, setScopeState] = useState<{ targetId: string | null; value: DesignScope }>(() => ({ targetId: dev.selectedDevId, value: "instance" }));
  const facet = facetState.targetId === dev.selectedDevId ? facetState.value : defaultFacet;
  const scope = scopeState.targetId === dev.selectedDevId ? scopeState.value : "instance";
  const setFacet = (value: InspectorFacet) => setFacetState({ targetId: dev.selectedDevId, value });
  const setScope = (value: DesignScope) => setScopeState({ targetId: dev.selectedDevId, value });
  const resolvedRoot = rootElement(root);
  const inspection = useMemo(
    () => inspectionFor(resolvedRoot, dev.selectedDevId),
    [dev.selectedDevId, resolvedRoot],
  );
  const contextualInspectorLabel = useText("design-studio.inspector.context", "Contextual Inspector");
  const targetDomainsLabel = useText("design-studio.inspector.target-domains", "Target Domains");
  const editingScopeLabel = useText("design-studio.inspector.editing-scope", "Editing Scope");
  const inspectorDomainsLabel = useText("design-studio.inspector.domains", "Inspector Domains");
  const boxLabel = useText("design-studio.inspector.domain.box", "Box");
  const textLabel = useText("design-studio.inspector.domain.text", "Text");
  const iconLabel = useText("design-studio.inspector.domain.icon", "Icon");
  const layoutLabel = useText("design-studio.inspector.domain.layout", "Arrangement");
  const behaviorLabel = useText("design-studio.inspector.domain.behavior", "Behavior");
  const statesLabel = useText("design-studio.inspector.domain.states", "States");
  const advancedLabel = useText("design-studio.inspector.domain.advanced", "Advanced");
  const instanceLabel = useText("design-studio.inspector.scope.instance", "Instance");
  const roleLabel = useText("design-studio.inspector.scope.role", "Role");
  const screenLabel = useText("design-studio.inspector.scope.screen", "Screen");
  const globalLabel = useText("design-studio.inspector.scope.global", "Global");
  const resetLabel = useText("design-studio.inspector.reset", "Reset");
  const targetLabel = useText("design-studio.inspector.reset.target", "Target");
  const variationLabel = useText("design-studio.inspector.reset.variation", "Variation");
  const themeLabel = useText("design-studio.inspector.reset.theme", "Theme");
  const fullDesignLabel = useText("design-studio.inspector.reset.full-design", "Full Personal Design");
  const scopeAria = useCopyFormatter("design-studio.inspector.scope.aria", "{scope} Scope");
  const scopeSummary = useCopyFormatter("design-studio.inspector.scope.summary", "{scope} · {count} {targets}");
  const singularTarget = useText("design-studio.inspector.scope.singular-target", "Target");
  const pluralTargets = useText("design-studio.inspector.scope.plural-targets", "Targets");
  const integratedDomain = useCopyFormatter("design-studio.inspector.domain.integrated", "{domain} Domain");
  const facets: readonly { id: InspectorFacet; label: string }[] = [
    { id: "box", label: boxLabel }, { id: "text", label: textLabel },
    { id: "icon", label: iconLabel }, { id: "layout", label: layoutLabel },
    { id: "behavior", label: behaviorLabel }, { id: "states", label: statesLabel },
    { id: "advanced", label: advancedLabel },
  ];
  const scopes: readonly { id: DesignScope; label: string }[] = [
    { id: "instance", label: instanceLabel }, { id: "role", label: roleLabel },
    { id: "screen", label: screenLabel }, { id: "global", label: globalLabel },
  ];

  const scopePreview = useMemo<ScopePreview>(
    () => inspection
      ? previewTargetScope(resolvedRoot, inspection.id, scope)
      : { scope, affectedTargetIds: [] },
    [inspection, resolvedRoot, scope],
  );
  const affectedTargetIds = scopePreview.affectedTargetIds;

  if (!dev.enabled || !inspection) return null;

  const chooseScope = (next: DesignScope) => {
    const preview = previewTargetScope(resolvedRoot, inspection.id, next);
    setScope(next);
    if (studio) {
      const targetScopes = { ...studio.document.targetScopes };
      for (const id of preview.affectedTargetIds) targetScopes[id] = next;
      studio.replaceDocument({ ...studio.document, targetScopes });
    }
  };
  const setElementProperty = (property: string, value: string) => {
    affectedTargetIds.forEach((id) => dev.setElementProp(id, property, value));
  };
  const resetElementProperty = (property: string) => {
    affectedTargetIds.forEach((id) => dev.resetElementProp(id, property));
  };
  const inspectionsFor = (ids: readonly string[]) => ids
    .map((id) => inspectionFor(resolvedRoot, id))
    .filter((item): item is TargetInspection => item !== null);
  const resetTargets = (ids: readonly string[]) => {
    dev.replaceDraft(resetDraftTargets(dev.draft, domainKeys(inspectionsFor(ids))));
  };
  const screenIds = previewTargetScope(resolvedRoot, inspection.id, "screen").affectedTargetIds;

  const resetVariation = () => {
    if (!studio?.activeVariationId) return;
    const active = studio.document.variations[studio.activeVariationId];
    if (!active) return;
    studio.replaceDocument({
      ...studio.document,
      variations: {
        ...studio.document.variations,
        [active.id]: { ...active, patch: {}, themes: {} },
      },
    });
  };
  const resetTheme = () => {
    if (!studio?.activeVariationId) {
      dev.replaceDraft(resetDraftTheme(dev.draft, dev.theme));
      return;
    }
    const active = studio.document.variations[studio.activeVariationId];
    if (!active?.themes?.[dev.theme]) return;
    const themes = { ...active.themes };
    delete themes[dev.theme];
    studio.replaceDocument({
      ...studio.document,
      variations: { ...studio.document.variations, [active.id]: { ...active, themes } },
    });
  };
  const resetPersonalDesign = () => {
    const empty = emptyDevModeDraft();
    dev.replaceDraft(empty);
    studio?.replaceDocument({
      schemaVersion: 1,
      base: empty,
      variations: {},
      activeVariationId: "",
      targetScopes: {},
    });
  };

  const inspectorProps = { inspection, affectedTargetIds, setElementProperty, resetElementProperty };
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

      <div className="border-b border-line px-3.5 py-2">
        <div className="flex flex-wrap gap-1" aria-label={editingScopeLabel}>
          {scopes.map((item) => (
            <button
              key={item.id}
              type="button"
              aria-label={scopeAria({ scope: item.label })}
              aria-pressed={scope === item.id}
              disabled={item.id === "role" && inspection.role === null}
              onClick={() => chooseScope(item.id)}
              className={`rounded-control border px-2 py-1 text-2xs font-semibold ${scope === item.id ? "border-transparent bg-acc text-acc-on" : "border-line text-t2 hover:text-t1"} disabled:opacity-35`}
            >
              {item.label}
            </button>
          ))}
        </div>
        <div className="mt-2 rounded-control border border-line bg-field p-2" aria-live="polite">
          <div className="text-2xs font-semibold text-t2">
            {scopeSummary({ scope: scopes.find((item) => item.id === scope)?.label ?? scope, count: affectedTargetIds.length, targets: affectedTargetIds.length === 1 ? singularTarget : pluralTargets })}
          </div>
          {scope !== "instance" ? (
            <ul className="mt-1 max-h-20 overflow-y-auto font-mono text-2xs text-t3">
              {affectedTargetIds.map((id) => <li key={id}>{id}</li>)}
            </ul>
          ) : null}
        </div>
      </div>

      <div role="tablist" aria-label={inspectorDomainsLabel} className="flex flex-wrap gap-1 border-b border-line px-3.5 py-1.5">
        {facets.map((item) => (
          <button key={item.id} type="button" role="tab" aria-selected={facet === item.id} onClick={() => setFacet(item.id)} className={`rounded-control px-2 py-1 text-2xs font-semibold ${facet === item.id ? "bg-raise2 text-t1" : "text-t3 hover:text-t2"}`}>
            {integrated && (item.id === "box" || item.id === "icon" || item.id === "behavior")
              ? integratedDomain({ domain: item.label })
              : item.label}
          </button>
        ))}
      </div>

      {facet === "box" ? <BoxInspector {...inspectorProps} /> : null}
      {facet === "text" ? <TextInspector {...inspectorProps} /> : null}
      {facet === "icon" ? <IconInspector {...inspectorProps} /> : null}
      {facet === "layout" ? <LayoutInspector {...inspectorProps} /> : null}
      {facet === "behavior" ? <BehaviorInspector {...inspectorProps} /> : null}
      {facet === "states" ? <StatesInspector {...inspectorProps} /> : null}
      {facet === "advanced" ? <AdvancedInspector {...inspectorProps} /> : null}

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
