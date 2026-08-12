import type { ProjectCollaboration } from "../../api/types";
import {
  PROJECT_IDS,
  SHARED_REVIEW_EVIDENCE,
  SHARED_REVIEWS,
  projectReadFixtures,
  type ProjectEda,
  type ProjectFixtureOptions,
} from "../fixtures/projectFixtures";
import type { DesignScenario, ScenarioUiState } from "../scenario";

export const projectScenarioIds = [
  "projects.loading",
  "projects.empty",
  "projects.list-error",
  "projects.workspace-error",
  "projects.kicad.overview",
  "projects.kicad.bom",
  "projects.kicad.build",
  "projects.kicad.activity",
  "projects.altium.overview",
  "projects.altium.bom",
  "projects.altium.build",
  "projects.altium.activity",
  "projects.render-blocked",
  "projects.native-render-ready",
  "projects.missing-kicad",
  "projects.missing-altium",
  "projects.overlay-blocked",
  "projects.no-repository",
  "projects.diverged",
  "projects.shared-review",
  "projects.build-complete",
] as const;

type ProjectScenarioId = (typeof projectScenarioIds)[number];
type ProjectWorkbench = "overview" | "bom" | "build" | "activity";

function scenario(
  id: ProjectScenarioId,
  options: {
    title: string;
    fixtures?: ProjectFixtureOptions;
    initialUi?: ScenarioUiState;
    expectedTargets: string[];
  },
): DesignScenario {
  return {
    id,
    title: options.title,
    area: "projects",
    group: "Projects",
    route: "projects",
    fixtures: projectReadFixtures(options.fixtures),
    initialUi: options.initialUi ?? {},
    expectedTargets: options.expectedTargets,
    coverage: ["route:projects", `state:${id.slice("projects.".length)}`],
  };
}

function projectUi(eda: ProjectEda, tab: ProjectWorkbench): ScenarioUiState {
  return { projects: { selectedId: PROJECT_IDS[eda], activeTab: tab } };
}

function workbenchScenario(eda: ProjectEda, tab: ProjectWorkbench): DesignScenario {
  const editor = eda === "kicad" ? "KiCad" : "Altium";
  return scenario(`projects.${eda}.${tab}`, {
    title: `${editor} ${tab === "activity" ? "Recent Work" : tab[0].toUpperCase() + tab.slice(1)}`,
    fixtures: { selectedEda: eda },
    initialUi: projectUi(eda, tab),
    expectedTargets: [`projects.${tab}`],
  });
}

const noRepository: ProjectCollaboration["repository"] = null;
export const projectScenarios: readonly DesignScenario[] = [
  scenario("projects.loading", {
    title: "Loading Projects",
    fixtures: { listBehavior: { state: "pending" } },
    expectedTargets: ["projects.picker.loading", "projects.loading"],
  }),
  scenario("projects.empty", {
    title: "No Linked Projects",
    fixtures: { projects: [] },
    expectedTargets: ["projects.empty"],
  }),
  scenario("projects.list-error", {
    title: "Project List Error",
    fixtures: {
      listBehavior: { state: "error", status: 503, message: "Project registry unavailable." },
    },
    expectedTargets: ["projects.picker.failed"],
  }),
  scenario("projects.workspace-error", {
    title: "Project Workspace Error",
    fixtures: {
      selectedEda: "kicad",
      workspaceBehavior: { state: "error", status: 500, message: "Project workspace unavailable." },
    },
    initialUi: projectUi("kicad", "overview"),
    expectedTargets: ["projects.workspace.error"],
  }),
  ...(["overview", "bom", "build", "activity"] as const).map((tab) =>
    workbenchScenario("kicad", tab),
  ),
  ...(["overview", "bom", "build", "activity"] as const).map((tab) =>
    workbenchScenario("altium", tab),
  ),
  scenario("projects.render-blocked", {
    title: "Native Render Blocked",
    fixtures: {
      selectedEda: "kicad",
      geometryState: "render-blocked",
      visualState: "blocked",
      blockNativeActions: true,
    },
    initialUi: projectUi("kicad", "overview"),
    expectedTargets: ["projects.overview", "projects.native-action-blocked"],
  }),
  scenario("projects.native-render-ready", {
    title: "Native Render Ready",
    fixtures: { selectedEda: "kicad", visualState: "native-ready" },
    initialUi: projectUi("kicad", "overview"),
    expectedTargets: ["projects.overview", "projects.native-board-render"],
  }),
  scenario("projects.missing-kicad", {
    title: "KiCad Missing",
    fixtures: { selectedEda: "kicad", runtimeState: "missing", geometryState: "missing" },
    initialUi: projectUi("kicad", "overview"),
    expectedTargets: ["projects.overview", "projects.runtime-missing"],
  }),
  scenario("projects.missing-altium", {
    title: "Altium Missing",
    fixtures: { selectedEda: "altium", runtimeState: "missing", geometryState: "missing" },
    initialUi: projectUi("altium", "overview"),
    expectedTargets: ["projects.overview", "projects.runtime-missing"],
  }),
  scenario("projects.overlay-blocked", {
    title: "Editor Overlay Blocked",
    fixtures: { selectedEda: "kicad", geometryState: "overlay-blocked", visualState: "blocked" },
    initialUi: projectUi("kicad", "overview"),
    expectedTargets: ["projects.overview", "projects.placement-blocked"],
  }),
  scenario("projects.no-repository", {
    title: "No Repository",
    fixtures: { selectedEda: "kicad", repository: noRepository },
    initialUi: projectUi("kicad", "activity"),
    expectedTargets: ["projects.activity", "projects.no-repository"],
  }),
  scenario("projects.diverged", {
    title: "Repository Diverged",
    fixtures: { selectedEda: "kicad", diverged: true },
    initialUi: projectUi("kicad", "activity"),
    expectedTargets: ["projects.activity", "projects.repository-diverged"],
  }),
  scenario("projects.shared-review", {
    title: "Shared Review",
    fixtures: {
      selectedEda: "kicad",
      reviews: SHARED_REVIEWS,
      reviewEvidence: SHARED_REVIEW_EVIDENCE,
    },
    initialUi: projectUi("kicad", "activity"),
    expectedTargets: ["projects.activity", "projects.shared-review"],
  }),
  scenario("projects.build-complete", {
    title: "Build Complete",
    fixtures: { selectedEda: "kicad", completedAssembly: true },
    initialUi: projectUi("kicad", "build"),
    expectedTargets: ["projects.build", "projects.build-complete"],
  }),
];
