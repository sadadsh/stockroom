/**
 * Presentation Data, a Settings section: WHICH RULES produced what you are looking at, and a
 * way to bring the whole library onto the current ones.
 *
 * The fact this surfaces is invisible everywhere else in the app and matters more than it
 * sounds. A part's name, description, category and normalized specs are COMPUTED from its stored
 * raw distributor payloads by a versioned ruleset. Improve those rules -- and 2026-07-27 did
 * exactly that, cutting Mouser's catalogue numbers off 13 of the owner's 158 descriptions -- and
 * every stored block is stale until something recomputes it. Two machines on different builds
 * then show DIFFERENT text for the same part from the same evidence, which is the owner's device
 * parity rule ("same update, same files, same info") broken in the least visible way possible.
 *
 * THE SIGNATURE ELEMENT IS THE STAMP LEDGER, and it is deliberately not a progress bar. "142 of
 * 158 current" averages away the one thing worth knowing: WHICH other rulesets are in play. A
 * part carrying a NEWER stamp than this build is a completely different problem from one
 * carrying an older stamp (that machine is behind, this one is not), and a part with no stamp at
 * all has never been derived. One row per stamp keeps those three apart; a percentage cannot.
 *
 * PRIOR ART considered, and what was REJECTED:
 *  - INTERNAL, and ADOPTED: `LibraryCompletionSection.tsx` is the same shape of problem (a
 *    read-only count over the library, plus one long-running write job) and this follows it
 *    deliberately -- same query/`useJob` split, same `Button`/`Badge`/`Dot` primitives, same
 *    "report from the job's own result" rule. A second settings section that behaved differently
 *    would be a trap for whoever debugs the second one.
 *  - REJECTED: the global `completionStore` (a module-level store outside React). It exists
 *    because a completion run is HOURS and must survive navigating away. A re-derive is local
 *    file work with no network in it -- measured at 158 parts in under a second -- so the store's
 *    whole justification is absent and `useJob` is the smaller correct tool.
 *  - REJECTED: a table library (TanStack Table and friends). Three columns of static data with no
 *    sorting, filtering, virtualization or selection is not a table problem; it is a `<table>`.
 *  - REJECTED: a progress bar / donut from a chart library, for the design reason above -- the
 *    per-stamp breakdown is the information, and a single ratio destroys it.
 *
 * The honesty rules it follows:
 *  - The running ruleset is named, not implied, so "current" has a referent.
 *  - Parts with no stored evidence are reported as SKIPPED, never counted as done. Recomputing
 *    them from nothing would blank a hand-added part, so the engine refuses and says so.
 *  - The action reports what it actually wrote, from the job's own result, never from the fact
 *    that it was started.
 */
import { useCallback, useState } from "react";
import { api } from "../api/client";
import { useLibraryDerivation } from "../api/queries";
import type { DerivationReport, LibraryDerivation } from "../api/types";
import { useJob } from "../lib/useJob";
import { useToast } from "../lib/toast";
import { Text } from "../lib/copy";
import { Badge, Button, Dot } from "./primitives";

// The empty stamp is a real state on disk, not a missing value: a record written before the
// derived block existed, or one whose derivation has never run.
const NEVER = "";

type Standing = "current" | "behind" | "ahead" | "never";

/**
 * What one stamp means relative to the ruleset this build runs.
 *
 * `ahead` is judged by a numeric read of the suffix, and that read is best-effort on purpose: a
 * stamp is an opaque label, so an unparseable one is reported as simply different rather than
 * being sorted into a version order it may not belong to.
 */
function standingOf(stamp: string, ruleset: string): Standing {
  if (stamp === ruleset) return "current";
  if (stamp === NEVER) return "never";
  const mine = Number(/@(\d+)$/.exec(ruleset)?.[1] ?? NaN);
  const theirs = Number(/@(\d+)$/.exec(stamp)?.[1] ?? NaN);
  if (Number.isFinite(mine) && Number.isFinite(theirs) && theirs > mine) return "ahead";
  return "behind";
}

