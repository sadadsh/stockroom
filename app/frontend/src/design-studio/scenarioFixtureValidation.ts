import type { ScenarioFixture } from "./scenario";

export type ScenarioFixtureValidator = (fixture: ScenarioFixture) => boolean;

/** Endpoint-keyed validators keep fixture schema ownership extensible for later domain modules. */
export interface ScenarioFixtureValidatorRegistry {
  validate: (fixture: ScenarioFixture) => boolean;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function isOnboardingResponse(value: unknown): boolean {
  return (
    isRecord(value) &&
    typeof value.onboarded === "boolean" &&
    typeof value.first_run === "boolean" &&
    typeof value.libraries_root === "string" &&
    Array.isArray(value.profiles) && value.profiles.every((profile) => typeof profile === "string") &&
    typeof value.under_git === "boolean" &&
    typeof value.default_dir === "string" &&
    Array.isArray(value.libraries)
  );
}

function isOnboardingMutation(fixture: ScenarioFixture): boolean {
  return (
    isRecord(fixture.body) &&
    (fixture.body.mode === "open" || fixture.body.mode === "create" || fixture.body.mode === "clone") &&
    isOnboardingResponse(fixture.response)
  );
}

function isUpdateResponse(value: unknown): boolean {
  return isRecord(value) && typeof value.update_available === "boolean";
}

function isSearchResponse(value: unknown): boolean {
  return isRecord(value) && Array.isArray(value.parts) && typeof value.count === "number";
}

function isParametricFacets(value: unknown): boolean {
  return (
    isRecord(value) &&
    (value.category === null || typeof value.category === "string") &&
    Array.isArray(value.facets) &&
    typeof value.total === "number"
  );
}

export function createScenarioFixtureValidatorRegistry(
  validators: Readonly<Record<string, ScenarioFixtureValidator>>,
): ScenarioFixtureValidatorRegistry {
  return {
    validate: (fixture) => validators[`${fixture.method.toUpperCase()} ${fixture.path}`]?.(fixture) === true,
  };
}

export const bootstrapFixtureValidators = createScenarioFixtureValidatorRegistry({
  "GET /api/onboarding": (fixture) => fixture.body === undefined && isOnboardingResponse(fixture.response),
  "POST /api/onboarding/library": isOnboardingMutation,
  "GET /api/update/check": (fixture) => fixture.body === undefined && isUpdateResponse(fixture.response),
  "GET /api/library/search": (fixture) => fixture.body === undefined && isSearchResponse(fixture.response),
  "GET /api/library/facets/parametric": (fixture) => fixture.body === undefined && isParametricFacets(fixture.response),
});
