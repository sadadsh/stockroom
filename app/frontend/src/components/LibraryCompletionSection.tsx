/**
 * Library Completion, a Settings section: "is my library complete?", and "make it complete".
 *
 * Both halves were things only a script outside the app could do, which by the owner's standing
 * rule (*"everything u do manually the app should do by itself"*) made them missing features.
 *
 * THE SIGNATURE ELEMENT IS THE COVERAGE MATRIX, and the choice is deliberate. The obvious design
 * is one big "92 of 158" number over a progress bar, which is the answer this page would give for
 * any subject and which hides the thing that actually matters: completeness is not one number, it
 * is a grid of EDA tool x asset kind. A matrix shows a whole EMPTY ALTIUM ROW at a glance, which
 * is the truth the owner needs and a single percentage would average away. It is also generated
 * from the requirement keys the backend sends, so registering an Altium source later grows the
 * matrix by itself rather than needing a new component.
 *
 * The honesty rules this surface follows, because a completion report is exactly the kind of
 * thing that quietly starts lying:
 *  - A part nothing can currently source is counted SEPARATELY from work a run can do, so the
 *    action never promises parts it cannot reach.
 *  - `deferred` (the catalogue rate-limited us) is shown apart from `unchanged` (nothing can help
 *    this part). One says try again, the other says do not bother, and merging them is a lie.
 *  - The run's cost is stated up front rather than discovered, because at the measured catalogue
 *    pace it is roughly eight parts a minute.
 */
import { useEffect } from "react";
import { useLibraryCoverage } from "../api/queries";
import type { CompletionItem, LibraryCoverage } from "../api/types";
import { CompletionWorklist } from "./CompletionWorklist";
import {
  cancelCompletion,
  pauseCompletion,
  reconnectCompletion,
  resumeCompletion,
  retryCompletion,
  startCompletion,
  stopCompletion,
  useCompletionState,
} from "../lib/completionStore";
import { useToast } from "../lib/toast";
import { Badge, Button, Dot } from "./primitives";

// The matrix axes, read off the requirement vocabulary the backend speaks (`<tool>_<kind>`).
// Listed here rather than derived from the data so the grid keeps a stable shape when a column
// happens to be fully satisfied -- a column that vanishes when it reaches 100% is a grid that
// silently changes meaning.
const TOOLS: { key: string; label: string }[] = [
  { key: "kicad", label: "KiCad" },
  { key: "altium", label: "Altium" },
];
const KINDS: { key: string; label: string }[] = [
  { key: "symbol", label: "Symbol" },
  { key: "footprint", label: "Footprint" },
  { key: "model", label: "3D Model" },
];

// MEASURED end to end on the owner's real 158-part library, 2026-07-27: a 68-part run filed its
// first part at 22:54:52 and its last at 23:04:32, so 68 parts in 9.7 minutes = 7.0 a minute. The
// limiter's 8-a-minute cap is the binding constraint, as designed, and real throughput sits just
// under it. Stated to the user rather than hidden, because at this rate 10,000 parts is a day.
const PARTS_PER_MINUTE = 7;

function estimate(parts: number): string {
  if (parts <= 0) return "";
  const minutes = Math.ceil(parts / PARTS_PER_MINUTE);
  if (minutes < 60) return `about ${minutes} ${minutes === 1 ? "minute" : "minutes"}`;
  const hours = Math.round((minutes / 60) * 10) / 10;
  return `about ${hours} ${hours === 1 ? "hour" : "hours"}`;
}

