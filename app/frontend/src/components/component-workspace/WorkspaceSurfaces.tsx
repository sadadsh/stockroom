/**
 * Every secondary surface an opened component can raise, in one place.
 *
 * The three columns are the reading surface and they never move. These are the windows that open
 * ON TOP of them - the provider comparison, identity editing, the pinout table, the price ladder,
 * the provenance ledger, the datasheet viewer, the full preview and the delete confirmation - and
 * they are gathered here so the workspace itself stays what it is: a header, three columns and a
 * status bar.
 *
 * Exactly one modal surface is open at a time. `surface` is a single value rather than six booleans
 * precisely so that "two windows are somehow open at once" is not a state this component can be put
 * into. The datasheet viewer and the CAD preview are separate because they are opened from
 * different places and must survive whatever is happening behind them.
 */
import type { ReactNode } from "react";
import type { ComponentDossier } from "../../api/dossierTypes";
import { useCopyFormatter, useText } from "../../lib/copy";
import { ConfirmDialog } from "../ConfirmDialog";
import { PreviewModal, type PreviewKind } from "../PreviewModal";
import { DatasheetViewer } from "./DatasheetViewer";
import { IdentitySheet } from "./IdentitySheet";
import { PinoutApply } from "./PinoutApply";
import { PinoutTable } from "./PinoutTable";
import { SourcesSheet } from "./SourcesSheet";
import type { SourcesSheetTab } from "./SourcesSheet";
import { SourcingSheet } from "./SourcingSheet";
import { WorkspaceModal } from "./WorkspaceModal";
import type { DatasheetTarget } from "./datasheetWorkflow";

/** Which secondary surface is open. Exactly one at a time; `null` is the reading state. */
export type WorkspaceSurface =
  | "identity"
  | "classification"
  | "provenance"
  | "offers"
  | "pinout";

export interface WorkspaceSurfacesProps {
  componentId: string;
  dossier: ComponentDossier;
  surface: WorkspaceSurface | null;
  onCloseSurface: () => void;
  /** The full-size CAD preview, which is its own window rather than a surface. */
  preview: PreviewKind | null;
  onClosePreview: () => void;
  /** The datasheet viewer, also its own window: it opens from the header and from the documents. */
  datasheet: DatasheetTarget | null;
  onCloseDatasheet: () => void;
  categoryOptions: string[];
  busy: boolean;
  refresh: { run: () => void; running: boolean };
  identityDetail: {
    data: unknown;
    isLoading: boolean;
    error: unknown;
    refetch: () => void;
  };
  onEditField: (field: string, value: unknown) => void;
  onMoveCategory: (category: string) => void;
  onPinoutSaved: () => void;
  onPinoutFailed: (error: unknown) => void;
  /** The enrichment surface, passed in so the provenance sheet never re-implements it. */
  enrich: ReactNode;
  confirmDelete: boolean;
  initialSourcesTab?: SourcesSheetTab;
  deleting: boolean;
  onCancelDelete: () => void;
  onConfirmDelete: () => void;
}

export function WorkspaceSurfaces({
  componentId,
  dossier,
  surface,
  onCloseSurface,
  preview,
  onClosePreview,
  datasheet,
  onCloseDatasheet,
  categoryOptions,
  busy,
  refresh,
  identityDetail,
  onEditField,
  onMoveCategory,
  onPinoutSaved,
  onPinoutFailed,
  enrich,
  confirmDelete,
  initialSourcesTab,
  deleting,
  onCancelDelete,
  onConfirmDelete,
}: WorkspaceSurfacesProps) {
  const identityTitle = useText("component-browser.identity-modal", "Edit Identification");
  const classificationTitle = useText(
    "component-browser.classification-modal",
    "Edit Class and Classification",
  );
  const provenanceTitle = useText("component-browser.provenance-modal", "Data Provenance");
  const offersTitle = useText("component-browser.offers-modal", "Price Breaks");
  const pinoutTitle = useText("component-browser.pinout-modal", "Pinout");
  const confirmDeleteTitle = useText("component-browser.delete-title", "Delete Component");
  const confirmDeleteLabel = useText("component-browser.delete-confirm", "Delete Component");
  const deleteBody = useCopyFormatter(
    "component-browser.delete-body",
    "{name} will be removed from this catalog, together with its symbol, footprint, 3D model, specifications and captured source records. Its files remain in the git commits and can be restored from the message that follows.",
  );
  const componentName = dossier.identity.mpn || dossier.identity.displayName;

  return (
    <>
      <PreviewModal
        open={preview !== null}
        partId={componentId}
        partName={componentName}
        initialKind={preview ?? "symbol"}
        onClose={onClosePreview}
      />

      {/* The datasheet opens on top of the reading surface rather than in another application, so
          the selected component, the column scroll positions and every filter survive reading it. */}
      <DatasheetViewer
        open={datasheet !== null}
        componentId={componentId}
        target={datasheet}
        onClose={onCloseDatasheet}
      />

      <WorkspaceModal
        open={surface === "identity" || surface === "classification"}
        title={surface === "classification" ? classificationTitle : identityTitle}
        onClose={onCloseSurface}
      >
        <IdentitySheet
          identity={dossier.identity}
          detail={(identityDetail.data as never) ?? null}
          detailLoading={identityDetail.isLoading}
          detailFailed={!!identityDetail.error}
          onRetryDetail={identityDetail.refetch}
          categories={categoryOptions}
          busy={busy}
          onEditField={onEditField}
          onMoveCategory={onMoveCategory}
        />
      </WorkspaceModal>

      <WorkspaceModal open={surface === "pinout"} title={pinoutTitle} onClose={onCloseSurface}>
        <PinoutTable
          pinout={dossier.diagnostics.pinout}
          action={
            <PinoutApply
              componentId={componentId}
              mpn={dossier.identity.mpn}
              category={dossier.identity.category}
              onSaved={onPinoutSaved}
              onFailed={onPinoutFailed}
            />
          }
        />
      </WorkspaceModal>

      <WorkspaceModal open={surface === "offers"} title={offersTitle} onClose={onCloseSurface}>
        <SourcingSheet
          offers={dossier.distributorOffers}
          documents={dossier.documents.items}
          relatedParts={dossier.relatedParts}
          sources={dossier.provenance.sources}
        />
      </WorkspaceModal>

      <WorkspaceModal
        open={surface === "provenance"}
        title={provenanceTitle}
        onClose={onCloseSurface}
      >
        {surface === "provenance" ? (
          <SourcesSheet
            componentId={componentId}
            componentName={componentName}
            provenance={dossier.provenance}
            diagnostics={dossier.diagnostics}
            applying={busy}
            onApplyAlternate={onEditField}
            refresh={refresh}
            enrich={enrich}
            initialTab={initialSourcesTab}
          />
        ) : null}
      </WorkspaceModal>

      {/* The confirmation names the component and says what goes with it. Only the final button is
          solid red; the menu item that opened this dialog is restrained red TEXT. */}
      <ConfirmDialog
        open={confirmDelete}
        title={confirmDeleteTitle}
        body={deleteBody({ name: componentName })}
        confirmLabel={confirmDeleteLabel}
        danger
        busy={deleting}
        onCancel={onCancelDelete}
        onConfirm={onConfirmDelete}
      />
    </>
  );
}
