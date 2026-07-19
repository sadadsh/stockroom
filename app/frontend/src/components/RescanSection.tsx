/**
 * Procurement Rescan, a Settings section (Phase-1b-3). Refreshes every part's price, stock
 * and lifecycle status from the free distributor APIs (Mouser + DigiKey) in one incremental
 * background job, with a live done/total progress bar and a running updated/unchanged/no-data/
 * failed tally, then an honest terminal summary (including any paused provider).
 *
 * Placement: Settings, not the Components picker column. That column has no header band by
 * design (rail | list | detail, each self-heading - see ComponentsPage) and is already tight
 * with Add Parts plus the search/facet Finder; cramming a trigger, a live progress bar and a
 * result summary in there would fight that layout. Settings already hosts every other
 * library-wide maintenance surface in the same shape - Library Health right above this one
 * scans/repairs the whole library and reports what happened the same way this reports a
 * rescan, so this section is its natural sibling.
 */
import { useState } from "react";
import { useRescanState } from "../api/queries";
import { useRescan, type RescanTally } from "../lib/useRescan";
import type { RescanStateResponse, RescanSummary } from "../api/types";
import { useToast } from "../lib/toast";
import { Badge, Button, Card, Dot, Eyebrow } from "./primitives";
import { RefreshIcon } from "./icons";

