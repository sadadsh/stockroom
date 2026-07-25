/**
 * The three.js GLB canvas, decoupled from where the GLB came from (a committed part or a
 * stock lib_id). Given the fetched GLB bytes plus the query's loading/error state, it
 * mounts the auto-rotating scene and degrades honestly: a 502 (no conversion tooling on
 * this machine) or a WebGL failure shows a plain message, never a blank canvas or a crash.
 * The heavy three.js code is import()ed lazily so it only loads when a 3D view is open.
 */
import { useEffect, useRef, useState } from "react";
import type { ModelSceneHandle, RenderMode, ViewMode } from "../lib/threeScene";
import type { LandPattern } from "../api/client";
import { ApiError } from "../api/client";

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
}: {
  data: ArrayBuffer | undefined;
  isLoading: boolean;
  isError: boolean;
  error?: unknown;
  /** The part's land pattern, when one could be read. Absent simply hides the Board toggle:
   *  a part with no footprint has nothing to check the body against. */
  land?: LandPattern | null;
}) {
  const mountRef = useRef<HTMLDivElement>(null);
  const [renderError, setRenderError] = useState(false);
  const sceneRef = useRef<ModelSceneHandle | null>(null);
  // read inside the mount effect without making the scene remount when the toggle flips
  const showLandRef = useRef(false);
  // Which canonical view is in force. Tracked in React (not read back off the camera) so the
  // control can show the CURRENT answer rather than just issuing commands into the scene.
  const [view, setView] = useState<ViewMode | null>(null);
  const [showLand, setShowLand] = useState(false);
  const [renderMode, setRenderMode] = useState<RenderMode>("realistic");
  const [showModel, setShowModel] = useState(true);
  const [showBoard, setShowBoard] = useState(true);

  useEffect(() => {
    const container = mountRef.current;
    if (!data || !container) return;
    let disposed = false;
    let handle: ModelSceneHandle | null = null;
    void (async () => {
      try {
        const { mountModelScene } = await import("../lib/threeScene");
        if (disposed || !mountRef.current) return;
        handle = mountModelScene(mountRef.current, data, () => {
          // GLTFLoader rejected the GLB asynchronously: show an honest message rather
          // than a blank canvas.
          if (!disposed) setRenderError(true);
        });
        sceneRef.current = handle;
        if (showLandRef.current && land) handle.setLandPattern(land);
      } catch {
        // no WebGL context (or three failed to load): degrade honestly.
        if (!disposed) setRenderError(true);
      }
    })();
    return () => {
      disposed = true;
      sceneRef.current = null;
      handle?.dispose();
    };
  }, [data]);

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
  if (renderError) {
    return <Centered>This device could not render the 3D preview.</Centered>;
  }
  return (
    <div className="relative h-full w-full">
      <div ref={mountRef} className="h-full w-full" data-testid="model-canvas" />
      <div
        data-dev-id="detail.model-layers"
        onClick={(e) => e.stopPropagation()}
        className="pointer-events-auto absolute bottom-2 left-2 flex flex-col items-start gap-1"
      >
        <div className="flex items-center gap-0.5 rounded-control border border-line bg-[var(--c-popover)]/85 p-0.5 backdrop-blur-sm">
          <LayerToggle
            devId="detail.model-show-model"
            label="Model"
            on={showModel}
            hint="Show or hide the 3D body"
            onToggle={() => {
              const next = !showModel;
              setShowModel(next);
              sceneRef.current?.setLayers({ model: next });
            }}
          />
          {land && land.pads.length > 0 ? (
            <>
              <LayerToggle
                devId="detail.model-board"
                label="Pads"
                on={showLand}
                hint="Show the land pattern, to check the body is oriented correctly"
                onToggle={() => {
                  const next = !showLand;
                  setShowLand(next);
                  showLandRef.current = next;
                  sceneRef.current?.setLandPattern(next ? land : null);
                }}
              />
              <LayerToggle
                devId="detail.model-show-board"
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
        <div
          data-dev-id="detail.model-shading"
          className="flex items-center gap-0.5 rounded-control border border-line bg-[var(--c-popover)]/85 p-0.5 backdrop-blur-sm"
        >
          {SHADING.map((r) => (
            <LayerToggle
              key={r.mode}
              devId={r.devId}
              label={r.label}
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
      <ViewControls
        active={view}
        onPick={(mode) => {
          setView(mode);
          sceneRef.current?.setView(mode);
        }}
      />
    </div>
  );
}

// The dev-id is written out in FULL rather than built as `detail.model-view-${mode}`: the parity
// gate scans source text, so an interpolated id is invisible to it and to anyone grepping for it.
const SHADING: { mode: RenderMode; label: string; hint: string; devId: string }[] = [
  {
    mode: "realistic",
    label: "Realistic",
    hint: "The model's own colours, physically lit with ambient occlusion",
    devId: "detail.model-shade-realistic",
  },
  {
    mode: "studio",
    label: "Studio",
    hint: "Flat high-contrast surface with feature lines, easiest for reading shape",
    devId: "detail.model-shade-studio",
  },
  {
    mode: "xray",
    label: "X-Ray",
    hint: "Translucent body, so the pads underneath stay visible",
    devId: "detail.model-shade-xray",
  },
];

/** One quiet toggle. Pressed state carries the answer; `aria-pressed` makes it audible too. */
function LayerToggle({
  devId,
  label,
  on,
  hint,
  onToggle,
}: {
  devId: string;
  label: string;
  on: boolean;
  hint: string;
  onToggle: () => void;
}) {
  return (
    <button
      type="button"
      data-dev-id={devId}
      aria-pressed={on}
      title={hint}
      onClick={(e) => {
        e.stopPropagation();
        onToggle();
      }}
      className={
        "rounded-[2px] px-1.5 py-0.5 text-2xs font-medium transition-[transform,background-color,color] duration-150 ease-out active:scale-[0.97] " +
        "focus-visible:outline focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-acc " +
        (on ? "bg-raise2 text-t1" : "text-t3 hover:bg-[var(--c-hover)] hover:text-t1")
      }
    >
      {label}
    </button>
  );
}

const VIEWS: { mode: ViewMode; label: string; hint: string; devId: string }[] = [
  { mode: "iso", label: "3D", hint: "Three-quarter view", devId: "detail.model-view-iso" },
  {
    mode: "top",
    label: "Top",
    hint: "Looking down at the land pattern",
    devId: "detail.model-view-top",
  },
  {
    mode: "front",
    label: "Front",
    hint: "Side elevation, the way a datasheet draws height",
    devId: "detail.model-view-front",
  },
];

/**
 * The canonical views, as a quiet segmented control resting on the canvas.
 *
 * Deliberately ALWAYS VISIBLE rather than revealed on hover: this is the only affordance telling
 * anyone the viewer has more than one view, and a control nobody can find is the same as a control
 * that does not exist. It stays quiet instead (low contrast until hovered or focused) so it never
 * competes with the render.
 */
function ViewControls({
  active,
  onPick,
}: {
  active: ViewMode | null;
  onPick: (mode: ViewMode) => void;
}) {
  return (
    <div
      data-dev-id="detail.model-views"
      // the whole strip swallows the tile's open-on-click, not just the buttons
      onClick={(e) => e.stopPropagation()}
      className="pointer-events-auto absolute bottom-2 right-2 flex items-center gap-0.5 rounded-control border border-line bg-[var(--c-popover)]/85 p-0.5 backdrop-blur-sm"
    >
      {VIEWS.map((v) => (
        <button
          key={v.mode}
          type="button"
          data-dev-id={v.devId}
          aria-pressed={active === v.mode}
          title={v.hint}
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
            "rounded-[2px] px-1.5 py-0.5 text-2xs font-medium transition-[transform,background-color,color] duration-150 ease-out active:scale-[0.97] " +
            "focus-visible:outline focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-acc " +
            (active === v.mode
              ? "bg-raise2 text-t1"
              : "text-t3 hover:bg-[var(--c-hover)] hover:text-t1")
          }
        >
          {v.label}
        </button>
      ))}
    </div>
  );
}
