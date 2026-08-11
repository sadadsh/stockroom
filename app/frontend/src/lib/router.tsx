/**
 * A tiny hash-backed router for the one Stockroom WebView2 window.
 *
 * The native update host keeps the same public origin and preserves the active
 * path, query, and hash while it adopts or rolls back a worker. Keeping the
 * route in a strict same-document hash therefore lets a renderer reload return
 * to the page the person was using. Unknown hashes never become URLs or route
 * names: they fail closed to Components and are replaced with the canonical
 * local hash.
 */
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { readUiSession, updateUiSession } from "./uiSession";

export const PRODUCTION_ROUTES = ["components", "projects", "stm", "settings"] as const;
export type Route = (typeof PRODUCTION_ROUTES)[number];

interface RouterValue {
  route: Route;
  navigate: (route: Route) => void;
}

const RouterContext = createContext<RouterValue | null>(null);
const DEFAULT_ROUTE: Route = "components";
const ROUTES: ReadonlySet<Route> = new Set(PRODUCTION_ROUTES);
const ROUTE_HASH_PREFIX = "#route=";

function isRoute(value: unknown): value is Route {
  return typeof value === "string" && ROUTES.has(value as Route);
}

function routeHash(route: Route): string {
  return `${ROUTE_HASH_PREFIX}${route}`;
}

function routeFromHash(hash: string, initial: Route): Route {
  if (!hash) return initial;
  if (!hash.startsWith(ROUTE_HASH_PREFIX)) return DEFAULT_ROUTE;
  const candidate = hash.slice(ROUTE_HASH_PREFIX.length);
  return isRoute(candidate) ? candidate : DEFAULT_ROUTE;
}

function currentRoute(initial: Route): Route {
  if (typeof window === "undefined") return initial;
  const restored = readUiSession().route;
  return routeFromHash(window.location.hash, isRoute(restored) ? restored : initial);
}

function persistRoute(route: Route): void {
  if (readUiSession().route === route) return;
  updateUiSession((current) => ({ ...current, route }));
}

function replaceRouteHash(route: Route): void {
  if (typeof window === "undefined") return;
  const hash = routeHash(route);
  if (window.location.hash === hash) return;
  window.history.replaceState(window.history.state, "", hash);
}

function pushRouteHash(route: Route): void {
  if (typeof window === "undefined") return;
  const hash = routeHash(route);
  if (window.location.hash === hash) return;
  window.history.pushState(window.history.state, "", hash);
}

export function RouterProvider({
  children,
  initial = "components",
}: {
  children: ReactNode;
  initial?: Route;
}) {
  const [route, setRoute] = useState<Route>(() => currentRoute(initial));

  useEffect(() => {
    // Canonicalize an empty or untrusted fragment without adding a history
    // entry. This also gives the first Components screen a reloadable route.
    replaceRouteHash(route);
    persistRoute(route);

    const restoreRoute = () => {
      const restored = currentRoute(initial);
      setRoute(restored);
      replaceRouteHash(restored);
      persistRoute(restored);
    };
    window.addEventListener("popstate", restoreRoute);
    window.addEventListener("hashchange", restoreRoute);
    return () => {
      window.removeEventListener("popstate", restoreRoute);
      window.removeEventListener("hashchange", restoreRoute);
    };
  }, [initial, route]);

  const navigate = useCallback(
    (next: Route) => {
      const safe = isRoute(next) ? next : DEFAULT_ROUTE;
      if (safe === route) {
        replaceRouteHash(safe);
        return;
      }
      pushRouteHash(safe);
      persistRoute(safe);
      setRoute(safe);
    },
    [route],
  );

  const value = useMemo<RouterValue>(
    () => ({ route, navigate }),
    [navigate, route],
  );
  return <RouterContext.Provider value={value}>{children}</RouterContext.Provider>;
}

export function useRouter(): RouterValue {
  const ctx = useContext(RouterContext);
  if (!ctx) throw new Error("useRouter must be used within a RouterProvider");
  return ctx;
}
