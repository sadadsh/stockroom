/**
 * One opened component, whole.
 *
 * Three bands that never move: the identity header (who this is, and whether it is in good shape),
 * the representation dock (what it looks like to each design tool), and four information tabs (what
 * it is, what its numbers are, where to buy it, where the answers came from). The bands share a
 * fixed height budget - the root is `height:100%; min-height:0; overflow:hidden` - so opening a
 * component never produces a document that scrolls past its own instruments. Anything longer than
 * its band goes to a modal, which is the only surface here allowed a scrollbar.
 *
 * Every datum comes from the workspace projection. This component makes presentation decisions;
 * it makes no decisions about where a datum belongs, because those were already made once on the
 * backend and arrive already made.
 *
 * The WRITES live here rather than in the sheets: identity edits, the category move, the pinout
 * persist, applying an alternate, and the sourcing refresh. One owner for the mutations means one
 * place decides what a failure says and what a success invalidates, and the sheets stay renderers.
 */
import { useCallback, useState, type ReactNode } from "react";
import {
  useEditField,
  useFacetsQuery,
  useMoveCategory,
  usePartDetailQuery,
  usePartHistory,
  usePartWorkspaceQuery,
  useRefreshSourcing,
} from "../../api/queries";
import { ApiError } from "../../api/client";
import type { RepresentationKind } from "../../api/workspaceTypes";
import { componentDevId } from "../../lib/componentDevIds";
import { Text, useText } from "../../lib/copy";
import { togglePinned, type PinnedSpecs } from "../../lib/keySpecs";
import { readPinnedSpecs, writePinnedSpecs } from "../../lib/pinnedSpecs";
import { useToast } from "../../lib/toast";
import {
  componentView,
  setComponentViewInSession,
  updateUiSession,
  useUiSession,
  type ComponentInfoTab,
  type RepresentationLayout,
} from "../../lib/uiSession";
import { CadVariantSection } from "../CadVariantSection";
import { CompleteComponentSheet } from "./CompleteComponentSheet";
import { EnrichPanel } from "../EnrichPanel";
import { PreviewModal, type PreviewKind } from "../PreviewModal";
import { ErrorState, LoadingState, TabPanel, type TabItem } from "../primitives";
import { ComponentHeader } from "./ComponentHeader";
import { IdentitySheet } from "./IdentitySheet";
import { InfoTabsShell } from "./InfoTabsShell";
import { OverviewTab } from "./OverviewTab";
import { PinoutApply } from "./PinoutApply";
import { SourcesTab, SourcingTab, SpecificationsTab } from "./InfoTabPanels";
import { RepresentationDock } from "./RepresentationDock";
import { REPRESENTATION_LABEL } from "./RepresentationModule";
import { PinoutTable, SpecificationsSheet } from "./SpecificationsSheet";
import { SourcesSheet } from "./SourcesSheet";
import { SourcingSheet } from "./SourcingSheet";
import { WorkspaceModal } from "./WorkspaceModal";

// The four questions the opened component answers. The labels carry copy ids like every other
// user-visible string: tab labels were the one class of text that never reached the copy layer.
const INFO_TABS: readonly TabItem<ComponentInfoTab>[] = [
  { id: "overview", label: "Overview", copyId: "component-browser.info-tab-overview" },
  {
    id: "specifications",
    label: "Specifications",
    copyId: "component-browser.info-tab-specifications",
  },
  { id: "sourcing", label: "Sourcing", copyId: "component-browser.info-tab-sourcing" },
  { id: "sources", label: "Sources & History", copyId: "component-browser.info-tab-sources" },
];

