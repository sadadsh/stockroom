import { useCopyFormatter, useText } from "../../../lib/copy";
import { cadPresentationTarget } from "../../../design-studio/cadPresentation";
import { useOptionalDesignStudio } from "../../../design-studio/DesignStudioProvider";
import type {
  FootprintPresentationOverride,
  Model3dPresentationOverride,
  SymbolPresentationOverride,
} from "../../../design-studio/document";
import type { DomainInspectorProps } from "./types";

const BOOLEAN_FIELDS = {
  symbol: ["body", "pins", "names", "numbers", "fields", "hiddenPins"],
  footprint: ["pads", "fabrication", "courtyard", "silkscreen", "reference", "value", "models3d"],
  model3d: ["models", "board", "axes", "grid"],
} as const;

const FIELD_LABELS: Record<string, string> = {
  body: "Outline",
  pins: "Pins",
  names: "Names",
  numbers: "Numbers",
  fields: "Fields",
  hiddenPins: "Hidden Pins",
  pads: "Pads",
  fabrication: "Fabrication",
  courtyard: "Courtyard",
  silkscreen: "Silkscreen",
  reference: "Reference",
  value: "Value",
  models3d: "3D Model",
  models: "Models",
  board: "Board",
  axes: "Axes",
  grid: "Grid",
};

type Presentation = SymbolPresentationOverride | FootprintPresentationOverride | Model3dPresentationOverride;

export function CadPresentationInspector({ inspection }: DomainInspectorProps) {
  const studio = useOptionalDesignStudio();
  const target = cadPresentationTarget(inspection.target);
  const title = useText("design-studio.inspector.cad.title", "CAD Presentation");
  const reset = useText("design-studio.inspector.cad.reset", "Reset CAD Presentation");
  const layerColors = useText("design-studio.inspector.cad.layer-colors", "Layer Colors");
  const materialLabel = useText("design-studio.inspector.cad.material", "Material");
  const sourceLabel = useText("design-studio.inspector.cad.material.source", "Source");
  const studioLabel = useText("design-studio.inspector.cad.material.studio", "Studio");
  const seeThroughLabel = useText("design-studio.inspector.cad.material.see-through", "See Through");
  const alphaLabel = useText("design-studio.inspector.cad.alpha", "Alpha");
  const valueAria = useCopyFormatter("design-studio.inspector.cad.value-aria", "CAD {label} Value");
  if (!studio || !target) return null;
  const presentation = (studio.resolvedCadPresentation[target.targetId]?.[target.kind] ?? {}) as Presentation;
  const set = (patch: Partial<Presentation>, themeSpecific = false) => {
    studio.setCadPresentation(target.targetId, target.kind, patch as never, themeSpecific);
  };
  return (
    <section className="border-t border-line px-3.5 py-3" aria-label={title}>
      <div className="flex items-center justify-between gap-2">
        <h4 className="ui-property-label">{title}</h4>
        <button type="button" onClick={() => studio.resetCadPresentation(target.targetId)} className="text-2xs font-semibold text-t2 hover:text-t1">{reset}</button>
      </div>
      <div className="mt-2 grid grid-cols-2 gap-2">
        {BOOLEAN_FIELDS[target.kind].map((field) => (
          <label key={field} className="flex items-center gap-2 text-xs text-t2">
            <input
              type="checkbox"
              checked={(presentation as Record<string, unknown>)[field] !== false}
              onChange={(event) => set({ [field]: event.target.checked })}
            />
            {FIELD_LABELS[field]}
          </label>
        ))}
      </div>
      {target.kind === "symbol" ? (
        <div className="mt-3 grid grid-cols-2 gap-2">
          <PresentationText label="Stroke" ariaLabel={valueAria({ label: "Stroke" })} value={(presentation as SymbolPresentationOverride).stroke ?? ""} onCommit={(value) => set({ stroke: value }, true)} />
          <PresentationText label="Fill" ariaLabel={valueAria({ label: "Fill" })} value={(presentation as SymbolPresentationOverride).fill ?? ""} onCommit={(value) => set({ fill: value }, true)} />
        </div>
      ) : null}
      {target.kind === "footprint" ? (
        <div className="mt-3">
          <h5 className="ui-property-label">{layerColors}</h5>
          <div className="mt-1 grid grid-cols-2 gap-2">
            {["copper", "mask", "paste", "silkscreen", "fabrication", "courtyard"].map((layer) => (
              <PresentationText
                key={layer}
                label={FIELD_LABELS[layer] ?? layer[0].toUpperCase() + layer.slice(1)}
                ariaLabel={valueAria({ label: FIELD_LABELS[layer] ?? layer })}
                value={(presentation as FootprintPresentationOverride).layerColors?.[layer] ?? ""}
                onCommit={(value) => set({ layerColors: { ...(presentation as FootprintPresentationOverride).layerColors, [layer]: value } }, true)}
              />
            ))}
          </div>
        </div>
      ) : null}
      {target.kind === "model3d" ? (
        <div className="mt-3 grid grid-cols-2 gap-2">
          <PresentationText label="Background" ariaLabel={valueAria({ label: "Background" })} value={(presentation as Model3dPresentationOverride).background ?? ""} onCommit={(value) => set({ background: value }, true)} />
          <PresentationText label="Tint" ariaLabel={valueAria({ label: "Tint" })} value={(presentation as Model3dPresentationOverride).tint ?? ""} onCommit={(value) => set({ tint: value }, true)} />
          <label className="text-xs text-t2">{materialLabel}
            <select
              value={(presentation as Model3dPresentationOverride).material ?? "realistic"}
              onChange={(event) => set({ material: event.target.value as "realistic" | "studio" | "xray" })}
              className="mt-1 w-full rounded-control border border-line bg-field px-2 py-1 text-2xs text-t1"
            >
              <option value="realistic">{sourceLabel}</option>
              <option value="studio">{studioLabel}</option>
              <option value="xray">{seeThroughLabel}</option>
            </select>
          </label>
          <label className="text-xs text-t2">{alphaLabel}
            <input
              type="number"
              min={0}
              max={1}
              step={0.05}
              value={(presentation as Model3dPresentationOverride).opacity ?? 1}
              onChange={(event) => {
                const value = event.currentTarget.valueAsNumber;
                if (Number.isFinite(value) && value >= 0 && value <= 1) set({ opacity: value });
              }}
              className="mt-1 w-full rounded-control border border-line bg-field px-2 py-1 text-2xs text-t1"
            />
          </label>
        </div>
      ) : null}
    </section>
  );
}

function PresentationText({ label, ariaLabel, value, onCommit }: { label: string; ariaLabel: string; value: string; onCommit: (value: string) => void }) {
  return (
    <label className="text-xs text-t2">
      {label}
      <input
        aria-label={ariaLabel}
        defaultValue={value}
        onBlur={(event) => {
          const next = event.currentTarget.value.trim();
          if (next) onCommit(next);
        }}
        className="mt-1 w-full rounded-control border border-line bg-field px-2 py-1 text-2xs text-t1"
      />
    </label>
  );
}
