import { AppShell } from "./components/AppShell";
import { ComponentsPage } from "./pages/ComponentsPage";
import { IngestPage } from "./pages/IngestPage";
import { useRouter, type Route } from "./lib/router";

// The shell hosts whichever page the active route names. Routes light up as their
// pages ship (see lib/nav.ts + the M6 plan); only reachable routes get a case.
export default function App() {
  const { route } = useRouter();
  return <AppShell>{renderRoute(route)}</AppShell>;
}

function renderRoute(route: Route) {
  switch (route) {
    case "components":
      return <ComponentsPage />;
    case "ingest":
      return <IngestPage />;
    default:
      // Unreachable in practice (the rail and palette only offer available
      // routes); fall back to the Components home rather than a blank frame.
      return <ComponentsPage />;
  }
}
