import { AppShell } from "./components/AppShell";
import { OnboardingGate } from "./components/OnboardingGate";
import { ErrorState, LoadingState } from "./components/productState";
import { CaptureStatusPill } from "./components/CaptureStatusPill";
import { LibraryPage } from "./pages/LibraryPage";
import { AssetsPage } from "./pages/AssetsPage";
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
  // The server revalidates the GitHub checkout and selected-tool connection on every read.
  // The shell opens only from that complete proof, never from the compatibility first_run flag.
  const onboarding = useOnboarding();
  if (onboarding.isPending) {
    return (
      <main className="flex min-h-screen items-center justify-center bg-app p-6">
        <LoadingState id="app.setup.checking">Checking setup...</LoadingState>
      </main>
    );
  }
  if (onboarding.isError || !onboarding.data) {
    return (
      <main data-dev-id="onboarding.setup-error" className="flex min-h-screen items-center justify-center bg-app p-6">
        <ErrorState id="app.setup.error">Stockroom could not check setup. Reconnect, then restart Stockroom.</ErrorState>
      </main>
    );
  }
  if (!onboarding.data.guided_setup.ready || !onboarding.data.onboarded) {
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
    case "assets":
      return <AssetsPage />;
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
