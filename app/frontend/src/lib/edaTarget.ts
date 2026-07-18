/**
 * EDA-target readiness model. Settings picks a target EDA tool (KiCad or Altium); the
 * library then flags parts that are not ready for THAT tool. An asset counts toward a tool
 * only when its reference exists AND targets that tool (a ref with no `tool` defaults to
 * "kicad", matching the backend), so a part carrying only KiCad symbol/footprint reads as
 * ready for KiCad but not for Altium. Pure functions, no React: the panel and the Settings
 * rollup read readiness through this one module instead of each re-deriving it.
 */
import type { LibRef, ModelRef, PartDetail, PartSummary } from "../api/types";

export type EdaTool = "kicad" | "altium";

// The default tool a reference with no explicit `tool` targets (the backend default).
const DEFAULT_TOOL: EdaTool = "kicad";

// The selectable tools with their display labels (KiCad first: it is the default).
export const EDA_TOOLS: readonly { tool: EdaTool; label: string }[] = [
  { tool: "kicad", label: "KiCad" },
  { tool: "altium", label: "Altium" },
] as const;

// The human labels for the three asset kinds, in the order the readiness UI reports them.
const SYMBOL_LABEL = "Symbol";
const FOOTPRINT_LABEL = "Footprint";
const MODEL_LABEL = "3D Model";

// True when a reference exists and targets `tool` (an absent `tool` reads as the default).
function targets(ref: LibRef | ModelRef | null, tool: EdaTool): boolean {
  return ref != null && (ref.tool ?? DEFAULT_TOOL) === tool;
}

export interface AssetReadiness {
  symbol: boolean;
  footprint: boolean;
  model: boolean;
  // The human labels of the assets absent for `tool`, in Symbol/Footprint/3D Model order.
  missing: string[];
  // Ready when the symbol AND footprint are present for `tool`; the 3D model is optional
  // (reported in `missing` when absent, but never blocks readiness).
  ready: boolean;
}

// The per-tool asset readiness of one part detail. An asset counts only when its reference
// targets the selected tool; a KiCad-only part is therefore not ready for Altium.
export function assetReadiness(part: PartDetail, tool: EdaTool): AssetReadiness {
  const symbol = targets(part.symbol, tool);
  const footprint = targets(part.footprint, tool);
  const model = targets(part.model, tool);

  const missing: string[] = [];
  if (!symbol) missing.push(SYMBOL_LABEL);
  if (!footprint) missing.push(FOOTPRINT_LABEL);
  if (!model) missing.push(MODEL_LABEL);

  return { symbol, footprint, model, missing, ready: symbol && footprint };
}

export interface SummaryReadiness {
  ready: boolean;
  missing: string[];
}

// The readiness of a list-row summary. A PartSummary carries no per-tool asset detail, so
// only the default (kicad) tool can be judged from it (its is_complete/missing flags). For
// any non-default tool the summary cannot confirm the tool's assets exist, so it is treated
// conservatively as not-ready (missing that tool's symbol + footprint) until a summary
// grows per-tool fields to say otherwise.
export function summaryReadiness(part: PartSummary, tool: EdaTool): SummaryReadiness {
  if (tool === DEFAULT_TOOL) {
    return { ready: part.is_complete, missing: part.missing };
  }
  return { ready: false, missing: [SYMBOL_LABEL, FOOTPRINT_LABEL] };
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
