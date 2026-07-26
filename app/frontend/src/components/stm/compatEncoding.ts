/**
 * The compatibility view's status encoding, shared by CompatUnionMap, CompatReconcileDetail, and
 * CompatVerdictBanner so all three read the same one classification->tone map (CONTEXT decision 3).
 * Status color runs ONLY through the Badge/Dot tone system here, never a scattered color literal.
 *
 * The tone map is frozen by CONTEXT: shared -> ok, divergent -> warn, partial -> neutral. An
 * un-swappable / blocking fact reads err. The SVG union map cannot mount the Dot span, so it paints
 * a small classification dot with TONE_VAR (the exact CSS-var tokens the Dot primitive uses), never
 * a filled pad background (VIZ-02 "color is data": the dot is the one place status color runs).
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

// The Badge/Dot tones as CSS-var fills, for the SVG map's classification dot only (the Dot span
// cannot render inside an <svg>). These are the exact tokens the Dot primitive paints with
// (bg-ok = --c-ok, bg-warn = --c-warn, bg-t3 = --c-t3, bg-err = --c-err), kept in lockstep.
export const TONE_VAR: Record<BadgeTone, string> = {
  ok: "var(--c-ok)",
  warn: "var(--c-warn)",
  err: "var(--c-err)",
  neutral: "var(--c-t3)",
};

export function classificationTone(c: Classification): BadgeTone {
  return CLASSIFICATION_TONE[c];
}
