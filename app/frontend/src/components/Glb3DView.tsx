/**
 * The three.js GLB canvas, decoupled from where the GLB came from (a committed part or a
 * stock lib_id). Given the fetched GLB bytes plus the query's loading/error state, it
 * mounts the auto-rotating scene and degrades honestly: a 502 (no conversion tooling on
 * this machine) or a WebGL failure shows a plain message, never a blank canvas or a crash.
 * The heavy three.js code is import()ed lazily so it only loads when a 3D view is open.
 *
 * What is left here is the FRAME: the canvas, the four states it can be in, and the settings
 * panel's open/closed question. The scene itself - the handle, the eight values that mirror it and
 * the effects that keep the two in step - lives in `useModelScene`, and every control that can
 * change one of those values lives in `Glb3DViewControls`. Splitting on that line is what stopped
 * the strip and the popover carrying separate copies of the same six toggles.
 */
import { useEffect, useRef, useState } from "react";
import type { LandPattern } from "../api/client";
import { ApiError } from "../api/client";
import { Text, useText } from "../lib/copy";
import { useModelScene, type ModelVisibility } from "../lib/useModelScene";
import { ModelViewerControlSurface, type ModelControlsMode } from "./Glb3DViewControls";

export type { ModelVisibility };

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
  controls = "bar",
  trailing = null,
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
   * How much of the control bar is VISIBLE at rest.
   *
   * `bar` (default) is the historical compact bar: layer icons and the spin toggle on the strip,
   * everything else behind the settings button.
   *
   * `panel` puts EVERY control behind that one button - layers and motion included - so the strip
   * is one icon plus whatever `trailing` supplies. The CAD column asked for this: at ~300px its
   * three previews were stacking a row of switches above each drawing, and the owner read the
   * whole column as noise rather than as three assets. No capability moves: the popover grows
   * Layers and Motion sections to hold what left the strip.
   *
   * `none` renders no strip at all, for a compacted module that is not being inspected.
   */
  controls?: ModelControlsMode;
  /** Placed at the end of the control strip, so a host's own icon shares the one line. */
  trailing?: React.ReactNode;
  /**
   * Reports rendered truth, not file presence. `visible` is emitted only after
   * Three.js has parsed non-empty geometry and computed its first complete frame.
   */
  onVisibilityChange?: (state: ModelVisibility) => void;
}) {
  const scene = useModelScene({ data, land, isLoading, isError, onVisibilityChange });
  const [compactControlsOpen, setCompactControlsOpen] = useState(false);
  const settingsRef = useRef<HTMLDivElement>(null);
  // Resolved above the loading/error returns so the hook order is stable across every branch.
  const modelLoadFailed = useText("model3d.load-failed", "Could not load the 3D model.");
  const canvasLabel = useText(
    "model3d.canvas",
    "3D model inspection canvas. Drag to orbit, scroll to zoom, and press 0 or F to fit.",
  );

  /**
   * Escape closes the settings panel and hands focus back to the button that opened it; a press
   * anywhere else closes it without stealing focus.
   *
   * This was missing while the panel was a corner popover on a large stage, and it is not optional
   * inside the CAD column: the column sits in a modal that also answers Escape, so without
   * `stopPropagation` here one press would close the whole opened component instead of the panel.
   */
  useEffect(() => {
    if (!compactControlsOpen) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      event.stopPropagation();
      setCompactControlsOpen(false);
      settingsRef.current
        ?.querySelector<HTMLButtonElement>("[data-dev-id='detail.model-settings']")
        ?.focus();
    };
    const onPointer = (event: PointerEvent) => {
      const target = event.target as Node | null;
      if (!target || settingsRef.current?.contains(target)) return;
      setCompactControlsOpen(false);
    };
    document.addEventListener("keydown", onKey, true);
    document.addEventListener("pointerdown", onPointer, true);
    return () => {
      document.removeEventListener("keydown", onKey, true);
      document.removeEventListener("pointerdown", onPointer, true);
    };
  }, [compactControlsOpen]);

  if (isLoading) {
    return (
      <Centered>
        <Text id="model3d.loading">Loading 3D model...</Text>
      </Centered>
    );
  }
  if (isError) {
    const err = error instanceof ApiError ? error : null;
    // A 502 carries an honest, specific reason from the backend (tooling not installed,
    // or a WRL model that is not convertible yet) — show it rather than a single guess.
    const message = err?.status === 502 && err.message ? err.message : modelLoadFailed;
    return <Centered>{message}</Centered>;
  }
  if (scene.failed) {
    return (
      <Centered>
        <Text id="model3d.unsupported">This device could not render the 3D preview.</Text>
      </Centered>
    );
  }
  return (
    // `settingsRef` spans the canvas, the strip and the panel: a press inside this viewer (an orbit
    // drag included) leaves the panel alone, and a press anywhere else in the workspace closes it.
    <div ref={settingsRef} className="relative flex h-full w-full flex-col">
      <div
        ref={scene.mountRef}
        data-testid="model-canvas"
        tabIndex={0}
        role="application"
        aria-label={canvasLabel}
        onKeyDown={(event) => {
          if (event.key === "0" || event.key.toLowerCase() === "f") {
            event.preventDefault();
            scene.controls.fit();
          }
        }}
        className="relative min-h-0 w-full flex-1 outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-acc"
      />
      {!compact && showViews ? <div aria-hidden="true" className="h-[82px] flex-none" /> : null}
      <ModelViewerControlSurface
        controls={scene.controls}
        land={scene.land}
        compact={compact}
        mode={controls}
        showViews={showViews}
        showShading={showShading}
        trailing={trailing}
        settingsOpen={compactControlsOpen}
        onSettingsOpen={setCompactControlsOpen}
      />
    </div>
  );
}
