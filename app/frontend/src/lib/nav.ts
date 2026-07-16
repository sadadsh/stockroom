/**
 * The single source of truth for the app's destinations. The rail shows only the
 * top-level surfaces (Library, Projects, Settings); the library sub-surfaces
 * (Add Parts, BOM Coverage, Duplicates, Doctor) live under Library and are reached
 * by route so the Ctrl+K palette can still deep-link to each. How each renders is
 * the Library flagship's business: BOM Coverage and the two health tools are tabs
 * (Duplicates + Doctor fold behind one Library Health tab), while Add Parts is a
 * full-screen wizard off the Parts toolbar. Both the rail and the palette derive
 * from this list, so they can never disagree. `available` gates what the user can
 * actually reach: a surface only appears once its page is really built and wired.
 */
import type { Route } from "./router";

export interface NavEntry {
  route: Route;
  title: string;
  group: "primary" | "foot";
  available: boolean;
  // rail=false keeps a destination out of the rail (it lives under Library, as a
  // tab or the Add Parts wizard); parent names the rail entry that stays
  // highlighted while it is active.
  rail?: boolean;
  parent?: Route;
}

export const NAV: NavEntry[] = [
  { route: "components", title: "Components", group: "primary", available: true },
  { route: "ingest", title: "Add Parts", group: "primary", available: true, rail: false, parent: "components" },
  { route: "bom", title: "BOM Coverage", group: "primary", available: true, rail: false, parent: "components" },
  { route: "duplicates", title: "Duplicates", group: "primary", available: true, rail: false, parent: "components" },
  { route: "doctor", title: "Doctor", group: "primary", available: true, rail: false, parent: "components" },
  { route: "projects", title: "Projects", group: "primary", available: true },
  { route: "settings", title: "Settings", group: "foot", available: true },
];

export function availableNav(): NavEntry[] {
  return NAV.filter((entry) => entry.available);
}

/** The rail's entries: available top-level destinations only. */
export function railNav(): NavEntry[] {
  return availableNav().filter((entry) => entry.rail !== false);
}

/** The rail entry a route lights up: itself, or its parent for a folded tab. */
export function railRouteFor(route: Route): Route {
  return NAV.find((entry) => entry.route === route)?.parent ?? route;
}
