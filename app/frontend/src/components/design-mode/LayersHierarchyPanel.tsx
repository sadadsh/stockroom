import { useMemo, useState } from "react";
import { useDesignStudio } from "../../design-studio/DesignStudioProvider";
import { DEV_IDS } from "../../lib/devIds";
import { targetLayersFor } from "../../design-studio/targetCoverage";
import { useDevMode } from "../../lib/devMode";
import { useText } from "../../lib/copy";

type TreeView = "layers" | "hierarchy";

export function LayersHierarchyPanel() {
  const studio = useDesignStudio();
  const dev = useDevMode();
  const [view, setView] = useState<TreeView>("layers");
  const variationsLabel = useText("design-studio.variations", "Variations");
  const baseLabel = useText("design-studio.variations.base", "Base");
  const noVariationsLabel = useText("design-studio.variations.empty", "No Variations Yet");
  const structureLabel = useText("design-studio.structure", "Layers And Structure");
  const layersLabel = useText("design-studio.layers", "Layers");
  const hierarchyLabel = useText("design-studio.hierarchy", "Structure");
  const variations = Object.values(studio.document.variations);
  const targets = useMemo(
    () => targetLayersFor(document, DEV_IDS),
    [studio.activeScenario, studio.document, dev.selectedDevId],
  );

  return (
    <div className="min-h-0 flex-1 overflow-y-auto">
      <section className="border-b border-line p-2" aria-labelledby="studio-variations-heading">
        <h2 id="studio-variations-heading" className="mb-1 text-xs font-semibold text-t1">{variationsLabel}</h2>
        <button
          type="button"
          aria-pressed={!studio.activeVariationId}
          onClick={() => studio.setVariation("")}
          className="block w-full rounded-control px-2 py-1 text-left text-xs text-t2 hover:bg-raise2"
        >
          {baseLabel}
        </button>
        {variations.map((variation) => (
          <button
            key={variation.id}
            type="button"
            aria-pressed={studio.activeVariationId === variation.id}
            onClick={() => studio.setVariation(variation.id)}
            className="block w-full rounded-control px-2 py-1 text-left text-xs text-t2 hover:bg-raise2"
          >
            {variation.title}
          </button>
        ))}
        {variations.length === 0 ? <p className="px-2 py-1 text-2xs text-t3">{noVariationsLabel}</p> : null}
      </section>

      <section aria-labelledby="studio-structure-heading">
        <header className="flex items-center gap-1 border-b border-line bg-band px-2 py-1.5">
          <h2 id="studio-structure-heading" className="sr-only">{structureLabel}</h2>
          {(["layers", "hierarchy"] as const).map((item) => (
            <button
              key={item}
              type="button"
              aria-pressed={view === item}
              onClick={() => setView(item)}
              className={
                "rounded-control px-2 py-0.5 text-xs font-semibold " +
                (view === item ? "bg-control-pressed text-t1" : "text-t2 hover:bg-control-hover")
              }
            >
              {item === "layers" ? layersLabel : hierarchyLabel}
            </button>
          ))}
        </header>
        <div className="p-2">
          {targets.map((entry) => (
            <button
              key={entry.key}
              type="button"
              data-target-key={entry.key}
              data-target-depth={entry.depth}
              onClick={() => entry.ownerDevId && dev.selectDevId(entry.ownerDevId)}
              className={
                "block w-full truncate rounded-control py-1 text-left text-xs hover:bg-raise2 " +
                (view === "hierarchy" ? "pr-2" : "px-2") +
                (dev.selectedDevId === entry.ownerDevId ? " bg-acc-soft text-t1" : " text-t2")
              }
              style={view === "hierarchy" ? { paddingLeft: `${8 + entry.depth * 12}px` } : undefined}
              title={entry.id}
            >
              {entry.label}{entry.occurrences > 1 ? ` (${entry.occurrences})` : ""}
            </button>
          ))}
        </div>
      </section>
    </div>
  );
}
