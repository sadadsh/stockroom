import { useCallback, useRef, useState } from "react";
import { useDesignStudio } from "../../design-studio/DesignStudioProvider";
import { useDevMode } from "../../lib/devMode";
import type { StudioMode } from "../../lib/devMode";
import { useCopyFormatter, useText } from "../../lib/copy";
import { useTheme } from "../../lib/theme";
import { Button } from "../primitives";
import {
  RESPONSIVE_VIEWPORT_PRESETS,
  type StudioViewport,
} from "../../design-studio/responsiveViewports";
import { ValueSlider } from "./ValueSlider";
import { useEscapeDismiss } from "../../lib/useEscapeDismiss";
import { downloadDesignHandoff } from "../../design-studio/designHandoff";

interface DesignStudioToolbarProps {
  mode: StudioMode;
  onModeChange: (mode: StudioMode) => void;
  presentation: boolean;
  onPresentationChange: (presentation: boolean) => void;
  viewport: StudioViewport;
  onViewportChange: (viewport: StudioViewport) => void;
  customViewportWidth: number;
  onCustomViewportWidthChange: (width: number) => void;
  zoom: number;
  onZoomChange: (zoom: number) => void;
  grid: boolean;
  onGridChange: (grid: boolean) => void;
  gridSize: number;
  onGridSizeChange: (gridSize: number) => void;
  snap: boolean;
  onSnapChange: (snap: boolean) => void;
  onDeveloperOpen?: () => void;
  onClose: () => void;
}

const MODES: readonly StudioMode[] = ["preview", "edit"];

function titleCase(value: string): string {
  return value.charAt(0).toUpperCase() + value.slice(1);
}

