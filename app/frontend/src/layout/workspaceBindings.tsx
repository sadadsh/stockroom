/**
 * PIECE ID -> WHAT DRAWS IT, and REGION ID -> WHAT WRAPS IT. The workspace's half of the renderer.
 *
 * `workspacePieces.ts` is the CATALOGUE: what a piece is called, what it reads, how small it can be.
 * It deliberately holds no React, so the commit pipeline and every test can read it without mounting
 * anything. This is the other half - the table that says which component actually appears when the
 * document places `workspace.sourcing-documents` - and it is a separate module for exactly that
 * reason.
 *
 * WHAT IS NOT HERE. No new sections. Every entry below is a component that already shipped, drawing
 * the same elements it drew when the arrangement was hardcoded; the only thing that changed is who
 * decides the ORDER and the CONDITIONS, which is now the document. Phase 1's whole claim is that the
 * DOM does not change, and `ComponentWorkspace.domParity.test.tsx` is where that is proved.
 *
 * WHY REGIONS HAVE CHROME AT ALL. A region is a container, and a container in this arrangement is
 * not a neutral `<div>`: a column is a bordered `<section>` that clips, a column body is the one
 * scroller the column owns, the header band is a `<header>` with its own padding. Those elements
 * exist today and must keep existing, so each of them is a chrome entry rather than something the
 * renderer invents from a layout mode. Regions with no entry - the status band - wrap in nothing,
 * which is also what they do today.
 *
 * WHY SOME CHROME OWNS STATE. Three chrome entries open a `LayoutRuntimeScope` and answer conditions
 * for their own subtree, because the state those conditions depend on belongs to the column and
 * moving it up would be a real behaviour change:
 *
 *   the identity header derives its four lines ONCE, because each line reads the ones above it;
 *   the specifications column owns the search text and the filtered result;
 *   the sourcing column owns the reveal preference, read once on mount.
 *
 * Everything else the document asks is answered at workspace level in `WorkspaceDocumentView`,
 * because the column BAND needs the sourcing fill to pick its widths and the sourcing column is
 * inside the band, not around it.
 */
import { createContext, useContext, useMemo, type ReactNode } from "react";
import type { ComponentDossier } from "../api/dossierTypes";
import {
  CadAssetModulePart,
  CadBodyChrome,
  CadColumnChrome,
  CadPreferredSourcePart,
  CadTitleStripPart,
} from "../components/component-workspace/CadAssetsColumn";
import {
  HeaderActionsPart,
  HeaderBandChrome,
  HeaderClassificationPart,
  HeaderDescriptionPart,
  HeaderIdentityPart,
  HeaderKeyFactsPart,
  HeaderLinesChrome,
  HeaderQualitySummaryPart,
} from "../components/component-workspace/ComponentHeader";
import {
  SourcingBodyChrome,
  SourcingColumnChrome,
  SourcingDocumentsPart,
  SourcingEmptySectionsPart,
  SourcingLifecyclePart,
  SourcingOffersPart,
  SourcingPricingPart,
  SourcingProvenancePart,
  SourcingRelatedPart,
  SourcingTitleStripPart,
} from "../components/component-workspace/SourcingColumn";
import {
  SpecificationsAnchorsPart,
  SpecificationsBodyChrome,
  SpecificationsColumnChrome,
  SpecificationsEmptyPart,
  SpecificationsFiltersPart,
  SpecificationsGroupPart,
  SpecificationsKeyBlockPart,
  SpecificationsPinoutPart,
  SpecificationsSearchPart,
  SpecificationsTitleStripPart,
  SpecificationsToolbarChrome,
} from "../components/component-workspace/SpecificationsPieces";
import { WorkspaceColumnBand } from "../components/component-workspace/WorkspaceColumns";
import { WorkspaceStatusBarPart } from "../components/component-workspace/WorkspaceStatusBar";
import {
  COLLAPSIBLE_SOURCING_SECTIONS,
  emptySourcingSections,
  sourcingIsSparse,
  sourcingSectionFill,
} from "../components/component-workspace/sourcingSections";
import {
  ArrangePlacementChrome,
  ArrangeSurfaceProvider,
} from "../components/design-mode/ArrangeSurface";
import { componentDevId } from "../lib/componentDevIds";
import { useDevMode } from "../lib/devMode";
import { sourcingFillCondition, WORKSPACE_CONDITION } from "./defaultWorkspaceLayout";
import { findRegion, type LayoutDocument } from "./document";
import { resolveWorkspaceLayout } from "./resolveWorkspaceLayout";
import {
  LayoutDocumentView,
  LayoutPlacementChromeProvider,
  LayoutRegionScope,
  LayoutRuntimeScope,
  useLayoutCondition,
  type LayoutBindings,
  type RegionChromeProps,
} from "./LayoutRenderer";
import {
  WorkspaceRenderProvider,
  useWorkspaceRender,
  type WorkspaceRenderContext,
} from "./workspaceRenderContext";
import { WORKSPACE_REGION } from "./workspacePieces";

