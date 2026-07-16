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
import { useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { ApiError, api } from "../api/client";
import {
  useProjectsQuery,
  useProjectQuery,
  useBuildability,
  useProjectAudit,
  useProjectBom,
  useProjectChecks,
  useProjectFab,
  useProjectRevisions,
  useProjectDesign,
  useSetNetClasses,
  useSetDesignRules,
  useSetNetclassPatterns,
  useProjectSettings,
  useSetProjectSettings,
  useProjectConform,
  usePreviewConform,
  useApplyConform,
  useProjectStackup,
  usePreviewStackup,
  useApplyStackup,
  useProjectPrepare,
  useInvalidateAfterPrepare,
  useProjectFields,
  useSetFields,
  useManualFill,
  useRestore,
  usePartsQuery,
  useBomDiff,
  useRegisterProject,
  useDeleteProject,
  useRepriceBom,
} from "../api/queries";
import type {
  AuditFinding,
  AuditResult,
  Buildability,
  BoardSetupField,
  BoardSetupValue,
  BomDiffResult,
  BomExportKind,
  BomLine,
  BomResult,
  BuildRollup,
  CheckFinding,
  CheckRun,
  ChecksResult,
  ConformBody,
  ConformCatalog,
  ConformCategory,
  ConformPreview,
  ConformTarget,
  Stackup,
  StackupBody,
  StackupLayer,
  StackupLayerEdit,
  StackupPreview,
  StackupRead,
  PrepareRead,
  PrepareResult,
  CompletionRoll,
  DesignResult,
  DesignRules,
  FabExportOptions,
  FabStatus,
  FieldRow,
  FieldEdit,
  NetClass,
  ProcurementExportOptions,
  SourcingRisks,
  LeadTime,
  ProjectSummary,
  BoardSettings,
} from "../api/types";
import { useJob } from "../lib/useJob";
import { useToast } from "../lib/toast";
import {
  Badge,
  Button,
  Card,
  Dot,
  Eyebrow,
  TabPanel,
  TabStrip,
  type TabItem,
} from "../components/primitives";
import { ProjectViewer, type ViewFile } from "../components/ProjectViewer";
import { ConfirmDialog } from "../components/ConfirmDialog";
import { ExternalIcon } from "../components/icons";

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
              key={selected.id}
              project={selected}
              onRemove={() => setPendingDelete(selected)}
              removeBusy={del.isPending}
            />
          ) : (
            <div className="flex h-full min-h-[300px] items-center justify-center text-sm text-t3">
              {projectsQuery.isLoading
                ? "Loading projects..."
                : "Select a project to see its health."}
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
      <div className="px-3 py-8 text-center text-sm text-t3">Loading projects...</div>
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

// The selected project was ONE long scroll of 14 stacked sections (owner: "the ia
// is still really bad"). It is now five per-project tabs, mirroring the Library
// fold and the north-star Projects shape: Overview (the readiness verdict + board
// viewer), Health (audit findings + ERC/DRC + Prepare), BOM & Procurement (build,
// cost, orderability, revision diff, fab exports), PCB Setup (board/stackup/conform/
// checks-config/meta editors), and Net Classes (net classes + design rules + patterns).
type ProjectTab = "overview" | "health" | "bom" | "setup" | "netclasses";

const PROJECT_TABS: readonly TabItem<ProjectTab>[] = [
  { id: "overview", label: "Overview" },
  { id: "health", label: "Health" },
  { id: "bom", label: "BOM & Procurement" },
  { id: "setup", label: "PCB Setup" },
  { id: "netclasses", label: "Net Classes" },
];

// Sections carry a leading `mt-7 border-t pt-6` divider to separate them when
// stacked. Whichever section renders FIRST in a tab has that divider stripped, so
// the tab strip is not followed by a stray rule and a large gap.
const TAB_BODY_CLS =
  "[&>*:first-child]:mt-0 [&>*:first-child]:border-t-0 [&>*:first-child]:pt-0";

function ProjectDetailView({
  project,
  onRemove,
  removeBusy,
}: {
  project: ProjectSummary;
  onRemove: () => void;
  removeBusy: boolean;
}) {
  // The whole view is keyed by project id at the call site, so a project switch
  // remounts it and this lands back on Overview with a fresh, flash-free state (no
  // post-paint reset effect, no stale tab briefly rendered against the new project).
  const [tab, setTab] = useState<ProjectTab>("overview");

  return (
    <div className="max-w-[860px] pb-12">
      <div className="mb-4 flex items-start justify-between gap-4">
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

      <TabStrip
        tabs={PROJECT_TABS}
        active={tab}
        onSelect={setTab}
        idBase="project"
        className="mb-6"
        aria-label="Project sections"
      />

      <TabPanel idBase="project" tab={tab} className={TAB_BODY_CLS}>
        {tab === "overview" ? (
          <OverviewTab projectId={project.id} />
        ) : tab === "health" ? (
          <HealthTab projectId={project.id} />
        ) : tab === "bom" ? (
          <BomTab projectId={project.id} />
        ) : tab === "setup" ? (
          <SetupTab projectId={project.id} />
        ) : (
          <NetClassesTab projectId={project.id} />
        )}
      </TabPanel>
    </div>
  );
}

// Overview: the readiness verdict card and the board viewer.
function OverviewTab({ projectId }: { projectId: string }) {
  return (
    <>
      <BuildabilitySection projectId={projectId} />
      <ProjectViewerSection projectId={projectId} />
    </>
  );
}

// Health: the audit findings table (with its kind filter), the ERC/DRC checks, and
// Prepare This Project (Fix-All + Restore). The audit query is scoped here so it
// loads only when Health is open, not on every project select.
function HealthTab({ projectId }: { projectId: string }) {
  const auditQuery = useProjectAudit(projectId);
  // The active kind filter for the findings table. null = show every finding.
  const [kindFilter, setKindFilter] = useState<string | null>(null);

  return (
    <>
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

      <ChecksSection projectId={projectId} />
      <PrepareSection projectId={projectId} />
    </>
  );
}

// BOM & Procurement: build and cost, per-line orderability, revision diff, and the
// fab (gerber/drill/placement) exports.
function BomTab({ projectId }: { projectId: string }) {
  return (
    <>
      <BomSection projectId={projectId} />
      <BomExportsSection projectId={projectId} />
      <RevisionDiffSection projectId={projectId} />
      <FabSection projectId={projectId} />
    </>
  );
}

// PCB Setup: the master-detail editors for the physical board and project settings
// (board setup + thickness, ERC/DRC severities + pin map + text variables, stackup,
// object conform, and the project title-block fields).
function SetupTab({ projectId }: { projectId: string }) {
  return (
    <>
      <BoardSetupSection projectId={projectId} />
      <ProSettingsSection projectId={projectId} />
      <StackupSection projectId={projectId} />
      <ConformSection projectId={projectId} />
      <FieldsSection projectId={projectId} />
    </>
  );
}

// Net Classes: net classes, board design rules, and netclass patterns.
function NetClassesTab({ projectId }: { projectId: string }) {
  return <EditorSection projectId={projectId} />;
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
          {audit.unresolved_footprints} could not be resolved from your components.
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
const BUILD_SIGNAL_LABEL: Record<string, string> = {
  pass: "Pass",
  clean: "Clean",
  fail: "Issues",
  warn: "Warnings",
  not_run: "Not Run",
  not_built: "Not Built",
  dirty: "Uncommitted",
  not_git: "No Git",
};

function buildSignalTone(state: string): "ok" | "warn" | "err" {
  if (state === "pass" || state === "clean") return "ok";
  if (state === "fail" || state === "not_run" || state === "not_built") return "err";
  return "warn"; // warn / dirty / not_git
}

function BuildabilitySection({ projectId }: { projectId: string }) {
  const build = useBuildability(projectId);
  const checks = useProjectChecks(projectId);
  const bom = useProjectBom(projectId);
  const qc = useQueryClient();
  // Keep the verdict live: refetch it whenever the checks / BOM caches change (a run, a
  // build, or an editor write that evicts them), so it never disagrees with the sections
  // below. Those queries are always mounted in the detail.
  const checksAt = checks.dataUpdatedAt;
  const bomAt = bom.dataUpdatedAt;
  useEffect(() => {
    qc.invalidateQueries({ queryKey: ["project-buildability", projectId] });
  }, [checksAt, bomAt, projectId, qc]);

  if (build.isLoading) {
    return (
      <Card className="mb-5 px-4 py-3.5" data-testid="buildability-section">
        <p className="py-1 text-sm text-t3">Checking buildability...</p>
      </Card>
    );
  }
  if (build.isError || !build.data) {
    return (
      <Card className="mb-5 px-4 py-3.5" data-testid="buildability-section">
        <p className="py-1 text-sm text-err">
          {errMsg(build.error, "Could not compute buildability.")}
        </p>
      </Card>
    );
  }
  const v: Buildability = build.data;
  const signals: { key: string; label: string; state: string }[] = [
    { key: "completeness", label: "Completeness", state: v.signals.completeness.state },
    { key: "checks", label: "Rules Check", state: v.signals.checks.state },
    { key: "bom", label: "BOM", state: v.signals.bom.state },
    { key: "git", label: "Version Control", state: v.signals.git.state },
  ];
  return (
    <Card className="mb-5 p-4" data-testid="buildability-section">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <Eyebrow className="mb-0.5">Buildability</Eyebrow>
          <p className="text-xs text-t3">
            One verdict across completeness, rules, sourcing, and version control.
          </p>
        </div>
        <Badge tone={v.ready ? "ok" : "err"} className="text-sm">
          {v.ready ? "Ready to Build" : "Not Ready"}
        </Badge>
      </div>

      <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-4">
        {signals.map((s) => (
          <div
            key={s.key}
            className="rounded-control border border-line bg-raise px-2.5 py-2"
          >
            <div className="text-xs text-t3">{s.label}</div>
            <div className="mt-0.5 flex items-center gap-1.5">
              <Dot tone={buildSignalTone(s.state)} />
              <span className="text-sm font-medium text-t1">
                {BUILD_SIGNAL_LABEL[s.state] ?? s.state}
              </span>
            </div>
          </div>
        ))}
      </div>

      {v.blockers.length > 0 ? (
        <div className="mt-3.5">
          <div className="mb-1 text-xs font-semibold text-t2">Blockers</div>
          <ul className="space-y-1">
            {v.blockers.map((b, i) => (
              <li key={`b-${i}`} className="flex items-start gap-2 text-sm text-t1">
                <span className="mt-1.5">
                  <Dot tone="err" />
                </span>
                <span>
                  {b.detail}. <span className="text-t3">{b.next_step}.</span>
                </span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {v.warnings.length > 0 ? (
        <div className="mt-3.5">
          <div className="mb-1 text-xs font-semibold text-t2">Warnings</div>
          <ul className="space-y-1">
            {v.warnings.map((w, i) => (
              <li key={`w-${i}`} className="flex items-start gap-2 text-sm text-t2">
                <span className="mt-1.5">
                  <Dot tone="warn" />
                </span>
                <span>
                  {w.detail}. <span className="text-t3">{w.next_step}.</span>
                </span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </Card>
  );
}

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

// -- Build And Cost (BOM grouping + cost, M7c + build-economics reprice) -----

const BUILD_QTY_KEY = "sr.bom.buildQty";
const TAX_RATE_KEY = "sr.bom.taxRate";

function formatMoney(n: number, currency: string): string {
  const sym = currency === "USD" ? "$" : "";
  return `${sym}${n.toFixed(2)}`;
}

// A per-line build-economics cell: "-" for a field that was never priced, never a
// fabricated $0.00.
function moneyOrDash(n: number | null | undefined, currency = "USD"): string {
  return n == null ? "-" : formatMoney(n, currency);
}

// A guided-input value persisted in localStorage so the Build Quantity / Tax-Tariff inputs
// "stick" across an app restart. A read/write failure (private mode, quota) falls back to
// the given default for this session only, never a crash.
function readStoredNumber(key: string, fallback: number): number {
  try {
    const raw = window.localStorage.getItem(key);
    if (raw == null) return fallback;
    const n = Number(raw);
    return Number.isFinite(n) ? n : fallback;
  } catch {
    return fallback;
  }
}

function writeStoredNumber(key: string, value: number): void {
  try {
    window.localStorage.setItem(key, String(value));
  } catch {
    /* storage unavailable; the input still works for this session */
  }
}

// The Build And Cost section: build a grouped, priced BOM as a job, then show the cached
// result. Keyed by project id in the parent so its job state never leaks across a switch.
// Honest states throughout: a project with no parts is "Nothing to Build", a build whose
// parts could not be sourced is "Unpriced" (never a fabricated cost), and an unbuilt
// project shows a "not built yet" prompt.
//
// Build Quantity and Tax/Tariff are two guided inputs (a stepper, a percent field) seeded
// from the cached build and persisted in localStorage so they stick across a restart. A
// change reprices the ALREADY-BUILT BOM instantly (POST .../bom/reprice, no rebuild,
// debounced ~400ms or applied immediately on blur) so the table and roll-up never sit
// stale on the old quantity; before a build the values are simply held for the next run.
function BomSection({ projectId }: { projectId: string }) {
  const bomQuery = useProjectBom(projectId);
  const job = useJob<BomResult>();
  const qc = useQueryClient();
  const { toast } = useToast();
  const reprice = useRepriceBom();
  const [starting, setStarting] = useState(false);
  const [startError, setStartError] = useState<string | null>(null);
  const [boards, setBoardsState] = useState<number>(() => readStoredNumber(BUILD_QTY_KEY, 1));
  const [taxRate, setTaxRateState] = useState<number>(() => readStoredNumber(TAX_RATE_KEY, 0));
  const seededRef = useRef(false);
  const repriceTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (job.status === "done") {
      qc.invalidateQueries({ queryKey: ["project-bom", projectId] });
      // A fresh build changes the diff's cost side (sourcing is now folded into the BOM result).
      qc.invalidateQueries({ queryKey: ["project-diff", projectId] });
    }
  }, [job.status, projectId, qc]);

  const data: BomResult | null =
    job.status === "done" && job.result ? job.result : (bomQuery.data ?? null);
  const hasBuilt = data != null && data.ran_at != null;

  // Seed the guided inputs from the loaded build the FIRST time data arrives, but only
  // where nothing was persisted yet: a persisted value is the deliberate last-used
  // setting and always wins, so it sticks across both a project switch and a restart.
  useEffect(() => {
    if (seededRef.current || !data) return;
    seededRef.current = true;
    if (window.localStorage.getItem(BUILD_QTY_KEY) == null) {
      setBoardsState(data.build?.build_qty ?? 1);
    }
    if (window.localStorage.getItem(TAX_RATE_KEY) == null) {
      setTaxRateState(data.tax_rate ?? 0);
    }
  }, [data]);

  useEffect(() => {
    return () => {
      if (repriceTimer.current) clearTimeout(repriceTimer.current);
    };
  }, []);

  async function doReprice(nextBoards: number, nextTax: number) {
    if (!hasBuilt) return; // hold the values for the next build; nothing to reprice yet
    try {
      await reprice.mutateAsync(
        { id: projectId, boards: nextBoards, tax_rate: nextTax },
        {
          onSuccess: (result) => {
            qc.setQueryData(["project-bom", projectId], result);
            // A reprice changes the diff's cost side exactly like a rebuild does.
            qc.invalidateQueries({ queryKey: ["project-diff", projectId] });
          },
        },
      );
    } catch (e) {
      toast(errMsg(e, "Could not reprice the BOM."), "err");
    }
  }

  function scheduleReprice(nextBoards: number, nextTax: number) {
    if (repriceTimer.current) clearTimeout(repriceTimer.current);
    repriceTimer.current = setTimeout(() => {
      repriceTimer.current = null;
      void doReprice(nextBoards, nextTax);
    }, 400);
  }

  // Applied on blur: fires the pending reprice immediately instead of waiting out the
  // debounce, so tabbing away from the field feels instant.
  function applyPendingNow() {
    if (!repriceTimer.current) return;
    clearTimeout(repriceTimer.current);
    repriceTimer.current = null;
    void doReprice(boards, taxRate);
  }

  function onBoardsChange(n: number) {
    const v = Number.isFinite(n) ? Math.max(1, Math.round(n)) : 1;
    setBoardsState(v);
    writeStoredNumber(BUILD_QTY_KEY, v);
    scheduleReprice(v, taxRate);
  }

  function onTaxChange(n: number) {
    const v = Number.isFinite(n) && n >= 0 ? n : 0;
    setTaxRateState(v);
    writeStoredNumber(TAX_RATE_KEY, v);
    scheduleReprice(boards, v);
  }

  async function onRun() {
    setStarting(true);
    setStartError(null);
    try {
      const { job_id } = await api.runBom(projectId, { boards, tax_rate: taxRate });
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

  return (
    <div className="mt-7 border-t border-line pt-6" data-testid="bom-section">
      <div className="mb-3 flex flex-wrap items-end justify-between gap-3">
        <div>
          <Eyebrow className="mb-0.5">Build And Cost</Eyebrow>
          <p className="text-xs text-t3">
            Group the schematic into a Bill of Materials and price it through the enrich
            layer.
          </p>
        </div>
        <div className="flex flex-wrap items-end gap-3">
          <BuildQuantityStepper
            value={boards}
            onChange={onBoardsChange}
            onApplyNow={applyPendingNow}
            disabled={busy}
          />
          <TaxTariffInput
            value={taxRate}
            onChange={onTaxChange}
            onApplyNow={applyPendingNow}
            disabled={busy}
          />
          <Button variant="accent" small onClick={onRun} disabled={busy}>
            {busy ? "Building..." : hasBuilt ? "Rebuild BOM" : "Build And Cost"}
          </Button>
        </div>
      </div>

      {busy && job.progress?.message ? (
        <p className="mb-2 text-xs text-t3">{job.progress.message}...</p>
      ) : null}
      {reprice.isPending ? <p className="mb-2 text-xs text-t3">Repricing...</p> : null}
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

// A stepper (- / + plus a bare numeric field) for the Build Quantity guided input: a
// whole-number board count, minimum 1. Reads and buttons alike route through `onChange` so
// every path (typing, clicking) shares the same clamp + persist + reprice-schedule.
function BuildQuantityStepper({
  value,
  onChange,
  onApplyNow,
  disabled,
}: {
  value: number;
  onChange: (n: number) => void;
  onApplyNow: () => void;
  disabled?: boolean;
}) {
  // The input's own draft string, separate from the clamped `value` it reflects: a plain
  // controlled `value={value}` would re-round every keystroke (typing "5" over a cleared
  // field would land as "1" mid-edit, so "5" lands after it as "15"). The draft only syncs
  // FROM the committed value (buttons, blur-revert, a prop change from a reprice); typing
  // free-edits the draft and commits upward the moment it parses to a real number.
  const [draft, setDraft] = useState(String(value));
  useEffect(() => setDraft(String(value)), [value]);

  return (
    <label className="flex flex-col gap-1 text-2xs text-t3">
      Build Quantity
      <div className="flex h-[31px] items-stretch overflow-hidden rounded-control border border-line2 bg-field">
        <button
          type="button"
          aria-label="Decrease Build Quantity"
          className="flex w-7 flex-none items-center justify-center text-t2 transition-colors hover:bg-raise2 hover:text-t1 disabled:cursor-not-allowed disabled:opacity-50"
          onClick={() => onChange(value - 1)}
          disabled={disabled || value <= 1}
        >
          -
        </button>
        <input
          type="number"
          inputMode="numeric"
          min={1}
          step={1}
          data-testid="build-qty-input"
          aria-label="Build Quantity"
          className="w-14 flex-none border-x border-line2 bg-field text-center text-sm text-t1 outline-none focus:border-acc disabled:opacity-50"
          value={draft}
          disabled={disabled}
          onChange={(e) => {
            setDraft(e.target.value);
            const n = Number(e.target.value);
            if (e.target.value.trim() !== "" && Number.isFinite(n)) onChange(n);
          }}
          onBlur={() => {
            setDraft(String(value)); // revert an invalid/empty draft to the last committed value
            onApplyNow();
          }}
        />
        <button
          type="button"
          aria-label="Increase Build Quantity"
          className="flex w-7 flex-none items-center justify-center text-t2 transition-colors hover:bg-raise2 hover:text-t1 disabled:cursor-not-allowed disabled:opacity-50"
          onClick={() => onChange(value + 1)}
          disabled={disabled}
        >
          +
        </button>
      </div>
    </label>
  );
}

// The Tax/Tariff guided input: a percent field with a `%` suffix affordance, minimum 0,
// quarter-point steps (fine enough for a real tariff schedule). Same draft/commit split as
// the Build Quantity stepper, so typing "9.5" over a cleared field never mangles into "09.5".
function TaxTariffInput({
  value,
  onChange,
  onApplyNow,
  disabled,
}: {
  value: number;
  onChange: (n: number) => void;
  onApplyNow: () => void;
  disabled?: boolean;
}) {
  const [draft, setDraft] = useState(String(value));
  useEffect(() => setDraft(String(value)), [value]);

  return (
    <label className="flex flex-col gap-1 text-2xs text-t3">
      Tax/Tariff
      <div className="flex h-[31px] items-stretch overflow-hidden rounded-control border border-line2 bg-field">
        <input
          type="number"
          min={0}
          step={0.25}
          data-testid="tax-rate-input"
          aria-label="Tax/Tariff Percent"
          className="w-16 flex-none bg-field pl-3 text-sm text-t1 outline-none focus:border-acc disabled:opacity-50"
          value={draft}
          disabled={disabled}
          onChange={(e) => {
            setDraft(e.target.value);
            const n = Number(e.target.value);
            if (e.target.value.trim() !== "" && Number.isFinite(n)) onChange(n);
          }}
          onBlur={() => {
            setDraft(String(value));
            onApplyNow();
          }}
        />
        <span className="flex w-6 flex-none items-center justify-center border-l border-line2 text-xs text-t3">
          %
        </span>
      </div>
    </label>
  );
}

// A BOM cost source ("library" / "mouser" / "digikey") as a Title Case chip label. "library" is
// your own combined library, priced offline from its stored data before any distributor.
function titleCaseSource(name: string): string {
  // The "library" source is your own combined components, priced offline; show it
  // as "Components" while the underlying source value stays "library".
  if (name.trim().toLowerCase() === "library") return "Components";
  return name.replace(/\b\w/g, (c) => c.toUpperCase());
}

// Known distributor hosts, so a line's purchase URL can name the real vendor even when its
// stored source is something generic (e.g. "library", priced offline from a Mouser link
// saved on the part) - the same host-mapping idiom the part detail's Sourcing card uses.
const _KNOWN_VENDOR_HOSTS: Record<string, string> = {
  lcsc: "LCSC",
  mouser: "Mouser",
  digikey: "DigiKey",
};

// The BOM line Vendor cell: map a known distributor host from the purchase URL first, else
// Title Case the stored source. "-" when the line carries neither (never a fabricated vendor).
function vendorLabel(source: string, url?: string): string {
  let host = "";
  try {
    host = url ? new URL(url).hostname.toLowerCase() : "";
  } catch {
    host = "";
  }
  for (const [token, name] of Object.entries(_KNOWN_VENDOR_HOSTS)) {
    if (host.includes(token)) return name;
  }
  const s = (source || "").trim();
  return s ? titleCaseSource(s) : "-";
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
            {titleCaseSource(name)}{" "}
            {formatMoney(sources[name].total_cost, result.by_source?.currency ?? "USD")}
          </span>
        ))}
      </div>

      {result.risks ? (
        <BomRiskHeadline risks={result.risks} lead={result.lead} priced={result.priced} />
      ) : null}

      {result.build && result.priced ? <BuildRollupLine build={result.build} /> : null}

      {result.lines.length === 0 ? (
        <p className="text-xs text-t3">No parts to build a BOM from.</p>
      ) : (
        <BomLinesTable lines={result.lines} />
      )}
    </div>
  );
}

// The sourcing-risk headline, folded onto the one BOM page (was the separate Procurement
// section): the failures worth catching before ordering (NRND, no stock, short lines) plus
// the critical-path lead time. Honest: a clean priced build reads "No Sourcing Risks"; an
// unpriced build notes that stock is unknown, not a risk.
function BomRiskHeadline({
  risks,
  lead,
  priced,
}: {
  risks: SourcingRisks;
  lead?: LeadTime;
  priced: boolean;
}) {
  return (
    <div className="flex flex-wrap items-center gap-2.5" data-testid="bom-risk-rollup">
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
      {lead?.any && lead.max_weeks != null ? (
        <span className="text-xs text-t3">
          Critical path {lead.max_weeks} wk{lead.critical_mpn ? ` (${lead.critical_mpn})` : ""}
        </span>
      ) : null}
      {!priced ? (
        <span className="text-2xs text-t3">Unpriced build: stock is unknown, not a risk.</span>
      ) : null}
    </div>
  );
}

// The build-size cost roll-up: subtotal, tax + tariff, and an emphasized grand total, for
// the N boards the cached BOM was last (re)priced at.
function BuildRollupLine({ build }: { build: BuildRollup }) {
  return (
    <div
      className="flex flex-wrap items-center gap-4 rounded-control border border-line2 bg-raise2 px-3 py-2"
      data-testid="bom-build-rollup"
    >
      <span className="text-2xs text-t3">
        For {build.build_qty} Board{build.build_qty === 1 ? "" : "s"}
      </span>
      <span className="text-xs text-t2">
        Subtotal {formatMoney(build.subtotal, build.currency)}
      </span>
      <span className="text-xs text-t2">
        Tax + Tariff {formatMoney(build.tax_total, build.currency)}
      </span>
      <span className="text-sm font-semibold text-t1">
        Grand Total {formatMoney(build.grand_total, build.currency)}
      </span>
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

// The distributor's own part number for a priced line, matched to its Source (LCSC -> lcsc_pn,
// Mouser -> mouser_pn, DigiKey -> digikey_pn), else whichever is present. Mirrors the backend
// _dist_pn so the on-screen Distributor P/N agrees with the export.
function distPn(line: BomLine): string {
  const src = (line.source || "").trim().toLowerCase();
  const lcsc = (line.lcsc_pn || "").trim();
  const mouser = (line.mouser_pn || "").trim();
  const digikey = (line.digikey_pn || "").trim();
  if (src === "lcsc") return lcsc || mouser || digikey;
  if (src === "mouser") return mouser || lcsc || digikey;
  if (src === "digikey") return digikey || mouser || lcsc;
  return lcsc || mouser || digikey;
}

// A KiCad footprint name without its library prefix (Resistor_SMD:R_0603 -> R_0603), for a
// compact Footprint column; the full name stays in the cell title.
function shortFootprint(fp: string): string {
  return (fp || "").split(":").pop() || "";
}

// A compact icon link that opens a datasheet or product page in a new tab; "-" when the line
// carries no URL (never a dead link).
function IconLink({ href, label }: { href?: string; label: string }) {
  if (!href) return <span className="text-t3">-</span>;
  return (
    <a
      href={href}
      target="_blank"
      rel="noreferrer"
      aria-label={label}
      title={label}
      className="inline-flex text-t2 hover:text-t1"
    >
      <ExternalIcon />
    </a>
  );
}

// The Stock cell, folded from the retired Procurement table: the known count, tinted by the
// per-line stock risk (red at 0, amber when short of the run) with the required quantity when
// short; "Unknown" when the line was never priced (unknown is never a risk).
function BomStockCell({ line }: { line: BomLine }) {
  const risk = line.stock_risk;
  if (!risk || risk.available == null) {
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

// The RoHS cell: a compact compliance verdict. "Yes" reads as an ok badge, "No" as an error
// badge, an unreadable value as muted text; "-" when unknown (never a guessed compliance).
function RohsCell({ value }: { value?: string }) {
  const v = (value || "").trim();
  if (!v) return <span className="text-t3">-</span>;
  if (v.toLowerCase() === "yes") return <Badge tone="ok">Yes</Badge>;
  if (v.toLowerCase() === "no") return <Badge tone="err">No</Badge>;
  return <span className="text-2xs text-t2">{v}</span>;
}

// The one wide BOM table (the "perfect BOM"): every field its own column, spreadsheet-style,
// scrolling horizontally inside its own container so the page body never does. Identity +
// package + sourcing (Vendor / Distributor P/N / Stock / Lifecycle / Lead) + the datasheet and
// product links + RoHS, then the per-line build economics (Min Qty / Final Qty / Unit Cost /
// Cost @ Qty / Tax/Tariff / Total Cost) at the current Build Quantity + Tax/Tariff. Every cell
// reads "-" when its value is absent, so an unpriced line still lines up the columns.
const BOM_COLUMNS = [
  "Reference", "Qty", "Value", "Library", "Description", "MPN", "Manufacturer", "Footprint", "Package",
  "Vendor", "Distributor P/N", "Stock", "Lifecycle", "Lead", "Datasheet", "Product Link", "RoHS",
  "Min Qty", "Final Qty", "Unit Cost", "Cost @ Qty", "Tax/Tariff", "Total Cost",
];

function BomLinesTable({ lines }: { lines: BomLine[] }) {
  const known = lines.filter((l) => l.in_library !== undefined);
  const covered = known.filter((l) => l.in_library).length;
  return (
    <>
      {known.length > 0 ? (
        <div className="mb-2 text-xs text-t3" data-testid="bom-coverage">
          <span className="text-t2">{covered}</span> of {known.length}{" "}
          {known.length === 1 ? "line is" : "lines are"} in your library
          {covered < known.length ? " (add the rest from the Components tab)" : ""}.
        </div>
      ) : null}
      <Card className="overflow-hidden" data-testid="bom-lines">
      <div className="overflow-x-auto">
        <table className="w-full min-w-[1680px] text-left text-sm">
          <thead>
            <tr className="border-b border-line text-2xs text-t3">
              {BOM_COLUMNS.map((c) => (
                <th key={c} className="whitespace-nowrap px-3 py-2 font-medium">
                  {c}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {lines.map((line, i) => (
              <BomLineRow key={`${line.mpn || line.value}-${i}`} line={line} />
            ))}
          </tbody>
        </table>
      </div>
    </Card>
    </>
  );
}

function BomLineRow({ line }: { line: BomLine }) {
  const refsText = line.refs.join(", ");
  const fp = shortFootprint(line.footprint);
  const dist = distPn(line);
  const lifecycle = (line.lifecycle || "").trim();
  return (
    <tr className="border-b border-line last:border-b-0">
      <td className="max-w-[9rem] truncate px-3 py-2 align-top text-t2" title={refsText}>
        {refsText || "-"}
      </td>
      <td className="px-3 py-2 align-top text-t2">{line.qty}</td>
      <td className="px-3 py-2 align-top text-t1">{line.value || "-"}</td>
      <td className="px-3 py-2 align-top">
        {line.in_library === undefined ? (
          <span className="text-t3">-</span>
        ) : line.in_library ? (
          <Badge tone="ok" size="sm">In Library</Badge>
        ) : (
          <Badge tone="neutral" size="sm">Not in Library</Badge>
        )}
      </td>
      <td
        className="max-w-[14rem] truncate px-3 py-2 align-top text-2xs text-t3"
        title={line.description}
      >
        {line.description || "-"}
      </td>
      <td className="px-3 py-2 align-top">
        {line.mpn ? (
          <span className="font-mono text-xs text-t2">{line.mpn}</span>
        ) : line.basic ? (
          <Badge tone="neutral">Basic</Badge>
        ) : (
          <Badge tone="neutral">No MPN</Badge>
        )}
      </td>
      <td className="px-3 py-2 align-top text-2xs text-t3">{line.manufacturer || "-"}</td>
      <td className="max-w-[11rem] truncate px-3 py-2 align-top text-2xs text-t3" title={line.footprint}>
        {fp || "-"}
      </td>
      <td className="px-3 py-2 align-top text-t2">{line.package || "-"}</td>
      <td className="px-3 py-2 align-top text-t2">{vendorLabel(line.source ?? "", line.url)}</td>
      <td className="px-3 py-2 align-top font-mono text-2xs text-t3">{dist || "-"}</td>
      <td className="px-3 py-2 align-top">
        <BomStockCell line={line} />
      </td>
      <td className="px-3 py-2 align-top text-2xs">
        {lifecycle ? (
          <span className={lifecycle.toLowerCase() === "active" ? "text-t3" : "text-warn"}>
            {lifecycle}
          </span>
        ) : (
          <span className="text-t3">-</span>
        )}
      </td>
      <td className="px-3 py-2 align-top text-2xs text-t3">{line.lead_time || "-"}</td>
      <td className="px-3 py-2 align-top">
        <IconLink href={line.datasheet} label="Datasheet" />
      </td>
      <td className="px-3 py-2 align-top">
        <IconLink href={line.url} label="Product Page" />
      </td>
      <td className="px-3 py-2 align-top">
        <RohsCell value={line.rohs} />
      </td>
      <td className="px-3 py-2 align-top text-t2">{line.moq ?? "-"}</td>
      <td className="px-3 py-2 align-top text-t2">{line.final_qty ?? "-"}</td>
      <td className="px-3 py-2 align-top text-t2">{moneyOrDash(line.final_unit_price)}</td>
      <td className="px-3 py-2 align-top text-t2">{moneyOrDash(line.final_extended)}</td>
      <td className="px-3 py-2 align-top text-t2">{moneyOrDash(line.tax_tariff)}</td>
      <td className="px-3 py-2 align-top font-medium text-t1">{moneyOrDash(line.line_total)}</td>
    </tr>
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

// The Exports section on the one BOM page (the sourcing risk + per-line orderability are now
// folded into the BOM table above): the purchasing-sheet knobs and the export bar. Gated on the
// cached BOM's built state (read from the same project-bom query the table uses, so the two
// never disagree): before a build it prompts to build, never a dead export.
function BomExportsSection({ projectId }: { projectId: string }) {
  const bomQuery = useProjectBom(projectId);
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

  const built = bomQuery.data != null && bomQuery.data.ran_at != null;

  return (
    <div className="mt-7 border-t border-line pt-6" data-testid="exports-section">
      <div className="mb-3">
        <Eyebrow className="mb-0.5">Exports</Eyebrow>
        <p className="text-xs text-t3">
          Purchasing sheets and vendor uploads from the priced BOM.
        </p>
      </div>

      {bomQuery.isLoading ? (
        <p className="text-sm text-t3">Loading the last build...</p>
      ) : !built ? (
        <p className="text-sm text-t3">Build the BOM to export the purchasing sheets.</p>
      ) : (
        <div className="flex flex-col gap-4" data-testid="exports-result">
          <ExportOptionsForm opts={opts} onChange={setOpts} />
          <ExportBar onExport={onExport} downloading={downloading} />
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

// What each export format is, so the picked format explains itself instead of the buyer
// guessing from a terse button label.
const EXPORT_HELP: Record<BomExportKind, string> = {
  csv: "The full grouped BOM as a CSV.",
  xlsx: "The full grouped BOM as an Excel workbook.",
  priced: "The priced purchasing sheet: unit and extended cost per line.",
  procurement: "The procurement sheet with spares, tax, shipping and assembly applied.",
  cart: "A Mouser cart upload: part numbers and quantities.",
  jlcpcb: "A JLCPCB assembly BOM.",
};

// One export control, not a row of six buttons (the formats are one choice, not six actions):
// pick a format, read what it is, then Export. Keeps a single primary action and lets the format
// list grow without crowding the page.
function ExportBar({
  onExport,
  downloading,
}: {
  onExport: (kind: BomExportKind) => void;
  downloading: BomExportKind | null;
}) {
  const [kind, setKind] = useState<BomExportKind>("csv");
  const busy = downloading != null;
  return (
    <div className="flex flex-wrap items-end gap-3" data-testid="export-bar">
      <label className="flex flex-col gap-1 text-2xs text-t3">
        Export Format
        <select
          className={`${INPUT_CLS} w-52`}
          data-testid="export-format"
          value={kind}
          disabled={busy}
          onChange={(e) => setKind(e.target.value as BomExportKind)}
        >
          {EXPORT_KINDS.map(({ kind: k, label }) => (
            <option key={k} value={k}>
              {label}
            </option>
          ))}
        </select>
      </label>
      <Button variant="accent" small onClick={() => onExport(kind)} disabled={busy}>
        {busy ? "Saving..." : "Export"}
      </Button>
      <p className="mb-1.5 max-w-xs text-2xs text-t3">{EXPORT_HELP[kind]}</p>
    </div>
  );
}

// -- Board viewer (interactive kicanvas board / schematic render, M7 #11) --------

function ProjectViewerSection({ projectId }: { projectId: string }) {
  const query = useProjectQuery(projectId);
  const detail = query.data ?? null;
  const short = (p: string) => p.replace(/\.(kicad_pcb|kicad_sch)$/i, "");
  const files: ViewFile[] = detail
    ? [
        ...detail.board_paths.map((p) => ({
          path: p,
          label: `Board · ${short(p)}`,
          kind: "Board" as const,
        })),
        ...detail.sheet_paths.map((p) => ({
          path: p,
          label: `Schematic · ${short(p)}`,
          kind: "Schematic" as const,
        })),
      ]
    : [];

  return (
    <div className="mt-7 border-t border-line pt-6" data-testid="viewer-section">
      <div className="mb-3">
        <Eyebrow className="mb-0.5">Board Viewer</Eyebrow>
        <p className="text-xs text-t3">
          An interactive view of the project's board and schematic, rendered in-app with pan,
          zoom and layer controls.
        </p>
      </div>
      {query.isLoading ? (
        <p className="text-sm text-t3">Loading viewer...</p>
      ) : query.isError ? (
        <p className="text-sm text-err" data-testid="viewer-detail-error">
          Could not load the project files.
        </p>
      ) : (
        <ProjectViewer projectId={projectId} files={files} />
      )}
    </div>
  );
}

// -- Fab prep (gerbers + drill + placement, plotted via kicad-cli into a downloadable zip, M7i) --

const DEFAULT_FAB_OPTS: FabExportOptions = {
  drillFormat: "excellon",
  drillMap: true,
  includePos: true,
  posFormat: "csv",
  protelExt: true,
};

// The Fab Prep section plots the manufacturing bundle straight from the board through
// kicad-cli. Honest gates: a schematic-only project (no board) or a machine without kicad-cli
// each get their own prompt instead of a dead button; nothing is ever written into the project.
function FabSection({ projectId }: { projectId: string }) {
  const query = useProjectFab(projectId);
  const { toast } = useToast();
  const [opts, setOpts] = useState<FabExportOptions>(DEFAULT_FAB_OPTS);
  const [board, setBoard] = useState<string>("");
  const [downloading, setDownloading] = useState(false);

  const data: FabStatus | null = query.data ?? null;

  async function onExport() {
    setDownloading(true);
    try {
      await api.downloadFabExport(projectId, { ...opts, board: board || undefined });
      toast("Saved the fab bundle.", "ok");
    } catch (e) {
      toast(errMsg(e, "Could not export the fab files."), "err");
    } finally {
      setDownloading(false);
    }
  }

  return (
    <div className="mt-7 border-t border-line pt-6" data-testid="fab-section">
      <div className="mb-3">
        <Eyebrow className="mb-0.5">Fab Prep</Eyebrow>
        <p className="text-xs text-t3">
          Plot the manufacturing bundle (gerbers, drill files and the placement file) straight
          from the board with kicad-cli, saved as one zip for your fab house.
        </p>
      </div>

      {query.isLoading ? (
        <p className="text-sm text-t3">Loading fab prep...</p>
      ) : query.isError ? (
        <p className="text-sm text-err" data-testid="fab-error">
          {errMsg(query.error, "Could not load fab prep.")}
        </p>
      ) : !data?.has_board ? (
        <p className="text-sm text-t3" data-testid="fab-no-board">
          This project has no .kicad_pcb to fabricate. Add a board to the project to export
          gerbers and drill files.
        </p>
      ) : !data.cli_available ? (
        <p className="text-sm text-t3" data-testid="fab-no-cli">
          kicad-cli was not found. Install KiCad on this machine to plot fab files.
        </p>
      ) : (
        <div className="flex flex-col gap-4" data-testid="fab-result">
          <FabOptionsForm
            opts={opts}
            onChange={setOpts}
            boards={data.boards}
            board={board}
            onBoard={setBoard}
          />
          <div className="flex flex-wrap items-center gap-3">
            <Button
              variant="accent"
              onClick={onExport}
              disabled={downloading}
              data-testid="fab-export"
            >
              {downloading ? "Plotting..." : "Export Fab Bundle"}
            </Button>
            <span className="text-2xs text-t3" data-testid="fab-contents">
              {"Zips gerbers, the "}
              {opts.drillFormat === "gerber" ? "Gerber" : "Excellon"}
              {" drill file"}
              {opts.drillMap ? " and its map" : ""}
              {opts.includePos ? ", and a placement file" : ""}
              {"."}
            </span>
          </div>
        </div>
      )}
    </div>
  );
}

function FabOptionsForm({
  opts,
  onChange,
  boards,
  board,
  onBoard,
}: {
  opts: FabExportOptions;
  onChange: (o: FabExportOptions) => void;
  boards: string[];
  board: string;
  onBoard: (b: string) => void;
}) {
  return (
    <div className="flex flex-wrap items-end gap-4" data-testid="fab-options">
      {boards.length > 1 ? (
        <label className="flex flex-col gap-1 text-2xs text-t3">
          Board
          <select
            className={`${INPUT_CLS} w-56`}
            data-testid="fab-board"
            value={board}
            onChange={(e) => onBoard(e.target.value)}
          >
            <option value="">First board ({boards[0]})</option>
            {boards.map((b) => (
              <option key={b} value={b}>
                {b}
              </option>
            ))}
          </select>
        </label>
      ) : null}
      <label className="flex flex-col gap-1 text-2xs text-t3">
        Drill Format
        <select
          className={`${INPUT_CLS} w-36`}
          data-testid="fab-drill-format"
          value={opts.drillFormat}
          onChange={(e) =>
            onChange({ ...opts, drillFormat: e.target.value as FabExportOptions["drillFormat"] })
          }
        >
          <option value="excellon">Excellon</option>
          <option value="gerber">Gerber</option>
        </select>
      </label>
      <label className="flex flex-col gap-1 text-2xs text-t3">
        Placement Format
        <select
          className={`${INPUT_CLS} w-36`}
          data-testid="fab-pos-format"
          value={opts.posFormat}
          disabled={!opts.includePos}
          onChange={(e) =>
            onChange({ ...opts, posFormat: e.target.value as FabExportOptions["posFormat"] })
          }
        >
          <option value="csv">CSV</option>
          <option value="ascii">ASCII</option>
          <option value="gerber">Gerber</option>
        </select>
      </label>
      <label className="flex items-center gap-2 text-2xs text-t2">
        <input
          type="checkbox"
          data-testid="fab-drill-map"
          checked={opts.drillMap}
          onChange={(e) => onChange({ ...opts, drillMap: e.target.checked })}
        />
        Drill Map
      </label>
      <label className="flex items-center gap-2 text-2xs text-t2">
        <input
          type="checkbox"
          data-testid="fab-include-pos"
          checked={opts.includePos}
          onChange={(e) => onChange({ ...opts, includePos: e.target.checked })}
        />
        Placement File
      </label>
      <label className="flex items-center gap-2 text-2xs text-t2">
        <input
          type="checkbox"
          data-testid="fab-protel-ext"
          checked={opts.protelExt}
          onChange={(e) => onChange({ ...opts, protelExt: e.target.checked })}
        />
        Protel Extensions
      </label>
    </div>
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
// M7h KiField bulk-field editor: the project's placed components as a rows-by-fields grid.
// Every editable cell is an input; Reference and non-editable rows (unannotated, or a duplicate
// designator) render as plain read-only text. A Save writes only the changed cells to the
// schematic and commits them to the project's own git in one atomic commit. Adding a field
// introduces a new editable column across the editable rows.
function FieldsSection({ projectId }: { projectId: string }) {
  const fields = useProjectFields(projectId);
  const save = useSetFields();
  const { toast } = useToast();
  const data = fields.data;

  // drafts[ref][field] overrides the on-disk value; extraCols are user-added field columns.
  const [drafts, setDrafts] = useState<Record<string, Record<string, string>>>({});
  const [extraCols, setExtraCols] = useState<string[]>([]);
  const [newField, setNewField] = useState("");

  // Clear the pending edits only when the on-disk grid actually CHANGES (a save commit re-reads
  // it), keyed on a content signature so an unrelated refetch never clobbers in-progress edits.
  const sig = data ? JSON.stringify(data.rows.map((r) => [r.ref, r.fields])) : "";
  useEffect(() => {
    setDrafts({});
    setExtraCols([]);
    setNewField("");
    // eslint-disable-next-line react-hooks/exhaustive-deps -- sig is the content of the grid
  }, [sig]);

  const readonlyCols = new Set(data?.readonly_columns ?? []);
  const columns = data
    ? [...data.columns, ...extraCols.filter((c) => !data.columns.includes(c))]
    : [];

  function cellValue(row: FieldRow, col: string): string {
    const d = drafts[row.ref];
    if (d && col in d) return d[col];
    return row.fields[col] ?? "";
  }

  function editCell(ref: string, col: string, value: string) {
    setDrafts((ds) => ({ ...ds, [ref]: { ...(ds[ref] ?? {}), [col]: value } }));
  }

  function addField() {
    const name = newField.trim();
    if (!name) return;
    const lc = name.toLowerCase();
    if ([...readonlyCols].some((c) => c.toLowerCase() === lc)) {
      toast(`The ${name} field is set by annotation, not the field editor.`, "err");
      return;
    }
    // Case-insensitive: adding "mpn" when an "MPN" column exists edits that column, never a
    // second duplicate (the backend snaps the edit to the existing column too).
    if (!columns.some((c) => c.toLowerCase() === lc)) setExtraCols((cs) => [...cs, name]);
    setNewField("");
  }

  // The edits = every draft cell on an EDITABLE row whose value differs from the on-disk value
  // (a new-column cell has on-disk "", so any non-blank is an edit). Read-only columns skipped.
  const edits: FieldEdit[] = [];
  if (data) {
    for (const row of data.rows) {
      if (!row.editable) continue;
      const d = drafts[row.ref];
      if (!d) continue;
      for (const [field, value] of Object.entries(d)) {
        if (readonlyCols.has(field)) continue;
        if (value !== (row.fields[field] ?? "")) edits.push({ ref: row.ref, field, value });
      }
    }
  }
  const dirty = edits.length > 0;

  function onSave() {
    if (!dirty) return;
    save.mutate(
      { id: projectId, edits },
      {
        onSuccess: (res) =>
          toast(
            res.committed
              ? `Saved ${res.fields} field value(s) on ${res.components} component(s).`
              : "Those values already match the schematic, so nothing changed.",
            res.committed ? "ok" : "neutral",
          ),
        onError: (e) => toast(errMsg(e, "Could not save the field changes."), "err"),
      },
    );
  }

  const canEdit = !!data && data.has_sch && data.under_git;

  return (
    <div className="mt-7 border-t border-line pt-6" data-testid="fields-section">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
        <div>
          <div className="flex items-center gap-2">
            <Eyebrow className="mb-0.5">Fields</Eyebrow>
            {dirty ? <Badge tone="warn">Unsaved</Badge> : null}
          </div>
          <p className="text-xs text-t3">
            Edit component fields in bulk. Each save writes only the changed cells to the schematic
            and commits them to the project's own git history in one atomic commit.
          </p>
        </div>
        {canEdit ? (
          <div className="flex flex-wrap items-center gap-2">
            <input
              type="text"
              className={`${INPUT_CLS} w-40 !py-1 text-xs`}
              data-testid="fields-new-field"
              placeholder="Add a field"
              value={newField}
              onChange={(e) => setNewField(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") addField();
              }}
            />
            <Button small onClick={addField} disabled={!newField.trim()}>
              Add Field
            </Button>
            <Button variant="accent" small onClick={onSave} disabled={!dirty || save.isPending}>
              {save.isPending ? "Saving..." : "Save Field Edits"}
            </Button>
          </div>
        ) : null}
      </div>

      {fields.isLoading ? (
        <p className="text-sm text-t3">Loading the component fields...</p>
      ) : fields.isError ? (
        <p className="text-sm text-err">
          {errMsg(fields.error, "Could not read the component fields.")}
        </p>
      ) : !data ? null : !data.has_sch ? (
        <p className="text-sm text-t3">
          This project has no schematic sheets, so there are no component fields to edit.
        </p>
      ) : data.rows.length === 0 ? (
        <p className="text-sm text-t3">This project's schematic has no placed components.</p>
      ) : (
        <>
          {!data.under_git ? (
            <p className="mb-3 text-sm text-t3" data-testid="fields-no-git">
              This project is not under git, so its fields are read-only here. Initialize a git
              repository for it to edit fields, so each change is committed atomically and can be
              undone.
            </p>
          ) : null}
          <div className="overflow-x-auto">
            <table className="min-w-full border-collapse text-xs" data-testid="fields-table">
              <thead>
                <tr className="border-b border-line text-left text-2xs text-t3">
                  {columns.map((col) => (
                    <th key={col} className="whitespace-nowrap px-2 py-1.5 font-medium text-t2">
                      {col}
                      {readonlyCols.has(col) ? (
                        <span className="ml-1 font-normal text-t4">(read only)</span>
                      ) : null}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {data.rows.map((row) => (
                  <tr
                    key={row.ref}
                    className="border-b border-line"
                    data-testid={`fields-row-${row.ref}`}
                  >
                    {columns.map((col) => {
                      const ro = readonlyCols.has(col) || !row.editable || !data.under_git;
                      const conflict = row.conflicts.includes(col);
                      const changed = cellValue(row, col) !== (row.fields[col] ?? "");
                      return (
                        <td key={col} className="px-1 py-0.5 align-top">
                          {ro ? (
                            <span
                              className={`block px-2 py-1 ${
                                conflict ? "text-warn" : col === "Reference" ? "text-t1" : "text-t3"
                              }`}
                              title={
                                col === "Reference"
                                  ? "The reference designator is set by annotation"
                                  : row.unannotated
                                    ? "Annotate this component before editing its fields"
                                    : conflict
                                      ? "This designator is shared by another component; resolve the duplicate first"
                                      : undefined
                              }
                            >
                              {cellValue(row, col)}
                            </span>
                          ) : (
                            <input
                              type="text"
                              className={`${INPUT_CLS} !px-2 !py-1 text-xs ${changed ? "border-acc" : ""}`}
                              data-testid={`fields-cell-${row.ref}-${col}`}
                              value={cellValue(row, col)}
                              onChange={(e) => editCell(row.ref, col, e.target.value)}
                            />
                          )}
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {data.summary.unannotated > 0 || data.summary.duplicate > 0 ? (
            <p className="mt-2 text-2xs text-t3" data-testid="fields-readonly-note">
              {data.summary.unannotated > 0
                ? `${data.summary.unannotated} unannotated component(s) are read-only here; run Prepare to annotate them first. `
                : ""}
              {data.summary.duplicate > 0
                ? `${data.summary.duplicate} component(s) share a designator with a different component and stay read-only until the duplicate is resolved.`
                : ""}
            </p>
          ) : null}
        </>
      )}
    </div>
  );
}

function EditorSection({ projectId }: { projectId: string }) {
  const [floor, setFloor] = useState("none");
  const design = useProjectDesign(projectId, floor);
  const data = design.data;

  return (
    <div className="mt-7 border-t border-line pt-6" data-testid="editor-section">
      <div className="mb-3">
        <Eyebrow className="mb-0.5">Editor</Eyebrow>
        <p className="text-xs text-t3">
          Edit the board net classes, netclass patterns, and design rules. Each save writes a
          minimal change to the project file and commits it to the project's own git history.
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
          <NetclassPatternEditor projectId={projectId} data={data} />
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

  // Re-seed only when the on-disk classes actually CHANGE (a save commit), NOT when the fab
  // floor changes. The design read is keyed on the floor, so a floor change yields a new
  // DesignResult whose net_classes is a fresh reference with identical content; keying the
  // effect on the content signature (not the reference) means a floor-only refetch does not
  // clobber the user's unsaved edits. keepPreviousData on the query prevents an unmount flash.
  const netSig = JSON.stringify(data.net_classes);
  useEffect(() => {
    setDrafts(seedDrafts(data.net_classes));
    setDeleted([]);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- netSig is the content of data.net_classes
  }, [netSig]);

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
    const named = drafts.filter((d) => d.name.trim() !== "");
    // A dimension field is free text (so decimals type cleanly), so guard against a
    // non-numeric value: a NaN would serialize to JSON null and be written as a fabricated
    // "saved". Block + warn instead, never write garbage.
    for (const d of named) {
      for (const f of NC_DIMS) {
        const raw = d.dims[f.key];
        if (raw != null && raw !== "" && !Number.isFinite(Number(raw))) {
          toast(`Enter a valid number for ${d.name.trim()} ${f.label}.`, "err");
          return;
        }
      }
    }
    const classes: NetClass[] = named.map((d) => ({
      name: d.name.trim(),
      ...Object.fromEntries(
        NC_DIMS.filter((f) => d.dims[f.key] !== "" && d.dims[f.key] != null).map((f) => [
          f.key,
          Number(d.dims[f.key]),
        ]),
      ),
    }));
    // A class re-added under a name that was also deleted must NOT be sent in both lists:
    // reconcile lets a delete win, so the re-added class would silently vanish. Drop any
    // deleted name that is present in the submitted set.
    const submittedNames = new Set(classes.map((c) => c.name));
    const effectiveDeleted = deleted.filter((n) => !submittedNames.has(n));
    save.mutate(
      { id: projectId, classes, deleted: effectiveDeleted, floor },
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

  // Re-seed on the rules CONTENT, not the reference, so a floor-only refetch (which returns
  // an identical-content design_rules with a fresh reference) does not clobber unsaved edits.
  const rulesSig = JSON.stringify(data.design_rules);
  useEffect(() => {
    setDraft(seedRules(data.design_rules));
    // eslint-disable-next-line react-hooks/exhaustive-deps -- rulesSig is the content of data.design_rules
  }, [rulesSig]);

  const dirty = JSON.stringify(draft) !== JSON.stringify(seedRules(data.design_rules));
  const keys = Object.keys(data.design_rules).sort();

  function onSave() {
    // The form re-sends the whole rules record, so a cleared field would otherwise be
    // written as Number("") === 0 (a fabricated value). Block + warn on any blank/non-numeric
    // field instead of silently committing a 0.
    const rules: DesignRules = {};
    for (const [k, v] of Object.entries(draft)) {
      if (typeof v === "boolean") {
        rules[k] = v;
        continue;
      }
      if (String(v).trim() === "" || !Number.isFinite(Number(v))) {
        toast(`Enter a valid number for ${k}.`, "err");
        return;
      }
      rules[k] = Number(v);
    }
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

// -- Editor: netclass patterns (roadmap #4) -----------------------------------

// One editable pattern row: a net-name glob bound to a net class. rowId is a stable key
// across edits/deletes; the on-wire shape is exactly {netclass, pattern} (the two keys KiCad
// writes). A blank-pattern row is incomplete and dropped on save, mirroring the net-class
// editor's drop of an unnamed class.
interface PatternDraft {
  rowId: string;
  pattern: string;
  netclass: string;
}

function seedPatterns(pats: { netclass: string; pattern: string }[]): PatternDraft[] {
  return pats.map((p, i) => ({ rowId: `seed-${i}`, pattern: p.pattern, netclass: p.netclass }));
}

// The netclass-pattern editor: assign net-name globs (e.g. *GND) to a net class. The editor
// re-sends the FULL list, so a save replaces net_settings.netclass_patterns wholesale as a
// minimal-diff scoped commit on the project's own git (roadmap #4). The net class is a select
// of the project's classes, so a pattern can never reference a class the project does not define.
function NetclassPatternEditor({ projectId, data }: { projectId: string; data: DesignResult }) {
  const [drafts, setDrafts] = useState<PatternDraft[]>(() => seedPatterns(data.netclass_patterns));
  const [newCount, setNewCount] = useState(0);
  const save = useSetNetclassPatterns();
  const { toast } = useToast();
  const classNames = data.net_classes.map((c) => c.name);

  // Re-seed on the patterns CONTENT (not the reference) so a floor-only refetch (identical
  // content, fresh reference) does not clobber unsaved edits, matching the net-class editor.
  const sig = JSON.stringify(data.netclass_patterns);
  useEffect(() => {
    setDrafts(seedPatterns(data.netclass_patterns));
    // eslint-disable-next-line react-hooks/exhaustive-deps -- sig is the content of data.netclass_patterns
  }, [sig]);

  const seeded = seedPatterns(data.netclass_patterns);
  const dirty =
    JSON.stringify(drafts.map((d) => [d.pattern, d.netclass])) !==
    JSON.stringify(seeded.map((d) => [d.pattern, d.netclass]));

  function editPattern(rowId: string, pattern: string) {
    setDrafts((ds) => ds.map((d) => (d.rowId === rowId ? { ...d, pattern } : d)));
  }

  function editNetclass(rowId: string, netclass: string) {
    setDrafts((ds) => ds.map((d) => (d.rowId === rowId ? { ...d, netclass } : d)));
  }

  function addRow() {
    const rowId = `new-${newCount}`;
    setNewCount((n) => n + 1);
    setDrafts((ds) => [...ds, { rowId, pattern: "", netclass: classNames[0] ?? "" }]);
  }

  function removeRow(rowId: string) {
    setDrafts((ds) => ds.filter((d) => d.rowId !== rowId));
  }

  function onSave() {
    // A blank-pattern row is incomplete: drop it rather than write an empty glob. The netclass
    // is always a select value, so it is never blank when a pattern is present.
    const active = drafts.filter((d) => d.pattern.trim() !== "");
    // A row whose net class the project no longer defines (e.g. the class was deleted in the Net
    // Classes editor, which does not clean up its patterns) would be rejected wholesale by the
    // backend, blocking every unrelated edit with an opaque error. Catch it here and name the
    // exact pattern to fix, so the user reassigns or deletes it deliberately (never silently).
    const orphan = active.find((d) => !classNames.includes(d.netclass));
    if (orphan) {
      toast(
        `Pattern "${orphan.pattern.trim()}" is assigned to net class "${orphan.netclass}", which no longer exists. Reassign or delete it before saving.`,
        "err",
      );
      return;
    }
    const rows = active.map((d) => ({ netclass: d.netclass, pattern: d.pattern.trim() }));
    save.mutate(
      { id: projectId, patterns: rows },
      {
        // Re-seed from the committed result so an effective no-op (e.g. a dropped blank row)
        // does not strand the section permanently Unsaved: the local drafts match disk again.
        onSuccess: (result) => {
          setDrafts(seedPatterns(result.netclass_patterns));
          toast("Netclass patterns saved.");
        },
        onError: (e) => toast(errMsg(e, "Could not save the netclass patterns."), "err"),
      },
    );
  }

  return (
    <div data-testid="netclass-pattern-editor">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <h3 className="text-sm font-medium text-t1">Netclass Patterns</h3>
          {dirty ? <Badge tone="warn">Unsaved</Badge> : null}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Button small onClick={addRow} disabled={classNames.length === 0}>
            Add Pattern
          </Button>
          <Button variant="accent" small onClick={onSave} disabled={!dirty || save.isPending}>
            {save.isPending ? "Saving..." : "Save Netclass Patterns"}
          </Button>
        </div>
      </div>

      <p className="mb-2 text-2xs text-t3">
        A net-name glob (e.g. *GND, *USB*) assigns every matching net to a net class. KiCad
        applies the patterns in order.
      </p>

      {drafts.length === 0 ? (
        <p className="text-xs text-t3" data-testid="ncp-empty">
          No netclass patterns. Add one to assign nets to a class by name.
        </p>
      ) : (
        <div className="flex flex-col">
          <div className="flex gap-2 border-b border-line pb-1.5 text-2xs text-t3">
            <div className="flex-1">Pattern</div>
            <div className="w-40 shrink-0">Net Class</div>
            <div className="w-16 shrink-0" />
          </div>
          {drafts.map((d, i) => {
            // A row is orphaned when its non-blank pattern points at a net class the project no
            // longer defines. It is kept (never silently dropped) but flagged so the user sees
            // exactly which pattern to reassign or delete before a save can go through.
            const orphan =
              d.pattern.trim() !== "" && d.netclass !== "" && !classNames.includes(d.netclass);
            return (
              <div
                key={d.rowId}
                className="border-b border-line py-1.5"
                data-testid={`ncp-row-${i}`}
              >
                <div className="flex items-center gap-2">
                  <input
                    type="text"
                    className={`${INPUT_CLS} flex-1 !py-1 text-xs`}
                    data-testid={`ncp-${i}-pattern`}
                    placeholder="*NET*"
                    value={d.pattern}
                    onChange={(e) => editPattern(d.rowId, e.target.value)}
                  />
                  <select
                    className={`${INPUT_CLS} w-40 shrink-0 !py-1 text-xs ${orphan ? "border-warn" : ""}`}
                    data-testid={`ncp-${i}-netclass`}
                    value={d.netclass}
                    onChange={(e) => editNetclass(d.rowId, e.target.value)}
                  >
                    {/* If a stored pattern names a class the project no longer defines, keep it as
                        a selectable option so the row is honest and a save never silently remaps it. */}
                    {!classNames.includes(d.netclass) && d.netclass !== "" ? (
                      <option value={d.netclass}>{d.netclass}</option>
                    ) : null}
                    {classNames.map((n) => (
                      <option key={n} value={n}>
                        {n}
                      </option>
                    ))}
                  </select>
                  <div className="flex w-16 shrink-0 justify-end">
                    <button
                      type="button"
                      className="text-2xs text-err hover:opacity-80"
                      onClick={() => removeRow(d.rowId)}
                    >
                      Delete
                    </button>
                  </div>
                </div>
                {orphan ? (
                  <p className="mt-1 pl-1 text-2xs text-warn">
                    Net class "{d.netclass}" no longer exists. Reassign or delete this pattern.
                  </p>
                ) : null}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

// -- Editor: board setup + thickness (M7f-A) ----------------------------------

// The board-setup draft holds numeric/coord fields as strings (so decimals type cleanly)
// and bools as booleans; a coord is an [x, y] string pair. Values coerce at save time, and
// only fields the user CHANGED are sent, so an untouched via-protection default is never
// re-written (which would flip an absent-defaults-ON tenting to OFF).
interface SetupDraft {
  fields: Record<string, string | boolean | [string, string]>;
  thickness: string;
}

function seedSetup(data: BoardSettings): SetupDraft {
  const fields: Record<string, string | boolean | [string, string]> = {};
  for (const f of data.fields) {
    const v = data.board_setup[f.key];
    if (f.kind === "bool") fields[f.key] = v === true;
    else if (f.kind === "coord")
      fields[f.key] = Array.isArray(v) ? [String(v[0]), String(v[1])] : ["", ""];
    else fields[f.key] = v != null && !Array.isArray(v) ? String(v) : "";
  }
  return { fields, thickness: data.thickness != null ? String(data.thickness) : "" };
}

// A numeric field counts as changed only when it is non-blank AND its NUMBER differs from the
// seed (so "1.60" equals "1.6" and never strands the form Unsaved). A blanked field cannot be
// sent (KiCad has no delete-key), so it is treated as no change, not a permanent dirty state.
function numChanged(cur: string, orig: string): boolean {
  const s = cur.trim();
  if (s === "") return false;
  const o = orig.trim();
  if (o === "") return true; // was absent, now has a value
  return Number(s) !== Number(o);
}

function fieldChanged(
  f: BoardSetupField,
  cur: string | boolean | [string, string],
  orig: string | boolean | [string, string],
): boolean {
  if (f.kind === "bool") return cur !== orig;
  if (f.kind === "coord") {
    const [cx, cy] = cur as [string, string];
    const [ox, oy] = orig as [string, string];
    if (cx.trim() === "" || cy.trim() === "") return false; // a partial coord cannot be sent
    return numChanged(cx, ox) || numChanged(cy, oy);
  }
  return numChanged(cur as string, orig as string);
}

// The Board Setup editor: edit a project's solder mask/paste clearances, via protection,
// origins, and overall thickness, written as a minimal-diff scoped commit on the project's
// own git (M7f-A). Honest states for a project with no .kicad_pcb or not under git.
function BoardSetupSection({ projectId }: { projectId: string }) {
  const q = useProjectSettings(projectId);
  const data = q.data;
  return (
    <div className="mt-7 border-t border-line pt-6" data-testid="board-setup-section">
      <div className="mb-3">
        <Eyebrow className="mb-0.5">Board Setup</Eyebrow>
        <p className="text-xs text-t3">
          Edit the board solder mask and paste clearances, via protection, origins, and overall
          thickness. Each save writes a minimal change to the board file and commits it to the
          project's own git history.
        </p>
      </div>

      {q.isLoading ? (
        <p className="text-sm text-t3">Loading the board setup...</p>
      ) : q.isError ? (
        <p className="text-sm text-err">{errMsg(q.error, "Could not read the board setup.")}</p>
      ) : !data ? null : !data.has_board ? (
        <p className="text-sm text-t3" data-testid="board-setup-no-board">
          This project has no .kicad_pcb file, so there is no board setup to edit.
        </p>
      ) : !data.under_git ? (
        <p className="text-sm text-t3" data-testid="board-setup-no-git">
          This project is not under git. Initialize a git repository for it to edit its board
          setup, so each change is committed atomically and can be undone.
        </p>
      ) : (
        <BoardSetupForm projectId={projectId} data={data} />
      )}
    </div>
  );
}

function BoardSetupForm({ projectId, data }: { projectId: string; data: BoardSettings }) {
  const [draft, setDraft] = useState<SetupDraft>(() => seedSetup(data));
  const save = useSetProjectSettings();
  const { toast } = useToast();

  // Re-seed on the settings CONTENT (not the reference) so a background re-read that returns
  // identical content does not clobber the user's unsaved edits (mirrors the M7e editor).
  const sig = JSON.stringify([data.board_setup, data.thickness]);
  useEffect(() => {
    setDraft(seedSetup(data));
    // eslint-disable-next-line react-hooks/exhaustive-deps -- sig is the content of the settings
  }, [sig]);

  const seed = seedSetup(data);
  const dirty =
    data.fields.some((f) => fieldChanged(f, draft.fields[f.key], seed.fields[f.key])) ||
    numChanged(draft.thickness, seed.thickness);

  const lengthFields = data.fields.filter((f) => f.kind === "length" || f.kind === "ratio");
  const boolFields = data.fields.filter((f) => f.kind === "bool");
  const coordFields = data.fields.filter((f) => f.kind === "coord");

  function setField(key: string, value: string | boolean | [string, string]) {
    setDraft((d) => ({ ...d, fields: { ...d.fields, [key]: value } }));
  }

  function onSave() {
    // Send only genuinely-changed fields (numeric equality, blanks skipped) so an untouched
    // via-protection default is never re-written (which would flip an effectively-ON tenting).
    const board_setup: Record<string, BoardSetupValue> = {};
    for (const f of data.fields) {
      const cur = draft.fields[f.key];
      if (!fieldChanged(f, cur, seed.fields[f.key])) continue;
      if (f.kind === "bool") {
        board_setup[f.key] = cur as boolean;
      } else if (f.kind === "coord") {
        const [cx, cy] = cur as [string, string];
        if (![cx, cy].every((s) => Number.isFinite(Number(s)))) {
          toast(`Enter both coordinates for ${f.label}.`, "err");
          return;
        }
        board_setup[f.key] = [Number(cx), Number(cy)];
      } else {
        const s = String(cur).trim();
        if (!Number.isFinite(Number(s))) {
          toast(`Enter a valid number for ${f.label}.`, "err");
          return;
        }
        board_setup[f.key] = Number(s);
      }
    }

    let thickness: number | undefined;
    if (numChanged(draft.thickness, seed.thickness)) {
      const t = draft.thickness.trim();
      if (!Number.isFinite(Number(t)) || Number(t) <= 0) {
        toast("Enter a positive number for board thickness.", "err");
        return;
      }
      thickness = Number(t);
    }

    const hasSetup = Object.keys(board_setup).length > 0;
    // dirty (numeric) implies a real change, so this is only a defensive guard, never a
    // user-facing error on a blanked field (which counts as no change and disables Save).
    if (!hasSetup && thickness === undefined) return;
    save.mutate(
      { id: projectId, board_setup: hasSetup ? board_setup : undefined, thickness },
      {
        // The mutation invalidates the settings query; the refetch's fresh content re-seeds the
        // draft (content-keyed effect below), so the form returns to clean after a real save.
        onSuccess: () => toast("Board setup saved."),
        onError: (e) => toast(errMsg(e, "Could not save the board setup."), "err"),
      },
    );
  }

  return (
    <div data-testid="board-setup-form">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <h3 className="text-sm font-medium text-t1">Physical Setup</h3>
          {dirty ? <Badge tone="warn">Unsaved</Badge> : null}
        </div>
        <Button variant="accent" small onClick={onSave} disabled={!dirty || save.isPending}>
          {save.isPending ? "Saving..." : "Save Board Setup"}
        </Button>
      </div>

      <div className="flex flex-col gap-5">
        <div>
          <h4 className="mb-2 text-2xs font-medium uppercase tracking-wide text-t3">Clearances</h4>
          <div className="grid grid-cols-2 gap-x-4 gap-y-2 sm:grid-cols-3">
            {lengthFields.map((f) => (
              <label key={f.key} className="flex flex-col gap-0.5 text-2xs text-t3">
                {f.label}
                <input
                  type="text"
                  inputMode="decimal"
                  className={`${INPUT_CLS} !py-1 text-xs`}
                  data-testid={`bs-${f.key}`}
                  value={String(draft.fields[f.key] ?? "")}
                  onChange={(e) => setField(f.key, e.target.value)}
                />
              </label>
            ))}
            <label className="flex flex-col gap-0.5 text-2xs text-t3">
              Board Thickness
              <input
                type="text"
                inputMode="decimal"
                className={`${INPUT_CLS} !py-1 text-xs`}
                data-testid="bs-thickness"
                value={draft.thickness}
                onChange={(e) => setDraft((d) => ({ ...d, thickness: e.target.value }))}
              />
            </label>
          </div>
        </div>

        <div>
          <h4 className="mb-2 text-2xs font-medium uppercase tracking-wide text-t3">
            Via Protection
          </h4>
          <div className="grid grid-cols-2 gap-x-4 gap-y-2 sm:grid-cols-3">
            {boolFields.map((f) => (
              <label key={f.key} className="flex items-center gap-2 text-2xs text-t2">
                <input
                  type="checkbox"
                  data-testid={`bs-${f.key}`}
                  checked={draft.fields[f.key] === true}
                  onChange={(e) => setField(f.key, e.target.checked)}
                />
                {f.label}
              </label>
            ))}
          </div>
        </div>

        <div>
          <h4 className="mb-2 text-2xs font-medium uppercase tracking-wide text-t3">Origins</h4>
          <div className="grid grid-cols-1 gap-x-4 gap-y-2 sm:grid-cols-2">
            {coordFields.map((f) => {
              const [x, y] = (draft.fields[f.key] as [string, string]) ?? ["", ""];
              return (
                <div key={f.key} className="flex flex-col gap-0.5 text-2xs text-t3">
                  {f.label}
                  <div className="flex gap-2">
                    <input
                      type="text"
                      inputMode="decimal"
                      className={`${INPUT_CLS} !py-1 text-xs`}
                      data-testid={`bs-${f.key}-x`}
                      placeholder="X"
                      value={x}
                      onChange={(e) => setField(f.key, [e.target.value, y])}
                    />
                    <input
                      type="text"
                      inputMode="decimal"
                      className={`${INPUT_CLS} !py-1 text-xs`}
                      data-testid={`bs-${f.key}-y`}
                      placeholder="Y"
                      value={y}
                      onChange={(e) => setField(f.key, [x, e.target.value])}
                    />
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      </div>
    </div>
  );
}

// -- Editor: .kicad_pro settings (severities + ERC pin-map + text-vars) (M7f-A2) --

// "pin_not_connected" -> "Pin Not Connected": a readable label for a KiCad rule id / pin type.
function humanizeId(id: string): string {
  return id
    .split("_")
    .map((w) => (w ? w[0].toUpperCase() + w.slice(1) : w))
    .join(" ");
}

// The .kicad_pro settings editor: ERC/DRC rule severities, the ERC pin-conflict matrix, and
// project text variables. Each save is a minimal-diff scoped commit on the project's own git.
// Reads from the same settings query as the board setup; honest states for no .kicad_pro / no git.
function ProSettingsSection({ projectId }: { projectId: string }) {
  const q = useProjectSettings(projectId);
  const data = q.data;
  return (
    <div className="mt-7 border-t border-line pt-6" data-testid="pro-settings-section">
      <div className="mb-3">
        <Eyebrow className="mb-0.5">Design Checks and Variables</Eyebrow>
        <p className="text-xs text-t3">
          Edit the ERC and DRC rule severities, the ERC pin conflict matrix, and the project text
          variables. Each save writes a minimal change to the project file and commits it to the
          project's own git history.
        </p>
      </div>

      {q.isLoading ? (
        <p className="text-sm text-t3">Loading the project settings...</p>
      ) : q.isError ? (
        <p className="text-sm text-err">
          {errMsg(q.error, "Could not read the project settings.")}
        </p>
      ) : !data ? null : !data.has_pro ? (
        <p className="text-sm text-t3" data-testid="prosettings-no-pro">
          This project has no .kicad_pro file, so there are no rule severities, pin map, or text
          variables to edit.
        </p>
      ) : !data.under_git ? (
        <p className="text-sm text-t3" data-testid="prosettings-no-git">
          This project is not under git. Initialize a git repository for it to edit these settings,
          so each change is committed atomically and can be undone.
        </p>
      ) : (
        <div className="flex flex-col gap-7">
          <SeveritiesForm projectId={projectId} data={data} />
          <PinMapForm projectId={projectId} data={data} />
          <TextVarsForm projectId={projectId} data={data} />
        </div>
      )}
    </div>
  );
}

type SevMap = Record<string, string>;

// The changed entries between a current severity map and its seed (send-only-changed, so an
// untouched rule is never re-written and the per-rule merge stays a minimal diff).
function changedSeverities(cur: SevMap, seed: SevMap): SevMap {
  const out: SevMap = {};
  for (const k of Object.keys(cur)) if (cur[k] !== seed[k]) out[k] = cur[k];
  return out;
}

function SeveritiesForm({ projectId, data }: { projectId: string; data: BoardSettings }) {
  const seedErc = data.erc_severities;
  const seedDrc = data.drc_severities;
  const [erc, setErc] = useState<SevMap>(() => ({ ...seedErc }));
  const [drc, setDrc] = useState<SevMap>(() => ({ ...seedDrc }));
  const save = useSetProjectSettings();
  const { toast } = useToast();

  // Re-seed on content (not reference) so a background re-read of identical content never
  // clobbers unsaved edits (mirrors the M7e/A editors).
  const sig = JSON.stringify([seedErc, seedDrc]);
  useEffect(() => {
    setErc({ ...seedErc });
    setDrc({ ...seedDrc });
    // eslint-disable-next-line react-hooks/exhaustive-deps -- sig is the content of the seed maps
  }, [sig]);

  const chErc = changedSeverities(erc, seedErc);
  const chDrc = changedSeverities(drc, seedDrc);
  const dirty = Object.keys(chErc).length > 0 || Object.keys(chDrc).length > 0;

  function onSave() {
    if (!dirty) return;
    const vars: { id: string; erc_severities?: SevMap; drc_severities?: SevMap } = { id: projectId };
    if (Object.keys(chErc).length) vars.erc_severities = chErc;
    if (Object.keys(chDrc).length) vars.drc_severities = chDrc;
    save.mutate(vars, {
      onSuccess: () => toast("Rule severities saved."),
      onError: (e) => toast(errMsg(e, "Could not save the rule severities."), "err"),
    });
  }

  return (
    <div data-testid="severities-form">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <h3 className="text-sm font-medium text-t1">Rule Severities</h3>
          {dirty ? <Badge tone="warn">Unsaved</Badge> : null}
        </div>
        <Button variant="accent" small onClick={onSave} disabled={!dirty || save.isPending}>
          {save.isPending ? "Saving..." : "Save Severities"}
        </Button>
      </div>
      <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
        <SeverityGroup
          title="Electrical Rules (ERC)"
          prefix="erc"
          map={erc}
          levels={data.severity_levels}
          onChange={(k, v) => setErc((m) => ({ ...m, [k]: v }))}
        />
        <SeverityGroup
          title="Design Rules (DRC)"
          prefix="drc"
          map={drc}
          levels={data.severity_levels}
          onChange={(k, v) => setDrc((m) => ({ ...m, [k]: v }))}
        />
      </div>
    </div>
  );
}

function SeverityGroup({
  title,
  prefix,
  map,
  levels,
  onChange,
}: {
  title: string;
  prefix: string;
  map: SevMap;
  levels: string[];
  onChange: (rule: string, level: string) => void;
}) {
  const keys = Object.keys(map).sort();
  return (
    <div>
      <h4 className="mb-2 text-2xs font-medium uppercase tracking-wide text-t3">{title}</h4>
      {keys.length === 0 ? (
        <p className="text-xs text-t3">This project defines no rules here.</p>
      ) : (
        <div className="flex max-h-72 flex-col gap-1 overflow-y-auto rounded-control border border-line2 p-2">
          {keys.map((k) => (
            <label key={k} className="flex items-center justify-between gap-2 text-xs text-t2">
              <span className="min-w-0 truncate" title={k}>
                {humanizeId(k)}
              </span>
              <select
                data-testid={`sev-${prefix}-${k}`}
                className="rounded-control border border-line2 bg-field px-1 py-0.5 text-xs text-t1 outline-none focus:border-acc"
                value={map[k]}
                onChange={(e) => onChange(k, e.target.value)}
              >
                {levels.map((lv) => (
                  <option key={lv} value={lv}>
                    {humanizeId(lv)}
                  </option>
                ))}
              </select>
            </label>
          ))}
        </div>
      )}
    </div>
  );
}

// One ERC pin-conflict cell's classes/glyph/label by severity (0 OK, 1 warning, 2 error, 3 is
// KiCad's unconnected sentinel, preserved on read). Tinted backgrounds mirror the Badge palette.
function pinSevCls(sev: number): string {
  if (sev === 2) return "bg-[rgba(215,108,98,0.15)] text-err";
  if (sev === 1) return "bg-[rgba(211,162,76,0.15)] text-warn";
  if (sev === 3) return "bg-raise2 text-t3";
  return "bg-field text-t3";
}
function pinSevGlyph(sev: number): string {
  return sev === 2 ? "E" : sev === 1 ? "W" : sev === 3 ? "-" : "";
}
function pinSevLabel(sev: number): string {
  return sev === 2 ? "Error" : sev === 1 ? "Warning" : sev === 3 ? "Unconnected" : "OK";
}

function PinMapForm({ projectId, data }: { projectId: string; data: BoardSettings }) {
  // A project whose .kicad_pro carries no matrix reads as null: never fabricate an all-OK matrix
  // (that would silently disable every pin-conflict check KiCad's real default enforces).
  if (data.erc_pin_map == null) {
    return (
      <p className="text-sm text-t3" data-testid="pinmap-absent">
        This project has no ERC pin conflict matrix yet. Open it in KiCad once to initialize the
        matrix, then it can be edited here (Stockroom never fabricates one, which would silently
        disable pin conflict checks).
      </p>
    );
  }
  return <PinMapGrid projectId={projectId} data={data} initial={data.erc_pin_map} />;
}

function PinMapGrid({
  projectId,
  data,
  initial,
}: {
  projectId: string;
  data: BoardSettings;
  initial: number[][];
}) {
  const [matrix, setMatrix] = useState<number[][]>(() => initial.map((r) => [...r]));
  const save = useSetProjectSettings();
  const { toast } = useToast();

  const sig = JSON.stringify(initial);
  useEffect(() => {
    setMatrix(initial.map((r) => [...r]));
    // eslint-disable-next-line react-hooks/exhaustive-deps -- sig is the content of the matrix
  }, [sig]);

  const dirty = JSON.stringify(matrix) !== sig;
  const types = data.erc_pin_types;

  function cycle(i: number, j: number) {
    setMatrix((m) => {
      const next = m.map((r) => [...r]);
      const c = next[i][j];
      const v = c === 0 ? 1 : c === 1 ? 2 : 0; // 0 -> 1 -> 2 -> 0 (a 3 sentinel resets to 0 on edit)
      next[i][j] = v;
      next[j][i] = v; // the matrix is symmetric, so mirror the pair
      return next;
    });
  }

  function onSave() {
    if (!dirty) return;
    save.mutate(
      { id: projectId, erc_pin_map: matrix },
      {
        onSuccess: () => toast("ERC pin map saved."),
        onError: (e) => toast(errMsg(e, "Could not save the pin map."), "err"),
      },
    );
  }

  return (
    <div data-testid="pinmap-grid">
      <div className="mb-2 flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <h3 className="text-sm font-medium text-t1">ERC Pin Conflict Matrix</h3>
          {dirty ? <Badge tone="warn">Unsaved</Badge> : null}
        </div>
        <Button variant="accent" small onClick={onSave} disabled={!dirty || save.isPending}>
          {save.isPending ? "Saving..." : "Save Pin Map"}
        </Button>
      </div>
      <p className="mb-2 text-2xs text-t3">
        Click a cell to cycle its severity: OK, Warning, Error. The matrix is symmetric, so both
        pairings update together.
      </p>
      <div className="overflow-x-auto">
        <table className="border-collapse text-2xs">
          <thead>
            <tr>
              <th className="p-1"></th>
              {types.map((t, j) => (
                <th key={j} className="p-1 font-normal text-t3" title={humanizeId(t)}>
                  {j + 1}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {types.map((t, i) => (
              <tr key={i}>
                <th
                  scope="row"
                  className="whitespace-nowrap p-1 text-right font-normal text-t3"
                  title={humanizeId(t)}
                >
                  {i + 1} {humanizeId(t)}
                </th>
                {types.map((c, j) => {
                  const sev = matrix[i][j];
                  return (
                    <td key={j} className="p-0.5">
                      <button
                        type="button"
                        data-testid={`pm-${i}-${j}`}
                        data-sev={sev}
                        onClick={() => cycle(i, j)}
                        title={`${humanizeId(t)} / ${humanizeId(c)}: ${pinSevLabel(sev)}`}
                        className={`h-5 w-5 rounded-control border border-line2 text-center font-medium leading-none ${pinSevCls(
                          sev,
                        )}`}
                      >
                        {pinSevGlyph(sev)}
                      </button>
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

interface TvRow {
  name: string;
  value: string;
}

// True when two string maps hold the same key/value pairs regardless of key order (text_variables
// is unordered; the backend stores it sorted, so an order-sensitive compare would mis-flag dirty).
function sameStringMap(a: Record<string, string>, b: Record<string, string>): boolean {
  const ak = Object.keys(a);
  if (ak.length !== Object.keys(b).length) return false;
  return ak.every((k) => Object.prototype.hasOwnProperty.call(b, k) && a[k] === b[k]);
}

function TextVarsForm({ projectId, data }: { projectId: string; data: BoardSettings }) {
  const seed = data.text_variables;
  const [rows, setRows] = useState<TvRow[]>(() =>
    Object.entries(seed).map(([name, value]) => ({ name, value })),
  );
  const save = useSetProjectSettings();
  const { toast } = useToast();

  const sig = JSON.stringify(seed);
  useEffect(() => {
    setRows(Object.entries(seed).map(([name, value]) => ({ name, value })));
    // eslint-disable-next-line react-hooks/exhaustive-deps -- sig is the content of the seed map
  }, [sig]);

  // The complete desired map from the current rows (a blank-name row is ignored, matching the
  // "a variable needs a name" rule). It is authoritative on save: a var absent from it is deleted.
  function buildDesired(): Record<string, string> {
    const out: Record<string, string> = {};
    for (const r of rows) {
      const n = r.name.trim();
      if (n) out[n] = r.value;
    }
    return out;
  }
  const desired = buildDesired();
  // Compare the maps ORDER-INDEPENDENTLY: text_variables is unordered and the backend re-serializes
  // it sorted (sort_keys=True), so seed comes back alphabetical while rows keep edit order. A
  // JSON.stringify compare would strand Save permanently Unsaved after a delete-then-re-add that
  // only reorders identical content (the re-seed cannot clear it: a no-op save is byte-identical).
  const dirty = !sameStringMap(desired, seed);

  function onSave() {
    // A row with a value but no name, or a duplicate name, is a clear error the user must fix
    // (the desired map would otherwise silently drop or collide the entry).
    const seen = new Set<string>();
    for (const r of rows) {
      const n = r.name.trim();
      if (!n) {
        if (r.value.trim()) {
          toast("Enter a name for every text variable.", "err");
          return;
        }
        continue;
      }
      if (seen.has(n)) {
        toast(`Duplicate text variable name: ${n}.`, "err");
        return;
      }
      seen.add(n);
    }
    if (!dirty) return;
    save.mutate(
      { id: projectId, text_variables: desired },
      {
        onSuccess: () => toast("Text variables saved."),
        onError: (e) => toast(errMsg(e, "Could not save the text variables."), "err"),
      },
    );
  }

  return (
    <div data-testid="textvars-form">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <h3 className="text-sm font-medium text-t1">Text Variables</h3>
          {dirty ? <Badge tone="warn">Unsaved</Badge> : null}
        </div>
        <Button variant="accent" small onClick={onSave} disabled={!dirty || save.isPending}>
          {save.isPending ? "Saving..." : "Save Text Variables"}
        </Button>
      </div>
      {rows.length === 0 ? (
        <p className="mb-2 text-xs text-t3">This project defines no text variables yet.</p>
      ) : (
        <div className="mb-2 flex flex-col gap-2">
          {rows.map((r, idx) => (
            <div key={idx} className="flex items-center gap-2">
              <input
                type="text"
                data-testid={`tv-name-${idx}`}
                className={`${INPUT_CLS} !py-1 text-xs`}
                placeholder="Name"
                value={r.name}
                onChange={(e) =>
                  setRows((rs) => rs.map((x, i) => (i === idx ? { ...x, name: e.target.value } : x)))
                }
              />
              <input
                type="text"
                data-testid={`tv-value-${idx}`}
                className={`${INPUT_CLS} !py-1 text-xs`}
                placeholder="Value"
                value={r.value}
                onChange={(e) =>
                  setRows((rs) => rs.map((x, i) => (i === idx ? { ...x, value: e.target.value } : x)))
                }
              />
              <Button
                variant="default"
                small
                data-testid={`tv-del-${idx}`}
                onClick={() => setRows((rs) => rs.filter((_, i) => i !== idx))}
              >
                Remove
              </Button>
            </div>
          ))}
        </div>
      )}
      <Button
        variant="default"
        small
        onClick={() => setRows((rs) => [...rs, { name: "", value: "" }])}
      >
        Add Variable
      </Button>
    </div>
  );
}

// The Object Conform editor (M7f-B): retroactively normalize the font size (and, where a font
// carries one, its thickness) of existing text objects across the project to a house standard.
// Preview shows exactly how many objects each type would change; Apply writes a minimal diff to
// every touched sheet + board as one atomic commit on the project's own git. Honest states for a
// project with no board/sheet or not under git.
function ConformSection({ projectId }: { projectId: string }) {
  const q = useProjectConform(projectId);
  const data = q.data;
  return (
    <div className="mt-7 border-t border-line pt-6" data-testid="conform-section">
      <div className="mb-3">
        <Eyebrow className="mb-0.5">Object Conform</Eyebrow>
        <p className="text-xs text-t3">
          Normalize the font size and thickness of existing text objects across the project to a
          standard. Preview the exact count each type would change, then apply it as a minimal
          change committed to the project's own git history.
        </p>
      </div>

      {q.isLoading ? (
        <p className="text-sm text-t3">Loading the conform options...</p>
      ) : q.isError ? (
        <p className="text-sm text-err">{errMsg(q.error, "Could not read the conform options.")}</p>
      ) : !data ? null : !data.has_pcb && !data.has_sch ? (
        <p className="text-sm text-t3" data-testid="conform-no-target">
          This project has no board or schematic files, so there are no text objects to conform.
        </p>
      ) : !data.under_git ? (
        <p className="text-sm text-t3" data-testid="conform-no-git">
          This project is not under git. Initialize a git repository for it to conform its objects,
          so each change is committed atomically and can be undone.
        </p>
      ) : (
        <ConformForm projectId={projectId} data={data} />
      )}
    </div>
  );
}

interface ConformDraftRow {
  enabled: boolean;
  size: string;
  thickness: string;
}

function seedConformDraft(data: ConformCatalog): Record<string, ConformDraftRow> {
  const out: Record<string, ConformDraftRow> = {};
  for (const c of [...data.pcb_categories, ...data.sch_categories]) {
    const s = data.suggested[c.key];
    out[c.key] = {
      enabled: false,
      size: s?.size != null ? String(s.size) : "",
      thickness: s?.thickness != null ? String(s.thickness) : "",
    };
  }
  return out;
}

function ConformForm({ projectId, data }: { projectId: string; data: ConformCatalog }) {
  const [draft, setDraft] = useState<Record<string, ConformDraftRow>>(() => seedConformDraft(data));
  const [preview, setPreview] = useState<ConformPreview | null>(null);
  const previewM = usePreviewConform();
  const applyM = useApplyConform();
  const { toast } = useToast();

  // A project shows only the categories it can actually conform (a board's silk/fab/copper, a
  // sheet's text/labels), so an enabled type always has a file to touch.
  const pcbCats = data.has_pcb ? data.pcb_categories : [];
  const schCats = data.has_sch ? data.sch_categories : [];
  const allCats = [...pcbCats, ...schCats];
  const anySelected = allCats.some((c) => draft[c.key]?.enabled);

  // Any edit invalidates a shown preview (the counts would be stale), so it is cleared until the
  // user previews again.
  function update(key: string, patch: Partial<ConformDraftRow>) {
    setDraft((d) => ({ ...d, [key]: { ...d[key], ...patch } }));
    setPreview(null);
  }

  // A conform target for one enabled category, or null when it names no valid positive dimension
  // (an enabled type with a blank/bad size and thickness is a clear input error, not a silent
  // no-op). A blank dimension is omitted (that dimension is left untouched).
  function targetOf(key: string, label: string): ConformTarget | null {
    const row = draft[key];
    const t: ConformTarget = {};
    for (const [dim, raw] of [
      ["size", row.size],
      ["thickness", row.thickness],
    ] as const) {
      const s = raw.trim();
      if (s === "") continue;
      const n = Number(s);
      if (!Number.isFinite(n) || n <= 0) {
        toast(`Enter a positive ${dim} for ${label}, or leave it blank.`, "err");
        return null;
      }
      t[dim] = n;
    }
    if (t.size === undefined && t.thickness === undefined) {
      toast(`Set a size or thickness for ${label}.`, "err");
      return null;
    }
    return t;
  }

  // The request body from the enabled categories, or null when a selected type has bad input.
  function buildBody(): ConformBody | null {
    const pcb: Record<string, ConformTarget> = {};
    const sch: Record<string, ConformTarget> = {};
    for (const c of pcbCats) {
      if (!draft[c.key].enabled) continue;
      const t = targetOf(c.key, c.label);
      if (!t) return null;
      pcb[c.key] = t;
    }
    for (const c of schCats) {
      if (!draft[c.key].enabled) continue;
      const t = targetOf(c.key, c.label);
      if (!t) return null;
      sch[c.key] = t;
    }
    const body: ConformBody = {};
    if (Object.keys(pcb).length) body.pcb_targets = pcb;
    if (Object.keys(sch).length) body.sch_targets = sch;
    return body;
  }

  function onPreview() {
    const body = buildBody();
    if (!body) return;
    previewM.mutate(
      { id: projectId, ...body },
      {
        onSuccess: (result) => setPreview(result),
        onError: (e) => toast(errMsg(e, "Could not preview the conform."), "err"),
      },
    );
  }

  function onApply() {
    const body = buildBody();
    if (!body) return;
    applyM.mutate(
      { id: projectId, ...body },
      {
        onSuccess: (result) => {
          setPreview(null);
          if (result.committed == null) {
            toast("Nothing to change; every selected object already matches.");
          } else {
            toast(`Conformed ${result.total} ${result.total === 1 ? "object" : "objects"}.`);
          }
        },
        onError: (e) => toast(errMsg(e, "Could not conform the objects."), "err"),
      },
    );
  }

  const busy = previewM.isPending || applyM.isPending;

  return (
    <div data-testid="conform-form">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
        <h3 className="text-sm font-medium text-t1">Text Objects</h3>
        <div className="flex items-center gap-2">
          <Button variant="default" small onClick={onPreview} disabled={!anySelected || busy}>
            {previewM.isPending ? "Previewing..." : "Preview Changes"}
          </Button>
          <Button variant="accent" small onClick={onApply} disabled={!anySelected || busy}>
            {applyM.isPending ? "Conforming..." : "Conform Objects"}
          </Button>
        </div>
      </div>

      <div className="flex flex-col gap-4">
        {pcbCats.length > 0 ? (
          <ConformGroup title="Board Text" cats={pcbCats} draft={draft} onUpdate={update} />
        ) : null}
        {schCats.length > 0 ? (
          <ConformGroup title="Schematic Text" cats={schCats} draft={draft} onUpdate={update} />
        ) : null}
      </div>

      {preview ? (
        <div className="mt-4 rounded-control border border-line2 bg-raise p-3" data-testid="conform-preview">
          {preview.total === 0 ? (
            <p className="text-xs text-t3">
              Nothing to change; every selected object already matches the target.
            </p>
          ) : (
            <div className="flex flex-col gap-1">
              <p className="text-2xs font-medium uppercase tracking-wide text-t3">
                Objects To Change
              </p>
              {preview.files
                .filter((f) => f.changed > 0)
                .map((f) => (
                  <div
                    key={f.path}
                    className="flex items-center justify-between gap-3 text-xs text-t2"
                  >
                    <span className="min-w-0 truncate" title={f.path}>
                      {f.path}
                    </span>
                    <span className="text-t1" data-testid={`conform-file-${f.path}`}>
                      {f.changed}
                    </span>
                  </div>
                ))}
              <p className="mt-1 text-xs text-t1" data-testid="conform-preview-total">
                {preview.total} {preview.total === 1 ? "object" : "objects"} across the project.
              </p>
            </div>
          )}
        </div>
      ) : null}
    </div>
  );
}

function ConformGroup({
  title,
  cats,
  draft,
  onUpdate,
}: {
  title: string;
  cats: ConformCategory[];
  draft: Record<string, ConformDraftRow>;
  onUpdate: (key: string, patch: Partial<ConformDraftRow>) => void;
}) {
  return (
    <div>
      <h4 className="mb-2 text-2xs font-medium uppercase tracking-wide text-t3">{title}</h4>
      <div className="flex flex-col gap-2">
        {cats.map((c) => {
          const row = draft[c.key];
          return (
            <div key={c.key} className="flex flex-wrap items-center gap-3">
              <label className="flex min-w-40 items-center gap-2 text-xs text-t2">
                <input
                  type="checkbox"
                  data-testid={`conform-enable-${c.key}`}
                  checked={row.enabled}
                  onChange={(e) => onUpdate(c.key, { enabled: e.target.checked })}
                />
                <span title={c.hint}>{c.label}</span>
              </label>
              <label className="flex items-center gap-1 text-2xs text-t3">
                Size
                <input
                  type="text"
                  inputMode="decimal"
                  className={`${INPUT_CLS} !w-20 !flex-none !py-1 text-xs`}
                  data-testid={`conform-size-${c.key}`}
                  value={row.size}
                  disabled={!row.enabled}
                  onChange={(e) => onUpdate(c.key, { size: e.target.value })}
                />
              </label>
              <label className="flex items-center gap-1 text-2xs text-t3">
                Thickness
                <input
                  type="text"
                  inputMode="decimal"
                  className={`${INPUT_CLS} !w-20 !flex-none !py-1 text-xs`}
                  data-testid={`conform-thickness-${c.key}`}
                  value={row.thickness}
                  disabled={!row.enabled}
                  onChange={(e) => onUpdate(c.key, { thickness: e.target.value })}
                  placeholder="Keep"
                />
              </label>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// --- M7f-C stackup / fab-preset ----------------------------------------------

const DIELECTRIC_TYPES = ["prepreg", "core"];

function isCopperLayer(l: StackupLayer): boolean {
  return l.type === "copper";
}

function isDielectricLayer(l: StackupLayer): boolean {
  return (
    !isCopperLayer(l) &&
    (l.material !== undefined ||
      l.epsilon_r !== undefined ||
      (l.type != null && DIELECTRIC_TYPES.includes(l.type)))
  );
}

function StackupSection({ projectId }: { projectId: string }) {
  const q = useProjectStackup(projectId);
  const data = q.data;
  return (
    <div className="mt-7 border-t border-line pt-6" data-testid="stackup-section">
      <div className="mb-3">
        <Eyebrow className="mb-0.5">Stackup</Eyebrow>
        <p className="text-xs text-t3">
          Snap the board's physical layer stack to a fab house standard, or edit individual stack
          fields. Each change is written to the board's own git history as a minimal, byte-preserving
          commit.
        </p>
      </div>

      {q.isLoading ? (
        <p className="text-sm text-t3">Loading the stackup...</p>
      ) : q.isError ? (
        <p className="text-sm text-err">{errMsg(q.error, "Could not read the stackup.")}</p>
      ) : !data ? null : !data.has_board ? (
        <p className="text-sm text-t3" data-testid="stackup-no-board">
          This project has no board file, so there is no layer stack to edit.
        </p>
      ) : !data.under_git ? (
        <p className="text-sm text-t3" data-testid="stackup-no-git">
          This project is not under git. Initialize a git repository for it to edit its stackup, so
          each change is committed atomically and can be undone.
        </p>
      ) : (
        <StackupForm projectId={projectId} data={data} />
      )}
    </div>
  );
}

function StackupForm({ projectId, data }: { projectId: string; data: StackupRead }) {
  const stack = data.stackup;
  return (
    <div data-testid="stackup-form" className="flex flex-col gap-5">
      {stack ? (
        <CurrentStackTable stack={stack} thickness={data.thickness} />
      ) : (
        <p className="text-sm text-t3" data-testid="stackup-none">
          This board has no layer stack yet. Apply a fab preset to generate one.
        </p>
      )}
      <StackupPresetBlock projectId={projectId} data={data} />
      {stack ? <StackupFieldBlock projectId={projectId} stack={stack} /> : null}
    </div>
  );
}

function fmtNum(v: number | undefined): string {
  return v != null ? String(v) : "";
}

function CurrentStackTable({
  stack,
  thickness,
}: {
  stack: Stackup;
  thickness: number | null;
}) {
  return (
    <div data-testid="stackup-current">
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <h3 className="text-sm font-medium text-t1">Current Stack</h3>
        <Badge tone="neutral">
          {thickness != null ? `${thickness} mm` : "No Thickness"}
        </Badge>
        <Badge tone="neutral">Finish: {stack.copper_finish ?? "None"}</Badge>
        <Badge tone="neutral">
          Constraints: {stack.dielectric_constraints ? "On" : "Off"}
        </Badge>
      </div>
      <div className="overflow-x-auto rounded-control border border-line2">
        <table className="w-full min-w-[28rem] text-left text-xs">
          <thead className="text-2xs uppercase tracking-wide text-t3">
            <tr className="border-b border-line2">
              <th className="px-3 py-1.5 font-medium">Layer</th>
              <th className="px-3 py-1.5 font-medium">Type</th>
              <th className="px-3 py-1.5 font-medium">Thickness</th>
              <th className="px-3 py-1.5 font-medium">Material</th>
              <th className="px-3 py-1.5 font-medium">Dk / Df</th>
            </tr>
          </thead>
          <tbody>
            {stack.layers.map((l, i) => (
              <tr
                key={`${l.name}-${i}`}
                className="border-b border-line2/50 last:border-0"
                data-testid={`stackup-row-${l.name}`}
              >
                <td className="px-3 py-1.5 text-t1">{l.name}</td>
                <td className="px-3 py-1.5 text-t3">{l.type ?? ""}</td>
                <td className="px-3 py-1.5 text-t2">{fmtNum(l.thickness)}</td>
                <td className="px-3 py-1.5 text-t2">{l.material ?? ""}</td>
                <td className="px-3 py-1.5 text-t3">
                  {l.epsilon_r != null || l.loss_tangent != null
                    ? `${fmtNum(l.epsilon_r) || "?"} / ${fmtNum(l.loss_tangent) || "?"}`
                    : ""}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function stackSummary(s: Stackup | null): string {
  if (!s) return "no stackup";
  const copper = s.layers.filter(isCopperLayer).length;
  return `${copper}-layer, finish ${s.copper_finish ?? "None"}, constraints ${
    s.dielectric_constraints ? "on" : "off"
  }`;
}

function StackupPresetBlock({ projectId, data }: { projectId: string; data: StackupRead }) {
  const [presetKey, setPresetKey] = useState("");
  const [preview, setPreview] = useState<StackupPreview | null>(null);
  const previewM = usePreviewStackup();
  const applyM = useApplyStackup();
  const { toast } = useToast();

  const copperCount = data.copper_layers.length;
  const selected = data.presets.find((p) => p.key === presetKey) ?? null;
  const compatible = selected ? selected.layers === copperCount : false;
  const busy = previewM.isPending || applyM.isPending;

  function choose(k: string) {
    setPresetKey(k);
    setPreview(null);
  }

  function onPreview() {
    if (!selected || !compatible) return;
    previewM.mutate(
      { id: projectId, preset_key: presetKey },
      {
        onSuccess: (r) => setPreview(r),
        onError: (e) => toast(errMsg(e, "Could not preview the preset."), "err"),
      },
    );
  }

  function onApply() {
    if (!selected || !compatible) return;
    applyM.mutate(
      { id: projectId, preset_key: presetKey },
      {
        onSuccess: (r) => {
          setPreview(null);
          toast(
            r.committed == null
              ? "Nothing to change; the board already matches this preset."
              : `Applied the ${selected.label} stackup.`,
          );
        },
        onError: (e) => toast(errMsg(e, "Could not apply the preset."), "err"),
      },
    );
  }

  return (
    <div data-testid="stackup-preset-block">
      <h3 className="mb-2 text-sm font-medium text-t1">Apply a Fab Preset</h3>
      <div className="flex flex-wrap items-center gap-3">
        <select
          data-testid="stackup-preset-select"
          className="rounded-control border border-line2 bg-field px-2 py-1.5 text-sm text-t1 outline-none focus:border-acc"
          value={presetKey}
          onChange={(e) => choose(e.target.value)}
        >
          <option value="">Select a preset...</option>
          {data.presets.map((p) => (
            <option key={p.key} value={p.key}>
              {p.label} ({p.layers}-layer, {p.board_thickness_mm} mm)
            </option>
          ))}
        </select>
        <Button
          variant="default"
          small
          onClick={onPreview}
          disabled={!selected || !compatible || busy}
        >
          {previewM.isPending ? "Previewing..." : "Preview"}
        </Button>
        <Button
          variant="accent"
          small
          onClick={onApply}
          disabled={!selected || !compatible || busy}
        >
          {applyM.isPending ? "Applying..." : "Apply Preset"}
        </Button>
      </div>

      {selected && !compatible ? (
        <p className="mt-2 text-xs text-err" data-testid="stackup-preset-mismatch">
          The {selected.label} preset is {selected.layers}-layer but this board has {copperCount}{" "}
          copper layer{copperCount === 1 ? "" : "s"}. Pick a preset that matches the board.
        </p>
      ) : null}

      {selected && compatible ? (
        <div className="mt-2 rounded-control border border-line2 bg-raise p-3">
          <p className="text-xs text-t2" data-testid="stackup-verify-note">
            {selected.verify_note}
          </p>
          {preview ? (
            <p className="mt-2 text-xs text-t1" data-testid="stackup-preset-preview">
              {preview.changed
                ? `Would set the stack to ${stackSummary(preview.stackup)} and the board to ${
                    preview.thickness ?? "?"
                  } mm.`
                : "The board already matches this preset; applying it changes nothing."}
            </p>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

interface StackupLayerRowDraft {
  thickness: string;
  material: string;
  epsilon_r: string;
  loss_tangent: string;
}

interface StackupFieldDraft {
  copper_finish: string;
  dielectric_constraints: boolean;
  layers: Record<string, StackupLayerRowDraft>;
}

function seedFieldDraft(stack: Stackup): StackupFieldDraft {
  const layers: Record<string, StackupLayerRowDraft> = {};
  for (const l of stack.layers) {
    if (!isCopperLayer(l) && !isDielectricLayer(l)) continue;
    layers[l.name] = {
      thickness: fmtNum(l.thickness),
      material: l.material ?? "",
      epsilon_r: fmtNum(l.epsilon_r),
      loss_tangent: fmtNum(l.loss_tangent),
    };
  }
  return {
    copper_finish: stack.copper_finish ?? "",
    dielectric_constraints: stack.dielectric_constraints ?? false,
    layers,
  };
}

function StackupFieldBlock({ projectId, stack }: { projectId: string; stack: Stackup }) {
  // Content-key re-seed: when the underlying stack changes (a save re-reads it), the draft resets
  // to the new on-disk values rather than showing stale edits (mirrors the other editor forms).
  const sig = JSON.stringify(stack);
  const [draft, setDraft] = useState<StackupFieldDraft>(() => seedFieldDraft(stack));
  const [seededSig, setSeededSig] = useState(sig);
  if (sig !== seededSig) {
    setDraft(seedFieldDraft(stack));
    setSeededSig(sig);
  }
  const [preview, setPreview] = useState<StackupPreview | null>(null);
  const previewM = usePreviewStackup();
  const applyM = useApplyStackup();
  const { toast } = useToast();

  const editable = stack.layers.filter((l) => isCopperLayer(l) || isDielectricLayer(l));
  const byName: Record<string, StackupLayer> = {};
  for (const l of stack.layers) byName[l.name] = l;

  function updateGlobal(patch: Partial<Pick<StackupFieldDraft, "copper_finish" | "dielectric_constraints">>) {
    setDraft((d) => ({ ...d, ...patch }));
    setPreview(null);
  }
  function updateLayer(name: string, patch: Partial<StackupLayerRowDraft>) {
    setDraft((d) => ({ ...d, layers: { ...d.layers, [name]: { ...d.layers[name], ...patch } } }));
    setPreview(null);
  }

  // A per-layer field counts as changed only when it is NON-BLANK and differs from disk: a numeric
  // or material atom is update-if-present (blank leaves it untouched), so buildBody drops a blanked
  // field. dirty() must agree, or clearing a field would light the "Unsaved" badge yet a Save would
  // report a false "No field changed".
  function fieldChanged(raw: string, current: string): boolean {
    const s = raw.trim();
    return s !== "" && s !== current;
  }

  // Whether any field differs from the on-disk stack (enables the buttons without toasting).
  function dirty(): boolean {
    // copper_finish blank-vs-set is a real (if invalid) change attempt, surfaced by buildBody with
    // its own "cannot be blank" message, so a blanked finish still counts as dirty here.
    if (draft.copper_finish.trim() !== (stack.copper_finish ?? "")) return true;
    if (draft.dielectric_constraints !== (stack.dielectric_constraints ?? false)) return true;
    for (const l of editable) {
      const row = draft.layers[l.name];
      if (fieldChanged(row.thickness, fmtNum(l.thickness))) return true;
      if (isDielectricLayer(l)) {
        if (fieldChanged(row.material, l.material ?? "")) return true;
        if (fieldChanged(row.epsilon_r, fmtNum(l.epsilon_r))) return true;
        if (fieldChanged(row.loss_tangent, fmtNum(l.loss_tangent))) return true;
      }
    }
    return false;
  }

  // The request body from only the changed fields, or null when a changed value is bad input.
  function buildBody(): StackupBody | null {
    const body: StackupBody = {};
    const cf = draft.copper_finish.trim();
    if (cf !== (stack.copper_finish ?? "")) {
      if (cf === "") {
        toast("Copper finish cannot be blank.", "err");
        return null;
      }
      body.copper_finish = cf;
    }
    if (draft.dielectric_constraints !== (stack.dielectric_constraints ?? false)) {
      body.dielectric_constraints = draft.dielectric_constraints;
    }
    const edits: Record<string, StackupLayerEdit> = {};
    for (const l of editable) {
      const row = draft.layers[l.name];
      const e: StackupLayerEdit = {};
      const numFields: [keyof StackupLayerEdit, string, number | undefined][] = [
        ["thickness", row.thickness, l.thickness],
      ];
      if (isDielectricLayer(l)) {
        numFields.push(["epsilon_r", row.epsilon_r, l.epsilon_r]);
        numFields.push(["loss_tangent", row.loss_tangent, l.loss_tangent]);
      }
      for (const [field, raw, cur] of numFields) {
        const s = raw.trim();
        if (s === fmtNum(cur)) continue; // unchanged
        if (s === "") continue; // blank leaves it (a numeric atom cannot be cleared)
        const n = Number(s);
        if (!Number.isFinite(n) || n <= 0) {
          toast(`Enter a positive ${field} for ${l.name}.`, "err");
          return null;
        }
        (e[field] as number) = n;
      }
      if (isDielectricLayer(l)) {
        const mat = row.material.trim();
        if (mat !== (l.material ?? "") && mat !== "") e.material = mat;
      }
      if (Object.keys(e).length) edits[l.name] = e;
    }
    if (Object.keys(edits).length) body.layer_edits = edits;
    if (
      body.copper_finish === undefined &&
      body.dielectric_constraints === undefined &&
      body.layer_edits === undefined
    ) {
      toast("No field changed.", "err");
      return null;
    }
    return body;
  }

  function onPreview() {
    const body = buildBody();
    if (!body) return;
    previewM.mutate(
      { id: projectId, ...body },
      {
        onSuccess: (r) => setPreview(r),
        onError: (e) => toast(errMsg(e, "Could not preview the changes."), "err"),
      },
    );
  }
  function onApply() {
    const body = buildBody();
    if (!body) return;
    applyM.mutate(
      { id: projectId, ...body },
      {
        onSuccess: (r) => {
          setPreview(null);
          toast(
            r.committed == null
              ? "Nothing to change; every field already matches."
              : "Saved the stackup fields.",
          );
        },
        onError: (e) => toast(errMsg(e, "Could not save the changes."), "err"),
      },
    );
  }

  const busy = previewM.isPending || applyM.isPending;
  const isDirty = dirty();

  return (
    <div data-testid="stackup-field-block">
      <div className="mb-2 flex flex-wrap items-center justify-between gap-3">
        <h3 className="text-sm font-medium text-t1">Edit Stack Fields</h3>
        <div className="flex items-center gap-2">
          {isDirty ? <Badge tone="warn">Unsaved</Badge> : null}
          <Button variant="default" small onClick={onPreview} disabled={!isDirty || busy}>
            {previewM.isPending ? "Previewing..." : "Preview"}
          </Button>
          <Button variant="accent" small onClick={onApply} disabled={!isDirty || busy}>
            {applyM.isPending ? "Saving..." : "Save Fields"}
          </Button>
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-4">
        <label className="flex items-center gap-1 text-2xs text-t3">
          Copper Finish
          <input
            type="text"
            className={`${INPUT_CLS} !w-28 !flex-none !py-1 text-xs`}
            data-testid="stackup-field-finish"
            value={draft.copper_finish}
            onChange={(e) => updateGlobal({ copper_finish: e.target.value })}
          />
        </label>
        <label className="flex items-center gap-2 text-xs text-t2">
          <input
            type="checkbox"
            data-testid="stackup-field-constraints"
            checked={draft.dielectric_constraints}
            onChange={(e) => updateGlobal({ dielectric_constraints: e.target.checked })}
          />
          Dielectric Constraints
        </label>
      </div>

      <div className="mt-3 flex flex-col gap-2">
        {editable.map((l) => (
          <div key={l.name} className="flex flex-wrap items-center gap-3">
            <span className="min-w-28 text-xs text-t2">{l.name}</span>
            <label className="flex items-center gap-1 text-2xs text-t3">
              Thickness
              <input
                type="text"
                inputMode="decimal"
                className={`${INPUT_CLS} !w-20 !flex-none !py-1 text-xs`}
                data-testid={`stackup-thickness-${l.name}`}
                value={draft.layers[l.name].thickness}
                onChange={(e) => updateLayer(l.name, { thickness: e.target.value })}
              />
            </label>
            {isDielectricLayer(l) ? (
              <>
                <label className="flex items-center gap-1 text-2xs text-t3">
                  Material
                  <input
                    type="text"
                    className={`${INPUT_CLS} !w-24 !flex-none !py-1 text-xs`}
                    data-testid={`stackup-material-${l.name}`}
                    value={draft.layers[l.name].material}
                    onChange={(e) => updateLayer(l.name, { material: e.target.value })}
                  />
                </label>
                <label className="flex items-center gap-1 text-2xs text-t3">
                  Dk
                  <input
                    type="text"
                    inputMode="decimal"
                    className={`${INPUT_CLS} !w-16 !flex-none !py-1 text-xs`}
                    data-testid={`stackup-dk-${l.name}`}
                    value={draft.layers[l.name].epsilon_r}
                    onChange={(e) => updateLayer(l.name, { epsilon_r: e.target.value })}
                  />
                </label>
                <label className="flex items-center gap-1 text-2xs text-t3">
                  Df
                  <input
                    type="text"
                    inputMode="decimal"
                    className={`${INPUT_CLS} !w-16 !flex-none !py-1 text-xs`}
                    data-testid={`stackup-df-${l.name}`}
                    value={draft.layers[l.name].loss_tangent}
                    onChange={(e) => updateLayer(l.name, { loss_tangent: e.target.value })}
                  />
                </label>
              </>
            ) : null}
          </div>
        ))}
      </div>

      {preview ? (
        <p className="mt-3 text-xs text-t1" data-testid="stackup-field-preview">
          {preview.changed
            ? `Would update the stack to ${stackSummary(preview.stackup)}.`
            : "Every field already matches; saving changes nothing."}
        </p>
      ) : null}
    </div>
  );
}

// M7f-D Prepare / Complete-All + Restore + manual library fill.
function PrepareSection({ projectId }: { projectId: string }) {
  const q = useProjectPrepare(projectId);
  const data = q.data;
  return (
    <div className="mt-7 border-t border-line pt-6" data-testid="prepare-section">
      <div className="mb-3">
        <Eyebrow className="mb-0.5">Prepare</Eyebrow>
        <p className="text-xs text-t3">
          Annotate every unnumbered reference and auto-fill each component's blank identity fields from
          your shared components, as one byte-preserving commit on the project's own git. Any component
          that cannot match stays untouched and can be linked by hand.
        </p>
      </div>

      {q.isLoading ? (
        <p className="text-sm text-t3">Loading the prepare plan...</p>
      ) : q.isError ? (
        <p className="text-sm text-err">{errMsg(q.error, "Could not read the prepare plan.")}</p>
      ) : !data ? null : !data.has_sch ? (
        <p className="text-sm text-t3" data-testid="prepare-no-sch">
          This project has no schematic sheet, so there is nothing to annotate or fill.
        </p>
      ) : !data.under_git ? (
        <p className="text-sm text-t3" data-testid="prepare-no-git">
          This project is not under git. Initialize a git repository for it to prepare it, so each
          change is committed atomically and can be undone.
        </p>
      ) : (
        <PrepareForm projectId={projectId} data={data} />
      )}
    </div>
  );
}

function PrepareForm({ projectId, data }: { projectId: string; data: PrepareRead }) {
  const job = useJob<PrepareResult>();
  const invalidate = useInvalidateAfterPrepare();
  const restore = useRestore();
  const { toast } = useToast();
  const [starting, setStarting] = useState(false);
  const [startError, setStartError] = useState<string | null>(null);

  // When a Prepare finishes, refresh the dry-run + derived caches so the residual re-reads.
  useEffect(() => {
    if (job.status === "done") invalidate(projectId);
  }, [job.status, projectId, invalidate]);

  async function onPrepare() {
    setStarting(true);
    setStartError(null);
    try {
      const { job_id } = await api.runPrepare(projectId);
      job.run(job_id);
    } catch (e) {
      const msg = errMsg(e, "Could not start Prepare.");
      setStartError(msg);
      toast(msg, "err");
    } finally {
      setStarting(false);
    }
  }

  function onRestore() {
    restore.mutate(projectId, {
      onSuccess: (r) => toast(`Restored: reverted ${r.short}.`, "ok"),
      onError: (e) => toast(errMsg(e, "Could not restore."), "err"),
    });
  }

  const busy = starting || job.status === "running";
  const result = job.status === "done" ? job.result : null;
  // The residual always follows the LIVE query (`data.completion`), never the frozen job result: a
  // Prepare / manual Link / Restore each invalidates the prepare query, so after any of them the
  // residual + the manual-fill picker re-read the current on-disk state (disk designators the picker
  // can act on). `result` is used only for the one-time "Prepared: ..." summary line.
  const residual: CompletionRoll = data.completion;
  const nothingToPrepare = !result && data.annotate === 0 && data.fill_fields === 0;

  return (
    <div data-testid="prepare-form" className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-sm text-t2" data-testid="prepare-summary">
          {result
            ? result.committed
              ? `Prepared: annotated ${result.annotated} references and filled ${result.fill_fields} fields.`
              : "Prepared: nothing needed annotating or filling."
            : nothingToPrepare
              ? "Nothing to prepare: every reference is numbered and no blank field has a component match."
              : `Prepare would annotate ${data.annotate} references and fill ${data.fill_fields} fields.`}
        </p>
        <div className="flex items-center gap-2">
          <Button
            variant="accent"
            small
            onClick={onPrepare}
            disabled={busy || (nothingToPrepare && !result)}
          >
            {busy ? "Preparing..." : "Prepare / Complete All"}
          </Button>
          <Button
            variant="default"
            small
            onClick={onRestore}
            disabled={restore.isPending}
            data-testid="prepare-restore"
          >
            {restore.isPending ? "Restoring..." : "Restore Last"}
          </Button>
        </div>
      </div>

      {busy && job.progress?.message ? (
        <p className="text-xs text-t3" data-testid="prepare-progress">{job.progress.message}...</p>
      ) : null}
      {startError ? <p className="text-sm text-err">{startError}</p> : null}
      {job.status === "error" ? (
        <p className="text-sm text-err">{job.error ?? "Prepare failed."}</p>
      ) : null}

      <CompletionResidual roll={residual} />
      {residual.incomplete_refs.length > 0 ? (
        <ManualFillPanel projectId={projectId} incompleteRefs={residual.incomplete_refs} />
      ) : (
        <p className="text-xs text-ok" data-testid="prepare-all-complete">
          Every component carries a full identity.
        </p>
      )}
    </div>
  );
}

function CompletionResidual({ roll }: { roll: CompletionRoll }) {
  const missing = Object.entries(roll.missing_counts).sort((a, b) => b[1] - a[1]);
  return (
    <div data-testid="prepare-residual" className="flex flex-wrap items-center gap-2">
      <Badge tone={roll.complete === roll.total ? "ok" : "neutral"}>
        {roll.complete} / {roll.total} Complete
      </Badge>
      {missing.map(([label, count]) => (
        <Badge key={label} tone="warn">
          {count} Missing {label}
        </Badge>
      ))}
    </div>
  );
}

function ManualFillPanel({
  projectId,
  incompleteRefs,
}: {
  projectId: string;
  incompleteRefs: string[];
}) {
  const [ref, setRef] = useState(incompleteRefs[0] ?? "");
  const [search, setSearch] = useState("");
  const [partId, setPartId] = useState("");
  const parts = usePartsQuery({ q: search, category: undefined, completeOnly: true });
  const fill = useManualFill();
  const { toast } = useToast();

  // Keep the selected ref valid as the residual shrinks after each fill.
  useEffect(() => {
    if (!incompleteRefs.includes(ref)) setRef(incompleteRefs[0] ?? "");
  }, [incompleteRefs, ref]);

  // Clear the armed part whenever the target component changes (a manual pick OR the auto-advance
  // after a fill), so Link never fires a part chosen for a DIFFERENT component.
  useEffect(() => {
    setPartId("");
  }, [ref]);

  const options = parts.data?.parts ?? [];

  function onLink() {
    if (!ref || !partId) return;
    fill.mutate(
      { id: projectId, ref, part_id: partId },
      {
        onSuccess: (r) =>
          toast(
            r.committed ? `Linked ${r.ref} to the component.` : `${r.ref} already matches; nothing changed.`,
            r.committed ? "ok" : "neutral",
          ),
        onError: (e) => toast(errMsg(e, "Could not link the component."), "err"),
      },
    );
  }

  return (
    <div
      data-testid="manual-fill-panel"
      className="rounded-control border border-line2 p-3"
    >
      <h3 className="mb-2 text-sm font-medium text-t1">Link a Component</h3>
      <p className="mb-3 text-xs text-t3">
        Pick a component the search could not match, then a part to link it to. Its symbol,
        footprint, and identity fields are set from that part in one commit.
      </p>
      <div className="flex flex-wrap items-end gap-2">
        <label className="flex flex-col gap-1 text-xs text-t3">
          Component
          <select
            data-testid="manual-fill-ref"
            className="rounded-control border border-line2 bg-bg2 px-2 py-1 text-sm text-t1"
            value={ref}
            onChange={(e) => setRef(e.target.value)}
          >
            {incompleteRefs.map((r) => (
              <option key={r} value={r}>
                {r}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1 text-xs text-t3">
          Search Components
          <input
            data-testid="manual-fill-search"
            className="rounded-control border border-line2 bg-bg2 px-2 py-1 text-sm text-t1"
            placeholder="MPN or name"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </label>
        <label className="flex flex-col gap-1 text-xs text-t3">
          Component
          <select
            data-testid="manual-fill-part"
            className="min-w-[12rem] rounded-control border border-line2 bg-bg2 px-2 py-1 text-sm text-t1"
            value={partId}
            onChange={(e) => setPartId(e.target.value)}
          >
            <option value="">Select a part</option>
            {options.map((p) => (
              <option key={p.id} value={p.id}>
                {p.display_name}
                {p.mpn ? ` (${p.mpn})` : ""}
              </option>
            ))}
          </select>
        </label>
        <Button
          variant="accent"
          small
          onClick={onLink}
          disabled={!ref || !partId || fill.isPending}
          data-testid="manual-fill-link"
        >
          {fill.isPending ? "Linking..." : "Link"}
        </Button>
      </div>
    </div>
  );
}
