/**
 * WHAT THE OPENED COMPONENT'S PIECES ARE HANDED, in one typed object.
 *
 * Re-homing composition into a document removed the prop chain that used to carry these values from
 * `ComponentWorkspace` down through three column components. Nothing about WHO OWNS THEM changed,
 * and that is the point of this file: the writes still live in `ComponentWorkspace` exactly as its
 * own header mandates, the refs are still created there, and this is only the delivery mechanism
 * they travel by now that there is no prop chain to travel down. A piece reads; it does not own.
 *
 * The context is grouped by BAND rather than being one flat bag, so a piece's import of it says
 * which part of the workspace it belongs to, and so the standalone column entry points can state
 * plainly which groups they are and are not able to supply.
 *
 * Every type here is imported from the module that already declares it. A second declaration of
 * `SpecFilter` or `WorkspaceActivity` would be a copy that drifts.
 */
import { createContext, useContext, type MutableRefObject } from "react";
import type { ComponentDossier, RepresentationKind } from "../api/dossierTypes";
import type { QualitySegmentKind } from "../components/component-workspace/componentIdentity";
import type { DatasheetTarget } from "../components/component-workspace/datasheetWorkflow";
import type { ManageMenuItem } from "../components/component-workspace/ManageMenu";
import type { SpecFilter } from "../components/component-workspace/specificationRows";
import type { WorkspaceActivity } from "../components/component-workspace/WorkspaceStatusBar";
import type { CadWorkspaceView, RepresentationLayout } from "../lib/uiSession";

export interface WorkspaceHeaderSlice {
  manageItems: ManageMenuItem[];
  /** A quality segment was pressed: take the reader to what it is about. */
  onQualitySegment: (kind: QualitySegmentKind) => void;
  onOpenDatasheet: (target: DatasheetTarget) => void;
  /** No datasheet is on record: open the surface that can go and find one. */
  onFindDatasheet: () => void;
}

export interface WorkspaceCadSlice {
  view: CadWorkspaceView;
  onView: (view: CadWorkspaceView) => void;
  /** `all` expands the three; a kind expands that one and compacts the other two. */
  layout: RepresentationLayout;
  onLayout: (layout: RepresentationLayout) => void;
  onOpenFullPreview: (kind: RepresentationKind) => void;
  /** Where each module's element is kept, so the quality summary can scroll one into view. */
  assetRefs: MutableRefObject<Partial<Record<RepresentationKind, HTMLElement | null>>>;
}

export interface WorkspaceSpecificationsSlice {
  /**
   * LIFTED, and still lifted.
   *
   * The filter lives in `ComponentWorkspace` because the identity header's quality summary and the
   * Manage menu both set it from outside the column. The SEARCH text is not here for the same
   * reason inverted: nothing outside the column has ever set it, so it stays inside the column.
   */
  filter: SpecFilter;
  onFilter: (filter: SpecFilter) => void;
  scrollRef: MutableRefObject<HTMLDivElement | null>;
  /** The pinout is genuinely tabular and opens on its own surface. */
  onViewPinout: () => void;
}

export interface WorkspaceSourcingSlice {
  onViewOffers: () => void;
  onViewProvenance: () => void;
  /** Open a stored or referenced document in the viewer, addressed by its derived id. */
  onOpenDocument: (id: string) => void;
  onRefresh: () => void;
  refreshing: boolean;
  scrollRef: MutableRefObject<HTMLDivElement | null>;
}

export interface WorkspaceRenderContext {
  componentId: string;
  dossier: ComponentDossier;
  header: WorkspaceHeaderSlice;
  cad: WorkspaceCadSlice;
  specifications: WorkspaceSpecificationsSlice;
  sourcing: WorkspaceSourcingSlice;
  status: { activity: WorkspaceActivity };
}

/**
 * `null` until a workspace provides one.
 *
 * A piece that finds no context returns nothing rather than throwing, for the same reason the
 * renderer does not throw on an unknown piece: a layout being edited can put a piece somewhere its
 * data does not reach, and warning about that is the validator's job in Phase 3, not a crash.
 */
const WorkspaceRenderContextValue = createContext<WorkspaceRenderContext | null>(null);

export function WorkspaceRenderProvider({
  value,
  children,
}: {
  value: WorkspaceRenderContext;
  children: React.ReactNode;
}) {
  return (
    <WorkspaceRenderContextValue.Provider value={value}>
      {children}
    </WorkspaceRenderContextValue.Provider>
  );
}

export function useWorkspaceRender(): WorkspaceRenderContext | null {
  return useContext(WorkspaceRenderContextValue);
}