/**
 * What opens OVER the workspace: the shell dialogs, the modals, the datasheet viewer.
 *
 * They are not placements - plan Phase 7 is where the overlay surfaces join the layout system - but
 * they are siblings of the three bands inside the workspace's own root element, so the root chrome
 * has to be handed them rather than the workspace rendering them somewhere else.
 */
const WorkspaceOverlaysContext = createContext<ReactNode>(null);

/**
 * The workspace root: the frame that never scrolls, and the open component's own instance element.
 *
 * Two nested elements rather than one, and the inner one is not a region: `component-browser
 * .component[<id>]` names THIS component's body, which is an identity, not a container anything
 * could be placed beside. Making it a region would offer a slot next to the whole workspace.
 */
function WorkspaceRootChrome({ children }: RegionChromeProps) {
  const workspace = useWorkspaceRender();
  const overlays = useContext(WorkspaceOverlaysContext);
  if (!workspace) return null;
  return (
    <div
      data-dev-id="component-browser.root"
      className="flex h-full min-h-0 flex-col overflow-hidden"
    >
      <div
        data-dev-id={componentDevId(workspace.componentId)}
        className="flex min-h-0 flex-1 flex-col overflow-hidden"
      >
        {children}
      </div>
      {overlays}
    </div>
  );
}

/**
 * The three-column band.
 *
 * The one condition it needs is the document's own `sparseSourcing`, asked of the runtime rather
 * than recomputed: the widths and the sections have to agree about whether this component has
 * anything to source, and two evaluations of the same rule is how they stop agreeing.
 */
function ColumnBandChrome({ region, slots }: RegionChromeProps) {
  const sparseSourcing = useLayoutCondition(WORKSPACE_CONDITION.sparseSourcing);
  return (
    <WorkspaceColumnBand region={region} slots={slots} sparseSourcing={sparseSourcing} />
  );
}

/**
 * The workspace's bindings: twenty-six pieces and eleven pieces of region chrome.
 *
 * Module-private on purpose. Callers mount a DOCUMENT or a REGION through the two entry points at
 * the bottom of this file; handing the table out would let somebody walk half a document with half
 * a binding set, which is a way to render a workspace that the coverage gate has never seen.
 */
