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
  useProjectBom,
  useProjectChecks,
  useProjectProcurement,
  useProjectRevisions,
  useProjectDesign,
  useSetNetClasses,
  useSetDesignRules,
  useBomDiff,
  useRegisterProject,
  useDeleteProject,
} from "../api/queries";
import type {
  AuditFinding,
  AuditResult,
  BomDiffResult,
  BomExportKind,
  BomLine,
  BomResult,
  CheckFinding,
  CheckRun,
  ChecksResult,
  DesignResult,
  DesignRules,
  NetClass,
  ProcurementExportOptions,
  ProcurementLine,
  ProcurementResult,
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
      <BomSection key={`bom-${project.id}`} projectId={project.id} />
      <ProcurementSection key={`proc-${project.id}`} projectId={project.id} />
      <RevisionDiffSection key={`diff-${project.id}`} projectId={project.id} />
      <EditorSection key={`editor-${project.id}`} projectId={project.id} />
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
    // A green "Clean" requires that a check actually ran (checked > 0) and passed; a run
    // that verified nothing (a project with no schematic or board) is an honest "Nothing
    // Checked", never a fabricated pass. A ran-but-failed check is "No Results".
    if (summary.checked === 0) {
      badges.push(
        <Badge key="n" tone="neutral">
          Nothing Checked
        </Badge>,
      );
    } else if (summary.ok) {
      badges.push(
        <Badge key="c" tone="ok">
          Clean
        </Badge>,
      );
    } else {
      badges.push(
        <Badge key="x" tone="neutral">
          No Results
        </Badge>,
      );
    }
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

// -- Build And Cost (BOM grouping + cost, M7c) -------------------------------

function formatMoney(n: number, currency: string): string {
  const sym = currency === "USD" ? "$" : "";
  return `${sym}${n.toFixed(2)}`;
}

function unitPriceLabel(line: BomLine): string {
  if (line.unit_price === undefined || line.unit_price === null || line.unit_price === "") {
    return "";
  }
  const n = typeof line.unit_price === "number" ? line.unit_price : Number(line.unit_price);
  return Number.isFinite(n) ? `$${n.toFixed(4)}` : String(line.unit_price);
}

// The Build And Cost section: build a grouped, priced BOM as a job, then show the cached
// result. Keyed by project id in the parent so its job state never leaks across a switch.
// Honest states throughout: a project with no parts is "Nothing to Build", a build whose
// parts could not be sourced is "Unpriced" (never a fabricated cost), and an unbuilt
// project shows a "not built yet" prompt.
function BomSection({ projectId }: { projectId: string }) {
  const bomQuery = useProjectBom(projectId);
  const job = useJob<BomResult>();
  const qc = useQueryClient();
  const { toast } = useToast();
  const [starting, setStarting] = useState(false);
  const [startError, setStartError] = useState<string | null>(null);

  useEffect(() => {
    if (job.status === "done") {
      qc.invalidateQueries({ queryKey: ["project-bom", projectId] });
      // A fresh build changes the sourcing data and the diff's cost side, so both re-read.
      qc.invalidateQueries({ queryKey: ["project-procurement", projectId] });
      qc.invalidateQueries({ queryKey: ["project-diff", projectId] });
    }
  }, [job.status, projectId, qc]);

  async function onRun() {
    setStarting(true);
    setStartError(null);
    try {
      const { job_id } = await api.runBom(projectId);
      job.run(job_id);
    } catch (e) {
      const msg = errMsg(e, "Could not start the BOM build.");
      setStartError(msg);
      toast(msg, "err");
    } finally {
      setStarting(false);
    }
  }

  const busy = starting || job.status === "running";
  const data: BomResult | null =
    job.status === "done" && job.result ? job.result : (bomQuery.data ?? null);
  const hasBuilt = data != null && data.ran_at != null;

  return (
    <div className="mt-7 border-t border-line pt-6" data-testid="bom-section">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
        <div>
          <Eyebrow className="mb-0.5">Build And Cost</Eyebrow>
          <p className="text-xs text-t3">
            Group the schematic into a Bill of Materials and price it through the enrich
            layer.
          </p>
        </div>
        <Button variant="accent" small onClick={onRun} disabled={busy}>
          {busy ? "Building..." : hasBuilt ? "Rebuild BOM" : "Build And Cost"}
        </Button>
      </div>

      {busy && job.progress?.message ? (
        <p className="mb-2 text-xs text-t3">{job.progress.message}...</p>
      ) : null}
      {startError ? <p className="mb-2 text-sm text-err">{startError}</p> : null}
      {job.status === "error" ? (
        <p className="mb-2 text-sm text-err">{job.error ?? "The BOM build failed."}</p>
      ) : null}

      {bomQuery.isLoading && !hasBuilt && !busy ? (
        <p className="text-sm text-t3">Loading the last build...</p>
      ) : hasBuilt && data ? (
        <BomResultView result={data} />
      ) : !busy && !startError && job.status !== "error" ? (
        <p className="text-sm text-t3">
          The BOM has not been built yet. Build it to group and price the parts.
        </p>
      ) : null}
    </div>
  );
}

function BomResultView({ result }: { result: BomResult }) {
  const s = result.summary;
  const sources = result.by_source?.sources ?? {};
  const sourceNames = Object.keys(sources).filter((n) => n !== "Unsourced");
  return (
    <div className="flex flex-col gap-4" data-testid="bom-result">
      <div className="flex flex-wrap items-center gap-2.5">
        {s ? <BomVerdictBadge summary={s} /> : null}
        {s ? (
          <span className="text-xs text-t3">
            {countLabel(s.line_count, "Line")}, {result.component_count} parts
          </span>
        ) : null}
        {sourceNames.map((name) => (
          <span key={name} className="text-2xs text-t3">
            {name} {formatMoney(sources[name].total_cost, result.by_source?.currency ?? "USD")}
          </span>
        ))}
      </div>

      {result.lines.length === 0 ? (
        <p className="text-xs text-t3">No parts to build a BOM from.</p>
      ) : (
        <BomLinesTable lines={result.lines} priced={result.priced} />
      )}
    </div>
  );
}

function BomVerdictBadge({ summary }: { summary: NonNullable<BomResult["summary"]> }) {
  const money = formatMoney(summary.total_cost, summary.currency);
  switch (summary.state) {
    case "empty":
      return <Badge tone="neutral">Nothing to Build</Badge>;
    case "built":
      return <Badge tone="neutral">Not Priced</Badge>;
    case "unpriced":
      return <Badge tone="warn">Unpriced</Badge>;
    case "partial":
      return (
        <>
          <Badge tone="ok">{money} Costed</Badge>
          <Badge tone="warn">{countLabel(summary.unpriced_lines, "Unpriced Line")}</Badge>
        </>
      );
    case "costed":
      return <Badge tone="ok">{money} Costed</Badge>;
    default:
      return null;
  }
}

function BomLinesTable({ lines, priced }: { lines: BomLine[]; priced: boolean }) {
  return (
    <Card className="overflow-hidden" data-testid="bom-lines">
      <table className="w-full text-left text-sm">
        <thead>
          <tr className="border-b border-line text-2xs text-t3">
            <th className="px-4 py-2 font-medium">Qty</th>
            <th className="px-4 py-2 font-medium">Value</th>
            <th className="px-4 py-2 font-medium">Part</th>
            <th className="px-4 py-2 font-medium">Footprint</th>
            {priced ? <th className="px-4 py-2 font-medium">Unit</th> : null}
            {priced ? <th className="px-4 py-2 font-medium">Ext</th> : null}
          </tr>
        </thead>
        <tbody>
          {lines.map((line, i) => (
            <tr key={`${line.mpn || line.value}-${i}`} className="border-b border-line last:border-b-0">
              <td className="px-4 py-2 align-top text-t2">{line.qty}</td>
              <td className="px-4 py-2 align-top text-t1">
                {line.value || "-"}
                <span className="mt-0.5 block text-2xs text-t3" title={line.refs.join(", ")}>
                  {line.refs.join(", ")}
                </span>
              </td>
              <td className="px-4 py-2 align-top">
                {line.mpn ? (
                  <span className="font-mono text-xs text-t2">{line.mpn}</span>
                ) : line.basic ? (
                  <Badge tone="neutral">Basic</Badge>
                ) : (
                  <Badge tone="neutral">No MPN</Badge>
                )}
                {line.manufacturer ? (
                  <span className="mt-0.5 block text-2xs text-t3">{line.manufacturer}</span>
                ) : null}
              </td>
              <td className="px-4 py-2 align-top font-mono text-2xs text-t3">
                {line.footprint || "-"}
              </td>
              {priced ? (
                <td className="px-4 py-2 align-top text-t2">{unitPriceLabel(line) || "-"}</td>
              ) : null}
              {priced ? (
                <td className="px-4 py-2 align-top text-t2">
                  {line.extended !== undefined && line.extended !== null
                    ? `$${line.extended.toFixed(2)}`
                    : "-"}
                </td>
              ) : null}
            </tr>
          ))}
        </tbody>
      </table>
    </Card>
  );
}

// -- Procurement (sourcing/stock risk + lead + orderability + exports, M7d) ----

// The BOM export kinds, in the order a buyer reaches for them: the full BOM, the priced
// purchasing sheet, then the vendor-specific uploads.
const EXPORT_KINDS: { kind: BomExportKind; label: string }[] = [
  { kind: "csv", label: "BOM CSV" },
  { kind: "xlsx", label: "BOM Excel" },
  { kind: "priced", label: "Priced Sheet" },
  { kind: "procurement", label: "Procurement Sheet" },
  { kind: "cart", label: "Mouser Cart" },
  { kind: "jlcpcb", label: "JLCPCB BOM" },
];

// Save an already-fetched text body (the diff CSV) as a file, client-side. The export
// endpoints stream binary through the authed client; this is only for text already in hand.
function saveText(filename: string, text: string): void {
  const url = URL.createObjectURL(new Blob([text], { type: "text/csv" }));
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

// The Procurement section reads the cached BOM's sourcing view: a risk headline (NRND / no
// stock / short lines / critical-path lead), a per-line orderability table, and the export
// bar. Honest: before a build it prompts to build; an unpriced build lists lines with
// unknown (never-a-risk) stock and no cost.
// The buy-side knobs, in UI units (percentages as whole numbers), defaulting to no
// adjustment so a one-click export is never silently inflated. tax/assembly are converted to
// the backend's fraction form when sent; spares stays a whole percent.
interface ExportOpts {
  sparesPct: number;
  pcbMultiple: number;
  taxPct: number;
  shipping: number;
  labourPerBoard: number;
  assemblyPct: number;
}

const DEFAULT_EXPORT_OPTS: ExportOpts = {
  sparesPct: 0,
  pcbMultiple: 1,
  taxPct: 0,
  shipping: 0,
  labourPerBoard: 0,
  assemblyPct: 0,
};

function ProcurementSection({ projectId }: { projectId: string }) {
  const query = useProjectProcurement(projectId);
  const { toast } = useToast();
  const [downloading, setDownloading] = useState<BomExportKind | null>(null);
  const [opts, setOpts] = useState<ExportOpts>(DEFAULT_EXPORT_OPTS);

  // Map the UI knobs to the export query params, per kind: the Procurement Sheet takes them
  // all, the Mouser Cart takes only spares, and every other kind is a plain one-click export.
  function exportOpts(kind: BomExportKind): ProcurementExportOptions | undefined {
    if (kind === "procurement") {
      return {
        spares_pct: opts.sparesPct,
        pcb_multiple: opts.pcbMultiple,
        tax_rate: opts.taxPct / 100,
        shipping: opts.shipping,
        labour_per_board: opts.labourPerBoard,
        assembly_surcharge_rate: opts.assemblyPct / 100,
      };
    }
    if (kind === "cart") return { spares_pct: opts.sparesPct };
    return undefined;
  }

  async function onExport(kind: BomExportKind) {
    setDownloading(kind);
    try {
      await api.downloadBomExport(projectId, kind, exportOpts(kind));
    } catch (e) {
      toast(errMsg(e, "Could not export the BOM."), "err");
    } finally {
      setDownloading(null);
    }
  }

  const data = query.data ?? null;
  const built = data != null && data.built;

  return (
    <div className="mt-7 border-t border-line pt-6" data-testid="procurement-section">
      <div className="mb-3">
        <Eyebrow className="mb-0.5">Procurement</Eyebrow>
        <p className="text-xs text-t3">
          Sourcing risk, lead time and per-line orderability from the priced BOM, plus the
          purchasing exports.
        </p>
      </div>

      {query.isLoading ? (
        <p className="text-sm text-t3">Loading procurement...</p>
      ) : !built ? (
        <p className="text-sm text-t3">
          Build the BOM to see sourcing risk, lead time and export the purchasing sheets.
        </p>
      ) : (
        <div className="flex flex-col gap-4" data-testid="procurement-result">
          <ProcurementRollup data={data as ProcurementResult} />
          <ExportOptionsForm opts={opts} onChange={setOpts} />
          <ExportBar onExport={onExport} downloading={downloading} />
          <ProcurementLinesTable lines={(data as ProcurementResult).lines} />
        </div>
      )}
    </div>
  );
}

function ExportOptionsForm({
  opts,
  onChange,
}: {
  opts: ExportOpts;
  onChange: (o: ExportOpts) => void;
}) {
  const fields: { key: keyof ExportOpts; label: string; step?: string }[] = [
    { key: "sparesPct", label: "Spares %" },
    { key: "pcbMultiple", label: "PCB Pack" },
    { key: "taxPct", label: "Tax %", step: "0.1" },
    { key: "shipping", label: "Shipping $", step: "0.01" },
    { key: "labourPerBoard", label: "Labour/Board $", step: "0.01" },
    { key: "assemblyPct", label: "Assembly %", step: "0.1" },
  ];
  return (
    <div data-testid="export-options">
      <p className="mb-1.5 text-2xs text-t3">
        Procurement Sheet options (spares also apply to the Mouser Cart).
      </p>
      <div className="flex flex-wrap gap-3">
        {fields.map(({ key, label, step }) => (
          <label key={key} className="flex flex-col gap-1 text-2xs text-t3">
            {label}
            <input
              type="number"
              min={0}
              step={step ?? "1"}
              className={`${INPUT_CLS} w-24`}
              data-testid={`opt-${key}`}
              value={opts[key]}
              onChange={(e) => onChange({ ...opts, [key]: Number(e.target.value) || 0 })}
            />
          </label>
        ))}
      </div>
    </div>
  );
}

function ProcurementRollup({ data }: { data: ProcurementResult }) {
  const { risks, lead } = data;
  return (
    <div className="flex flex-wrap items-center gap-2.5" data-testid="procurement-rollup">
      {!risks.any ? (
        <Badge tone="ok">No Sourcing Risks</Badge>
      ) : (
        <>
          {risks.not_active > 0 ? (
            <Badge tone="warn">{countLabel(risks.not_active, "Not Active")}</Badge>
          ) : null}
          {risks.no_stock > 0 ? (
            <Badge tone="err">{countLabel(risks.no_stock, "No Stock Line")}</Badge>
          ) : null}
          {risks.insufficient_stock > 0 ? (
            <Badge tone="warn">{countLabel(risks.insufficient_stock, "Short Line")}</Badge>
          ) : null}
        </>
      )}
      {lead.any && lead.max_weeks != null ? (
        <span className="text-xs text-t3">
          Critical path {lead.max_weeks} wk{lead.critical_mpn ? ` (${lead.critical_mpn})` : ""}
        </span>
      ) : null}
      {!data.priced ? (
        <span className="text-2xs text-t3">Unpriced build: stock is unknown, not a risk.</span>
      ) : null}
    </div>
  );
}

function ExportBar({
  onExport,
  downloading,
}: {
  onExport: (kind: BomExportKind) => void;
  downloading: BomExportKind | null;
}) {
  return (
    <div className="flex flex-wrap gap-2" data-testid="export-bar">
      {EXPORT_KINDS.map(({ kind, label }) => (
        <Button
          key={kind}
          small
          onClick={() => onExport(kind)}
          disabled={downloading != null}
        >
          {downloading === kind ? "Saving..." : label}
        </Button>
      ))}
    </div>
  );
}

function ProcurementLinesTable({ lines }: { lines: ProcurementLine[] }) {
  return (
    <Card className="overflow-hidden" data-testid="procurement-lines">
      <table className="w-full text-left text-sm">
        <thead>
          <tr className="border-b border-line text-2xs text-t3">
            <th className="px-4 py-2 font-medium">Part</th>
            <th className="px-4 py-2 font-medium">Qty</th>
            <th className="px-4 py-2 font-medium">Stock</th>
            <th className="px-4 py-2 font-medium">Lifecycle</th>
            <th className="px-4 py-2 font-medium">Lead</th>
            <th className="px-4 py-2 font-medium">Orderable</th>
          </tr>
        </thead>
        <tbody>
          {lines.map((line, i) => (
            <tr
              key={`${line.mpn || line.value}-${i}`}
              className="border-b border-line last:border-b-0"
            >
              <td className="px-4 py-2 align-top">
                {line.mpn ? (
                  <span className="font-mono text-xs text-t2">{line.mpn}</span>
                ) : (
                  <span className="text-t2">{line.value || "-"}</span>
                )}
                <span className="mt-0.5 block text-2xs text-t3">{line.refs.join(", ")}</span>
              </td>
              <td className="px-4 py-2 align-top text-t2">{line.qty}</td>
              <td className="px-4 py-2 align-top">
                <StockCell line={line} />
              </td>
              <td className="px-4 py-2 align-top text-2xs">
                {line.lifecycle ? (
                  <span
                    className={
                      line.lifecycle.toLowerCase() === "active" ? "text-t3" : "text-warn"
                    }
                  >
                    {line.lifecycle}
                  </span>
                ) : (
                  <span className="text-t3">-</span>
                )}
              </td>
              <td className="px-4 py-2 align-top text-2xs text-t3">{line.lead_time || "-"}</td>
              <td className="px-4 py-2 align-top">
                {line.orderable ? (
                  <Badge tone="ok">Yes</Badge>
                ) : (
                  <Badge tone="neutral">No</Badge>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </Card>
  );
}

function StockCell({ line }: { line: ProcurementLine }) {
  const risk = line.stock_risk;
  if (risk.available == null) {
    return <span className="text-2xs text-t3">Unknown</span>;
  }
  const tone = risk.kind === "err" ? "text-err" : risk.kind === "warn" ? "text-warn" : "text-t2";
  return (
    <span className={`text-xs ${tone}`}>
      {risk.available.toLocaleString()}
      {risk.short ? (
        <span className="ml-1 text-2xs">need {risk.required.toLocaleString()}</span>
      ) : null}
    </span>
  );
}

// -- Revision diff (compare the BOM at a git revision to the current build, M7d) --

// The value the "Current build" option carries in the Revision B picker: the backend reads a
// blank b as the current build (its cached priced rows), so cost/lead deltas are meaningful.
const CURRENT_BUILD = "";

function RevisionDiffSection({ projectId }: { projectId: string }) {
  const revs = useProjectRevisions(projectId);
  const [revA, setRevA] = useState<string | null>(null);
  const [revB, setRevB] = useState<string>(CURRENT_BUILD);
  const diff = useBomDiff(projectId, revA, revB);

  const underGit = revs.data?.under_git ?? false;
  const revisions = revs.data?.revisions ?? [];

  return (
    <div className="mt-7 border-t border-line pt-6" data-testid="diff-section">
      <div className="mb-3">
        <Eyebrow className="mb-0.5">Revision Diff</Eyebrow>
        <p className="text-xs text-t3">
          Compare the BOM at an older commit to the current build: what changed, what it costs,
          and how it moves the lead time.
        </p>
      </div>

      {revs.isLoading ? (
        <p className="text-sm text-t3">Loading revisions...</p>
      ) : !underGit ? (
        <p className="text-sm text-t3">
          This project is not under git, so there is no revision history to diff.
        </p>
      ) : revisions.length === 0 ? (
        <p className="text-sm text-t3">No commits touch this project's schematics yet.</p>
      ) : (
        <div className="flex flex-col gap-4">
          <div className="flex flex-wrap items-end gap-3" data-testid="diff-pickers">
            <label className="flex flex-col gap-1 text-2xs text-t3">
              Compare Revision
              <select
                className={INPUT_CLS}
                data-testid="diff-rev-a"
                value={revA ?? ""}
                onChange={(e) => setRevA(e.target.value || null)}
              >
                <option value="">Select a commit</option>
                {revisions.map((r) => (
                  <option key={r.sha} value={r.sha}>
                    {r.short} {r.subject}
                  </option>
                ))}
              </select>
            </label>
            <label className="flex flex-col gap-1 text-2xs text-t3">
              Against
              <select
                className={INPUT_CLS}
                data-testid="diff-rev-b"
                value={revB}
                onChange={(e) => setRevB(e.target.value)}
              >
                <option value={CURRENT_BUILD}>Current build</option>
                {revisions.map((r) => (
                  <option key={r.sha} value={r.sha}>
                    {r.short} {r.subject}
                  </option>
                ))}
              </select>
            </label>
          </div>

          {revA == null ? (
            <p className="text-sm text-t3">Choose a commit to compare against the current build.</p>
          ) : diff.isLoading ? (
            <p className="text-sm text-t3">Computing the diff...</p>
          ) : diff.isError ? (
            <p className="text-sm text-err">{errMsg(diff.error, "Could not diff the revisions.")}</p>
          ) : diff.data ? (
            <BomDiffView result={diff.data} />
          ) : null}
        </div>
      )}
    </div>
  );
}

function BomDiffView({ result }: { result: BomDiffResult }) {
  const { added, removed, changed, cost, lead } = result;
  const noChange = added.length === 0 && removed.length === 0 && changed.length === 0;
  const filename = `${(result.project || "project").replace(/[^A-Za-z0-9._-]+/g, "_")}_bom_diff.csv`;

  // Honesty guard: when a revision's schematics could not be read (the files did not exist at
  // that commit, or were renamed since), its side reconstructs to zero components and every
  // current part reads as Added with a fabricated cost/lead delta. Surface that instead of the
  // misleading diff. b_sheets_found is null for the current build, so it never false-triggers.
  const unreadable =
    result.a_sheets_found === 0
      ? "A"
      : result.b_sheets_found === 0
        ? "B"
        : null;
  if (unreadable) {
    return (
      <Card className="px-4 py-3.5" data-testid="diff-unreadable">
        <p className="text-sm text-warn">
          Revision {unreadable} had no readable schematics at that commit, so this comparison is
          not meaningful. Pick a commit after the schematic was added.
        </p>
      </Card>
    );
  }

  return (
    <div className="flex flex-col gap-4" data-testid="diff-result">
      <div className="flex flex-wrap items-center gap-2.5">
        <Badge tone="neutral">{countLabel(added.length, "Added")}</Badge>
        <Badge tone="neutral">{countLabel(removed.length, "Removed")}</Badge>
        <Badge tone="neutral">{countLabel(changed.length, "Changed")}</Badge>
        {cost.priced ? (
          <Badge tone={cost.delta > 0 ? "warn" : "ok"}>
            {cost.delta >= 0 ? "+" : "-"}
            {formatMoney(Math.abs(cost.delta), cost.currency)}/board
          </Badge>
        ) : null}
        {lead.on_critical_path && lead.added_critical_mpn ? (
          <span className="text-2xs text-warn">
            New part on the critical path ({lead.added_critical_mpn}, {lead.added_max_weeks} wk)
          </span>
        ) : null}
        <Button small onClick={() => saveText(filename, result.csv)}>
          Download Diff CSV
        </Button>
      </div>

      {noChange ? (
        <p className="text-xs text-t3">No BOM change between these revisions.</p>
      ) : (
        <Card className="overflow-hidden" data-testid="diff-lines">
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="border-b border-line text-2xs text-t3">
                <th className="px-4 py-2 font-medium">Change</th>
                <th className="px-4 py-2 font-medium">Part</th>
                <th className="px-4 py-2 font-medium">From</th>
                <th className="px-4 py-2 font-medium">To</th>
              </tr>
            </thead>
            <tbody>
              {added.map((r, i) => (
                <DiffRow key={`a-${i}`} change="Added" tone="ok" label={r.mpn || r.value}
                  from={0} to={r.qty} />
              ))}
              {removed.map((r, i) => (
                <DiffRow key={`r-${i}`} change="Removed" tone="err" label={r.mpn || r.value}
                  from={r.qty} to={0} />
              ))}
              {changed.map((r, i) => (
                <DiffRow key={`c-${i}`} change="Changed" tone="warn" label={r.mpn || r.value}
                  from={r.from_qty} to={r.to_qty} />
              ))}
            </tbody>
          </table>
        </Card>
      )}
    </div>
  );
}

function DiffRow({
  change,
  tone,
  label,
  from,
  to,
}: {
  change: string;
  tone: "ok" | "err" | "warn";
  label: string;
  from: number;
  to: number;
}) {
  return (
    <tr className="border-b border-line last:border-b-0">
      <td className="px-4 py-2 align-top">
        <Badge tone={tone}>{change}</Badge>
      </td>
      <td className="px-4 py-2 align-top text-t1">{label || "-"}</td>
      <td className="px-4 py-2 align-top text-t2">{from}</td>
      <td className="px-4 py-2 align-top text-t2">{to}</td>
    </tr>
  );
}

// -- Editor: design rules + net classes (M7e) ---------------------------------

// The routing dimensions the Editor edits per net class. KiCad-internal fields
// (colors, line/wire/bus stroke, tuning_profile) are preserved by the backend
// reconcile and never surfaced here, so a save touches only the dims the UI shows.
const NC_DIMS: { key: string; label: string }[] = [
  { key: "clearance", label: "Clearance" },
  { key: "track_width", label: "Track" },
  { key: "via_diameter", label: "Via" },
  { key: "via_drill", label: "Via Drill" },
  { key: "microvia_diameter", label: "uVia" },
  { key: "microvia_drill", label: "uVia Drill" },
  { key: "diff_pair_width", label: "DP Width" },
  { key: "diff_pair_gap", label: "DP Gap" },
  { key: "priority", label: "Priority" },
];

// A brand-new class's starting dims (the backend fills the rest of the KiCad-10 fields).
const NEW_CLASS_DIMS: Record<string, string> = {
  clearance: "0.2", track_width: "0.2", via_diameter: "0.6", via_drill: "0.3",
  microvia_diameter: "0.3", microvia_drill: "0.1", diff_pair_width: "0.2",
  diff_pair_gap: "0.25", priority: "0",
};

// The Editor draft holds every dim as a string so decimals type cleanly (a number
// input reports "" mid-decimal); values coerce to numbers only at save time.
interface DraftClass {
  rowId: string;
  isNew: boolean;
  name: string;
  dims: Record<string, string>;
}

function seedDrafts(classes: NetClass[]): DraftClass[] {
  return classes.map((c) => ({
    rowId: c.name,
    isNew: false,
    name: c.name,
    dims: Object.fromEntries(
      NC_DIMS.map((d) => [d.key, c[d.key] != null ? String(c[d.key]) : ""]),
    ),
  }));
}

function seedRules(rules: DesignRules): Record<string, string | boolean> {
  return Object.fromEntries(
    Object.entries(rules).map(([k, v]) => [k, typeof v === "boolean" ? v : String(v)]),
  );
}

// The Editor: edit a project's net classes + board design rules and write each as a
// minimal-diff, one scoped commit on the project's own git (M7e). Honest states for a
// project not under git or with no .kicad_pro (neither is editable, never a crash).
function EditorSection({ projectId }: { projectId: string }) {
  const [floor, setFloor] = useState("none");
  const design = useProjectDesign(projectId, floor);
  const data = design.data;

  return (
    <div className="mt-7 border-t border-line pt-6" data-testid="editor-section">
      <div className="mb-3">
        <Eyebrow className="mb-0.5">Editor</Eyebrow>
        <p className="text-xs text-t3">
          Edit the board net classes and design rules. Each save writes a minimal change to
          the project file and commits it to the project's own git history.
        </p>
      </div>

      {design.isLoading ? (
        <p className="text-sm text-t3">Loading the project settings...</p>
      ) : design.isError ? (
        <p className="text-sm text-err">
          {errMsg(design.error, "Could not read the project settings.")}
        </p>
      ) : !data ? null : !data.has_pro ? (
        <p className="text-sm text-t3">
          This project has no .kicad_pro file, so there are no net classes or design rules to
          edit.
        </p>
      ) : !data.under_git ? (
        <p className="text-sm text-t3" data-testid="editor-no-git">
          This project is not under git. Initialize a git repository for it to edit its net
          classes and design rules, so each change is committed atomically and can be undone.
        </p>
      ) : (
        <div className="flex flex-col gap-7">
          <NetClassEditor projectId={projectId} data={data} floor={floor} onFloor={setFloor} />
          <DesignRulesEditor projectId={projectId} data={data} />
        </div>
      )}
    </div>
  );
}

function NetClassEditor({
  projectId,
  data,
  floor,
  onFloor,
}: {
  projectId: string;
  data: DesignResult;
  floor: string;
  onFloor: (f: string) => void;
}) {
  const [drafts, setDrafts] = useState<DraftClass[]>(() => seedDrafts(data.net_classes));
  const [deleted, setDeleted] = useState<string[]>([]);
  const [newCount, setNewCount] = useState(0);
  const save = useSetNetClasses();
  const { toast } = useToast();

  // Re-seed only when the on-disk classes actually change (a save commit), NOT when the
  // fab floor changes (that only re-reads validation): react-query structural sharing keeps
  // net_classes' identity stable across a floor-only refetch, so unsaved edits survive.
  useEffect(() => {
    setDrafts(seedDrafts(data.net_classes));
    setDeleted([]);
  }, [data.net_classes]);

  const dirty = deleted.length > 0 || JSON.stringify(drafts) !== JSON.stringify(seedDrafts(data.net_classes));

  function editDim(rowId: string, key: string, value: string) {
    setDrafts((ds) =>
      ds.map((d) => (d.rowId === rowId ? { ...d, dims: { ...d.dims, [key]: value } } : d)),
    );
  }

  function editName(rowId: string, name: string) {
    setDrafts((ds) => ds.map((d) => (d.rowId === rowId ? { ...d, name } : d)));
  }

  function addClass() {
    const rowId = `new-${newCount}`;
    setNewCount((n) => n + 1);
    setDrafts((ds) => [...ds, { rowId, isNew: true, name: "", dims: { ...NEW_CLASS_DIMS } }]);
  }

  function duplicate(dc: DraftClass) {
    const rowId = `new-${newCount}`;
    setNewCount((n) => n + 1);
    setDrafts((ds) => [
      ...ds,
      { rowId, isNew: true, name: `${dc.name}_copy`, dims: { ...dc.dims } },
    ]);
  }

  function removeRow(dc: DraftClass) {
    setDrafts((ds) => ds.filter((d) => d.rowId !== dc.rowId));
    if (!dc.isNew) setDeleted((del) => (del.includes(dc.name) ? del : [...del, dc.name]));
  }

  function onSave() {
    const classes: NetClass[] = drafts
      .filter((d) => d.name.trim() !== "")
      .map((d) => ({
        name: d.name.trim(),
        ...Object.fromEntries(
          NC_DIMS.filter((f) => d.dims[f.key] !== "" && d.dims[f.key] != null).map((f) => [
            f.key,
            Number(d.dims[f.key]),
          ]),
        ),
      }));
    save.mutate(
      { id: projectId, classes, deleted, floor },
      {
        onSuccess: () => toast("Net classes saved."),
        onError: (e) => toast(errMsg(e, "Could not save the net classes."), "err"),
      },
    );
  }

  const issuesByClass = new Map<string, string[]>();
  for (const v of data.validation) {
    const list = issuesByClass.get(v.netclass) ?? [];
    list.push(v.issue);
    issuesByClass.set(v.netclass, list);
  }

  return (
    <div data-testid="net-class-editor">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <h3 className="text-sm font-medium text-t1">Net Classes</h3>
          {dirty ? <Badge tone="warn">Unsaved</Badge> : null}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <label className="flex items-center gap-1.5 text-2xs text-t3">
            Fab Floor
            <select
              className={`${INPUT_CLS} w-40`}
              data-testid="fab-floor-select"
              value={floor}
              onChange={(e) => onFloor(e.target.value)}
            >
              {Object.entries(data.fab_floors).map(([key, f]) => (
                <option key={key} value={key}>
                  {f.label}
                </option>
              ))}
            </select>
          </label>
          <Button small onClick={addClass}>
            Add Net Class
          </Button>
          <Button variant="accent" small onClick={onSave} disabled={!dirty || save.isPending}>
            {save.isPending ? "Saving..." : "Save Net Classes"}
          </Button>
        </div>
      </div>

      <div className="overflow-x-auto">
        <div className="min-w-[720px]">
          <div className="flex gap-2 border-b border-line pb-1.5 text-2xs text-t3">
            <div className="w-28 shrink-0">Name</div>
            {NC_DIMS.map((d) => (
              <div key={d.key} className="w-16 shrink-0 text-right">
                {d.label}
              </div>
            ))}
            <div className="w-16 shrink-0" />
          </div>
          {drafts.map((dc) => {
            const rid = dc.isNew ? dc.rowId : dc.name;
            const issues = issuesByClass.get(dc.name) ?? [];
            return (
              <div key={dc.rowId} className="border-b border-line py-1.5" data-testid={`nc-row-${rid}`}>
                <div className="flex items-center gap-2">
                  <div className="w-28 shrink-0">
                    {dc.isNew ? (
                      <input
                        type="text"
                        className={`${INPUT_CLS} !py-1 text-xs`}
                        data-testid="nc-new-name"
                        placeholder="Name"
                        value={dc.name}
                        onChange={(e) => editName(dc.rowId, e.target.value)}
                      />
                    ) : (
                      <span className="text-xs text-t1">{dc.name}</span>
                    )}
                  </div>
                  {NC_DIMS.map((d) => (
                    <input
                      key={d.key}
                      type="text"
                      inputMode="decimal"
                      className={`${INPUT_CLS} w-16 shrink-0 !px-2 !py-1 text-right text-xs`}
                      data-testid={`nc-${rid}-${d.key}`}
                      value={dc.dims[d.key] ?? ""}
                      onChange={(e) => editDim(dc.rowId, d.key, e.target.value)}
                    />
                  ))}
                  <div className="flex w-16 shrink-0 justify-end gap-1">
                    <button
                      type="button"
                      className="text-2xs text-t3 hover:text-t1"
                      onClick={() => duplicate(dc)}
                    >
                      Copy
                    </button>
                    <button
                      type="button"
                      className="text-2xs text-err hover:opacity-80"
                      onClick={() => removeRow(dc)}
                    >
                      Delete
                    </button>
                  </div>
                </div>
                {issues.length > 0 ? (
                  <p className="mt-1 pl-1 text-2xs text-warn">{issues.join("; ")}</p>
                ) : null}
              </div>
            );
          })}
        </div>
      </div>
      {data.validation.length > 0 ? (
        <p className="mt-2 text-2xs text-t3">
          Amber rows are below the selected fab floor. They are warnings, not blockers, so you
          can still save.
        </p>
      ) : null}
    </div>
  );
}

function DesignRulesEditor({ projectId, data }: { projectId: string; data: DesignResult }) {
  const [draft, setDraft] = useState<Record<string, string | boolean>>(() =>
    seedRules(data.design_rules),
  );
  const save = useSetDesignRules();
  const { toast } = useToast();

  useEffect(() => {
    setDraft(seedRules(data.design_rules));
  }, [data.design_rules]);

  const dirty = JSON.stringify(draft) !== JSON.stringify(seedRules(data.design_rules));
  const keys = Object.keys(data.design_rules).sort();

  function onSave() {
    const rules: DesignRules = Object.fromEntries(
      Object.entries(draft).map(([k, v]) => [k, typeof v === "boolean" ? v : Number(v)]),
    );
    save.mutate(
      { id: projectId, rules },
      {
        onSuccess: () => toast("Design rules saved."),
        onError: (e) => toast(errMsg(e, "Could not save the design rules."), "err"),
      },
    );
  }

  return (
    <div data-testid="design-rules-editor">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <h3 className="text-sm font-medium text-t1">Design Rules</h3>
          {dirty ? <Badge tone="warn">Unsaved</Badge> : null}
        </div>
        <Button variant="accent" small onClick={onSave} disabled={!dirty || save.isPending}>
          {save.isPending ? "Saving..." : "Save Design Rules"}
        </Button>
      </div>
      <div className="grid grid-cols-2 gap-x-4 gap-y-2 sm:grid-cols-3">
        {keys.map((key) => {
          const v = draft[key];
          if (typeof v === "boolean") {
            return (
              <label key={key} className="flex items-center gap-2 text-2xs text-t2">
                <input
                  type="checkbox"
                  data-testid={`dr-${key}`}
                  checked={v}
                  onChange={(e) => setDraft((d) => ({ ...d, [key]: e.target.checked }))}
                />
                {key}
              </label>
            );
          }
          return (
            <label key={key} className="flex flex-col gap-0.5 text-2xs text-t3">
              {key}
              <input
                type="text"
                inputMode="decimal"
                className={`${INPUT_CLS} !py-1 text-xs`}
                data-testid={`dr-${key}`}
                value={String(v ?? "")}
                onChange={(e) => setDraft((d) => ({ ...d, [key]: e.target.value }))}
              />
            </label>
          );
        })}
      </div>
    </div>
  );
}
