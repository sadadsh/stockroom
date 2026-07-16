import { AppShell } from "./components/AppShell";
import { OnboardingGate } from "./components/OnboardingGate";
import { LibraryPage } from "./pages/LibraryPage";
import { IngestPage } from "./pages/IngestPage";
import { ProjectsPage } from "./pages/ProjectsPage";
import { SettingsPage } from "./pages/SettingsPage";
import { useOnboarding } from "./api/queries";
import { useRouter, type Route } from "./lib/router";

// The shell hosts whichever page the active route names. Routes light up as their
// pages ship (see lib/nav.ts + the M6 plan); only reachable routes get a case.
export default function App() {
  const { route } = useRouter();
  // First-run gate (M9c): a frozen exe ships no library, so on the very first launch the
  // user must choose one before any library/project feature is meaningful. Flip to the
  // gate ONLY when the backend positively reports first_run; while the status is loading,
  // errored, or already onboarded, render the app normally (no blank/flashing frame).
  const onboarding = useOnboarding();
  if (onboarding.data?.first_run) {
    return <OnboardingGate status={onboarding.data} />;
  }
  return <AppShell>{renderRoute(route)}</AppShell>;
}

function renderRoute(route: Route) {
  switch (route) {
    case "components":
    case "bom":
    case "duplicates":
    case "doctor":
      // The library surfaces are tabs of the Library flagship; the route names
      // the active tab so the palette and drop overlay keep deep-linking.
      return <LibraryPage route={route} />;
    case "ingest":
      // Add A Part is a full-screen wizard, not a Library tab: it takes over the
      // content area (the rail stays lit on Library) with its own back-to-Parts
      // affordance. Still reached from the Parts toolbar, the palette, and a drop.
      return <IngestPage />;
    case "projects":
      return <ProjectsPage />;
    case "settings":
      return <SettingsPage />;
    default:
      // Unreachable in practice (the rail and palette only offer available
      // routes); fall back to the Library home rather than a blank frame.
      return <LibraryPage route="components" />;
  }
}
