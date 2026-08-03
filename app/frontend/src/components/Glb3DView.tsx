/**
 * The three.js GLB canvas, decoupled from where the GLB came from (a committed part or a
 * stock lib_id). Given the fetched GLB bytes plus the query's loading/error state, it
 * mounts the auto-rotating scene and degrades honestly: a 502 (no conversion tooling on
 * this machine) or a WebGL failure shows a plain message, never a blank canvas or a crash.
 * The heavy three.js code is import()ed lazily so it only loads when a 3D view is open.
 */
import { useEffect, useRef, useState } from "react";
import type {
  ModelSceneHandle,
  PlacementMode,
  RenderMode,
  ViewMode,
} from "../lib/threeScene";
import type { PlacementAssessment } from "../lib/placementAssessment";
// VALUE import, and deliberately from boardPlane rather than threeScene: threeScene
// top-level-imports three and is loaded lazily so three lands in its own chunk, so importing a
// value from it here would pull the whole library into the main bundle. boardPlane is three-free.
import { DEFAULT_LAYERS } from "../lib/boardPlane";
import type { LandPattern } from "../api/client";
import { ApiError } from "../api/client";
import { Icon } from "./Icon";

export type ModelVisibility = "checking" | "visible" | "unavailable";

function startsWithMotion(): boolean {
  return !(
    typeof window !== "undefined" &&
    window.matchMedia?.("(prefers-reduced-motion: reduce)").matches === true
  );
}

function usableLandPattern(land: LandPattern | null | undefined): LandPattern | null {
  // The 3D model is independently useful. Older caches and partial test/provider
  // responses can have a land-pattern object without the arrays required by the
  // overlay renderer; treat that as no overlay instead of taking down the preview.
  return land && Array.isArray(land.pads) ? land : null;
}

function Centered({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex h-full w-full items-center justify-center px-6 text-center text-sm text-t3">
      {children}
    </div>
  );
}

