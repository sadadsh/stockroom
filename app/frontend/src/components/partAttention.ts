/**
 * What the parts picker says about an incomplete part, and what a gap is CALLED there.
 *
 * Declared beside `PartsList.tsx` rather than in it: a module that exports both components and
 * plain functions is not a Fast Refresh boundary, so the picker could not hot-swap. This is the
 * plain-function half, and `PartsList.test.tsx` exercises it directly.
 */
import type { PartSummary } from "../api/types";

export interface PartAttention {
  reason: string;
  /**
   * The whole sentence, for the row's tooltip and its accessible label - reason AND what Stockroom
   * will do next.
   *
   * The next step used to have a LINE of its own in the row, and at a 290px picker it rendered as
   * `Next: Collecting Ev...`, which names nothing and promises nothing. A hint cut mid-word is
   * worse than no hint, so the row states the reason and this states the rest.
   */
  description: string;
}

/**
 * What a gap is CALLED in the picker.
 *
 * An EDA application's name never appears during ordinary component inspection, and browsing the
 * library is the most ordinary inspection there is. A key that arrives tool-qualified
 * (`kicad_model`, `altium_footprint`) names the same engineering artifact whichever tool can read
 * it, so the tool prefix is dropped and the ASSET is what the row states: a person scanning the
 * picker is asking "what is this part missing", not "which application could open the file".
 *
 * EDA compatibility is a real question with a real home - Export Component..., Open In...,
 * Compatibility Settings... - and this is not it.
 */
const ASSET_LABELS: Record<string, string> = {
  symbol: "Symbol",
  footprint: "Footprint",
  model: "3D Model",
  "3d model": "3D Model",
};

function missingLabel(value: string): string {
  const withoutTool = value.replace(/^(?:kicad|altium|eagle|orcad|easyeda)[_\s-]*/i, "");
  const spaced = withoutTool.replace(/[_-]+/g, " ").trim();
  const asset = ASSET_LABELS[spaced.toLowerCase()];
  if (asset) return asset;
  return spaced.replace(/\b\w/g, (character) => character.toUpperCase());
}

/**
 * The list warning is a decision summary, not a decorative triangle. It names
 * the blocking fact and the automatic next step in the same compact row.
 */
export function partAttention(part: PartSummary): PartAttention | null {
  if (part.is_complete) return null;
  // Deduplicated: two tools missing the same artifact is ONE gap in the part, and listing it
  // twice was only ever legible because the tool names made the entries look different.
  const missing = [...new Set(part.missing.flatMap((key) => missingLabel(key) || []))];
  const reason =
    missing.length === 0
      ? "Verification Evidence Pending"
      : missing.length <= 2
        ? `Missing ${missing.join(" + ")}`
        : `Missing ${missing[0]} + ${missing.length - 1} More`;
  const exactReason =
    missing.length > 0
      ? `Missing ${missing.join(", ")}`
      : "Verification evidence is incomplete";
  return {
    reason,
    description: `Needs Attention. ${exactReason}. Next: Stockroom will continue source collection and verification.`,
  };
}
