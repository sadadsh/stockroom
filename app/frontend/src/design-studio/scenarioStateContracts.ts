import type { Route } from "../lib/router";
import type { ScenarioArea } from "./scenario";

/** A state contract is owned by its product domain, independently of scenario presentation data. */
export interface ScenarioStateContract<TId extends string = string> {
  id: TId;
  area: ScenarioArea;
  route: Route;
}

export function defineScenarioStateContracts<const TIds extends readonly string[]>(
  area: ScenarioArea,
  route: Route,
  ids: TIds,
): readonly ScenarioStateContract<TIds[number]>[] {
  return ids.map((id) => ({ id, area, route }));
}
