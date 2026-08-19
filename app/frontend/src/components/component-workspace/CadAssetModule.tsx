/**
 * One CAD asset: the symbol, the land pattern, or the 3D body.
 *
 * A module names what the asset IS, what state it is in, and where it came from - in that order
 * of weight, on ONE dense line. What it deliberately does NOT name is the EDA application the
 * file happens to be readable by. A person inspecting a component is asking whether the footprint
 * is right, not which of two tools can open it; putting `KiCad` and `Altium` in the module header
 * turned every asset into a compatibility report and pushed the actual asset off the line.
 *
 * A collapsed module keeps its header AND a small preview. Collapsing must never remove the third
 * of the CAD set that happens not to be in focus, because "is the symbol consistent with the
 * footprint" is one question and it cannot be answered by flipping between two views.
 *
 * The provider is stated here only when it DIFFERS from the column's preferred source. Repeating
 * the same provider sentence under all three assets is what pushed the asset off its own header
 * line; the column says where the set came from once, and a module speaks up when it disagrees.
 */
import type {
  CadPreferenceView,
  RepresentationKind,
  RepresentationView,
} from "../../api/dossierTypes";
import { useLandPattern, usePreviewGlb, useSymbolGeometry } from "../../api/queries";
import { componentRepresentationDevId } from "../../lib/componentDevIds";
import { Text, useText } from "../../lib/copy";
import { CubeArt, FootprintArt, SymbolArt } from "../icons";
import { Icon } from "../Icon";
import { Glb3DView } from "../Glb3DView";
import { StatusText, WarnMark } from "../primitives";
import {
  AssetControlStrip,
  AssetOptionsButton,
  MaximizeButton,
  MeasureButton,
  type AssetOption,
} from "./AssetOptions";
import { assetFormat } from "./cadAssetSet";
import { assetOverride } from "./cadPreference";
import { footprintEvidence, symbolEvidence } from "./cadEvidence";
import {
  FootprintPreview,
  useFootprintLayers,
  type FootprintLayer,
} from "./FootprintPreview";
import {
  SymbolPreview,
  useSymbolLayers,
  type SymbolLayer,
} from "./SymbolPreview";
import { cadAssetStatus, cadStatusTone, type CadAssetStatus, type CadMeasured } from "./workspaceStatus";

/** What each asset is CALLED. Asset kinds, not file formats and not applications. */
const REPRESENTATION_LABEL: Record<RepresentationKind, string> = {
  symbol: "Symbol",
  footprint: "Footprint",
  model: "3D Model",
};

const REPRESENTATION_COPY_ID: Record<RepresentationKind, string> = {
  symbol: "component-browser.asset-symbol",
  footprint: "component-browser.asset-footprint",
  model: "component-browser.asset-model",
};

function assetArt(kind: RepresentationKind) {
  if (kind === "symbol") return <SymbolArt />;
  if (kind === "footprint") return <FootprintArt />;
  return <CubeArt />;
}

/**
 * One honest absence mark, sized from the owner's dark-theme design rather than by overriding the
 * three asset-art ids globally. Attached files that are loading or unreadable keep their own art;
 * a question mark means only that no file exists.
 */
function MissingAssetArt({ kind: _kind }: { kind: RepresentationKind }) {
  return (
    <span
      data-dev-id="component-browser.asset-missing-art"
      aria-hidden="true"
      className="flex items-center justify-center"
    >
      <Icon
        id="status.cad-missing"
        className="h-14 w-14 opacity-40"
      />
    </span>
  );
}

/**
 * The DRAWING SHEET, for all three assets, in either tag.
 *
 * The symbol and the land pattern paint it themselves; the 3D canvas is transparent and inherits
 * it, so the three previews sit on one surface instead of two sheets and a recessed input well.
 * Theme-aware, which is the whole point: this used to be near-white under the symbol and the
 * footprint in dark theme, brighter than anything else in the workspace including the part number.
 *
 * `w-full` because the compact stage is a <button>, which is inline-block and would otherwise
 * shrink to its contents where the expanded <div> fills the column.
 */
