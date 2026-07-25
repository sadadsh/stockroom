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
import { useEffect, useMemo, useState } from "react";
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
  Button,
  Eyebrow,
  SegmentedControl,
  TabPanel,
  TabStrip,
  type TabItem,
} from "../components/primitives";

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
  { id: "explorer", label: "Explorer" },
  { id: "compatibility", label: "Bench" },
];

// The coarse server-side narrowing (decision 3): exactly one selected family narrows server-side;
// zero or multiple families fetch the wider matrix and are reconciled by the client filter below.
// Sub-series lines never hit the server (a pure client filter), so adding one never refetches.
function scopeToArgs(scope: StmScope): StmMcusArgs {
  return { family: scope.families.length === 1 ? scope.families[0] : undefined };
}

export function StmViewerPage() {
  const [tab, setTab] = useState<StmTab>("explorer");
  const [scope, setScope] = useState<StmScope>(EMPTY_SCOPE);
  const [activePart, setActivePart] = useState<string | null>(null);
  const [selectedPosition, setSelectedPosition] = useState<string | null>(null);

  const status = useStmStatus();
  const args = useMemo(() => scopeToArgs(scope), [scope]);
  const mcus = useStmMcus(args);
  const pinout = useStmPinout(activePart);

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
    let r = mcus.data?.mcus ?? [];
    if (scope.families.length) r = r.filter((row) => scope.families.includes(row.series));
    if (scope.mcus.length) r = r.filter((row) => scope.mcus.includes(row.line));
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
          aria-label="STM Viewer sections"
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
              <div className="py-16 text-center text-sm text-t3">Loading the spec matrix...</div>
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
}: {
  activePart: string | null;
  pinout: import("../api/types").PinoutDTO | null;
  isLoading: boolean;
  error: Error | null;
  selectedPosition: string | null;
  onSelectPosition: (position: string) => void;
  inspectedPin: import("../api/types").PinDTO | null;
  onRetry: () => void;
}) {
  const [view, setView] = useState<"map" | "table">("map");
  // The legend's category lens: highlighted buckets dim every other pad on the map. Reset when
  // the part changes (the lens describes the previous part's pins).
  const [highlight, setHighlight] = useState<ReadonlySet<string>>(new Set());
  useEffect(() => {
    setHighlight(new Set());
  }, [activePart]);
  const toggleHighlight = (key: string) =>
    setHighlight((cur) => {
      const next = new Set(cur);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="mb-2 flex items-center justify-between gap-2 px-1">
        <Eyebrow>Pinout</Eyebrow>
        {pinout ? (
          <SegmentedControl
            options={PINOUT_VIEWS}
            value={view}
            onChange={setView}
            size="small"
            aria-label="Pinout view"
          />
        ) : null}
      </div>

      {!activePart ? (
        <GhostSpecimen />
      ) : isLoading ? (
        <ChamberMessage>Loading the pinout...</ChamberMessage>
      ) : error ? (
        <div className="flex min-h-0 flex-1 flex-col items-center justify-center gap-3 rounded-card bg-stage px-6 text-center">
          <p className="text-sm text-err">
            {error instanceof ApiError && error.status === 0
              ? "Cannot reach the Stockroom server."
              : error.message}
          </p>
          <Button small onClick={onRetry}>
            Try Again
          </Button>
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
                <p className="px-1 py-4 text-sm text-t3">Select a pin to inspect its facts.</p>
              )}
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}

const PINOUT_VIEWS = [
  { id: "map", label: "Map" },
  { id: "table", label: "Table" },
] as const;

function ChamberMessage({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex min-h-0 flex-1 items-center justify-center rounded-card bg-stage px-6 text-center shadow-[inset_0_1px_0_var(--edge-hi)]">
      <p className="text-sm text-t3">{children}</p>
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
      <p className="text-sm text-t3">Select a part to see its pinout.</p>
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
    <div className="flex min-h-0 flex-1 flex-col">
      <header className="flex items-baseline gap-3 px-[30px] pb-4 pt-[22px]">
        <h1 className="text-title font-semibold text-t1">STM Viewer</h1>
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
  const message =
    status === 0
      ? "Cannot reach the Stockroom server."
      : status === 401
        ? "Not authorized. The API token is missing or invalid."
        : error.message;
  return (
    <div className="flex flex-col items-center gap-3 py-16 text-center">
      <div className="text-sm text-err">{message}</div>
      <Button small onClick={onRetry}>
        Try Again
      </Button>
    </div>
  );
}
