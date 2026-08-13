export const DEFAULT_DESIGN_GRID_SIZE = 8;

export function finiteDesignGridSize(
  value: string | number,
  fallback = DEFAULT_DESIGN_GRID_SIZE,
): number {
  if (typeof value === "string" && value.trim() === "") return fallback;
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return fallback;
  return Math.min(64, Math.max(1, Math.round(parsed)));
}
