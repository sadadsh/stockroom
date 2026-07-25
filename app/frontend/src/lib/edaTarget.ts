/**
 * EDA-target readiness model. Settings picks a target EDA tool; the library then flags parts
 * that are not ready for THAT tool. Pure functions, no React: the panel and the Settings
 * rollup read readiness through this one module instead of each re-deriving it.
 *
 * Readiness is now GENERIC. A part carries one symmetric asset bundle per tool
 * (`detail.eda[tool]`, matching `stockroom.model.part.EdaAssets`), and the tool's facts come
 * from `edaRegistry.generated.ts`, which is generated from the Python registry and gated by a
 * pytest. So "is this part ready for tool X" is the same check for every tool, and adding a
 * third tool changes nothing here.
 *
 * That symmetry is the fix, not a refactor. This module used to branch:
 * `if (tool === "altium")` read `part.altium_symbol`, while the KiCad path read `part.symbol`
 * -- and because Altium had no 3D-model slot at all, the branch simply asserted
 * `model = true`. Any part whose Altium assets were attached still read "CAD Incomplete"
 * forever (live 2026-07-24, reported ~10 times). A branch per tool is how that happens; a
 * uniform lookup is how it cannot.
 */
import { ASSET_LABELS, DEFAULT_EDA_TOOL, EDA_TOOLS, edaTool } from "./edaRegistry.generated";
import type { AssetRef, EdaAssets, PartDetail, PartSummary } from "../api/types";

export type EdaTool = string;

export { DEFAULT_EDA_TOOL };

// The selectable tools with their display labels, in the registry's own order (KiCad first:
// it is the default and the library Stockroom itself writes).
export const EDA_TOOL_OPTIONS: readonly { tool: EdaTool; label: string }[] = EDA_TOOLS.map(
  (t) => ({ tool: t.key, label: t.label }),
);

// Title Case labels for the readiness UI (the design contract: Title Case for interactive
// labels and headings). The registry's lower-case kind labels are the record-level wording.
const TITLE_LABELS: Record<string, string> = {
  symbol: "Symbol",
  footprint: "Footprint",
  model: "3D Model",
};

/** The Title Case name of an asset kind, for interactive labels and headings (the
 * design contract: Title Case for controls, sentence case for body prose). */
export function assetTitleLabel(kind: string): string {
  return TITLE_LABELS[kind] ?? ASSET_LABELS[kind] ?? kind;
}

const EMPTY_ASSETS: EdaAssets = { symbol: null, footprint: null, model: null };

/** A part's asset bundle for one tool. Absent tools read as an empty bundle, never as
 * another tool's assets. */
export function assetsFor(part: Pick<PartDetail, "eda">, tool: EdaTool): EdaAssets {
  return part.eda?.[tool] ?? EMPTY_ASSETS;
}

/** True when a reference actually resolves: an entry-shaped asset by `name`, a file-shaped
 * one (a 3D model) by `file`. A container with no entry is NOT present. Mirrors
 * `stockroom.model.part.asset_present`. */
export function assetPresent(ref: AssetRef | null | undefined): boolean {
  return !!ref && !!(ref.name || ref.file);
}

export interface AssetReadiness {
  /** Per-kind presence, e.g. `{ symbol: true, footprint: false, model: false }`. */
  present: Record<string, boolean>;
  /** The Title Case labels of the assets absent for `tool`, in the tool's kind order. */
  missing: string[];
  /**
   * Asset kinds this tool cannot be given by reference at all, mapped to why (Altium's 3D
   * model lives inside the footprint's .PcbLib binary). These are NEVER counted as missing:
   * reporting a gap that can never be closed is what "CAD Incomplete forever" looked like.
   */
  unsupported: Record<string, string>;
  /** Ready when the symbol AND footprint are present; a 3D model is reported when absent but
   * never blocks readiness (a footprint places fine without one). */
  ready: boolean;
}

// The per-tool asset readiness of one part detail.
export function assetReadiness(part: PartDetail, tool: EdaTool): AssetReadiness {
  const spec = edaTool(tool);
  const assets = assetsFor(part, tool);
  const kinds = spec?.assetKinds ?? ["symbol", "footprint", "model"];
  const unsupported = spec?.unsupportedAssets ?? {};

  const present: Record<string, boolean> = {};
  const missing: string[] = [];
  for (const kind of kinds) {
    if (kind in unsupported) continue;
    // A passive references the stock footprint, which carries its own 3D body, so it needs
    // no owned model. Mirrors PartRecord.missing_assets.
    if (kind === "model" && part.passive) {
      present[kind] = true;
      continue;
    }
    const ok = assetPresent(assets[kind as keyof EdaAssets]);
    present[kind] = ok;
    if (!ok) missing.push(assetTitleLabel(kind));
  }

  return {
    present,
    missing,
    unsupported,
    ready: !!present.symbol && !!present.footprint,
  };
}

export interface SummaryReadiness {
  ready: boolean;
  missing: string[];
}

// The readiness of a list-row summary. A PartSummary carries no per-tool asset detail, so
// only the default tool can be judged from it (its is_complete/missing flags). For any other
// tool the summary cannot confirm that tool's assets exist, so it is treated conservatively
// as not-ready until a summary grows per-tool fields to say otherwise.
export function summaryReadiness(part: PartSummary, tool: EdaTool): SummaryReadiness {
  if (tool === DEFAULT_EDA_TOOL) {
    return { ready: part.is_complete, missing: part.missing };
  }
  return { ready: false, missing: [assetTitleLabel("symbol"), assetTitleLabel("footprint")] };
}

export interface LibraryReadiness {
  total: number;
  complete: number;
  incomplete: number;
  // The ids of the parts not ready for the selected tool (the ones the library flags red).
  notReadyIds: string[];
}

// The library-wide readiness rollup the Settings panel shows for the selected tool.
export function libraryReadiness(parts: PartSummary[], tool: EdaTool): LibraryReadiness {
  const notReadyIds: string[] = [];
  for (const part of parts) {
    if (!summaryReadiness(part, tool).ready) notReadyIds.push(part.id);
  }
  return {
    total: parts.length,
    complete: parts.length - notReadyIds.length,
    incomplete: notReadyIds.length,
    notReadyIds,
  };
}
