import type { PartSummary } from "../../api/types";
import { SETTINGS_ONBOARDING } from "../fixtures/settingsFixtures";
import type { DesignScenario, ScenarioFixture } from "../scenario";

const PARTS: PartSummary[] = [
  {
    id: "needs-assets",
    display_name: "ADG714BRUZ-REEL",
    category: "Switches",
    mpn: "ADG714BRUZ-REEL",
    manufacturer: "Analog Devices",
    is_complete: false,
    missing: ["symbol", "footprint", "model"],
    eda_readiness: {
      altium: { required: ["symbol", "footprint", "model"], missing: ["symbol", "footprint", "model"], coverage_complete: false, trust: "unknown", ready: false },
    },
  },
  {
    id: "ready-assets",
    display_name: "LM358DR",
    category: "Integrated Circuits",
    mpn: "LM358DR",
    manufacturer: "Texas Instruments",
    is_complete: true,
    missing: [],
    eda_readiness: {
      altium: { required: ["symbol", "footprint", "model"], missing: [], coverage_complete: true, trust: "pass", ready: true },
    },
  },
];

function fixtures(): ScenarioFixture[] {
  return [
    { method: "GET", path: "/api/onboarding", params: {}, body: undefined, response: { ...SETTINGS_ONBOARDING, primary_eda: "altium" } },
    { method: "GET", path: "/api/library/parts", params: {}, body: undefined, response: { parts: PARTS, count: PARTS.length } },
  ];
}

function scenario(id: string, title: string): DesignScenario {
  return {
    id,
    title,
    area: "assets",
    group: "Assets",
    route: "assets",
    fixtures: fixtures(),
    initialUi: {},
    expectedTargets: ["assets.root"],
  };
}

export const assetsScenarios: readonly DesignScenario[] = [
  scenario("assets.landing", "Assets Landing"),
];
