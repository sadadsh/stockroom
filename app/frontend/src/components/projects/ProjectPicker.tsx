import { useEffect, useMemo, useRef, useState } from "react";
import type { DiscoveredProject, ProjectSummary } from "../../api/types";
import { ApiError } from "../../api/client";
import { useDiscoverProjects, useRegisterProject } from "../../api/queries";
import { BoardIcon, CloseIcon, SearchIcon } from "../icons";
import { Badge, Button, EmptyState, ErrorState, LoadingState, RouteHeader } from "../primitives";
import { useToast } from "../../lib/toast";
import { Text, useText } from "../../lib/copy";
import { pickHostFolder } from "../../lib/hostFolderPicker";

const INPUT =
  "h-9 w-full rounded-control border border-line bg-field px-3 text-sm text-t1 outline-none " +
  "placeholder:text-t3 focus:border-acc focus-visible:outline focus-visible:outline-2 " +
  "focus-visible:outline-offset-1 focus-visible:outline-acc";

export function ProjectPicker({
  projects,
  selectedId,
  loading,
  error,
  onSelect,
  onRetry,
}: {
  projects: ProjectSummary[];
  selectedId: string | null;
  loading: boolean;
  error: Error | null;
  onSelect: (id: string) => void;
  onRetry: () => void;
}) {
  const [search, setSearch] = useState("");
  const [linkOpen, setLinkOpen] = useState(false);
  const projectButtons = useRef(new Map<string, HTMLButtonElement>());
  const pickerLabel = useText("projects.picker.aria", "Project picker");
  const searchPlaceholder = useText("projects.picker.search-placeholder", "Find projects");
  const clearSearchLabel = useText("projects.picker.clear-search", "Clear Search");
  const listLabel = useText("projects.picker.list-aria", "Projects");
  const boardLabel = useText("projects.board", "board");
  const boardsLabel = useText("projects.boards", "boards");
  const gitLabel = useText("projects.git", "Git");
  const localLabel = useText("projects.local", "Local");
  const kicadLabel = useText("projects.eda.kicad", "KiCad");
  const altiumLabel = useText("projects.eda.altium", "Altium");
  const filtered = useMemo(() => {
    const query = search.trim().toLocaleLowerCase();
    if (!query) return projects;
    return projects.filter((project) =>
      `${project.name} ${project.root} ${project.eda}`.toLocaleLowerCase().includes(query),
    );
  }, [projects, search]);
  const selectedVisible = filtered.some((project) => project.id === selectedId);

  function moveSelection(currentId: string, key: string) {
    if (!filtered.length) return;
    const current = filtered.findIndex((project) => project.id === currentId);
    const nextIndex =
      key === "Home"
        ? 0
        : key === "End"
          ? filtered.length - 1
          : key === "ArrowUp"
            ? Math.max(0, current - 1)
            : Math.min(filtered.length - 1, current + 1);
    const next = filtered[nextIndex < 0 ? 0 : nextIndex];
    onSelect(next.id);
    projectButtons.current.get(next.id)?.focus();
  }

  return (
    <aside
      data-dev-id="projects.picker"
      className="flex w-[320px] flex-none flex-col max-[1180px]:w-[224px]"
      aria-label={pickerLabel}
    >
      <RouteHeader
        data-dev-id="projects.list-title"
        right={projects.length ? projects.length.toLocaleString() : undefined}
      >
        <Text id="projects.picker.title">Projects</Text>
      </RouteHeader>
      <div className="px-3 pt-3">
        <Button
          variant="soft"
          icon={<BoardIcon />}
          className="mb-2.5 h-9 w-full justify-center"
          onClick={() => setLinkOpen(true)}
        >
          <Text id="projects.picker.link">Link Project</Text>
        </Button>
        <label className="relative block">
          <span className="sr-only">
            <Text id="projects.picker.find">Find Projects</Text>
          </span>
          <span
            aria-hidden
            className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-t3"
          >
            <SearchIcon />
          </span>
          <input
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            className={`${INPUT} pl-9 ${search ? "pr-9" : ""}`}
            placeholder={searchPlaceholder}
          />
          {search ? (
            <button
              type="button"
              aria-label={clearSearchLabel}
              onClick={() => setSearch("")}
              className="absolute right-1.5 top-1/2 flex size-6 -translate-y-1/2 items-center justify-center rounded-control text-t3 hover:bg-raise hover:text-t1 focus-visible:outline focus-visible:outline-2 focus-visible:outline-acc"
            >
              <CloseIcon />
            </button>
          ) : null}
        </label>
      </div>
      <div className="mt-2 min-h-0 flex-1 overflow-y-auto px-3 pb-3">
        {loading ? (
          <LoadingState className="mt-2" id="projects.picker.loading">
            Loading this machine's linked projects...
          </LoadingState>
        ) : error ? (
          // A written sentence and the shared retry, not `error.message` and a bare button.
          <ErrorState className="mt-2" id="projects.picker.failed" onRetry={onRetry}>
            This machine's linked projects could not be listed.
          </ErrorState>
        ) : projects.length === 0 ? (
          <div className="flex flex-col items-center gap-2.5 px-5 py-10 text-center">
            <span className="text-t3">
              <BoardIcon />
            </span>
            <p className="text-sm font-medium text-t2">
              <Text id="projects.picker.empty-title">No Linked Projects</Text>
            </p>
            <p className="text-xs leading-5 text-t3">
              <Text id="projects.picker.empty-detail">
                Link a KiCad or Altium project folder.
              </Text>
            </p>
          </div>
        ) : filtered.length === 0 ? (
          <EmptyState className="mt-2" id="projects.picker.no-match">
            No project matches this search.
          </EmptyState>
        ) : (
          <div className="space-y-1" role="listbox" aria-label={listLabel}>
            {filtered.map((project) => {
              const active = project.id === selectedId;
              return (
                <button
                  type="button"
                  role="option"
                  aria-selected={active}
                  tabIndex={active || (!selectedVisible && project === filtered[0]) ? 0 : -1}
                  ref={(node) => {
                    if (node) projectButtons.current.set(project.id, node);
                    else projectButtons.current.delete(project.id);
                  }}
                  key={project.id}
                  onClick={() => onSelect(project.id)}
                  onKeyDown={(event) => {
                    if (
                      event.key === "ArrowDown" ||
                      event.key === "ArrowUp" ||
                      event.key === "Home" ||
                      event.key === "End"
                    ) {
                      event.preventDefault();
                      moveSelection(project.id, event.key);
                    }
                  }}
                  title={project.root}
                  className={
                    "group relative w-full rounded-control px-2.5 py-2.5 text-left transition-colors " +
                    "focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-1 " +
                    "focus-visible:outline-acc " +
                    (active ? "bg-raise2" : "hover:bg-raise")
                  }
                >
                  <span
                    aria-hidden
                    className={
                      "absolute inset-y-2 left-0 w-0.5 rounded-full " +
                      (active ? "bg-acc" : "bg-transparent")
                    }
                  />
                  <span className="flex items-start gap-2.5">
                    <span
                      className={
                        "mt-0.5 flex h-7 w-7 flex-none items-center justify-center rounded-control " +
                        (active ? "bg-acc-soft text-acc" : "bg-field text-t3")
                      }
                    >
                      <BoardIcon />
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-sm font-semibold text-t1">
                        {project.name}
                      </span>
                      <span className="mt-1 flex items-center gap-1.5">
                        <Badge size="sm" tone="neutral">
                          {project.eda === "kicad" ? kicadLabel : altiumLabel}
                        </Badge>
                        <span className="text-2xs text-t3">
                          {project.board_count}{" "}
                          {project.board_count === 1 ? boardLabel : boardsLabel}
                        </span>
                        <span aria-hidden className="text-line2">
                          ·
                        </span>
                        <span className={project.has_git ? "text-2xs text-ok" : "text-2xs text-warn"}>
                          {project.has_git ? gitLabel : localLabel}
                        </span>
                      </span>
                    </span>
                  </span>
                </button>
              );
            })}
          </div>
        )}
      </div>
      {linkOpen ? (
        <LinkProjectDialog
          onClose={() => setLinkOpen(false)}
          onLinked={(id) => onSelect(id)}
        />
      ) : null}
    </aside>
  );
}

