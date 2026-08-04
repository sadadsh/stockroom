/**
 * Projects is the cross-EDA collaboration workspace. Its shell deliberately follows
 * Components: one docked picker, one selected specimen, one compact title band, and
 * contextual workbench tabs. KiCad and Altium share every React component and every
 * normalized workflow; adapter-specific behavior ends at the API boundary.
 */
import { useEffect, useState } from "react";
import {
  useProjectCollaboration,
  useProjects,
  useProjectWorkspace,
} from "../api/queries";
import { ProjectPicker } from "../components/projects/ProjectPicker";
import { ProjectDesignWorkbench } from "../components/projects/ProjectDesignWorkbench";
import { ProjectBomWorkbench } from "../components/projects/ProjectBomWorkbench";
import { ProjectAssemblyWorkbench } from "../components/projects/ProjectAssemblyWorkbench";
import { ProjectChangesWorkbench } from "../components/projects/ProjectChangesWorkbench";
import {
  Badge,
  Dot,
  EmptyState,
  ErrorState,
  LoadingState,
  TabPanel,
  TabStrip,
  type TabItem,
} from "../components/primitives";
import { Text, useText } from "../lib/copy";
import { readUiSession, updateUiSession } from "../lib/uiSession";

type ProjectTool = "overview" | "bom" | "build" | "activity";

export function ProjectsPage() {
  const projects = useProjects();
  const [selectedId, setSelectedId] = useState<string | null>(
    () => readUiSession().selected_ids.project,
  );
  const summaries = projects.data ?? [];

  useEffect(() => {
    if (readUiSession().selected_ids.project === selectedId) return;
    updateUiSession((snapshot) => ({
      ...snapshot,
      selected_ids: { ...snapshot.selected_ids, project: selectedId },
    }));
  }, [selectedId]);

  useEffect(() => {
    if (projects.isFetching) return;
    if (!summaries.length) {
      if (selectedId) setSelectedId(null);
      return;
    }
    if (!selectedId || !summaries.some((project) => project.id === selectedId)) {
      setSelectedId(summaries[0].id);
    }
  }, [summaries, selectedId, projects.isFetching]);

  return (
    <div data-dev-id="projects.root" className="flex min-h-0 flex-1">
      <ProjectPicker
        projects={summaries}
        selectedId={selectedId}
        loading={projects.isLoading}
        error={projects.error}
        onSelect={setSelectedId}
        onRetry={() => projects.refetch()}
      />
      <main className="min-h-0 min-w-0 flex-1 overflow-hidden border-l border-line">
        {selectedId ? (
          <SelectedProject key={selectedId} projectId={selectedId} />
        ) : (
          <div className="flex h-full items-center justify-center p-8 text-center">
            {projects.isLoading ? (
              <LoadingState dense id="projects.loading">
                Loading this machine's linked projects...
              </LoadingState>
            ) : (
              <EmptyState dense id="projects.empty">
                Link a project or select one from the list.
              </EmptyState>
            )}
          </div>
        )}
      </main>
    </div>
  );
}

