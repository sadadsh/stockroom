import { PRODUCTION_ROUTES, type Route } from "../lib/router";
import type {
  DesignScenario,
  ScenarioArea,
  ScenarioCoverageTag,
  ScenarioFixture,
} from "./scenario";
import { bootstrapFixtureValidators, type ScenarioFixtureValidatorRegistry } from "./scenarioFixtureValidation";

export type ScenarioRegistryIssueCode =
  | "duplicate-scenario"
  | "unknown-route"
  | "malformed-fixture"
  | "invalid-fixture-shape"
  | "missing-local-outcome"
  | "missing-targets"
  | "missing-coverage"
  | "missing-route";

export interface ScenarioRegistryIssue {
  code: ScenarioRegistryIssueCode;
  scenarioId?: string;
  value?: string;
}

export interface ScenarioRegistry {
  readonly scenarios: readonly DesignScenario[];
  readonly issues: readonly ScenarioRegistryIssue[];
  scenarioById: (id: string) => DesignScenario | undefined;
  scenariosForArea: (area: ScenarioArea) => readonly DesignScenario[];
  searchScenarios: (query: string) => readonly DesignScenario[];
}

const KNOWN_ROUTES = new Set<string>(PRODUCTION_ROUTES);

function isStringRecord(value: unknown): value is Readonly<Record<string, string | readonly string[]>> {
  return (
    value !== null &&
    typeof value === "object" &&
    !Array.isArray(value) &&
    Object.values(value).every(
      (entry) =>
        typeof entry === "string" ||
        (Array.isArray(entry) && entry.every((item) => typeof item === "string")),
    )
  );
}

function isFixture(value: unknown): value is ScenarioFixture {
  if (value === null || typeof value !== "object" || Array.isArray(value)) return false;
  const fixture = value as Partial<ScenarioFixture>;
  return (
    typeof fixture.method === "string" &&
    fixture.method.length > 0 &&
    typeof fixture.path === "string" &&
    fixture.path.startsWith("/api/") &&
    isStringRecord(fixture.params) &&
    Object.prototype.hasOwnProperty.call(fixture, "body") &&
    Object.prototype.hasOwnProperty.call(fixture, "response")
  );
}

function isMutation(fixture: ScenarioFixture): boolean {
  const method = fixture.method.toUpperCase();
  return method !== "GET" && method !== "HEAD" && method !== "OPTIONS";
}

function hasLocalOutcome(fixture: ScenarioFixture): boolean {
  const outcome = fixture.localOutcome;
  return (
    outcome !== undefined &&
    (outcome.state === "succeeded" || outcome.state === "failed") &&
    typeof outcome.target === "string" &&
    outcome.target.length > 0
  );
}

function coverageIssues(scenario: DesignScenario): ScenarioRegistryIssue[] {
  const tags = scenario.coverage as readonly ScenarioCoverageTag[];
  const hasRoute = tags.some((tag) => tag === `route:${scenario.route}`);
  const hasState = tags.some((tag) => tag.startsWith("state:") && tag.length > "state:".length);
  return [
    ...(hasRoute ? [] : [{ code: "missing-coverage" as const, scenarioId: scenario.id, value: "route" }]),
    ...(hasState ? [] : [{ code: "missing-coverage" as const, scenarioId: scenario.id, value: "state" }]),
  ];
}

/**
 * Validates and indexes supplied scenarios without side effects. Invalid scenarios stay out of
 * the lookup indexes so callers cannot accidentally activate a malformed preview.
 */
export function registerScenarios(
  items: readonly DesignScenario[],
  fixtureValidators: ScenarioFixtureValidatorRegistry = bootstrapFixtureValidators,
): ScenarioRegistry {
  const issues: ScenarioRegistryIssue[] = [];
  const counts = new Map<string, number>();
  for (const scenario of items) counts.set(scenario.id, (counts.get(scenario.id) ?? 0) + 1);
  const valid: DesignScenario[] = [];

  for (const scenario of items) {
    const scenarioIssues: ScenarioRegistryIssue[] = [];
    if ((counts.get(scenario.id) ?? 0) > 1) {
      scenarioIssues.push({ code: "duplicate-scenario", scenarioId: scenario.id, value: scenario.id });
    }
    if (!KNOWN_ROUTES.has(scenario.route)) {
      scenarioIssues.push({ code: "unknown-route", scenarioId: scenario.id, value: String(scenario.route) });
    }
    if (!Array.isArray(scenario.expectedTargets) || scenario.expectedTargets.length === 0) {
      scenarioIssues.push({ code: "missing-targets", scenarioId: scenario.id });
    }
    scenarioIssues.push(...coverageIssues(scenario));
    for (const fixture of scenario.fixtures) {
      if (!isFixture(fixture)) {
        scenarioIssues.push({ code: "malformed-fixture", scenarioId: scenario.id });
        continue;
      }
      if (!fixtureValidators.validate(fixture)) {
        scenarioIssues.push({ code: "invalid-fixture-shape", scenarioId: scenario.id, value: fixture.path });
      }
      if (isMutation(fixture) && !hasLocalOutcome(fixture)) {
        scenarioIssues.push({ code: "missing-local-outcome", scenarioId: scenario.id, value: fixture.path });
      }
    }
    issues.push(...scenarioIssues);
    if (scenarioIssues.length === 0) valid.push(scenario);
  }

  const byId = new Map(valid.map((scenario) => [scenario.id, scenario]));
  return {
    scenarios: valid,
    issues,
    scenarioById: (id) => byId.get(id),
    scenariosForArea: (area) => valid.filter((scenario) => scenario.area === area),
    searchScenarios: (query) => {
      const needle = query.trim().toLocaleLowerCase();
      if (!needle) return valid;
      return valid.filter((scenario) =>
        [scenario.id, scenario.title, scenario.group, scenario.area]
          .join(" ")
          .toLocaleLowerCase()
          .includes(needle),
      );
    },
  };
}

/** Reports route gaps from the one production route registry, never a test-maintained list. */
export function routeCoverageIssues(registry: ScenarioRegistry): ScenarioRegistryIssue[] {
  const covered = new Set(registry.scenarios.map((scenario) => scenario.route));
  return PRODUCTION_ROUTES.filter((route) => !covered.has(route)).map((route: Route) => ({
    code: "missing-route",
    value: route,
  }));
}
