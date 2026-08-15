/**
 * Ownership of one three.js model scene, and of the React state that mirrors it.
 *
 * This is the half of the 3D viewer that is not markup: the mount node, the scene handle, the eight
 * values a viewer can be in (which view, which layers, which shading, whether it spins, how the
 * body is placed) and the effects that keep the scene and those values in step. It is a hook rather
 * than a component because it renders nothing - it synchronises an external object - and the
 * control surface that DOES render is a different concern with a different reason to change.
 *
 * The setters it hands back are the reason it exists in this shape. Each one moves React state and
 * commands the scene in the same act, so "the pads are on" cannot mean two things; before, the
 * viewer's control strip and its settings popover each carried their own copy of every one of those
 * six pairs, which is six chances for the two surfaces to disagree about what a toggle does.
 *
 * The scene is imported lazily (three.js is large and belongs in its own chunk), so everything here
 * has to survive the handle arriving one microtask after the commit that asked for it.
 */
import { useEffect, useLayoutEffect, useRef, useState, type RefObject } from "react";
import type { LandPattern } from "../api/client";
// VALUE import, and deliberately from boardPlane rather than threeScene: threeScene
// top-level-imports three and is loaded lazily so three lands in its own chunk, so importing a
// value from it here would pull the whole library into the main bundle. boardPlane is three-free.
import { DEFAULT_LAYERS } from "./boardPlane";
import type { PlacementAssessment } from "./placementAssessment";
import type {
  ModelSceneHandle,
  PlacementMode,
  RenderMode,
  ViewMode,
} from "./threeScene";

export type ModelVisibility = "checking" | "visible" | "unavailable";

function startsWithMotion(): boolean {
  return !(
    typeof window !== "undefined" &&
    window.matchMedia?.("(prefers-reduced-motion: reduce)").matches === true
  );
}

export function usableLandPattern(land: LandPattern | null | undefined): LandPattern | null {
  // The 3D model is independently useful. Older caches and partial test/provider
  // responses can have a land-pattern object without the arrays required by the
  // overlay renderer; treat that as no overlay instead of taking down the preview.
  return land && Array.isArray(land.pads) ? land : null;
}

/**
 * What the viewer is showing, and the only sanctioned way to change it.
 *
 * Every setter writes React state AND commands the scene, so no caller can move one without the
 * other. `toggleSpin` is the one that cannot be a plain assignment: the scene answers with the
 * state actually in force, which is `false` under prefers-reduced-motion whatever was asked, and
 * that answer is what gets stored - so a chip can never claim to be spinning when it is not.
 */
export interface ModelViewerControls {
  view: ViewMode | null;
  showModel: boolean;
  showLand: boolean;
  showBoard: boolean;
  renderMode: RenderMode;
  spinning: boolean;
  placementMode: PlacementMode;
  placementAssessment: PlacementAssessment | null;
  selectedPlacementSource: "kicad" | "model";
  setView: (mode: ViewMode) => void;
  setRenderMode: (mode: RenderMode) => void;
  setPlacementMode: (mode: PlacementMode) => void;
  toggleModel: () => void;
  togglePads: () => void;
  toggleBoard: () => void;
  toggleSpin: () => void;
  fit: () => void;
}

export interface ModelScene {
  /** Attach to the element the canvas is mounted into. */
  mountRef: RefObject<HTMLDivElement>;
  /** True once THESE bytes failed to parse or this device could not give a WebGL context. */
  failed: boolean;
  /** The land pattern the overlay renderer can actually draw, or null. */
  land: LandPattern | null;
  controls: ModelViewerControls;
}

export function useModelScene({
  data,
  land,
  isLoading,
  isError,
  onVisibilityChange,
  boardInitiallyVisible = DEFAULT_LAYERS.board,
}: {
  data: ArrayBuffer | undefined;
  land: LandPattern | null | undefined;
  isLoading: boolean;
  isError: boolean;
  onVisibilityChange?: (state: ModelVisibility) => void;
  /** Initial board visibility. Mini previews omit the PCB slab so the component remains the subject. */
  boardInitiallyVisible?: boolean;
}): ModelScene {
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
  const [showBoard, setShowBoard] = useState(boardInitiallyVisible);
  const [placementMode, setPlacementMode] = useState<PlacementMode>("auto");
  const [placementAssessment, setPlacementAssessment] =
    useState<PlacementAssessment | null>(null);
  const [selectedPlacementSource, setSelectedPlacementSource] = useState<"kicad" | "model">(
    "model",
  );
  const renderableLand = usableLandPattern(land);
  const landRef = useRef<LandPattern | null>(renderableLand);
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
  // Both snapshots are refreshed in a LAYOUT effect, not during render.
  //
  // Render must stay pure - React can replay or discard a render, and a render-phase write leaks
  // out of work that never commits. Layout is the right phase rather than a passive effect because
  // it keeps the ORIGINAL timing exactly: the only reader is the mount effect's async body, which
  // resumes in a microtask after the commit, and layout effects are flushed synchronously inside
  // that commit. A passive effect can be scheduled after those microtasks, which would have let the
  // newly mounted scene be handed a snapshot one commit old.
  //
  // Declared BEFORE the mount effect so, on a commit that changes both, the snapshot is already
  // current when the mount effect starts a fresh import.
  useLayoutEffect(() => {
    landRef.current = renderableLand;
  }, [renderableLand]);
  useLayoutEffect(() => {
    viewerStateRef.current = {
      view,
      showLand,
      renderMode,
      spinning,
      showModel,
      showBoard,
      placementMode,
    };
  }, [view, showLand, renderMode, spinning, showModel, showBoard, placementMode]);

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
        const { mountModelScene } = await import("./threeScene");
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

  const controls: ModelViewerControls = {
    view,
    showModel,
    showLand,
    showBoard,
    renderMode,
    spinning,
    placementMode,
    placementAssessment,
    selectedPlacementSource,
    setView: (mode) => {
      setView(mode);
      sceneRef.current?.setView(mode);
    },
    setRenderMode: (mode) => {
      setRenderMode(mode);
      sceneRef.current?.setRenderMode(mode);
    },
    setPlacementMode: (mode) => {
      setPlacementMode(mode);
      sceneRef.current?.setPlacementMode(mode);
    },
    toggleModel: () => {
      const next = !showModel;
      setShowModel(next);
      sceneRef.current?.setLayers({ model: next });
    },
    togglePads: () => {
      const next = !showLand;
      setShowLand(next);
      // visibility only - the geometry is already built. Rebuilding it here also
      // destroyed and recreated the board every time the pads were toggled.
      sceneRef.current?.setLayers({ pads: next });
    },
    toggleBoard: () => {
      const next = !showBoard;
      setShowBoard(next);
      sceneRef.current?.setLayers({ board: next });
    },
    toggleSpin: () => {
      const next = !spinning;
      // trust the SCENE's answer, not the request: under prefers-reduced-motion it stays off
      const inForce = sceneRef.current?.setSpin(next) ?? next;
      setSpinning(inForce);
    },
    fit: () => sceneRef.current?.fit(),
  };

  return {
    mountRef,
    failed: !!data && failedData === data,
    land: renderableLand,
    controls,
  };
}
