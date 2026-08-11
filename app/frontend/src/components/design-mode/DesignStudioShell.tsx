import { useCallback, useEffect, useState, type CSSProperties, type ReactNode } from "react";
import { useDesignStudio } from "../../design-studio/DesignStudioProvider";
import { useDevMode } from "../../lib/devMode";
import { useText } from "../../lib/copy";
import { openModalCount } from "../../lib/useModalDismiss";
import { flushPendingUiPrefs, readPref, writePref } from "../../lib/uiPrefs";
import { DevPanel } from "../DevPanel";
import { DesignStudioToolbar, type StudioViewport } from "./DesignStudioToolbar";
import { LayersHierarchyPanel } from "./LayersHierarchyPanel";
import { ScenarioCatalog } from "./ScenarioCatalog";

const LEFT_COLLAPSED_KEY = "stockroom.design-studio.left-collapsed";
const RIGHT_COLLAPSED_KEY = "stockroom.design-studio.right-collapsed";
const LEFT_WIDTH_KEY = "stockroom.design-studio.left-width";
const RIGHT_WIDTH_KEY = "stockroom.design-studio.right-width";
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
      className="design-studio-resizer flex w-[18px] flex-none items-center justify-center border-x border-line bg-band text-2xs text-t3 hover:bg-control-hover hover:text-t1 focus-visible:outline focus-visible:outline-2 focus-visible:outline-acc"
    >
      <span className="[writing-mode:vertical-rl]">{resizeLabel}</span>
    </button>
  );
}

