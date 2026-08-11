import { createContext, useContext, type ReactNode } from "react";
import type { ScenarioUiState } from "./scenario";

const EMPTY_SCENARIO_UI: Readonly<ScenarioUiState> = {};
const ScenarioUiContext = createContext<Readonly<ScenarioUiState>>(EMPTY_SCENARIO_UI);

/** Scoped preview UI state. Outside a scenario, production components retain their normal defaults. */
export function ScenarioUiProvider({ state, children }: { state: Readonly<ScenarioUiState>; children: ReactNode }) {
  return <ScenarioUiContext.Provider value={state}>{children}</ScenarioUiContext.Provider>;
}

export function useScenarioUiState(): Readonly<ScenarioUiState> {
  return useContext(ScenarioUiContext);
}