// ISO 8601 -> a compact local date/time; fall back to the raw string if it does not parse
// (never show "Invalid Date").
function formatDate(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

function countOf(counts: Record<string, number>, key: string): number {
  return counts[key] ?? 0;
}

// The idle-state "last refreshed" line, derived from GET /rescan/state (the last-known
// outcome per part, uncommitted and per-machine). checked_at sorts lexically (UTC ISO-8601),
// so the last entry after a plain string sort is the most recent check.
function lastChecked(data: RescanStateResponse): { checkedAt: string | null; total: number } {
  const entries = Object.values(data.parts);
  if (entries.length === 0) return { checkedAt: null, total: 0 };
  const sorted = entries.map((e) => e.checked_at).sort();
  const checkedAt = sorted[sorted.length - 1] ?? null;
  return { checkedAt, total: entries.length };
}

export function RescanSection() {
  const state = useRescanState();
  const rescan = useRescan();
  const { toast } = useToast();
  const [force, setForce] = useState(false);

  const busy = rescan.status === "running";

  async function onTrigger() {
    try {
      const result = await rescan.start(force);
      if (result?.already_running) {
        toast("A rescan was already running. Showing its live progress.", "neutral");
      }
    } catch (err) {
      toast(err instanceof Error ? err.message : "Could not start the rescan.", "err");
    }
  }

  return (
    <section className="mb-7">
      <Eyebrow className="mb-2">Procurement Rescan</Eyebrow>
      <p className="mb-2.5 text-xs text-t3">
        Refresh every part&rsquo;s price, stock and lifecycle status from Mouser and DigiKey.
        Parts checked recently are skipped unless you force a full pass.
      </p>
      <Card className="px-4 py-3.5">
        {rescan.status === "running" ? (
          <RunningBody
            tally={rescan.tally}
            currentPartId={rescan.currentPartId}
            startMessage={rescan.startMessage}
          />
        ) : rescan.status === "done" && rescan.summary ? (
          <DoneBody summary={rescan.summary} />
        ) : state.isLoading ? (
          <p className="py-1 text-sm text-t3">Reading the last rescan...</p>
        ) : state.isError ? (
          <p className="py-1 text-sm text-err">Could not read the last rescan.</p>
        ) : state.data ? (
          <IdleBody data={state.data} />
        ) : null}

        {rescan.status === "error" ? (
          <p className="mt-3 text-sm text-err" data-testid="rescan-error">
            {rescan.error}
          </p>
        ) : null}

        <div className="mt-3.5 flex flex-wrap items-center gap-3">
          <Button variant="accent" onClick={onTrigger} disabled={busy} icon={<RefreshIcon className="h-3.5 w-3.5" />}>
            {busy
              ? "Refreshing..."
              : rescan.status === "done" || rescan.status === "error"
                ? "Refresh Again"
                : "Refresh Prices & Stock"}
          </Button>
          <label className="flex cursor-pointer select-none items-center gap-2 text-sm text-t2">
            <span
              className={
                "flex h-[17px] w-[17px] flex-none items-center justify-center rounded-[5px] border-[1.5px] text-[11px] " +
                (force ? "border-acc bg-acc text-acc-on" : "border-line2 text-transparent")
              }
            >
              {"✓"}
            </span>
            <input
              type="checkbox"
              className="sr-only"
              checked={force}
              disabled={busy}
              onChange={(e) => setForce(e.target.checked)}
            />
            Force Full Rescan
          </label>
        </div>
      </Card>
    </section>
  );
}

function IdleBody({ data }: { data: RescanStateResponse }) {
  const { checkedAt, total } = lastChecked(data);
  if (total === 0) {
    return (
      <div className="flex items-center gap-2.5 py-1" data-testid="rescan-never-run">
        <Dot tone="neutral" />
        <span className="text-sm text-t2">This library has never been rescanned.</span>
      </div>
    );
  }
  const failed = countOf(data.counts, "failed");
  return (
    <div className="flex flex-col gap-2.5" data-testid="rescan-last-summary">
      <div className="flex items-center gap-2.5">
        <Dot tone={failed > 0 ? "warn" : "ok"} />
        <span className="text-sm text-t2">
          Last refreshed <span className="tnum font-mono text-t1">{total}</span>{" "}
          {total === 1 ? "part" : "parts"}
          {checkedAt ? ` · ${formatDate(checkedAt)}` : ""}
        </span>
      </div>
      <TallyRow
        updated={countOf(data.counts, "updated")}
        unchanged={countOf(data.counts, "unchanged")}
        noData={countOf(data.counts, "no_data")}
        failed={failed}
      />
    </div>
  );
}

function RunningBody({
  tally,
  currentPartId,
  startMessage,
}: {
  tally: RescanTally;
  currentPartId: string | null;
  startMessage: string | null;
}) {
  // Distinguish "no event has landed yet" (the brief gap between the POST resolving and the
  // job's first progress event) from "the job reported zero parts to refresh" (a real,
  // honest outcome for an incremental rescan when every part is already fresh): only the
  // latter has actually heard from the job.
  const heard = tally.total > 0 || startMessage !== null || currentPartId !== null;
  const pct = tally.total > 0 ? Math.min(100, Math.round((tally.done / tally.total) * 100)) : 0;
  return (
    <div className="flex flex-col gap-2.5" data-testid="rescan-running">
      <div className="h-1.5 w-full overflow-hidden rounded-full bg-raise2">
        <div
          className="h-full rounded-full bg-acc transition-[width]"
          style={{ width: `${pct}%` }}
        />
      </div>
      <div className="text-xs text-t3">
        {!heard ? (
          "Starting the rescan..."
        ) : tally.total === 0 ? (
          "Every part was checked recently. Nothing to refresh."
        ) : (
          <>
            <span className="tnum font-mono text-t1">{tally.done}</span> of{" "}
            <span className="tnum font-mono text-t1">{tally.total}</span> parts checked
            {currentPartId ? <span> · {currentPartId}</span> : null}
          </>
        )}
      </div>
      <TallyRow
        updated={tally.updated}
        unchanged={tally.unchanged}
        noData={tally.no_data}
        failed={tally.failed}
      />
    </div>
  );
}

function DoneBody({ summary }: { summary: RescanSummary }) {
  const headline =
    summary.failed > 0
      ? "Refreshed with some failures."
      : summary.total === 0
        ? "Every part was already current."
        : "Refresh complete.";
  return (
    <div className="flex flex-col gap-2.5" data-testid="rescan-done">
      <div className="flex items-center gap-2.5">
        <Dot tone={summary.failed > 0 ? "warn" : "ok"} />
        <span className="text-sm font-medium text-t1">{headline}</span>
      </div>
      <p className="text-xs text-t3">{summary.message}</p>
      <TallyRow
        updated={summary.updated}
        unchanged={summary.unchanged}
        noData={summary.no_data}
        failed={summary.failed}
      />
      {summary.paused_providers.length > 0 ? (
        <div
          className="flex flex-col gap-1 rounded-control border border-line2 bg-raise2 p-3"
          data-testid="rescan-paused"
        >
          <div className="flex items-center gap-2">
            <Badge tone="warn">Paused</Badge>
            <span className="text-sm text-t1">{summary.paused_providers.join(", ")}</span>
          </div>
          <p className="text-xs text-t3">
            {summary.paused_providers.length === 1 ? "This provider" : "These providers"} hit a
            quota or authorization issue partway through and were skipped for the rest of this
            run. Run the rescan again later to pick up where it left off.
          </p>
        </div>
      ) : null}
    </div>
  );
}

function TallyRow({
  updated,
  unchanged,
  noData,
  failed,
}: {
  updated: number;
  unchanged: number;
  noData: number;
  failed: number;
}) {
  return (
    <div className="flex flex-wrap items-center gap-2" data-testid="rescan-tally">
      <Badge tone={updated > 0 ? "ok" : "neutral"}>{updated} Updated</Badge>
      <Badge tone="neutral">{unchanged} Unchanged</Badge>
      <Badge tone="neutral">{noData} No Data</Badge>
      <Badge tone={failed > 0 ? "err" : "neutral"}>{failed} Failed</Badge>
    </div>
  );
}