function previewStageClass(expanded: boolean): string {
  return (
    "flex w-full items-center justify-center overflow-hidden border-y border-line " +
    "bg-technical focus-visible:outline focus-visible:outline-2 " +
    "focus-visible:-outline-offset-2 focus-visible:outline-focus " +
    (expanded ? "min-h-[40px] flex-1" : "h-[56px] min-h-[32px] flex-none")
  );
}

export function CadAssetModule({
  componentId,
  kind,
  view,
  preference,
  expectedPins,
  expectedPitch,
  expanded,
  focused,
  onToggle,
  onOpenFullPreview,
  focusRef,
}: {
  componentId: string;
  kind: RepresentationKind;
  view: RepresentationView;
  preference: CadPreferenceView;
  /** The component's own pin count, so a terminal count has a second side to be compared to. */
  expectedPins: number | null;
  expectedPitch: number | null;
  /** Expanded carries the full preview and its controls; collapsed keeps a compact one. */
  expanded: boolean;
  /**
   * This module, and only this module, is the one the column is focused on.
   *
   * Distinct from `expanded`, which is true for all three in the resting `all` layout. The measured
   * evidence footer is gated on THIS rather than on `expanded`, because at rest the column was
   * carrying three lines of counts nobody had asked for - `2 pins · No duplicates`,
   * `2 pads · 0.96 mm pitch · Courtyard present · 1.80 x 0.84 mm` - under three drawings, in a
   * ~300px column. A validation FAILURE is not gated: see `AssetIssue`.
   */
  focused: boolean;
  onToggle: () => void;
  onOpenFullPreview: () => void;
  focusRef?: (node: HTMLElement | null) => void;
}) {
  const label = REPRESENTATION_LABEL[kind];
  const override = assetOverride(preference, kind);
  // What the header actually DOES, which is not expand or collapse: at rest all three modules are
  // expanded, and pressing one focuses it - the other two reduce to compact previews and this one
  // states the evidence it measured. The two words were describing a state the control does not have.
  const collapseLabel = useText("component-browser.asset-collapse", "Show All Three");
  const focusLabel = useText("component-browser.asset-expand", "Focus This Asset");
  const fullPreview = useText("component-browser.asset-full-preview", "Open Full Preview");
  const attached = view.tools.some((tool) => tool.present);

  const preview = usePreviewData(componentId, kind, attached);
  const measured = measurementsFor(kind, preview, expectedPins);
  const status = cadAssetStatus(view, measured);

  return (
    <section
      ref={focusRef}
      data-dev-id={componentRepresentationDevId(componentId, kind)}
      data-dev-role="component-browser.cad-asset" data-design-cad-kind={kind === "model" ? "model3d" : kind} data-design-cad-target={`cad.${kind === "model" ? "model3d" : kind}`}
      data-asset-kind={kind}
      data-expanded={expanded ? "true" : "false"}
      data-status={status}
      aria-label={label}
      className={
        "flex min-h-0 flex-col border-b border-line last:border-b-0 " +
        (expanded ? "flex-1" : "flex-none")
      }
    >
      {/* One dense line: name, state, and the source ONLY when it differs from the column's. */}
      <h3 className="flex items-center gap-2 px-2 py-1">
        <button
          type="button"
          data-dev-id="component-browser.asset-header"
          aria-expanded={expanded}
          title={focused ? collapseLabel : focusLabel}
          onClick={onToggle}
          className={
            "ui-section-title flex-none rounded-control focus-visible:outline focus-visible:outline-2 " +
            "focus-visible:outline-offset-1 focus-visible:outline-focus"
          }
        >
          <Text id={REPRESENTATION_COPY_ID[kind]}>{label}</Text>
        </button>
        {status === "Missing" ? (
          // The centred question mark already says that this asset is absent. Keep the exact state
          // for assistive technology without printing the same word beside every module heading.
          <span data-dev-id="component-browser.cad-status" className="sr-only">
            <CadStatusLabel status={status} />
          </span>
        ) : (
          <StatusText
            data-dev-id="component-browser.cad-status"
            tone={cadStatusTone(status)}
            className="flex-none"
          >
            <CadStatusLabel status={status} />
          </StatusText>
        )}
        {override ? (
          <span className="ui-component-metadata ml-auto min-w-0 truncate" title={override}>
            {override}
          </span>
        ) : null}
      </h3>

      {/* The preview is present in BOTH states, smaller when the module is not in focus, because
          the three assets are read against each other. Never a text button, which competes with
          the asset for the line.

          The STAGE ITSELF is a control only while the module is compact, and that condition is not
          a style choice. `button` takes presentational children, so a widget role on this container
          deletes everything under it from the accessibility tree - and while the module is expanded
          that subtree is the asset's whole control surface: the maximize button, the 3D settings
          popover, the land pattern's measure target. This container used to carry role="button" in
          BOTH states, so every one of those controls was invisible to a screen reader, and Enter
          was the only key that worked because a div gets no keyboard behaviour of its own.

          So the tag follows the content. Compact, the subtree is inert (`interactive={expanded}`
          switches every child's controls off), nothing is swallowed, and a real <button> gives the
          stage a name, focus, Enter AND Space for free. Expanded, the stage is a plain surface and
          the keyboard path is the maximize button that is already inside it. */}
      {expanded ? (
        <div data-dev-id="component-browser.asset-preview" className={previewStageClass(true)}>
          <AssetPreview
            kind={kind}
            view={view}
            preview={preview}
            missing={status === "Missing"}
            interactive
            onOpenFullPreview={onOpenFullPreview}
          />
        </div>
      ) : (
        <button
          type="button"
          data-dev-id="component-browser.asset-preview"
          aria-label={fullPreview}
          onClick={onOpenFullPreview}
          className={previewStageClass(false)}
        >
          <AssetPreview
            kind={kind}
            view={view}
            preview={preview}
            missing={status === "Missing"}
            interactive={false}
            onOpenFullPreview={onOpenFullPreview}
          />
        </button>
      )}

      {expanded && attached ? (
        <AssetControls
          kind={kind}
          preview={preview}
          onOpenFullPreview={onOpenFullPreview}
        />
      ) : null}

      {/* A FAILURE is never gated on focus. Everything else about this asset is a count a person
          can go and ask for; a recorded fault is the one thing the column has to say unprompted. */}
      <AssetIssue status={view.status} issue={view.issue} />

      {focused ? (
        <AssetEvidence
          kind={kind}
          view={view}
          preview={preview}
          expectedPins={expectedPins}
          expectedPitch={expectedPitch}
          format={assetFormat(view)}
        />
      ) : null}
    </section>
  );
}

