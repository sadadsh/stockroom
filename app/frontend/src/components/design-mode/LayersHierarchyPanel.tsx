import { useMemo, useState, type FormEvent } from "react";
import { useDesignStudio } from "../../design-studio/DesignStudioProvider";
import { DEV_IDS } from "../../lib/devIds";
import { targetLayersFor } from "../../design-studio/targetCoverage";
import { useDevMode } from "../../lib/devMode";
import { useText } from "../../lib/copy";
import { BUILT_IN_VARIATIONS } from "../../design-studio/document";
import { designIdOf, ensureDesignIdentities } from "../../lib/designIdentity";

type TreeView = "layers" | "hierarchy";

export function LayersHierarchyPanel() {
  const studio = useDesignStudio();
  const dev = useDevMode();
  const [view, setView] = useState<TreeView>("layers");
  const [creatingVariation, setCreatingVariation] = useState(false);
  const [allElements, setAllElements] = useState(false);
  const [variationTitle, setVariationTitle] = useState("");
  const variationsLabel = useText("design-studio.variations", "Variations");
  const baseLabel = useText("design-studio.variations.base", "Base");
  const noVariationsLabel = useText("design-studio.variations.empty", "No Variations Yet");
  const extendsLabel = useText("design-studio.variations.extends", "Extends");
  const variationParentLabel = useText("design-studio.variations.parent", "Variation Parent");
  const noneLabel = useText("design-studio.variations.none", "None");
  const deleteLabel = useText("design-studio.variations.delete", "Delete");
  const variationNameLabel = useText("design-studio.variations.name", "Variation Name");
  const createLabel = useText("design-studio.variations.create", "Create");
  const newVariationLabel = useText("design-studio.variations.new", "New Variation");
  const structureLabel = useText("design-studio.structure", "Layers And Structure");
  const layersLabel = useText("design-studio.layers", "Layers");
  const hierarchyLabel = useText("design-studio.hierarchy", "Structure");
  const allElementsLabel = useText("design-studio.layers.all-elements", "All Elements");
  const hideSelectedLabel = useText("design-studio.layers.hide-selected", "Hide Selected");
  const hideScreenLabel = useText("design-studio.layers.hide-screen", "Hide Screen Contents");
  const showHiddenLabel = useText("design-studio.layers.show-hidden", "Show All Hidden");
  const hiddenLabel = useText("design-studio.layers.hidden", "Hidden");
  const variations = Object.values(studio.document.variations);
  const parentVariations = variations.filter((variation) => variation.id !== studio.activeVariationId);
  const builtInIds = useMemo<Set<string>>(() => new Set(BUILT_IN_VARIATIONS.map((variation) => variation.id)), []);
  const targets = useMemo(
    () => targetLayersFor(document, DEV_IDS),
    [studio.activeScenario, studio.document, dev.selectedDevId, dev.draft.elements],
  );
  const visibleTargets = targets.filter(
    (target) => allElements || target.meaningful || dev.draft.elements[target.ownerDevId ?? ""]?.visibility === "hidden",
  );

  const replaceElementVisibility = (ids: readonly string[], hidden: boolean) => {
    const elements = Object.fromEntries(
      Object.entries(dev.draft.elements).map(([id, props]) => [id, { ...props }]),
    );
    for (const id of ids) {
      if (hidden) {
        elements[id] = { ...(elements[id] ?? {}), visibility: "hidden" };
      } else if (elements[id]) {
        delete elements[id].visibility;
        if (Object.keys(elements[id]).length === 0) delete elements[id];
      }
    }
    studio.replaceResolvedDraftAtomically({ ...dev.draft, elements });
  };

  const hideScreenContents = () => {
    const root = document.querySelector("[data-design-product-root]");
    if (!root) return;
    ensureDesignIdentities(root);
    const id = designIdOf(root);
    if (id) replaceElementVisibility([id], true);
  };

  const showAllHidden = () => {
    const ids: string[] = [];
    for (const [id, props] of Object.entries(dev.draft.elements)) {
      if (props.visibility === "hidden") ids.push(id);
    }
    replaceElementVisibility(ids, false);
  };

  const createVariation = (event: FormEvent) => {
    event.preventDefault();
    const title = variationTitle.trim();
    if (!title) return;
    const baseId = title.toLocaleLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "") || "variation";
    let id = baseId;
    let suffix = 2;
    while (studio.document.variations[id]) id = `${baseId}-${suffix++}`;
    studio.replaceDocument({
      ...studio.document,
      variations: {
        ...studio.document.variations,
        [id]: {
          id,
          title,
          extends: studio.activeVariationId || "full-data",
          patch: {},
        },
      },
      activeVariationId: id,
    });
    setVariationTitle("");
    setCreatingVariation(false);
  };

  const deleteActiveVariation = () => {
    const id = studio.activeVariationId;
    const removed = studio.document.variations[id];
    if (!removed || builtInIds.has(id)) return;
    const nextEntries: [string, (typeof studio.document.variations)[string]][] = [];
    for (const [candidate, variation] of Object.entries(studio.document.variations)) {
      if (candidate === id) continue;
      nextEntries.push([candidate, variation.extends === id
        ? { ...variation, extends: removed.extends }
        : variation]);
    }
    const variations = Object.fromEntries(nextEntries);
    studio.replaceDocument({
      ...studio.document,
      variations,
      activeVariationId: removed.extends && variations[removed.extends] ? removed.extends : "full-data",
    });
  };

  const setActiveParent = (parentId: string) => {
    const id = studio.activeVariationId;
    const active = studio.document.variations[id];
    if (!active || parentId === id) return;
    let cursor = parentId;
    while (cursor) {
      if (cursor === id) return;
      cursor = studio.document.variations[cursor]?.extends ?? "";
    }
    studio.replaceDocument({
      ...studio.document,
      variations: {
        ...studio.document.variations,
        [id]: { ...active, extends: parentId || undefined },
      },
    });
  };

  return (
    <div className="min-h-0 flex-1 overflow-y-auto">
      <section className="p-2" aria-labelledby="studio-variations-heading">
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
        {studio.activeVariationId ? (
          <div className="mt-2 flex items-center gap-1 px-2">
            <label className="min-w-0 flex-1 text-2xs text-t3">
              {extendsLabel}
              <select
                aria-label={variationParentLabel}
                value={studio.document.variations[studio.activeVariationId]?.extends ?? ""}
                onChange={(event) => setActiveParent(event.target.value)}
                className="mt-0.5 w-full rounded-control border border-line bg-field px-1 py-0.5 text-xs text-t1"
              >
                <option value="">{noneLabel}</option>
                {parentVariations.map((variation) => (
                  <option key={variation.id} value={variation.id}>{variation.title}</option>
                ))}
              </select>
            </label>
            {!builtInIds.has(studio.activeVariationId) ? (
              <button type="button" onClick={deleteActiveVariation} className="self-end rounded-control px-2 py-1 text-xs text-err-text hover:bg-err/10">
                {deleteLabel}
              </button>
            ) : null}
          </div>
        ) : null}
        {creatingVariation ? (
          <form onSubmit={createVariation} className="mt-2 flex gap-1 px-2">
            <input
              aria-label={variationNameLabel}
              autoFocus
              value={variationTitle}
              onChange={(event) => setVariationTitle(event.target.value)}
              className="min-w-0 flex-1 rounded-control border border-line bg-field px-1.5 py-1 text-xs text-t1"
            />
            <button type="submit" className="rounded-control bg-acc px-2 py-1 text-xs text-acc-on">{createLabel}</button>
          </form>
        ) : (
          <button type="button" onClick={() => setCreatingVariation(true)} className="mt-2 block w-full rounded-control px-2 py-1 text-left text-xs text-acc hover:bg-acc/10">
            {newVariationLabel}
          </button>
        )}
      </section>

      <section aria-labelledby="studio-structure-heading">
        <header className="flex items-center gap-1 bg-band px-2 py-1.5">
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
          <div className="mb-2 grid grid-cols-2 gap-1">
            <button
              type="button"
              aria-pressed={allElements}
              onClick={() => setAllElements((current) => !current)}
              className="rounded-control px-2 py-1 text-left text-2xs text-t2 hover:bg-raise2"
            >
              {allElementsLabel}
            </button>
            <button
              type="button"
              disabled={!dev.selectedDevId}
              onClick={() => dev.selectedDevId && replaceElementVisibility([dev.selectedDevId], true)}
              className="rounded-control px-2 py-1 text-left text-2xs text-t2 hover:bg-raise2 disabled:text-t5"
            >
              {hideSelectedLabel}
            </button>
            <button type="button" onClick={hideScreenContents} className="rounded-control px-2 py-1 text-left text-2xs text-t2 hover:bg-raise2">
              {hideScreenLabel}
            </button>
            <button type="button" onClick={showAllHidden} className="rounded-control px-2 py-1 text-left text-2xs text-t2 hover:bg-raise2">
              {showHiddenLabel}
            </button>
          </div>
          {visibleTargets.map((entry) => {
            const isHidden = dev.draft.elements[entry.ownerDevId ?? ""]?.visibility === "hidden";
            return (
            <button
              key={entry.key}
              type="button"
              data-target-key={entry.key}
              data-target-depth={entry.depth}
              onClick={() => entry.ownerDevId && dev.selectDevId(entry.ownerDevId)}
              className={
                "block w-full truncate rounded-control py-1 text-left text-xs hover:bg-raise2 " +
                (view === "hierarchy" ? "pr-2" : "px-2") +
                (dev.selectedDevId === entry.ownerDevId ? " bg-acc-soft text-t1" : " text-t2") +
                (isHidden ? " opacity-60 outline outline-1 outline-dashed outline-line2" : "")
              }
              style={view === "hierarchy" ? { paddingLeft: `${8 + entry.depth * 12}px` } : undefined}
              title={entry.id}
            >
              {entry.label}{entry.occurrences > 1 ? ` (${entry.occurrences})` : ""}{isHidden ? ` · ${hiddenLabel}` : ""}
            </button>
            );
          })}
        </div>
      </section>
    </div>
  );
}
