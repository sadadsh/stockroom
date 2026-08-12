import { defineScenarioStateContracts } from "../scenarioStateContracts";
import { componentScenarioIds } from "./components";
import { globalScenarioIds } from "./global";
import { projectScenarioIds } from "./projects";
import { providerScenarioIds } from "./provider";
import { settingsScenarioIds } from "./settings";
import { stmScenarioIds } from "./stm";

export const globalStateContracts = defineScenarioStateContracts("global", "components", globalScenarioIds);
export const componentStateContracts = defineScenarioStateContracts("components", "components", componentScenarioIds);
export const providerStateContracts = defineScenarioStateContracts("components", "components", providerScenarioIds);
export const projectStateContracts = defineScenarioStateContracts("projects", "projects", projectScenarioIds);
export const stmStateContracts = defineScenarioStateContracts("stm", "stm", stmScenarioIds);
export const settingsStateContracts = defineScenarioStateContracts("settings", "settings", settingsScenarioIds);

/** Exact authority for the shipped scenario/state parity gate. */
export const bootstrapStateContracts = [
  ...globalStateContracts,
  ...componentStateContracts,
  ...providerStateContracts,
  ...projectStateContracts,
  ...stmStateContracts,
  ...settingsStateContracts,
] as const;
