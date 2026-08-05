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
import type { ReactNode } from "react";
import type {
  CadPreferenceView,
  RepresentationKind,
  RepresentationView,
} from "../../api/dossierTypes";
import { useLandPattern, usePreviewGlb, useSymbolGeometry } from "../../api/queries";
import { componentRepresentationDevId } from "../../lib/componentDevIds";
import { Text, useText } from "../../lib/copy";
import { CubeArt, FootprintArt, SymbolArt } from "../icons";
import { Glb3DView } from "../Glb3DView";
import { StatusText } from "../primitives";
import { assetOverride } from "./cadPreference";
import {
  FootprintPreview,
  footprintEvidence,
  useFootprintLayers,
  type FootprintLayer,
} from "./FootprintPreview";
import {
  SymbolPreview,
  symbolEvidence,
  useSymbolLayers,
  type SymbolLayer,
} from "./SymbolPreview";
import { cadAssetStatus, cadStatusTone, type CadAssetStatus, type CadMeasured } from "./workspaceStatus";

export const REPRESENTATION_KINDS: readonly RepresentationKind[] = [
  "symbol",
  "footprint",
  "model",
];

/** What each asset is CALLED. Asset kinds, not file formats and not applications. */
export const REPRESENTATION_LABEL: Record<RepresentationKind, string> = {
  symbol: "Symbol",
  footprint: "Footprint",
  model: "3D Model",
};

export const REPRESENTATION_COPY_ID: Record<RepresentationKind, string> = {
  symbol: "component-browser.asset-symbol",
  footprint: "component-browser.asset-footprint",
  model: "component-browser.asset-model",
};

export function assetArt(kind: RepresentationKind) {
  if (kind === "symbol") return <SymbolArt />;
  if (kind === "footprint") return <FootprintArt />;
  return <CubeArt />;
}

/**
 * The provider that supplied this asset. A PROVIDER name (Ultra Librarian, SnapMagic, Samacsys)
 * is source information and belongs here; an EDA application's name is not and does not.
 */
export function assetSource(view: RepresentationView): string {
  const tool = view.tools.find((entry) => entry.tool === view.selectedTool) ?? view.tools[0];
  return (view.sourceLabel || tool?.sourceLabel || "").trim();
}

/** The file format the asset is held in, from the reference itself. Never an application name. */
export function assetFormat(view: RepresentationView): string {
  const tool = view.tools.find((entry) => entry.tool === view.selectedTool) ?? view.tools[0];
  const file = tool?.reference.file ?? "";
  const dot = file.lastIndexOf(".");
  return dot > 0 ? file.slice(dot + 1).toUpperCase() : "";
}

