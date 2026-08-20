import { providerReadFixtures, type ProviderFixtureState } from "../fixtures/providerFixtures";
import type { DesignScenario } from "../scenario";

export const providerScenarioIds = [
  "provider.loading",
  "provider.ready",
  "provider.sign-in",
  "provider.waiting-for-person",
  "provider.format-selection",
  "provider.download-armed",
  "provider.one-file",
  "provider.multiple-files",
  "provider.partial-retained",
  "provider.unavailable",
  "provider.timeout",
  "provider.canceled",
  "provider.error",
  "provider.selected-file-recovery",
  "provider.returned-to-stockroom",
  "provider.complete",
] as const;

const TITLES: Record<ProviderFixtureState, string> = {
  loading: "Loading",
  ready: "Ready",
  "sign-in": "Sign In",
  "waiting-for-person": "Waiting For Person",
  "format-selection": "Format Selection",
  "download-armed": "Download Armed",
  "one-file": "One File",
  "multiple-files": "Multiple Files",
  "partial-retained": "Partial Retained",
  unavailable: "Unavailable",
  timeout: "Timeout",
  canceled: "Canceled",
  error: "Error",
  "selected-file-recovery": "Selected File Recovery",
  "returned-to-stockroom": "Returned To Stockroom",
  complete: "Complete",
};

const BROWSER_VISIBLE_STATES = new Set<ProviderFixtureState>([
  "loading",
  "ready",
  "sign-in",
  "waiting-for-person",
  "format-selection",
  "download-armed",
  "one-file",
  "multiple-files",
  "partial-retained",
]);

export const providerScenarios: readonly DesignScenario[] = providerScenarioIds.map((id) => {
  const state = id.slice("provider.".length) as ProviderFixtureState;
  return {
    id,
    title: TITLES[state],
    area: "assets",
    group: "Provider Download",
    route: "assets",
    fixtures: providerReadFixtures(state),
    initialUi: {
      components: { cadView: "manage-models" },
      provider: { state },
    },
    expectedTargets: [
      "component-browser.manage-models",
      BROWSER_VISIBLE_STATES.has(state)
        ? "component-browser.provider-viewport"
        : "component-browser.provider-status",
    ],
  } satisfies DesignScenario;
});
