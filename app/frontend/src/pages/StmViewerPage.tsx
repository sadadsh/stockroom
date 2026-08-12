/**
 * The STM Viewer: browse and filter every STM32 in a virtualized spec matrix, scope by family,
 * and inspect a chosen part's interactive pinout map. It renders an honest "Build the Index" call
 * to action when the backend reports the derived index is not built (HTTP 409), never a raw error
 * or an infinite spinner (CONTEXT decision 9).
 *
 * Two separately-named pieces of client state (CONTEXT decision 2): `scope` is the FamilyPicker
 * multi-select that narrows the matrix; `activePart` is the one part shown in the pinout map. Both
 * live here and pass down as props; no global store. The coarse family selection drives at most
 * one useStmMcus fetch per scope change (a single selected family narrows server-side, otherwise
 * the family/line multi-select and every column facet filter client-side over the fetched rows,
 * decision 3); a matrix row click sets activePart, the seam the pinout map (04-03) consumes.
 */
import { useEffect, useMemo, useRef, useState } from "react";
import { useStmMcus, useStmStatus, useStmPinout } from "../api/stmQueries";
import { ApiError } from "../api/client";
import type { StmMcusArgs } from "../api/client";
import { FamilyPicker } from "../components/stm/FamilyPicker";
import { SpecMatrixTable } from "../components/stm/SpecMatrixTable";
import { PinoutMap } from "../components/stm/PinoutMap";
import { PinoutLegend } from "../components/stm/PinoutLegend";
import { PinInspector } from "../components/stm/PinInspector";
import { PinoutTable } from "../components/stm/PinoutTable";
import { BuildIndexGate } from "../components/stm/BuildIndexGate";
import { CompatibilityWorkbench } from "../components/stm/CompatibilityWorkbench";
import {
  EmptyState,
  ErrorState,
  Eyebrow,
  LoadingState,
  SegmentedControl,
  TabPanel,
  TabStrip,
  type TabItem,
} from "../components/primitives";
import { Text, useText } from "../lib/copy";
import { useScenarioUiState } from "../design-studio/scenarioState";

export interface StmScope extends StmMcusArgs {
  families: string[];
  mcus: string[];
}

const EMPTY_SCOPE: StmScope = { families: [], mcus: [] };

// The STM Viewer's two co-equal sections (CONTEXT decision 10 - a tab of this page, never a new
// nav route): the Phase-4 explorer and the Bench (the socket-union workbench, named for the
// retired Hardware app's Bench tab this workstream rebuilds - owner rename 2026-07-23).
type StmTab = "explorer" | "compatibility";
const STM_TABS: readonly TabItem<StmTab>[] = [
  { id: "explorer", label: "Explorer", copyId: "stm.viewer.tab.explorer" },
  { id: "compatibility", label: "Bench", copyId: "stm.viewer.tab.compatibility" },
];

// The coarse server-side narrowing (decision 3): exactly one selected family narrows server-side;
// zero or multiple families fetch the wider matrix and are reconciled by the client filter below.
// Sub-series lines never hit the server (a pure client filter), so adding one never refetches.
function scopeToArgs(scope: StmScope): StmMcusArgs {
  return { family: scope.families.length === 1 ? scope.families[0] : undefined };
}