function SelectedProject({ projectId }: { projectId: string }) {
  const workspace = useProjectWorkspace(projectId);
  const collaboration = useProjectCollaboration(projectId);
  const [tool, setTool] = useState<ProjectTool>("overview");
  const overviewLabel = useText("projects.tab.overview", "Overview");
  const bomLabel = useText("projects.tab.bom", "BOM");
  const buildLabel = useText("projects.tab.build", "Build");
  const activityLabel = useText("projects.tab.activity", "Activity");
  const toolsLabel = useText("projects.tabs.aria", "Project views");
  const cleanLabel = useText("projects.git.clean", "clean");
  const changedLabel = useText("projects.git.changed", "changed");
  const workingLabel = useText("projects.session.working", "working");

  if (workspace.isLoading) {
    return (
      <WorkspaceMessage>
        <LoadingState dense id="projects.workspace.loading">
          Loading this project...
        </LoadingState>
      </WorkspaceMessage>
    );
  }
  if (workspace.error || !workspace.data) {
    return (
      <WorkspaceMessage>
        {/* A written sentence and one retry. `workspace.error.message` is a transport string
            (a status line, a stack) and was shown to the person verbatim. */}
        <ErrorState id="projects.workspace.error" onRetry={() => workspace.refetch()}>
          This project could not be opened.
        </ErrorState>
      </WorkspaceMessage>
    );
  }

  const data = workspace.data;
  const tabs: TabItem<ProjectTool>[] = [
    { id: "overview", label: overviewLabel },
    { id: "bom", label: bomLabel },
    { id: "build", label: buildLabel },
    { id: "activity", label: activityLabel },
  ];
  const active = tabs.some((tab) => tab.id === tool) ? tool : "overview";
  const repo = collaboration.data?.repository;
  const session = collaboration.data?.session;

  return (
    <div data-dev-id="projects.workspace" className="flex h-full min-h-0 flex-col">
      <div
        data-dev-id="projects.title-strip"
        className="flex h-[34px] flex-none items-center gap-4 border-b border-line bg-band px-5 max-[1180px]:gap-2 max-[1180px]:px-3"
      >
        <div className="flex min-w-0 items-center gap-2">
          <h1
            className="min-w-0 truncate text-sm font-semibold tracking-[-0.01em] text-t1"
            title={`${data.project.name}\n${data.project.root}`}
          >
            {data.project.name}
          </h1>
          <RuntimeBadge
            editor={data.eda_label}
            status={data.runtime.status}
            available={data.runtime.available}
          />
          <span aria-hidden className="mx-0.5 h-3.5 w-px flex-none bg-line2" />
          {repo ? (
            <span
              className="flex min-w-0 items-center gap-1.5 text-2xs text-t3"
              title={`${repo.branch} · ${
                repo.clean ? cleanLabel : `${repo.dirty_paths.length} ${changedLabel}`
              }`}
            >
              <Dot
                tone={
                  repo.clean && repo.ahead === 0 && repo.behind === 0
                    ? "ok"
                    : "warn"
                }
              />
              <span className="max-w-[10rem] truncate font-mono text-t2">
                {repo.branch}
              </span>
              <span className="whitespace-nowrap">
                {repo.clean
                  ? cleanLabel
                  : `${repo.dirty_paths.length} ${changedLabel}`}
              </span>
            </span>
          ) : (
            <span className="whitespace-nowrap text-2xs text-warn">
              <Text id="projects.no-repository">No Git repository</Text>
            </span>
          )}
          {session ? (
            <span className="min-w-0 truncate text-2xs text-ok">
              {session.owner} {workingLabel}
            </span>
          ) : null}
        </div>
        <div className="ml-auto flex-none">
          <TabStrip
            tabs={tabs}
            active={active}
            onSelect={setTool}
            idBase="project-workbench"
            devIdBase="projects"
            aria-label={toolsLabel}
          />
        </div>
      </div>

      <div className="@container flex min-h-0 flex-1 flex-col">
        {active === "overview" ? (
          <TabPanel idBase="project-workbench" tab="overview" className="flex min-h-0 flex-1 flex-col">
            <ProjectDesignWorkbench workspace={data} collaboration={collaboration.data} />
          </TabPanel>
        ) : null}
        {active === "bom" ? (
          <TabPanel idBase="project-workbench" tab="bom" className="flex min-h-0 flex-1 flex-col">
            <ProjectBomWorkbench projectId={projectId} workspace={data} />
          </TabPanel>
        ) : null}
        {active === "build" ? (
          <TabPanel idBase="project-workbench" tab="build" className="flex min-h-0 flex-1 flex-col">
            <ProjectAssemblyWorkbench projectId={projectId} />
          </TabPanel>
        ) : null}
        {active === "activity" ? (
          <TabPanel idBase="project-workbench" tab="activity" className="flex min-h-0 flex-1 flex-col">
            <ProjectChangesWorkbench projectId={projectId} workspace={data} />
          </TabPanel>
        ) : null}
      </div>
    </div>
  );
}

function RuntimeBadge({
  editor,
  status,
  available,
}: {
  editor: string;
  status: string;
  available: boolean;
}) {
  const readyLabel = useText("projects.editor-ready", "Ready");
  const busyLabel = useText("projects.editor-busy", "Busy");
  const neededLabel = useText("projects.editor-needed", "Needed");
  const blockedLabel = useText("projects.editor-blocked", "Blocked");

  if (available || status === "ready") {
    return (
      <Badge size="sm" tone="ok">
        {editor} {readyLabel}
      </Badge>
    );
  }
  if (status === "busy") {
    return (
      <Badge size="sm" tone="warn">
        {editor} {busyLabel}
      </Badge>
    );
  }
  if (status === "unavailable" || status === "not-installed") {
    return (
      <Badge size="sm" tone="warn">
        {editor} {neededLabel}
      </Badge>
    );
  }
  return (
    <Badge size="sm" tone="warn">
      {editor} {blockedLabel}
    </Badge>
  );
}

/** The centring frame the route's state block sits in. The state decides its own tone. */
function WorkspaceMessage({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex h-full min-h-[300px] flex-col items-center justify-center gap-3 p-8 text-center">
      {children}
    </div>
  );
}