export function LibraryCompletionSection() {
  const coverage = useLibraryCoverage();
  const run = useCompletionState();
  const { toast } = useToast();

  useEffect(() => {
    void reconnectCompletion();
  }, []);

  async function onRun() {
    const final = await startCompletion({});
    if (final.status === "error") {
      toast(final.error ?? "The run failed.", "err");
      return;
    }
    if (final.transport === "durable") {
      if (final.status === "done") {
        toast("The durable completion run finished. Coverage was refreshed.", "ok");
        coverage.refetch();
      } else if (final.status === "failed") {
        toast(
          "The durable run failed. Retry is available without repeating completed work.",
          "err",
        );
      } else if (final.status === "cancelled") {
        toast("The durable run was cancelled.", "neutral");
        coverage.refetch();
      }
      return;
    }
    const counts = final.result?.counts ?? {};
    const filled = (counts.completed ?? 0) + (counts.improved ?? 0);
    toast(
      filled
        ? `Filed files for ${filled} ${filled === 1 ? "component" : "components"}.`
        : "Nothing new could be filed.",
      filled ? "ok" : "neutral",
    );
    coverage.refetch();
  }

  return (
    <>
      {coverage.isLoading ? (
        <p className="py-1 text-sm text-t3">Counting what your components have...</p>
      ) : coverage.isError ? (
        <p className="py-1 text-sm text-err">Could not read your library.</p>
      ) : coverage.data ? (
        <CoverageBody
          data={coverage.data}
          onRun={onRun}
          running={run.status === "running" || run.status === "paused" || run.status === "failed"}
        />
      ) : null}
      {run.transport === "durable" && run.batchId ? <DurableRun /> : null}
      {/* The same run, read as WORK: what it finished alone, and the short list it could not.
          Mounted with the batch rather than at its end, because each part's result is retained as
          that part settles - a person can start the first provider trip while the rest still run. */}
      {run.transport === "durable" && run.batchId ? (
        <CompletionWorklist batchId={run.batchId} live={run.status === "running"} />
      ) : null}
      {run.transport !== "durable" && run.status === "running" ? <LiveRun /> : null}
      {run.transport !== "durable" && run.status === "done" && run.result ? <RunReport /> : null}
      {run.transport !== "durable" && run.status === "error" && run.error ? (
        <p className="mt-3 text-sm text-err">{run.error}</p>
      ) : null}
    </>
  );
}

function CoverageBody({
  data,
  onRun,
  running,
}: {
  data: LibraryCoverage;
  onRun: () => void;
  running: boolean;
}) {
  const {
    total,
    complete,
    needs_files: needsFiles,
    needs_assistance: needsAssistance = 0,
    unsourced,
  } = data;
  const allDone = total > 0 && complete === total;

  return (
    <div className="flex flex-col gap-4">
      <p className="text-base text-t2">
        {total === 0 ? (
          "Your library has no components yet."
        ) : allDone ? (
          <>All {total} components have every file they need.</>
        ) : (
          <>
            <span className="tnum font-medium text-t1">{complete}</span> of{" "}
            <span className="tnum">{total}</span> components have every file they need.
          </>
        )}
      </p>

      <CoverageMatrix data={data} />

      <div className="flex flex-wrap items-center gap-3 border-t border-line pt-3">
        {/* Enabled whenever ANY remaining gap is reachable by either lane, not only by the
            automatic one. A library whose last gaps all need a provider route still has work for
            this button: the run settles what it can and reports, per part, which provider needs a
            person - which is the only way that list exists at all. */}
        <Button
          variant="accent"
          onClick={onRun}
          disabled={running || (needsFiles === 0 && needsAssistance === 0)}
        >
          {running ? "Filling Gaps" : "Fill Supported CAD Gaps"}
        </Button>
        <p className="text-sm text-t2">
          {needsFiles > 0 ? (
            <>
              {needsFiles} {needsFiles === 1 ? "component has a gap" : "components have gaps"} a
              source ladder can try, {estimate(needsFiles)}. It reuses verified evidence, ranks
              eligible sources, and retains fallbacks. You can stop it and resume without repeating
              settled work.
            </>
          ) : total === 0 ? (
            "Add a component first."
          ) : needsAssistance > 0 ? (
            <>
              Every remaining gap needs a provider route. The run still settles what it can and
              then names the component and provider for each one that needs you.
            </>
          ) : (
            "Nothing here can be filled automatically right now."
          )}
        </p>
      </div>

      {needsAssistance > 0 ? (
        <p className="border-l-2 border-acc pl-3 text-sm text-t2">
          <span className="tnum text-t1">{needsAssistance}</span>{" "}
          {needsAssistance === 1
            ? "component has a gap that needs"
            : "components have gaps that need"}{" "}
          one explicit Collect All Sources session. Stockroom reuses the provider session, captures
          and validates downloads, and advances through fallbacks; the visible window pauses only
          for a provider-required login, security check, or download choice.
        </p>
      ) : null}

      {unsourced > 0 ? (
        <p className="border-l-2 border-line pl-3 text-sm text-t2">
          <span className="tnum text-t2">{unsourced}</span>{" "}
          {unsourced === 1 ? "component needs a file" : "components need files"} that neither an
          automatic source nor a managed provider can supply yet.
        </p>
      ) : null}
    </div>
  );
}

