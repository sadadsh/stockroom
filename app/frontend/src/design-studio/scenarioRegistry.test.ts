import { describe, expect, it } from "vitest";
import type { OnboardingStatus } from "../api/types";
import type { DesignScenario, ScenarioFixture } from "./scenario";
import { registerScenarios } from "./scenarioRegistry";
import { bootstrapScenarioRegistry, globalScenarios } from "./scenarios";
import { componentScenarios } from "./scenarios/components";
import { projectScenarios } from "./scenarios/projects";
import { providerScenarios } from "./scenarios/provider";
import { stmScenarios } from "./scenarios/stm";
import { settingsScenarios } from "./scenarios/settings";
import {
  SETTINGS_READY,
  settingsFixtureValidators,
} from "./fixtures/settingsFixtures";
import { defineScenarioStateContracts } from "./scenarioStateContracts";
import { GUIDED_SETUP_READY } from "./fixtures/onboardingFixtures";
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
          primary_eda: "kicad",
          primary_eda_pending: null,
          primary_eda_confirmation_required: false,
          recommended_primary_eda: "kicad",
          primary_eda_requirements: ["symbol", "footprint", "model"],
          retained_optional_eda: ["altium"],
          eda_tools: [],
          onboarded: true,
          first_run: false,
          libraries_root: "C:\\Stockroom",
          profiles: [],
          under_git: true,
          default_dir: "C:\\Stockroom",
          libraries: [],
          guided_setup: GUIDED_SETUP_READY,
        },
      } satisfies ScenarioFixture,
    ],
    initialUi: {},
    expectedTargets: ["shell.root"],
  };
}

describe("registerScenarios", () => {
  it("rejects duplicate scenario IDs", () => {
    const duplicate = scenario("global.onboarding.open");
    const result = registerScenarios([duplicate, duplicate]);

    expect(result.issues).toContainEqual(
      expect.objectContaining({ code: "duplicate-scenario", value: duplicate.id }),
    );
  });

  it("requires exact scenario parity with explicit domain state contracts", () => {
    const contracted = scenario("global.onboarding.open");
    const uncontracted = scenario("global.uncontracted");
    const contracts = defineScenarioStateContracts("settings", "settings", [
      contracted.id,
      "global.missing-scenario",
    ] as const);

    const result = registerScenarios(
      [contracted, uncontracted],
      settingsFixtureValidators,
      contracts,
    );

    expect(result.issues).toEqual(expect.arrayContaining([
      expect.objectContaining({ code: "missing-state-contract", scenarioId: uncontracted.id }),
      expect.objectContaining({ code: "missing-scenario", scenarioId: "global.missing-scenario" }),
      expect.objectContaining({ code: "state-contract-mismatch", scenarioId: contracted.id }),
    ]));
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

  it("rejects a Settings fixture missing the Primary CAD Tool contract", () => {
    const { primary_eda: _primaryEda, ...missingPrimaryEda } = SETTINGS_READY;
    const invalid = {
      ...scenario("settings.invalid-primary-eda"),
      route: "settings",
      fixtures: [
        {
          method: "GET",
          path: "/api/settings",
          params: {},
          body: undefined,
          response: missingPrimaryEda,
        },
      ],
    } as DesignScenario;

    expect(
      registerScenarios([invalid], settingsFixtureValidators).issues,
    ).toContainEqual(
      expect.objectContaining({
        code: "invalid-fixture-shape",
        scenarioId: invalid.id,
      }),
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
      {
        ...scenario("global.invalid-guided-setup"),
        fixtures: [{ method: "GET", path: "/api/onboarding", params: {}, body: undefined, response: { ...validOnboarding, guided_setup: { ready: true } } }],
      },
      {
        ...scenario("global.invalid-guided-repository-url"),
        fixtures: [{ method: "POST", path: "/api/onboarding/repository", params: {}, body: { mode: "connect", owner: "engineer", name: "catalog", path: "D:/Catalog", url: "https://example.invalid" }, response: validOnboarding }],
      },
    ] as unknown as DesignScenario[];

    const result = registerScenarios(invalidScenarios);

    for (const invalidScenario of invalidScenarios) {
      expect(result.issues).toContainEqual(
        expect.objectContaining({ code: "invalid-fixture-shape", scenarioId: invalidScenario.id }),
      );
    }
  });

  it("validates Guided Setup job, listing, repository, source, and completion fixtures", () => {
    const validOnboarding = scenario("global.valid-guided-actions").fixtures[0]?.response as OnboardingStatus;
    const repository = {
      owner: "engineer", name: "stockroom-catalog",
      url: "https://github.com/engineer/stockroom-catalog.git",
      visibility: "private", permission: "admin", writable: true,
    };
    const fixtures: ScenarioFixture[] = [
      { method: "POST", path: "/api/onboarding/github/login", params: {}, body: undefined, response: { job_id: "login-1" } },
      { method: "GET", path: "/api/onboarding/github/repositories/engineer", params: {}, body: undefined, response: { repositories: [repository] } },
      { method: "POST", path: "/api/onboarding/repository", params: {}, body: { mode: "create", owner: "engineer", name: "stockroom-catalog", visibility: "private", path: "D:/Catalog" }, response: validOnboarding },
      { method: "POST", path: "/api/onboarding/tool/connect", params: {}, body: undefined, response: { job_id: "tool-1" } },
      { method: "POST", path: "/api/onboarding/source-data", params: {}, body: { skipped: true }, response: validOnboarding },
      { method: "POST", path: "/api/onboarding/complete", params: {}, body: undefined, response: validOnboarding },
    ];
    expect(fixtures.every((fixture) => bootstrapFixtureValidators.validate(fixture))).toBe(true);
  });

  it("accepts the shipped typed fixtures through their endpoint-owned validators", () => {
    expect(
      globalScenarios.flatMap((scenario) => scenario.fixtures).every((fixture) =>
        settingsFixtureValidators.validate(fixture),
      ),
    ).toBe(true);
  });

  it("registers the shipped bootstrap scenarios with stable targets and typed fixtures", () => {
    expect(bootstrapScenarioRegistry.issues).toEqual([]);
    expect(bootstrapScenarioRegistry.scenarios.map((item) => item.id)).toEqual([
      ...globalScenarios.map((scenario) => scenario.id),
      ...componentScenarios.map((scenario) => scenario.id),
      ...providerScenarios.map((scenario) => scenario.id),
      ...projectScenarios.map((scenario) => scenario.id),
      ...stmScenarios.map((scenario) => scenario.id),
      ...settingsScenarios.map((scenario) => scenario.id),
    ]);
    expect(bootstrapScenarioRegistry.searchScenarios("update")).toContainEqual(
      expect.objectContaining({ id: "global.update.available", expectedTargets: ["rail.update"] }),
    );
  });
});