/**
 * The recorded FAULT on this asset, if there is one. Visible in every state.
 *
 * Split out of the evidence footer when the footer stopped rendering at rest. A silent failure is
 * worse than a line of text: the module header's status word (`Failed`, `Pin Match Failed`,
 * `Incomplete`, `Needs Review`) says THAT something is wrong in every state, and this says WHAT.
 * Neutral text with the warning triangle beside it, because the warning tier is no longer a hue.
 *
 * A MISSING asset is not a fault with anything to add. The projection sets its `issue` to "No file is
 * attached yet.", which is the header's own `Missing` in a longer sentence - so a component with no
 * CAD at all said the same thing twice per module, six times down a ~300px column. The payload keeps
 * the string (the completion worklist reads it as a detail line, where it is the only wording there
 * is); the column does not restate it. `failed` and `review` DO add something - which check, and
 * whether it failed or could not be measured - so those are stated unconditionally.
 */
function AssetIssue({
  status,
  issue,
}: {
  status: RepresentationView["status"];
  issue: string | null;
}) {
  if (!issue || (status !== "failed" && status !== "review")) return null;
  return (
    <p
      data-dev-id="component-browser.asset-issue"
      className="ui-component-metadata flex items-baseline gap-1 px-2 py-1 text-warn"
    >
      <WarnMark />
      <span>{issue}</span>
    </p>
  );
}

