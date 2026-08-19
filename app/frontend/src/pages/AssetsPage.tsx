import { useMemo, useState } from "react";
import { useOnboarding, usePartDossierQuery, usePartsQuery } from "../api/queries";
import type { PartSummary } from "../api/types";
import { AddPartIcon, BoardIcon, BuildIcon, WarnIcon } from "../components/icons";
import { ManageModelsWorkspace } from "../components/component-workspace/ManageModelsWorkspace";
import { Button, EmptyState, ErrorState, LoadingState, RouteHeader } from "../components/primitives";
import { Text, useText } from "../lib/copy";
import { useScenarioUiState } from "../design-studio/scenarioState";
import { useAddPart } from "../lib/addPart";
import { useOptionalCapture } from "../lib/capture";
import type { CaptureEda } from "../lib/captureRequirements";
import { assetTitleLabel } from "../lib/edaTarget";
import {
  componentView,
  openComponentInSession,
  setComponentViewInSession,
  updateUiSession,
  useUiSession,
} from "../lib/uiSession";

type AssetsView = "needs-assets" | "build-now" | null;

function readiness(part: PartSummary, tool: string | null) {
  return tool ? part.eda_readiness?.[tool] : undefined;
}

function selectAssetsComponent(partId: string) {
  updateUiSession((snapshot) => {
    const opened = openComponentInSession(snapshot, partId);
    const marked = setComponentViewInSession(opened, partId, { cad_view: "manage-models" });
    return { ...marked, selected_ids: { ...marked.selected_ids, component: partId } };
  });
}

function AssetRow({ part, tool, onManage }: { part: PartSummary; tool: string; onManage: () => void }) {
  const state = readiness(part, tool);
  const missing = state?.missing ?? [];
  return (
    <li className="grid grid-cols-[minmax(0,1fr)_minmax(10rem,0.7fr)_auto] items-center gap-4 border-b border-line px-4 py-3 last:border-b-0">
      <span className="flex min-w-0 items-center gap-2.5">
        <BoardIcon className="h-4 w-4 flex-none text-t3" />
        <span className="min-w-0">
          <span className="block truncate text-sm font-semibold text-t1">{part.mpn || part.display_name}</span>
          <span className="block truncate text-xs text-t3">{part.manufacturer || part.category}</span>
        </span>
      </span>
      <span className="min-w-0 text-xs text-t2">
        {missing.length > 0 ? missing.map(assetTitleLabel).join(", ") : <Text id="assets.readiness.review">Readiness needs review</Text>}
      </span>
      <Button small icon={<BoardIcon className="h-3.5 w-3.5" />} onClick={onManage}>
        <Text id="assets.manage">Manage CAD Assets</Text>
      </Button>
    </li>
  );
}

function FocusedAssetWorkspace({ componentId, tool, onBack }: { componentId: string; tool: CaptureEda; onBack: () => void }) {
  const dossier = usePartDossierQuery(componentId);
  if (dossier.isLoading) {
    return <LoadingState className="m-6" id="assets.component-loading">Reading this component's CAD sources...</LoadingState>;
  }
  if (dossier.isError || !dossier.data) {
    return <ErrorState className="m-6" id="assets.component-error" onRetry={() => void dossier.refetch()}>This component's CAD sources could not be read.</ErrorState>;
  }
  return (
    <ManageModelsWorkspace
      key={componentId}
      componentId={componentId}
      dossier={dossier.data}
      primaryEda={tool}
      onBack={onBack}
      onAttached={() => void dossier.refetch()}
    />
  );
}

