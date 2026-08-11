export type StudioViewport = "desktop-1366" | "desktop-1600" | "desktop-1920" | "custom";

export const RESPONSIVE_VIEWPORT_PRESETS = [
  { id: "desktop-1366", label: "1366 px", width: 1366 },
  { id: "desktop-1600", label: "1600 px", width: 1600 },
  { id: "desktop-1920", label: "1920 px", width: 1920 },
  { id: "custom", label: "Custom", width: null },
] as const satisfies readonly { id: StudioViewport; label: string; width: number | null }[];

export function finiteViewportWidth(raw: string, fallback: number): number {
  if (raw.trim() === "") return fallback;
  const parsed = Number(raw);
  return Number.isFinite(parsed) ? parsed : fallback;
}