/** The nine words, each with its own copy id so it can be reworded without touching the set. */
function CadStatusLabel({ status }: { status: CadAssetStatus }) {
  if (status === "Validated") return <Text id="component-browser.cad-validated">Validated</Text>;
  if (status === "Available") return <Text id="component-browser.cad-available">Available</Text>;
  if (status === "Needs Review")
    return <Text id="component-browser.cad-needs-review">Needs Review</Text>;
  if (status === "Missing") return <Text id="component-browser.cad-missing">Missing</Text>;
  if (status === "Failed") return <Text id="component-browser.cad-failed">Failed</Text>;
  if (status === "Package Matched")
    return <Text id="component-browser.cad-package-matched">Package Matched</Text>;
  if (status === "Pin Match Failed")
    return <Text id="component-browser.cad-pin-match-failed">Pin Match Failed</Text>;
  if (status === "Incomplete")
    return <Text id="component-browser.cad-incomplete">Incomplete</Text>;
  return <Text id="component-browser.cad-not-required">Not Required</Text>;
}

/* -------------------------------------------------------------------------- */
/*  the preview data, per asset kind                                           */
/* -------------------------------------------------------------------------- */

type PreviewData = ReturnType<typeof usePreviewData>;

/**
 * Every asset kind's preview data, fetched under one fixed hook order.
 *
 * All three queries are declared unconditionally and gated by `enabled`, because a hook order
 * that changed with the asset kind would be a different component on every render.
 */
function usePreviewData(componentId: string, kind: RepresentationKind, attached: boolean) {
  const geometry = useSymbolGeometry(componentId, attached && kind === "symbol");
  const land = useLandPattern(componentId, attached && (kind === "footprint" || kind === "model"));
  const model = usePreviewGlb(componentId, attached && kind === "model");
  const symbolLayers = useSymbolLayers(geometry.data);
  const footprintLayers = useFootprintLayers();
  return { geometry, land, model, symbolLayers, footprintLayers };
}

/** The terminal counts the status vocabulary needs, when the drawing supplied them. */
function measurementsFor(
  kind: RepresentationKind,
  preview: PreviewData,
  expectedPins: number | null,
): CadMeasured | null {
  if (kind === "symbol" && preview.geometry.data) {
    const evidence = symbolEvidence(preview.geometry.data, expectedPins);
    return {
      terminals: evidence.pins,
      expected: expectedPins,
      duplicates: evidence.duplicates.length,
      unnumbered: evidence.unnumbered,
    };
  }
  if (kind === "footprint" && preview.land.data) {
    const evidence = footprintEvidence(preview.land.data, { pins: expectedPins, pitch: null });
    return {
      terminals: evidence.pads,
      expected: expectedPins,
      duplicates: evidence.duplicates.length,
      unnumbered: evidence.unnumbered,
    };
  }
  // A 3D body has no terminals to count. Reporting zero would read as a body with no pins.
  return null;
}

