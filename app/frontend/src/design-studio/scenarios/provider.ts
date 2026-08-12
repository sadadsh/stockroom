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

export const providerScenarios: readonly DesignScenario[] = providerScenarioIds.map((id) => {
  const state = id.slice("provider.".length) as ProviderFixtureState;
  return {
    id,
    title: TITLES[state],
    area: "components",
    group: "Provider Download",
    route: "components",
    fixtures: providerReadFixtures(state),
    initialUi: {
      components: { surface: "cad-sources" },
      provider: {
        state,
        nativeHostTargets: ["provider-back", "provider-forward", "stockroom-tab", "provider-tab"],
      },
    },
    expectedTargets: ["component-browser.complete-component", "component-browser.provider-browser"],
    coverage: ["route:components", `state:provider-${state}`],
  } satisfies DesignScenario;
});
