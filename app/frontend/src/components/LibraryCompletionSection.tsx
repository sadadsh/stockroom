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
import { Text, useCopyFormatter, useText } from "../lib/copy";
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
  // A toast is written from inside a callback, where a hook cannot run, so every sentence one can
  // carry is resolved here during render. The counted form gets one id per number agreement, so a
  // rewording owns the whole sentence rather than a noun stitched onto a number.
  const runFailed = useText("library.completion.toast-run-failed", "The run failed.");
  const durableFinished = useText(
    "library.completion.toast-durable-finished",
    "The durable completion run finished. Coverage was refreshed.",
  );
  const durableFailed = useText(
    "library.completion.toast-durable-failed",
    "The durable run failed. Rerun is available without repeating completed work.",
  );
  const durableCancelled = useText(
    "library.completion.toast-durable-cancelled",
    "The durable run was cancelled.",
  );
  const filedOne = useCopyFormatter(
    "library.completion.toast-filed-one",
    "Filed files for {count} component.",
  );
  const filedMany = useCopyFormatter(
    "library.completion.toast-filed-many",
    "Filed files for {count} components.",
  );
  const filedNothing = useText(
    "library.completion.toast-filed-nothing",
    "Nothing new could be filed.",
  );

  useEffect(() => {
    void reconnectCompletion();
  }, []);

  async function onRun() {
    const final = await startCompletion({});
    if (final.status === "error") {
      toast(final.error ?? runFailed, "err");
      return;
    }
    if (final.transport === "durable") {
      if (final.status === "done") {
        toast(durableFinished, "ok");
        coverage.refetch();
      } else if (final.status === "failed") {
        toast(durableFailed, "err");
      } else if (final.status === "cancelled") {
        toast(durableCancelled, "neutral");
        coverage.refetch();
      }
      return;
    }
    const counts = final.result?.counts ?? {};
    const filled = (counts.completed ?? 0) + (counts.improved ?? 0);
    const filedMessage = filled
      ? (filled === 1 ? filedOne : filedMany)({ count: filled })
      : filedNothing;
    toast(filedMessage, filled ? "ok" : "neutral");
    coverage.refetch();
  }

  return (
    <>
      {coverage.isLoading ? (
        <p className="py-1 text-sm text-t3">
          <Text id="library.completion.loading">Counting what the components have...</Text>
        </p>
      ) : coverage.isError ? (
        <p className="py-1 text-sm text-err-text">
          <Text id="library.completion.error">Could not read the catalog.</Text>
        </p>
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
        <p className="mt-3 text-sm text-err-text">{run.error}</p>
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
  // The two counted sentences get one id per number agreement, so a rewording owns the whole
  // sentence rather than a noun stitched onto a number.
  const gapOne = useCopyFormatter(
    "library.completion.gap-one",
    "{count} component has a gap a source ladder can attempt, {estimate}. It reuses validated evidence and works the eligible sources in order, opening each provider page in turn. Stopping and resuming repeats no settled work.",
  );
  const gapMany = useCopyFormatter(
    "library.completion.gap-many",
    "{count} components have gaps a source ladder can attempt, {estimate}. It reuses validated evidence and works the eligible sources in order, opening each provider page in turn. Stopping and resuming repeats no settled work.",
  );
  const unsourcedOne = useCopyFormatter(
    "library.completion.unsourced-one",
    "{count} component needs a file that no eligible source can provide so far.",
  );
  const unsourcedMany = useCopyFormatter(
    "library.completion.unsourced-many",
    "{count} components need files that no eligible source can provide so far.",
  );
  // The count keeps its own emphasis here, so the sentence begins after it rather than carrying it.
  const assistanceOne = useText(
    "library.completion.assistance-one",
    "component has a gap that needs one Get Files run. Stockroom opens the provider page for each one; a person signs in where the provider asks, chooses the needed formats and downloads them, and Stockroom captures and validates each file before moving to the next source.",
  );
  const assistanceMany = useText(
    "library.completion.assistance-many",
    "components have gaps that need one Get Files run. Stockroom opens the provider page for each one; a person signs in where the provider asks, chooses the needed formats and downloads them, and Stockroom captures and validates each file before moving to the next source.",
  );

  return (
    <div className="flex flex-col gap-4">
      <p className="text-base text-t2">
        {total === 0 ? (
          <Text id="library.completion.no-components">
            The catalog has no components so far.
          </Text>
        ) : allDone ? (
          <Text id="library.completion.all-complete" values={{ total }}>
            {"All {total} components hold each needed file."}
          </Text>
        ) : (
          <>
            <span className="tnum font-medium text-t1">{complete}</span> of{" "}
            <span className="tnum">{total}</span>{" "}
            <Text id="library.completion.have-every-file">components hold each needed file.</Text>
          </>
        )}
      </p>

      <CoverageMatrix data={data} />

      <div className="flex flex-wrap items-center gap-3 border-t border-line pt-3">
        {/* Enabled whenever ANY remaining gap is reachable by a registered source. A library
            whose last gaps all need a provider route still has work for this button: the run
            settles what it can and reports, per part, which provider needs a person - which is
            the only way that list exists at all. */}
        <Button
          variant="accent"
          onClick={onRun}
          disabled={running || (needsFiles === 0 && needsAssistance === 0)}
        >
          {running ? (
            <Text id="library.completion.fill-running">Filling Gaps</Text>
          ) : (
            <Text id="library.completion.fill">Fill Supported CAD Gaps</Text>
          )}
        </Button>
        <p className="text-sm text-t2">
          {needsFiles > 0 ? (
            (needsFiles === 1 ? gapOne : gapMany)({
              count: needsFiles,
              estimate: estimate(needsFiles),
            })
          ) : total === 0 ? (
            <Text id="library.completion.add-first">Add a component first.</Text>
          ) : needsAssistance > 0 ? (
            <Text id="library.completion.assistance-only">
              Each remaining gap needs a provider route. The run still settles what it can and then
              names the component and provider for each one that needs a person.
            </Text>
          ) : (
            <Text id="library.completion.nothing-reachable">
              No registered source can provide what is still missing here.
            </Text>
          )}
        </p>
      </div>

      {needsAssistance > 0 ? (
        <p className="border-l-2 border-acc pl-3 text-sm text-t2">
          <span className="tnum text-t1">{needsAssistance}</span>{" "}
          {needsAssistance === 1 ? assistanceOne : assistanceMany}
        </p>
      ) : null}

      {unsourced > 0 ? (
        <p className="tnum border-l-2 border-line pl-3 text-sm text-t2">
          {(unsourced === 1 ? unsourcedOne : unsourcedMany)({ count: unsourced })}
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
          <Text id="library.completion.matrix-caption">Components holding each file, per EDA tool and asset kind</Text>
        </caption>
        <thead>
          <tr>
            <th
              scope="col"
              className="w-[7rem] pb-2 text-left ui-table-header"
            >
              <Text id="library.completion.column-tool">Tool</Text>
            </th>
            {KINDS.map((kind) => (
              <th
                key={kind.key}
                scope="col"
                className="pb-2 text-left ui-table-header"
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
    return (
      <span className="text-t3">
        <Text id="library.completion.cell-not-applicable">Not applicable</Text>
      </span>
    );
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
          <Text id="library.completion.cell-provider">Provider</Text>
        </Badge>
      ) : !reachable ? (
        <Badge tone="neutral" size="sm">
          <Text id="library.completion.cell-no-source">No Source</Text>
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
        <p className="text-sm text-t2">
          {run.error ?? (
            <Text id="library.completion.durable-connecting">
              Connecting to the durable run...
            </Text>
          )}
        </p>
        {run.error ? (
          <Button small onClick={() => void reconnectCompletion()}>
            <Text id="library.completion.durable-reconnect">Reconnect</Text>
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
          <Badge tone="neutral">
            <Text id="library.completion.durable-badge">Durable</Text>
          </Badge>
          <span className="text-sm text-t2">
            <span className="tnum">{settled}</span>
            <span className="text-t3">
              {" "}
              <Text id="library.completion.durable-settled" values={{ total: batch.total_items }}>
                {"of {total} settled"}
              </Text>
            </span>
          </span>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {batch.actions.can_pause ? (
            <Button small onClick={() => void pauseCompletion()} disabled={pending !== null}>
              {pending === "pause" ? (
                <Text id="library.completion.durable-pause-pending">Pausing</Text>
              ) : (
                <Text id="library.completion.durable-pause">Pause</Text>
              )}
            </Button>
          ) : null}
          {batch.actions.can_resume ? (
            <Button small onClick={() => void resumeCompletion()} disabled={pending !== null}>
              {pending === "resume" ? (
                <Text id="library.completion.durable-resume-pending">Resuming</Text>
              ) : (
                <Text id="library.completion.durable-resume">Resume</Text>
              )}
            </Button>
          ) : null}
          {batch.actions.can_retry ? (
            <Button small onClick={() => void retryCompletion()} disabled={pending !== null}>
              {pending === "retry" ? (
                <Text id="library.completion.durable-retry-pending">Rerunning</Text>
              ) : (
                <Text id="library.completion.durable-retry">Rerun</Text>
              )}
            </Button>
          ) : null}
          {batch.actions.can_cancel ? (
            <Button
              small
              variant="ghost-danger"
              onClick={() => void cancelCompletion()}
              disabled={pending !== null}
            >
              {pending === "cancel" ? (
                <Text id="library.completion.durable-cancel-pending">Cancelling</Text>
              ) : (
                <Text id="library.completion.durable-cancel">Cancel</Text>
              )}
            </Button>
          ) : null}
          {run.status === "error" ? (
            <Button small onClick={() => void reconnectCompletion()}>
              <Text id="library.completion.durable-reconnect-error">Reconnect</Text>
            </Button>
          ) : null}
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        {completed > 0 ? (
          <Badge tone="ok">
            <Text id="library.completion.durable-completed" values={{ count: completed }}>
              {"{count} Completed"}
            </Text>
          </Badge>
        ) : null}
        {failed > 0 ? (
          <Badge tone="err">
            <Text id="library.completion.durable-failed" values={{ count: failed }}>
              {"{count} Failed"}
            </Text>
          </Badge>
        ) : null}
        {blocked > 0 ? (
          <Badge tone="warn">
            <Text id="library.completion.durable-blocked" values={{ count: blocked }}>
              {"{count} Blocked"}
            </Text>
          </Badge>
        ) : null}
        {cancelled > 0 ? (
          <Badge tone="neutral">
            <Text id="library.completion.durable-cancelled-count" values={{ count: cancelled }}>
              {"{count} Cancelled"}
            </Text>
          </Badge>
        ) : null}
      </div>

      {batch.status === "completed" ? (
        <p className="text-sm text-t3">
          The durable workflow completed. Library coverage is read again from filed component facts;
          this status does not infer which files changed.
        </p>
      ) : batch.status === "failed" ? (
        <p className="text-sm text-t3">
          <Text id="library.completion.durable-failed-note">Rerun requeues just the failed stages. Completed stages and their terminal evidence are preserved.</Text>
        </p>
      ) : batch.status === "blocked" ? (
        <p className="text-sm text-t3">
          Work is waiting on a durable exception decision; unrelated items can still advance.
        </p>
      ) : null}

      {run.error ? <p className="text-sm text-err-text">{run.error}</p> : null}
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
          <Badge tone="neutral">
            <Text id="library.completion.live-transport">Compatibility · 1,000 Max</Text>
          </Badge>
          <p className="text-sm text-t2">
            {frame ? (
              <>
                <span className="tnum">{done}</span>
                {frame.total ? <span className="text-t3"> of {frame.total}</span> : null}
                <span className="text-t3">
                  {" "}
                  <Text id="library.completion.live-working-on">filed, working on</Text>{" "}
                </span>
                <span className="font-mono text-xs text-t1">{frame.mpn || frame.part_id}</span>
              </>
            ) : (
              <Text id="library.completion.live-starting">Starting...</Text>
            )}
          </p>
        </div>
        <Button small onClick={() => void stopCompletion()} disabled={run.stopping}>
          {run.stopping ? (
            <Text id="library.completion.live-stop-pending">Stopping</Text>
          ) : (
            <Text id="library.completion.live-stop">Stop</Text>
          )}
        </Button>
      </div>
      {run.live.processed > 0 ? (
        <div data-testid="completion-live-summary" className="flex flex-wrap items-center gap-2">
          <Badge tone="neutral">
            <Text id="library.completion.live-processed" values={{ count: run.live.processed }}>
              {"{count} Processed"}
            </Text>
          </Badge>
          {liveFilled > 0 ? (
            <Badge tone="ok">
              <Text id="library.completion.live-filed" values={{ count: liveFilled }}>
                {"{count} Filed"}
              </Text>
            </Badge>
          ) : null}
          {run.live.retained > 0 ? (
            <Badge tone="neutral">
              <Text id="library.completion.live-retained" values={{ count: run.live.retained }}>
                {"{count} Additional Retained"}
              </Text>
            </Badge>
          ) : null}
          {liveDeferred > 0 ? (
            <Badge tone="warn">
              <Text id="library.completion.live-deferred" values={{ count: liveDeferred }}>
                {"{count} To Rerun"}
              </Text>
            </Badge>
          ) : null}
          {liveStuck > 0 ? (
            <Badge tone="neutral">
              <Text id="library.completion.live-stuck" values={{ count: liveStuck }}>
                {"{count} No Source"}
              </Text>
            </Badge>
          ) : null}
        </div>
      ) : null}
      {run.log.length ? (
        <ul className="max-h-40 overflow-y-auto text-xs">
          {/* One entry per part in the run, so the part IS the row's identity. The position was
              not: the log grows while the run is live and the list is sliced to the first 40. */}
          {run.log.slice(0, 40).map((entry) => (
            <li
              key={entry.part_id}
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
  // Resolved before the early return below, and before the row loop, because the two sentences a
  // row can carry are written inside a `.map()` callback where a hook cannot run.
  const notesAndRemaining = useCopyFormatter(
    "library.completion.item-notes-remaining",
    "{notes}. Still needs {remaining}",
  );
  const remainingOnly = useCopyFormatter(
    "library.completion.item-remaining",
    "still needs {remaining}",
  );
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
        <Badge tone={filled ? "ok" : "neutral"}>
          <Text id="library.completion.report-filed" values={{ count: filled }}>
            {"{count} Filed"}
          </Text>
        </Badge>
        {retained > 0 ? (
          <Badge tone="neutral">
            <Text id="library.completion.report-retained" values={{ count: retained }}>
              {"{count} Additional Retained"}
            </Text>
          </Badge>
        ) : null}
        {deferred > 0 ? (
          <Badge tone="warn">
            <Text id="library.completion.report-deferred" values={{ count: deferred }}>
              {"{count} To Rerun"}
            </Text>
          </Badge>
        ) : null}
        {stuck > 0 ? (
          <Badge tone="neutral">
            <Text id="library.completion.report-stuck" values={{ count: stuck }}>
              {"{count} No Source"}
            </Text>
          </Badge>
        ) : null}
      </div>
      {result.stopped ? (
        <p className="text-sm text-t2">
          {result.stop_reason ? (
            result.stop_reason
          ) : (
            <Text id="library.completion.stopped">
              Stopped. Run it again to resume from where it left off.
            </Text>
          )}
        </p>
      ) : null}
      {deferred > 0 && !result.stop_reason ? (
        <p className="text-sm text-t3">
          <Text id="library.completion.deferred-note">
            The parts catalogue limits how fast it will answer. Run this again later to pick up the
            ones it skipped.
          </Text>
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
                    ? notesAndRemaining({
                        notes: item.notes.join("; "),
                        remaining: item.remaining.map((r) => KIND_WORD[r] ?? r).join(", "),
                      })
                    : remainingOnly({
                        remaining: item.remaining.map((r) => KIND_WORD[r] ?? r).join(", "),
                      })}
              </span>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}