function AssetPreview({
  kind,
  view,
  preview,
  missing,
  interactive,
  onOpenFullPreview,
}: {
  kind: RepresentationKind;
  view: RepresentationView;
  preview: PreviewData;
  missing: boolean;
  interactive: boolean;
  /** Handed to the 3D viewer, which owns the only control strip a model module has. */
  onOpenFullPreview: () => void;
}) {
  const fullPreview = useText("component-browser.asset-full-preview", "Open Full Preview");
  const unreadable = useText(
    "component-browser.asset-unreadable",
    "This file could not be read on this machine",
  );

  // NOTHING ATTACHED: the asset's own line art, and no sentence. `No file is attached` was a second
  // statement of the header's `Missing` two lines above it, one per absent asset, so a component with
  // no CAD at all said the same thing four times down a ~300px column. The decorative question
  // mark is the visual statement; the exact status remains screen-reader text in the header.
  if (!view.tools.some((tool) => tool.present)) {
    return <PreviewMessage kind={kind} message="" missing={missing} />;
  }
  if (kind === "symbol") {
    if (preview.geometry.isError) return <PreviewMessage kind={kind} message={unreadable} />;
    if (!preview.geometry.data) return <PreviewMessage kind={kind} message="" />;
    return (
      <SymbolPreview
        geometry={preview.geometry.data}
        layers={preview.symbolLayers.layers}
        interactive={interactive}
      />
    );
  }
  if (kind === "footprint") {
    if (preview.land.isError) return <PreviewMessage kind={kind} message={unreadable} />;
    if (!preview.land.data) return <PreviewMessage kind={kind} message="" />;
    return (
      <FootprintPreview
        land={preview.land.data}
        layers={preview.footprintLayers.layers}
        measuring={interactive && preview.footprintLayers.measuring}
        measurement={preview.footprintLayers.measurement}
        onMeasure={preview.footprintLayers.place}
        interactive={interactive}
      />
    );
  }
  return (
    <div className="h-full w-full">
      <Glb3DView
        data={preview.model.data as ArrayBuffer | undefined}
        isLoading={preview.model.isLoading}
        isError={preview.model.isError}
        error={preview.model.error}
        land={preview.land.data ?? null}
        boardInitiallyVisible={false}
        showViews={interactive}
        showShading={interactive}
        compact
        // One button, one panel, exactly like the symbol and the land pattern beside it: layers,
        // motion, camera, appearance and placement all live inside the popover, and the strip is
        // the settings icon plus the maximize control the module hands down. The previous compact
        // bar still carried up to four always-visible layer icons and a spin toggle, which is the
        // same "row of switches above the drawing" the column was being read as.
        controls={interactive ? "panel" : "none"}
        trailing={interactive ? <MaximizeButton label={fullPreview} onClick={onOpenFullPreview} /> : null}
      />
    </div>
  );
}

function PreviewMessage({
  kind,
  message,
  missing = false,
}: {
  kind: RepresentationKind;
  message: string;
  missing?: boolean;
}) {
  return (
    <span className="flex flex-col items-center gap-1 text-t3">
      {missing ? <MissingAssetArt kind={kind} /> : assetArt(kind)}
      {message ? <span className="ui-component-metadata">{message}</span> : null}
    </span>
  );
}

/* -------------------------------------------------------------------------- */
/*  the controls                                                               */
/* -------------------------------------------------------------------------- */

/**
 * The controls that operate on the drawing in front of the person: ONE strip, icons only.
 *
 * Every visibility switch is inside the panel `AssetOptionsButton` opens, and nothing else about
 * what is drawn is visible until it is asked for. Counted on the running application, the previous
 * arrangement put fourteen outlined pills across six rows above the first piece of evidence in a
 * ~300px column; this puts two or three 20px icons on one 24px line. Not one switch was removed -
 * see `AssetOptions.tsx` for where each went and why measure and fit are not switches.
 *
 * The 3D body's controls are NOT duplicated here. `Glb3DView` owns the scene, so it owns its own
 * one-button panel (`controls="panel"`) and this module hands it the maximize control to place at
 * the end of the same strip - one row for the model too, rather than a bar under a bar.
 */