/**
 * The signature: coverage as a grid of EDA tool against asset kind, each cell naming how many
 * components still lack that exact file. A cell is the smallest true unit of "complete", and
 * seeing an entire row at zero is what makes a missing tool obvious instead of averaged away.
 */
function CoverageMatrix({ data }: { data: LibraryCoverage }) {
  const {
    total,
    by_requirement: missing,
    can_provide: canProvide,
    assisted_can_provide: assistedCanProvide = [],
  } = data;
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[26rem] border-collapse text-sm">
        <caption className="sr-only">
          Components holding each file, by EDA tool and asset kind
        </caption>
        <thead>
          <tr>
            <th
              scope="col"
              className="w-[7rem] pb-2 text-left text-2xs font-medium uppercase tracking-wide text-t3"
            >
              Tool
            </th>
            {KINDS.map((kind) => (
              <th
                key={kind.key}
                scope="col"
                className="pb-2 text-left text-2xs font-medium uppercase tracking-wide text-t3"
              >
                {kind.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {TOOLS.map((tool) => (
            <tr key={tool.key} className="border-t border-line">
              <th scope="row" className="py-2 text-left text-sm font-medium text-t1">
                {tool.label}
              </th>
              {KINDS.map((kind) => (
                <td key={kind.key} className="py-2">
                  <Cell
                    total={total}
                    lacking={missing[`${tool.key}_${kind.key}`]}
                    sourced={canProvide.includes(`${tool.key}_${kind.key}`)}
                    assisted={assistedCanProvide.includes(`${tool.key}_${kind.key}`)}
                    requirement={`${tool.key}_${kind.key}`}
                  />
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/**
 * One cell. Three genuinely different states, and they must not look alike:
 *  - every component has it (ok),
 *  - some are missing it and a source can get them (warn, and a run will act on it),
 *  - some are missing it and a managed provider can get them (warn + Provider),
 *  - some are missing it and nothing can (neutral, honest, not presented as pending work).
 * A kind the tool cannot hold at all (an Altium 3D body lives inside its footprint binary, so
 * no requirement exists for it) renders as a dash rather than a misleading zero.
 */
function Cell({
  total,
  lacking,
  sourced,
  assisted,
  requirement,
}: {
  total: number;
  lacking: number | undefined;
  sourced: boolean;
  assisted: boolean;
  requirement: string;
}) {
  // No requirement for this pair at all: not a gap, not a score. Say nothing rather than "0".
  if (lacking === undefined && !NAMEABLE.has(requirement)) {
    return <span className="text-t3">Not applicable</span>;
  }
  const missing = lacking ?? 0;
  const have = Math.max(0, total - missing);
  if (missing === 0) {
    return (
      <span className="inline-flex items-center gap-1.5 text-t2">
        <Dot tone="ok" />
        <span className="tnum w-8 text-right">{have}</span>
        <span className="text-t3">of {total}</span>
      </span>
    );
  }
  const reachable = sourced || assisted;
  return (
    <span className="inline-flex items-center gap-1.5 text-t2">
      <Dot tone={reachable ? "warn" : "neutral"} />
      <span className="tnum w-8 text-right">{have}</span>
      <span className="text-t3">of {total}</span>
      {assisted && !sourced ? (
        <Badge tone="warn" size="sm">
          Provider
        </Badge>
      ) : !reachable ? (
        <Badge tone="neutral" size="sm">
          No Source
        </Badge>
      ) : null}
    </span>
  );
}

// The tool/kind pairs that are real requirements. Anything else is structurally impossible for
// that tool rather than merely absent, and the matrix says so instead of scoring it zero.
const NAMEABLE = new Set([
  "kicad_symbol",
  "kicad_footprint",
  "kicad_model",
  "altium_symbol",
  "altium_footprint",
]);

function DurableRun() {
  const run = useCompletionState();
  const batch = run.workflow;
  if (!batch) {
    return (
      <div className="mt-4 flex items-center justify-between gap-3 border-t border-line pt-3">
        <p className="text-sm text-t2">{run.error ?? "Connecting to the durable run..."}</p>
        {run.error ? (
          <Button small onClick={() => void reconnectCompletion()}>
            Reconnect
          </Button>
        ) : null}
      </div>
    );
  }

  const counts = batch.item_counts;
  const completed = counts.completed ?? 0;
  const failed = counts.failed ?? 0;
  const cancelled = counts.cancelled ?? 0;
  const blocked = counts.blocked ?? 0;
  const settled = completed + failed + cancelled;
  const cancelling = batch.cancellation?.state === "requested";
  const statusLabel = cancelling
    ? "Cancelling"
    : {
        queued: "Queued",
        running: "Running",
        blocked: "Blocked",
        paused: "Paused",
        completed: "Completed",
        failed: "Failed",
        cancelled: "Cancelled",
      }[batch.status];
  const statusTone =
    batch.status === "completed"
      ? "ok"
      : batch.status === "failed"
        ? "err"
        : batch.status === "paused" || batch.status === "blocked"
          ? "warn"
          : "neutral";
  const pending = run.controlPending;

  return (
    <div
      data-testid="completion-durable-run"
      className="mt-4 flex flex-col gap-2 border-t border-line pt-3"
    >
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap items-center gap-2">
          <Badge tone={statusTone}>{statusLabel}</Badge>
          <Badge tone="neutral">Durable</Badge>
          <span className="text-sm text-t2">
            <span className="tnum">{settled}</span>
            <span className="text-t3"> of {batch.total_items} settled</span>
          </span>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {batch.actions.can_pause ? (
            <Button small onClick={() => void pauseCompletion()} disabled={pending !== null}>
              {pending === "pause" ? "Pausing" : "Pause"}
            </Button>
          ) : null}
          {batch.actions.can_resume ? (
            <Button small onClick={() => void resumeCompletion()} disabled={pending !== null}>
              {pending === "resume" ? "Resuming" : "Resume"}
            </Button>
          ) : null}
          {batch.actions.can_retry ? (
            <Button small onClick={() => void retryCompletion()} disabled={pending !== null}>
              {pending === "retry" ? "Retrying" : "Retry"}
            </Button>
          ) : null}
          {batch.actions.can_cancel ? (
            <Button
              small
              variant="ghost-danger"
              onClick={() => void cancelCompletion()}
              disabled={pending !== null}
            >
              {pending === "cancel" ? "Cancelling" : "Cancel"}
            </Button>
          ) : null}
          {run.status === "error" ? (
            <Button small onClick={() => void reconnectCompletion()}>
              Reconnect
            </Button>
          ) : null}
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        {completed > 0 ? <Badge tone="ok">{completed} Completed</Badge> : null}
        {failed > 0 ? <Badge tone="err">{failed} Failed</Badge> : null}
        {blocked > 0 ? <Badge tone="warn">{blocked} Blocked</Badge> : null}
        {cancelled > 0 ? <Badge tone="neutral">{cancelled} Cancelled</Badge> : null}
      </div>

      {batch.status === "completed" ? (
        <p className="text-sm text-t3">
          The durable workflow completed. Library coverage is read again from filed component facts;
          this status does not infer which files changed.
        </p>
      ) : batch.status === "failed" ? (
        <p className="text-sm text-t3">
          Retry requeues only failed stages. Completed stages and their terminal evidence are
          preserved.
        </p>
      ) : batch.status === "blocked" ? (
        <p className="text-sm text-t3">
          Work is waiting on a durable exception decision; unrelated items can still advance.
        </p>
      ) : null}

      {run.error ? <p className="text-sm text-err">{run.error}</p> : null}
      {run.workflowLog.length ? (
        <ul className="max-h-40 overflow-y-auto text-xs">
          {run.workflowLog.slice(0, 40).map((event) => (
            <li
              key={event.sequence}
              className="flex items-center gap-2 border-t border-line py-1 first:border-t-0"
            >
              <span className="tnum w-14 shrink-0 text-t3">#{event.sequence}</span>
              <span className="truncate text-t2">{describeWorkflowEvent(event)}</span>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

function describeWorkflowEvent(event: {
  kind: string;
  details: Record<string, string | number>;
}): string {
  const eventName = event.kind
    .split("_")
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(" ");
  const stage = event.details.stage;
  return typeof stage === "string" ? `${eventName} · ${stage.replaceAll("_", " ")}` : eventName;
}

function LiveRun() {
  const run = useCompletionState();
  const frame = run.progress;
  const done = frame ? frame.done + 1 : 0;
  const liveFilled = (run.live.counts.completed ?? 0) + (run.live.counts.improved ?? 0);
  const liveDeferred = run.live.counts.deferred ?? 0;
  const liveStuck = (run.live.counts.unchanged ?? 0) + (run.live.counts.error ?? 0);
  return (
    <div className="mt-4 flex flex-col gap-2 border-t border-line pt-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap items-center gap-2">
          <Badge tone="neutral">Compatibility · 1,000 Max</Badge>
          <p className="text-sm text-t2">
            {frame ? (
              <>
                <span className="tnum">{done}</span>
                {frame.total ? <span className="text-t3"> of {frame.total}</span> : null}
                <span className="text-t3"> filed, working on </span>
                <span className="font-mono text-xs text-t1">{frame.mpn || frame.part_id}</span>
              </>
            ) : (
              "Starting..."
            )}
          </p>
        </div>
        <Button small onClick={() => void stopCompletion()} disabled={run.stopping}>
          {run.stopping ? "Stopping" : "Stop"}
        </Button>
      </div>
      {run.live.processed > 0 ? (
        <div data-testid="completion-live-summary" className="flex flex-wrap items-center gap-2">
          <Badge tone="neutral">{run.live.processed} Processed</Badge>
          {liveFilled > 0 ? <Badge tone="ok">{liveFilled} Filed</Badge> : null}
          {run.live.retained > 0 ? (
            <Badge tone="neutral">{run.live.retained} Supplementary Retained</Badge>
          ) : null}
          {liveDeferred > 0 ? <Badge tone="warn">{liveDeferred} To Retry</Badge> : null}
          {liveStuck > 0 ? <Badge tone="neutral">{liveStuck} No Source</Badge> : null}
        </div>
      ) : null}
      {run.log.length ? (
        <ul className="max-h-40 overflow-y-auto text-xs">
          {run.log.slice(0, 40).map((entry, i) => (
            <li
              key={`${entry.part_id}-${i}`}
              className="flex items-center gap-2 border-t border-line py-1 first:border-t-0"
            >
              <Dot tone={statusTone(entry.status)} />
              <span className="w-40 shrink-0 truncate font-mono text-t2">
                {entry.mpn || entry.part_id}
              </span>
              <span className="truncate text-t3">
                {describe(entry.status, entry.satisfied, entry.retained ?? 0)}
              </span>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

function statusTone(status: string): "ok" | "warn" | "err" | "neutral" {
  if (status === "completed" || status === "already-complete") return "ok";
  if (status === "improved" || status === "deferred") return "warn";
  if (status === "error") return "err";
  return "neutral";
}

// Names a row in the user's own vocabulary. "kicad_symbol" is how the system stores it; "symbol"
// is what the person asked for.
const KIND_WORD: Record<string, string> = {
  kicad_symbol: "symbol",
  kicad_footprint: "footprint",
  kicad_model: "3D model",
  altium_symbol: "Altium symbol",
  altium_footprint: "Altium footprint",
};

function describe(status: string, satisfied: string[], retained = 0): string {
  const got = satisfied.map((s) => KIND_WORD[s] ?? s);
  const retainedText = retained
    ? `retained ${retained} supplementary ${retained === 1 ? "file" : "files"}`
    : "";
  if (retainedText && !got.length) return `${retainedText}; library still incomplete`;
  switch (status) {
    case "completed":
      return got.length
        ? `filed ${got.join(", ")}${retainedText ? `; ${retainedText}` : ""}`
        : "already had everything";
    case "improved":
      return `filed ${got.join(", ")}, some still missing${
        retainedText ? `; ${retainedText}` : ""
      }`;
    case "already-complete":
      return "already had everything";
    case "deferred":
      return "the catalogue is busy, will retry on the next run";
    case "error":
      return "could not be read";
    default:
      return "no source could supply its files";
  }
}

function RunReport() {
  const { result } = useCompletionState();
  if (!result) return null;
  const counts = result.counts ?? {};
  const filled = (counts.completed ?? 0) + (counts.improved ?? 0);
  const deferred = counts.deferred ?? 0;
  const stuck = (counts.unchanged ?? 0) + (counts.error ?? 0);
  const retained = result.items.reduce((total, item) => total + (item.retained ?? 0), 0);
  // Only the parts a person can act on, plus provider-declined rows that now carry an exact
  // explanation. Anonymous "no source" rows stay collapsed so they cannot bury useful evidence.
  const actionable: CompletionItem[] = result.items.filter(
    (i) =>
      i.status === "improved" ||
      i.status === "error" ||
      (i.retained ?? 0) > 0 ||
      (i.remaining.length > 0 && (i.notes?.length ?? 0) > 0),
  );

  return (
    <div className="mt-4 flex flex-col gap-2 border-t border-line pt-3">
      <div className="flex flex-wrap items-center gap-2">
        <Badge tone={filled ? "ok" : "neutral"}>{filled} Filed</Badge>
        {retained > 0 ? <Badge tone="neutral">{retained} Supplementary Retained</Badge> : null}
        {deferred > 0 ? <Badge tone="warn">{deferred} To Retry</Badge> : null}
        {stuck > 0 ? <Badge tone="neutral">{stuck} No Source</Badge> : null}
      </div>
      {result.stopped ? (
        <p className="text-sm text-t2">
          {result.stop_reason
            ? result.stop_reason
            : "Stopped. Run it again to carry on from where it left off."}
        </p>
      ) : null}
      {deferred > 0 && !result.stop_reason ? (
        <p className="text-sm text-t3">
          The parts catalogue limits how fast it will answer. Run this again later to pick up the
          ones it skipped.
        </p>
      ) : null}
      {actionable.length ? (
        <ul className="max-h-40 overflow-y-auto text-xs">
          {actionable.slice(0, 40).map((item) => (
            <li
              key={item.part_id}
              className="flex items-center gap-2 border-t border-line py-1 first:border-t-0"
            >
              <Dot tone={statusTone(item.status)} />
              <span className="w-40 shrink-0 truncate font-mono text-t2">
                {item.mpn || item.part_id}
              </span>
              <span className="truncate text-t3">
                {item.status === "error"
                  ? item.error
                  : item.notes?.length
                    ? `${item.notes.join("; ")}. Still needs ${item.remaining
                        .map((r) => KIND_WORD[r] ?? r)
                        .join(", ")}`
                    : `still needs ${item.remaining.map((r) => KIND_WORD[r] ?? r).join(", ")}`}
              </span>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}