export function StmViewerPage() {
  const preview = useScenarioUiState().stm;
  const [tab, setTab] = useState<StmTab>(preview?.tab ?? "explorer");
  const priorScenarioTab = useRef<StmTab | null>(null);
  const [scope, setScope] = useState<StmScope>(EMPTY_SCOPE);
  const [activePart, setActivePart] = useState<string | null>(preview?.activePart ?? null);
  const [selectedPosition, setSelectedPosition] = useState<string | null>(preview?.selectedPosition ?? null);

  const status = useStmStatus();
  const sectionsAria = useText("stm.viewer.sections-aria", "STM Viewer sections");
  const args = useMemo(() => scopeToArgs(scope), [scope]);
  const mcus = useStmMcus(args);
  const pinout = useStmPinout(activePart);

  useEffect(() => {
    if (!preview) {
      if (priorScenarioTab.current !== null) setTab(priorScenarioTab.current);
      priorScenarioTab.current = null;
      return;
    }
    if (priorScenarioTab.current === null) priorScenarioTab.current = tab;
    setTab(preview.tab ?? "explorer");
    // Each preview object is an explicit registry transition. `tab` is deliberately excluded so
    // owner interaction inside a preview cannot replace the real-data tab restored on exit.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [preview]);

  // A new part clears any pin selection (the previous pin does not exist on the new package).
  useEffect(() => {
    setSelectedPosition(null);
  }, [activePart]);

  // The inspected pin, looked up from the ALREADY-fetched pinout (decision 4): no per-pin fetch.
  const inspectedPin =
    selectedPosition != null
      ? (pinout.data?.pins.find((p) => p.position === selectedPosition) ?? null)
      : null;

  const mcusError = mcus.error;
  const indexNotBuilt =
    (mcusError instanceof ApiError && mcusError.status === 409) ||
    (status.data ? !status.data.built : false);

  // The family / line multi-select applied client-side over the fetched rows (the server narrowed
  // to at most one family; everything finer is client-side, decision 3).
  const rows = useMemo(() => {
    // one Set per selection, so a wide matrix does not re-scan the family/line lists per row
    const families = new Set(scope.families);
    const lines = new Set(scope.mcus);
    let r = mcus.data?.mcus ?? [];
    if (families.size) r = r.filter((row) => families.has(row.series));
    if (lines.size) r = r.filter((row) => lines.has(row.line));
    return r;
  }, [mcus.data, scope.families, scope.mcus]);

  if (indexNotBuilt) {
    return (
      <PageShell>
        <BuildIndexGate />
      </PageShell>
    );
  }

  return (
    <PageShell status={status.data?.mcu_count} families={status.data?.family_count}>
      <div className="flex-none px-[30px] pb-3">
        <TabStrip
          tabs={STM_TABS}
          active={tab}
          onSelect={setTab}
          idBase="stm-view"
          devIdBase="stm"
          aria-label={sectionsAria}
        />
      </div>

      {tab === "explorer" ? (
        <TabPanel idBase="stm-view" tab="explorer" className="flex min-h-0 min-w-0 flex-1">
          {/* scope */}
          <div className="flex w-[236px] flex-none flex-col overflow-hidden px-3 pt-1">
            <FamilyPicker scope={scope} onScopeChange={setScope} />
          </div>

          {/* matrix */}
          <div className="flex min-w-0 flex-1 flex-col border-l border-line px-4 pt-1">
            {mcus.isLoading ? (
              <LoadingState className="mt-4" id="stm.matrix-loading">
                Loading the STM32 specification matrix...
              </LoadingState>
            ) : mcusError ? (
              <MatrixError error={mcusError} onRetry={() => mcus.refetch()} />
            ) : (
              <SpecMatrixTable
                rows={rows}
                activePart={activePart}
                onSelectPart={setActivePart}
              />
            )}
          </div>

          {/* pinout map + legend + inspector */}
          <aside className="flex w-[384px] flex-none flex-col overflow-hidden border-l border-line px-4 pt-1">
            <PinoutRegion
              activePart={activePart}
              pinout={pinout.data ?? null}
              isLoading={pinout.isLoading && !!activePart}
              error={pinout.error}
              selectedPosition={selectedPosition}
              onSelectPosition={setSelectedPosition}
              inspectedPin={inspectedPin}
              onRetry={() => pinout.refetch()}
              initialView={preview?.pinoutView}
            />
          </aside>
        </TabPanel>
      ) : (
        <TabPanel idBase="stm-view" tab="compatibility" className="flex min-h-0 min-w-0 flex-1">
          <CompatibilityWorkbench />
        </TabPanel>
      )}
    </PageShell>
  );
}

// The specimen region: the empty state until a part is picked, then the pinout map OR the full
// pinout table (one selection model across both), the modular legend, and the inspector - all off
// the single already-fetched pinout (decision 4).
function PinoutRegion({
  activePart,
  pinout,
  isLoading,
  error,
  selectedPosition,
  onSelectPosition,
  inspectedPin,
  onRetry,
  initialView,
}: {
  activePart: string | null;
  pinout: import("../api/types").PinoutDTO | null;
  isLoading: boolean;
  error: Error | null;
  selectedPosition: string | null;
  onSelectPosition: (position: string) => void;
  inspectedPin: import("../api/types").PinDTO | null;
  onRetry: () => void;
  initialView?: "map" | "table";
}) {
  const [view, setView] = useState<"map" | "table">(initialView ?? "map");
  const viewAria = useText("stm.viewer.pinout-view-aria", "Pinout view");
  // The legend's category lens: highlighted buckets dim every other pad on the map. The lens
  // describes ONE part's pins, so it is stored WITH the part it was picked on and read back only
  // for that part - a new part shows no lens on its first render, where a reset effect would have
  // drawn the previous part's lens once before clearing it. The map/table choice deliberately
  // survives a part change, so this stays a partial reset rather than a keyed remount.
  const [lens, setLens] = useState<{ part: string | null; keys: ReadonlySet<string> }>({
    part: activePart,
    keys: EMPTY_HIGHLIGHT,
  });
  const highlight = lens.part === activePart ? lens.keys : EMPTY_HIGHLIGHT;
  const toggleHighlight = (key: string) => {
    const next = new Set(highlight);
    if (next.has(key)) next.delete(key);
    else next.add(key);
    setLens({ part: activePart, keys: next });
  };

  return (
    <div data-dev-id="stm.pinout" className="flex min-h-0 flex-1 flex-col">
      <div className="mb-2 flex items-center justify-between gap-2 px-1">
        <Eyebrow>
          <Text id="stm.viewer.pinout-title">Pinout</Text>
        </Eyebrow>
        {pinout ? (
          <SegmentedControl
            options={PINOUT_VIEWS}
            value={view}
            onChange={setView}
            size="small"
            aria-label={viewAria}
          />
        ) : null}
      </div>

      {!activePart ? (
        <GhostSpecimen />
      ) : isLoading ? (
        <ChamberMessage>
          <LoadingState dense id="stm.pinout-loading">
            Loading this part's pinout...
          </LoadingState>
        </ChamberMessage>
      ) : error ? (
        <div className="flex min-h-0 flex-1 flex-col items-center justify-center gap-3 rounded-card bg-stage px-6 text-center">
          {error instanceof ApiError && error.status === 0 ? (
            <ErrorState dense id="stm.pinout-unreachable" onRetry={onRetry}>
              Stockroom is not answering on this machine.
            </ErrorState>
          ) : (
            <ErrorState dense id="stm.pinout-failed" onRetry={onRetry}>
              This part's pinout could not be read.
            </ErrorState>
          )}
        </div>
      ) : pinout ? (
        <div className="flex min-h-0 flex-1 flex-col gap-3">
          {/* A definite-height COLUMN FLEX slot: PinoutMap's chamber shrinks inside it so the
              chamber footer (badges + Reset View) stays within the slot instead of spilling
              over the legend below. The table view fills the same slot. */}
          <div className="flex h-[392px] flex-none flex-col">
            {view === "map" ? (
              <PinoutMap
                pinout={pinout}
                selectedPosition={selectedPosition}
                onSelectPosition={onSelectPosition}
                highlight={highlight}
              />
            ) : (
              <PinoutTable
                pinout={pinout}
                selectedPosition={selectedPosition}
                onSelectPosition={onSelectPosition}
              />
            )}
          </div>
          {/* ONE scroller for legend + inspector: the legend grew live counts and the
              bring-up section, so pinning it flex-none clipped its tail (and the whole
              inspector) with no way to scroll onto them. */}
          <div className="min-h-0 flex-1 overflow-y-auto">
            <div className="border-b border-line pb-3">
              <PinoutLegend
                pinout={pinout}
                highlight={highlight}
                onToggleHighlight={toggleHighlight}
              />
            </div>
            <div className="pt-2">
              {inspectedPin ? (
                <PinInspector pin={inspectedPin} part={activePart} />
              ) : (
                <EmptyState dense className="px-1" id="stm.pin-prompt">
                  Select a pin to inspect its facts.
                </EmptyState>
              )}
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}

// The no-lens value, kept module-level so "no highlight" is one stable identity.
const EMPTY_HIGHLIGHT: ReadonlySet<string> = new Set<string>();

const PINOUT_VIEWS = [
  { id: "map", label: "Map", copyId: "stm.viewer.view.map" },
  { id: "table", label: "Table", copyId: "stm.viewer.view.table" },
] as const;

/** The centring chamber a state block sits in. The state decides its own tone and wording. */
function ChamberMessage({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex min-h-0 flex-1 items-center justify-center rounded-card bg-stage px-6 text-center shadow-[inset_0_1px_0_var(--edge-hi)]">
      {children}
    </div>
  );
}

// The no-part-selected chamber: a quiet neutral specimen sketch (an unlabeled LQFP outline in the
// chamber's own line tints, no data hues) so the empty state teaches what the space is FOR instead
// of sitting as a bare grey void. Purely decorative; the prompt line carries the instruction.
function GhostSpecimen() {
  const pads = Array.from({ length: 11 }, (_, i) => 34 + i * 12);
  return (
    <div
      className="flex min-h-0 flex-1 flex-col items-center justify-center gap-4 rounded-card bg-stage px-6 text-center shadow-[inset_0_1px_0_var(--edge-hi)]"
      data-testid="pinout-ghost"
    >
      <svg viewBox="0 0 200 200" className="h-36 w-36 opacity-60" aria-hidden="true">
        <rect
          x={40}
          y={40}
          width={120}
          height={120}
          rx={8}
          fill="var(--c-raise)"
          stroke="var(--c-line2)"
          strokeWidth={1}
        />
        {pads.map((p) => (
          <g key={p} fill="var(--c-raise2)">
            <rect x={26} y={p} width={12} height={6} rx={1.5} />
            <rect x={162} y={p} width={12} height={6} rx={1.5} />
            <rect x={p} y={26} width={6} height={12} rx={1.5} />
            <rect x={p} y={162} width={6} height={12} rx={1.5} />
          </g>
        ))}
      </svg>
      <EmptyState dense id="stm.part-prompt">Select a part to see its pinout.</EmptyState>
    </div>
  );
}

// The page frame: a self-heading header band (the rail carries the active-surface highlight) over
// a full-height content area the columns fill.
function PageShell({
  children,
  status,
  families,
}: {
  children: React.ReactNode;
  status?: number;
  families?: number;
}) {
  return (
    <div data-dev-id="stm.root" className="flex min-h-0 flex-1 flex-col">
      <header className="flex items-baseline gap-3 px-[30px] pb-4 pt-[22px]">
        <h1 className="text-title font-semibold text-t1">
          <Text id="stm.viewer.title">STM Viewer</Text>
        </h1>
        {status != null ? (
          <span className="tnum font-mono text-xs text-t3">
            {status.toLocaleString()} MCUs
            {families != null ? ` · ${families} families` : ""}
          </span>
        ) : null}
      </header>
      {children}
    </div>
  );
}

// A non-409 failure (a network drop, an unexpected status) is an honest retry surface, never the
// build call to action (which is only for the specific not-built state).
function MatrixError({ error, onRetry }: { error: Error; onRetry: () => void }) {
  const status = error instanceof ApiError ? error.status : undefined;
  // Three written sentences, one per cause a person can act on differently. `error.message` used
  // to be the fallback branch, which put a transport string in the middle of the matrix.
  if (status === 0) {
    return (
      <ErrorState className="mt-4" id="stm.matrix-unreachable" onRetry={onRetry}>
        Stockroom is not answering on this machine.
      </ErrorState>
    );
  }
  if (status === 401) {
    return (
      <ErrorState className="mt-4" id="stm.matrix-unauthorized" onRetry={onRetry}>
        This machine is not signed in to the catalog.
      </ErrorState>
    );
  }
  return (
    <ErrorState className="mt-4" id="stm.matrix-failed" onRetry={onRetry}>
      The STM32 specification matrix could not be read.
    </ErrorState>
  );
}
