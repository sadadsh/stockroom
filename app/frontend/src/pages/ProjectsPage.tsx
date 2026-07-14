/**
 * Projects (M7a): register and audit external KiCad projects. A registered project
 * is referenced by path, never owned by Stockroom, so this page never edits the
 * external files; it registers a reference, reads a health audit against the active
 * library, and unregisters on request.
 *
 * Left is a project switcher: each row shows the project NAME and its full folder
 * PATH, with a Register Project affordance (an absolute-path input plus a button)
 * that surfaces a 400 honestly as a toast. Selecting a project loads its audit: the
 * healthy/total headline, clickable breakdown chips (derived from counts.by_kind)
 * that filter the findings table by kind, the findings table (ref, severity, detail),
 * a Download Report button that saves the audit markdown as a .md, and an in-window
 * confirm to remove the registration.
 *
 * Honest states throughout: an empty library shows a register affordance (not a
 * blank frame); loading and error surfaces are explicit; a connection failure shows
 * a retry surface, never a crash.
 */
import { useEffect, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { ApiError, api } from "../api/client";
import {
  useProjectsQuery,
  useProjectAudit,
  useProjectChecks,
  useRegisterProject,
  useDeleteProject,
} from "../api/queries";
import type {
  AuditFinding,
  AuditResult,
  CheckFinding,
  CheckRun,
  ChecksResult,
  ProjectSummary,
} from "../api/types";
import { useJob } from "../lib/useJob";
import { useToast } from "../lib/toast";
import { Badge, Button, Card, Eyebrow } from "../components/primitives";
import { ConfirmDialog } from "../components/ConfirmDialog";

const INPUT_CLS =
  "min-w-0 flex-1 rounded-control border border-line2 bg-field px-3 py-2 " +
  "text-sm text-t1 outline-none focus:border-acc disabled:opacity-50";

// Severity -> the shared tone (err/warn/neutral) so the findings table and the
// headline read the same hue as the rest of the app. info is muted (neutral).
const SEVERITY_TONE: Record<AuditFinding["severity"], "err" | "warn" | "neutral"> = {
  error: "err",
  warning: "warn",
  info: "neutral",
};

function errMsg(err: unknown, fallback: string): string {
  return err instanceof ApiError ? err.message : fallback;
}

export function ProjectsPage() {
  const projectsQuery = useProjectsQuery();
  const register = useRegisterProject();
  const del = useDeleteProject();
  const { toast } = useToast();

  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [rootInput, setRootInput] = useState("");
  const [pendingDelete, setPendingDelete] = useState<ProjectSummary | null>(null);

  const projects = projectsQuery.data ?? [];

  // Keep the selection valid: when the list settles, drop a selection that fell out
  // of it (a delete, or the first load). Do not auto-select the first project; the
  // audit is a deliberate click, not something to fire on every list refresh.
  const projectsFetching = projectsQuery.isFetching;
  useEffect(() => {
    if (projectsFetching) return;
    if (selectedId && !projects.some((p) => p.id === selectedId)) {
      setSelectedId(null);
    }
  }, [projects, selectedId, projectsFetching]);

  function handleRegister() {
    const root = rootInput.trim();
    if (!root || register.isPending) return;
    register.mutate(root, {
      onSuccess: (rec) => {
        toast(`Registered ${rec.name}.`, "ok");
        setRootInput("");
        setSelectedId(rec.id);
      },
      onError: (err) => toast(errMsg(err, "Could not register the project."), "err"),
    });
  }

  function handleConfirmDelete() {
    const project = pendingDelete;
    if (!project) return;
    del.mutate(project.id, {
      onSuccess: () => {
        setPendingDelete(null);
        if (selectedId === project.id) setSelectedId(null);
        toast(`Removed ${project.name}.`, "ok");
      },
      onError: (err) => {
        setPendingDelete(null);
        // A 404 means it is already gone (a stale row acted on twice); that is the
        // desired end state, so report it neutrally, not as a red failure.
        if (err instanceof ApiError && err.status === 404) {
          toast(`${project.name} was already removed.`, "neutral");
        } else {
          toast(errMsg(err, "Could not remove the project."), "err");
        }
      },
    });
  }

  const selected = projects.find((p) => p.id === selectedId) ?? null;

  return (
    <>
      <div className="flex h-14 flex-none items-center px-[18px]">
        <div className="text-lg font-semibold text-t1">Projects</div>
        <div className="ml-auto text-2xs text-t3">
          {projectsQuery.data
            ? `${projects.length} ${projects.length === 1 ? "Project" : "Projects"}`
            : ""}
        </div>
      </div>

      <div className="flex min-h-0 flex-1">
        {/* picker */}
        <div className="flex w-[348px] flex-none flex-col border-r border-line px-3.5 pt-1.5">
          <div className="min-h-0 flex-1 overflow-y-auto px-2 pb-3 pt-1">
            <ProjectPicker
              isLoading={projectsQuery.isLoading}
              error={projectsQuery.error}
              projects={projects}
              selectedId={selectedId}
              onSelect={setSelectedId}
              onRetry={() => projectsQuery.refetch()}
            />
          </div>
          <RegisterBar
            value={rootInput}
            onChange={setRootInput}
            onRegister={handleRegister}
            busy={register.isPending}
          />
        </div>

        {/* detail */}
        <div className="min-w-0 flex-1 overflow-y-auto px-[30px] pt-[22px]">
          {selected ? (
            <ProjectDetailView
              project={selected}
              onRemove={() => setPendingDelete(selected)}
              removeBusy={del.isPending}
            />
          ) : (
            <div className="flex h-full min-h-[300px] items-center justify-center text-sm text-t3">
              {projectsQuery.isLoading
                ? "Loading Projects..."
                : "Select A Project To See Its Health."}
            </div>
          )}
        </div>
      </div>

      <ConfirmDialog
        open={pendingDelete !== null}
        title="Remove Project"
        body={
          <>
            Remove <b>{pendingDelete?.name}</b> from Stockroom? Only the registration
            is removed; the project files on disk are never touched.
          </>
        }
        confirmLabel="Remove"
        danger
        busy={del.isPending}
        onConfirm={handleConfirmDelete}
        onCancel={() => setPendingDelete(null)}
      />
    </>
  );
}

function ProjectPicker({
  isLoading,
  error,
  projects,
  selectedId,
  onSelect,
  onRetry,
}: {
  isLoading: boolean;
  error: Error | null;
  projects: ProjectSummary[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  onRetry: () => void;
}) {
  if (isLoading) {
    return (
      <div className="px-3 py-8 text-center text-sm text-t3">Loading Projects...</div>
    );
  }
  if (error) {
    const status = error instanceof ApiError ? error.status : undefined;
    const message =
      status === 0
        ? "Cannot reach the Stockroom server."
        : status === 401
          ? "Not authorized. The API token is missing or invalid."
          : error.message;
    return (
      <div className="flex flex-col items-center gap-3 px-3 py-8 text-center">
        <div className="text-sm text-err">{message}</div>
        <Button small onClick={onRetry}>
          Try Again
        </Button>
      </div>
    );
  }
  if (projects.length === 0) {
    return (
      <div className="flex flex-col items-center gap-2 px-4 py-10 text-center">
        <div className="text-sm font-medium text-t2">No projects are registered.</div>
        <div className="text-xs text-t3">
          Register an existing KiCad project by its folder path below to audit its
          health.
        </div>
      </div>
    );
  }
  return (
    <div className="flex flex-col gap-1.5">
      {projects.map((project) => (
        <ProjectRow
          key={project.id}
          project={project}
          selected={project.id === selectedId}
          onSelect={() => onSelect(project.id)}
        />
      ))}
    </div>
  );
}

function ProjectRow({
  project,
  selected,
  onSelect,
}: {
  project: ProjectSummary;
  selected: boolean;
  onSelect: () => void;
}) {
  return (
    <button
      type="button"
      data-testid={`project-row-${project.id}`}
      onClick={onSelect}
      className={
        "flex w-full flex-col gap-1 rounded-control border px-3 py-2.5 text-left transition-colors " +
        (selected
          ? "border-acc bg-raise2"
          : "border-line bg-raise hover:bg-raise2 hover:border-line2")
      }
    >
      <div className="flex items-center gap-2">
        <span className="min-w-0 flex-1 truncate text-sm font-medium text-t1">
          {project.name}
        </span>
        {project.has_git ? (
          <Badge tone="neutral" title="Under version control">
            Git
          </Badge>
        ) : null}
      </div>
      <span className="truncate font-mono text-2xs text-t3" title={project.root}>
        {project.root}
      </span>
      <span className="text-2xs text-t3">
        {project.board_count} {project.board_count === 1 ? "board" : "boards"} ·{" "}
        {project.sheet_count} {project.sheet_count === 1 ? "sheet" : "sheets"}
      </span>
    </button>
  );
}

function RegisterBar({
  value,
  onChange,
  onRegister,
  busy,
}: {
  value: string;
  onChange: (v: string) => void;
  onRegister: () => void;
  busy: boolean;
}) {
  return (
    <div className="flex-none border-t border-line px-2 py-3">
      <Eyebrow className="mb-1.5">Register Project</Eyebrow>
      <div className="flex flex-col gap-2">
        <input
          value={value}
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") onRegister();
          }}
          placeholder="Absolute path to a KiCad project folder"
          className={INPUT_CLS}
          spellCheck={false}
        />
        <Button
          variant="accent"
          onClick={onRegister}
          disabled={busy || !value.trim()}
          className="w-full justify-center"
        >
          {busy ? "Registering..." : "Register Project"}
        </Button>
      </div>
    </div>
  );
}