export function Glb3DView({
  data,
  isLoading,
  isError,
  error,
  land,
  showViews = false,
  showShading = false,
  compact = false,
  onVisibilityChange,
}: {
  data: ArrayBuffer | undefined;
  isLoading: boolean;
  isError: boolean;
  error?: unknown;
  /** The part's land pattern, when one could be read. Absent simply hides the Board toggle:
   *  a part with no footprint has nothing to check the body against. */
  land?: LandPattern | null;
  /**
   * Whether the canonical VIEW controls (3D / Top / Front) appear here.
   *
   * Off for the inline detail tile (owner, 2026-07-25). At 266px the control bar wrapped to three
   * rows and took about a third of a 268px tile, leaving the render less room than its own chrome.
   * The views are the least-used of the three groups and the ones that most want a big stage to
   * be worth switching to, so they live in the preview modal - where there is room - and the tile
   * keeps the layer and shading toggles. No feature is lost; it moves to where it is usable.
   */
  showViews?: boolean;
  /**
   * Whether the SHADING controls (Source Color / Studio / X-Ray) appear here.
   *
   * Off for the inline detail tile for the same reason the views are, and by the owner's reading of
   * the result: *"the new ui u developed looks so uneven in some parts, like the buttons in 3d model
   * viewer"*. Measured, the tile carried THREE stacked strips under its render - layer chips,
   * shading chips, then the tile's own label bar - while the Symbol and Footprint tiles beside it
   * carried one. Shading is a viewing PREFERENCE, not a per-part action: nobody sets it to answer a
   * question about this diode. It belongs on the big stage next to the views, and the tile is left
   * with the one group that is genuinely per-part, the layers.
   */
  showShading?: boolean;
  /** Narrow host (the detail tile): controls become compact icons and advanced controls move
   *  behind one settings button. Orbit, zoom, layers, motion and inspection remain available. */
  compact?: boolean;
  /**
   * Reports rendered truth, not file presence. `visible` is emitted only after
   * Three.js has parsed non-empty geometry and computed its first complete frame.
   */
  onVisibilityChange?: (state: ModelVisibility) => void;
}) {
  const mountRef = useRef<HTMLDivElement>(null);
  // Bind a parse/WebGL failure to the bytes that caused it. A plain boolean survived a part
  // change, removed the canvas from the DOM, and then prevented the replacement scene from ever
  // mounting because the effect had already observed the new data while no mount node existed.
  const [failedData, setFailedData] = useState<ArrayBuffer | null>(null);
  const sceneRef = useRef<ModelSceneHandle | null>(null);
  // Which canonical view is in force. Tracked in React (not read back off the camera) so the
  // control can show the CURRENT answer rather than just issuing commands into the scene.
  const [view, setView] = useState<ViewMode | null>("iso");
  const [showLand, setShowLand] = useState(DEFAULT_LAYERS.pads);
  // Start with the source-authored materials. Studio remains available for shape inspection, but
  // it must be an explicit choice rather than making every newly opened part look like a clay model.
  const [renderMode, setRenderMode] = useState<RenderMode>("realistic");
  // The idle spin. Owner 2026-07-26 asked for "an option to stop rotation" - and the same switch closes
  // a logged accessibility defect, since the perpetual rotation ignored prefers-reduced-motion while
  // the 300ms view tween honoured it. `setSpin` returns the state actually in force, which is false
  // under reduced motion whatever is asked, so the chip can never claim to be spinning when it is not.
  const [spinning, setSpinning] = useState(startsWithMotion);
  const [showModel, setShowModel] = useState(DEFAULT_LAYERS.model);
  const [showBoard, setShowBoard] = useState(DEFAULT_LAYERS.board);
  const [placementMode, setPlacementMode] = useState<PlacementMode>("auto");
  const [placementAssessment, setPlacementAssessment] =
    useState<PlacementAssessment | null>(null);
  const [selectedPlacementSource, setSelectedPlacementSource] = useState<"kicad" | "model">(
    "model",
  );
  const [compactControlsOpen, setCompactControlsOpen] = useState(false);
  const renderableLand = usableLandPattern(land);
  const landRef = useRef<LandPattern | null>(renderableLand);
  landRef.current = renderableLand;
  // The scene is imported asynchronously. Keep one current snapshot so the handle receives the
  // state visible in React at the moment it becomes available, rather than the values captured by
  // an older render that began the import.
  const viewerStateRef = useRef({
    view,
    showLand,
    renderMode,
    spinning,
    showModel,
    showBoard,
    placementMode,
  });
  viewerStateRef.current = {
    view,
    showLand,
    renderMode,
    spinning,
    showModel,
    showBoard,
    placementMode,
  };

  useEffect(() => {
    onVisibilityChange?.(isError || (!isLoading && !data) ? "unavailable" : "checking");
  }, [data, isError, isLoading, onVisibilityChange]);

  useEffect(() => {
    const container = mountRef.current;
    if (!data || !container) return;
    let disposed = false;
    let handle: ModelSceneHandle | null = null;
    void (async () => {
      try {
        const { mountModelScene } = await import("../lib/threeScene");
        if (disposed || !mountRef.current) return;
        handle = mountModelScene(mountRef.current, data, {
          onError: () => {
            // GLTFLoader rejected the GLB asynchronously: show an honest message rather
            // than a blank canvas.
            if (!disposed) {
              setFailedData(data);
              onVisibilityChange?.("unavailable");
            }
          },
          onReady: () => {
            if (!disposed) onVisibilityChange?.("visible");
          },
          onViewChange: (nextView) => {
            if (!disposed) setView(nextView);
          },
          onPlacementAssessment: (assessment, source) => {
            if (!disposed) {
              setPlacementAssessment(assessment);
              setSelectedPlacementSource(source);
            }
          },
        });
        sceneRef.current = handle;
        const state = viewerStateRef.current;
        handle.setPlacementMode(state.placementMode);
        // Build whenever the data exists, not only when the Pads toggle happens to be on: the
        // board and the pads are two independently switchable layers of ONE land pattern, and
        // gating construction on one of them made the other unreachable.
        const currentLand = landRef.current;
        if (currentLand) handle.setLandPattern(currentLand);
        handle.setRenderMode(state.renderMode);
        handle.setLayers({
          model: state.showModel,
          pads: state.showLand,
          board: state.showBoard,
        });
        const spinInForce = handle.setSpin(state.spinning);
        if (spinInForce !== state.spinning && !disposed) setSpinning(spinInForce);
        if (state.view) handle.setView(state.view);
      } catch {
        // no WebGL context (or three failed to load): degrade honestly.
        if (!disposed) {
          setFailedData(data);
          onVisibilityChange?.("unavailable");
        }
      }
    })();
    return () => {
      disposed = true;
      sceneRef.current = null;
      handle?.dispose();
    };
  }, [data, onVisibilityChange]);

  // Land data is a separate query from the GLB. It frequently resolves after the renderer has
  // mounted, so it needs its own synchronization path; tying it to the data-only mount effect left
  // the board and pads absent forever for exactly that ordinary arrival order.
  useEffect(() => {
    sceneRef.current?.setLandPattern(renderableLand);
  }, [renderableLand]);

  if (isLoading) {
    return <Centered>Loading 3D model...</Centered>;
  }
  if (isError) {
    const err = error instanceof ApiError ? error : null;
    // A 502 carries an honest, specific reason from the backend (tooling not installed,
    // or a WRL model that is not convertible yet) — show it rather than a single guess.
    const message =
      err?.status === 502 && err.message ? err.message : "Could not load the 3D model.";
    return <Centered>{message}</Centered>;
  }
  if (data && failedData === data) {
    return <Centered>This device could not render the 3D preview.</Centered>;
  }
  return (
    // The controls sit in a RESERVED BAR beneath the canvas, not floating over it.
    //
    // They used to be two chip stacks pinned bottom-left plus the view cluster bottom-right, which
    // was fine only while the stage was 540px tall and mostly empty. The moment the stage took the
    // landscape proportion a part actually has (2026-07-25, the composition slice), those stacks
    // landed ON the model - measured, and the exact reason an earlier attempt at the aspect was
    // reverted. Overlaying controls on the subject is a bet that the subject will stay small, and
    // that bet is what the camera-fit work exists to lose.
    //
    // The full inspection bar deliberately spends space on visible grouping and credible targets.
    // Compact keeps the same capabilities through icon controls and one advanced-settings popover.
    <div className="relative flex h-full w-full flex-col">
      <div
        ref={mountRef}
        data-testid="model-canvas"
        tabIndex={0}
        role="application"
        aria-label="3D model inspection canvas. Drag to orbit, scroll to zoom, and press 0 or F to fit."
        onKeyDown={(event) => {
          if (event.key === "0" || event.key.toLowerCase() === "f") {
            event.preventDefault();
            sceneRef.current?.fit();
          }
        }}
        className="relative min-h-0 w-full flex-1 outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-acc"
      />
      {!compact && showViews ? <div aria-hidden="true" className="h-[82px] flex-none" /> : null}
      <div
        onClick={(e) => e.stopPropagation()}
        // pointer-events-auto is LOAD-BEARING: the detail panel wraps this whole view in a
        // `pointer-events-none` box so the render never swallows the tile's own open-preview
        // click. The controls have to opt back in, or they render perfectly and do nothing.
        // They did exactly that when they moved from floating chips (which each carried this) into
        // this bar - every screenshot looked right and not one control could be clicked.
        // justify-BETWEEN, not start. Owner 2026-07-26: "the settings should look clean, the buttons
        // are all just pushed to one corner" - which was literally the CSS: every cluster crammed left
        // with the rest of the bar empty. Now the layer + shading clusters hold the left and the view
        // cluster holds the right, so the bar reads as two ends rather than one heap.
        className={
          "pointer-events-auto flex items-center " +
          (compact
            ? "h-[38px] flex-none justify-between gap-2 border-t border-line2 bg-band px-2 py-1"
            : "absolute bottom-3 left-1/2 z-10 w-max max-w-[calc(100%-24px)] -translate-x-1/2 gap-0 overflow-x-auto rounded-card border border-line2 bg-popover/95 p-2 shadow-pop backdrop-blur-sm")
        }
      >
      {/* Compact has only layer icons here. The full inspection stage has room for explicit
          Layers / Appearance / Placement groups, so the user does not have to decode one heap. */}
      <div
        data-dev-id="detail.model-layers"
        className={"flex min-w-0 items-center " + (compact ? "gap-1" : "gap-0")}
      >
        <div
          className={compact ? "flex items-center gap-1.5" : "flex flex-col items-start gap-1 pr-3"}
          role="group"
          aria-label="Layers"
        >
          {!compact ? <ControlLabel>Layers</ControlLabel> : null}
          <div className="flex items-center gap-0.5 rounded-control border border-line2 bg-field p-0.5">
          <LayerToggle
            devId="detail.model-show-model"
            icon="layer.model"
            compact={compact}
            label="Model"
            on={showModel}
            hint="Show or hide the 3D body"
            onToggle={() => {
              const next = !showModel;
              setShowModel(next);
              sceneRef.current?.setLayers({ model: next });
            }}
          />
          {renderableLand && renderableLand.pads.length > 0 ? (
            <>
              <LayerToggle
                devId="detail.model-board"
            icon="layer.pads"
            compact={compact}
                label="Pads"
                on={showLand}
                hint="Show the land pattern, to check the body is oriented correctly"
                onToggle={() => {
                  const next = !showLand;
                  setShowLand(next);
                  // visibility only - the geometry is already built. Rebuilding it here also
                  // destroyed and recreated the board every time the pads were toggled.
                  sceneRef.current?.setLayers({ pads: next });
                }}
              />
              <LayerToggle
                devId="detail.model-show-board"
            icon="layer.board"
            compact={compact}
                label="PCB"
                on={showBoard}
                hint="Show the board the pads sit on"
                onToggle={() => {
                  const next = !showBoard;
                  setShowBoard(next);
                  sceneRef.current?.setLayers({ board: next });
                }}
              />
            </>
          ) : null}
          </div>
        </div>
        {showShading && !compact ? (
        <div
          data-dev-id="detail.model-shading"
          role="group"
          aria-label="Appearance"
          // NO border-l. On a bar that wraps, a left border on a flex child becomes a stray vertical
          // tick floating at the start of the new row - visible in the owner's real shot as a glitch
          // beside "Realistic". Grouping is carried by the gap instead, which cannot wrap wrongly.
          className="flex flex-col items-start gap-1 border-l border-line pl-3 pr-3"
        >
          <ControlLabel>Appearance</ControlLabel>
          <div className="flex items-center gap-0.5 rounded-control border border-line2 bg-field p-0.5">
          {SHADING.map((r) => (
            <LayerToggle
              key={r.mode}
              devId={r.devId}
              label={r.label}
              icon={r.icon}
              compact={compact}
              on={renderMode === r.mode}
              hint={r.hint}
              onToggle={() => {
                setRenderMode(r.mode);
                sceneRef.current?.setRenderMode(r.mode);
              }}
            />
          ))}
          </div>
        </div>
        ) : null}
        {showViews && !compact && renderableLand?.model_placement ? (
          <PlacementControls
            active={placementMode}
            assessment={placementAssessment}
            selectedSource={selectedPlacementSource}
            onPick={(mode) => {
              setPlacementMode(mode);
              sceneRef.current?.setPlacementMode(mode);
            }}
          />
        ) : null}
      </div>
      {showViews ? (
        <div className={"flex items-center " + (compact ? "gap-1" : "gap-0")}>
          <div
            className={
              compact
                ? "flex items-center gap-1.5"
                : "flex flex-col items-start gap-1 border-l border-line pl-3 pr-3"
            }
            role="group"
            aria-label="Motion"
          >
            {!compact ? <ControlLabel>Motion</ControlLabel> : null}
            <div className="flex items-center rounded-control border border-line2 bg-field p-0.5">
              <LayerToggle
                devId="detail.model-spin"
                icon="action.refresh"
                compact={compact}
                label="Auto rotate"
                on={spinning}
                hint="Stop or resume automatic rotation"
                onToggle={() => {
                  const next = !spinning;
                  // trust the SCENE's answer, not the request: under prefers-reduced-motion it stays off
                  const inForce = sceneRef.current?.setSpin(next) ?? next;
                  setSpinning(inForce);
                }}
              />
            </div>
          </div>
          {compact ? (
            <button
              type="button"
              data-dev-id="detail.model-settings"
              aria-label="3D view settings"
              aria-expanded={compactControlsOpen}
              title="View, appearance, placement, and fit settings"
              onClick={() => setCompactControlsOpen((open) => !open)}
              className={
                "flex h-[30px] w-[30px] items-center justify-center rounded-control border border-line2 transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-acc " +
                (compactControlsOpen
                  ? "bg-raise2 text-t1 shadow-card"
                  : "bg-field text-t2 hover:bg-raise hover:text-t1")
              }
            >
              <Icon id="action.settings" className="h-4 w-4" />
            </button>
          ) : (
            <div
              className="flex flex-col items-start gap-1 border-l border-line pl-3"
              role="group"
              aria-label="Camera view"
            >
              <ControlLabel>View</ControlLabel>
              <div className="flex items-center gap-1">
                <ViewControls
                  active={view}
                  onPick={(mode) => {
                    setView(mode);
                    sceneRef.current?.setView(mode);
                  }}
                />
                <button
                  type="button"
                  onClick={() => sceneRef.current?.fit()}
                  title="Frame the whole visible model (0 or F)"
                  className="inline-flex min-h-[32px] items-center rounded-control border border-line2 bg-field px-2.5 text-xs font-semibold text-t2 transition-[transform,background-color,color] active:scale-[0.97] hover:bg-raise hover:text-t1 focus-visible:outline focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-acc"
                >
                  Fit
                </button>
              </div>
            </div>
          )}
        </div>
      ) : null}
      </div>
      {compact && compactControlsOpen ? (
        <div
          data-dev-id="detail.model-settings-popover"
          onClick={(event) => event.stopPropagation()}
          className="pointer-events-auto absolute bottom-10 right-2 z-20 w-[270px] rounded-card border border-line2 bg-popover p-2 shadow-pop"
        >
          <ControlSection label="View">
            <div className="flex items-center gap-1">
              <ViewControls
                active={view}
                compact
                onPick={(mode) => {
                  setView(mode);
                  sceneRef.current?.setView(mode);
                }}
              />
              <button
                type="button"
                onClick={() => sceneRef.current?.fit()}
                aria-label="Fit model"
                title="Frame the whole visible model (0 or F)"
                className="flex h-[32px] min-w-[42px] items-center justify-center rounded-control border border-line2 bg-field px-2 text-xs font-semibold text-t2 hover:bg-raise hover:text-t1 focus-visible:outline focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-acc"
              >
                Fit
              </button>
            </div>
          </ControlSection>
          {showShading ? (
            <ControlSection label="Appearance">
              <div className="flex items-center gap-0.5 rounded-control border border-line2 bg-field p-0.5">
                {SHADING.map((item) => (
                  <LayerToggle
                    key={item.mode}
                    devId={item.devId}
                    label={item.label}
                    icon={item.icon}
                    compact
                    on={renderMode === item.mode}
                    hint={item.hint}
                    onToggle={() => {
                      setRenderMode(item.mode);
                      sceneRef.current?.setRenderMode(item.mode);
                    }}
                  />
                ))}
              </div>
            </ControlSection>
          ) : null}
          {renderableLand?.model_placement ? (
            <ControlSection label="Placement">
              <PlacementControls
                active={placementMode}
                assessment={placementAssessment}
                selectedSource={selectedPlacementSource}
                showLabel={false}
                onPick={(mode) => {
                  setPlacementMode(mode);
                  sceneRef.current?.setPlacementMode(mode);
                }}
              />
            </ControlSection>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

function ControlSection({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div className="flex items-start justify-between gap-2 border-b border-line py-2 last:border-b-0">
      <span className="flex-none pt-2 text-2xs font-semibold text-t3">{label}</span>
      <div className="min-w-0">{children}</div>
    </div>
  );
}

function ControlLabel({ children }: { children: React.ReactNode }) {
  return <span className="flex-none text-2xs font-semibold text-t3">{children}</span>;
}

const PLACEMENT_MODES: {
  mode: PlacementMode;
  label: string;
  hint: string;
  icon: string;
}[] = [
  {
    mode: "auto",
    label: "Auto",
    hint: "Use KiCad placement when it passes conservative sanity checks; otherwise show the model frame",
    icon: "action.enrich",
  },
  {
    mode: "kicad",
    label: "Source",
    hint: "Show the KiCad model placement exactly, even when it is flagged",
    icon: "layer.pads",
  },
  {
    mode: "model",
    label: "Model",
    hint: "Ignore footprint placement and inspect the model's own frame",
    icon: "layer.model",
  },
];

function PlacementControls({
  active,
  assessment,
  selectedSource,
  onPick,
  showLabel = true,
}: {
  active: PlacementMode;
  assessment: PlacementAssessment | null;
  selectedSource: "kicad" | "model";
  onPick: (mode: PlacementMode) => void;
  showLabel?: boolean;
}) {
  const suspect = assessment?.status === "suspect";
  const issueText = assessment?.issues.join(". ");
  return (
    <div
      className={
        showLabel
          ? "flex flex-col items-start gap-1 border-l border-line pl-3 pr-3"
          : "flex w-full flex-col items-start gap-1.5"
      }
      role="group"
      aria-label="Placement"
    >
      {showLabel ? <ControlLabel>Placement</ControlLabel> : null}
      <div
        className={
          showLabel ? "flex items-center gap-1.5" : "flex w-full flex-col items-start gap-1.5"
        }
      >
        <div className="flex items-center gap-0.5 rounded-control border border-line2 bg-field p-0.5">
          {PLACEMENT_MODES.map((item) => (
            <button
              key={item.mode}
              type="button"
              aria-pressed={active === item.mode}
              title={item.hint}
              onClick={() => onPick(item.mode)}
              className={
                "inline-flex min-h-[32px] items-center gap-1.5 rounded-control px-2.5 text-xs font-semibold transition-[transform,background-color,color] active:scale-[0.97] " +
                "focus-visible:outline focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-acc " +
                (active === item.mode
                  ? "bg-raise2 text-t1 shadow-card"
                  : "text-t2 hover:bg-raise hover:text-t1")
              }
            >
              <Icon id={item.icon} className="h-4 w-4" />
              <span>{item.label}</span>
            </button>
          ))}
        </div>
        <span
          title={
            suspect
              ? `${issueText}. Auto is showing the ${selectedSource} frame.`
              : `Auto is showing the ${selectedSource} frame.`
          }
          className={
            "flex min-h-[32px] items-center rounded-control px-2 text-xs font-semibold " +
            (suspect ? "bg-warn/15 text-warn" : "bg-ok/15 text-ok")
          }
        >
          {suspect ? "Check" : selectedSource === "kicad" ? "Source" : "Model"}
        </span>
      </div>
    </div>
  );
}

// The dev-id is written out in FULL rather than built as `detail.model-view-${mode}`: the parity
// gate scans source text, so an interpolated id is invisible to it and to anyone grepping for it.
const SHADING: { mode: RenderMode; label: string; hint: string; devId: string; icon: string }[] = [
  {
    mode: "realistic",
    label: "Source Color",
    hint: "The model's source-authored materials, physically lit with ambient occlusion",
    devId: "detail.model-shade-realistic",
    icon: "view.shade-realistic",
  },
  {
    mode: "studio",
    label: "Studio",
    hint: "Flat high-contrast surface with feature lines, easiest for reading shape",
    devId: "detail.model-shade-studio",
    icon: "view.shade-studio",
  },
  {
    mode: "xray",
    label: "X-Ray",
    hint: "Translucent body, so the pads underneath stay visible",
    devId: "detail.model-shade-xray",
    icon: "view.shade-xray",
  },
];

/** One visible, comfortably sized toggle. Pressed state carries the answer audibly and visually. */
function LayerToggle({
  devId,
  label,
  on,
  hint,
  onToggle,
  icon,
  compact = false,
}: {
  devId: string;
  label: string;
  on: boolean;
  hint: string;
  onToggle: () => void;
  /** Registry icon id. Only used in `compact` mode. */
  icon?: string;
  /** ICON-ONLY. The mini tile is ~280px and ten text chips wrapped to three rows there, taking a third
   *  of the stage; the owner chose icon-only for the tile (2026-07-26). The modal has room and keeps
   *  its labels. The NAME is never lost - `title` and `aria-label` both carry it. */
  compact?: boolean;
}) {
  const iconOnly = compact && !!icon;
  return (
    <button
      type="button"
      data-dev-id={devId}
      aria-pressed={on}
      aria-label={iconOnly ? label : undefined}
      title={iconOnly ? `${label} - ${hint}` : hint}
      onClick={(e) => {
        e.stopPropagation();
        onToggle();
      }}
      className={
        "rounded-control font-semibold transition-[transform,background-color,color] duration-150 ease-out active:scale-[0.97] " +
        "focus-visible:outline focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-acc " +
        (iconOnly
          ? "flex h-[30px] w-[30px] items-center justify-center "
          : "inline-flex min-h-[32px] items-center gap-1.5 px-2.5 text-xs ") +
        (on ? "bg-raise2 text-t1 shadow-card" : "text-t2 hover:bg-raise hover:text-t1")
      }
    >
      {icon ? <Icon id={icon} className="h-4 w-4 flex-none" /> : null}
      {!iconOnly ? <span>{label}</span> : null}
    </button>
  );
}

const VIEWS: { mode: ViewMode; label: string; hint: string; devId: string; icon: string }[] = [
  {
    mode: "iso",
    label: "Isometric",
    hint: "Three-quarter view",
    devId: "detail.model-view-iso",
    icon: "view.iso",
  },
  {
    mode: "top",
    label: "Top",
    hint: "Looking down at the land pattern",
    devId: "detail.model-view-top",
    icon: "view.top",
  },
  {
    mode: "front",
    label: "Front",
    hint: "Side elevation, the way a datasheet draws height",
    devId: "detail.model-view-front",
    icon: "view.front",
  },
];

/**
 * The canonical views, as a visible segmented control in the reserved toolbar.
 *
 * Deliberately ALWAYS VISIBLE rather than revealed on hover: this is the only affordance telling
 * anyone the viewer has more than one view, and a control nobody can find is the same as a control
 * that does not exist. A bordered track plus a raised selected state makes both the hit region and
 * the current answer legible without competing with the render.
 */
function ViewControls({
  active,
  onPick,
  compact = false,
}: {
  active: ViewMode | null;
  onPick: (mode: ViewMode) => void;
  /** ICON-ONLY in the narrow tile. This component renders its own buttons rather than LayerToggle, so
   *  it did NOT inherit the tile's compact mode and its three chips stayed text while the other seven
   *  became icons - the bar sat at two rows for that reason alone. */
  compact?: boolean;
}) {
  return (
    <div
      data-dev-id="detail.model-views"
      // the whole strip swallows the tile's open-on-click, not just the buttons
      onClick={(e) => e.stopPropagation()}
      className="flex items-center gap-0.5 rounded-control border border-line2 bg-field p-0.5"
    >
      {VIEWS.map((v) => (
        <button
          key={v.mode}
          type="button"
          data-dev-id={v.devId}
          aria-pressed={active === v.mode}
          aria-label={compact ? v.label : undefined}
          title={compact ? `${v.label} - ${v.hint}` : v.hint}
          onClick={(e) => {
            // The tile that hosts this canvas is ITSELF a click target that opens the preview
            // modal, so without stopping here, choosing a view ALSO opened the modal - the
            // control appeared to do two things at once.
            e.stopPropagation();
            onPick(v.mode);
          }}
          className={
            // 160ms ease-out + a 0.97 press: a control with no press feedback does not feel like
            // it heard the click. transform/opacity only, so it stays off the layout path.
            "rounded-control font-semibold transition-[transform,background-color,color] duration-150 ease-out active:scale-[0.97] " +
            "focus-visible:outline focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-acc " +
            (compact
              ? "flex h-[30px] w-[30px] items-center justify-center "
              : "inline-flex min-h-[32px] items-center gap-1.5 px-2.5 text-xs ") +
            (active === v.mode
              ? "bg-raise2 text-t1 shadow-card"
              : "text-t2 hover:bg-raise hover:text-t1")
          }
        >
          <Icon id={v.icon} className="h-4 w-4 flex-none" />
          {!compact ? <span>{v.label}</span> : null}
        </button>
      ))}
    </div>
  );
}
