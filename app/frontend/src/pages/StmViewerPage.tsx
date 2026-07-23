/**
 * The STM Viewer: browse and filter every STM32 in a spec matrix, scope by family, and inspect
 * a chosen part's interactive pinout map. This first slice (04-01) proves the whole
 * frontend-to-API pipe: it lists MCUs by their real MPN and renders an honest "Build the index"
 * call to action when the backend reports the derived index is not built (HTTP 409). The full
 * faceted matrix (04-02) and the pinout map + inspector (04-03) expand out from this shell.
 *
 * Two separately-named pieces of client state (CONTEXT decision 2): `scope` is the FamilyPicker
 * multi-select that narrows the matrix; `activePart` is the one part shown in the pinout map.
 * Both live here and pass down as props; no global store.
 */
import { useEffect, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useStmMcus, useStmStatus, useBuildStmIndex } from "../api/stmQueries";
import { ApiError } from "../api/client";
import type { StmMcusArgs } from "../api/client";
import type { McuSpecRow } from "../api/types";
import { Button, Card, Eyebrow } from "../components/primitives";

export interface StmScope extends StmMcusArgs {
  families: string[];
  mcus: string[];
}

const EMPTY_SCOPE: StmScope = { families: [], mcus: [] };

// The coarse server-side narrowing the matrix fetch honors: the first selected family and MCU
// (one fetch per scope change; every finer facet is a client-side column filter, decision 3).
function scopeToArgs(scope: StmScope): StmMcusArgs {
  return {
    family: scope.families[0],
    q: scope.mcus[0],
  };
}

export function StmViewerPage() {
  const [scope, setScope] = useState<StmScope>(EMPTY_SCOPE);
  // Declared now (CONTEXT decision 2); the FamilyPicker (04-02) drives setScope, the spec matrix
  // (04-02) sets activePart, the pinout map (04-03) reads it. Unused in this tracer slice beyond
  // being the reserved seams the later plans wire in.
  const [activePart, setActivePart] = useState<string | null>(null);
  void setScope;
  void activePart;
  void setActivePart;

  const status = useStmStatus();
  const mcus = useStmMcus(scopeToArgs(scope));

  // The index is not built when a read 409s, or the status endpoint reports built:false. Either
  // path routes to the build call to action, never a raw error screen or an infinite spinner.
  const mcusError = mcus.error;
  const indexNotBuilt =
    (mcusError instanceof ApiError && mcusError.status === 409) ||
    (status.data ? !status.data.built : false);

  if (indexNotBuilt) {
    return (
      <PageFrame>
        <BuildIndexGate />
      </PageFrame>
    );
  }

  const rows = mcus.data?.mcus ?? [];

  return (
    <PageFrame status={status.data?.mcu_count} families={status.data?.family_count}>
      {mcus.isLoading ? (
        <div className="py-16 text-center text-sm text-t3">Loading the spec matrix...</div>
      ) : mcusError ? (
        <MatrixError error={mcusError} onRetry={() => mcus.refetch()} />
      ) : (
        <MinimalMcuList rows={rows} />
      )}
    </PageFrame>
  );
}

// The page self-heading (the rail carries the active-surface highlight; the content states its
// own name + a quiet live readout, matching the app's other page shells).
function PageFrame({
  children,
  status,
  families,
}: {
  children: React.ReactNode;
  status?: number;
  families?: number;
}) {
  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-y-auto px-[30px] pt-[22px]">
      <header className="mb-5 flex items-baseline gap-3">
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

// The honest "index not built" call to action, driven by the build job's live progress (mirrors
// the RescanSection running/done/error flow). On success it re-queries the STM surface so the
// gate clears to the real matrix.
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
    <div className="flex flex-1 items-center justify-center py-10">
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
            <p className="text-xs text-t3">
              {build.progress?.message ?? "Starting the build..."}
            </p>
          </div>
        ) : null}

        {build.status === "error" ? (
          <p className="mb-4 text-sm text-err" data-testid="stm-build-error">
            {build.error}
          </p>
        ) : null}

        <Button
          variant="accent"
          onClick={() => build.start()}
          disabled={running}
        >
          {running
            ? "Building..."
            : build.status === "error"
              ? "Try Again"
              : "Build the Index"}
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

// The tracer's minimal render: one row per MCU by its real MPN (never the ref_name wildcard).
// 04-02 replaces this with the virtualized, faceted SpecMatrixTable.
function MinimalMcuList({ rows }: { rows: McuSpecRow[] }) {
  if (rows.length === 0) {
    return (
      <div className="py-16 text-center text-sm text-t3">
        No MCUs match the current scope.
      </div>
    );
  }
  return (
    <div className="flex flex-col gap-0.5" data-testid="stm-mcu-list">
      {rows.map((row) => (
        <div
          key={row.part}
          className="flex items-center gap-4 rounded-control px-3 py-2 hover:bg-[var(--c-hover)]"
        >
          <span className="tnum min-w-0 flex-1 truncate font-mono text-sm font-semibold text-t1">
            {row.mpn_example}
          </span>
          <span className="w-20 flex-none font-mono text-xs text-t2">{row.core}</span>
          <span className="w-20 flex-none font-mono text-xs text-t2">{row.series}</span>
          <span className="w-28 flex-none font-mono text-xs text-t3">{row.package}</span>
        </div>
      ))}
    </div>
  );
}
