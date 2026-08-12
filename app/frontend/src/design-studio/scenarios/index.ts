import { registerScenarios } from "../scenarioRegistry";
import { projectFixtureValidators } from "../fixtures/projectFixtures";
import { componentScenarios } from "./components";
import { globalScenarios } from "./global";
import { projectScenarios } from "./projects";
import { providerScenarios } from "./provider";

export { globalScenarios } from "./global";
export { componentScenarios } from "./components";
export { projectScenarios } from "./projects";
export { providerScenarios } from "./provider";

/** The shipped scenario set. Domain-specific scenarios are added by their owning feature. */
export const bootstrapScenarioRegistry = registerScenarios(
  [...globalScenarios, ...componentScenarios, ...providerScenarios, ...projectScenarios],
  projectFixtureValidators,
);

export function scenarioById(id: string) {
  return bootstrapScenarioRegistry.scenarioById(id);
}

export function scenariosForArea(area: Parameters<typeof bootstrapScenarioRegistry.scenariosForArea>[0]) {
  return bootstrapScenarioRegistry.scenariosForArea(area);
}

export function searchScenarios(query: string) {
  return bootstrapScenarioRegistry.searchScenarios(query);
}