const WORKSPACE_LAYOUT_BINDINGS: LayoutBindings = {
  pieces: {
    "workspace.header-identity": HeaderIdentityPart,
    "workspace.header-description": HeaderDescriptionPart,
    "workspace.header-classification": HeaderClassificationPart,
    "workspace.header-key-facts": HeaderKeyFactsPart,
    "workspace.header-quality-summary": HeaderQualitySummaryPart,
    "workspace.header-actions": HeaderActionsPart,

    "workspace.cad-title-strip": CadTitleStripPart,
    "workspace.cad-preferred-source": CadPreferredSourcePart,
    "workspace.cad-asset-module": CadAssetModulePart,

    "workspace.specifications-title-strip": SpecificationsTitleStripPart,
    "workspace.specifications-search": SpecificationsSearchPart,
    "workspace.specifications-filters": SpecificationsFiltersPart,
    "workspace.specifications-anchors": SpecificationsAnchorsPart,
    "workspace.specifications-key-block": SpecificationsKeyBlockPart,
    "workspace.specifications-group": SpecificationsGroupPart,
    "workspace.specifications-empty": SpecificationsEmptyPart,
    "workspace.specifications-pinout": SpecificationsPinoutPart,

    "workspace.sourcing-title-strip": SourcingTitleStripPart,
    "workspace.sourcing-lifecycle": SourcingLifecyclePart,
    "workspace.sourcing-offers": SourcingOffersPart,
    "workspace.sourcing-pricing": SourcingPricingPart,
    "workspace.sourcing-documents": SourcingDocumentsPart,
    "workspace.sourcing-related": SourcingRelatedPart,
    "workspace.sourcing-provenance": SourcingProvenancePart,
    "workspace.sourcing-empty-sections": SourcingEmptySectionsPart,

    "workspace.status-bar": WorkspaceStatusBarPart,
  },
  chrome: {
    [WORKSPACE_REGION.root]: WorkspaceRootChrome,
    [WORKSPACE_REGION.headerBand]: HeaderBandChrome,
    [WORKSPACE_REGION.headerLines]: HeaderLinesChrome,
    [WORKSPACE_REGION.columnBand]: ColumnBandChrome,
    [WORKSPACE_REGION.cadColumn]: CadColumnChrome,
    [WORKSPACE_REGION.cadBody]: CadBodyChrome,
    [WORKSPACE_REGION.specificationsColumn]: SpecificationsColumnChrome,
    [WORKSPACE_REGION.specificationsToolbar]: SpecificationsToolbarChrome,
    [WORKSPACE_REGION.specificationsBody]: SpecificationsBodyChrome,
    [WORKSPACE_REGION.sourcingColumn]: SourcingColumnChrome,
    [WORKSPACE_REGION.sourcingBody]: SourcingBodyChrome,
  },
};

/**
 * The conditions the WHOLE workspace answers, as opposed to the ones a column answers for itself.
 *
 * All of them are the sourcing fill and what follows from it, and they are here rather than in the
 * sourcing column for one reason: the column BAND reads `sparseSourcing` to pick its widths, and the
 * band is outside the column. Developer mode is part of the input exactly as it is in the source -
 * it always fills Technical Diagnostics, so a component that is sparse for everybody else is not
 * sparse here, and the column must not be narrowed.
 */
function useWorkspaceConditions(dossier: ComponentDossier): Record<string, boolean> {
  const { enabled: developerMode } = useDevMode();
  return useMemo(() => {
    const fill = sourcingSectionFill(dossier, developerMode);
    const conditions: Record<string, boolean> = {
      [WORKSPACE_CONDITION.sparseSourcing]: sourcingIsSparse(fill),
      [WORKSPACE_CONDITION.sourcingHasEmptySections]: emptySourcingSections(fill).length > 0,
    };
    for (const id of COLLAPSIBLE_SOURCING_SECTIONS) {
      conditions[sourcingFillCondition(id)] = fill[id];
    }
    return conditions;
  }, [dossier, developerMode]);
}

/**
 * WHICH ARRANGEMENT THIS WORKSPACE DRAWS - the one place the question is asked.
 *
 * Design Mode's working draft, else the committed override, else the shipped default; the order and
 * the reasons for it are in `resolveWorkspaceLayout.ts`, and the resolution is a pure function so the
 * only thing this hook adds is reading the draft out of the provider. With no draft and a `null`
 * committed override - as the app ships - it returns `DEFAULT_WORKSPACE_LAYOUT` by reference, which is
 * why `ComponentWorkspace.domParity.test.tsx`'s digests do not move.
 *
 * The RENDERER is untouched by this: `LayoutRenderer` is handed a document and never learns that
 * overrides exist, which is what keeps it able to draw the shell (Phase 6) and every route after it.
 */
function useWorkspaceLayout(): LayoutDocument {
  const { layoutDraft } = useDevMode();
  return resolveWorkspaceLayout(layoutDraft);
}