export function CadAssetModule({
  componentId,
  kind,
  view,
  preference,
  expectedPins,
  expectedPitch,
  expanded,
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
  onToggle: () => void;
  onOpenFullPreview: () => void;
  focusRef?: (node: HTMLElement | null) => void;
}) {
  const label = REPRESENTATION_LABEL[kind];
  const override = assetOverride(preference, kind);
  const collapseLabel = useText("component-browser.asset-collapse", "Collapse");
  const expandLabel = useText("component-browser.asset-expand", "Expand");
  const fullPreview = useText("component-browser.asset-full-preview", "Open Full Preview");
  const attached = view.tools.some((tool) => tool.present);

  const preview = usePreviewData(componentId, kind, attached);
  const measured = measurementsFor(kind, preview, expectedPins);
  const status = cadAssetStatus(view, measured);

  return (
    <section
      ref={focusRef}
      data-dev-id={componentRepresentationDevId(componentId, kind)}
      data-dev-role="component-browser.cad-asset"
      data-asset-kind={kind}
      data-expanded={expanded ? "true" : "false"}
      data-status={status}
      aria-label={label}
      className="flex min-h-0 flex-none flex-col border-b border-line last:border-b-0"
    >
      {/* One dense line: name, state, and the source ONLY when it differs from the column's. */}
      <h3 className="flex items-center gap-2 px-2 py-1">
        <button
          type="button"
          data-dev-id="component-browser.asset-header"
          aria-expanded={expanded}
          title={expanded ? collapseLabel : expandLabel}
          onClick={onToggle}
          className={
            "ui-section-title flex-none rounded-control focus-visible:outline focus-visible:outline-2 " +
            "focus-visible:outline-offset-1 focus-visible:outline-focus"
          }
        >
          <Text id={REPRESENTATION_COPY_ID[kind]}>{label}</Text>
        </button>
        <StatusText tone={cadStatusTone(status)} className="flex-none">
          <CadStatusLabel status={status} />
        </StatusText>
        {override ? (
          <span className="ui-component-metadata ml-auto min-w-0 truncate" title={override}>
            {override}
          </span>
        ) : null}
      </h3>

      {/* The preview is present in BOTH states, smaller when the module is not in focus, because
          the three assets are read against each other. Click or double-click it to open the full
          preview - never a text button, which competes with the asset for the line. */}
      <div
        data-dev-id="component-browser.asset-preview"
        role="button"
        tabIndex={0}
        aria-label={fullPreview}
        onDoubleClick={onOpenFullPreview}
        onKeyDown={(event) => {
          if (event.key !== "Enter") return;
          event.preventDefault();
          onOpenFullPreview();
        }}
        className={
          "flex flex-none items-center justify-center overflow-hidden border-y border-line " +
          "bg-field focus-visible:outline focus-visible:outline-2 " +
          "focus-visible:-outline-offset-2 focus-visible:outline-focus " +
          (expanded ? "h-[184px]" : "h-[56px]")
        }
      >
        <AssetPreview
          kind={kind}
          view={view}
          preview={preview}
          interactive={expanded}
        />
      </div>

      {expanded ? (
        <AssetControls
          kind={kind}
          preview={preview}
          onOpenFullPreview={onOpenFullPreview}
        />
      ) : null}

      {expanded ? (
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
  interactive,
}: {
  kind: RepresentationKind;
  view: RepresentationView;
  preview: PreviewData;
  interactive: boolean;
}) {
  const absent = useText("component-browser.asset-absent", "No file is attached");
  const unreadable = useText(
    "component-browser.asset-unreadable",
    "This file could not be read on this machine",
  );

  if (!view.tools.some((tool) => tool.present)) {
    return <PreviewMessage kind={kind} message={absent} />;
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
        showViews={interactive}
        showShading={interactive}
        compact={!interactive}
      />
    </div>
  );
}

function PreviewMessage({ kind, message }: { kind: RepresentationKind; message: string }) {
  return (
    <span className="flex flex-col items-center gap-1 text-t3">
      {assetArt(kind)}
      {message ? <span className="ui-component-metadata">{message}</span> : null}
    </span>
  );
}

/* -------------------------------------------------------------------------- */
/*  the controls                                                               */
/* -------------------------------------------------------------------------- */

/**
 * One toggle. Icon-free by design at this size - a 22px square holding a legible glyph plus a
 * pressed state is wider than the whole column allows - but every one of them carries a tooltip,
 * an accessible label and `aria-pressed`, which is what the pressed state has to be readable as.
 */
function LayerToggle({
  devId,
  label,
  pressed,
  onToggle,
  disabledReason = "",
}: {
  devId: string;
  label: ReactNode;
  pressed: boolean;
  onToggle: () => void;
  /** Stated, never silent: a control that cannot operate has to say why in words. */
  disabledReason?: string;
}) {
  return (
    <button
      type="button"
      data-dev-id={devId}
      aria-pressed={pressed}
      disabled={disabledReason !== ""}
      title={disabledReason || undefined}
      onClick={onToggle}
      className={
        "ui-control-label h-[20px] rounded-control border border-line px-2 " +
        "hover:bg-control-hover disabled:opacity-50 disabled:hover:bg-transparent " +
        "focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-1 " +
        "focus-visible:outline-focus " +
        (pressed ? "bg-selected text-t1" : "text-t3")
      }
    >
      {label}
    </button>
  );
}

/**
 * The controls that actually operate on the drawing in front of the person.
 *
 * Deliberately only the ones backed by real data. The 3D body's own controls - fit, orientation,
 * projection, the preset views, the land-pattern overlay - live inside `Glb3DView`, which owns
 * the scene; duplicating them here would be a second set of buttons pointing at one camera.
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

  if (kind === "model") {
    return (
      <div className="flex items-center justify-end gap-1 px-2 py-1">
        <MaximizeButton label={openFull} onClick={onOpenFullPreview} />
      </div>
    );
  }

  if (kind === "symbol") {
    const geometry = preview.geometry.data;
    const reason = geometry ? "" : noSymbol;
    const { layers, toggle } = preview.symbolLayers;
    const symbolToggle = (layer: SymbolLayer, devId: string, label: ReactNode) => (
      <LayerToggle
        devId={devId}
        label={label}
        pressed={layers[layer]}
        onToggle={() => toggle(layer)}
        disabledReason={reason}
      />
    );
    return (
      <div className="flex flex-wrap items-center gap-1 px-2 py-1">
        {symbolToggle(
          "pinName",
          "component-browser.asset-layer-pin-name",
          <Text id="component-browser.layer-pin-name">Pin Names</Text>,
        )}
        {symbolToggle(
          "pinNumber",
          "component-browser.asset-layer-pin-number",
          <Text id="component-browser.layer-pin-number">Pin Numbers</Text>,
        )}
        {symbolToggle(
          "electrical",
          "component-browser.asset-layer-electrical",
          <Text id="component-browser.layer-electrical">Electrical Type</Text>,
        )}
        <span className="ml-auto flex items-center gap-1">
          <MaximizeButton label={openFull} onClick={onOpenFullPreview} />
        </span>
      </div>
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
  const footprintToggle = (
    layer: FootprintLayer,
    devId: string,
    label: ReactNode,
    reason: string,
  ) => (
    <LayerToggle
      devId={devId}
      label={label}
      pressed={layers[layer]}
      onToggle={() => toggle(layer)}
      disabledReason={base || reason}
    />
  );

  return (
    <div className="flex flex-wrap items-center gap-1 px-2 py-1">
      {footprintToggle(
        "copper",
        "component-browser.asset-layer-copper",
        <Text id="component-browser.layer-copper">Copper</Text>,
        land && land.pads.length === 0 ? noLayer : "",
      )}
      {footprintToggle(
        "mask",
        "component-browser.asset-layer-mask",
        <Text id="component-browser.layer-mask">Mask</Text>,
        land && !declares(".Mask") ? noMask : "",
      )}
      {footprintToggle(
        "paste",
        "component-browser.asset-layer-paste",
        <Text id="component-browser.layer-paste">Paste</Text>,
        land && !declares(".Paste") ? noPaste : "",
      )}
      {footprintToggle(
        "silkscreen",
        "component-browser.asset-layer-silkscreen",
        <Text id="component-browser.layer-silkscreen">Silkscreen</Text>,
        land && !drawn(".SilkS") ? noLayer : "",
      )}
      {footprintToggle(
        "fabrication",
        "component-browser.asset-layer-fabrication",
        <Text id="component-browser.layer-fabrication">Fabrication</Text>,
        land && !drawn(".Fab") ? noLayer : "",
      )}
      {footprintToggle(
        "courtyard",
        "component-browser.asset-layer-courtyard",
        <Text id="component-browser.layer-courtyard">Courtyard</Text>,
        land && !drawn(".CrtYd") ? noLayer : "",
      )}
      {footprintToggle(
        "numbers",
        "component-browser.asset-layer-numbers",
        <Text id="component-browser.layer-numbers">Pad Numbers</Text>,
        "",
      )}
      {footprintToggle(
        "origin",
        "component-browser.asset-layer-origin",
        <Text id="component-browser.layer-origin">Origin</Text>,
        "",
      )}
      {footprintToggle(
        "dimensions",
        "component-browser.asset-layer-dimensions",
        <Text id="component-browser.layer-dimensions">Dimensions</Text>,
        land && land.pads.length === 0 ? noLayer : "",
      )}
      <LayerToggle
        devId="component-browser.asset-measure"
        label={<Text id="component-browser.layer-measure">Measure</Text>}
        pressed={measuring}
        onToggle={toggleMeasuring}
        disabledReason={base}
      />
      <span className="ml-auto flex items-center gap-1">
        <MaximizeButton label={openFull} onClick={onOpenFullPreview} />
      </span>
    </div>
  );
}

/** The one control that opens the full preview: a small maximize glyph, never a text button. */
function MaximizeButton({ label, onClick }: { label: string; onClick: () => void }) {
  return (
    <button
      type="button"
      data-dev-id="component-browser.asset-maximize"
      aria-label={label}
      title={label}
      onClick={onClick}
      className={
        "flex h-[20px] w-[20px] items-center justify-center rounded-control text-t3 " +
        "hover:bg-control-hover hover:text-t1 focus-visible:outline focus-visible:outline-2 " +
        "focus-visible:outline-offset-1 focus-visible:outline-focus"
      }
    >
      <svg viewBox="0 0 16 16" aria-hidden className="h-3.5 w-3.5" fill="none" stroke="currentColor" strokeWidth="1.4">
        <path d="M6 2H2v4M10 14h4v-4M14 6V2h-4M2 10v4h4" />
      </svg>
    </button>
  );
}

/* -------------------------------------------------------------------------- */
/*  the evidence footer                                                        */
/* -------------------------------------------------------------------------- */

/**
 * What was actually checked, in plain counts, reading `STEP . 5/8 pins matched . No duplicates`.
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
  const noBody = useText("component-browser.evidence-no-body", "No body drawn");
  const courtyardYes = useText("component-browser.evidence-courtyard", "Courtyard present");
  const courtyardNo = useText("component-browser.evidence-no-courtyard", "No courtyard");
  const pinOneNo = useText("component-browser.evidence-no-pin-one", "No pad numbered 1");
  const pitchWord = useText("component-browser.evidence-pitch", "pitch");
  const noChecks = useText("component-browser.evidence-none", "Nothing has been checked yet");

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
      {view.issue ? (
        <p data-dev-id="component-browser.asset-issue" className="ui-component-metadata text-warn">
          {view.issue}
        </p>
      ) : null}
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
