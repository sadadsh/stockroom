/**
 * The Specifications column, mounted on its own.
 *
 * The column itself - its frame, its toolbar, its seven pieces and the one derivation they share -
 * is `SpecificationsPieces.tsx`, and the ORDER those pieces appear in is the layout document's
 * (plan Phase 1). What is left here is the entry point: the shape a caller who wants the column and
 * nothing else can mount it through.
 *
 * WHY THE INERT SLICES BELOW ARE HONEST. The workspace context is one object with a slice per band,
 * and this caller can only supply the specifications slice - it has no header actions to offer, no
 * CAD focus state to hold, no sourcing refresh to run. The other slices are filled with values that
 * do nothing, and that is safe for exactly one reason, which is worth stating rather than assuming:
 * the region rendered here contains only specification pieces, so no piece that would read them is
 * ever mounted. If a future edit moved a sourcing section into this column, that piece would draw
 * with dead callbacks - which is why the workspace itself always supplies the whole object, and why
 * this entry point exists for the column and not for arbitrary regions.
 */
import { useMemo, type MutableRefObject } from "react";
import type { ComponentDossier, RepresentationKind } from "../../api/dossierTypes";
import { WorkspaceRegionView } from "../../layout/workspaceBindings";
import { WORKSPACE_REGION } from "../../layout/workspacePieces";
import type { WorkspaceRenderContext } from "../../layout/workspaceRenderContext";
import type { SpecFilter } from "./specificationRows";

const NO_ASSET_REFS: MutableRefObject<Partial<Record<RepresentationKind, HTMLElement | null>>> = {
  current: {},
};

const NO_SCROLLER: MutableRefObject<HTMLDivElement | null> = { current: null };

function noop(): void {
  /* A slice this entry point cannot supply. See the file header. */
}

export function SpecificationsColumn({
  componentId,
  dossier,
  filter,
  onFilter,
  scrollRef,
  onViewPinout,
}: {
  componentId: string;
  dossier: ComponentDossier;
  filter: SpecFilter;
  onFilter: (filter: SpecFilter) => void;
  scrollRef: MutableRefObject<HTMLDivElement | null>;
  /** The pinout is genuinely tabular and opens on its own surface. */
  onViewPinout: () => void;
}) {
  const context = useMemo<WorkspaceRenderContext>(
    () => ({
      componentId,
      dossier,
      header: {
        manageItems: [],
        onQualitySegment: noop,
        onOpenDatasheet: noop,
        onFindDatasheet: noop,
      },
      cad: {
        layout: "all",
        onLayout: noop,
        onCompareSources: noop,
        onOpenFullPreview: noop,
        assetRefs: NO_ASSET_REFS,
      },
      specifications: { filter, onFilter, scrollRef, onViewPinout },
      sourcing: {
        onViewOffers: noop,
        onViewProvenance: noop,
        onOpenDocument: noop,
        onRefresh: noop,
        refreshing: false,
        scrollRef: NO_SCROLLER,
      },
      status: { activity: "idle" },
    }),
    [componentId, dossier, filter, onFilter, onViewPinout, scrollRef],
  );
  return (
    <WorkspaceRegionView
      regionId={WORKSPACE_REGION.specificationsColumn}
      context={context}
    />
  );
}
