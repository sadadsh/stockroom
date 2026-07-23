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
import { useQueryClient } from "@tanstack/react-query";
import { useStmMcus, useStmStatus, useBuildStmIndex } from "../api/stmQueries";
import { ApiError } from "../api/client";
import type { StmMcusArgs } from "../api/client";
import { FamilyPicker } from "../components/stm/FamilyPicker";
import { SpecMatrixTable } from "../components/stm/SpecMatrixTable";
import { Button, Card, Eyebrow } from "../components/primitives";

export interface StmScope extends StmMcusArgs {
  families: string[];
  mcus: string[];
}

const EMPTY_SCOPE: StmScope = { families: [], mcus: [] };

// The coarse server-side narrowing (decision 3): exactly one selected family narrows server-side;
// zero or multiple families fetch the wider matrix and are reconciled by the client filter below.
// Sub-series lines never hit the server (a pure client filter), so adding one never refetches.
function scopeToArgs(scope: StmScope): StmMcusArgs {
  return { family: scope.families.length === 1 ? scope.families[0] : undefined };
}

export function StmViewerPage() {
  const [scope, setScope] = useState<StmScope>(EMPTY_SCOPE);
  const [activePart, setActivePart] = useState<string | null>(null);

  const status = useStmStatus();
  const args = useMemo(() => scopeToArgs(scope), [scope]);
  const mcus = useStmMcus(args);

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
      <div className="flex min-h-0 flex-1">
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

        {/* pinout map + inspector (04-03 fills this reserved region) */}
        <aside className="flex w-[384px] flex-none flex-col border-l border-line px-4 pt-1">
          <PinoutRegionPlaceholder activePart={activePart} />
        </aside>
      </div>
    </PageShell>
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

// The reserved specimen region (04-03 renders the pinout map + legend + inspector here). Until a
// part is picked it is the recessed "chamber" empty state, so the column is never dead space.
function PinoutRegionPlaceholder({ activePart }: { activePart: string | null }) {
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <Eyebrow className="mb-2 px-1">Pinout</Eyebrow>
      <div className="flex min-h-0 flex-1 items-center justify-center rounded-card bg-stage px-6 text-center shadow-[inset_0_1px_0_var(--edge-hi)]">
        <p className="text-sm text-t3">
          {activePart
            ? "The pinout map lands here."
            : "Select a part to see its pinout."}
        </p>
      </div>
    </div>
  );
}

// The honest "index not built" call to action, driven by the build job's live progress (mirrors
// the RescanSection running/done/error flow). On success it re-queries the STM surface so the gate
// clears to the real matrix.
function BuildIndexGate() {
  const build = useBuildStmIndex();
  const qc = useQueryClient();

  useEffect(() => {
    if (build.status === "done") {
      qc.invalidateQueries({ queryKey: ["stm-status"] });
      qc.invalidateQueries({ queryKey: ["stm-mcus"] });
      qc.invalidateQueries({ queryKey: ["stm-families"] });
    }
  }, [build.status, qc]);

  const running = build.status === "running";
  const pct =
    build.progress?.pct != null ? Math.min(100, Math.round(build.progress.pct)) : null;

  return (
    <div className="flex flex-1 items-center justify-center px-6 py-10">
      <Card className="w-full max-w-[440px] px-6 py-6">
        <Eyebrow className="mb-2">STM Index</Eyebrow>
        <h2 className="mb-1.5 text-lg font-semibold text-t1">Build the Index</h2>
        <p className="mb-4 text-sm text-t2">
          The STM32 spec matrix and pinout maps are served from a derived index built from your
          CubeMX source. It has not been built yet on this machine. Building runs once and takes a
          moment.
        </p>

        {running ? (
          <div className="mb-4 flex flex-col gap-2" data-testid="stm-build-running">
            <div className="h-1.5 w-full overflow-hidden rounded-full bg-raise2">
              <div
                className="h-full rounded-full bg-acc transition-[width]"
                style={{ width: pct != null ? `${pct}%` : "35%" }}
              />
            </div>
            <p className="text-xs text-t3">{build.progress?.message ?? "Starting the build..."}</p>
          </div>
        ) : null}

        {build.status === "error" ? (
          <p className="mb-4 text-sm text-err" data-testid="stm-build-error">
            {build.error}
          </p>
        ) : null}

        <Button variant="accent" onClick={() => build.start()} disabled={running}>
          {running ? "Building..." : build.status === "error" ? "Try Again" : "Build the Index"}
        </Button>
      </Card>
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
