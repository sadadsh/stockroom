import { useCallback, useEffect, useRef, useState, type CSSProperties, type KeyboardEvent as ReactKeyboardEvent, type PointerEvent as ReactPointerEvent, type ReactNode } from "react";
import { useDesignStudio } from "../../design-studio/DesignStudioProvider";
import { useDevMode } from "../../lib/devMode";
import { useText } from "../../lib/copy";
import { openEscapeLayerCount } from "../../lib/useEscapeDismiss";
import { flushPendingUiPrefs, readPref, writePref } from "../../lib/uiPrefs";
import { DevPanel } from "../DevPanel";
import { DesignStudioToolbar } from "./DesignStudioToolbar";
import {
  RESPONSIVE_VIEWPORT_PRESETS,
  type StudioViewport,
} from "../../design-studio/responsiveViewports";
import { LayersHierarchyPanel } from "./LayersHierarchyPanel";
import { ArrangePreferencesProvider } from "./ArrangeSurface";
import { ScenarioCatalog } from "./ScenarioCatalog";
import { PREVIEW_EFFECT_BLOCKED_EVENT, type PreviewEffectError } from "../../design-studio/previewEffects";
import { useToast } from "../../lib/toast";
import { DEFAULT_DESIGN_GRID_SIZE, finiteDesignGridSize } from "../../design-studio/gridSize";
import { DesignPreviewBoundary } from "./DesignPreviewBoundary";
import { InspectorPanel } from "./InspectorPanel";
import { Icon } from "../Icon";

const LEFT_WIDTH_KEY = "stockroom.design-studio.left-width";
const RIGHT_WIDTH_KEY = "stockroom.design-studio.right-width";
const LAST_SCENARIO_KEY = "stockroom.design-studio.last-scenario";
const VIEWPORT_KEY = "stockroom.design-studio.viewport";
const CUSTOM_VIEWPORT_WIDTH_KEY = "stockroom.design-studio.custom-viewport-width";
const MODE_KEY = "stockroom.design-studio.mode";
const ZOOM_KEY = "stockroom.design-studio.zoom";
const GRID_KEY = "stockroom.design-studio.grid";
const GRID_SIZE_KEY = "stockroom.design-studio.grid-size";
const SNAP_KEY = "stockroom.design-studio.snap";
const PRESENTATION_KEY = "stockroom.design-studio.presentation";
const MIN_PANEL_WIDTH = 210;
const MAX_PANEL_WIDTH = 480;

function parseBoolean(raw: string): boolean | undefined {
  if (raw === "true") return true;
  if (raw === "false") return false;
  return undefined;
}

function parsePanelWidth(raw: string): number | undefined {
  const value = Number(raw);
  return Number.isFinite(value) && value >= MIN_PANEL_WIDTH && value <= MAX_PANEL_WIDTH
    ? value
    : undefined;
}

function parseString(raw: string): string | undefined {
  return raw || undefined;
}

function parseNumber(raw: string): number | undefined {
  const value = Number(raw);
  return Number.isFinite(value) ? value : undefined;
}

function parseViewport(raw: string): StudioViewport | undefined {
  return RESPONSIVE_VIEWPORT_PRESETS.some((preset) => preset.id === raw) ? raw as StudioViewport : undefined;
}

function parseMode(raw: string): "preview" | "edit" | undefined {
  if (raw === "preview" || raw === "browse") return "preview";
  if (raw === "edit" || raw === "inspect" || raw === "arrange") return "edit";
  return undefined;
}

function clampPanelWidth(value: number): number {
  return Math.max(MIN_PANEL_WIDTH, Math.min(MAX_PANEL_WIDTH, value));
}

function focusStudioEntry(): void {
  window.setTimeout(() => {
    document.querySelector<HTMLButtonElement>("[data-design-studio-entry]")?.focus();
  }, 0);
}