const LABELS: Record<Standing, string> = {
  current: "Current",
  behind: "Behind",
  ahead: "From A Newer Build",
  never: "Never Derived",
};

const TONES: Record<Standing, "ok" | "warn" | "neutral"> = {
  current: "ok",
  behind: "warn",
  ahead: "neutral",
  never: "warn",
};

export function DerivationSection() {
  const derivation = useLibraryDerivation();
  const job = useJob<DerivationReport>();
  const { toast } = useToast();
  const [report, setReport] = useState<DerivationReport | null>(null);

  const onRebuild = useCallback(async () => {
    setReport(null);
    let ref: { job_id: string };
    try {
      ref = await api.rebuildDerivation();
    } catch (err) {
      toast(err instanceof Error ? err.message : "Could not start the rebuild.", "err");
      return;
    }
    // Report from what the job ACTUALLY returned, never from the fact that it was started.
    const finished = await job.run(ref.job_id);
    if (finished.status === "error") {
      toast(finished.error ?? "The rebuild failed.", "err");
      return;
    }
    const result = finished.result;
    if (!result) return;
    setReport(result);
    toast(
      result.rewritten
        ? `Recomputed ${result.rewritten} ${result.rewritten === 1 ? "component" : "components"}.`
        : "Every component was already current.",
      result.rewritten ? "ok" : "neutral",
    );
    derivation.refetch();
  }, [job, toast, derivation]);

  if (derivation.isLoading) {
    return (
      <p className="py-1 text-sm text-t3">
        <Text id="library.derivation.loading">Reading which rules built your components...</Text>
      </p>
    );
  }
  if (derivation.isError || !derivation.data) {
    return (
      <p className="py-1 text-sm text-err">
        <Text id="library.derivation.error">Could not read your library.</Text>
      </p>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      <Summary data={derivation.data} />
      <StampLedger data={derivation.data} />
      <div className="flex flex-wrap items-center gap-3">
        <Button
          variant="accent"
          onClick={onRebuild}
          disabled={job.status === "running" || derivation.data.stale === 0}
          data-dev-id="settings.derivation.rebuild"
        >
          {job.status === "running" ? "Recomputing" : "Recompute Presentation Data"}
        </Button>
        <p className="text-sm text-t2">
          {derivation.data.stale > 0
            ? "Lands as one change: every component moves, or none does. What you imported is only ever read."
            : "Every component was built by the rules this version runs."}
        </p>
      </div>
      {job.status === "running" && job.progress?.message ? (
        <p className="text-sm text-t2">{job.progress.message}</p>
      ) : null}
      {job.status === "error" && job.error ? (
        <p className="text-sm text-err">{job.error}</p>
      ) : null}
      {report ? <Report report={report} /> : null}
    </div>
  );
}

function Summary({ data }: { data: LibraryDerivation }) {
  const total = data.current + data.stale;
  if (total === 0)
    return (
      <p className="text-base text-t2">
        <Text id="library.derivation.empty">Your library has no components yet.</Text>
      </p>
    );
  // Three sentences, not one with a ratio in it. "162 of 162 were built by different rules" is
  // arithmetically true and reads as broken: a count whose numerator equals its denominator says
  // "all", so it has to SAY all. Same class of defect as the count-vs-noun mismatches `717ec2c`
  // put an AST gate over, and it was visible in the very first screenshot of this section.
  return (
    <p className="text-base text-t2">
      {data.stale === 0 ? (
        <>
          All <span className="tnum font-medium text-t1">{total}</span> components were built by{" "}
          <span className="font-medium text-t1">{data.ruleset}</span>, the rules this version runs.
        </>
      ) : data.current === 0 ? (
        <>
          None of the <span className="tnum font-medium text-t1">{total}</span>{" "}
          <Text id="library.derivation.summary-none-built">components were built by</Text>{" "}
          <span className="font-medium text-t1">{data.ruleset}</span>, the rules this
          version runs, so their names and descriptions may not match what a rebuilt component
          shows.
        </>
      ) : (
        <>
          <span className="tnum font-medium text-t1">{data.stale}</span> of{" "}
          <span className="tnum">{total}</span> components were built by different rules than the{" "}
          <span className="font-medium text-t1">{data.ruleset}</span>{" "}
          <Text id="library.derivation.summary-mixed-tail">
            this version runs, so their names and descriptions may not match what a rebuilt
            component shows.
          </Text>
        </>
      )}
    </p>
  );
}

/**
 * The signature: one row per ruleset actually present in the library. Three different problems
 * that a single "N behind" number would flatten into one -- older rules, a newer peer's rules,
 * and never derived at all.
 */
function StampLedger({ data }: { data: LibraryDerivation }) {
  const rows = Object.entries(data.counts).sort((a, b) => b[1] - a[1]);
  if (rows.length === 0) return null;
  return (
    <table className="w-full border-collapse text-sm">
      <caption className="sr-only">
        <Text id="library.derivation.table-caption">
          Components by the ruleset that built them
        </Text>
      </caption>
      <thead>
        <tr>
          <th
            scope="col"
            className="w-[9rem] pb-2 text-left text-2xs font-medium uppercase tracking-wide text-t3"
          >
            <Text id="library.derivation.column-ruleset">Ruleset</Text>
          </th>
          <th
            scope="col"
            className="w-[6rem] pb-2 text-right text-2xs font-medium uppercase tracking-wide text-t3"
          >
            <Text id="library.derivation.column-components">Components</Text>
          </th>
          <th
            scope="col"
            className="pb-2 pl-4 text-left text-2xs font-medium uppercase tracking-wide text-t3"
          >
            <Text id="library.derivation.column-standing">Standing</Text>
          </th>
        </tr>
      </thead>
      <tbody>
        {rows.map(([stamp, count]) => {
          const standing = standingOf(stamp, data.ruleset);
          return (
            <tr key={stamp || "never"} className="border-t border-line last:border-b">
              <th scope="row" className="py-2 text-left font-medium text-t1">
                {stamp || (
                  <span className="text-t3">
                    <Text id="library.derivation.stamp-none">None</Text>
                  </span>
                )}
              </th>
              <td className="tnum py-2 text-right text-t2">{count}</td>
              <td className="py-2 pl-4">
                <span className="inline-flex items-center gap-1.5 text-t2">
                  <Dot tone={TONES[standing]} />
                  {LABELS[standing]}
                </span>
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

function Report({ report }: { report: DerivationReport }) {
  const skipped = report.no_evidence;
  return (
    <div className="flex flex-col gap-2 border-l-2 border-line pl-3 text-sm text-t2">
      <p>
        <Text id="library.derivation.report-checked">Checked</Text>{" "}
        <span className="tnum">{report.checked}</span>, recomputed{" "}
        <span className="tnum text-t1">{report.rewritten}</span>, already current{" "}
        <span className="tnum">{report.unchanged}</span>.
      </p>
      {skipped > 0 ? (
        <p>
          <span className="tnum">{skipped}</span>{" "}
          {skipped === 1 ? "component has" : "components have"} no stored distributor data, so{" "}
          {skipped === 1 ? "it was" : "they were"} left exactly as {skipped === 1 ? "it is" : "they are"}.
          Rebuilding {skipped === 1 ? "it" : "them"} from nothing would erase what is there.
        </p>
      ) : null}
      {report.failed.length > 0 ? (
        <div>
          <Badge tone="err" size="sm">
            {report.failed.length === 1
              ? "1 Component Could Not Be Read"
              : `${report.failed.length} Components Could Not Be Read`}
          </Badge>
          <ul className="mt-1 list-disc pl-5">
            {report.failed.map((f) => (
              <li key={f.id}>
                <span className="font-medium text-t1">{f.id}</span>: {f.error}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  );
}
