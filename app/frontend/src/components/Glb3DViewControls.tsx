/**
 * The 3D viewer's control surface: the strip beneath the canvas, the panel its settings button
 * opens, and the small pressed-state controls both are built from.
 */
import type { ModelViewerControls } from "../lib/useModelScene";
import type { LandPattern } from "../api/client";
import type { PlacementAssessment } from "../lib/placementAssessment";
import type { PlacementMode, RenderMode, ViewMode } from "../lib/threeScene";
import { Text, useCopyFormatter, useText } from "../lib/copy";
import { Icon } from "./Icon";
import type { IconId } from "../lib/iconRegistry";

/**
 * How much of the control surface is VISIBLE at rest. `bar` is the historical compact strip,
 * `panel` puts every control behind the one settings button, and `none` draws no strip at all.
 */
export type ModelControlsMode = "bar" | "panel" | "none";


/**
 * Everything the 3D viewer can be told to do, as a surface rather than as an overlay.
 *
 * The controls sit in a RESERVED BAR beneath the canvas, not floating over it.
 *
 * They used to be two chip stacks pinned bottom-left plus the view cluster bottom-right, which
 * was fine only while the stage was 540px tall and mostly empty. The moment the stage took the
 * landscape proportion a part actually has (2026-07-25, the composition slice), those stacks
 * landed ON the model - measured, and the exact reason an earlier attempt at the aspect was
 * reverted. Overlaying controls on the subject is a bet that the subject will stay small, and
 * that bet is what the camera-fit work exists to lose.
 *
 * The two surfaces below are the two answers to "how much is visible at rest": the STRIP, which is
 * whatever the host has room for, and the PANEL, which holds whatever the strip does not. They are
 * separate components because they are reached differently - one is always there, the other is
 * opened - and because between them they would otherwise be one 360-line body whose two halves
 * never render together in the full-size viewer.
 *
 * Both read and write ONE `ModelViewerControls` handed down from the scene hook, so they cannot
 * disagree about what a toggle does - which they could, and did, while each carried its own copy
 * of the six state-plus-scene pairs.
 */
export function ModelViewerControlSurface({
  controls,
  land,
  compact,
  mode,
  showViews,
  showShading,
  trailing,
  settingsOpen,
  onSettingsOpen,
}: {
  controls: ModelViewerControls;
  land: LandPattern | null;
  compact: boolean;
  mode: ModelControlsMode;
  showViews: boolean;
  showShading: boolean;
  trailing?: React.ReactNode;
  settingsOpen: boolean;
  onSettingsOpen: (next: boolean) => void;
}) {
  return (
    <>
      {mode === "none" ? null : (
        <ModelControlStrip
          controls={controls}
          land={land}
          compact={compact}
          panelMode={mode === "panel"}
          showViews={showViews}
          showShading={showShading}
          trailing={trailing}
          settingsOpen={settingsOpen}
          onSettingsOpen={onSettingsOpen}
        />
      )}
      {(compact || mode === "panel") && settingsOpen ? (
        <ModelSettingsPanel
          controls={controls}
          land={land}
          panelMode={mode === "panel"}
          showShading={showShading}
        />
      ) : null}
    </>
  );
}

/**
 * The strip that is always there: whatever this host has room to show without being asked, plus
 * the one button that opens everything else.
 *
 * What is on it is decided by the host, not by the control: the full inspection stage carries
 * labelled Layers / Appearance / Placement / Motion / View groups, the narrow tile carries layer
 * icons and a settings button, and panel mode carries the settings button alone. No capability is
 * lost between them - the panel below grows the sections that leave here.
 */