function ProjectDetailView({
  project,
  onRemove,
  removeBusy,
}: {
  project: ProjectSummary;
  onRemove: () => void;
  removeBusy: boolean;
}) {
  const auditQuery = useProjectAudit(project.id);
  // The active kind filter for the findings table. null = show every finding.
  const [kindFilter, setKindFilter] = useState<string | null>(null);

  // Reset the filter whenever the selected project changes, so a chip active on one
  // project never carries over to another.
  useEffect(() => {
    setKindFilter(null);
  }, [project.id]);

  return (
    <div className="max-w-[820px] pb-12">
      <div className="mb-5 flex items-start justify-between gap-4">
        <div className="min-w-0">
          <div className="truncate text-xl font-semibold text-t1">{project.name}</div>
          <div className="truncate font-mono text-xs text-t3" title={project.root}>
            {project.root}
          </div>
        </div>
        <Button
          variant="danger"
          small
          onClick={onRemove}
          disabled={removeBusy}
          className="flex-none"
        >
          Remove Project
        </Button>
      </div>

      {auditQuery.isLoading ? (
        <Card className="px-4 py-3.5">
          <p className="py-1 text-sm text-t3">Auditing the project...</p>
        </Card>
      ) : auditQuery.isError ? (
        <Card className="px-4 py-3.5">
          <p className="py-1 text-sm text-err">
            {errMsg(auditQuery.error, "Could not audit the project.")}
          </p>
        </Card>
      ) : auditQuery.data ? (
        <AuditView
          audit={auditQuery.data}
          kindFilter={kindFilter}
          onKindFilter={setKindFilter}
        />
      ) : null}

      <ChecksSection key={project.id} projectId={project.id} />
    </div>
  );
}

