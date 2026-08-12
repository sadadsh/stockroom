import { registerScenarios } from "../scenarioRegistry";
import { settingsFixtureValidators } from "../fixtures/settingsFixtures";
import { componentScenarios } from "./components";
import { globalScenarios } from "./global";
import { projectScenarios } from "./projects";
import { providerScenarios } from "./provider";
import { stmScenarios } from "./stm";
import { settingsScenarios } from "./settings";
import { bootstrapStateContracts } from "./contracts";

export { globalScenarios } from "./global";
export { componentScenarios } from "./components";
export { projectScenarios } from "./projects";
export { providerScenarios } from "./provider";
export { stmScenarios } from "./stm";
export { settingsScenarios } from "./settings";
export { scenarioStateSignature } from "../scenario";

/** The shipped scenario set. Domain-specific scenarios are added by their owning feature. */
export const bootstrapScenarioRegistry = registerScenarios(
  [...globalScenarios, ...componentScenarios, ...providerScenarios, ...projectScenarios, ...stmScenarios, ...settingsScenarios],
  settingsFixtureValidators,
  bootstrapStateContracts,
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
