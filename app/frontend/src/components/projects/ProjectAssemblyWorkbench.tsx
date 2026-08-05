import { Fragment, useEffect, useMemo, useRef, useState } from "react";
import {
  useActiveAssembly,
  useCompleteAssembly,
  useProjectCollaboration,
  useProjectPlacementGeometry,
  useRecordAssemblyEvent,
  useStartAssembly,
} from "../../api/queries";
import type { AssemblyPlacementState } from "../../api/types";
import { Text, useText } from "../../lib/copy";
import { useToast } from "../../lib/toast";
import { Badge, Button, ErrorState, Panel, SectionHeading } from "../primitives";
import { ProjectInspectorFacts } from "./ProjectInspectorFacts";
import { ProjectPlacementStage } from "./ProjectPlacementStage";
import { AdaptiveChoice } from "../AdaptiveChoice";

export function ProjectAssemblyWorkbench({
  projectId,
}: {
  projectId: string;
}) {
  const assembly = useActiveAssembly(projectId);
  const collaboration = useProjectCollaboration(projectId);
  const geometry = useProjectPlacementGeometry(projectId);
  const start = useStartAssembly(projectId);
  const record = useRecordAssemblyEvent(projectId);
  const complete = useCompleteAssembly(projectId);
  const [selectedId, setSelectedId] = useState("");
  const [operator, setOperator] = useState("");
  const [boards, setBoards] = useState(1);
  const [scan, setScan] = useState("");
  const [note, setNote] = useState("");
  const inputRef = useRef<HTMLInputElement | null>(null);
  const { toast } = useToast();
  const runSetupTitle = useText("projects.build.run-setup", "Build Setup");
  const buildCompleteTitle = useText("projects.build.complete", "Build Complete");
  const operatorPlaceholder = useText("projects.build.operator-placeholder", "Your name");
  const scanPlaceholder = useText("projects.build.scan-placeholder", "Scan Stockroom label");
  const notePlaceholder = useText("projects.build.note-placeholder", "Optional note");
  const selectedPlacementLabel = useText(
    "projects.build.selected-placement-aria",
    "Selected placement",
  );
  const placementSelectorLabel = useText(
    "projects.build.placement-selector-aria",
    "Placement",
  );
  const placementStateLabels: Record<AssemblyPlacementState, string> = {
    pending: useText("projects.build.state-pending", "Pending"),
    done: useText("projects.build.state-done", "Placed"),
    reworked: useText("projects.build.state-reworked", "Reworked"),
    skipped: useText("projects.build.state-skipped", "Skipped"),
    issue: useText("projects.build.state-issue", "Issue"),
  };
  const boardField = useText("projects.build.field-board", "Board");
  const sheetField = useText("projects.build.field-sheet", "Sheet");
  const footprintField = useText("projects.build.field-footprint", "Footprint");
  const manufacturerField = useText("projects.build.field-manufacturer", "Manufacturer");
  const libraryPartField = useText("projects.build.field-library-part", "Library Part");
  const notReported = useText("projects.build.not-reported", "Not reported");
  const notSet = useText("projects.build.not-set", "Not set");
  const notLinked = useText("projects.build.not-linked", "Not linked");
  const boardSingular = useText("projects.board", "board");
  const boardPlural = useText("projects.boards", "boards");
  const workingFiles = useText("projects.build.working-files", "working files");
  const checkingRepositoryTitle = useText(
    "projects.build.checking-repository",
    "Checking Repository",
  );
  const checkingRepositoryDetail = useText(
    "projects.build.checking-repository-detail",
    "Reading the linked repository before a build snapshot is pinned.",
  );
  const gitRequiredTitle = useText("projects.build.git-required", "Git Required");
  const gitRequiredDetail = useText(
    "projects.build.git-required-detail",
    "Link this project to a Git repository before starting a physical build.",
  );
  const cleanSnapshotTitle = useText(
    "projects.build.clean-snapshot-required",
    "Clean Snapshot Required",
  );
  const cleanSnapshotDetail = useText(
    "projects.build.clean-snapshot-required-detail",
    "Commit or preserve local project changes before starting a physical build.",
  );
  const readingPlacementsTitle = useText(
    "projects.build.reading-placements",
    "Reading Placements",
  );
  const readingPlacementsDetail = useText(
    "projects.build.reading-placements-detail",
    "Reading the native board placement snapshot.",
  );
  const placementRequiredTitle = useText(
    "projects.build.placement-required",
    "Placement Data Required",
  );
  const placementRequiredDetail = useText(
    "projects.build.placement-required-detail",
    "Resolve the editor blocker, then retry the placement map before starting.",
  );
  const retryPlacementLabel = useText(
    "projects.build.retry-placement",
    "Retry PCB View",
  );
  const identityNeeded = useText("projects.identity-needed", "Identity Needed");
  const couldNotRecord = useText(
    "projects.build.toast-record-failed",
    "Could not record placement",
  );
  const buildStarted = useText("projects.build.toast-started", "Build started");
  const couldNotStart = useText("projects.build.toast-start-failed", "Could not start build");
  const receiptCreated = useText(
    "projects.build.toast-receipt-created",
    "Build receipt created",
  );
  const couldNotComplete = useText(
    "projects.build.toast-complete-failed",
    "Could not complete build",
  );
  const run = assembly.data;
  const repository = collaboration.data?.repository;
  const startBlocker = collaboration.isLoading
    ? { title: checkingRepositoryTitle, detail: checkingRepositoryDetail, retry: false }
    : !repository
      ? { title: gitRequiredTitle, detail: gitRequiredDetail, retry: false }
      : !repository.clean
        ? { title: cleanSnapshotTitle, detail: cleanSnapshotDetail, retry: false }
        : geometry.isLoading
          ? { title: readingPlacementsTitle, detail: readingPlacementsDetail, retry: false }
          : geometry.error || geometry.data?.status !== "ready"
            ? { title: placementRequiredTitle, detail: placementRequiredDetail, retry: true }
            : null;
  const placements = run?.placements ?? [];
  // Pending work first (the queue advances through it), then BOARD, then reference. Without the
  // board term a three-board run interleaved the boards and every row was labelled by reference
  // alone, so the queue read "R1, R1, R1, R2, R2, R2" with nothing to tell the copies apart.
  const ordered = useMemo(
    () =>
      [...placements].sort((a, b) => {
        const aPending = a.state === "pending" ? 0 : 1;
        const bPending = b.state === "pending" ? 0 : 1;
        return (
          aPending - bPending ||
          a.board_index - b.board_index ||
          a.reference.localeCompare(b.reference, undefined, { numeric: true })
        );
      }),
    [placements],
  );
  // One board needs no board banner; more than one needs it on every row.
  const multiBoard = useMemo(
    () => new Set(placements.map((placement) => placement.board_index)).size > 1,
    [placements],
  );
  const mappedReferences = useMemo(
    () =>
      new Set(
        (geometry.data?.placements ?? []).map((placement) =>
          placement.reference.toLocaleUpperCase(),
        ),
      ),
    [geometry.data?.placements],
  );

  useEffect(() => {
    if (!ordered.length) {
      if (selectedId) setSelectedId("");
      return;
    }
    if (geometry.isLoading) return;
    if (!ordered.some((placement) => placement.placement_id === selectedId)) {
      setSelectedId(
        ordered.find(
          (placement) =>
            placement.state === "pending" &&
            mappedReferences.has(placement.reference.toLocaleUpperCase()),
        )?.placement_id ??
          ordered.find((placement) => placement.state === "pending")?.placement_id ??
          ordered[0].placement_id,
      );
    }
  }, [geometry.isLoading, mappedReferences, ordered, selectedId]);

  const selected = ordered.find((placement) => placement.placement_id === selectedId) ?? null;
  // The placement stage draws exactly one board, so its state map must describe that board.
  // The backend emits one placement per (board_index, component), so keying by reference
  // alone collapsed every board into a single entry and let the last board overwrite the
  // rest - a multi-board run showed another board's progress on the selected board.
  const activeBoardIndex = selected?.board_index ?? ordered[0]?.board_index;
  const states = useMemo(
    () =>
      Object.fromEntries(
        placements
          .filter((placement) => placement.board_index === activeBoardIndex)
          .map((placement) => [placement.reference, placement.state]),
      ),
    [placements, activeBoardIndex],
  );
  const progress = run?.progress ?? assemblyProgress(placements);

  function save(state: Exclude<AssemblyPlacementState, "pending">) {
    if (!run || !selected) return;
    record.mutate(
      {
        runId: run.id,
        placementId: selected.placement_id,
        state,
        scannedMpn: scan.trim(),
        note: note.trim(),
      },
      {
        onSuccess: (updated) => {
          setScan("");
          setNote("");
          const next =
            updated.placements.find(
              (placement) =>
                placement.state === "pending" &&
                mappedReferences.has(placement.reference.toLocaleUpperCase()),
            ) ?? updated.placements.find((placement) => placement.state === "pending");
          if (next) setSelectedId(next.placement_id);
          requestAnimationFrame(() => inputRef.current?.focus());
          toast(`${selected.reference} saved`, "ok");
        },
        onError: (error) =>
          toast(error instanceof Error ? error.message : couldNotRecord, "err"),
      },
    );
  }

  if (assembly.isLoading) {
    return (
      <AssemblyMessage>
        <Text id="projects.build.loading">Loading build...</Text>
      </AssemblyMessage>
    );
  }
  if (assembly.error) {
    return (
      <AssemblyMessage>
        <ErrorState dense id="projects.build.failed" onRetry={() => assembly.refetch()}>
          This project's build could not be read.
        </ErrorState>
      </AssemblyMessage>
    );
  }
  if (!run) {
    return (
      <div
        data-dev-id="projects.build"
        className="grid min-h-0 flex-1 grid-cols-[300px_minmax(440px,1fr)] overflow-hidden rounded-card border border-line bg-surface max-[1180px]:grid-cols-[210px_minmax(380px,1fr)]"
      >
        <div className="flex min-h-0 flex-col border-r border-line p-5">
          <div>
            <p className="text-xs font-semibold text-t3">
              <Text id="projects.build.ready-eyebrow">Build Setup</Text>
            </p>
            <h2 className="mt-1 text-xl font-semibold text-t1">
              <Text id="projects.build.start-title">Start Build</Text>
            </h2>
            <p className="mt-2 text-sm leading-6 text-t2">
              <Text id="projects.build.start-detail">
                Pin the current placement snapshot, then record each physical placement.
              </Text>
            </p>
          </div>
          {startBlocker ? (
            <Panel inset className="mt-5">
              <p className="text-sm font-medium text-t1">{startBlocker.title}</p>
              <p className="mt-1 text-xs leading-5 text-t3">{startBlocker.detail}</p>
              {startBlocker.retry ? (
                <Button className="mt-3" onClick={() => geometry.refetch()}>
                  {retryPlacementLabel}
                </Button>
              ) : null}
            </Panel>
          ) : (
            <Panel title={runSetupTitle} className="mt-5">
              <div className="grid gap-4 @xl:grid-cols-[1fr_150px]">
                <label>
                  <span className="mb-1.5 block text-xs font-medium text-t2">
                    <Text id="projects.build.operator">Operator</Text>
                  </span>
                  <input
                    value={operator}
                    onChange={(event) => setOperator(event.target.value)}
                    className={INPUT}
                    placeholder={operatorPlaceholder}
                  />
                </label>
                <label>
                  <span className="mb-1.5 block text-xs font-medium text-t2">
                    <Text id="projects.build.boards">Boards</Text>
                  </span>
                  <input
                    type="number"
                    min={1}
                    max={999}
                    value={boards}
                    onChange={(event) => setBoards(Math.max(1, Number(event.target.value) || 1))}
                    className={INPUT}
                  />
                </label>
              </div>
              <div className="mt-4 flex items-center border-t border-line pt-4">
                <p className="text-xs text-t3">
                  <Text id="projects.build.source">Source: current placement snapshot</Text>
                </p>
                <Button
                  variant="accent"
                  className="ml-auto"
                  disabled={!operator.trim() || start.isPending}
                  onClick={() =>
                    start.mutate(
                      { operator: operator.trim(), boards },
                      {
                        onSuccess: () => toast(buildStarted, "ok"),
                        onError: (error) =>
                          toast(
                            error instanceof Error ? error.message : couldNotStart,
                            "err",
                          ),
                      },
                    )
                  }
                >
                  {start.isPending ? (
                    <Text id="projects.build.starting">Starting...</Text>
                  ) : (
                    <Text id="projects.build.start">Start Build</Text>
                  )}
                </Button>
              </div>
            </Panel>
          )}
        </div>
        <div className="min-h-0 min-w-0">
          <ProjectPlacementStage
            projectId={projectId}
            geometry={geometry.data}
            unavailable={!!geometry.error}
            onRetry={() => geometry.refetch()}
            selectedReferences={[]}
            className="h-full !rounded-none !border-0"
          />
        </div>
      </div>
    );
  }

  return (
    <div data-dev-id="projects.build" className="flex min-h-0 flex-1 flex-col">
      <div className="flex flex-none items-center gap-4 pb-3">
        <div>
          <SectionHeading>
            <Text id="projects.build.title">Build</Text>
          </SectionHeading>
          <p className="mt-0.5 text-xs text-t3">
            {run.operator} · {run.boards}{" "}
            {run.boards === 1 ? boardSingular : boardPlural} ·{" "}
            {run.source_commit ? run.source_commit.slice(0, 8) : workingFiles}
          </p>
        </div>
        <div className="ml-auto text-right">
          <p className="font-mono text-lg font-semibold text-t1">
            {progress.resolved}/{progress.total}
          </p>
          <p className="text-2xs text-t3">
            <Text id="projects.build.placements">placements</Text>
          </p>
        </div>
      </div>
      <div className="mb-3 h-1.5 flex-none overflow-hidden rounded-full bg-field">
        <div
          className="h-full rounded-full bg-acc transition-[width] motion-reduce:transition-none"
          style={{ width: `${progress.percent}%` }}
        />
      </div>

      <div className="grid min-h-0 flex-1 grid-cols-[minmax(0,1fr)_228px] overflow-hidden rounded-card border border-line bg-surface @[60rem]:grid-cols-[220px_minmax(420px,1fr)_250px]">
        <section className="hidden min-h-0 overflow-y-auto border-r border-line @[60rem]:block">
          {ordered.map((placement, index) => {
            const active = placement.placement_id === selectedId;
            // A board banner opens each run of rows from the same board. Pending work sorts
            // ahead of resolved work, so one board legitimately opens two runs; the banner
            // repeats there rather than letting a row sit under the wrong board.
            const opensBoard =
              multiBoard && placement.board_index !== ordered[index - 1]?.board_index;
            return (
              <Fragment key={placement.placement_id}>
                {opensBoard ? (
                  <div className="sticky top-0 z-[1] border-b border-line bg-band px-3 py-1.5 text-2xs font-semibold text-t2">
                    {boardField} {placement.board_index}
                  </div>
                ) : null}
                <button
                  type="button"
                  onClick={() => setSelectedId(placement.placement_id)}
                  className={
                    "relative w-full border-b border-line px-3 py-2.5 text-left transition-colors " +
                    "focus-visible:z-10 focus-visible:outline focus-visible:outline-2 " +
                    "focus-visible:-outline-offset-2 focus-visible:outline-acc " +
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
                  <span className="flex min-w-0 items-center gap-2">
                    <span className="min-w-0 flex-1 truncate font-mono text-sm font-semibold text-t1">
                      {placement.reference}
                    </span>
                    {multiBoard ? (
                      <span className="flex-none font-mono text-2xs text-t3">
                        {boardField} {placement.board_index}
                      </span>
                    ) : null}
                    <PlacementState state={placement.state} />
                  </span>
                  <span className="mt-1 block truncate text-xs font-medium text-t2">
                    {placement.mpn || placement.value || identityNeeded}
                  </span>
                  <span className="mt-0.5 block truncate font-mono text-2xs text-t3">
                    {placement.footprint}
                  </span>
                </button>
              </Fragment>
            );
          })}
        </section>
        <div className="flex min-h-0 min-w-0 flex-col border-r border-line">
          <label className="flex flex-none items-center gap-3 border-b border-line px-3 py-2 @[60rem]:hidden">
            <span className="text-xs font-medium text-t2">
              {placementSelectorLabel}
            </span>
            <AdaptiveChoice
              devId="projects.build-placement-control"
              label={placementSelectorLabel}
              value={selectedId}
              onChange={setSelectedId}
              className="h-8 flex-1"
              options={ordered.map((placement) => ({
                value: placement.placement_id,
                label: `${multiBoard ? `${boardField} ${placement.board_index} · ` : ""}${placement.reference} · ${placementStateLabels[placement.state]} · ${placement.mpn || placement.value || identityNeeded}`,
              }))}
            />
          </label>
          <ProjectPlacementStage
            projectId={projectId}
            geometry={geometry.data}
            unavailable={!!geometry.error}
            onRetry={() => geometry.refetch()}
            selectedReferences={selected ? [selected.reference] : []}
            activeReference={selected?.reference ?? ""}
            states={states}
            onSelectReference={(reference) => {
              // Prefer the placement on the board currently drawn; the same reference exists
              // once per board, so matching on reference alone selected another board's row.
              const placement =
                ordered.find(
                  (candidate) =>
                    candidate.reference === reference &&
                    candidate.board_index === activeBoardIndex,
                ) ?? ordered.find((candidate) => candidate.reference === reference);
              if (placement) setSelectedId(placement.placement_id);
            }}
            className="min-h-0 flex-1 !rounded-none !border-0"
          />
        </div>
        <aside className="min-h-0 overflow-y-auto p-4" aria-label={selectedPlacementLabel}>
          {selected ? (
            <>
              <div className="flex items-start gap-3">
                <div className="min-w-0 flex-1">
                  <p className="text-xs font-semibold text-t3">
                    <Text id="projects.build.current-placement">Current Placement</Text>
                  </p>
                  <h3 className="mt-1 font-mono text-2xl font-semibold text-t1">
                    {selected.reference}
                  </h3>
                  <p className="mt-1 text-sm text-t2">
                    {selected.mpn || selected.value || identityNeeded}
                  </p>
                </div>
                <PlacementState state={selected.state} />
              </div>
              <ProjectInspectorFacts
                items={[
                  { label: boardField, value: selected.board_index, mono: true },
                  { label: sheetField, value: selected.sheet || notReported },
                  {
                    label: footprintField,
                    value: selected.footprint || notSet,
                    mono: true,
                  },
                  {
                    label: manufacturerField,
                    value: selected.manufacturer || notSet,
                  },
                  {
                    label: libraryPartField,
                    value: selected.part_id || notLinked,
                    mono: true,
                  },
                ]}
              />
              <div className="mt-4">
                <label>
                  <span className="mb-1.5 block text-xs font-medium text-t2">
                    <Text id="projects.build.scan">Scan Part</Text>
                  </span>
                  <input
                    ref={inputRef}
                    autoFocus
                    value={scan}
                    onChange={(event) => setScan(event.target.value)}
                    onKeyDown={(event) => {
                      if (event.key === "Enter" && !record.isPending) save("done");
                    }}
                    className={INPUT}
                    placeholder={selected.mpn || scanPlaceholder}
                  />
                </label>
                <label className="mt-3 block">
                  <span className="mb-1.5 block text-xs font-medium text-t2">
                    <Text id="projects.build.note">Note</Text>
                  </span>
                  <input
                    value={note}
                    onChange={(event) => setNote(event.target.value)}
                    className={INPUT}
                    placeholder={notePlaceholder}
                  />
                </label>
                <div className="mt-4 flex flex-wrap gap-2">
                  <Button
                    variant="accent"
                    disabled={record.isPending}
                    onClick={() => save("done")}
                  >
                    <Text id="projects.build.mark-placed">Mark Placed</Text>
                  </Button>
                  <Button disabled={record.isPending} onClick={() => save("skipped")}>
                    <Text id="projects.build.skip">Skip</Text>
                  </Button>
                  <Button disabled={record.isPending} onClick={() => save("reworked")}>
                    <Text id="projects.build.mark-reworked">Mark Reworked</Text>
                  </Button>
                  <Button
                    variant="ghost-danger"
                    disabled={record.isPending}
                    onClick={() => save("issue")}
                  >
                    <Text id="projects.build.record-issue">Record Issue</Text>
                  </Button>
                </div>
              </div>
              {progress.resolved === progress.total ? (
                <Panel title={buildCompleteTitle} className="mt-5">
                  <p className="text-xs leading-5 text-t3">
                    <Text id="projects.build.complete-detail">
                      Create a receipt from the saved placement events.
                    </Text>
                  </p>
                  <Button
                    variant="accent"
                    className="mt-3"
                    disabled={complete.isPending}
                    onClick={() =>
                      complete.mutate(run.id, {
                        onSuccess: () => toast(receiptCreated, "ok"),
                        onError: (error) =>
                          toast(
                            error instanceof Error
                              ? error.message
                              : couldNotComplete,
                            "err",
                          ),
                      })
                    }
                  >
                    {complete.isPending ? (
                      <Text id="projects.build.creating">Creating...</Text>
                    ) : (
                      <Text id="projects.build.create-receipt">Create Receipt</Text>
                    )}
                  </Button>
                </Panel>
              ) : null}
            </>
          ) : (
            <AssemblyMessage>
              <Text id="projects.build.select-placement">Select a placement.</Text>
            </AssemblyMessage>
          )}
        </aside>
      </div>
    </div>
  );
}

const INPUT =
  "h-9 w-full rounded-control border border-line bg-field px-3 text-sm text-t1 outline-none " +
  "placeholder:text-t3 focus:border-acc focus-visible:outline focus-visible:outline-2 " +
  "focus-visible:outline-offset-1 focus-visible:outline-acc";

function PlacementState({ state }: { state: AssemblyPlacementState }) {
  const tone =
    state === "done" || state === "reworked"
      ? "ok"
      : state === "issue"
        ? "err"
        : state === "skipped"
          ? "warn"
          : "neutral";
  const fallback =
    state === "pending"
      ? "Pending"
      : state === "done"
        ? "Placed"
        : state === "reworked"
          ? "Reworked"
          : state === "skipped"
            ? "Skipped"
            : "Issue";
  const label = useText(`projects.build.state-${state}`, fallback);
  return (
    <Badge size="sm" tone={tone}>
      {label}
    </Badge>
  );
}

function assemblyProgress(
  placements: Array<{ state: AssemblyPlacementState }>,
) {
  const counts: Record<AssemblyPlacementState, number> = {
    pending: 0,
    done: 0,
    skipped: 0,
    reworked: 0,
    issue: 0,
  };
  for (const placement of placements) counts[placement.state] += 1;
  const resolved = counts.done + counts.skipped + counts.reworked;
  return {
    total: placements.length,
    complete: counts.done,
    resolved,
    percent: placements.length ? Math.round((resolved / placements.length) * 1000) / 10 : 0,
    counts,
  };
}

function AssemblyMessage({
  children,
  tone = "neutral",
}: {
  children: React.ReactNode;
  tone?: "neutral" | "err";
}) {
  return (
    <div
      data-dev-id="projects.build"
      className={`flex min-h-[260px] flex-1 items-center justify-center p-6 text-center text-sm ${
        tone === "err" ? "text-err" : "text-t3"
      }`}
    >
      {children}
    </div>
  );
}
