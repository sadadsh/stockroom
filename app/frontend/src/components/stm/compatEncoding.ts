/**
 * The compatibility view's status encoding, shared by CompatUnionMap, CompatReconcileDetail, and
 * CompatVerdictBanner so all three read the same one classification->tone map (CONTEXT decision 3).
 * Status color runs ONLY through the Badge/Dot tone system here, never a scattered color literal.
 *
 * The tone map is frozen by CONTEXT: shared -> ok, divergent -> warn, partial -> neutral. An
 * un-swappable / blocking fact reads err. The SVG union map cannot mount the Dot span, so it paints
 * its classification dot from unionClassificationHue instead, never a filled pad background
 * (VIZ-02 "color is data": the dot is the one place status color runs).
 */
import type { UnionPositionDTO } from "../../api/types";
import type { BadgeTone } from "../primitives";

export type Classification = UnionPositionDTO["classification"];

// CONTEXT tone map. Kept as the single source so the map, the reconcile detail, and the verdict
// banner never drift apart on what shared/divergent/partial look like.
export const CLASSIFICATION_TONE: Record<Classification, BadgeTone> = {
  shared: "ok",
  divergent: "warn",
  partial: "neutral",
};

// Title Case labels for the classification legend and headings (interactive/label text).
export const CLASSIFICATION_LABEL: Record<Classification, string> = {
  shared: "Shared",
  divergent: "Divergent",
  partial: "Partial",
};

export function classificationTone(c: Classification): BadgeTone {
  return CLASSIFICATION_TONE[c];
}