function AssetControls({
  kind,
  preview,
  onOpenFullPreview,
}: {
  kind: RepresentationKind;
  preview: PreviewData;
  onOpenFullPreview: () => void;
}) {
  const openFull = useText("component-browser.asset-full-preview", "Open Full Preview");
  const symbolOptions = useText(
    "component-browser.asset-symbol-options",
    "Show Or Hide Drawn Detail",
  );
  const footprintOptions = useText(
    "component-browser.asset-footprint-options",
    "Show Or Hide Drawn Detail",
  );
  const symbolGroup = useText("component-browser.asset-symbol-group", "Drawn Detail");
  const measureLabel = useText("component-browser.layer-measure", "Measure");
  const noSymbol = useText(
    "component-browser.asset-controls-no-symbol",
    "The symbol could not be read, so there is nothing to switch on",
  );
  const noFootprint = useText(
    "component-browser.asset-controls-no-footprint",
    "The land pattern could not be read, so there is nothing to switch on",
  );
  const noMask = useText(
    "component-browser.asset-no-mask",
    "No pad in this footprint declares a solder-mask layer",
  );
  const noPaste = useText(
    "component-browser.asset-no-paste",
    "No pad in this footprint declares a paste layer",
  );
  const noLayer = useText(
    "component-browser.asset-no-layer",
    "This footprint draws nothing on that layer",
  );

  // The model's strip is Glb3DView's own, so that the settings button and the maximize control sit
  // on ONE line instead of a module strip stacked under a viewer bar.
  if (kind === "model") return null;

  if (kind === "symbol") {
    const reason = preview.geometry.data ? "" : noSymbol;
    const { layers, toggle } = preview.symbolLayers;
    const symbolOption = (
      layer: SymbolLayer,
      devId: string,
      copyId: string,
      label: string,
    ): AssetOption => ({
      id: layer,
      devId,
      copyId,
      label,
      on: layers[layer],
      toggle: () => toggle(layer),
      disabledReason: reason,
    });
    return (
      <AssetControlStrip>
        <AssetOptionsButton
          devId="component-browser.asset-options-symbol"
          buttonLabel={symbolOptions}
          groupLabel={symbolGroup}
          emptyReason={noSymbol}
          options={[
            symbolOption(
              "pinName",
              "component-browser.asset-layer-pin-name",
              "component-browser.layer-pin-name",
              "Pin Names",
            ),
            symbolOption(
              "pinNumber",
              "component-browser.asset-layer-pin-number",
              "component-browser.layer-pin-number",
              "Pin Numbers",
            ),
            symbolOption(
              "electrical",
              "component-browser.asset-layer-electrical",
              "component-browser.layer-electrical",
              "Electrical Type",
            ),
          ]}
        />
        <span className="ml-auto flex items-center gap-1">
          <MaximizeButton label={openFull} onClick={onOpenFullPreview} />
        </span>
      </AssetControlStrip>
    );
  }

  const land = preview.land.data;
  const { layers, toggle, measuring, toggleMeasuring } = preview.footprintLayers;
  // Every switch is offered only where the file has something to draw on that layer, and says so
  // when it does not - a switch that turns nothing on is a dead click path with a light on it.
  const drawn = (suffix: string) =>
    (land?.graphics ?? []).some((graphic) => graphic.layer.endsWith(suffix));
  const declares = (suffix: string) =>
    (land?.pads ?? []).some((pad) => pad.layers.some((layer) => layer.endsWith(suffix)));
  const base = land ? "" : noFootprint;
  const footprintOption = (
    layer: FootprintLayer,
    devId: string,
    copyId: string,
    label: string,
    reason = "",
  ): AssetOption => ({
    id: layer,
    devId,
    copyId,
    label,
    on: layers[layer],
    toggle: () => toggle(layer),
    disabledReason: base || reason,
  });

  return (
    <AssetControlStrip>
      <AssetOptionsButton
        devId="component-browser.asset-options-footprint"
        buttonLabel={footprintOptions}
        groupLabel={symbolGroup}
        emptyReason={noFootprint}
        options={[
          footprintOption(
            "copper",
            "component-browser.asset-layer-copper",
            "component-browser.layer-copper",
            "Copper",
            land && land.pads.length === 0 ? noLayer : "",
          ),
          footprintOption(
            "mask",
            "component-browser.asset-layer-mask",
            "component-browser.layer-mask",
            "Mask",
            land && !declares(".Mask") ? noMask : "",
          ),
          footprintOption(
            "paste",
            "component-browser.asset-layer-paste",
            "component-browser.layer-paste",
            "Paste",
            land && !declares(".Paste") ? noPaste : "",
          ),
          footprintOption(
            "silkscreen",
            "component-browser.asset-layer-silkscreen",
            "component-browser.layer-silkscreen",
            "Silkscreen",
            land && !drawn(".SilkS") ? noLayer : "",
          ),
          footprintOption(
            "fabrication",
            "component-browser.asset-layer-fabrication",
            "component-browser.layer-fabrication",
            "Fabrication",
            land && !drawn(".Fab") ? noLayer : "",
          ),
          footprintOption(
            "courtyard",
            "component-browser.asset-layer-courtyard",
            "component-browser.layer-courtyard",
            "Courtyard",
            land && !drawn(".CrtYd") ? noLayer : "",
          ),
          footprintOption(
            "numbers",
            "component-browser.asset-layer-numbers",
            "component-browser.layer-numbers",
            "Pad Numbers",
          ),
          footprintOption(
            "origin",
            "component-browser.asset-layer-origin",
            "component-browser.layer-origin",
            "Origin",
          ),
          footprintOption(
            "dimensions",
            "component-browser.asset-layer-dimensions",
            "component-browser.layer-dimensions",
            "Dimensions",
            land && land.pads.length === 0 ? noLayer : "",
          ),
        ]}
      />
      <MeasureButton
        label={measureLabel}
        pressed={measuring}
        onToggle={toggleMeasuring}
        disabledReason={base}
      />
      <span className="ml-auto flex items-center gap-1">
        <MaximizeButton label={openFull} onClick={onOpenFullPreview} />
      </span>
    </AssetControlStrip>
  );
}

