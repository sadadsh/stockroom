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
import { lastChecked } from "./rescanState";
import { useToast } from "../lib/toast";
import { Text, useText } from "../lib/copy";
import { Badge, Button, Dot } from "./primitives";
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

export function RescanSection() {
  const state = useRescanState();
  const rescan = useRescan();
  const { toast } = useToast();
  const [force, setForce] = useState(false);
  // Resolved during render: a toast is written inside the callback below, where a hook cannot run.
  // The thrown error's own message is a backend diagnostic and stays as it arrived.
  const attached = useText(
    "library.rescan.toast-attached",
    "A rescan is now running. Showing its live progress.",
  );
  const startFailed = useText(
    "library.rescan.toast-start-failed",
    "Could not start the rescan.",
  );

  const busy = rescan.status === "running";

  async function onTrigger() {
    try {
      const result = await rescan.start(force);
      if (result?.already_running) {
        toast(attached, "neutral");
      }
    } catch (err) {
      toast(err instanceof Error ? err.message : startFailed, "err");
    }
  }

  return (
    <>
        {rescan.status === "running" ? (
          <RunningBody
            tally={rescan.tally}
            currentPartId={rescan.currentPartId}
            startMessage={rescan.startMessage}
          />
        ) : rescan.status === "done" && rescan.summary ? (
          <DoneBody summary={rescan.summary} />
        ) : state.isLoading ? (
          <p className="py-1 text-sm text-t3">
            <Text id="library.rescan.loading">Reading the last rescan...</Text>
          </p>
        ) : state.isError ? (
          <p className="py-1 text-sm text-err-text">
            <Text id="library.rescan.error">Could not read the last rescan.</Text>
          </p>
        ) : state.data ? (
          <IdleBody data={state.data} />
        ) : null}

        {rescan.status === "error" ? (
          <p className="mt-3 text-sm text-err-text" data-testid="rescan-error">
            {rescan.error}
          </p>
        ) : null}

        <div className="mt-3.5 flex flex-wrap items-center gap-3">
          <Button variant="accent" onClick={onTrigger} disabled={busy} icon={<RefreshIcon className="h-3.5 w-3.5" />} data-dev-id="settings.rescan-action">
            {busy ? (
              <Text id="library.rescan.action-running">Refreshing...</Text>
            ) : rescan.status === "done" || rescan.status === "error" ? (
              <Text id="library.rescan.action-again">Refresh Again</Text>
            ) : (
              <Text id="library.rescan.action">Refresh Prices &amp; Stock</Text>
            )}
          </Button>
          <label className="flex cursor-pointer select-none items-center gap-2 text-sm text-t2">
            <span
              className={
                "flex h-[17px] w-[17px] flex-none items-center justify-center rounded-control border-[1.5px] text-xs " +
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
            <Text id="library.rescan.force-label">Force Full Rescan</Text>
          </label>
        </div>
    </>
  );
}

function IdleBody({ data }: { data: RescanStateResponse }) {
  const { checkedAt, total } = lastChecked(data);
  if (total === 0) {
    return (
      <div className="flex items-center gap-2.5 py-1" data-testid="rescan-never-run">
        <Dot tone="neutral" />
        <span className="text-sm text-t2">
          <Text id="library.rescan.never-run">This catalog has never been rescanned.</Text>
        </span>
      </div>
    );
  }
  const failed = countOf(data.counts, "failed");
  return (
    <div className="flex flex-col gap-2.5" data-testid="rescan-last-summary">
      <div className="flex items-center gap-2.5">
        <Dot tone={failed > 0 ? "warn" : "ok"} />
        <span className="text-sm text-t2">
          <Text id="library.rescan.last-refreshed">Last refreshed</Text>{" "}
          <span className="tnum font-mono text-t1">{total}</span>{" "}
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
      <div className="h-1.5 w-full overflow-hidden bg-raise2">
        <div
          className="h-full bg-acc transition-[width]"
          style={{ width: `${pct}%` }}
        />
      </div>
      <div className="text-xs text-t3">
        {!heard ? (
          <Text id="library.rescan.progress-starting">Starting the rescan...</Text>
        ) : tally.total === 0 ? (
          <Text id="library.rescan.progress-none-due">
            Each part was checked in the recent past. Nothing to refresh.
          </Text>
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
  // One id per number agreement: the subject and its verb have to move together in a rewording.
  const pausedOne = useText(
    "library.rescan.paused-one",
    "This provider hit a quota or authorization issue during the run and was skipped for the rest of it. Run the rescan again later to pick up where it left off.",
  );
  const pausedMany = useText(
    "library.rescan.paused-many",
    "These providers hit a quota or authorization issue during the run and were skipped for the rest of it. Run the rescan again later to pick up where it left off.",
  );
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
            <Badge tone="warn">
              <Text id="library.rescan.paused">Paused</Text>
            </Badge>
            <span className="text-sm text-t1">{summary.paused_providers.join(", ")}</span>
          </div>
          <p className="text-xs text-t3">
            {summary.paused_providers.length === 1 ? pausedOne : pausedMany}
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
      <Badge tone={updated > 0 ? "ok" : "neutral"}>
        <Text id="library.rescan.tally-updated" values={{ count: updated }}>
          {"{count} Updated"}
        </Text>
      </Badge>
      <Badge tone="neutral">
        <Text id="library.rescan.tally-unchanged" values={{ count: unchanged }}>
          {"{count} Unchanged"}
        </Text>
      </Badge>
      <Badge tone="neutral">
        <Text id="library.rescan.tally-no-data" values={{ count: noData }}>
          {"{count} No Data"}
        </Text>
      </Badge>
      <Badge tone={failed > 0 ? "err" : "neutral"}>
        <Text id="library.rescan.tally-failed" values={{ count: failed }}>
          {"{count} Failed"}
        </Text>
      </Badge>
    </div>
  );
}
