/**
 * The three CAD assets as a SET: the order they are read in, which window one opens into, and the
 * two facts read straight off a representation's chosen reference.
 *
 * Nothing here draws anything, and that is exactly why it is a module of its own rather than a
 * second export on `CadAssetModule.tsx`. The reading order is consulted by the column that stacks
 * the three modules and by the coverage table that sorts the payload's artifact list; the preview
 * kind is consulted by the workspace, which owns the full-size window; the source and the format
 * are read off a reference by whoever is describing an asset. Hanging any of that off a component
 * file would tie four unrelated consumers to that component's refresh boundary for facts that have
 * no rendering in them at all.
 */
import type { RepresentationKind, RepresentationView } from "../../api/dossierTypes";
import type { PreviewKind } from "../PreviewModal";

/**
 * The READING ORDER of the three CAD modules, and the only place it is decided.
 *
 * 3D Model, then Footprint, then Symbol - the owner's order, and the inspection order it implies:
 * the body you can recognise on sight, then the land pattern it has to sit on, then the schematic
 * abstraction of it. The previous order was the order the files are AUTHORED in, which is not the
 * order anyone checks them in.
 *
 * The backend's `ASSET_KINDS` is deliberately NOT reordered to match. That tuple is a storage and
 * domain ordering - it decides the key order of persisted part JSON and the sequence of the
 * library-wide readiness lists - so reordering it would rewrite files and move text on surfaces
 * nobody asked about. The payload states the SET; this states the reading order, and every consumer
 * that renders the three in sequence goes through here (see `ProviderCoverageMatrix`, which sorts the
 * payload's artifact list by this array rather than trusting its order).
 */
export const REPRESENTATION_KINDS: readonly RepresentationKind[] = [
  "model",
  "footprint",
  "symbol",
];

/** Which representation a full preview should open on. `model` is the 3D body's own preview kind. */
export function previewKindFor(kind: RepresentationKind): PreviewKind {
  return kind === "model" ? "model" : kind;
}

/** The file format the asset is held in, from the reference itself. Never an application name. */
export function assetFormat(view: RepresentationView): string {
  const tool = view.tools.find((entry) => entry.tool === view.selectedTool) ?? view.tools[0];
  const file = tool?.reference.file ?? "";
  const dot = file.lastIndexOf(".");
  return dot > 0 ? file.slice(dot + 1).toUpperCase() : "";
}