/* -------------------------------------------------------------------------- */
/*  the evidence footer                                                        */
/* -------------------------------------------------------------------------- */

/**
 * What was actually checked, in plain counts, reading `STEP . 5/8 pins matched . No duplicates`.
 *
 * ONLY WHEN THIS MODULE IS THE FOCUSED ONE. At rest the column stacks three drawings, and it used to
 * put a line of counts under each of them - `2 pins · No duplicates`, `2 pads · 0.96 mm pitch ·
 * Courtyard present · 1.80 x 0.84 mm`, `No file is attached` - which is three lines of measurement
 * nobody asked for above the specifications a person opened the component to read. Clicking a module
 * header focuses it (and `Show All Three` comes back), and the focused module states its evidence.
 * The data is not gone from anywhere: it is measured from the drawing on demand, the recorded checks
 * are in Manage Models and the evidence surface, and a genuine FAULT is stated in every state by
 * `AssetIssue` above plus the header's own status word.
 *
 * Built from the drawing and from the recorded checks, never from a claim. An asset nobody has
 * measured says so rather than implying a validation that never ran, and a comparison whose
 * other side the specification does not state is omitted rather than reported as a pass.
 *
 * The PROVIDER is deliberately absent. It is stated once at column level, and repeating the same
 * provider sentence under all three assets is exactly what pushed the asset off its own line; the
 * header states it only where this asset's source disagrees with the column's.
 */