export function DesignStudioShell({ children }: { children: ReactNode }) {
  const studio = useDesignStudio();
  const dev = useDevMode();
  const [presentation, setPresentation] = useState(false);
  const [viewport, setViewport] = useState<StudioViewport>("fit");
  const [zoom, setZoom] = useState(100);
  const [grid, setGrid] = useState(false);
  const [snap, setSnap] = useState(true);
  const [leftCollapsed, setLeftCollapsed] = useState(() =>
    readPref("design_studio_left_collapsed", LEFT_COLLAPSED_KEY, parseBoolean, false),
  );
  const [rightCollapsed, setRightCollapsed] = useState(() =>
    readPref("design_studio_right_collapsed", RIGHT_COLLAPSED_KEY, parseBoolean, false),
  );
  const [leftWidth, setLeftWidth] = useState(() =>
    readPref("design_studio_left_width", LEFT_WIDTH_KEY, parsePanelWidth, 270),
  );
  const [rightWidth, setRightWidth] = useState(() =>
    readPref("design_studio_right_width", RIGHT_WIDTH_KEY, parsePanelWidth, 340),
  );
  const screensLabel = useText("design-studio.panel.screens", "Screens And States");
  const hideScreensLabel = useText("design-studio.panel.screens-hide", "Hide Screens And States");
  const showScreensLabel = useText("design-studio.panel.screens-show", "Show Screens And States");
  const previewLabel = useText("design-studio.preview", "Stockroom Preview");
  const inspectorLabel = useText("design-studio.panel.inspector", "Inspector");
  const hideInspectorLabel = useText("design-studio.panel.inspector-hide", "Hide Inspector");
  const showInspectorLabel = useText("design-studio.panel.inspector-show", "Show Inspector");

  const mode = dev.studioMode;
  const changeMode = dev.setStudioMode;

  const close = useCallback(() => {
    changeMode("browse");
    setPresentation(false);
    studio.close();
    focusStudioEntry();
  }, [changeMode, studio]);
  const changePresentation = useCallback((next: boolean) => {
    if (next) changeMode("browse");
    setPresentation(next);
  }, [changeMode]);

  useEffect(() => {
    if (!studio.enabled) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      if (openModalCount() > 0) return;
      event.preventDefault();
      if (mode !== "browse") changeMode("browse");
      else close();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [changeMode, close, mode, studio.enabled]);

  useEffect(() => {
    if (studio.enabled) return;
    if (mode !== "browse") changeMode("browse");
    if (presentation) setPresentation(false);
  }, [changeMode, mode, presentation, studio.enabled]);

  useEffect(() => {
    if (studio.activeScenario === null) void flushPendingUiPrefs();
  }, [studio.activeScenario]);

  const setLeftPanelCollapsed = (collapsed: boolean) => {
    setLeftCollapsed(collapsed);
    writePref("design_studio_left_collapsed", collapsed, LEFT_COLLAPSED_KEY);
  };
  const setRightPanelCollapsed = (collapsed: boolean) => {
    setRightCollapsed(collapsed);
    writePref("design_studio_right_collapsed", collapsed, RIGHT_COLLAPSED_KEY);
  };
  const resizeLeft = (width: number) => {
    setLeftWidth(width);
    writePref("design_studio_left_width", width, LEFT_WIDTH_KEY);
  };
  const resizeRight = (width: number) => {
    setRightWidth(width);
    writePref("design_studio_right_width", width, RIGHT_WIDTH_KEY);
  };
  const viewportWidth = viewport === "desktop" ? 1440 : viewport === "tablet" ? 900 : viewport === "mobile" ? 430 : undefined;
  const previewStyle: CSSProperties = {
    width: viewportWidth ? `${viewportWidth}px` : "100%",
    transform: `scale(${zoom / 100})`,
    transformOrigin: "top center",
  };

  return (
    <div
      className={studio.enabled ? "fixed inset-0 z-[190] flex flex-col overflow-hidden bg-canvas text-t1" : "contents"}
      data-studio-mode={studio.enabled ? mode : undefined}
    >
      {studio.enabled ? (
        <DesignStudioToolbar
          mode={mode}
          onModeChange={changeMode}
          presentation={presentation}
          onPresentationChange={changePresentation}
          viewport={viewport}
          onViewportChange={setViewport}
          zoom={zoom}
          onZoomChange={setZoom}
          grid={grid}
          onGridChange={setGrid}
          snap={snap}
          onSnapChange={setSnap}
          onClose={close}
        />
      ) : null}
      <div className={studio.enabled ? "flex min-h-0 flex-1" : "contents"}>
        {studio.enabled && !presentation && !leftCollapsed ? (
          <>
            <aside
              aria-label={screensLabel}
              className="flex min-h-0 flex-none flex-col border-r border-line bg-surface"
              style={{ width: leftWidth }}
            >
              <div className="flex items-center justify-end border-b border-line bg-band px-2 py-1">
                <button
                  type="button"
                  onClick={() => setLeftPanelCollapsed(true)}
                  className="rounded-control px-2 py-0.5 text-xs text-t2 hover:bg-control-hover hover:text-t1"
                >
                  {hideScreensLabel}
                </button>
              </div>
              <ScenarioCatalog />
              <LayersHierarchyPanel />
            </aside>
            <PanelResizer
              label="Resize Screens And States Panel"
              value={leftWidth}
              direction={1}
              onChange={resizeLeft}
            />
          </>
        ) : studio.enabled && !presentation ? (
          <button
            type="button"
            aria-label={showScreensLabel}
            onClick={() => setLeftPanelCollapsed(false)}
            className="w-[26px] flex-none border-r border-line bg-band text-2xs text-t2 [writing-mode:vertical-rl] hover:bg-control-hover hover:text-t1"
          >
            {screensLabel}
          </button>
        ) : null}

        <div
          role={studio.enabled ? "region" : undefined}
          aria-label={studio.enabled ? previewLabel : undefined}
          data-grid={studio.enabled ? (grid ? "visible" : "hidden") : undefined}
          data-snap={studio.enabled ? (snap ? "on" : "off") : undefined}
          className={
            studio.enabled
              ? "min-w-0 flex-1 overflow-auto bg-field p-2 " +
                (grid ? "design-studio-preview-grid" : "")
              : "contents"
          }
        >
          <div
            className={studio.enabled ? "mx-auto min-h-full overflow-hidden border border-line bg-surface shadow-pop" : "contents"}
            style={studio.enabled ? previewStyle : undefined}
          >
            {children}
          </div>
        </div>

        {studio.enabled && !presentation && !rightCollapsed ? (
          <>
            <PanelResizer
              label="Resize Inspector Panel"
              value={rightWidth}
              direction={-1}
              onChange={resizeRight}
            />
            <aside
              aria-label={inspectorLabel}
              className="flex min-h-0 flex-none flex-col border-l border-line bg-popover"
              style={{ width: rightWidth }}
            >
              <div className="flex items-center justify-end border-b border-line bg-band px-2 py-1">
                <button
                  type="button"
                  onClick={() => setRightPanelCollapsed(true)}
                  className="rounded-control px-2 py-0.5 text-xs text-t2 hover:bg-control-hover hover:text-t1"
                >
                  {hideInspectorLabel}
                </button>
              </div>
              <DevPanel fixturePreview={studio.activeScenario !== null} onClose={close} />
            </aside>
          </>
        ) : studio.enabled && !presentation ? (
          <button
            type="button"
            aria-label={showInspectorLabel}
            onClick={() => setRightPanelCollapsed(false)}
            className="w-[26px] flex-none border-l border-line bg-band text-2xs text-t2 [writing-mode:vertical-rl] hover:bg-control-hover hover:text-t1"
          >
            {inspectorLabel}
          </button>
        ) : null}
      </div>
    </div>
  );
}
