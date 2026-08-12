import { AppShell } from "./components/AppShell";
import { OnboardingGate } from "./components/OnboardingGate";
import { CaptureStatusPill } from "./components/CaptureStatusPill";
import { LibraryPage } from "./pages/LibraryPage";
import { ProjectsPage } from "./pages/ProjectsPage";
import { StmViewerPage } from "./pages/StmViewerPage";
import { SettingsPage } from "./pages/SettingsPage";
import { useOnboarding } from "./api/queries";
import { useRouter, type Route } from "./lib/router";
import { useEffect } from "react";
import { useScenarioUiState } from "./design-studio/scenarioState";
import { useToast } from "./lib/toast";
import { ConfirmDialog } from "./components/ConfirmDialog";
import { useText } from "./lib/copy";

// The shell hosts whichever page the active route names. Routes light up as their
// pages ship (see lib/nav.ts + the M6 plan); only reachable routes get a case.
export default function App() {
  const { route } = useRouter();
  // First-run gate (M9c): a frozen exe ships no library, so on the very first launch the
  // user must choose one before any library feature is meaningful. Flip to the
  // gate ONLY when the backend positively reports first_run; while the status is loading,
  // errored, or already onboarded, render the app normally (no blank/flashing frame).
  const onboarding = useOnboarding();
  if (onboarding.data?.first_run) {
    return <OnboardingGate status={onboarding.data} />;
  }
  return (
    <>
      <AppShell>{renderRoute(route)}</AppShell>
      {/* The guided capture keeps running when the modal is closed; the pill is its handle. */}
      <CaptureStatusPill />
      <ScenarioGlobalEffects />
    </>
  );
}

function ScenarioGlobalEffects() {
  const scenario = useScenarioUiState();
  const { toast } = useToast();
  const neutralTitle = useText("scenario.confirm.neutral", "Confirm Change");
  const destructiveTitle = useText("scenario.confirm.destructive", "Delete Component");
  useEffect(() => {
    if (scenario.toast) return toast(scenario.toast.message, scenario.toast.tone, undefined, null);
  }, [scenario.toast, toast]);
  return (
    <ConfirmDialog
      open={scenario.confirmation !== undefined}
      title={scenario.confirmation?.danger ? destructiveTitle : neutralTitle}
      body="Review this fixture-backed operation before continuing."
      confirmLabel="Confirm"
      danger={scenario.confirmation?.danger}
      onConfirm={() => {}}
      onCancel={() => {}}
    />
  );
}

function renderRoute(route: Route) {
  switch (route) {
    case "components":
      // The Components flagship is just the Parts view now: Duplicates is a Parts
      // filter, and Doctor is in Settings.
      return <LibraryPage />;
    case "projects":
      return <ProjectsPage />;
    case "stm":
      return <StmViewerPage />;
    case "settings":
      return <SettingsPage />;
    default:
      // Unreachable in practice (the rail only offers available routes); fall back
      // to the Components home rather than a blank frame.
      return <LibraryPage />;
  }
}