function AssetEvidence({
  kind,
  view,
  preview,
  expectedPins,
  expectedPitch,
  format,
}: {
  kind: RepresentationKind;
  view: RepresentationView;
  preview: PreviewData;
  expectedPins: number | null;
  expectedPitch: number | null;
  format: string;
}) {
  const pinsMatched = useText("component-browser.evidence-pins-matched", "pins matched");
  const pinsFound = useText("component-browser.evidence-pins", "pins");
  const padsFound = useText("component-browser.evidence-pads", "pads");
  const expectedWord = useText("component-browser.evidence-expected", "expected");
  const noDuplicates = useText("component-browser.evidence-no-duplicates", "No duplicates");
  const duplicateWord = useText("component-browser.evidence-duplicates", "duplicate numbers");
  const unnumberedWord = useText("component-browser.evidence-unnumbered", "unnumbered");
  const hiddenWord = useText("component-browser.evidence-hidden", "hidden");
  const noBody = useText("component-browser.evidence-no-body", "No outline drawn");
  const courtyardYes = useText("component-browser.evidence-courtyard", "Courtyard present");
  const courtyardNo = useText("component-browser.evidence-no-courtyard", "No courtyard");
  const pinOneNo = useText("component-browser.evidence-no-pin-one", "No pad numbered 1");
  const pitchWord = useText("component-browser.evidence-pitch", "pitch");
  const noChecks = useText("component-browser.evidence-none", "Nothing has been checked so far");

  const parts: string[] = [];
  if (format) parts.push(format);

  if (kind === "symbol" && preview.geometry.data) {
    const evidence = symbolEvidence(preview.geometry.data, expectedPins);
    parts.push(
      evidence.expectedPins !== null
        ? `${evidence.pins}/${evidence.expectedPins} ${pinsMatched}`
        : `${evidence.pins} ${pinsFound}`,
    );
    parts.push(
      evidence.duplicates.length === 0
        ? noDuplicates
        : `${evidence.duplicates.length} ${duplicateWord}`,
    );
    if (evidence.unnumbered > 0) parts.push(`${evidence.unnumbered} ${unnumberedWord}`);
    if (evidence.hidden > 0) parts.push(`${evidence.hidden} ${hiddenWord}`);
    if (!evidence.bounds) parts.push(noBody);
  }

  if (kind === "footprint" && preview.land.data) {
    const evidence = footprintEvidence(preview.land.data, {
      pins: expectedPins,
      pitch: expectedPitch,
    });
    parts.push(
      evidence.expectedPins !== null
        ? `${evidence.pads}/${evidence.expectedPins} ${padsFound}`
        : `${evidence.pads} ${padsFound}`,
    );
    if (evidence.duplicates.length > 0) {
      parts.push(`${evidence.duplicates.length} ${duplicateWord}`);
    }
    if (!evidence.hasPinOne) parts.push(pinOneNo);
    if (evidence.pitch !== null) {
      parts.push(
        evidence.expectedPitch !== null
          ? `${evidence.pitch} mm ${pitchWord} (${expectedWord} ${evidence.expectedPitch})`
          : `${evidence.pitch} mm ${pitchWord}`,
      );
    }
    parts.push(evidence.courtyard ? courtyardYes : courtyardNo);
    if (evidence.size) {
      parts.push(`${evidence.size.width.toFixed(2)} x ${evidence.size.height.toFixed(2)} mm`);
    }
  }

  const checks = view.tools.flatMap((tool) => tool.checks);
  if (kind === "model" && checks.length === 0 && parts.length <= 2) parts.push(noChecks);

  return (
    <div className="flex flex-col gap-0.5 px-2 py-1">
      {parts.length > 0 ? (
        <p data-dev-id="component-browser.asset-evidence" className="ui-component-metadata">
          {parts.join(" · ")}
        </p>
      ) : null}
      {checks.length > 0 ? (
        <ul className="flex flex-col">
          {checks.map((check, index) => (
            <li key={index} className="ui-row-metadata" data-check={check.check}>
              {`${check.check}: ${String(check.measured ?? "—")} / ${String(check.expected ?? "—")}`}
              {check.against ? ` · ${check.against}` : ""}
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}