function PanelResizer({
  label,
  value,
  direction,
  onChange,
}: {
  label: string;
  value: number;
  direction: 1 | -1;
  onChange: (value: number) => void;
}) {
  const resizeLabel = useText("design-studio.panel.resize", "Resize");
  const resize = (delta: number) => onChange(clampPanelWidth(value + delta * direction));
  return (
    <button
      data-design-studio-chrome="true"
      type="button"
      role="separator"
      aria-label={label}
      aria-orientation="vertical"
      aria-valuemin={MIN_PANEL_WIDTH}
      aria-valuemax={MAX_PANEL_WIDTH}
      aria-valuenow={value}
      title={label}
      onClick={() => resize(16)}
      onKeyDown={(event) => {
        if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
        event.preventDefault();
        resize(event.key === "ArrowRight" ? 16 : -16);
      }}
      className="design-studio-resizer w-1.5 flex-none cursor-col-resize bg-line/40 hover:bg-acc focus-visible:outline focus-visible:outline-2 focus-visible:outline-acc"
    >
      <span className="sr-only">{resizeLabel}</span>
    </button>
  );
}

export function DesignStudioShell({ children }: { children: ReactNode }) {
  const studio = useDesignStudio();
  const dev = useDevMode();
  const { toast } = useToast();
  const [presentation, setPresentation] = useState(() => readPref("design_studio_presentation", PRESENTATION_KEY, parseBoolean, false));
  const [viewport, setViewport] = useState<StudioViewport>(() => readPref("design_studio_viewport", VIEWPORT_KEY, parseViewport, "desktop-1366"));
  const [customViewportWidth, setCustomViewportWidth] = useState(() => readPref("design_studio_custom_viewport_width", CUSTOM_VIEWPORT_WIDTH_KEY, parseNumber, 1366));
  const [zoom, setZoom] = useState(() => readPref("design_studio_zoom", ZOOM_KEY, parseNumber, 0));
  const [grid, setGrid] = useState(() => readPref("design_studio_grid", GRID_KEY, parseBoolean, false));
  const [gridSize, setGridSize] = useState(() => readPref(
    "design_studio_grid_size",
    GRID_SIZE_KEY,
    (raw) => finiteDesignGridSize(raw),
    DEFAULT_DESIGN_GRID_SIZE,
  ));
  const [snap, setSnap] = useState(() => readPref("design_studio_snap", SNAP_KEY, parseBoolean, true));
  const [lastScenario] = useState(() => readPref("design_studio_last_scenario", LAST_SCENARIO_KEY, parseString, "global.real-data"));
  const [preferredMode] = useState(() => readPref("design_studio_mode", MODE_KEY, parseMode, "preview"));
  const previewRegionRef = useRef<HTMLDivElement | null>(null);
  const [previewRegionWidth, setPreviewRegionWidth] = useState(0);
  const closingRef = useRef(false);
  const restoredOpenRef = useRef(false);
  const panStart = useRef<{ x: number; y: number; left: number; top: number } | null>(null);
  const [leftDrawer, setLeftDrawer] = useState<"screens" | "layers" | null>(null);
  const [developerOpen, setDeveloperOpen] = useState(false);
  const [leftWidth, setLeftWidth] = useState(() =>
    readPref("design_studio_left_width", LEFT_WIDTH_KEY, parsePanelWidth, 270),
  );
  const [rightWidth, setRightWidth] = useState(() =>
    readPref("design_studio_right_width", RIGHT_WIDTH_KEY, parsePanelWidth, 340),
  );
  const screensLabel = useText("design-studio.panel.screens", "Screens");
  const layersLabel = useText("design-studio.panel.layers", "Layers");
  const closeDrawerLabel = useText("design-studio.panel.close", "Close Drawer");
  const previewLabel = useText("design-studio.preview", "Stockroom Preview");
  const panCueLabel = useText("design-studio.pan-cue", "Drag canvas or press arrow controls to pan");
  const fitLabel = useText("design-studio.zoom.fit", "Fit");
  const inspectorLabel = useText("design-studio.panel.inspector", "Inspector");
  const developerLabel = useText("design-studio.developer", "Developer Tools");

  const mode = dev.studioMode;
  const changeMode = useCallback((next: "preview" | "edit") => {
    dev.setStudioMode(next);
    writePref("design_studio_mode", next, MODE_KEY);
  }, [dev.setStudioMode]);

  useEffect(() => {
    const showBlockedEffect = (event: Event) => {
      toast((event as CustomEvent<PreviewEffectError>).detail.message, "err");
    };
    window.addEventListener(PREVIEW_EFFECT_BLOCKED_EVENT, showBlockedEffect);
    return () => window.removeEventListener(PREVIEW_EFFECT_BLOCKED_EVENT, showBlockedEffect);
  }, [toast]);

  const close = useCallback(() => {
    closingRef.current = true;
    changeMode("preview");
    setPresentation(false);
    studio.close();
    focusStudioEntry();
  }, [changeMode, studio]);
  const changePresentation = useCallback((next: boolean) => {
    if (next) dev.setStudioMode("preview");
    setPresentation(next);
    writePref("design_studio_presentation", next, PRESENTATION_KEY);
  }, [dev.setStudioMode]);

  useEffect(() => {
    if (!studio.enabled) {
      restoredOpenRef.current = false;
      closingRef.current = false;
      return;
    }
    if (restoredOpenRef.current) return;
    restoredOpenRef.current = true;
    dev.setStudioMode(preferredMode);
    if (lastScenario !== "global.real-data") {
      void studio.activateScenario(lastScenario).catch(() => undefined);
    }
  }, [dev.setStudioMode, lastScenario, preferredMode, studio]);

  useEffect(() => {
    if (!studio.enabled || closingRef.current) return;
    writePref("design_studio_last_scenario", studio.activeScenario?.id ?? "global.real-data", LAST_SCENARIO_KEY);
  }, [studio.activeScenario, studio.enabled]);

  useEffect(() => {
    if (!studio.enabled) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      if (openEscapeLayerCount() > 0) return;
      event.preventDefault();
      if (mode !== "preview") changeMode("preview");
      else close();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [changeMode, close, mode, studio.enabled]);

  useEffect(() => {
    if (studio.enabled) return;
    if (mode !== "preview") changeMode("preview");
    if (presentation) setPresentation(false);
  }, [changeMode, mode, presentation, studio.enabled]);

  useEffect(() => {
    if (studio.activeScenario === null) void flushPendingUiPrefs();
  }, [studio.activeScenario]);

  useEffect(() => {
    if (!studio.enabled) return;
    const region = previewRegionRef.current;
    if (!region) return;
    const measure = () => setPreviewRegionWidth(region.clientWidth);
    measure();
    const observer = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(measure);
    observer?.observe(region);
    window.addEventListener("resize", measure);
    return () => {
      observer?.disconnect();
      window.removeEventListener("resize", measure);
    };
  }, [studio.enabled]);

  const resizeLeft = (width: number) => {
    setLeftWidth(width);
    writePref("design_studio_left_width", width, LEFT_WIDTH_KEY);
  };
  const resizeRight = (width: number) => {
    setRightWidth(width);
    writePref("design_studio_right_width", width, RIGHT_WIDTH_KEY);
  };
  const presetWidth = RESPONSIVE_VIEWPORT_PRESETS.find((preset) => preset.id === viewport)?.width;
  const viewportWidth = presetWidth ?? Math.min(3840, Math.max(320, customViewportWidth || 320));
  const fitScale = zoom === 0
    ? Math.min(1, Math.max(0.1, ((previewRegionWidth || viewportWidth) - 24) / viewportWidth))
    : zoom / 100;
  const previewStyle: CSSProperties = {
    width: `${viewportWidth}px`,
    transform: `scale(${fitScale})`,
    transformOrigin: "top center",
  };
  const previewRegionStyle = {
    "--design-studio-grid-size": `${gridSize}px`,
  } as CSSProperties;

  const changeViewport = (next: StudioViewport) => {
    setViewport(next);
    writePref("design_studio_viewport", next, VIEWPORT_KEY);
  };
  const changeCustomViewportWidth = (next: number) => {
    setCustomViewportWidth(next);
    writePref("design_studio_custom_viewport_width", next, CUSTOM_VIEWPORT_WIDTH_KEY);
  };
  const changeZoom = (next: number) => {
    setZoom(next);
    writePref("design_studio_zoom", next, ZOOM_KEY);
  };
  const changeGrid = (next: boolean) => {
    setGrid(next);
    writePref("design_studio_grid", next, GRID_KEY);
  };
  const changeGridSize = (next: number) => {
    const finite = finiteDesignGridSize(next, gridSize);
    setGridSize(finite);
    writePref("design_studio_grid_size", finite, GRID_SIZE_KEY);
  };
  const changeSnap = (next: boolean) => {
    setSnap(next);
    writePref("design_studio_snap", next, SNAP_KEY);
  };
  const panByKey = (event: ReactKeyboardEvent<HTMLDivElement>) => {
    if (event.target !== event.currentTarget) return;
    const delta = 80;
    if (event.key === "ArrowLeft") previewRegionRef.current!.scrollLeft -= delta;
    else if (event.key === "ArrowRight") previewRegionRef.current!.scrollLeft += delta;
    else if (event.key === "ArrowUp") previewRegionRef.current!.scrollTop -= delta;
    else if (event.key === "ArrowDown") previewRegionRef.current!.scrollTop += delta;
    else return;
    event.preventDefault();
  };
  const beginPan = (event: ReactPointerEvent<HTMLDivElement>) => {
    const region = previewRegionRef.current;
    const target = event.target;
    if (
      !region ||
      event.button !== 0 ||
      !(target instanceof Element) ||
      target.closest("button, a, input, select, textarea, [contenteditable='true'], [role='button'], [role='slider'], [role='separator'], [data-design-control]")
    ) return;
    panStart.current = { x: event.clientX, y: event.clientY, left: region.scrollLeft, top: region.scrollTop };
    region.setPointerCapture?.(event.pointerId);
  };
  const movePan = (event: ReactPointerEvent<HTMLDivElement>) => {
    const region = previewRegionRef.current;
    const start = panStart.current;
    if (!region || !start) return;
    region.scrollLeft = start.left - (event.clientX - start.x);
    region.scrollTop = start.top - (event.clientY - start.y);
  };

  return (
    <div
      className={studio.enabled ? "design-studio-shell fixed inset-0 z-[190] flex flex-col overflow-hidden bg-canvas text-t1" : "contents"}
      data-studio-mode={studio.enabled ? mode : undefined}
      data-scenario-id={studio.activeScenario?.id ?? "global.real-data"}
      data-preview-live-product-requests={studio.activeScenario ? "0" : undefined}
    >
      {studio.enabled ? (
        <DesignStudioToolbar
          mode={mode}
          onModeChange={changeMode}
          presentation={presentation}
          onPresentationChange={changePresentation}
          viewport={viewport}
          onViewportChange={changeViewport}
          customViewportWidth={customViewportWidth}
          onCustomViewportWidthChange={changeCustomViewportWidth}
          zoom={zoom}
          onZoomChange={changeZoom}
          grid={grid}
          onGridChange={changeGrid}
          gridSize={gridSize}
          onGridSizeChange={changeGridSize}
          snap={snap}
          onSnapChange={changeSnap}
          onDeveloperOpen={() => setDeveloperOpen(true)}
          onClose={close}
        />
      ) : null}
      <div className={studio.enabled ? "flex min-h-0 flex-1" : "contents"}>
        {studio.enabled && !presentation ? (
          <nav data-design-studio-chrome="true" aria-label="Design Studio Drawers" className="flex w-11 flex-none flex-col gap-1 bg-band p-1.5">
            <button
              type="button"
              aria-label={screensLabel}
              aria-pressed={leftDrawer === "screens"}
              onClick={() => setLeftDrawer((open) => open === "screens" ? null : "screens")}
              title={screensLabel}
              className="grid h-9 place-items-center rounded-control text-t2 hover:bg-control-hover hover:text-t1 aria-pressed:bg-control-pressed aria-pressed:text-t1"
            >
              <Icon id="nav.components" className="h-4 w-4" />
            </button>
            <button
              type="button"
              aria-label={layersLabel}
              aria-pressed={leftDrawer === "layers"}
              onClick={() => setLeftDrawer((open) => open === "layers" ? null : "layers")}
              title={layersLabel}
              className="grid h-9 place-items-center rounded-control text-t2 hover:bg-control-hover hover:text-t1 aria-pressed:bg-control-pressed aria-pressed:text-t1"
            >
              <Icon id="finder.filter" className="h-4 w-4" />
            </button>
          </nav>
        ) : null}

        {studio.enabled && !presentation && leftDrawer ? (
          <>
            <aside
              data-design-studio-chrome="true"
              aria-label={leftDrawer === "screens" ? screensLabel : layersLabel}
              className="flex min-h-0 flex-none flex-col bg-surface shadow-card"
              style={{ width: leftWidth }}
            >
              <div className="flex h-9 items-center justify-between px-3">
                <strong className="text-xs">{leftDrawer === "screens" ? screensLabel : layersLabel}</strong>
                <button
                  type="button"
                  aria-label={closeDrawerLabel}
                  onClick={() => setLeftDrawer(null)}
                  className="rounded-control px-2 py-1 text-xs text-t2 hover:bg-control-hover hover:text-t1"
                >
                  ×
                </button>
              </div>
              <DesignPreviewBoundary resetKey={`${leftDrawer}:${studio.activeScenario?.id ?? "real-data"}`} onRecover={() => setLeftDrawer(null)}>
                {leftDrawer === "screens" ? <ScenarioCatalog /> : <LayersHierarchyPanel />}
              </DesignPreviewBoundary>
            </aside>
            <PanelResizer
              label="Resize Screens And States Panel"
              value={leftWidth}
              direction={1}
              onChange={resizeLeft}
            />
          </>
        ) : null}

        <div
          ref={previewRegionRef}
          tabIndex={studio.enabled ? 0 : undefined}
          onKeyDown={studio.enabled ? panByKey : undefined}
          onPointerDown={studio.enabled ? beginPan : undefined}
          onPointerMove={studio.enabled ? movePan : undefined}
          onPointerUp={studio.enabled ? () => { panStart.current = null; } : undefined}
          role={studio.enabled ? "region" : undefined}
          aria-label={studio.enabled ? previewLabel : undefined}
          data-grid={studio.enabled ? (grid ? "visible" : "hidden") : undefined}
          data-grid-size={studio.enabled ? gridSize : undefined}
          data-snap={studio.enabled ? (snap ? "on" : "off") : undefined}
          style={studio.enabled ? previewRegionStyle : undefined}
          className={
            studio.enabled
              ? "min-w-0 flex-1 overflow-auto bg-field p-2"
              : "contents"
          }
        >
          <div
            data-design-product-root="true"
            className={studio.enabled ? "relative mx-auto min-h-full overflow-hidden border border-line bg-surface shadow-pop" : "contents"}
            style={studio.enabled ? previewStyle : undefined}
          >
            <DesignPreviewBoundary resetKey={JSON.stringify(dev.draft)} onRecover={dev.undo}>
              <ArrangePreferencesProvider snap={snap} gridSize={gridSize}>{children}</ArrangePreferencesProvider>
            </DesignPreviewBoundary>
            {studio.enabled && grid ? <div aria-hidden="true" data-design-grid-overlay="true" className="design-studio-preview-grid-overlay pointer-events-none absolute inset-0 z-[180]" /> : null}
          </div>
          {studio.enabled ? (
            <div data-design-studio-chrome="true" className="sticky bottom-2 left-2 z-10 w-fit rounded-control border border-line bg-popover/90 px-2 py-1 text-2xs text-t2" data-dev-id="design.pan-cue">
              {zoom === 0 ? `${fitLabel} · ` : ""}{panCueLabel}
            </div>
          ) : null}
        </div>

        {studio.enabled && !presentation && (developerOpen || mode === "edit") ? (
          <>
            <PanelResizer
              label="Resize Inspector Panel"
              value={rightWidth}
              direction={-1}
              onChange={resizeRight}
            />
            <aside
              data-design-studio-chrome="true"
              aria-label={developerOpen ? developerLabel : inspectorLabel}
              className="flex min-h-0 flex-none flex-col bg-popover shadow-card"
              style={{ width: rightWidth }}
            >
              <div className="flex h-9 items-center justify-between px-3">
                <strong className="text-xs">{developerOpen ? developerLabel : inspectorLabel}</strong>
                <button
                  type="button"
                  aria-label={closeDrawerLabel}
                  onClick={() => developerOpen ? setDeveloperOpen(false) : changeMode("preview")}
                  className="rounded-control px-2 py-1 text-xs text-t2 hover:bg-control-hover hover:text-t1"
                >
                  ×
                </button>
              </div>
              <DesignPreviewBoundary resetKey={`${dev.selectedDevId ?? "none"}:${JSON.stringify(dev.draft)}`} onRecover={dev.undo}>
                {developerOpen
                  ? <DevPanel fixturePreview={studio.activeScenario !== null} onClose={() => setDeveloperOpen(false)} />
                  : <div className="min-h-0 flex-1 overflow-y-auto"><InspectorPanel /></div>}
              </DesignPreviewBoundary>
            </aside>
          </>
        ) : null}
      </div>
    </div>
  );
}
