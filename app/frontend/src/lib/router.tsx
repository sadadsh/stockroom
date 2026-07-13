/**
 * A tiny state-based router. One WebView2 window with base "./" has no URL
 * semantics to honor, so navigation is just an in-memory route. Pages read the
 * active route from context; the rail and the Ctrl+K palette navigate through it.
 */
import { createContext, useContext, useMemo, useState, type ReactNode } from "react";

export type Route =
  | "components"
  | "ingest"
  | "duplicates"
  | "projects"
  | "doctor"
  | "settings";

interface RouterValue {
  route: Route;
  navigate: (route: Route) => void;
}

const RouterContext = createContext<RouterValue | null>(null);

export function RouterProvider({
  children,
  initial = "components",
}: {
  children: ReactNode;
  initial?: Route;
}) {
  const [route, setRoute] = useState<Route>(initial);
  const value = useMemo<RouterValue>(
    () => ({ route, navigate: setRoute }),
    [route],
  );
  return <RouterContext.Provider value={value}>{children}</RouterContext.Provider>;
}

export function useRouter(): RouterValue {
  const ctx = useContext(RouterContext);
  if (!ctx) throw new Error("useRouter must be used within a RouterProvider");
  return ctx;
}
