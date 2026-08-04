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
 */
import { useCallback, useState } from "react";
import { usePartWorkspaceQuery } from "../../api/queries";
import type { RepresentationKind } from "../../api/workspaceTypes";
import { componentDevId } from "../../lib/componentDevIds";
import { Text, useText } from "../../lib/copy";
import { togglePinned, type PinnedSpecs } from "../../lib/keySpecs";
import { readPinnedSpecs, writePinnedSpecs } from "../../lib/pinnedSpecs";
import {
  componentView,
  setComponentViewInSession,
  updateUiSession,
  useUiSession,
  type ComponentInfoTab,
  type RepresentationLayout,
} from "../../lib/uiSession";
import { CadVariantSection } from "../CadVariantSection";
import { PreviewModal, type PreviewKind } from "../PreviewModal";
import { TabPanel, type TabItem } from "../primitives";
import { ComponentHeader } from "./ComponentHeader";
import { InfoTabsShell } from "./InfoTabsShell";
import { OverviewTab } from "./OverviewTab";
import { SourcesTab, SourcingTab, SpecificationsTab } from "./InfoTabPanels";
import { RepresentationDock } from "./RepresentationDock";
import { REPRESENTATION_LABEL } from "./RepresentationModule";
import { WorkspaceModal } from "./WorkspaceModal";

const INFO_TABS: readonly TabItem<ComponentInfoTab>[] = [
  { id: "overview", label: "Overview" },
  { id: "specifications", label: "Specifications" },
  { id: "sourcing", label: "Sourcing" },
  { id: "sources", label: "Sources & History" },
];

export function ComponentWorkspace({ componentId }: { componentId: string }) {
  const session = useUiSession();
  const view = componentView(session, componentId);
  const query = usePartWorkspaceQuery(componentId);
  const [pinned, setPinned] = useState<PinnedSpecs>(readPinnedSpecs);
  const [preview, setPreview] = useState<PreviewKind | null>(null);
  const [details, setDetails] = useState<RepresentationKind | null>(null);
  const [viewAll, setViewAll] = useState<ComponentInfoTab | null>(null);
  const loadingLabel = useText("component-browser.loading", "Loading component...");
  const loadFailed = useText(
    "component-browser.load-failed",
    "Could not load this component.",
  );
  const manual = useText("component-browser.manual", "Manual");
  const emptyValue = useText("component-browser.no-value", "None");

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

  if (query.isLoading) {
    return <WorkspaceMessage>{loadingLabel}</WorkspaceMessage>;
  }
  if (query.error || !query.data) {
    return (
      <WorkspaceMessage tone="err">
        {`${loadFailed} ${query.error?.message ?? ""}`.trim()}
      </WorkspaceMessage>
    );
  }

  const workspace = query.data;
  const infoTab = view.info_tab;

  /**
   * What an attention item's action does HERE.
   *
   * A representation problem is fixed by looking at that representation, so the dock expands it. A
   * source disagreement is answered in Sources & History, which is where attribution lives. Nothing
   * pretends to be a repair it cannot perform.
   */
  function runAction(action: string | null) {
    if (!action) {
      patchView({ info_tab: "specifications" });
      setViewAll("specifications");
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
              <SpecificationsTab workspace={workspace} onViewAll={() => setViewAll("specifications")} />
            ) : infoTab === "sourcing" ? (
              <SourcingTab workspace={workspace} onViewAll={() => setViewAll("sourcing")} />
            ) : (
              <SourcesTab workspace={workspace} onViewAll={() => setViewAll("sources")} />
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
        open={viewAll !== null}
        title={viewAll ? `${INFO_TABS.find((tab) => tab.id === viewAll)?.label ?? ""}` : ""}
        onClose={() => setViewAll(null)}
      >
        <ViewAllBody workspace={workspace} tab={viewAll} />
      </WorkspaceModal>
    </div>
  );
}

/**
 * The exhaustive views, as shells.
 *
 * They state the real totals from the projection so the shell is never a lie, and they name what
 * the full sheet will carry. Building four exhaustive sheets here would duplicate the surface the
 * next slice replaces them with.
 */
function ViewAllBody({
  workspace,
  tab,
}: {
  workspace: import("../../api/workspaceTypes").ComponentWorkspaceResponse;
  tab: ComponentInfoTab | null;
}) {
  if (tab === "specifications") {
    return (
      <div className="flex flex-col gap-2">
        {workspace.specifications.groups.map((group) => (
          <section key={group.id}>
            <h2 className="mb-1 text-xs font-semibold text-t1">{`${group.label} (${group.count})`}</h2>
            <dl>
              {group.facts.map((fact) => (
                <div
                  key={fact.id}
                  className="flex items-baseline justify-between gap-4 border-b border-line/60 py-1"
                >
                  <dt className="min-w-0 truncate text-xs text-t2">{fact.label}</dt>
                  <dd className="tnum flex-none font-mono text-xs text-t1">
                    {fact.unit ? `${fact.formattedValue} ${fact.unit}` : fact.formattedValue}
                  </dd>
                </div>
              ))}
            </dl>
          </section>
        ))}
        {workspace.specifications.groups.length === 0 ? (
          <p className="text-xs text-t3">
            <Text id="component-browser.specifications-empty">No specifications on record.</Text>
          </p>
        ) : null}
      </div>
    );
  }
  if (tab === "sourcing") {
    return (
      <div className="flex flex-col gap-2">
        {workspace.sourcing.offers.map((offer) => (
          <div
            key={`${offer.sourceId}:${offer.partNumber}`}
            className="flex items-baseline justify-between gap-4 border-b border-line/60 py-1"
          >
            <span className="min-w-0 truncate text-xs text-t1">
              {`${offer.sourceLabel || offer.sourceId} ${offer.partNumber}`.trim()}
            </span>
            <span className="tnum flex-none font-mono text-xs text-t2">
              {offer.priceBreaks.length}
              {" "}
              <Text id="component-browser.price-breaks">price breaks</Text>
            </span>
          </div>
        ))}
        {workspace.sourcing.offers.length === 0 ? (
          <p className="text-xs text-t3">
            <Text id="component-browser.sourcing-empty">No distributor offers on record.</Text>
          </p>
        ) : null}
      </div>
    );
  }
  if (tab === "sources") {
    return (
      <div className="flex flex-col gap-2">
        {workspace.sources.records.map((record) => (
          <div
            key={record.id}
            className="flex items-baseline justify-between gap-4 border-b border-line/60 py-1"
          >
            <span className="min-w-0 truncate text-xs text-t1">{record.label}</span>
            <span className="flex-none text-xs text-t3">
              {record.fetchedAt || <Text id="component-browser.undated">Undated</Text>}
            </span>
          </div>
        ))}
        {workspace.sources.records.length === 0 ? (
          <p className="text-xs text-t3">
            <Text id="component-browser.sources-empty">No captured source records.</Text>
          </p>
        ) : null}
      </div>
    );
  }
  return null;
}

function WorkspaceMessage({
  tone = "t3",
  children,
}: {
  tone?: "t3" | "err";
  children: string;
}) {
  return (
    <div
      data-dev-id="component-browser.message"
      className={`flex h-full min-h-0 items-center justify-center overflow-hidden px-6 text-center text-sm ${
        tone === "err" ? "text-err" : "text-t3"
      }`}
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
