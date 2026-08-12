/**
 * One opened component, whole.
 *
 * A fixed-height frame with three bands that never move: the identity header, the three-column
 * body (CAD Assets, Specifications, Sourcing and Resources), and the component's own status bar.
 * The columns are side by side at every supported desktop size and each one owns its own
 * scrollbar, so reading a long specification list never pushes the symbol off the screen and
 * nothing here ever grows a page scrollbar.
 *
 * There are no per-component tabs and no information tabs. The four-tab structure this replaces
 * made a person choose which third of the answer to look at, when the whole point of opening a
 * component is to see the drawing, the numbers and the price together.
 *
 * The WRITES live here rather than in the columns: identity edits, the category move, the pinout
 * persist, applying an alternate, the sourcing refresh and the delete. One owner for the mutations
 * means one place decides what a failure says and what a success invalidates, and the columns stay
 * renderers. The windows those writes open live in `WorkspaceSurfaces`.
 *
 * THE ARRANGEMENT IS A DOCUMENT NOW (plan Phase 1). The three bands, the three columns and every
 * section in them are no longer composed here: `DEFAULT_WORKSPACE_LAYOUT` says what goes where and
 * `WorkspaceDocumentView` walks it. Nothing about ownership moved with them. This module still holds
 * the mutations, the refs, the surface state and the lifted specification filter, and hands them to
 * the renderer as ONE typed object - which is the same prop drilling it always did, with the chain
 * replaced by a context because there is no longer a fixed chain to drill down. The loading, failed
 * and empty states stay here too: they REPLACE the workspace rather than sitting in it, so they are
 * not placements and the document does not model them.
 */
import { useCallback, useMemo, useRef, useState, type ReactNode } from "react";
import {
  useDeletePart,
  useEditField,
  useFacetsQuery,
  useMoveCategory,
  usePartDetailQuery,
  usePartDossierQuery,
  usePartShellQuery,
  useRefreshSourcing,
  useRevealPartFiles,
} from "../../api/queries";
import { ApiError } from "../../api/client";
import type { RepresentationKind } from "../../api/dossierTypes";
import { WorkspaceDocumentView } from "../../layout/workspaceBindings";
import type { WorkspaceRenderContext } from "../../layout/workspaceRenderContext";
import { Text, useText } from "../../lib/copy";
import { useToast } from "../../lib/toast";
import {
  componentView,
  setComponentViewInSession,
  updateUiSession,
  useUiSession,
  type RepresentationLayout,
} from "../../lib/uiSession";
import { EnrichPanel } from "../EnrichPanel";
import type { PreviewKind } from "../PreviewModal";
import { ErrorState, LoadingState } from "../primitives";
import { WorkspaceShellDialogs, type ShellDialog } from "./ShellActions";
import { WorkspaceSurfaces, type WorkspaceSurface } from "./WorkspaceSurfaces";
import { previewKindFor } from "./cadAssetSet";
import { manageMenuItems, shellManageItems } from "./manageActions";
import { cadFocusKind, type QualitySegmentKind } from "./componentIdentity";
import { openKindFor, type DatasheetTarget } from "./datasheetWorkflow";
import type { SpecFilter } from "./specificationRows";

