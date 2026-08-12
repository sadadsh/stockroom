import { describe, expect, it } from "vitest";
import type { OnboardingStatus } from "../api/types";
import type { DesignScenario, ScenarioFixture } from "./scenario";
import { registerScenarios } from "./scenarioRegistry";
import { bootstrapScenarioRegistry, globalScenarios } from "./scenarios";
import { componentScenarioIds } from "./scenarios/components";
import { projectScenarioIds } from "./scenarios/projects";
import { providerScenarioIds } from "./scenarios/provider";
import { bootstrapFixtureValidators } from "./scenarioFixtureValidation";

function scenario(id: string): DesignScenario {
  return {
    id,
    title: "Scenario fixture",
    area: "global",
    group: "Bootstrap",
    route: "components",
    fixtures: [
      {
        method: "GET",
        path: "/api/onboarding",
        params: {},
        body: undefined,
        response: {
          onboarded: true,
          first_run: false,
          libraries_root: "C:\\Stockroom",
          profiles: [],
          under_git: true,
          default_dir: "C:\\Stockroom",
          libraries: [],
        },
      } satisfies ScenarioFixture,
    ],
    initialUi: {},
    expectedTargets: ["shell.root"],
    coverage: ["route:components", "state:ready"],
  };
}

describe("registerScenarios", () => {
  it("rejects duplicate IDs and missing route/state coverage tags", () => {
    const duplicate = scenario("global.onboarding.open");
    const missingCoverage = {
      ...scenario("global.missing-coverage"),
      coverage: [],
    };

    const result = registerScenarios([duplicate, duplicate, missingCoverage]);

    expect(result.issues).toContainEqual(
      expect.objectContaining({ code: "duplicate-scenario", value: duplicate.id }),
    );
    expect(result.issues).toContainEqual(
      expect.objectContaining({ code: "missing-coverage", value: "route" }),
    );
    expect(result.issues).toContainEqual(
      expect.objectContaining({ code: "missing-coverage", value: "state" }),
    );
  });

  it("rejects unknown routes, malformed fixture descriptors, mutation fixtures without outcomes, and missing targets", () => {
    const invalid = {
      ...scenario("global.invalid"),
      route: "not-a-route",
      fixtures: [
        { method: "GET", path: "/api/onboarding", params: {}, response: {} },
        {
          method: "POST",
          path: "/api/onboarding/library",
          params: {},
          body: { mode: "create" },
          response: {},
        },
      ],
      expectedTargets: [],
    } as unknown as DesignScenario;

    const result = registerScenarios([invalid]);

    expect(result.issues).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ code: "unknown-route", value: "not-a-route" }),
        expect.objectContaining({ code: "malformed-fixture" }),
        expect.objectContaining({ code: "missing-local-outcome" }),
        expect.objectContaining({ code: "missing-targets" }),
      ]),
    );
  });

  it("indexes valid scenarios by area and search terms", () => {
    const onboarding = scenario("global.onboarding.open");
    const serviceError = { ...scenario("global.service-error"), title: "Service Error" };
    const registry = registerScenarios([onboarding, serviceError]);

    expect(registry.issues).toEqual([]);
    expect(registry.scenarioById(onboarding.id)).toBe(onboarding);
    expect(registry.scenariosForArea("global")).toEqual([onboarding, serviceError]);
    expect(registry.searchScenarios("SERVICE")).toEqual([serviceError]);
  });

  it("fails closed for every duplicate ID instead of activating the first entry", () => {
    const duplicate = scenario("global.duplicate");
    const registry = registerScenarios([duplicate, { ...duplicate, title: "Second" }]);

    expect(registry.scenarioById(duplicate.id)).toBeUndefined();
    expect(registry.scenarios).not.toContainEqual(expect.objectContaining({ id: duplicate.id }));
  });

  it("rejects a known endpoint fixture with an invalid typed response", () => {
    const invalid = {
      ...scenario("global.invalid-onboarding-response"),
      fixtures: [{
        method: "GET",
        path: "/api/onboarding",
        params: {},
        body: undefined,
        response: { first_run: "yes" },
      }],
    } as unknown as DesignScenario;

    expect(registerScenarios([invalid]).issues).toContainEqual(
      expect.objectContaining({ code: "invalid-fixture-shape" }),
    );
  });

  it("rejects malformed nested bootstrap DTOs and clone bodies", () => {
    const validOnboarding = scenario("global.valid-onboarding").fixtures[0]?.response as OnboardingStatus;
    const invalidScenarios = [
      {
        ...scenario("global.invalid-onboarding-library"),
        fixtures: [{ method: "GET", path: "/api/onboarding", params: {}, body: undefined, response: { ...validOnboarding, libraries: [null] } }],
      },
      {
        ...scenario("global.invalid-search-part"),
        fixtures: [{ method: "GET", path: "/api/library/search", params: {}, body: undefined, response: { parts: [null], count: 1 } }],
      },
      {
        ...scenario("global.invalid-parametric-facet"),
        fixtures: [{ method: "GET", path: "/api/library/facets/parametric", params: {}, body: undefined, response: { category: null, facets: [null], total: 1 } }],
      },
      {
        ...scenario("global.invalid-clone-body"),
        fixtures: [{
          method: "POST",
          path: "/api/onboarding/library",
          params: {},
          body: { mode: "clone", url: 42 },
          response: validOnboarding,
          localOutcome: { state: "succeeded", target: "onboarding.gate" },
        }],
      },
    ] as unknown as DesignScenario[];

    const result = registerScenarios(invalidScenarios);

    for (const invalidScenario of invalidScenarios) {
      expect(result.issues).toContainEqual(
        expect.objectContaining({ code: "invalid-fixture-shape", scenarioId: invalidScenario.id }),
      );
    }
  });

  it("accepts the shipped typed fixtures through their endpoint-owned validators", () => {
    expect(
      globalScenarios.flatMap((scenario) => scenario.fixtures).every((fixture) =>
        bootstrapFixtureValidators.validate(fixture),
      ),
    ).toBe(true);
  });

  it("registers the shipped bootstrap scenarios with stable targets and typed fixtures", () => {
    expect(bootstrapScenarioRegistry.issues).toEqual([]);
    expect(bootstrapScenarioRegistry.scenarios.map((item) => item.id)).toEqual([
      ...globalScenarios.map((scenario) => scenario.id),
      ...componentScenarioIds,
      ...providerScenarioIds,
      ...projectScenarioIds,
    ]);
    expect(bootstrapScenarioRegistry.searchScenarios("update")).toEqual([
      expect.objectContaining({ id: "global.update.available", expectedTargets: ["rail.update"] }),
    ]);
  });
});
