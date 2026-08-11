import { registerScenarios } from "../scenarioRegistry";
import { globalScenarios } from "./global";

export { globalScenarios } from "./global";

/** The shipped scenario set. Domain-specific scenarios are added by their owning feature. */
export const bootstrapScenarioRegistry = registerScenarios(globalScenarios);

export function scenarioById(id: string) {
  return bootstrapScenarioRegistry.scenarioById(id);
}

export function scenariosForArea(area: Parameters<typeof bootstrapScenarioRegistry.scenariosForArea>[0]) {
  return bootstrapScenarioRegistry.scenariosForArea(area);
}

export function searchScenarios(query: string) {
  return bootstrapScenarioRegistry.searchScenarios(query);
}