export function ComponentWorkspace({ componentId }: { componentId: string }) {
  const session = useUiSession();
  const view = componentView(session, componentId);
  const query = usePartWorkspaceQuery(componentId);
  const history = usePartHistory(componentId);
  const facets = useFacetsQuery();
  const editField = useEditField();
  const moveCategory = useMoveCategory();
  const refresh = useRefreshSourcing(componentId);
  const { toast } = useToast();
  const [pinned, setPinned] = useState<PinnedSpecs>(readPinnedSpecs);
  const [preview, setPreview] = useState<PreviewKind | null>(null);
  const [details, setDetails] = useState<RepresentationKind | null>(null);
  const [viewAll, setViewAll] = useState<ComponentInfoTab | null>(null);
  const [identityOpen, setIdentityOpen] = useState(false);
  const [providersOpen, setProvidersOpen] = useState(false);
  // The canonical record, fetched only while identity editing is open. The handoff band inside
  // that sheet renders the RECORD (the EDA registry names record attributes), while everything
  // else on this surface reads the projection. Declared after the state it is gated on.
  const identityDetail = usePartDetailQuery(identityOpen ? componentId : null);
  const manual = useText("component-browser.manual", "Manual");
  const emptyValue = useText("component-browser.no-value", "None");
  const identityTitle = useText("component-browser.identity-modal", "Edit Identity");
  const providersTitle = useText("component-browser.providers-modal", "Complete Component");
  const savedLabel = useText("component-browser.saved", "Saved");
  const saveFailed = useText("component-browser.save-failed", "Could not save");
  const movedLabel = useText("component-browser.moved", "Moved");
  const moveFailed = useText("component-browser.move-failed", "Could not move");
  const pinoutSaved = useText("component-browser.pinout-saved", "Pinout saved");
  const pinoutFailed = useText("component-browser.pinout-failed", "Could not save the pinout");

  const patchView = useCallback(
    (patch: Parameters<typeof setComponentViewInSession>[2]) => {
      updateUiSession((snapshot) => setComponentViewInSession(snapshot, componentId, patch));
    },
    [componentId],
  );

  const togglePin = useCallback((category: string, specKey: string) => {
    setPinned((current) => {
      const next = togglePinned(current, category, specKey);
      writePinnedSpecs(next);
      return next;
    });
  }, []);

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
        {/* A written sentence and a retry, not the query's own exception text appended to a
            prefix. `${loadFailed} ${query.error.message}` put a raw transport error in the
            middle of the pane, which is the one thing a person cannot act on. */}
        <ErrorState id="component-browser.load-failed" onRetry={() => query.refetch()}>
          This component could not be opened.
        </ErrorState>
      </WorkspaceMessage>
    );
  }

  const workspace = query.data;
  const infoTab = view.info_tab;
  const busy = editField.isPending || moveCategory.isPending;
  const categories = Object.keys(facets.data?.by_category ?? {}).sort();
  const categoryOptions = facets.data?.category_catalog?.length
    ? facets.data.category_catalog
    : categories;

  /**
   * What an attention item's action does HERE.
   *
   * A representation problem is fixed by looking at that representation, so the dock expands it. A
   * missing identity field is fixed by editing it, so the identity sheet opens. A source
   * disagreement is answered in Sources & History, which is where attribution lives. Nothing
   * pretends to be a repair it cannot perform.
   */
  function runAction(action: string | null) {
    if (!action) {
      patchView({ info_tab: "specifications" });
      setViewAll("specifications");
      return;
    }
    if (action === "edit-identity") {
      setIdentityOpen(true);
      return;
    }
    if (action.startsWith("open-representation:")) {
      const kind = action.slice("open-representation:".length) as RepresentationLayout;
      patchView({ representation_layout: kind });
      return;
    }
    patchView({ info_tab: "sources" });
  }

  return (
    <div
      data-dev-id="component-browser.root"
      className="@container flex h-full min-h-0 flex-col overflow-hidden"
    >
      <div
        data-dev-id={componentDevId(componentId)}
        className="flex min-h-0 flex-1 flex-col overflow-hidden"
      >
        <ComponentHeader
          workspace={workspace}
          onPrimaryAction={runAction}
          onEditIdentity={() => setIdentityOpen(true)}
          onOpenProviders={() => setProvidersOpen(true)}
          onOpenDatasheet={() => {
            const url = workspace.summary.datasheetUrl;
            if (url) window.open(url, "_blank", "noreferrer");
          }}
        />

        <RepresentationDock
          componentId={componentId}
          representations={workspace.representations}
          layout={view.representation_layout}
          onLayout={(layout) => patchView({ representation_layout: layout })}
          toolByKind={view.representation_tool}
          onSelectTool={(kind, tool) => patchView({ representation_tool: { [kind]: tool } })}
          onExpand={(kind) => setPreview(kind === "model" ? "model" : kind)}
          onDetails={(kind) => setDetails(kind)}
        />

        <InfoTabsShell
          tabs={INFO_TABS}
          active={infoTab}
          onSelect={(tab) => patchView({ info_tab: tab })}
        >
          <TabPanel
            idBase="component-info"
            tab={infoTab}
            className="flex min-h-0 flex-1 flex-col overflow-hidden"
          >
            {infoTab === "overview" ? (
              <OverviewTab
                workspace={workspace}
                pinned={pinned}
                onTogglePin={togglePin}
                onAttentionAction={runAction}
                onOpenTab={(tab) => patchView({ info_tab: tab })}
              />
            ) : infoTab === "specifications" ? (
              <SpecificationsTab
                workspace={workspace}
                pinned={pinned}
                onViewAll={() => setViewAll("specifications")}
              />
            ) : infoTab === "sourcing" ? (
              <SourcingTab workspace={workspace} onViewAll={() => setViewAll("sourcing")} />
            ) : (
              <SourcesTab
                workspace={workspace}
                revisionCount={history.data?.count ?? null}
                onViewAll={() => setViewAll("sources")}
              />
            )}
          </TabPanel>
        </InfoTabsShell>
      </div>

      <PreviewModal
        open={preview !== null}
        partId={componentId}
        partName={workspace.identity.displayName}
        initialKind={preview ?? "symbol"}
        onClose={() => setPreview(null)}
      />

      <WorkspaceModal
        open={details !== null}
        title={details ? `${REPRESENTATION_LABEL[details]} Details` : ""}
        onClose={() => setDetails(null)}
      >
        {details ? (
          <div className="flex flex-col gap-3">
            <table className="w-full text-left text-xs">
              <thead className="text-2xs text-t3">
                <tr>
                  <th className="py-1 pr-3 font-medium">
                    <Text id="component-browser.details-tool">Tool</Text>
                  </th>
                  <th className="py-1 pr-3 font-medium">
                    <Text id="component-browser.details-state">State</Text>
                  </th>
                  <th className="py-1 pr-3 font-medium">
                    <Text id="component-browser.details-reference">Reference</Text>
                  </th>
                  <th className="py-1 pr-3 font-medium">
                    <Text id="component-browser.details-source">Source</Text>
                  </th>
                  <th className="py-1 font-medium">
                    <Text id="component-browser.details-checks">Checks</Text>
                  </th>
                </tr>
              </thead>
              <tbody className="text-t1">
                {workspace.representations[details].tools.map((tool) => (
                  <tr key={tool.tool} className="border-t border-line">
                    <td className="py-1 pr-3">{tool.toolLabel}</td>
                    <td className="py-1 pr-3">{tool.status}</td>
                    <td className="py-1 pr-3 font-mono text-2xs">
                      {[tool.reference.lib, tool.reference.name].filter(Boolean).join(":") ||
                        tool.reference.file ||
                        emptyValue}
                    </td>
                    <td className="py-1 pr-3">{tool.sourceLabel || manual}</td>
                    <td className="py-1 tabular-nums">{tool.checks.length}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {/* The retained-variant chooser stays reachable from here until its own slice replaces it. */}
            <CadVariantSection partId={componentId} enabled />
          </div>
        ) : null}
      </WorkspaceModal>

      <WorkspaceModal
        open={providersOpen}
        title={providersTitle}
        onClose={() => setProvidersOpen(false)}
      >
        {providersOpen ? (
          <CompleteComponentSheet
            componentId={componentId}
            identity={workspace.identity}
            providers={workspace.providers}
            onClose={() => setProvidersOpen(false)}
          />
        ) : null}
      </WorkspaceModal>

      <WorkspaceModal
        open={identityOpen}
        title={identityTitle}
        onClose={() => setIdentityOpen(false)}
      >
        <IdentitySheet
          identity={workspace.identity}
          detail={identityDetail.data ?? null}
          detailLoading={identityDetail.isLoading}
          detailFailed={!!identityDetail.error}
          onRetryDetail={() => identityDetail.refetch()}
          categories={categoryOptions}
          busy={busy}
          onEditField={(field, value) => applyField(field, value)}
          onMoveCategory={(category) =>
            moveCategory.mutate(
              { id: componentId, category },
              {
                onSuccess: () => toast(`${movedLabel} ${category}`, "ok"),
                onError: (error) => failure(error, moveFailed),
              },
            )
          }
        />
      </WorkspaceModal>

      <WorkspaceModal
        open={viewAll !== null}
        title={viewAll ? `${INFO_TABS.find((tab) => tab.id === viewAll)?.label ?? ""}` : ""}
        onClose={() => setViewAll(null)}
      >
        {viewAll === "specifications" ? (
          <SpecificationsSheet
            specifications={workspace.specifications}
            category={workspace.identity.category}
            pinned={pinned}
            onTogglePin={(specKey) => togglePin(workspace.identity.category, specKey)}
            pinout={
              <PinoutTable
                pinout={workspace.specifications.pinout}
                action={
                  <PinoutApply
                    componentId={componentId}
                    mpn={workspace.identity.mpn}
                    category={workspace.identity.category}
                    onSaved={() => toast(pinoutSaved, "ok")}
                    onFailed={(error) => failure(error, pinoutFailed)}
                  />
                }
              />
            }
          />
        ) : viewAll === "sourcing" ? (
          <SourcingSheet
            sourcing={workspace.sourcing}
            sourceRecords={workspace.sources.records}
          />
        ) : viewAll === "sources" ? (
          <SourcesSheet
            componentId={componentId}
            componentName={workspace.identity.displayName}
            sources={workspace.sources}
            applying={busy}
            onApplyAlternate={applyField}
            refresh={{ run: refresh.run, running: refresh.status === "running" }}
            enrich={
              <EnrichPanel
                mpn={workspace.identity.mpn}
                category={workspace.identity.category}
                current={{
                  manufacturer: workspace.identity.manufacturer,
                  description: workspace.summary.description.formattedValue,
                }}
                busy={busy}
                onApply={applyField}
              />
            }
          />
        ) : null}
      </WorkspaceModal>
    </div>
  );
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
      className="flex h-full min-h-0 items-center justify-center overflow-hidden px-6 text-center text-sm text-t3"
    >
      <Text id="component-browser.empty">Select a component to open it.</Text>
    </div>
  );
}