export function AssetsPage() {
  const [view, setView] = useState<AssetsView>(null);
  const onboarding = useOnboarding();
  const parts = usePartsQuery({});
  const session = useUiSession();
  const scenarioUi = useScenarioUiState();
  const { open: openAddPart } = useAddPart();
  const capture = useOptionalCapture();
  const tool = onboarding.data?.primary_eda ?? null;
  const captureTool: CaptureEda | null = tool === "kicad" || tool === "altium" ? tool : null;
  const toolLabel = onboarding.data?.eda_tools.find((item) => item.key === tool)?.label ?? tool ?? "CAD";
  const rows = parts.data?.parts ?? [];
  const needsAssets = useMemo(
    () => tool ? rows.filter((part) => readiness(part, tool)?.ready !== true) : [],
    [rows, tool],
  );
  const readyToBuild = useMemo(
    () => tool ? rows.filter((part) => readiness(part, tool)?.ready === true) : [],
    [rows, tool],
  );
  const activeId = session.active_component;
  const scenarioFocusedId = scenarioUi.components?.cadView === "manage-models" || scenarioUi.provider
    ? rows[0]?.id ?? null
    : null;
  const focusedId = scenarioFocusedId
    ?? (activeId && componentView(session, activeId).cad_view === "manage-models" ? activeId : null);
  const heading = useText("assets.title", "Assets");
  const workflowLabel = useText("assets.workflow", "Asset workflow");

  function closeFocused() {
    if (!focusedId) return;
    if (capture?.active.partId === focusedId && capture.active.routeToken) {
      void capture.keepWorking();
    }
    updateUiSession((snapshot) => setComponentViewInSession(snapshot, focusedId, { cad_view: "models" }));
  }

  return (
    <div data-dev-id="assets.root" className="flex min-h-0 flex-1 flex-col">
      <RouteHeader
        heading
        data-dev-id="assets.title"
        right={captureTool ? `${toolLabel} Catalog` : undefined}
      >
        {heading}
      </RouteHeader>

      {focusedId && captureTool ? (
        <FocusedAssetWorkspace componentId={focusedId} tool={captureTool} onBack={closeFocused} />
      ) : (
        <div className="min-h-0 flex-1 overflow-y-auto p-5">
          <div className="mx-auto max-w-5xl">
            <Button
              variant="accent"
              icon={<AddPartIcon />}
              className="mb-5 !h-12 w-full justify-center text-sm"
              data-dev-id="assets.add-parts"
              onClick={openAddPart}
            >
              <Text id="assets.add-parts">Add Parts</Text>
            </Button>
            <div className="grid grid-cols-2 gap-3" role="group" aria-label={workflowLabel}>
              <button
                type="button"
                aria-pressed={view === "needs-assets"}
                onClick={() => setView("needs-assets")}
                className={`rounded-card border p-4 text-left ${view === "needs-assets" ? "border-focus bg-raise2" : "border-line bg-surface hover:bg-raise"}`}
              >
                <span className="flex items-center gap-2 text-sm font-semibold text-t1"><WarnIcon className="h-4 w-4" /><Text id="assets.needs-assets">Needs Assets</Text></span>
                <span className="mt-1 block text-xs text-t3"><Text id="assets.needs-assets-help">Components missing required Symbol, Footprint, or shared 3D evidence.</Text></span>
              </button>
              <button
                type="button"
                aria-pressed={view === "build-now"}
                onClick={() => setView("build-now")}
                className={`rounded-card border p-4 text-left ${view === "build-now" ? "border-focus bg-raise2" : "border-line bg-surface hover:bg-raise"}`}
              >
                <span className="flex items-center gap-2 text-sm font-semibold text-t1"><BuildIcon className="h-4 w-4" /><Text id="assets.build-now">Build Now</Text></span>
                <span className="mt-1 block text-xs text-t3"><Text id="assets.build-now-help">Components ready for the selected CAD tool's Catalog Build.</Text></span>
              </button>
            </div>

            {!view ? (
              <EmptyState className="mt-8" id="assets.choose-view">Choose Needs Assets or Build Now.</EmptyState>
            ) : onboarding.isLoading || parts.isLoading ? (
              <LoadingState className="mt-8" id="assets.loading">Reading catalog readiness...</LoadingState>
            ) : onboarding.isError || parts.isError || !tool ? (
              <ErrorState className="mt-8" id="assets.error">Asset readiness could not be read.</ErrorState>
            ) : (
              <section className="mt-4 overflow-hidden rounded-card border border-line bg-surface">
                <header className="flex items-center justify-between border-b border-line bg-band px-4 py-2.5">
                  <h2 className="flex items-center gap-2 text-sm font-semibold text-t1">
                    {view === "needs-assets" ? <><WarnIcon className="h-4 w-4" /><Text id="assets.needs-assets">Needs Assets</Text></> : <><BuildIcon className="h-4 w-4" /><Text id="assets.build-now">Build Now</Text></>}
                  </h2>
                  <span className="text-xs tabular-nums text-t3">{(view === "needs-assets" ? needsAssets : readyToBuild).length}</span>
                </header>
                {view === "needs-assets" ? (
                  needsAssets.length > 0 ? <ul>{needsAssets.map((part) => <AssetRow key={part.id} part={part} tool={tool} onManage={() => selectAssetsComponent(part.id)} />)}</ul>
                  : <EmptyState className="m-5" id="assets.none-missing">No components need required CAD assets.</EmptyState>
                ) : readyToBuild.length > 0 ? (
                  <ul>{readyToBuild.map((part) => <AssetRow key={part.id} part={part} tool={tool} onManage={() => selectAssetsComponent(part.id)} />)}</ul>
                ) : <EmptyState className="m-5" id="assets.none-ready">No components are ready for Catalog Build.</EmptyState>}
              </section>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
