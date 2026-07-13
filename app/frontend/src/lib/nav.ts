/**
 * The single source of truth for the app's destinations. Both the rail and the
 * Ctrl+K palette derive their navigation from this list, so they can never
 * disagree. `available` gates what the user can actually reach: a surface only
 * appears once its page is really built and wired, never as an inert stub. As
 * each M6 sub-milestone ships its page, flip its flag and add the App route case.
 */
import type { Route } from "./router";

export interface NavEntry {
  route: Route;
  title: string;
  glyph: string;
  group: "primary" | "foot";
  available: boolean;
}

export const NAV: NavEntry[] = [
  { route: "components", title: "Components", glyph: "▤", group: "primary", available: true },
  { route: "ingest", title: "Ingest", glyph: "▽", group: "primary", available: true },
  { route: "duplicates", title: "Duplicates", glyph: "⧉", group: "primary", available: false },
  { route: "projects", title: "Projects", glyph: "▧", group: "primary", available: false },
  { route: "doctor", title: "Doctor", glyph: "✚", group: "foot", available: false },
  { route: "settings", title: "Settings", glyph: "⚙", group: "foot", available: true },
];

export function availableNav(): NavEntry[] {
  return NAV.filter((entry) => entry.available);
}
