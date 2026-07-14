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
import { ApiError } from "../api/client";
import {
  useProjectsQuery,
  useProjectAudit,
  useRegisterProject,
  useDeleteProject,
} from "../api/queries";
import type { AuditFinding, AuditResult, ProjectSummary } from "../api/types";
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
