import { useCallback, useMemo, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useCatalogBuild, useCatalogBuildStatus, useOnboarding, usePartDossierQuery, usePartsQuery } from "../api/queries";
import { invalidatePartCadProjection } from "../api/partCadProjectionQueries";
import type { PartSummary } from "../api/types";
import { AddPartIcon, BoardIcon, BuildIcon, WarnIcon } from "../components/icons";
import { ManageModelsWorkspace } from "../components/component-workspace/ManageModelsWorkspace";
import { Button, EmptyState, ErrorState, LoadingState, RouteHeader } from "../components/primitives";
import { ConfirmDialog } from "../components/ConfirmDialog";
import { Text, useCopyFormatter, useText } from "../lib/copy";
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

function AssetRow({ part, tool, onManage, stateLabel }: { part: PartSummary; tool: string; onManage: () => void; stateLabel?: string }) {
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
        {stateLabel ?? (missing.length > 0 ? missing.map(assetTitleLabel).join(", ") : <Text id="assets.readiness.review">Readiness needs review</Text>)}
      </span>
      <Button small icon={<BoardIcon className="h-3.5 w-3.5" />} onClick={onManage}>
        <Text id="assets.manage">Manage CAD Assets</Text>
      </Button>
    </li>
  );
}

function FocusedAssetWorkspace({ componentId, tool, onBack }: { componentId: string; tool: CaptureEda; onBack: () => void }) {
  const dossier = usePartDossierQuery(componentId);
  const queryClient = useQueryClient();
  const refreshAttachedPart = useCallback(() => {
    void invalidatePartCadProjection(queryClient, componentId);
  }, [componentId, queryClient]);
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
      onAttached={refreshAttachedPart}
    />
  );
}