function AuditView({
  audit,
  kindFilter,
  onKindFilter,
}: {
  audit: AuditResult;
  kindFilter: string | null;
  onKindFilter: (kind: string | null) => void;
}) {
  const allHealthy = audit.healthy >= audit.components && audit.findings.length === 0;
  const kinds = Object.entries(audit.counts.by_kind).sort((a, b) =>
    a[0].localeCompare(b[0]),
  );
  const findings = kindFilter
    ? audit.findings.filter((f) => f.kind === kindFilter)
    : audit.findings;

  return (
    <div className="flex flex-col gap-5">
      {/* headline */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-baseline gap-2">
          <span className="text-2xl font-semibold text-t1">
            {audit.healthy} of {audit.components}
          </span>
          <span className="text-sm text-t3">
            components healthy across {audit.sheets}{" "}
            {audit.sheets === 1 ? "sheet" : "sheets"}
          </span>
        </div>
        <Button small onClick={() => downloadMarkdown(audit)}>
          Download Report
        </Button>
      </div>

      {allHealthy ? (
        <Card className="px-4 py-3.5">
          <div className="flex items-center gap-2.5 py-1">
            <Badge tone="ok">Healthy</Badge>
            <span className="text-sm text-t2">
              Every component is annotated, footprinted, and sourced. Nothing needs
              attention.
            </span>
          </div>
        </Card>
      ) : (
        <>
          {/* breakdown chips: click one to filter the table by that kind */}
          {kinds.length > 0 ? (
            <div className="flex flex-wrap items-center gap-2" data-testid="audit-chips">
              {kinds.map(([kind, count]) => {
                const active = kindFilter === kind;
                return (
                  <button
                    key={kind}
                    type="button"
                    data-testid={`audit-chip-${kind}`}
                    aria-pressed={active}
                    onClick={() => onKindFilter(active ? null : kind)}
                    className={
                      "inline-flex items-center gap-1.5 rounded-control border px-2.5 py-1 text-xs font-medium transition-colors " +
                      (active
                        ? "border-acc bg-raise2 text-t1"
                        : "border-line bg-raise text-t2 hover:bg-raise2 hover:text-t1")
                    }
                  >
                    <span>{kindLabel(kind)}</span>
                    <span className="text-t3">{count}</span>
                  </button>
                );
              })}
              {kindFilter ? (
                <button
                  type="button"
                  onClick={() => onKindFilter(null)}
                  className="text-xs text-t3 underline-offset-2 hover:text-t2 hover:underline"
                >
                  Clear Filter
                </button>
              ) : null}
            </div>
          ) : null}

          {/* findings table */}
          <FindingsTable findings={findings} />
        </>
      )}

      {audit.unresolved_footprints > 0 ? (
        <p className="text-xs text-t3">
          Pin/pad and 3D checks ran on {audit.checked_footprints}{" "}
          {audit.checked_footprints === 1 ? "footprint" : "footprints"};{" "}
          {audit.unresolved_footprints} could not be resolved from the active library.
        </p>
      ) : null}
    </div>
  );
}

function FindingsTable({ findings }: { findings: AuditFinding[] }) {
  if (findings.length === 0) {
    return (
      <p className="py-1 text-sm text-t3">No findings match the current filter.</p>
    );
  }
  return (
    <Card className="overflow-hidden" data-testid="audit-findings">
      <table className="w-full text-left text-sm">
        <thead>
          <tr data-testid="findings-head" className="border-b border-line text-2xs text-t3">
            <th className="px-4 py-2 font-medium">Ref</th>
            <th className="px-4 py-2 font-medium">Severity</th>
            <th className="px-4 py-2 font-medium">Detail</th>
          </tr>
        </thead>
        <tbody>
          {findings.map((finding, i) => (
            <tr
              key={`${finding.ref}-${finding.kind}-${i}`}
              className="border-b border-line last:border-b-0"
              data-testid={`finding-${finding.ref}-${finding.kind}`}
            >
              <td className="px-4 py-2 align-top font-mono text-xs text-t2">
                {finding.ref}
              </td>
              <td className="px-4 py-2 align-top">
                <Badge tone={SEVERITY_TONE[finding.severity]}>
                  {severityLabel(finding.severity)}
                </Badge>
              </td>
              <td className="px-4 py-2 align-top text-t1">{finding.detail}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </Card>
  );
}

// Turn a machine kind (no_footprint) into a Title Case chip label (No Footprint).
function kindLabel(kind: string): string {
  return kind
    .split("_")
    .map((word) => (word ? word[0].toUpperCase() + word.slice(1) : word))
    .join(" ");
}

function severityLabel(severity: AuditFinding["severity"]): string {
  return severity[0].toUpperCase() + severity.slice(1);
}

// Save the audit markdown as a .md file through an in-window Blob download (no OS
// dialog beyond the browser's own save prompt, which the runtime owns).
function downloadMarkdown(audit: AuditResult) {
  const blob = new Blob([audit.markdown], { type: "text/markdown;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `${audit.project || "project"}-health.md`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

// -- Rules Check (ERC + DRC, M7b) --------------------------------------------

// Severity -> tone for the ERC/DRC findings tables. exclusion is a deliberate KiCad
// waiver (neutral); info is muted.
const CHECK_SEVERITY_TONE: Record<CheckFinding["severity"], "err" | "warn" | "neutral"> = {
  error: "err",
  warning: "warn",
  exclusion: "neutral",
  info: "neutral",
};

// The Rules Check section: run structured ERC + DRC via kicad-cli as a job, then show
// the cached result. Keyed by project id in the parent so its job state never leaks
// across a project switch. Honest states throughout: a missing kicad-cli is an inline
// error (never a fabricated pass), and an unrun project shows a "not run yet" prompt.
function ChecksSection({ projectId }: { projectId: string }) {
  const checksQuery = useProjectChecks(projectId);
  const job = useJob<ChecksResult>();
  const qc = useQueryClient();
  const { toast } = useToast();
  const [starting, setStarting] = useState(false);
  const [startError, setStartError] = useState<string | null>(null);

  // When a run finishes, refresh the cached-run query so a later revisit reads the
  // same server-cached result this job just produced.
  useEffect(() => {
    if (job.status === "done") {
      qc.invalidateQueries({ queryKey: ["project-checks", projectId] });
    }
  }, [job.status, projectId, qc]);

  async function onRun() {
    setStarting(true);
    setStartError(null);
    try {
      const { job_id } = await api.runChecks(projectId);
      job.run(job_id);
    } catch (e) {
      // A missing kicad-cli is an honest 502; surface it inline (and as a toast).
      const msg = errMsg(e, "Could not start the checks.");
      setStartError(msg);
      toast(msg, "err");
    } finally {
      setStarting(false);
    }
  }

  const busy = starting || job.status === "running";
  // Prefer the just-produced run; else the cached last run.
  const data: ChecksResult | null =
    job.status === "done" && job.result ? job.result : (checksQuery.data ?? null);
  const hasRun = data != null && data.ran_at != null;

  return (
    <div className="mt-7 border-t border-line pt-6" data-testid="checks-section">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
        <div>
          <Eyebrow className="mb-0.5">Rules Check</Eyebrow>
          <p className="text-xs text-t3">
            Run KiCad ERC on the schematic and DRC on the board through kicad-cli.
          </p>
        </div>
        <Button variant="accent" small onClick={onRun} disabled={busy}>
          {busy ? "Running..." : hasRun ? "Re-run Checks" : "Run Checks"}
        </Button>
      </div>

      {busy && job.progress?.message ? (
        <p className="mb-2 text-xs text-t3">{job.progress.message}...</p>
      ) : null}
      {startError ? <p className="mb-2 text-sm text-err">{startError}</p> : null}
      {job.status === "error" ? (
        <p className="mb-2 text-sm text-err">{job.error ?? "The checks failed."}</p>
      ) : null}

      {checksQuery.isLoading && !hasRun && !busy ? (
        <p className="text-sm text-t3">Loading the last run...</p>
      ) : hasRun && data ? (
        <ChecksResultView result={data} />
      ) : !busy && !startError && job.status !== "error" ? (
        <p className="text-sm text-t3">
          Checks have not run yet. Run them to see ERC and DRC results.
        </p>
      ) : null}
    </div>
  );
}

function ChecksResultView({ result }: { result: ChecksResult }) {
  const s = result.summary;
  return (
    <div className="flex flex-col gap-4" data-testid="checks-result">
      <div className="flex flex-wrap items-center gap-2.5">
        {s ? <ChecksVerdictBadge summary={s} /> : null}
        {s && !s.ok ? (
          <span className="text-xs text-warn">
            A check could not complete; its results are not included.
          </span>
        ) : null}
      </div>

      <CheckRunView label="ERC" run={result.erc} emptyLabel="No schematic to check." />

      {result.drc.length === 0 ? (
        <p className="text-xs text-t3">No board to run DRC on.</p>
      ) : (
        result.drc.map((run, i) => (
          <CheckRunView
            key={run.board ?? i}
            label={run.board ? `DRC (${run.board})` : "DRC"}
            run={run}
            emptyLabel=""
          />
        ))
      )}
    </div>
  );
}

function ChecksVerdictBadge({
  summary,
}: {
  summary: NonNullable<ChecksResult["summary"]>;
}) {
  const badges = [];
  if (summary.errors > 0) {
    badges.push(
      <Badge key="e" tone="err">
        {countLabel(summary.errors, "Error")}
      </Badge>,
    );
  }
  if (summary.warnings > 0) {
    badges.push(
      <Badge key="w" tone="warn">
        {countLabel(summary.warnings, "Warning")}
      </Badge>,
    );
  }
  if (badges.length === 0) {
    badges.push(
      summary.ok ? (
        <Badge key="c" tone="ok">
          Clean
        </Badge>
      ) : (
        <Badge key="x" tone="neutral">
          No Results
        </Badge>
      ),
    );
  }
  return <>{badges}</>;
}

function CheckRunView({
  label,
  run,
  emptyLabel,
}: {
  label: string;
  run: CheckRun | null;
  emptyLabel: string;
}) {
  if (run == null) {
    return emptyLabel ? <p className="text-xs text-t3">{emptyLabel}</p> : null;
  }
  if (!run.ok) {
    return (
      <div>
        <div className="mb-1 text-sm font-medium text-t2">{label}</div>
        <p className="text-sm text-err">{run.error || "This check could not complete."}</p>
      </div>
    );
  }
  if (run.findings.length === 0) {
    return (
      <div className="flex items-center gap-2">
        <span className="text-sm font-medium text-t2">{label}</span>
        <Badge tone="ok">Clean</Badge>
      </div>
    );
  }
  return (
    <div>
      <div className="mb-1.5 flex items-center gap-2">
        <span className="text-sm font-medium text-t2">{label}</span>
        <span className="text-2xs text-t3">
          {countLabel(run.summary.errors, "error")},{" "}
          {countLabel(run.summary.warnings, "warning")}
        </span>
      </div>
      <CheckFindingsTable findings={run.findings} testid={`check-findings-${label}`} />
    </div>
  );
}

function CheckFindingsTable({
  findings,
  testid,
}: {
  findings: CheckFinding[];
  testid: string;
}) {
  return (
    <Card className="overflow-hidden" data-testid={testid}>
      <table className="w-full text-left text-sm">
        <thead>
          <tr className="border-b border-line text-2xs text-t3">
            <th className="px-4 py-2 font-medium">Severity</th>
            <th className="px-4 py-2 font-medium">Rule</th>
            <th className="px-4 py-2 font-medium">Message</th>
          </tr>
        </thead>
        <tbody>
          {findings.map((finding, i) => (
            <tr
              key={`${finding.rule}-${i}`}
              className="border-b border-line last:border-b-0"
            >
              <td className="px-4 py-2 align-top">
                <Badge tone={CHECK_SEVERITY_TONE[finding.severity]}>
                  {checkSeverityLabel(finding.severity)}
                </Badge>
              </td>
              <td className="px-4 py-2 align-top font-mono text-xs text-t2">
                {finding.rule}
              </td>
              <td className="px-4 py-2 align-top text-t1">
                {finding.message}
                {finding.where ? (
                  <span className="mt-0.5 block text-2xs text-t3">{finding.where}</span>
                ) : null}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </Card>
  );
}

function checkSeverityLabel(severity: CheckFinding["severity"]): string {
  return severity[0].toUpperCase() + severity.slice(1);
}

// "1 Error", "3 Errors"; noun casing is the caller's (Title Case in a badge, lower in
// a caption).
function countLabel(n: number, noun: string): string {
  return `${n} ${noun}${n === 1 ? "" : "s"}`;
}
