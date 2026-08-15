import { useEffect, useMemo, useState } from "react";
import {
  useProjectVisualArtifact,
  useProjectVisuals,
  useRefreshProjectVisuals,
} from "../../api/queries";
import type {
  AssemblyPlacementState,
  ProjectBoardBounds,
  ProjectBoardSceneComponent,
  ProjectBoardScenePin,
  ProjectBoardSceneTrack,
  ProjectBoardSceneVia,
  ProjectPlacement,
  ProjectPlacementGeometry,
  ProjectVisualDocument,
} from "../../api/types";
import { Text, useCopyFormatter, useText } from "../../lib/copy";
import { useObjectUrl } from "../../lib/useObjectUrl";
import { usePanZoom } from "../../lib/usePanZoom";
import { Badge, Button, SegmentedControl } from "../primitives";
import { AdaptiveChoice } from "../AdaptiveChoice";
import { useScenarioUiState } from "../../design-studio/scenarioState";

type PlacementStateByReference = Record<string, AssemblyPlacementState | undefined>;

/** An inspected placement, remembered together with the board and side it was inspected on. */
interface PlacementSelection {
  board: string;
  side: "top" | "bottom";
  reference: string;
}

/**
 * A pin or via selection, remembered together with an `owner` string naming everything the
 * selection depends on. Reading it back is a comparison rather than an effect: when the owner
 * changes, the stored key stops matching and the selection is simply gone.
 */
interface ScopedSelection {
  owner: string;
  key: string;
}

/** One pin on the selected net, and the component it belongs to. */
interface NetPeer {
  reference: string;
  pin: ProjectBoardScenePin;
}