function LinkProjectDialog({
  onClose,
  onLinked,
}: {
  onClose: () => void;
  onLinked: (id: string) => void;
}) {
  const [folder, setFolder] = useState("");
  const [choice, setChoice] = useState<DiscoveredProject | null>(null);
  const discover = useDiscoverProjects();
  const register = useRegisterProject();
  const { toast } = useToast();
  const results = discover.data?.projects ?? [];
  const closeLabel = useText("projects.picker.dialog-close", "Close");
  const folderPlaceholder = useText(
    "projects.picker.folder-placeholder",
    "Project or repository folder",
  );
  const detectedLabel = useText("projects.picker.detected-aria", "Detected projects");
  const linkFailed = useText("projects.picker.toast-link-failed", "Could not link project");
  const linkedLabel = useText("projects.picker.toast-linked", "linked");
  const boardLabel = useText("projects.board", "board");
  const boardsLabel = useText("projects.boards", "boards");
  const schematicLabel = useText("projects.schematic", "schematic");
  const schematicsLabel = useText("projects.schematics", "schematics");

  useEffect(() => {
    if (results.length === 1) {
      setChoice(results[0]);
      return;
    }
    if (
      choice &&
      !results.some(
        (project) => project.root === choice.root && project.eda === choice.eda,
      )
    ) {
      setChoice(null);
    }
  }, [discover.data, results, choice]);

  async function chooseFolder() {
    try {
      const selected = await pickHostFolder("project");
      if (selected) {
        setFolder(selected);
        setChoice(null);
        discover.mutate(selected);
      }
    } catch (error) {
      toast(error instanceof Error ? error.message : linkFailed, "err");
    }
  }

  function inspect() {
    const candidate = folder.trim();
    if (!candidate) return;
    setChoice(null);
    discover.mutate(candidate);
  }

  function link() {
    if (!choice) return;
    register.mutate(choice, {
      onSuccess: (project) => {
        toast(`${choice.name} ${linkedLabel}`, "ok");
        onLinked(project.id);
        onClose();
      },
      onError: (error) =>
        toast(error instanceof ApiError ? error.message : linkFailed, "err"),
    });
  }

  return (
    <div
      className="fixed inset-0 z-[90] flex items-center justify-center bg-scrim p-5"
      role="presentation"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <section
        role="dialog"
        aria-modal="true"
        aria-labelledby="link-project-title"
        className="w-full max-w-[620px] rounded-card border border-line bg-surface shadow-pop"
      >
        <header className="flex h-[44px] items-center border-b border-line bg-band px-4">
          <h2 id="link-project-title" className="text-sm font-semibold text-t1">
            <Text id="projects.picker.dialog-title">Link Project</Text>
          </h2>
          <button
            type="button"
            aria-label={closeLabel}
            onClick={onClose}
            className="ml-auto rounded-control p-1.5 text-t3 hover:bg-raise hover:text-t1 focus-visible:outline focus-visible:outline-2 focus-visible:outline-acc"
          >
            <CloseIcon />
          </button>
        </header>
        <div className="p-5">
          <p className="mb-4 max-w-[520px] text-sm leading-6 text-t2">
            <Text id="projects.picker.dialog-detail">
              Choose a project folder or repository to find KiCad and Altium projects.
            </Text>
          </p>
          <div className="flex gap-2">
            <input
              autoFocus
              value={folder}
              onChange={(event) => setFolder(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter") inspect();
              }}
              className={INPUT}
              placeholder={folderPlaceholder}
            />
            <Button onClick={chooseFolder}>
              <Text id="projects.picker.choose-folder">Choose Folder</Text>
            </Button>
            <Button variant="accent" onClick={inspect} disabled={!folder.trim() || discover.isPending}>
              {discover.isPending ? (
                <Text id="projects.picker.finding">Finding...</Text>
              ) : (
                <Text id="projects.picker.find-projects">Find Projects</Text>
              )}
            </Button>
          </div>
          {discover.error ? (
            <ErrorState className="mt-3" id="projects.picker.discover-failed">
              This machine could not be searched for projects.
            </ErrorState>
          ) : null}
          {discover.isSuccess && results.length === 0 ? (
            <p className="mt-4 rounded-card border border-line bg-field p-4 text-sm text-t2">
              <Text id="projects.picker.none-found">
                No KiCad or Altium projects found.
              </Text>
            </p>
          ) : null}
          {results.length > 0 ? (
            <div className="mt-4 space-y-2" role="radiogroup" aria-label={detectedLabel}>
              {results.map((project) => {
                const selected =
                  choice?.root === project.root && choice?.eda === project.eda;
                return (
                  <button
                    type="button"
                    role="radio"
                    aria-checked={selected}
                    key={`${project.eda}:${project.descriptor}`}
                    onClick={() => setChoice(project)}
                    className={
                      "flex w-full items-start gap-3 rounded-card border p-3 text-left transition-colors " +
                      "focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 " +
                      "focus-visible:outline-acc " +
                      (selected
                        ? "border-acc bg-acc-soft"
                        : "border-line bg-surface hover:bg-raise")
                    }
                  >
                    <span className="mt-0.5 text-t3">
                      <BoardIcon />
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="flex items-center gap-2">
                        <span className="font-semibold text-t1">{project.name}</span>
                        <Badge size="sm" tone="neutral">
                          {project.eda_label}
                        </Badge>
                      </span>
                      <span className="mt-1 block truncate font-mono text-2xs text-t3">
                        {project.descriptor}
                      </span>
                      <span className="mt-1 block text-xs text-t2">
                        {project.boards.length}{" "}
                        {project.boards.length === 1 ? boardLabel : boardsLabel} ·{" "}
                        {project.schematics.length}{" "}
                        {project.schematics.length === 1
                          ? schematicLabel
                          : schematicsLabel}
                      </span>
                    </span>
                  </button>
                );
              })}
            </div>
          ) : null}
        </div>
        <footer className="flex items-center justify-end gap-2 border-t border-line px-5 py-3.5">
          <Button onClick={onClose}>
            <Text id="projects.cancel">Cancel</Text>
          </Button>
          <Button
            variant="accent"
            onClick={link}
            disabled={!choice || register.isPending}
          >
            {register.isPending ? (
              <Text id="projects.picker.linking">Linking...</Text>
            ) : (
              <Text id="projects.picker.link">Link Project</Text>
            )}
          </Button>
        </footer>
      </section>
    </div>
  );
}