export function AssetsPage() {
  const [view, setView] = useState<AssetsView>(null);
  const [confirmBuild, setConfirmBuild] = useState(false);
  const [historyOpen, setHistoryOpen] = useState(false);
  const onboarding = useOnboarding();
  const parts = usePartsQuery({});
  const catalogStatus = useCatalogBuildStatus();
  const catalogBuild = useCatalogBuild();
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
  const pendingIds = useMemo(
    () => new Set(catalogStatus.data?.pending_parts.map((part) => part.id) ?? []),
    [catalogStatus.data?.pending_parts],
  );
  const readyToBuild = useMemo(() => rows.filter((part) => pendingIds.has(part.id)), [rows, pendingIds]);
  const automaticView: AssetsView = needsAssets.length > 0
    ? "needs-assets"
    : readyToBuild.length > 0
      ? "build-now"
      : null;
  const activeView = view ?? automaticView;
  const activeId = session.active_component;
  const scenarioFocusedId = scenarioUi.components?.cadView === "manage-models" || scenarioUi.provider
    ? rows[0]?.id ?? null
    : null;
  const focusedId = scenarioFocusedId
    ?? (activeId && componentView(session, activeId).cad_view === "manage-models" ? activeId : null);
  const heading = useText("assets.title", "Assets");
  const workflowLabel = useText("assets.workflow", "Asset workflow");
  const allCurrentLabel = useCopyFormatter(
    "assets.all-current-copy",
    "All CAD assets and the {tool} catalog are current.",
  );
  const pendingBuildOne = useCopyFormatter(
    "assets.pending-build-one",
    "1 component will build for {tool}.",
  );
  const pendingBuildMany = useCopyFormatter(
    "assets.pending-build-many",
    "{count} components will build for {tool}.",
  );
  const catalogCurrentLabel = useCopyFormatter(
    "assets.catalog-current",
    "The {tool} catalog is current.",
  );
  const buildResultOne = useCopyFormatter(
    "assets.build-result-one",
    "1 component current. {failed} failed.",
  );
  const buildResultMany = useCopyFormatter(
    "assets.build-result-many",
    "{succeeded} components current. {failed} failed.",
  );
  const buildTitle = useCopyFormatter("assets.build-confirm-title", "Build {tool} Catalog");
  const buildFailedLabel = useText("assets.build-failed", "Catalog Build failed.");
  const buildBodyOne = useText(
    "assets.build-confirm-body-one",
    "Build 1 pending component as one coalesced batch. Successful components remain current if another component fails.",
  );
  const buildBodyMany = useCopyFormatter(
    "assets.build-confirm-body-many",
    "Build {count} pending components as one coalesced batch. Successful components remain current if another component fails.",
  );
  const statusFact = catalogBuild.isPending || catalogStatus.data?.state === "building"
    ? "Building"
    : catalogStatus.data?.state === "current"
      ? "Current"
      : catalogStatus.data
        ? `${catalogStatus.data.pending_count} Pending`
        : "Catalog Status";
  const latestResult = catalogBuild.data ?? catalogStatus.data?.last_result ?? null;
  const buildHistory = latestResult
    ? [
        latestResult,
        ...(catalogStatus.data?.history ?? []).filter(
          (run) => run.completed_at !== latestResult.completed_at,
        ),
      ]
    : catalogStatus.data?.history ?? [];

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
        right={captureTool ? statusFact : undefined}
      >
        {heading}
      </RouteHeader>

      {focusedId && captureTool ? (
        <FocusedAssetWorkspace componentId={focusedId} tool={captureTool} onBack={closeFocused} />
      ) : (
        <div className="min-h-0 flex-1 overflow-y-auto p-5">
          <div className="mx-auto max-w-5xl">
            {activeView !== "build-now" ? (
              <Button
                variant="accent"
                icon={<AddPartIcon />}
                className="mb-5 !h-12 w-full justify-center text-sm"
                data-dev-id="assets.add-parts"
                onClick={openAddPart}
              >
                <Text id="assets.add-parts">Add Parts</Text>
              </Button>
            ) : null}
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2" role="group" aria-label={workflowLabel}>
              <button
                type="button"
                aria-pressed={activeView === "needs-assets"}
                onClick={() => setView("needs-assets")}
                className={`rounded-card p-4 text-left transition-colors ${activeView === "needs-assets" ? "bg-raise2" : "bg-surface hover:bg-raise"}`}
              >
                <span className="flex items-center gap-2 text-sm font-semibold text-t1"><WarnIcon className="h-4 w-4" /><Text id="assets.needs-assets">Needs Assets</Text></span>
                <span className="mt-1 block text-xs text-t3"><Text id="assets.needs-assets-help">Components missing required Symbol, Footprint, or shared 3D evidence.</Text></span>
              </button>
              <button
                type="button"
                aria-pressed={activeView === "build-now"}
                onClick={() => setView("build-now")}
                className={`rounded-card p-4 text-left transition-colors ${activeView === "build-now" ? "bg-raise2" : "bg-surface hover:bg-raise"}`}
              >
                <span className="flex items-center gap-2 text-sm font-semibold text-t1"><BuildIcon className="h-4 w-4" /><Text id="assets.build-now">Build Now</Text></span>
                <span className="mt-1 block text-xs text-t3"><Text id="assets.build-now-help">Components ready for the selected CAD tool's Catalog Build.</Text></span>
              </button>
            </div>

            {onboarding.isLoading || parts.isLoading || catalogStatus.isLoading ? (
              <LoadingState className="mt-8" id="assets.loading">Reading catalog readiness...</LoadingState>
            ) : onboarding.isError || parts.isError || catalogStatus.isError || !tool ? (
              <ErrorState className="mt-8" id="assets.error">Asset readiness could not be read.</ErrorState>
            ) : !activeView ? (
              <EmptyState className="mt-8" id="assets.all-current">
                {allCurrentLabel({ tool: catalogStatus.data?.tool_label ?? toolLabel })}
              </EmptyState>
            ) : (
              <section className="mt-5 overflow-hidden">
                <header className="flex items-center justify-between border-b border-line px-1 py-2.5">
                  <h2 className="flex items-center gap-2 text-sm font-semibold text-t1">
                    {activeView === "needs-assets" ? <><WarnIcon className="h-4 w-4" /><Text id="assets.needs-assets">Needs Assets</Text></> : <><BuildIcon className="h-4 w-4" /><Text id="assets.build-now">Build Now</Text></>}
                  </h2>
                  <span className="text-xs tabular-nums text-t3">{(activeView === "needs-assets" ? needsAssets : readyToBuild).length}</span>
                </header>
                {activeView === "needs-assets" ? (
                  needsAssets.length > 0 ? <ul>{needsAssets.map((part) => <AssetRow key={part.id} part={part} tool={tool} onManage={() => selectAssetsComponent(part.id)} />)}</ul>
                  : <EmptyState className="m-5" id="assets.none-missing">No components need required CAD assets.</EmptyState>
                ) : (
                  <>
                    <div className="flex flex-wrap items-center justify-between gap-3 px-1 py-4">
                      <p className="text-xs text-t3">
                        {catalogStatus.data?.pending_count
                          ? catalogStatus.data.pending_count === 1
                            ? pendingBuildOne({ tool: catalogStatus.data.tool_label })
                            : pendingBuildMany({ count: catalogStatus.data.pending_count, tool: catalogStatus.data.tool_label })
                          : catalogCurrentLabel({ tool: catalogStatus.data?.tool_label ?? toolLabel })}
                      </p>
                      <Button
                        variant="accent"
                        icon={<BuildIcon />}
                        disabled={!catalogStatus.data?.pending_count || catalogBuild.isPending}
                        onClick={() => setConfirmBuild(true)}
                      >
                        {catalogBuild.isPending ? (
                          <Text id="assets.building">Building</Text>
                        ) : (
                          <Text id="assets.build-now-action">Build Now</Text>
                        )}
                      </Button>
                    </div>
                    {latestResult ? (
                      <div
                        className="bg-raise px-3 py-2 text-xs text-t2"
                        role={catalogBuild.data ? "status" : undefined}
                        aria-live={catalogBuild.data ? "polite" : undefined}
                      >
                        {latestResult.succeeded === 1
                          ? buildResultOne({ failed: latestResult.failed })
                          : buildResultMany({ succeeded: latestResult.succeeded, failed: latestResult.failed })}
                      </div>
                    ) : null}
                    {catalogBuild.isError ? (
                      <ErrorState className="my-3" id="assets.build-error">
                        {catalogBuild.error instanceof Error ? catalogBuild.error.message : (
                          buildFailedLabel
                        )}
                      </ErrorState>
                    ) : null}
                    {latestResult?.items.filter((item) => item.status === "failed").map((item) => (
                      <p key={item.part_id} className="px-3 py-2 text-xs text-err-text">{item.part_id}: {item.detail}</p>
                    ))}
                    {readyToBuild.length > 0 ? (
                      <ul>{readyToBuild.map((part) => <AssetRow key={part.id} part={part} tool={tool} stateLabel="CAD Ready On Part" onManage={() => selectAssetsComponent(part.id)} />)}</ul>
                    ) : <EmptyState className="m-5" id="assets.none-ready">No components are pending Catalog Build.</EmptyState>}
                    {buildHistory.length ? (
                      <div className="mt-4 border-t border-line pt-3">
                        <Button small onClick={() => setHistoryOpen((open) => !open)} aria-expanded={historyOpen}>
                          <Text id="assets.build-record">Build History</Text>
                        </Button>
                        {historyOpen ? (
                          <ul className="mt-2 divide-y divide-line">
                            {buildHistory.map((run, index) => (
                              <li key={`${run.completed_at}-${run.primary_eda}-${index}`} className="py-2 text-xs text-t2">
                                <span className="font-semibold text-t1">
                                  <Text
                                    id="assets.build-record-summary"
                                    values={{ tool: run.tool_label, succeeded: run.succeeded, failed: run.failed }}
                                  >
                                    {"{tool}: {succeeded} current, {failed} failed"}
                                  </Text>
                                </span>
                                {run.items.map((item) => <span key={item.part_id} className="mt-1 block text-t3">{item.part_id}: {item.detail}</span>)}
                              </li>
                            ))}
                          </ul>
                        ) : null}
                      </div>
                    ) : null}
                  </>
                )}
              </section>
            )}
          </div>
        </div>
      )}
      <ConfirmDialog
        open={confirmBuild}
        title={buildTitle({ tool: catalogStatus.data?.tool_label ?? toolLabel })}
        body={(catalogStatus.data?.pending_count ?? 0) === 1
          ? buildBodyOne
          : buildBodyMany({ count: catalogStatus.data?.pending_count ?? 0 })}
        confirmLabel="Build Catalog"
        busy={catalogBuild.isPending}
        onCancel={() => setConfirmBuild(false)}
        onConfirm={() => {
          setConfirmBuild(false);
          catalogBuild.mutate();
        }}
      />
    </div>
  );
}
