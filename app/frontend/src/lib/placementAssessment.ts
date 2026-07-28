/**
 * Conservative placement diagnostics for a 3D model projected against its footprint.
 *
 * This does not try to prove a placement correct—geometry alone cannot do that. It only catches
 * source data that is obviously implausible (wrong units, a model many land-pattern widths away,
 * completely below the board, etc.) so Auto mode can avoid presenting bad KiCad metadata as fact.
 * Borderline placements stay visible and are left to the human inspection controls.
 */
export interface Bounds3 {
  min: [number, number, number];
  max: [number, number, number];
}

export interface PlacementPad {
  at: [number, number];
  size: [number, number];
  rotation: number;
}

export interface PlacementAssessment {
  status: "plausible" | "suspect" | "unavailable";
  issues: string[];
  metrics: {
    centerOffsetRatio: number | null;
    sizeRatio: number | null;
    verticalOffsetRatio: number | null;
  };
}

const emptyMetrics = {
  centerOffsetRatio: null,
  sizeRatio: null,
  verticalOffsetRatio: null,
};

function finiteBounds(bounds: Bounds3): boolean {
  return [...bounds.min, ...bounds.max].every(Number.isFinite);
}

export function assessPlacement(
  model: Bounds3 | null,
  pads: PlacementPad[],
): PlacementAssessment {
  if (!model || !finiteBounds(model) || !pads.length) {
    return { status: "unavailable", issues: [], metrics: emptyMetrics };
  }

  let minX = Infinity;
  let maxX = -Infinity;
  let minZ = Infinity;
  let maxZ = -Infinity;
  for (const pad of pads) {
    const angle = (pad.rotation * Math.PI) / 180;
    const c = Math.abs(Math.cos(angle));
    const s = Math.abs(Math.sin(angle));
    const halfX = (c * pad.size[0] + s * pad.size[1]) / 2;
    const halfZ = (s * pad.size[0] + c * pad.size[1]) / 2;
    minX = Math.min(minX, pad.at[0] - halfX);
    maxX = Math.max(maxX, pad.at[0] + halfX);
    minZ = Math.min(minZ, pad.at[1] - halfZ);
    maxZ = Math.max(maxZ, pad.at[1] + halfZ);
  }

  const landWidth = Math.max(maxX - minX, 1e-6);
  const landDepth = Math.max(maxZ - minZ, 1e-6);
  const landSpan = Math.max(landWidth, landDepth);
  const landCenterX = (minX + maxX) / 2;
  const landCenterZ = (minZ + maxZ) / 2;
  const modelWidth = Math.max(model.max[0] - model.min[0], 0);
  const modelDepth = Math.max(model.max[2] - model.min[2], 0);
  const modelSpan = Math.max(modelWidth, modelDepth);
  const modelCenterX = (model.min[0] + model.max[0]) / 2;
  const modelCenterZ = (model.min[2] + model.max[2]) / 2;
  const centerOffsetRatio =
    Math.hypot(modelCenterX - landCenterX, modelCenterZ - landCenterZ) / landSpan;
  const sizeRatio = modelSpan / landSpan;
  const verticalOffsetRatio = Math.abs(model.min[1]) / landSpan;

  const issues: string[] = [];
  // Deliberately broad limits: connectors and odd mechanical parts can be much larger than their
  // pad field. These thresholds catch unit/frame failures, not stylistic disagreements.
  if (sizeRatio < 0.002 || sizeRatio > 50) issues.push("Model scale is implausible for the pad field");
  if (centerOffsetRatio > 4) issues.push("Model is far from the footprint origin");
  if (model.max[1] < -landSpan * 0.1) issues.push("Model is entirely below the board plane");
  if (verticalOffsetRatio > 4) issues.push("Model height offset is implausible for the footprint");

  return {
    status: issues.length ? "suspect" : "plausible",
    issues,
    metrics: { centerOffsetRatio, sizeRatio, verticalOffsetRatio },
  };
}