export function ProjectPlacementStage({
  projectId,
  geometry,
  selectedReferences,
  activeReference = "",
  states = {},
  onSelectReference,
  onBoardChange,
  onSideChange,
  onRetry,
  unavailable = false,
  className = "",
}: {
  projectId: string;
  geometry: ProjectPlacementGeometry | undefined;
  selectedReferences: string[];
  activeReference?: string;
  states?: PlacementStateByReference;
  onSelectReference?: (reference: string, board: string) => void;
  onBoardChange?: (board: string) => void;
  onSideChange?: (side: "top" | "bottom") => void;
  onRetry?: () => void;
  unavailable?: boolean;
  className?: string;
}) {
  const fixturePreview = useScenarioUiState().projects !== undefined;
  const mapLabel = useText("projects.placement-map.aria", "PCB view");
  // The stage's accessible name states the gestures, which nothing visible does.
  const stageName = useCopyFormatter(
    "projects.placement-stage.aria",
    "{subject}. Drag to pan, scroll or use plus and minus to zoom, and press 0 to fit.",
  );
  // The board the reader PICKED, which is not necessarily a board this project still reports. The
  // board actually shown is derived below, so a document list that changes under the picker cannot
  // leave the stage pointing at a board that is no longer there.
  const [boardChoice, setBoardChoice] = useState("");
  const [side, setSide] = useState<"top" | "bottom">("top");
  const [expanded, setExpanded] = useState(false);
  // Each of the three selections below is stored WITH the thing it belongs to, and read back only
  // while that thing is still on screen. They used to be bare strings kept in step by a chain of
  // effects - one cleared the reference when the board changed, one cleared the pin when the
  // reference changed, one cleared the via when the pin changed - so one click walked the screen
  // through several renders and showed the PREVIOUS board's selection in the first of them.
  // Deriving asks the same questions in the render that already knows the answers.
  const [inspected, setInspected] = useState<PlacementSelection | null>(null);
  const [pinChoice, setPinChoice] = useState<ScopedSelection | null>(null);
  const [viaChoice, setViaChoice] = useState<ScopedSelection | null>(null);
  const { view, frameRef, handlers, reset, zoomIn, zoomOut } = usePanZoom();
  const visuals = useProjectVisuals(projectId);
  const refreshVisuals = useRefreshProjectVisuals(projectId);
  const renderedBoards = useMemo(() => {
    // One pass, same order, the same entries the filter-then-map chain produced.
    const paths: string[] = [];
    for (const document of visuals.data?.documents ?? []) {
      if (document.kind === "pcb" && document.status === "ready") paths.push(document.path);
    }
    return paths;
  }, [visuals.data?.documents]);
  const boards = geometry?.boards.length ? geometry.boards : renderedBoards;
  // Derived, not corrected in an effect: the render that first sees a new board list already shows
  // a board that exists in it, and the reader's own pick is kept while it is still offered.
  const board = boards.includes(boardChoice) ? boardChoice : (boards[0] ?? "");
  const selected = useMemo(
    () => new Set(selectedReferences.map((reference) => reference.toLocaleUpperCase())),
    [selectedReferences],
  );
  // An inspected placement survives only while it is still selected AND still on the board and side
  // it was inspected on.
  const inspectedReference =
    inspected &&
    inspected.board === board &&
    inspected.side === side &&
    selected.has(inspected.reference.toLocaleUpperCase())
      ? inspected.reference
      : "";

  useEffect(() => {
    // The pan/zoom frame is an external thing to synchronise, so it stays an effect - and it is the
    // ONLY thing this effect does now. Reset is intentionally tied to the board identity, not every
    // render. usePanZoom keeps its imperative functions lightweight, and including their fresh
    // identity here would refit after every pan.
    reset();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [board, side]);

  const effectiveReference = activeReference || inspectedReference;
  // A pin belongs to one reference, on one side, of one board; a via additionally belongs to the pin
  // whose net it sits on. Storing that owner alongside the key is what makes these reads
  // self-clearing: when the owner changes the stored selection simply stops matching.
  const pinOwner = board + "|" + side + "|" + effectiveReference;
  const selectedPinKey = pinChoice?.owner === pinOwner ? pinChoice.key : "";
  const viaOwner = pinOwner + "|" + selectedPinKey;
  const selectedViaKey = viaChoice?.owner === viaOwner ? viaChoice.key : "";

  useEffect(() => {
    if (!expanded) return;
    function close(event: KeyboardEvent) {
      if (event.key === "Escape") setExpanded(false);
    }
    window.addEventListener("keydown", close);
    return () => window.removeEventListener("keydown", close);
  }, [expanded]);

  const scene = usePlacementScene({
    documents: visuals.data?.documents,
    geometry,
    board,
    side,
    reference: effectiveReference,
    selectedPinKey,
    selectedViaKey,
  });
  const boardArtifact = scene.boardDocument?.artifacts.find(
    (candidate) => candidate.kind === "pcb" && candidate.view === side,
  );
  const artifact = useProjectVisualArtifact(projectId, boardArtifact?.id ?? "");
  const nativeBoardUrl = useObjectUrl(artifact.data);
  const nativeRenderPending =
    visuals.isLoading || (!!boardArtifact && artifact.isLoading);
  const zoomPercent = Math.round(view.scale * 100);

  return (
    <section
      data-dev-id="projects.placement-stage"
      className={`flex min-h-0 min-w-0 flex-col overflow-hidden rounded-card border border-line bg-surface ${
        expanded ? "fixed inset-3 z-[80] !h-auto shadow-pop" : ""
      } ${className}`}
      aria-label={mapLabel}
    >
      <PlacementStageToolbar
        board={board}
        boards={boards}
        side={side}
        placements={scene.boardPlacements}
        nativeBoardUrl={nativeBoardUrl}
        nativeRenderPending={nativeRenderPending}
        renderNote={refreshVisuals.error?.message || visuals.data?.detail || visuals.error?.message}
        fixturePreview={fixturePreview}
        rerendering={refreshVisuals.isPending}
        onRerender={() => refreshVisuals.mutate()}
        onBoard={(nextBoard) => {
          // The event that owns the change clears what the change invalidates. The owner
          // checks above are the safety net for changes that arrive as PROPS; this is the
          // one case a person performs, and clearing it here means picking the old board
          // again does not silently bring the old pad selection back with it.
          setBoardChoice(nextBoard);
          setInspected(null);
          setPinChoice(null);
          setViaChoice(null);
          onBoardChange?.(nextBoard);
        }}
        onSide={(nextSide) => {
          setSide(nextSide);
          setInspected(null);
          setPinChoice(null);
          setViaChoice(null);
          onSideChange?.(nextSide);
        }}
        zoomPercent={zoomPercent}
        onZoomIn={zoomIn}
        onZoomOut={zoomOut}
        onFit={reset}
        expanded={expanded}
        onExpanded={() => setExpanded((current) => !current)}
      />

      <div
        ref={frameRef}
        role="application"
        tabIndex={0}
        aria-label={stageName({ subject: mapLabel })}
        onDoubleClick={reset}
        onKeyDown={(event) => {
          if (event.key === "+" || event.key === "=") {
            event.preventDefault();
            zoomIn();
          } else if (event.key === "-" || event.key === "_") {
            event.preventDefault();
            zoomOut();
          } else if (event.key === "0" || event.key.toLocaleLowerCase() === "f") {
            event.preventDefault();
            reset();
          } else if (event.key === "Escape" && selectedViaKey) {
            event.preventDefault();
            event.stopPropagation();
            setViaChoice(null);
          } else if (event.key === "Escape" && selectedPinKey) {
            event.preventDefault();
            event.stopPropagation();
            setPinChoice(null);
          } else if (event.key === "Escape" && expanded) {
            event.preventDefault();
            event.stopPropagation();
            setExpanded(false);
          }
        }}
        className="relative min-h-[260px] flex-1 cursor-grab overflow-hidden bg-field outline-none active:cursor-grabbing focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-focus"
        {...handlers}
      >
        <div
          aria-hidden
          className="pointer-events-none absolute inset-y-0 left-1/2 w-px bg-line opacity-35"
        />
        <div
          aria-hidden
          className="pointer-events-none absolute inset-x-0 top-1/2 h-px bg-line opacity-35"
        />
        <PlacementStageScene
          geometry={geometry}
          unavailable={unavailable}
          onRetry={onRetry}
          nativeBoardUrl={nativeBoardUrl}
          mapLabel={mapLabel}
          view={view}
          side={side}
          scene={scene}
          selected={selected}
          states={states}
          activeReference={effectiveReference}
          selectedPinKey={selectedPinKey}
          selectedViaKey={selectedViaKey}
          onInspect={(reference) => {
            setInspected({ board, side, reference });
            onSelectReference?.(reference, board);
          }}
          onPickPin={(key) => setPinChoice({ owner: pinOwner, key })}
          onPickVia={(key) => setViaChoice({ owner: viaOwner, key })}
        />
      </div>

      <PlacementStageLegend
        scene={scene}
        side={side}
        activeReference={effectiveReference}
        selectedReferences={selectedReferences}
        selectable={!!onSelectReference}
        states={states}
        zoomPercent={zoomPercent}
      />
    </section>
  );
}

/**
 * Everything the stage DRAWS, derived from the visuals, the geometry, and what is selected.
 *
 * One hook rather than eighteen loose memos in the component body, because every value here
 * answers the same question - "given this board, this side and this selection, what is on screen"
 * - and both the diagram and the status line below it read the answer. Splitting them across the
 * two would have meant walking the same net twice and letting the picture and its caption
 * disagree about what is on it.
 *
 * Deriving rather than correcting in an effect is the point, and it is why the selections arrive
 * as plain keys: the render that first sees a new board already shows that board's selection,
 * where a chain of clearing effects walked the screen through several renders and showed the
 * PREVIOUS board's selection in the first of them.
 */
export interface PlacementScene {
  boardDocument: ProjectVisualDocument | undefined;
  boardPlacements: ProjectPlacement[];
  visible: ProjectPlacement[];
  sceneComponents: Map<string, ProjectBoardSceneComponent>;
  activePins: ProjectBoardScenePin[];
  selectedPin: ProjectBoardScenePin | null;
  visibleNetPins: NetPeer[];
  visibleNetVias: ProjectBoardSceneVia[];
  visibleNetTracks: ProjectBoardSceneTrack[];
  selectedVia: ProjectBoardSceneVia | null;
  transform: ReturnType<typeof placementTransform>;
  fittedViewBox: string;
}

function usePlacementScene({
  documents,
  geometry,
  board,
  side,
  reference,
  selectedPinKey,
  selectedViaKey,
}: {
  documents: ProjectVisualDocument[] | undefined;
  geometry: ProjectPlacementGeometry | undefined;
  board: string;
  side: "top" | "bottom";
  /** The placement whose pads are being inspected, or "" when none is. */
  reference: string;
  selectedPinKey: string;
  selectedViaKey: string;
}): PlacementScene {
  const boardDocument = useMemo(
    () => findBoardDocument(documents ?? [], board),
    [board, documents],
  );
  const boardScene = boardDocument?.scene;
  const scenePlacements = useMemo(
    () =>
      (boardScene?.components ?? []).map((component) => ({
        reference: component.reference,
        board,
        x_mm: component.x_mm,
        y_mm: component.y_mm,
        rotation_deg: component.rotation_deg,
        side: component.side,
        footprint: component.package,
      })),
    [board, boardScene?.components],
  );
  const boardPlacements = useMemo(() => {
    const reported = (geometry?.placements ?? []).filter(
      (placement) => placement.board === board,
    );
    return reported.length ? reported : scenePlacements;
  }, [board, geometry?.placements, scenePlacements]);
  const visible = useMemo(
    () => boardPlacements.filter((placement) => placement.side === side),
    [boardPlacements, side],
  );
  const sceneComponents = useMemo(
    () =>
      new Map(
        (boardScene?.components ?? []).map((component) => [
          component.reference.toLocaleUpperCase(),
          component,
        ]),
      ),
    [boardScene?.components],
  );
  const activeComponent = sceneComponents.get(reference.toLocaleUpperCase());
  const activePins = useMemo(
    () => (activeComponent?.pins ?? []).filter((pin) => pin.side === side),
    [activeComponent?.pins, side],
  );
  const selectedPin =
    activePins.find((pin) => pinKey(pin) === selectedPinKey) ?? null;
  const visibleNetPins = useMemo(() => {
    const net = selectedPin?.net.trim().toLocaleUpperCase();
    if (!net) return [];
    // One pass per component, in component order then pin order - the same sequence the
    // filter-then-map chain produced, without an intermediate array per component.
    const peers: NetPeer[] = [];
    for (const component of boardScene?.components ?? []) {
      for (const pin of component.pins ?? []) {
        if (pin.side === side && pin.net.trim().toLocaleUpperCase() === net) {
          peers.push({ reference: component.reference, pin });
        }
      }
    }
    return peers;
  }, [boardScene?.components, selectedPin?.net, side]);
  const visibleNetVias = useMemo(() => {
    const net = selectedPin?.net.trim().toLocaleUpperCase();
    if (!net) return [];
    return (boardScene?.vias ?? []).filter(
      (via) =>
        via.net.trim().toLocaleUpperCase() === net && via.sides.includes(side),
    );
  }, [boardScene?.vias, selectedPin?.net, side]);
  const visibleNetTracks = useMemo(() => {
    const net = selectedPin?.net.trim().toLocaleUpperCase();
    if (!net) return [];
    return (boardScene?.tracks ?? []).filter(
      (track) =>
        track.net.trim().toLocaleUpperCase() === net && track.side === side,
    );
  }, [boardScene?.tracks, selectedPin?.net, side]);
  const selectedVia =
    visibleNetVias.find((via) => viaKey(via) === selectedViaKey) ?? null;
  const transform = useMemo(
    () => placementTransform(boardPlacements, boardScene?.bounds),
    [boardPlacements, boardScene?.bounds],
  );
  const fittedViewBox = stageViewBox(transform.frame);
  return {
    boardDocument,
    boardPlacements,
    visible,
    sceneComponents,
    activePins,
    selectedPin,
    visibleNetPins,
    visibleNetVias,
    visibleNetTracks,
    selectedVia,
    transform,
    fittedViewBox,
  };
}

/**
 * The stage's own title strip: which board and which side are being read, and the four things that
 * change how they are being looked at.
 *
 * Everything on this bar is about the VIEW rather than about the design, which is the line it is
 * split on. The selection-clearing that a board or side change forces is handed IN rather than
 * done here, because the stage owns what a change invalidates and this bar only reports that one
 * happened.
 */
function PlacementStageToolbar({
  board,
  boards,
  side,
  placements,
  nativeBoardUrl,
  nativeRenderPending,
  renderNote,
  fixturePreview,
  rerendering,
  onRerender,
  onBoard,
  onSide,
  zoomPercent,
  onZoomIn,
  onZoomOut,
  onFit,
  expanded,
  onExpanded,
}: {
  board: string;
  boards: string[];
  side: "top" | "bottom";
  /** Every placement on this board, BOTH sides: the side control counts them. */
  placements: ProjectPlacement[];
  nativeBoardUrl: string | null;
  nativeRenderPending: boolean;
  renderNote: string | undefined;
  fixturePreview: boolean;
  rerendering: boolean;
  onRerender: () => void;
  onBoard: (board: string) => void;
  onSide: (side: "top" | "bottom") => void;
  zoomPercent: number;
  onZoomIn: () => void;
  onZoomOut: () => void;
  onFit: () => void;
  expanded: boolean;
  onExpanded: () => void;
}) {
  const boardLabel = useText("projects.placement-map.board", "Board");
  const sideLabel = useText("projects.placement-map.side", "Board side");
  const topLabel = useText("projects.placement-map.top", "Top");
  const bottomLabel = useText("projects.placement-map.bottom", "Bottom");
  const renderingBoardLabel = useText(
    "projects.placement-map.rendering-board",
    "Rendering PCB",
  );
  const geometryMapLabel = useText(
    "projects.placement-map.geometry-map",
    "Placement View",
  );
  const renderBoardLabel = useText(
    "projects.placement-map.render-board",
    "Render PCB",
  );
  const zoomInLabel = useText("projects.placement-map.zoom-in", "Zoom In");
  const zoomOutLabel = useText("projects.placement-map.zoom-out", "Zoom Out");
  const fitLabel = useText("projects.placement-map.fit", "Fit Board");
  const expandLabel = useText("projects.placement-map.expand", "Expand Board");
  const collapseLabel = useText("projects.placement-map.collapse", "Close Board View");
  const sideOptions = [
    {
      id: "top" as const,
      label: `${topLabel} · ${
        placements.filter((placement) => placement.side === "top").length
      }`,
    },
    {
      id: "bottom" as const,
      label: `${bottomLabel} · ${
        placements.filter((placement) => placement.side === "bottom").length
      }`,
    },
  ];
  return (
    <header className="flex h-[40px] flex-none items-center gap-2 border-b border-line bg-band px-3">
      <div className="flex min-w-0 items-center gap-1.5">
        <h2 className="flex-none text-xs font-semibold text-t1">
          <Text id="projects.placement-map.title">PCB</Text>
        </h2>
        {board ? (
          <span className="max-w-32 truncate font-mono text-2xs text-t3" title={board}>
            {fileName(board)}
          </span>
        ) : null}
      </div>
      <div className="ml-auto flex items-center gap-2">
        {!nativeBoardUrl ? (
          <Badge
            size="sm"
            tone="neutral"
            title={renderNote}
          >
            {nativeRenderPending ? renderingBoardLabel : geometryMapLabel}
          </Badge>
        ) : null}
        {!nativeRenderPending &&
        !nativeBoardUrl ? (
          <Button
            small
            disabled={rerendering}
            aria-describedby={fixturePreview ? "projects-native-render-preview-help" : undefined}
            onClick={onRerender}
          >
            {rerendering ? renderingBoardLabel : renderBoardLabel}
          </Button>
        ) : null}
        {fixturePreview ? (
          <span id="projects-native-render-preview-help" className="sr-only">
            <Text id="projects.preview.native-render-help">
              Fixture Preview blocks native rendering. Return to Real Data to render the PCB.
            </Text>
          </span>
        ) : null}
        {/* The board picker's strip is a DIV, not a label. The control inside carries its own
            accessible name, which wins over a wrapping label's text, so the `<label>` it used to
            be named nothing and existed only to draw the bordered strip. */}
        {boards.length > 1 ? (
          <div className="flex h-8 items-center gap-2 rounded-control border border-line bg-field px-2 text-2xs text-t3">
            <span>{boardLabel}</span>
            <AdaptiveChoice
              devId="projects.board-control"
              label={boardLabel}
              value={board}
              onChange={onBoard}
              className="max-w-[180px] border-0 bg-transparent"
              options={boards.map((name) => ({ value: name, label: name }))}
            />
          </div>
        ) : null}
        <SegmentedControl
          options={sideOptions}
          value={side}
          onChange={onSide}
          size="small"
          aria-label={sideLabel}
        />
        <span aria-hidden className="h-4 w-px bg-line2" />
        <div className="flex items-center rounded-control border border-line bg-field p-0.5">
          <StageToolButton
            label={zoomOutLabel}
            disabled={zoomPercent <= 30}
            onClick={onZoomOut}
          >
            <MinusGlyph />
          </StageToolButton>
          <button
            type="button"
            className="h-6 min-w-[42px] px-1 font-mono text-2xs tabular-nums text-t3 hover:text-t1 focus-visible:outline focus-visible:outline-2 focus-visible:outline-focus"
            aria-label={fitLabel}
            title={fitLabel}
            onClick={onFit}
          >
            {zoomPercent}%
          </button>
          <StageToolButton
            label={zoomInLabel}
            disabled={zoomPercent >= 800}
            onClick={onZoomIn}
          >
            <PlusGlyph />
          </StageToolButton>
        </div>
        <StageToolButton
          label={expanded ? collapseLabel : expandLabel}
          onClick={onExpanded}
          aria-pressed={expanded}
          framed
        >
          {expanded ? <ContractGlyph /> : <ExpandGlyph />}
        </StageToolButton>
      </div>
    </header>
  );
}

/**
 * The diagram itself: the board, the placements on the side being read, and - once a pad is
 * chosen - the net it belongs to, drawn as its tracks, its peer pads and its vias.
 *
 * It renders exactly one of four things and says which honestly: still loading, blocked with the
 * reason the linked editor gave, nothing placed on this side, or the board. The blocked reason is
 * decided here because this is the only surface that shows it, and the board itself is
 * `PlacementBoardDiagram` below - the difference between "what state is the stage in" and "what is
 * drawn on it" is the line these two are split on.
 */
function PlacementStageScene({
  geometry,
  unavailable,
  onRetry,
  nativeBoardUrl,
  mapLabel,
  view,
  side,
  scene,
  selected,
  states,
  activeReference,
  selectedPinKey,
  selectedViaKey,
  onInspect,
  onPickPin,
  onPickVia,
}: {
  geometry: ProjectPlacementGeometry | undefined;
  unavailable: boolean;
  onRetry?: () => void;
  nativeBoardUrl: string | null;
  /** The stage's accessible name, shared with the frame around it so both say one thing. */
  mapLabel: string;
  view: ReturnType<typeof usePanZoom>["view"];
  side: "top" | "bottom";
  scene: PlacementScene;
  /** Upper-cased references the workbench has highlighted. */
  selected: Set<string>;
  states: PlacementStateByReference;
  activeReference: string;
  selectedPinKey: string;
  selectedViaKey: string;
  onInspect: (reference: string) => void;
  onPickPin: (key: string) => void;
  onPickVia: (key: string) => void;
}) {
  const unavailableLabel = useText(
    "projects.placement-map.unavailable",
    "Placement data is not available for this project.",
  );
  const licenseLabel = useText(
    "projects.placement-map.license-required",
    "A valid editor license is required to read placement data.",
  );
  const busyLabel = useText(
    "projects.placement-map.editor-busy",
    "The linked editor is in use. Close the project there, then rerun.",
  );
  const installLabel = useText(
    "projects.placement-map.editor-required",
    "Install the linked editor to read placement data.",
  );
  const retryLabel = useText("projects.placement-map.retry", "Rerun");
  const blockedDetail = (geometry?.detail ?? "").toLocaleLowerCase();
  const blockedMessage = blockedDetail.includes("license")
    ? licenseLabel
    : blockedDetail.includes("busy") || blockedDetail.includes("already open")
      ? busyLabel
      : blockedDetail.includes("not installed") || blockedDetail.includes("not found")
        ? installLabel
        : unavailableLabel;
  return (
    <>
      {!geometry && !unavailable && !nativeBoardUrl ? (
        <StageMessage>
          <Text id="projects.placement-map.loading">Loading placement map...</Text>
        </StageMessage>
      ) : (unavailable || geometry?.status !== "ready") && !nativeBoardUrl ? (
        <StageMessage tone="warn" devId="projects.placement-blocked">
          <div>
            <p>{blockedMessage}</p>
            {onRetry ? (
              <Button small className="mt-3" onClick={onRetry}>
                {retryLabel}
              </Button>
            ) : null}
          </div>
        </StageMessage>
      ) : !scene.visible.length && !nativeBoardUrl ? (
        <StageMessage>
          <Text id="projects.placement-map.empty-side">
            No placements are reported on this side.
          </Text>
        </StageMessage>
      ) : (
        <PlacementBoardDiagram
          mapLabel={mapLabel}
          view={view}
          side={side}
          scene={scene}
          selected={selected}
          states={states}
          activeReference={activeReference}
          selectedPinKey={selectedPinKey}
          selectedViaKey={selectedViaKey}
          nativeBoardUrl={nativeBoardUrl}
          onInspect={onInspect}
          onPickPin={onPickPin}
          onPickVia={onPickVia}
        />
      )}
    </>
  );
}

/**
 * The board itself, drawn: the placements on the side being read, and - once a pad is chosen - the
 * net it belongs to, as its tracks, its peer pads and its vias.
 *
 * `role="group"`, NOT `role="img"`. An `img` role makes its whole subtree presentational, which
 * quietly deleted every placement, pin and via control inside this diagram from the accessibility
 * tree - each has role="button", an accessible name and a key handler, and no screen reader could
 * reach any of them. The stage is an interactive diagram, so it is a named group whose children
 * keep their own semantics.
 *
 * MIRRORING is the one rule every layer below obeys and none of them may forget: on the bottom
 * side an x is reflected across the board frame and a rotation is negated, because the reader is
 * looking through the board rather than at it. Each layer applies it to its own geometry, which is
 * why the layers are components rather than one 300-line map: a layer that forgot lands its marks
 * in the mirror image of where they belong, and a layer with one job is where that is visible.
 */
function PlacementBoardDiagram({
  mapLabel,
  view,
  side,
  scene,
  selected,
  states,
  activeReference,
  selectedPinKey,
  selectedViaKey,
  nativeBoardUrl,
  onInspect,
  onPickPin,
  onPickVia,
}: {
  mapLabel: string;
  view: ReturnType<typeof usePanZoom>["view"];
  side: "top" | "bottom";
  scene: PlacementScene;
  selected: Set<string>;
  states: PlacementStateByReference;
  activeReference: string;
  selectedPinKey: string;
  selectedViaKey: string;
  nativeBoardUrl: string | null;
  onInspect: (reference: string) => void;
  onPickPin: (key: string) => void;
  onPickVia: (key: string) => void;
}) {
  const footprintUnsetLabel = useText(
    "projects.placement-map.footprint-unset",
    "footprint not set",
  );
  const pinLabel = useText("projects.placement-map.pin", "Pin");
  const viaLabel = useText("projects.placement-map.via", "Via");
  const drillLabel = useText("projects.placement-map.drill", "mm drill");
  const noNetLabel = useText("projects.placement-map.no-net", "No net");
  const {
    visible,
    sceneComponents,
    activePins,
    visibleNetPins,
    visibleNetVias,
    visibleNetTracks,
    transform,
    fittedViewBox,
  } = scene;
  return (
    <svg
      // role="group", NOT role="img". An `img` role makes its whole subtree presentational,
      // which quietly deleted every placement, pin and via control inside this diagram from
      // the accessibility tree - each has role="button", an accessible name and a key
      // handler, and no screen reader could reach any of them. The stage is an interactive
      // diagram, so it is a named group whose children keep their own semantics.
      role="group"
      aria-label={mapLabel}
      viewBox={fittedViewBox}
      className="relative h-full min-h-[260px] w-full touch-none select-none"
      preserveAspectRatio="xMidYMid meet"
      style={{
        transform: `translate(${view.x}px, ${view.y}px) scale(${view.scale})`,
        transformOrigin: "center",
      }}
    >
      {nativeBoardUrl ? (
        <image
          data-dev-id="projects.native-board-render"
          href={nativeBoardUrl}
          x={transform.frame.x}
          y={transform.frame.y}
          width={transform.frame.width}
          height={transform.frame.height}
          preserveAspectRatio="xMidYMid meet"
          aria-hidden
          className="projects-native-board-render"
        />
      ) : (
        <>
          <rect
            x={transform.frame.x}
            y={transform.frame.y}
            width={transform.frame.width}
            height={transform.frame.height}
            rx="18"
            className="fill-surface stroke-line2"
            strokeWidth="2"
          />
          <g className="opacity-50">
            <line
              x1={transform.frame.x}
              y1={transform.frame.y + transform.frame.height / 2}
              x2={transform.frame.x + transform.frame.width}
              y2={transform.frame.y + transform.frame.height / 2}
              className="stroke-line"
              strokeDasharray="7 9"
            />
            <line
              x1={transform.frame.x + transform.frame.width / 2}
              y1={transform.frame.y}
              x2={transform.frame.x + transform.frame.width / 2}
              y2={transform.frame.y + transform.frame.height}
              className="stroke-line"
              strokeDasharray="7 9"
            />
          </g>
        </>
      )}
      <NetTracks tracks={visibleNetTracks} side={side} transform={transform} />
      <PlacementMarkers
        placements={visible}
        side={side}
        transform={transform}
        selected={selected}
        states={states}
        activeReference={activeReference}
        components={sceneComponents}
        nativeBoard={!!nativeBoardUrl}
        footprintUnsetLabel={footprintUnsetLabel}
        onInspect={onInspect}
      />
      <NetPeerPads peers={visibleNetPins} side={side} transform={transform} />
      <NetVias
        vias={visibleNetVias}
        side={side}
        transform={transform}
        selectedViaKey={selectedViaKey}
        viaLabel={viaLabel}
        noNetLabel={noNetLabel}
        drillLabel={drillLabel}
        onPickVia={onPickVia}
      />
      <ActivePins
        pins={activePins}
        side={side}
        transform={transform}
        selectedPinKey={selectedPinKey}
        reference={activeReference}
        pinLabel={pinLabel}
        noNetLabel={noNetLabel}
        onPickPin={onPickPin}
      />
    </svg>
  );
}

/** The net's copper, under everything else so a track never covers a pad it runs to. */
function NetTracks({
  tracks,
  side,
  transform,
}: {
  tracks: ProjectBoardSceneTrack[];
  side: "top" | "bottom";
  transform: ReturnType<typeof placementTransform>;
}) {
  return (
    <>
      {tracks.map((track, index) => {
        const start = transform.point({
          x_mm: track.start_x_mm,
          y_mm: track.start_y_mm,
        });
        const end = transform.point({
          x_mm: track.end_x_mm,
          y_mm: track.end_y_mm,
        });
        const startX =
          side === "bottom"
            ? transform.frame.x + transform.frame.width - (start.x - transform.frame.x)
            : start.x;
        const endX =
          side === "bottom"
            ? transform.frame.x + transform.frame.width - (end.x - transform.frame.x)
            : end.x;
        return (
          <line
            key={`${track.layer}:${track.start_x_mm}:${track.start_y_mm}:${track.end_x_mm}:${track.end_y_mm}:${index}`}
            data-net-track={track.net}
            aria-hidden="true"
            x1={startX}
            y1={start.y}
            x2={endX}
            y2={end.y}
            className="pointer-events-none stroke-acc/75"
            strokeWidth={Math.max(1.5, track.width_mm * transform.scale)}
            strokeLinecap="round"
          />
        );
      })}
    </>
  );
}

/** One control per placement on this side, named for its reference and its footprint. */
function PlacementMarkers({
  placements,
  side,
  transform,
  selected,
  states,
  activeReference,
  components,
  nativeBoard,
  footprintUnsetLabel,
  onInspect,
}: {
  placements: ProjectPlacement[];
  side: "top" | "bottom";
  transform: ReturnType<typeof placementTransform>;
  selected: Set<string>;
  states: PlacementStateByReference;
  activeReference: string;
  components: Map<string, ProjectBoardSceneComponent>;
  /** A real board render underneath changes how a marker has to be drawn over it. */
  nativeBoard: boolean;
  footprintUnsetLabel: string;
  onInspect: (reference: string) => void;
}) {
  return (
    <>
      {placements.map((placement) => {
        const point = transform.point(placement);
        const x =
          side === "bottom"
            ? transform.frame.x + transform.frame.width - (point.x - transform.frame.x)
            : point.x;
        const isSelected = selected.has(placement.reference.toLocaleUpperCase());
        const isActive = placement.reference === activeReference;
        const state = states[placement.reference];
        const marker = markerSize(
          components.get(placement.reference.toLocaleUpperCase()),
          transform,
          isSelected,
          isActive,
        );
        return (
          <g
            key={`${placement.board}:${placement.reference}`}
            transform={`translate(${x} ${point.y})`}
          >
            {isActive ? (
              <SelectionLocator
                reference={placement.reference}
                width={marker.width}
                height={marker.height}
              />
            ) : null}
            <g
              role="button"
              tabIndex={0}
              aria-label={`${placement.reference}, ${
                placement.footprint || footprintUnsetLabel
              }`}
              data-reference={placement.reference}
              data-hit-width={marker.width.toFixed(2)}
              data-hit-height={marker.height.toFixed(2)}
              onClick={() => onInspect(placement.reference)}
              onKeyDown={(event) => {
                if (event.key === "Enter" || event.key === " ") {
                  event.preventDefault();
                  onInspect(placement.reference);
                }
              }}
              className="group cursor-pointer focus:outline-none"
            >
              <title>
                {placement.reference} · {placement.footprint || footprintUnsetLabel}
              </title>
              <g
                transform={`rotate(${
                  side === "bottom"
                    ? -placement.rotation_deg
                    : placement.rotation_deg
                })`}
              >
                <rect
                  x={-marker.hitWidth / 2}
                  y={-marker.hitHeight / 2}
                  width={marker.hitWidth}
                  height={marker.hitHeight}
                  rx={marker.radius}
                  className="fill-transparent stroke-transparent"
                />
                <rect
                  x={-marker.width / 2}
                  y={-marker.height / 2}
                  width={marker.width}
                  height={marker.height}
                  rx={marker.radius}
                  className={`${markerClass(
                    state,
                    isSelected,
                    isActive,
                    nativeBoard,
                  )} group-focus-visible:stroke-focus`}
                  strokeWidth={isActive ? 4 : 2}
                />
                <circle
                  cx={-marker.width / 2 + marker.padOffset}
                  cy="0"
                  r={marker.padRadius}
                  className="fill-surface"
                />
              </g>
            </g>
            {(isSelected || isActive) && (
              <text
                x="0"
                y={isActive ? 35 : 30}
                textAnchor="middle"
                className="fill-t1 font-mono text-[17px] font-semibold"
              >
                {placement.reference}
              </text>
            )}
          </g>
        );
      })}
    </>
  );
}

/** The other pads on the chosen net, marked but never clickable: the pad already chosen is. */
function NetPeerPads({
  peers,
  side,
  transform,
}: {
  peers: NetPeer[];
  side: "top" | "bottom";
  transform: ReturnType<typeof placementTransform>;
}) {
  return (
    <>
      {peers.map(({ reference, pin }) => {
        const point = transform.point(pin);
        const x =
          side === "bottom"
            ? transform.frame.x + transform.frame.width - (point.x - transform.frame.x)
            : point.x;
        const marker = pinMarker(pin, transform.scale);
        return (
          <rect
            key={`${reference}:${pinKey(pin)}`}
            data-net-peer={`${reference}:${pin.number}`}
            aria-hidden="true"
            x={-marker.width / 2}
            y={-marker.height / 2}
            width={marker.width}
            height={marker.height}
            rx={marker.radius}
            transform={`translate(${x} ${point.y}) rotate(${
              side === "bottom" ? -pin.rotation_deg : pin.rotation_deg
            })`}
            className="pointer-events-none fill-acc/10 stroke-acc/55"
            strokeWidth="1.5"
            strokeDasharray="3 2"
          />
        );
      })}
    </>
  );
}

/** The vias carrying the chosen net through the board, each one selectable in its own right. */
function NetVias({
  vias,
  side,
  transform,
  selectedViaKey,
  viaLabel,
  noNetLabel,
  drillLabel,
  onPickVia,
}: {
  vias: ProjectBoardSceneVia[];
  side: "top" | "bottom";
  transform: ReturnType<typeof placementTransform>;
  selectedViaKey: string;
  viaLabel: string;
  noNetLabel: string;
  drillLabel: string;
  onPickVia: (key: string) => void;
}) {
  return (
    <>
      {vias.map((via) => {
        const point = transform.point(via);
        const x =
          side === "bottom"
            ? transform.frame.x + transform.frame.width - (point.x - transform.frame.x)
            : point.x;
        const radius = Math.max(3, (via.diameter_mm * transform.scale) / 2);
        const key = viaKey(via);
        const active = key === selectedViaKey;
        const name = via.name || viaLabel;
        const accessibleName = via.name
          ? `${viaLabel} ${via.name}`
          : viaLabel;
        return (
          <g key={key} transform={`translate(${x} ${point.y})`}>
            <g
              role="button"
              tabIndex={0}
              aria-label={`${accessibleName}, ${
                via.net || noNetLabel
              }, ${via.diameter_mm.toFixed(2)} ${drillLabel}`}
              data-net-via={name}
              onClick={(event) => {
                event.stopPropagation();
                onPickVia(key);
              }}
              onKeyDown={(event) => {
                if (event.key === "Enter" || event.key === " ") {
                  event.preventDefault();
                  event.stopPropagation();
                  onPickVia(key);
                }
              }}
              className="group cursor-pointer focus:outline-none"
            >
              <title>{`${name} · ${
                via.net || noNetLabel
              } · ${via.diameter_mm.toFixed(2)} ${drillLabel}`}</title>
              <circle
                r={Math.max(radius, 8)}
                className="fill-transparent stroke-transparent"
              />
              <circle
                r={radius}
                className={`${
                  active
                    ? "fill-acc/30 stroke-acc"
                    : "fill-surface/20 stroke-acc/70"
                } group-hover:fill-acc/20 group-hover:stroke-acc group-focus-visible:stroke-t1`}
                strokeWidth={active ? 2.5 : 1.5}
              />
            </g>
          </g>
        );
      })}
    </>
  );
}

/** The inspected placement's own pads - the only pads a person can pick to trace a net from. */
function ActivePins({
  pins,
  side,
  transform,
  selectedPinKey,
  reference,
  pinLabel,
  noNetLabel,
  onPickPin,
}: {
  pins: ProjectBoardScenePin[];
  side: "top" | "bottom";
  transform: ReturnType<typeof placementTransform>;
  selectedPinKey: string;
  /** Named in every pad's accessible name, so a pad says which footprint it is on. */
  reference: string;
  pinLabel: string;
  noNetLabel: string;
  onPickPin: (key: string) => void;
}) {
  return (
    <>
      {pins.map((pin) => {
        const point = transform.point(pin);
        const x =
          side === "bottom"
            ? transform.frame.x + transform.frame.width - (point.x - transform.frame.x)
            : point.x;
        const marker = pinMarker(pin, transform.scale);
        const key = pinKey(pin);
        const active = key === selectedPinKey;
        const net = pin.net || noNetLabel;
        return (
          <g
            key={key}
            transform={`translate(${x} ${point.y}) rotate(${
              side === "bottom" ? -pin.rotation_deg : pin.rotation_deg
            })`}
          >
            <g
              role="button"
              tabIndex={0}
              aria-label={`${reference}, ${pinLabel} ${pin.number}, ${net}`}
              onClick={(event) => {
                event.stopPropagation();
                onPickPin(key);
              }}
              onKeyDown={(event) => {
                if (event.key === "Enter" || event.key === " ") {
                  event.preventDefault();
                  event.stopPropagation();
                  onPickPin(key);
                }
              }}
              className="group cursor-pointer focus:outline-none"
            >
              <title>{`${pinLabel} ${pin.number} · ${net}`}</title>
              <rect
                x={-marker.hitWidth / 2}
                y={-marker.hitHeight / 2}
                width={marker.hitWidth}
                height={marker.hitHeight}
                rx={marker.radius}
                className="fill-transparent stroke-transparent"
              />
              <rect
                x={-marker.width / 2}
                y={-marker.height / 2}
                width={marker.width}
                height={marker.height}
                rx={marker.radius}
                className={`${
                  active
                    ? "fill-acc/25 stroke-acc"
                    : "fill-transparent stroke-acc/80"
                } group-hover:fill-acc/15 group-hover:stroke-acc group-focus-visible:stroke-t1`}
                strokeWidth={active ? 2.5 : 1.5}
              />
            </g>
          </g>
        );
      })}
    </>
  );
}


/**
 * The stage's status line: what is selected, said in the terms of the thing that is selected.
 *
 * Four readings in one place, narrowing as the selection narrows - a via, a pad and the whole net
 * it sits on, a placement with nothing chosen on it yet, or a set of highlighted references - and
 * each one ends by naming the next move rather than stopping at a noun.
 */
function PlacementStageLegend({
  scene,
  side,
  activeReference,
  selectedReferences,
  selectable,
  states,
  zoomPercent,
}: {
  scene: PlacementScene;
  side: "top" | "bottom";
  activeReference: string;
  selectedReferences: string[];
  /** Whether picking a placement does anything here; a read-only stage says so instead. */
  selectable: boolean;
  states: PlacementStateByReference;
  zoomPercent: number;
}) {
  const topLabel = useText("projects.placement-map.top", "Top");
  const bottomLabel = useText("projects.placement-map.bottom", "Bottom");
  const placementLabel = useText("projects.placement-map.placement", "placement");
  const placementsLabel = useText("projects.placement-map.placements", "placements");
  const pinLabel = useText("projects.placement-map.pin", "Pin");
  const padLabel = useText("projects.placement-map.pad", "pad");
  const padsLabel = useText("projects.placement-map.pads", "pads");
  const viaLabel = useText("projects.placement-map.via", "Via");
  const viaCountLabel = useText("projects.placement-map.via-count", "via");
  const viasLabel = useText("projects.placement-map.vias", "vias");
  const trackLabel = useText("projects.placement-map.track", "track");
  const tracksLabel = useText("projects.placement-map.tracks", "tracks");
  const drillLabel = useText("projects.placement-map.drill", "mm drill");
  const noNetLabel = useText("projects.placement-map.no-net", "No net");
  const inspectFootprintLabel = useText(
    "projects.placement-map.inspect-footprint",
    "Select a footprint to inspect it",
  );
  const inspectHighlightedLabel = useText(
    "projects.placement-map.inspect-highlighted",
    "select one to inspect",
  );
  const inspectNetLabel = useText(
    "projects.placement-map.inspect-net",
    "select a pad to trace its net",
  );
  const { selectedVia, selectedPin, visibleNetPins, visibleNetVias, visibleNetTracks, visible } =
    scene;
  return (
    <footer className="flex min-h-9 flex-none items-center gap-4 border-t border-line px-3">
      <div className="min-w-0 text-xs text-t2" aria-live="polite">
        {selectedVia ? (
          <Legend dotClass="bg-acc" copyId="projects.placement-map.selected-via">
            {`${selectedVia.name || viaLabel} · ${
              selectedVia.net || noNetLabel
            } · ${selectedVia.diameter_mm.toFixed(2)} ${drillLabel}`}
          </Legend>
        ) : selectedPin ? (
          <Legend dotClass="bg-acc" copyId="projects.placement-map.selected-pin">
            {`${pinLabel} ${selectedPin.number} · ${
              selectedPin.net || noNetLabel
            }${
              visibleNetPins.length ||
              visibleNetVias.length ||
              visibleNetTracks.length
                ? ` · ${visibleNetPins.length} ${
                    visibleNetPins.length === 1 ? padLabel : padsLabel
                  } · ${visibleNetVias.length} ${
                    visibleNetVias.length === 1 ? viaCountLabel : viasLabel
                  } · ${visibleNetTracks.length} ${
                    visibleNetTracks.length === 1 ? trackLabel : tracksLabel
                  } · ${side === "top" ? topLabel : bottomLabel}`
                : ""
            }`}
          </Legend>
        ) : activeReference ? (
          <Legend dotClass="bg-acc" copyId="projects.placement-map.selected">
            {`${activeReference} · ${inspectNetLabel}`}
          </Legend>
        ) : selectedReferences.length ? (
          <Legend dotClass="bg-acc" copyId="projects.placement-map.highlighted">
            {`${selectedReferences.length} ${
              selectedReferences.length === 1 ? placementLabel : placementsLabel
            } highlighted · ${inspectHighlightedLabel}`}
          </Legend>
        ) : selectable ? (
          <span className="truncate">{inspectFootprintLabel}</span>
        ) : (
          <span>
            <Text id="projects.placement-map.no-selection">No selection</Text>
          </span>
        )}
      </div>
      {Object.keys(states).length ? (
        <>
          <Legend dotClass="bg-ok" copyId="projects.placement-map.placed">
            Placed
          </Legend>
          <Legend dotClass="bg-warn" copyId="projects.placement-map.attention">
            Attention
          </Legend>
        </>
      ) : null}
      <span className="ml-auto flex-none font-mono text-2xs text-t3">
        <span className="mr-3 text-t3">{zoomPercent}%</span>
        {visible.length} {visible.length === 1 ? placementLabel : placementsLabel}
      </span>
    </footer>
  );
}


function SelectionLocator({
  reference,
  width,
  height,
}: {
  reference: string;
  width: number;
  height: number;
}) {
  const locatorWidth = Math.max(width + 18, 28);
  const locatorHeight = Math.max(height + 18, 28);
  const left = -locatorWidth / 2;
  const right = locatorWidth / 2;
  const top = -locatorHeight / 2;
  const bottom = locatorHeight / 2;
  const arm = Math.min(8, locatorWidth / 3, locatorHeight / 3);

  return (
    <g
      data-active-locator={reference}
      aria-hidden="true"
      className="pointer-events-none fill-none stroke-acc opacity-90 transition-opacity duration-150 motion-reduce:transition-none"
      strokeWidth="2"
      strokeLinecap="square"
    >
      <path d={`M ${left + arm} ${top} H ${left} V ${top + arm}`} />
      <path d={`M ${right - arm} ${top} H ${right} V ${top + arm}`} />
      <path d={`M ${left + arm} ${bottom} H ${left} V ${bottom - arm}`} />
      <path d={`M ${right - arm} ${bottom} H ${right} V ${bottom - arm}`} />
    </g>
  );
}

function pinKey(pin: ProjectBoardScenePin) {
  return `${pin.side}:${pin.layer}:${pin.number}:${pin.x_mm}:${pin.y_mm}`;
}

function viaKey(via: ProjectBoardSceneVia) {
  return `${via.net}:${via.name}:${via.x_mm}:${via.y_mm}:${via.diameter_mm}`;
}

function pinMarker(pin: ProjectBoardScenePin, scale: number) {
  const width = Math.max(4, (pin.shape?.width_mm ?? 0.45) * scale);
  const height = Math.max(4, (pin.shape?.height_mm ?? 0.45) * scale);
  return {
    width,
    height,
    hitWidth: Math.max(width, 10),
    hitHeight: Math.max(height, 10),
    radius:
      pin.shape?.kind === "circle" || pin.shape?.kind === "oval"
        ? Math.min(width, height) / 2
        : pin.shape?.kind === "rounded-rect"
          ? Math.min(3, Math.min(width, height) / 3)
          : 1,
  };
}

function markerSize(
  component: ProjectBoardSceneComponent | undefined,
  transform: ReturnType<typeof placementTransform>,
  selected: boolean,
  active: boolean,
) {
  const physicalWidth = component?.bounds
    ? component.bounds.width * transform.scale
    : 6;
  const physicalHeight = component?.bounds
    ? component.bounds.height * transform.scale
    : 4;
  const emphasis = active ? 4 : selected ? 2 : 0;
  const width = Math.max(physicalWidth + emphasis, active ? 8 : 4);
  const height = Math.max(physicalHeight + emphasis, active ? 7 : 4);
  return {
    width,
    height,
    hitWidth: Math.max(width, 4),
    hitHeight: Math.max(height, 4),
    radius: Math.min(3, Math.max(1, Math.min(width, height) / 4)),
    padOffset: Math.min(width / 3, Math.max(1.5, width * 0.22)),
    padRadius: Math.min(2.8, Math.max(1, Math.min(width, height) * 0.16)),
  };
}

function placementTransform(
  placements: ProjectPlacement[],
  boardBounds?: ProjectBoardBounds,
) {
  const viewport = { x: 40, y: 40, width: 920, height: 540 };
  const measured = boardBounds ?? placementBounds(placements);
  if (!measured) {
    return {
      frame: viewport,
      scale: 1,
      point() {
        return { x: 500, y: 310 };
      },
    };
  }
  const scale = Math.min(
    viewport.width / measured.width,
    viewport.height / measured.height,
  );
  const frame = {
    x: viewport.x + (viewport.width - measured.width * scale) / 2,
    y: viewport.y + (viewport.height - measured.height * scale) / 2,
    width: measured.width * scale,
    height: measured.height * scale,
  };
  return {
    frame,
    scale,
    point(placement: Pick<ProjectPlacement, "x_mm" | "y_mm">) {
      return {
        x: frame.x + (placement.x_mm - measured.min_x) * scale,
        y: frame.y + (measured.max_y - placement.y_mm) * scale,
      };
    },
  };
}

function placementBounds(
  placements: ProjectPlacement[],
): ProjectBoardBounds | undefined {
  if (!placements.length) return undefined;
  const xs = placements.map((placement) => placement.x_mm);
  const ys = placements.map((placement) => placement.y_mm);
  const minX = Math.min(...xs);
  const maxX = Math.max(...xs);
  const minY = Math.min(...ys);
  const maxY = Math.max(...ys);
  const width = Math.max(maxX - minX, 1);
  const height = Math.max(maxY - minY, 1);
  return {
    min_x: minX - width * 0.05,
    min_y: minY - height * 0.05,
    max_x: maxX + width * 0.05,
    max_y: maxY + height * 0.05,
    width: width * 1.1,
    height: height * 1.1,
  };
}

function stageViewBox(frame: {
  x: number;
  y: number;
  width: number;
  height: number;
}) {
  const margin = Math.max(48, Math.min(frame.width, frame.height) * 0.08);
  return [
    frame.x - margin,
    frame.y - margin,
    frame.width + margin * 2,
    frame.height + margin * 2,
  ].join(" ");
}

function markerClass(
  state: AssemblyPlacementState | undefined,
  selected: boolean,
  active: boolean,
  nativeBoard: boolean,
) {
  if (active) return "fill-acc stroke-surface";
  if (state === "done" || state === "reworked") return "fill-ok stroke-surface";
  if (state === "skipped") return "fill-warn stroke-surface";
  if (state === "issue") return "fill-err stroke-surface";
  if (selected) return "fill-acc/80 stroke-acc";
  if (nativeBoard) {
    return "fill-transparent stroke-transparent group-hover:fill-surface/55 group-hover:stroke-t2/70";
  }
  return "fill-t2/35 stroke-t3/60";
}

function findBoardDocument(
  documents: ProjectVisualDocument[],
  board: string,
): ProjectVisualDocument | undefined {
  const normalizedBoard = normalizePath(board);
  const boardDocuments = documents.filter(
    (document) => document.kind === "pcb" && document.status === "ready",
  );
  return (
    boardDocuments.find((candidate) => normalizePath(candidate.path) === normalizedBoard) ??
    (boardDocuments.length === 1 ? boardDocuments[0] : undefined)
  );
}

function normalizePath(path: string) {
  return path.replaceAll("\\", "/").toLocaleLowerCase();
}

function fileName(path: string) {
  const pieces = path.replaceAll("\\", "/").split("/");
  return pieces[pieces.length - 1] || path;
}

function StageMessage({
  children,
  tone = "neutral",
  devId,
}: {
  children: React.ReactNode;
  tone?: "neutral" | "warn";
  devId?: string;
}) {
  return (
    <div
      data-dev-id={devId}
      className={`absolute inset-0 z-10 flex items-center justify-center p-6 text-center text-sm ${
        tone === "warn" ? "text-warn" : "text-t3"
      }`}
    >
      {children}
    </div>
  );
}

function Legend({
  dotClass,
  copyId,
  children,
}: {
  dotClass: string;
  copyId: string;
  children: string;
}) {
  return (
    <span className="flex min-w-0 items-center gap-1.5">
      <span aria-hidden className={`size-2 flex-none rounded-full ${dotClass}`} />
      <span className="truncate">
        <Text id={copyId}>{children}</Text>
      </span>
    </span>
  );
}

function StageToolButton({
  label,
  framed = false,
  children,
  ...props
}: {
  label: string;
  framed?: boolean;
  children: React.ReactNode;
} & React.ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      className={`flex h-6 w-6 items-center justify-center rounded-control text-t3 transition-colors hover:bg-raise hover:text-t1 focus-visible:outline focus-visible:outline-2 focus-visible:outline-focus disabled:cursor-not-allowed disabled:opacity-35 ${
        framed ? "border border-line bg-field" : ""
      }`}
      {...props}
    >
      {children}
    </button>
  );
}

function MinusGlyph() {
  return (
    <svg aria-hidden viewBox="0 0 16 16" className="size-3.5">
      <path d="M3 8h10" fill="none" stroke="currentColor" strokeWidth="1.5" />
    </svg>
  );
}

function PlusGlyph() {
  return (
    <svg aria-hidden viewBox="0 0 16 16" className="size-3.5">
      <path d="M3 8h10M8 3v10" fill="none" stroke="currentColor" strokeWidth="1.5" />
    </svg>
  );
}

function ExpandGlyph() {
  return (
    <svg aria-hidden viewBox="0 0 16 16" className="size-3.5">
      <path
        d="M2.75 6V2.75H6M10 2.75h3.25V6M13.25 10v3.25H10M6 13.25H2.75V10"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.35"
      />
    </svg>
  );
}

function ContractGlyph() {
  return (
    <svg aria-hidden viewBox="0 0 16 16" className="size-3.5">
      <path
        d="M6 2.75V6H2.75M13.25 6H10V2.75M10 13.25V10h3.25M2.75 10H6v3.25"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.35"
      />
    </svg>
  );
}