export function ComponentWorkspace({
  componentId,
  onDeleted,
  initialSurface,
  initialPreview,
  initialConfirmDelete = false,
}: {
  componentId: string;
  /** The component was removed. The page owns what happens to the selection afterwards. */
  onDeleted?: (id: string) => void;
  initialSurface?: WorkspaceSurface;
  initialPreview?: PreviewKind;
  initialConfirmDelete?: boolean;
}) {
  const session = useUiSession();
  const view = componentView(session, componentId);
  const query = usePartDossierQuery(componentId);
  const facets = useFacetsQuery();
  const editField = useEditField();
  const moveCategory = useMoveCategory();
  const deletePart = useDeletePart();
  const refresh = useRefreshSourcing(componentId);
  // What this host can do OUTSIDE the application for this component. Read once per opened
  // component; nothing here changes while a menu is open.
  const shell = usePartShellQuery(componentId);
  const revealFiles = useRevealPartFiles();
  const { toast } = useToast();
  const [preview, setPreview] = useState<PreviewKind | null>(initialPreview ?? null);
  const [surface, setSurface] = useState<WorkspaceSurface | null>(initialSurface ?? null);
  const [datasheet, setDatasheet] = useState<DatasheetTarget | null>(null);
  const [specFilter, setSpecFilter] = useState<SpecFilter>("all");
  const [confirmDelete, setConfirmDelete] = useState(initialConfirmDelete);
  const [shellDialog, setShellDialog] = useState<ShellDialog>(null);
  const specScrollRef = useRef<HTMLDivElement | null>(null);
  const sourcingScrollRef = useRef<HTMLDivElement | null>(null);
  const assetRefs = useRef<Partial<Record<RepresentationKind, HTMLElement | null>>>({});
  // The canonical record, fetched only while identity editing is open.
  const identityDetail = usePartDetailQuery(
    surface === "identity" || surface === "classification" ? componentId : null,
  );
  const savedLabel = useText("component-browser.saved", "Saved");
  const saveFailed = useText("component-browser.save-failed", "Could not save");
  const movedLabel = useText("component-browser.moved", "Moved");
  const moveFailed = useText("component-browser.move-failed", "Could not move");
  const pinoutSaved = useText("component-browser.pinout-saved", "Pinout saved");
  const pinoutFailed = useText("component-browser.pinout-failed", "Could not save the pinout");
  const deleteFailed = useText("component-browser.delete-failed", "Could not delete");
  const revealFailed = useText(
    "component-browser.reveal-failed",
    "Could not open the file browser",
  );

  const patchView = useCallback(
    (patch: Parameters<typeof setComponentViewInSession>[2]) => {
      updateUiSession((snapshot) => setComponentViewInSession(snapshot, componentId, patch));
    },
    [componentId],
  );

  const failure = useCallback(
    (error: unknown, fallback: string) =>
      toast(error instanceof ApiError ? error.message : fallback, "err"),
    [toast],
  );

  const applyField = useCallback(
    (field: string, value: unknown) => {
      editField.mutate(
        { id: componentId, field, value },
        {
          onSuccess: () => toast(savedLabel, "ok"),
          onError: (error) => failure(error, saveFailed),
        },
      );
    },
    [componentId, editField, failure, saveFailed, savedLabel, toast],
  );

  /** Take the reader to the rows a quality segment is about, and to nothing else. */
  const onQualitySegment = useCallback(
    (kind: QualitySegmentKind) => {
      if (kind === "cad") {
        const focus = cadFocusKind(query.data!.cadAssets.kinds);
        patchView({ representation_layout: focus });
        assetRefs.current[focus]?.scrollIntoView({ block: "nearest" });
        return;
      }
      setSpecFilter(kind === "missing" ? "missing" : "conflicts");
      scrollColumnToTop(specScrollRef.current);
    },
    [patchView, query.data],
  );

  const busy = editField.isPending || moveCategory.isPending;
  const refreshing = refresh.status === "running";

  const shellItems = useMemo(
    () =>
      shellManageItems(shell.data, {
        onExport: () => setShellDialog("export"),
        onOpenIn: () => setShellDialog("open-in"),
        onReveal: () => {
          revealFiles.mutate(componentId, {
            onError: (error) => failure(error, revealFailed),
          });
        },
      }),
    [componentId, failure, revealFailed, revealFiles, shell.data],
  );

  const manageItems = useMemo(
    () =>
      manageMenuItems({
        onEditIdentity: () => setSurface("identity"),
        onEditClassification: () => setSurface("classification"),
        onReviewMissing: () => {
          setSpecFilter("missing");
          scrollColumnToTop(specScrollRef.current);
        },
        onRefresh: () => refresh.run(),
        refreshing,
        onReviewCadSources: () => setSurface("cad-sources"),
        onViewProvenance: () => setSurface("provenance"),
        onDelete: () => setConfirmDelete(true),
        shellItems,
      }),
    [refresh, refreshing, shellItems],
  );

  if (query.isLoading) {
    return (
      <WorkspaceMessage>
        <LoadingState dense id="component-browser.loading">
          Loading this component...
        </LoadingState>
      </WorkspaceMessage>
    );
  }
  if (query.error || !query.data) {
    return (
      <WorkspaceMessage>
        <ErrorState id="component-browser.load-failed" onRetry={() => query.refetch()}>
          This component could not be opened.
        </ErrorState>
      </WorkspaceMessage>
    );
  }

  const dossier = query.data;
  const categories = Object.keys(facets.data?.by_category ?? {}).sort();
  const categoryOptions = facets.data?.category_catalog?.length
    ? facets.data.category_catalog
    : categories;

  // Everything the placed pieces read, assembled by the one module that owns it. Not memoised, and
  // deliberately: the callbacks below are the same fresh closures the three columns used to be given
  // as props every render, so nothing here re-renders more or less often than it did before.
  const context: WorkspaceRenderContext = {
    componentId,
    dossier,
    header: {
      manageItems,
      onQualitySegment,
      onOpenDatasheet: setDatasheet,
      onFindDatasheet: () => setSurface("provenance"),
    },
    cad: {
      layout: view.representation_layout,
      onLayout: (layout: RepresentationLayout) => patchView({ representation_layout: layout }),
      onCompareSources: () => setSurface("cad-sources"),
      onOpenFullPreview: (kind) => setPreview(previewKindFor(kind)),
      assetRefs,
    },
    specifications: {
      filter: specFilter,
      onFilter: setSpecFilter,
      scrollRef: specScrollRef,
      onViewPinout: () => setSurface("pinout"),
    },
    sourcing: {
      onViewOffers: () => setSurface("offers"),
      onViewProvenance: () => setSurface("provenance"),
      onOpenDocument: (id) => {
        const item = dossier.documents.items.find((entry) => entry.id === id);
        if (item) setDatasheet({ id, document: item, kind: openKindFor(item) });
      },
      onRefresh: () => refresh.run(),
      refreshing,
      scrollRef: sourcingScrollRef,
    },
    status: {
      activity: deletePart.isPending
        ? "deleting"
        : refreshing
          ? "refreshing"
          : busy
            ? "saving"
            : "idle",
    },
  };

  return (
    <WorkspaceDocumentView
      context={context}
      overlays={
        <>
          <WorkspaceShellDialogs
            componentId={componentId}
            shell={shell.data}
            open={shellDialog}
            onClose={() => setShellDialog(null)}
            onFailure={failure}
          />

          <WorkspaceSurfaces
            componentId={componentId}
            dossier={dossier}
            surface={surface}
            onCloseSurface={() => setSurface(null)}
            preview={preview}
            onClosePreview={() => setPreview(null)}
            datasheet={datasheet}
            onCloseDatasheet={() => setDatasheet(null)}
            categoryOptions={categoryOptions}
            busy={busy}
            refresh={{ run: refresh.run, running: refreshing }}
            identityDetail={identityDetail}
            onEditField={applyField}
            onMoveCategory={(category) =>
              moveCategory.mutate(
                { id: componentId, category },
                {
                  onSuccess: () => toast(`${movedLabel} ${category}`, "ok"),
                  onError: (error) => failure(error, moveFailed),
                },
              )
            }
            onPinoutSaved={() => toast(pinoutSaved, "ok")}
            onPinoutFailed={(error) => failure(error, pinoutFailed)}
            enrich={
              <EnrichPanel
                mpn={dossier.identity.mpn}
                category={dossier.identity.category}
                current={{
                  manufacturer: dossier.identity.manufacturer,
                  description: dossier.qualitySummary.description,
                }}
                busy={busy}
                onApply={applyField}
              />
            }
            confirmDelete={confirmDelete}
            deleting={deletePart.isPending}
            onCancelDelete={() => setConfirmDelete(false)}
            onConfirmDelete={() => {
              setConfirmDelete(false);
              deletePart.mutate(componentId, {
                // The page owns the aftermath: it holds the selection, and it is still mounted
                // after this workspace goes, which is where an Undo has to live.
                onSuccess: () => onDeleted?.(componentId),
                onError: (error) => failure(error, deleteFailed),
              });
            }}
          />
        </>
      }
    />
  );
}