function ModelControlStrip({
  controls,
  land,
  compact,
  panelMode,
  showViews,
  showShading,
  trailing,
  settingsOpen,
  onSettingsOpen,
}: {
  controls: ModelViewerControls;
  land: LandPattern | null;
  compact: boolean;
  panelMode: boolean;
  showViews: boolean;
  showShading: boolean;
  trailing?: React.ReactNode;
  settingsOpen: boolean;
  onSettingsOpen: (next: boolean) => void;
}) {
  const layersLabel = useText("model3d.layers", "Layers");
  const appearanceLabel = useText("model3d.appearance", "Appearance");
  const motionLabel = useText("model3d.motion", "Motion");
  const settingsLabel = useText("model3d.settings", "3D view settings");
  const settingsHint = useText(
    "model3d.settings-hint",
    "View, appearance, placement, and fit settings",
  );
  const cameraViewLabel = useText("model3d.camera-view", "Camera view");
  const fitHint = useText("model3d.fit-hint", "Frame the whole visible model (0 or F)");
  const hasPads = !!land && land.pads.length > 0;

  return (
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
        (panelMode
          ? // The same 24px strip the symbol and land-pattern previews use, so the three
            // modules read as one column rather than three differently-chromed tiles.
            "min-h-[24px] flex-none gap-1 px-2 py-0.5"
          : compact
            ? "h-[38px] flex-none justify-between gap-2 border-t border-line2 bg-band px-2 py-1"
            : "absolute bottom-3 left-1/2 z-10 w-max max-w-[calc(100%-24px)] -translate-x-1/2 gap-0 overflow-x-auto rounded-card border border-line2 bg-popover p-2 shadow-pop")
      }
    >
    {/* Compact has only layer icons here. The full inspection stage has room for explicit
        Layers / Appearance / Placement groups, so the user does not have to decode one heap.
        Panel mode has NONE of it on the strip: it all moves into the popover below. */}
    {panelMode ? null : (
    <div
      data-dev-id="detail.model-layers"
      className={"flex min-w-0 items-center " + (compact ? "gap-1" : "gap-0")}
    >
      <div
        className={compact ? "flex items-center gap-1.5" : "flex flex-col items-start gap-1 pr-3"}
        role="group"
        aria-label={layersLabel}
      >
        {!compact ? (
          <ControlLabel>
            <Text id="model3d.layers">Layers</Text>
          </ControlLabel>
        ) : null}
        <div className="flex items-center gap-0.5 rounded-control border border-line2 bg-field p-0.5">
        <LayerToggle
          devId="detail.model-show-model"
          icon="layer.model"
          compact={compact}
          label="Model"
          on={controls.showModel}
          hint="Show or hide the 3D body"
          onToggle={controls.toggleModel}
        />
        {hasPads ? (
          <>
            <LayerToggle
              devId="detail.model-board"
          icon="layer.pads"
          compact={compact}
              label="Pads"
              on={controls.showLand}
              hint="Show the land pattern, to check the body is oriented correctly"
              onToggle={controls.togglePads}
            />
            <LayerToggle
              devId="detail.model-show-board"
          icon="layer.board"
          compact={compact}
              label="PCB"
              on={controls.showBoard}
              hint="Show the board the pads sit on"
              onToggle={controls.toggleBoard}
            />
          </>
        ) : null}
        </div>
      </div>
      {showShading && !compact ? (
      <div
        data-dev-id="detail.model-shading"
        role="group"
        aria-label={appearanceLabel}
        // NO border-l. On a bar that wraps, a left border on a flex child becomes a stray vertical
        // tick floating at the start of the new row - visible in the owner's real shot as a glitch
        // beside "Realistic". Grouping is carried by the gap instead, which cannot wrap wrongly.
        className="flex flex-col items-start gap-1 border-l border-line pl-3 pr-3"
      >
        <ControlLabel>
          <Text id="model3d.appearance">Appearance</Text>
        </ControlLabel>
        <div className="flex items-center gap-0.5 rounded-control border border-line2 bg-field p-0.5">
        {SHADING.map((r) => (
          <LayerToggle
            key={r.mode}
            devId={r.devId}
            label={r.label}
            icon={r.icon}
            compact={compact}
            on={controls.renderMode === r.mode}
            hint={r.hint}
            onToggle={() => controls.setRenderMode(r.mode)}
          />
        ))}
        </div>
      </div>
      ) : null}
      {showViews && !compact && land?.model_placement ? (
        <PlacementControls
          active={controls.placementMode}
          assessment={controls.placementAssessment}
          selectedSource={controls.selectedPlacementSource}
          onPick={controls.setPlacementMode}
        />
      ) : null}
    </div>
    )}
    {showViews && !panelMode ? (
      <div className={"flex items-center " + (compact ? "gap-1" : "gap-0")}>
        <div
          className={
            compact
              ? "flex items-center gap-1.5"
              : "flex flex-col items-start gap-1 border-l border-line pl-3 pr-3"
          }
          role="group"
          aria-label={motionLabel}
        >
          {!compact ? (
            <ControlLabel>
              <Text id="model3d.motion">Motion</Text>
            </ControlLabel>
          ) : null}
          <div className="flex items-center rounded-control border border-line2 bg-field p-0.5">
            <LayerToggle
              devId="detail.model-spin"
              icon="action.refresh"
              compact={compact}
              label="Auto rotate"
              on={controls.spinning}
              hint="Stop or resume automatic rotation"
              onToggle={controls.toggleSpin}
            />
          </div>
        </div>
        {compact ? (
          <button
            type="button"
            data-dev-id="detail.model-settings"
            aria-label={settingsLabel}
            aria-expanded={settingsOpen}
            title={settingsHint}
            onClick={() => onSettingsOpen(!settingsOpen)}
            className={
              "flex h-[30px] w-[30px] items-center justify-center rounded-control border border-line2 transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-focus " +
              (settingsOpen
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
            aria-label={cameraViewLabel}
          >
            <ControlLabel>
              <Text id="model3d.view">View</Text>
            </ControlLabel>
            <div className="flex items-center gap-1">
              <ViewControls active={controls.view} onPick={controls.setView} />
              <button
                type="button"
                onClick={controls.fit}
                title={fitHint}
                className="inline-flex min-h-[32px] items-center rounded-control border border-line2 bg-field px-2.5 text-xs font-semibold text-t2 transition-[background-color,color] hover:bg-raise hover:text-t1 focus-visible:outline focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-focus"
              >
                <Text id="model3d.fit">Fit</Text>
              </button>
            </div>
          </div>
        )}
      </div>
    ) : null}
    {panelMode ? (
      <>
        {/* ONE control on the strip. Everything the viewer can do is inside what it opens. */}
        <button
          type="button"
          data-dev-id="detail.model-settings"
          aria-label={settingsLabel}
          aria-expanded={settingsOpen}
          title={settingsLabel}
          onClick={() => onSettingsOpen(!settingsOpen)}
          className={
            "flex h-[20px] w-[20px] flex-none items-center justify-center rounded-control " +
            "hover:bg-control-hover hover:text-t1 focus-visible:outline focus-visible:outline-2 " +
            "focus-visible:outline-offset-1 focus-visible:outline-focus " +
            (settingsOpen ? "bg-selected text-t1" : "text-t3")
          }
        >
          <Icon id="action.settings" className="h-3.5 w-3.5" />
        </button>
        {trailing ? (
          <span className="ml-auto flex flex-none items-center gap-1">{trailing}</span>
        ) : null}
      </>
    ) : trailing ? (
      <span className="ml-1 flex flex-none items-center gap-1">{trailing}</span>
    ) : null}
    </div>
  );
}

/**
 * The panel the settings button opens: everything the strip had no room for.
 *
 * Its contents are the complement of the strip's, which is why it takes the same `panelMode` and
 * `showShading` questions: in panel mode the layers and the idle spin moved off the strip and are
 * grown here, and in the narrow tile they did not. Nothing became unreachable in either case -
 * these are the same controls, one surface further in.
 */
function ModelSettingsPanel({
  controls,
  land,
  panelMode,
  showShading,
}: {
  controls: ModelViewerControls;
  land: LandPattern | null;
  panelMode: boolean;
  showShading: boolean;
}) {
  const layersLabel = useText("model3d.layers", "Layers");
  const appearanceLabel = useText("model3d.appearance", "Appearance");
  const motionLabel = useText("model3d.motion", "Motion");
  const viewLabel = useText("model3d.view", "View");
  const placementLabel = useText("model3d.placement", "Placement");
  const fitModelLabel = useText("model3d.fit-model", "Fit model");
  const fitHint = useText("model3d.fit-hint", "Frame the whole visible model (0 or F)");
  const hasPads = !!land && land.pads.length > 0;

  return (
    <div
      data-dev-id="detail.model-settings-popover"
      onClick={(event) => event.stopPropagation()}
      className={
        "pointer-events-auto absolute z-20 rounded-card border border-line2 bg-popover p-2 shadow-pop " +
        (panelMode ? "bottom-6 left-2 w-[15rem]" : "bottom-10 right-2 w-[270px]")
      }
    >
      {/* Panel mode holds the two groups that left the strip. Nothing became unreachable:
          the layers and the idle spin are the same controls, one surface further in. */}
      {panelMode ? (
        <>
          <ControlSection label={layersLabel}>
            <div className="flex items-center gap-0.5 rounded-control border border-line2 bg-field p-0.5">
              <LayerToggle
                devId="detail.model-show-model"
                icon="layer.model"
                compact
                label="Model"
                on={controls.showModel}
                hint="Show or hide the 3D body"
                onToggle={controls.toggleModel}
              />
              {hasPads ? (
                <>
                  <LayerToggle
                    devId="detail.model-board"
                    icon="layer.pads"
                    compact
                    label="Pads"
                    on={controls.showLand}
                    hint="Show the land pattern, to check the body is oriented correctly"
                    onToggle={controls.togglePads}
                  />
                  <LayerToggle
                    devId="detail.model-show-board"
                    icon="layer.board"
                    compact
                    label="PCB"
                    on={controls.showBoard}
                    hint="Show the board the pads sit on"
                    onToggle={controls.toggleBoard}
                  />
                </>
              ) : null}
            </div>
          </ControlSection>
          <ControlSection label={motionLabel}>
            <div className="flex items-center rounded-control border border-line2 bg-field p-0.5">
              <LayerToggle
                devId="detail.model-spin"
                icon="action.refresh"
                compact
                label="Auto rotate"
                on={controls.spinning}
                hint="Stop or resume automatic rotation"
                onToggle={controls.toggleSpin}
              />
            </div>
          </ControlSection>
        </>
      ) : null}
      <ControlSection label={viewLabel}>
        <div className="flex items-center gap-1">
          <ViewControls active={controls.view} compact onPick={controls.setView} />
          <button
            type="button"
            onClick={controls.fit}
            aria-label={fitModelLabel}
            title={fitHint}
            className="flex h-[32px] min-w-[42px] items-center justify-center rounded-control border border-line2 bg-field px-2 text-xs font-semibold text-t2 hover:bg-raise hover:text-t1 focus-visible:outline focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-focus"
          >
            <Text id="model3d.fit">Fit</Text>
          </button>
        </div>
      </ControlSection>
      {showShading ? (
        <ControlSection label={appearanceLabel}>
          <div className="flex items-center gap-0.5 rounded-control border border-line2 bg-field p-0.5">
            {SHADING.map((item) => (
              <LayerToggle
                key={item.mode}
                devId={item.devId}
                label={item.label}
                icon={item.icon}
                compact
                on={controls.renderMode === item.mode}
                hint={item.hint}
                onToggle={() => controls.setRenderMode(item.mode)}
              />
            ))}
          </div>
        </ControlSection>
      ) : null}
      {land?.model_placement ? (
        <ControlSection label={placementLabel}>
          <PlacementControls
            active={controls.placementMode}
            assessment={controls.placementAssessment}
            selectedSource={controls.selectedPlacementSource}
            showLabel={false}
            onPick={controls.setPlacementMode}
          />
        </ControlSection>
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
  icon: IconId;
}[] = [
  {
    mode: "auto",
    label: "Auto",
    hint: "Use KiCad placement when it passes conservative sanity checks; otherwise show the model frame",
    icon: "view.placement-auto",
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
  const issueText = assessment?.issues.join(". ") ?? "";
  const groupLabel = useText("model3d.placement", "Placement");
  // The frame note is a sentence with a value in it, so it is a formatter rather than a fragment
  // concatenated at the call site: the word order belongs in the string, not in the JavaScript.
  const frameNote = useCopyFormatter(
    "model3d.placement-frame",
    "Auto is showing the {source} frame.",
  );
  const suspectFrameNote = useCopyFormatter(
    "model3d.placement-frame-flagged",
    "{issues}. Auto is showing the {source} frame.",
  );
  const checkLabel = useText("model3d.placement-flagged", "Check");
  const sourceLabel = useText("model3d.placement-from-source", "Source");
  const modelLabel = useText("model3d.placement-from-model", "Model");
  return (
    <div
      className={
        showLabel
          ? "flex flex-col items-start gap-1 border-l border-line pl-3 pr-3"
          : "flex w-full flex-col items-start gap-1.5"
      }
      role="group"
      aria-label={groupLabel}
    >
      {showLabel ? (
        <ControlLabel>
          <Text id="model3d.placement">Placement</Text>
        </ControlLabel>
      ) : null}
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
                "inline-flex min-h-[32px] items-center gap-1.5 rounded-control px-2.5 text-xs font-semibold transition-[background-color,color] " +
                "focus-visible:outline focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-focus " +
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
              ? suspectFrameNote({ issues: issueText, source: selectedSource })
              : frameNote({ source: selectedSource })
          }
          className={
            "flex min-h-[32px] items-center rounded-control px-2 text-xs font-semibold " +
            (suspect ? "bg-warn/15 text-warn" : "bg-ok/15 text-ok-text")
          }
        >
          {suspect ? checkLabel : selectedSource === "kicad" ? sourceLabel : modelLabel}
        </span>
      </div>
    </div>
  );
}

// The dev-id is written out in FULL rather than built as `detail.model-view-${mode}`: the parity
// gate scans source text, so an interpolated id is invisible to it and to anyone grepping for it.
const SHADING: { mode: RenderMode; label: string; hint: string; devId: string; icon: IconId }[] = [
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
  icon?: IconId;
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
        "rounded-control font-semibold transition-[background-color,color] duration-100 ease-out " +
        "focus-visible:outline focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-focus " +
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

const VIEWS: { mode: ViewMode; label: string; hint: string; devId: string; icon: IconId }[] = [
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
            "rounded-control font-semibold transition-[background-color,color] duration-100 ease-out " +
            "focus-visible:outline focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-focus " +
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
