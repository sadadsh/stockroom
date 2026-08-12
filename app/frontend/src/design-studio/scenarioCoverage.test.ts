import { describe, expect, it } from "vitest";
import { PRODUCTION_ROUTES, type Route } from "../lib/router";
import type { DesignScenario } from "./scenario";
import { registerScenarios, routeCoverageIssues } from "./scenarioRegistry";

function scenario(route: Route): DesignScenario {
  return {
    id: `route.${route}`,
    title: `${route} route`,
    area: "global",
    group: "Coverage",
    route,
    fixtures: [],
    initialUi: {},
    expectedTargets: ["shell.root"],
  };
}

function registryWithout(route: Route) {
  return registerScenarios(PRODUCTION_ROUTES.filter((candidate) => candidate !== route).map(scenario));
}

describe("routeCoverageIssues", () => {
  it("requires every production route", () => {
    expect(routeCoverageIssues(registryWithout("settings"))).toEqual([
      expect.objectContaining({ code: "missing-route", value: "settings" }),
    ]);
  });
});
