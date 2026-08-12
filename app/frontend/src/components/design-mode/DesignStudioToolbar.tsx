import { useDesignStudio } from "../../design-studio/DesignStudioProvider";
import { useDevMode } from "../../lib/devMode";
import type { StudioMode } from "../../lib/devMode";
import { useText } from "../../lib/copy";
import { useTheme } from "../../lib/theme";
import { Button } from "../primitives";
import {
  finiteViewportWidth,
  RESPONSIVE_VIEWPORT_PRESETS,
  type StudioViewport,
} from "../../design-studio/responsiveViewports";

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
  snap: boolean;
  onSnapChange: (snap: boolean) => void;
  onClose: () => void;
}

const MODES: readonly StudioMode[] = ["browse", "inspect", "arrange"];

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
  snap,
  onSnapChange,
  onClose,
}: DesignStudioToolbarProps) {
  const studio = useDesignStudio();
  const dev = useDevMode();
  const { theme, toggle: toggleTheme } = useTheme();
  const fixturePreview = studio.activeScenario !== null;
  const stockroomLabel = useText("design-studio.breadcrumb.stockroom", "Stockroom");
  const studioLabel = useText("design-studio.title", "Design Studio");
  const realDataLabel = useText("design-studio.real-data", "Real Data");
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
  const snapLabel = useText("design-studio.snap", "Snap");
  const undoLabel = useText("design-studio.undo", "Undo");
  const redoLabel = useText("design-studio.redo", "Redo");
  const resetLabel = useText("design-studio.reset", "Reset");
  const fixtureLabel = useText("design-studio.fixture-preview", "Fixture Preview");
  const validationLabel = useText("design-studio.validation", "Preview Validation Status");
  const makeDefaultLabel = useText("design-studio.make-default", "Make App Default");
  const makeDefaultFixtureTitle = useText("design-studio.make-default.fixture-help", "Return To Real Data To Make App Default");
  const makeDefaultTitle = useText("design-studio.make-default.help", "Save This Design To Source");
  const promotionStatusLabel = useText("design-studio.promotion-status", "Source Promotion Status");
  const presentationLabel = useText("design-studio.presentation", "Presentation Mode");
  const closeLabel = useText("design-studio.close", "Close Design Studio");

  return (
    <header className="flex min-h-[38px] flex-none items-center gap-2 border-b border-line bg-band px-2 py-1">
      <div className="mr-1 min-w-0 text-xs text-t2" aria-label={breadcrumbLabel}>
        <span className="font-semibold text-t1">{stockroomLabel}</span>
        <span className="px-1.5 text-t3">/</span>
        <span>{studioLabel}</span>
        <span className="px-1.5 text-t3">/</span>
        <span className="truncate text-t1">{studio.activeScenario?.title ?? realDataLabel}</span>
      </div>

      <div className="flex items-center overflow-hidden rounded-control border border-line-dark" aria-label={modeLabel}>
        {MODES.map((item) => (
          <button
            key={item}
            type="button"
            aria-pressed={mode === item}
            onClick={() => onModeChange(item)}
            className={
              "h-[22px] border-r border-line-dark px-2 text-xs font-semibold last:border-r-0 " +
              (mode === item ? "bg-control-pressed text-t1" : "bg-raise text-t2 hover:bg-control-hover")
            }
          >
            {titleCase(item)}
          </button>
        ))}
      </div>

      <Button small onClick={toggleTheme} title={switchThemeLabel}>
        {theme === "dark" ? darkLabel : lightLabel}
      </Button>

      <label className="flex items-center gap-1 text-xs text-t2">
        <span>{viewportLabel}</span>
        <select
          aria-label={viewportLabel}
          value={viewport}
          onChange={(event) => onViewportChange(event.target.value as StudioViewport)}
          className="h-[22px] rounded-control border border-line bg-field px-1.5 text-xs text-t1"
        >
          {RESPONSIVE_VIEWPORT_PRESETS.map((preset) => (
            <option key={preset.id} value={preset.id}>{preset.label}</option>
          ))}
        </select>
      </label>
      {viewport === "custom" ? (
        <input
          type="number"
          aria-label={customViewportLabel}
          min={320}
          max={3840}
          step={1}
          value={customViewportWidth}
          onChange={(event) =>
            onCustomViewportWidthChange(
              finiteViewportWidth(event.target.value, customViewportWidth),
            )
          }
          className="h-[22px] w-20 rounded-control border border-line bg-field px-1.5 text-xs text-t1"
        />
      ) : null}

      <label className="flex items-center gap-1 text-xs text-t2">
        <span>{zoomLabel}</span>
        <select
          aria-label={zoomLabel}
          value={zoom}
          onChange={(event) => onZoomChange(Number(event.target.value))}
          className="h-[22px] rounded-control border border-line bg-field px-1.5 text-xs text-t1"
        >
          {[0, 50, 75, 100, 125].map((value) => (
            <option key={value} value={value}>{value === 0 ? fitLabel : `${value}%`}</option>
          ))}
        </select>
      </label>

      <Button small aria-pressed={grid} onClick={() => onGridChange(!grid)}>{gridLabel}</Button>
      <Button small aria-pressed={snap} onClick={() => onSnapChange(!snap)}>{snapLabel}</Button>

      <span className="mx-1 h-5 w-px bg-line" aria-hidden />
      <Button small disabled={!dev.canUndo} onClick={dev.undo}>{undoLabel}</Button>
      <Button small disabled={!dev.canRedo} onClick={dev.redo}>{redoLabel}</Button>
      <Button small onClick={dev.resetAll}>{resetLabel}</Button>

      <span
        className={"ml-auto text-xs font-semibold " + (fixturePreview ? "text-warn" : "text-ok-text")}
        aria-label={validationLabel}
      >
        {fixturePreview ? fixtureLabel : realDataLabel}
      </span>
      <span
        aria-label={promotionStatusLabel}
        title={studio.promotionStatus.message}
        className={
          "max-w-64 truncate text-xs " +
          (studio.promotionStatus.state === "ready" || studio.promotionStatus.state === "success"
            ? "text-ok-text"
            : studio.promotionStatus.state === "checking" || studio.promotionStatus.state === "running"
              ? "text-t3"
              : "text-warn")
        }
      >
        {studio.promotionStatus.message}
      </span>
      <Button
        small
        variant="accent"
        disabled={fixturePreview || studio.promotionStatus.state !== "ready"}
        title={fixturePreview ? makeDefaultFixtureTitle : makeDefaultTitle}
        onClick={() => void studio.promotePersonalDesign("Promote personal Stockroom design")}
      >
        {makeDefaultLabel}
      </Button>
      <Button
        small
        aria-pressed={presentation}
        onClick={() => onPresentationChange(!presentation)}
      >
        {presentationLabel}
      </Button>
      <Button small aria-label={closeLabel} onClick={onClose}>{closeLabel}</Button>
    </header>
  );
}