/**
 * Put a column back at the top after its content was filtered underneath the reader.
 *
 * Guarded because a scroll container is not guaranteed to implement `scrollTo` - jsdom does not,
 * and neither does a detached node mid-unmount. Failing to scroll is a cosmetic loss; throwing out
 * of a click handler takes the workspace down with it.
 */
function scrollColumnToTop(node: HTMLDivElement | null): void {
  if (node && typeof node.scrollTo === "function") node.scrollTo({ top: 0 });
  else if (node) node.scrollTop = 0;
}

/** The centring frame the workspace's own state block sits in. The state decides its own tone. */
function WorkspaceMessage({ children }: { children: ReactNode }) {
  return (
    <div
      data-dev-id="component-browser.message"
      className="flex h-full min-h-0 items-center justify-center overflow-hidden px-6 text-center"
    >
      {children}
    </div>
  );
}

/** Exported so the empty workspace state can share the copy id with the message it replaces. */
export function ComponentWorkspaceEmpty() {
  return (
    <div
      data-dev-id="component-browser.empty"
      className="flex h-full min-h-0 items-center justify-center overflow-hidden px-6 text-center"
    >
      <span className="ui-component-description">
        <Text id="component-browser.empty">Select a component to open it.</Text>
      </span>
    </div>
  );
}
