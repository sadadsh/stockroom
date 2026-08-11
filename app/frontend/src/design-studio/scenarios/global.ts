import type {
  OnboardingStatus,
  ParametricFacets,
  SearchResponse,
  SetLibraryBody,
  UpdateCheck,
} from "../../api/types";
import type { DesignScenario, ScenarioFixture } from "../scenario";

const ONBOARDING_READY: OnboardingStatus = {
  onboarded: true,
  first_run: false,
  libraries_root: "C:\\Stockroom",
  profiles: [],
  under_git: true,
  default_dir: "C:\\Stockroom\\Components",
  libraries: [
    {
      name: "Components",
      path: "C:\\Stockroom\\Components",
      active: true,
      available: true,
      under_git: true,
    },
  ],
};

const ONBOARDING_FIRST_RUN: OnboardingStatus = {
  ...ONBOARDING_READY,
  onboarded: false,
  first_run: true,
  libraries: [],
};

const UPDATE_AVAILABLE: UpdateCheck = {
  update_available: true,
  state: "available",
  behind: 1,
  current_revision: "preview-current",
  target_revision: "preview-next",
  detail: "An update is available.",
};

const EMPTY_SEARCH: SearchResponse = { parts: [], count: 0 };
const EMPTY_PARAMETRIC_FACETS: ParametricFacets = { category: null, facets: [], total: 0 };

function onboardingFixture(
  response: OnboardingStatus,
): ScenarioFixture<OnboardingStatus, undefined> {
  return { method: "GET", path: "/api/onboarding", params: {}, body: undefined, response };
}

function coverage(state: string): readonly [`route:components`, `state:${string}`] {
  return ["route:components", `state:${state}`];
}

const common = {
  area: "global" as const,
  group: "Global",
  route: "components" as const,
};

/** Global preview cases that exercise existing production chrome without a parallel UI. */
export const globalScenarios: readonly DesignScenario[] = [
  {
    ...common,
    id: "global.real-data",
    title: "Real Data",
    fixtures: [],
    initialUi: {},
    expectedTargets: ["shell.root"],
    coverage: coverage("real-data"),
  },
  {
    ...common,
    id: "global.onboarding.open",
    title: "Onboarding Open",
    fixtures: [onboardingFixture(ONBOARDING_FIRST_RUN)],
    initialUi: { onboarding: { mode: "open" } },
    expectedTargets: ["onboarding.gate"],
    coverage: coverage("onboarding-open"),
  },
  {
    ...common,
    id: "global.onboarding.create",
    title: "Onboarding Create",
    fixtures: [
      onboardingFixture(ONBOARDING_FIRST_RUN),
      {
        method: "POST",
        path: "/api/onboarding/library",
        params: {},
        body: { mode: "create" } satisfies SetLibraryBody,
        response: ONBOARDING_READY,
        localOutcome: { state: "succeeded", target: "onboarding.gate" },
      } satisfies ScenarioFixture<OnboardingStatus, SetLibraryBody>,
    ],
    initialUi: { onboarding: { mode: "create" } },
    expectedTargets: ["onboarding.gate"],
    coverage: coverage("onboarding-create"),
  },
  {
    ...common,
    id: "global.onboarding.clone",
    title: "Onboarding Clone",
    fixtures: [
      onboardingFixture(ONBOARDING_FIRST_RUN),
      {
        method: "POST",
        path: "/api/onboarding/library",
        params: {},
        body: { mode: "clone", url: "https://example.test/components.git" } satisfies SetLibraryBody,
        response: ONBOARDING_READY,
        localOutcome: { state: "succeeded", target: "onboarding.gate" },
      } satisfies ScenarioFixture<OnboardingStatus, SetLibraryBody>,
    ],
    initialUi: { onboarding: { mode: "clone" } },
    expectedTargets: ["onboarding.gate"],
    coverage: coverage("onboarding-clone"),
  },
  {
    ...common,
    id: "global.onboarding.error",
    title: "Onboarding Error",
    fixtures: [onboardingFixture(ONBOARDING_FIRST_RUN)],
    initialUi: { onboarding: { mode: "open", error: "Could not set up the components" } },
    expectedTargets: ["onboarding.error"],
    coverage: coverage("onboarding-error"),
  },
  {
    ...common,
    id: "global.about.open",
    title: "About Open",
    fixtures: [
      onboardingFixture(ONBOARDING_READY),
      { method: "GET", path: "/api/update/check", params: {}, body: undefined, response: UPDATE_AVAILABLE } satisfies ScenarioFixture<UpdateCheck, undefined>,
    ],
    initialUi: { rail: { aboutOpen: true } },
    expectedTargets: ["about.root"],
    coverage: coverage("about-open"),
  },
  {
    ...common,
    id: "global.update.available",
    title: "Update Available",
    fixtures: [
      onboardingFixture(ONBOARDING_READY),
      { method: "GET", path: "/api/update/check", params: {}, body: undefined, response: UPDATE_AVAILABLE } satisfies ScenarioFixture<UpdateCheck, undefined>,
    ],
    initialUi: {},
    expectedTargets: ["rail.update"],
    coverage: coverage("update-available"),
  },
  {
    ...common,
    id: "global.search.open",
    title: "Search Open",
    fixtures: [
      onboardingFixture(ONBOARDING_READY),
      { method: "GET", path: "/api/library/search", params: {}, body: undefined, response: EMPTY_SEARCH } satisfies ScenarioFixture<SearchResponse, undefined>,
      { method: "GET", path: "/api/library/facets/parametric", params: {}, body: undefined, response: EMPTY_PARAMETRIC_FACETS } satisfies ScenarioFixture<ParametricFacets, undefined>,
    ],
    initialUi: { search: { open: true } },
    expectedTargets: ["search.query"],
    coverage: coverage("search-open"),
  },
  {
    ...common,
    id: "global.service-error",
    title: "Service Error",
    fixtures: [onboardingFixture(ONBOARDING_READY)],
    initialUi: { service: { error: "Service unavailable" } },
    expectedTargets: ["components.list-unreachable"],
    coverage: coverage("service-error"),
  },
];
