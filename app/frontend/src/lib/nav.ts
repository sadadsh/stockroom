/**
 * The single source of truth for the app's destinations: the three top-level
 * surfaces (Components, Projects, Settings) shown in the rail. Add Parts is a
 * full-screen wizard off the Parts toolbar, not a route. The rail derives from
 * this list, so they can never disagree. `available` gates what the user can
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
