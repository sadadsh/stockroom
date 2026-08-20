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
import { isRootProtectedDesignProperty, type ExactDesignTargetAuthority } from "../../lib/designIdentity";
import { AdvancedInspector } from "./inspectors/AdvancedInspector";
import { BehaviorInspector } from "./inspectors/BehaviorInspector";
import { BoxInspector } from "./inspectors/BoxInspector";
import { IconInspector } from "./inspectors/IconInspector";
import { LayoutInspector } from "./inspectors/LayoutInspector";
import { StatesInspector } from "./inspectors/StatesInspector";
import { TextInspector } from "./inspectors/TextInspector";
import { CadPresentationInspector } from "./inspectors/CadPresentationInspector";
import { Icon } from "../Icon";

type InspectorFacet = "layout" | "appearance" | "content" | "advanced";

function rootElement(root?: Element): Element {
  return root ?? document.documentElement;
}

function inspectionFor(root: Element, target: string | ExactDesignTargetAuthority | null): TargetInspection | null {
  if (!target) return null;
  try {
    return inspectTarget(root, target);
  } catch {
    return null;
  }
}

function domainKeys(inspections: readonly TargetInspection[]) {
  return {
    targetIds: inspections.map((inspection) => inspection.overrideId),
    copyIds: [...new Set(inspections.flatMap((inspection) => inspection.texts.flatMap((text) => text.copyId ? [text.copyId] : [])))],
    iconIds: [...new Set(inspections.flatMap((inspection) => inspection.icons.flatMap((icon) => icon.iconId ? [icon.iconId] : [])))],
  };
}

export function InspectorPanel({ root }: { root?: Element; integrated?: boolean } = {}) {
  const dev = useDevMode();
  const studio = useOptionalDesignStudio();
  const defaultFacet: InspectorFacet = "layout";
  const [openState, setOpenState] = useState<{ targetId: string | null; values: InspectorFacet[] }>(() => ({ targetId: dev.selectedDevId, values: [defaultFacet] }));
  const openFacets = openState.targetId === dev.selectedDevId ? openState.values : [defaultFacet];
  const toggleFacet = (value: InspectorFacet) => setOpenState((current) => {
    const values = current.targetId === dev.selectedDevId ? current.values : [defaultFacet];
    return {
      targetId: dev.selectedDevId,
      values: values.includes(value) ? values.filter((item) => item !== value) : [...values, value],
    };
  });
  const resolvedRoot = rootElement(root);
  const inspection = useMemo(
    () => inspectionFor(resolvedRoot, dev.selectedTarget),
    [dev.selectedTarget, resolvedRoot],
  );
  const contextualInspectorLabel = useText("design-studio.inspector.context", "Contextual Inspector");
  const selectHint = useText("design-studio.inspector.select-hint", "Click an item in Stockroom to edit it.");
  const inspectorDomainsLabel = useText("design-studio.inspector.domains", "Inspector Groups");
  const layoutLabel = useText("design-studio.inspector.domain.layout", "Layout");
  const appearanceLabel = useText("design-studio.inspector.domain.appearance", "Appearance");
  const contentLabel = useText("design-studio.inspector.domain.content", "Content");
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
    () => inspection ? [inspection.overrideId] : [],
    [inspection],
  );
  const affectedInspections = useMemo(
    () => inspection ? [inspection] : [],
    [inspection],
  );

  if (!dev.enabled) return null;
  if (!inspection) return (
    <section aria-label={contextualInspectorLabel} className="grid min-h-48 place-items-center px-6 text-center">
      <p className="text-sm text-t2">{selectHint}</p>
    </section>
  );

  const domainOverrideIds = (domain: EditableTargetDomain) => {
    const ids = new Set<string>();
    for (const item of affectedInspections) {
      const target = item.editTargets[domain];
      if (target.elements.length > 0) ids.add(target.overrideId);
    }
    return [...ids];
  };
  const setDomainProperty = (domain: EditableTargetDomain, property: string, value: string) => {
    if (isRootProtectedDesignProperty(inspection.target, property)) return;
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
    const targets = ids.map((id) => (
      id === inspection.id || id === inspection.overrideId
        ? inspection
        : inspectionFor(resolvedRoot, id)
    )).filter((item): item is TargetInspection => item !== null);
    const next = resetDraftTargets(dev.draft, domainKeys(targets));
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
  const textContentIds = inspection.editTargets.text.contentIds;
  const iconContentIds = inspection.editTargets.icon.contentIds;
  const facetContent = (value: InspectorFacet) => {
    if (value === "layout") return <>
      <LayoutInspector {...inspectorProps} />
      <BoxInspector {...inspectorProps} section="layout" />
    </>;
    if (value === "appearance") return <>
      <BoxInspector {...inspectorProps} section="appearance" />
      <StatesInspector {...inspectorProps} />
    </>;
    if (value === "advanced") return <>
      <div className="px-3.5 py-2 font-mono text-2xs text-t3">
        <div aria-label={textDomainPreviewLabel}>{textContentIds.join(" ")}</div>
        <div aria-label={iconDomainPreviewLabel}>{iconContentIds.join(" ")}</div>
      </div>
      <BehaviorInspector {...inspectorProps} />
      <AdvancedInspector {...inspectorProps} />
    </>;
    return <>
      <TextInspector {...inspectorProps} />
      <IconInspector {...inspectorProps} />
      <CadPresentationInspector {...inspectorProps} />
    </>;
  };
  return (
    <section aria-label={contextualInspectorLabel}>
      <div className="px-3.5 py-2.5">
        <div className="flex items-baseline justify-between gap-2">
          <div>
            <div className="truncate text-sm font-semibold text-t1">{inspection.target.textContent?.replace(/\s+/g, " ").trim().slice(0, 48) || contextualInspectorLabel}</div>
          </div>
        </div>
      </div>

      <div aria-label={inspectorDomainsLabel} className="space-y-1 px-2">
        {facets.map((item) => (
          <section key={item.id} className="rounded-control bg-field/35">
            <button type="button" aria-expanded={openFacets.includes(item.id)} onClick={() => toggleFacet(item.id)} className="flex h-8 w-full items-center justify-between rounded-control px-2.5 text-left text-xs font-semibold text-t2 hover:bg-raise2 hover:text-t1">
              {item.label}
              <Icon
                id={openFacets.includes(item.id) ? "navigation.chevron-down" : "overlay.chevron"}
                className="h-3 w-3 flex-none"
              />
            </button>
            {openFacets.includes(item.id) ? <div>{facetContent(item.id)}</div> : null}
          </section>
        ))}
      </div>

      <div className="mt-2 bg-band/50 px-3.5 py-2">
        <div className="ui-property-label mb-1.5">{resetLabel}</div>
        <div className="flex flex-wrap gap-x-3 gap-y-1">
          <button type="button" onClick={() => resetTargets([inspection.overrideId])} className="text-2xs font-semibold text-t2 hover:text-t1">{targetLabel}</button>
          <button type="button" onClick={() => resetTargets(screenIds)} className="text-2xs font-semibold text-t2 hover:text-t1">{screenLabel}</button>
          <button type="button" disabled={!studio?.activeVariationId} onClick={resetVariation} className="text-2xs font-semibold text-t2 hover:text-t1 disabled:opacity-35">{variationLabel}</button>
          <button type="button" onClick={resetTheme} className="text-2xs font-semibold text-t2 hover:text-t1">{themeLabel}</button>
          <button type="button" onClick={resetPersonalDesign} className="text-2xs font-semibold text-err-text hover:text-t1">{fullDesignLabel}</button>
        </div>
      </div>
    </section>
  );
}