export function DesignStudioToolbar({
  mode,
  onModeChange,
  presentation,
  onPresentationChange,
  viewport,
  onViewportChange,
  customViewportWidth,
  onCustomViewportWidthChange,
  zoom,
  onZoomChange,
  grid,
  onGridChange,
  gridSize,
  onGridSizeChange,
  snap,
  onSnapChange,
  onDeveloperOpen,
  onClose,
}: DesignStudioToolbarProps) {
  const [viewOpen, setViewOpen] = useState(false);
  const viewAnchorRef = useRef<HTMLDivElement | null>(null);
  const closeView = useCallback(() => {
    setViewOpen(false);
    window.setTimeout(() => viewAnchorRef.current?.querySelector<HTMLButtonElement>("button")?.focus(), 0);
  }, []);
  useEscapeDismiss(viewOpen, closeView);
  const studio = useDesignStudio();
  const dev = useDevMode();
  const { theme, toggle: toggleTheme } = useTheme();
  const fixturePreview = studio.activeScenario !== null;
  const stockroomLabel = useText("design-studio.breadcrumb.stockroom", "Stockroom");
  const studioLabel = useText("design-studio.title", "Design Studio");
  const realDataLabel = useText("design-studio.real-data", "Real Data");
  const fixtureDataLabel = useText("design-studio.fixture-data", "Preview Data");
  const breadcrumbLabel = useText("design-studio.breadcrumb", "Design Studio Breadcrumb");
  const modeLabel = useText("design-studio.mode", "Studio Mode");
  const darkLabel = useText("design-studio.theme.dark", "Dark");
  const lightLabel = useText("design-studio.theme.light", "Light");
  const switchThemeLabel = useText("design-studio.theme.switch", "Switch Preview Theme");
  const viewportLabel = useText("design-studio.viewport", "Viewport");
  const customViewportLabel = useText("design-studio.viewport.custom-width", "Custom Viewport Width");
  const zoomLabel = useText("design-studio.zoom", "Zoom");
  const fitLabel = useText("design-studio.zoom.fit", "Fit");
  const gridLabel = useText("design-studio.grid", "Grid");
  const editGridControlsLabel = useText("design-studio.edit-grid-controls", "Edit Grid Controls");
  const gridSizeLabel = useText("design-studio.grid-size", "Grid And Snap Size");
  const snapLabel = useText("design-studio.snap", "Snap");
  const undoLabel = useText("design-studio.undo", "Undo");
  const redoLabel = useText("design-studio.redo", "Redo");
  const viewLabel = useText("design-studio.view", "View");
  const developerLabel = useText("design-studio.developer", "Developer Tools");
  const exportLabel = useText("design-studio.export", "Export Design");
  const applyLabel = useText("design-studio.apply-local", "Apply To This PC");
  const applyFixtureTitle = useText("design-studio.apply-local.fixture-help", "Return To Real Data To Apply This Draft");
  const applyTitle = useText("design-studio.apply-local.help", "Apply This Draft On This PC");
  const appliedStatusLabel = useText("design-studio.applied-status", "Applied Design Status");
  const appliedLabel = useCopyFormatter(
    "design-studio.applied-this-pc",
    "Applied · {revision}",
  );
  const draftOnlyLabel = useText("design-studio.draft-only", "Draft");
  const draftChangedLabel = useText("design-studio.draft-changed", "Draft Changes");
  const commitFailedLabel = useText("design-studio.commit-failed", "Apply Failed");
  const applyingLabel = useText("design-studio.applying", "Applying...");
  const committedLabel = useText("design-studio.committed", "Applied");
  const presentationLabel = useText("design-studio.presentation", "Presentation");
  const closeLabel = useText("design-studio.close", "Exit");

  return (
    <header data-design-studio-chrome="true" className="relative z-30 flex min-h-11 flex-none items-center gap-2 bg-band px-2.5 py-1.5 shadow-card">
      <Button aria-label={closeLabel} onClick={onClose}>{closeLabel}</Button>

      <div role="group" className="flex items-center overflow-hidden rounded-control bg-raise" aria-label={modeLabel}>
        {MODES.map((item) => (
          <button
            key={item}
            type="button"
            aria-pressed={mode === item}
            onClick={() => onModeChange(item)}
            className={
              "h-7 px-3 text-xs font-semibold " +
              (mode === item ? "bg-control-pressed text-t1" : "bg-raise text-t2 hover:bg-control-hover")
            }
          >
            {titleCase(item)}
          </button>
        ))}
      </div>

      <div className="min-w-0 flex-1 truncate text-center text-xs text-t2" aria-label={breadcrumbLabel}>
        <span className="sr-only">{stockroomLabel} / {studioLabel} / </span>
        <span className="font-semibold text-t1">{studio.activeScenario?.title ?? realDataLabel}</span>
        {fixturePreview ? <span className="ml-2 rounded-control bg-warn/15 px-1.5 py-0.5 font-semibold text-warn-text">{fixtureDataLabel}</span> : null}
      </div>

      <Button onClick={toggleTheme} title={switchThemeLabel}>
        {theme === "dark" ? darkLabel : lightLabel}
      </Button>
      <Button disabled={!dev.canUndo} onClick={dev.undo}>{undoLabel}</Button>
      <Button disabled={!dev.canRedo} onClick={dev.redo}>{redoLabel}</Button>

      <div ref={viewAnchorRef} className="relative">
        <Button aria-expanded={viewOpen} onClick={() => setViewOpen((open) => !open)}>{viewLabel}</Button>
        {viewOpen ? (
          <div className="absolute right-0 top-full z-50 mt-2 w-72 rounded-card bg-popover p-3 shadow-pop" aria-label={viewLabel}>
            <div className="grid grid-cols-2 gap-3">
              <label className="text-xs text-t2">
                <span>{viewportLabel}</span>
                <select aria-label={viewportLabel} value={viewport} onChange={(event) => onViewportChange(event.target.value as StudioViewport)} className="mt-1 h-7 w-full rounded-control bg-field px-2 text-xs text-t1">
                  {RESPONSIVE_VIEWPORT_PRESETS.map((preset) => <option key={preset.id} value={preset.id}>{preset.label}</option>)}
                </select>
              </label>
              <label className="text-xs text-t2">
                <span>{zoomLabel}</span>
                <select aria-label={zoomLabel} value={zoom} onChange={(event) => onZoomChange(Number(event.target.value))} className="mt-1 h-7 w-full rounded-control bg-field px-2 text-xs text-t1">
                  {[0, 50, 75, 100, 125].map((value) => <option key={value} value={value}>{value === 0 ? fitLabel : `${value}%`}</option>)}
                </select>
              </label>
            </div>
            {viewport === "custom" ? <ValueSlider ariaLabel={customViewportLabel} min={320} max={3840} step={1} value={customViewportWidth} unit="px" onChange={onCustomViewportWidthChange} className="mt-3 w-full" /> : null}
            <div role="group" aria-label={editGridControlsLabel} className="mt-3 rounded-control bg-field/50 p-2">
              <div className="mb-2 flex items-center gap-2">
                <Button aria-pressed={grid} onClick={() => onGridChange(!grid)}>{gridLabel}</Button>
                <Button aria-pressed={snap} onClick={() => onSnapChange(!snap)}>{snapLabel}</Button>
              </div>
              <span className="sr-only">{gridSizeLabel}</span>
              <ValueSlider ariaLabel={gridSizeLabel} min={1} max={64} step={1} value={gridSize} unit="px" onChange={onGridSizeChange} className="w-full" />
            </div>
            <div className="mt-3 flex items-center gap-2">
              <Button aria-pressed={presentation} onClick={() => onPresentationChange(!presentation)}>{presentationLabel}</Button>
            </div>
            <button
              type="button"
              disabled={fixturePreview}
              onClick={() => {
                downloadDesignHandoff({
                  document: studio.document,
                  theme,
                  activeScenarioId: studio.activeScenarioId,
                  appliedRevision: studio.appliedRevision,
                });
                closeView();
              }}
              className="mt-3 w-full rounded-control px-2 py-1.5 text-left text-xs text-t2 hover:bg-raise2 hover:text-t1 disabled:text-t5"
            >
              {exportLabel}
            </button>
            {onDeveloperOpen ? <button type="button" onClick={() => { setViewOpen(false); onDeveloperOpen(); }} className="mt-3 w-full rounded-control px-2 py-1.5 text-left text-xs text-t2 hover:bg-raise2 hover:text-t1">{developerLabel}</button> : null}
          </div>
        ) : null}
      </div>

      <span
        aria-label={appliedStatusLabel}
        aria-live="polite"
        className={
          "max-w-48 truncate text-xs " +
          (studio.appliedState === "error" ? "text-err" : "text-t3")
        }
      >
        {studio.appliedState === "error"
          ? commitFailedLabel
          : studio.appliedMatchesDraft && studio.appliedRevision
            ? appliedLabel({ revision: studio.appliedRevision.slice(0, 8) })
            : studio.appliedRevision
              ? draftChangedLabel
              : draftOnlyLabel}
      </span>
      <Button
        variant="accent"
        disabled={
          fixturePreview
          || studio.appliedState === "loading"
          || studio.appliedState === "applying"
          || studio.appliedMatchesDraft
        }
        title={fixturePreview ? applyFixtureTitle : applyTitle}
        onClick={() => void studio.applyLocal()}
      >
        {studio.appliedState === "applying"
          ? applyingLabel
          : studio.appliedMatchesDraft
            ? committedLabel
            : applyLabel}
      </Button>
    </header>
  );
}