/**
 * The workspace, drawn with whatever editing chrome Design Mode currently asks for.
 *
 * TWO WRAPPERS AND NEITHER DRAWS AN ELEMENT. `ArrangeSurfaceProvider` carries the arrangement, the
 * one write path into the draft, and the drag / menu state; `LayoutPlacementChromeProvider` hands
 * the renderer a component to wrap each placement in. With arrange OFF the provider's value is
 * `null` and the chrome is `null`, so the renderer takes the branch it always took and the rendered
 * DOM is byte-identical - which is what `ComponentWorkspace.domParity.test.tsx` holds. Both wrappers
 * are here rather than in `LayoutRenderer`, because the renderer has to keep drawing the shell and
 * every remaining route (plan Phase 6 and 7) without learning that an editor exists.
 */
function ArrangeableWorkspace({
  layout,
  children,
}: {
  layout: LayoutDocument;
  children: ReactNode;
}) {
  const { editMode, setLayoutDraft } = useDevMode();
  return (
    <ArrangeSurfaceProvider active={editMode} layout={layout} onLayout={setLayoutDraft}>
      <LayoutPlacementChromeProvider chrome={editMode ? ArrangePlacementChrome : null}>
        {children}
      </LayoutPlacementChromeProvider>
    </ArrangeSurfaceProvider>
  );
}

/**
 * The opened component, drawn from the layout document in force.
 *
 * `ComponentWorkspace` still owns every write and every piece of workspace state; this takes the
 * object it assembles and walks the document with it.
 */
export function WorkspaceDocumentView({
  context,
  overlays,
  bodyOverride,
}: {
  context: WorkspaceRenderContext;
  overlays?: ReactNode;
  bodyOverride?: ReactNode;
}) {
  const conditions = useWorkspaceConditions(context.dossier);
  const layout = useWorkspaceLayout();
  return (
    <WorkspaceRenderProvider value={context}>
      <WorkspaceOverlaysContext.Provider value={overlays ?? null}>
        <LayoutRuntimeScope conditions={conditions}>
          <ArrangeableWorkspace layout={layout}>
            {bodyOverride ? (
              <div data-dev-id="component-browser.root" className="flex h-full min-h-0 flex-col overflow-hidden">
                <div data-dev-id={componentDevId(context.componentId)} className="flex min-h-0 flex-1 flex-col overflow-hidden">
                  {findRegion(layout, WORKSPACE_REGION.headerBand) ? (
                    <LayoutRegionScope region={findRegion(layout, WORKSPACE_REGION.headerBand)!} bindings={WORKSPACE_LAYOUT_BINDINGS} />
                  ) : null}
                  {bodyOverride}
                  {findRegion(layout, WORKSPACE_REGION.statusBand) ? (
                    <LayoutRegionScope region={findRegion(layout, WORKSPACE_REGION.statusBand)!} bindings={WORKSPACE_LAYOUT_BINDINGS} />
                  ) : null}
                </div>
                {overlays}
              </div>
            ) : (
              <LayoutDocumentView document={layout} bindings={WORKSPACE_LAYOUT_BINDINGS} />
            )}
          </ArrangeableWorkspace>
        </LayoutRuntimeScope>
      </WorkspaceOverlaysContext.Provider>
    </WorkspaceRenderProvider>
  );
}

/**
 * One region of the workspace document, on its own.
 *
 * What a column entry point mounts. The workspace-level conditions are supplied here too, so a
 * column rendered by itself answers the same questions it answers inside the band.
 */
export function WorkspaceRegionView({
  regionId,
  context,
}: {
  regionId: string;
  context: WorkspaceRenderContext;
}) {
  const conditions = useWorkspaceConditions(context.dossier);
  // The same document the whole workspace draws, so a column mounted on its own is the column the
  // arrangement in force describes rather than the one that shipped.
  const layout = useWorkspaceLayout();
  const region = findRegion(layout, regionId);
  if (!region) return null;
  return (
    <WorkspaceRenderProvider value={context}>
      <LayoutRuntimeScope conditions={conditions}>
        <ArrangeableWorkspace layout={layout}>
          <LayoutRegionScope region={region} bindings={WORKSPACE_LAYOUT_BINDINGS} />
        </ArrangeableWorkspace>
      </LayoutRuntimeScope>
    </WorkspaceRenderProvider>
  );
}
