import type { ScenarioFixture } from "./scenario";
import type {
  OnboardingStatus,
  ParametricFacet,
  ParametricFacets,
  SearchResponse,
  SetLibraryBody,
  UpdateCheck,
} from "../api/types";

export type ScenarioFixtureValidator = (fixture: ScenarioFixture) => boolean;

/** Endpoint-keyed validators keep fixture schema ownership extensible for later domain modules. */
export interface ScenarioFixtureValidatorRegistry {
  validate: (fixture: ScenarioFixture) => boolean;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function isStringArray(value: unknown): value is string[] {
  return Array.isArray(value) && value.every((item) => typeof item === "string");
}

function isOptionalString(value: unknown): boolean {
  return value === undefined || typeof value === "string";
}

function isOptionalNumber(value: unknown): boolean {
  return value === undefined || typeof value === "number";
}

function isOnboardingLibrary(value: unknown): boolean {
  return (
    isRecord(value) &&
    typeof value.name === "string" &&
    typeof value.path === "string" &&
    typeof value.active === "boolean" &&
    typeof value.available === "boolean" &&
    typeof value.under_git === "boolean"
  );
}

/** Endpoint owner for GET /api/onboarding, checked against OnboardingStatus. */
function isOnboardingResponse(value: unknown): value is OnboardingStatus {
  return (
    isRecord(value) &&
    typeof value.onboarded === "boolean" &&
    typeof value.first_run === "boolean" &&
    typeof value.libraries_root === "string" &&
    isStringArray(value.profiles) &&
    typeof value.under_git === "boolean" &&
    typeof value.default_dir === "string" &&
    Array.isArray(value.libraries) && value.libraries.every(isOnboardingLibrary)
  );
}

/** Endpoint owner for POST /api/onboarding/library, checked against SetLibraryBody. */
function isSetLibraryBody(value: unknown): value is SetLibraryBody {
  if (!isRecord(value) || !isOptionalString(value.path) || !isOptionalString(value.url) || !isOptionalString(value.dest)) {
    return false;
  }
  if (value.mode === "open") return typeof value.path === "string";
  if (value.mode === "create") return true;
  return value.mode === "clone" && typeof value.url === "string";
}

function isOnboardingMutation(fixture: ScenarioFixture): boolean {
  return (
    isSetLibraryBody(fixture.body) &&
    isOnboardingResponse(fixture.response)
  );
}

/** Endpoint owner for GET /api/update/check, checked against UpdateCheck. */
function isUpdateResponse(value: unknown): value is UpdateCheck {
  return (
    isRecord(value) &&
    typeof value.update_available === "boolean" &&
    isOptionalString(value.state) &&
    isOptionalNumber(value.behind) &&
    isOptionalString(value.current_release_id) &&
    isOptionalString(value.target_release_id) &&
    isOptionalString(value.current_revision) &&
    isOptionalString(value.target_revision) &&
    isOptionalString(value.frontend_revision) &&
    isOptionalString(value.channel) &&
    (value.automatic_on_launch === undefined || typeof value.automatic_on_launch === "boolean") &&
    isOptionalNumber(value.check_interval_seconds) &&
    isOptionalString(value.convergence_phase) &&
    (value.automatic_apply === undefined || typeof value.automatic_apply === "boolean") &&
    isOptionalString(value.detail)
  );
}

function isSearchScalarMap(value: unknown): boolean {
  return (
    isRecord(value) &&
    Object.values(value).every(
      (entry) => typeof entry === "string" || typeof entry === "number" || typeof entry === "boolean",
    )
  );
}

function isSearchRow(value: unknown): boolean {
  return (
    isRecord(value) &&
    typeof value.id === "string" &&
    typeof value.display_name === "string" &&
    typeof value.category === "string" &&
    typeof value.mpn === "string" &&
    typeof value.manufacturer === "string" &&
    typeof value.is_complete === "boolean" &&
    isStringArray(value.missing) &&
    isSearchScalarMap(value.specs) &&
    (value.stock === null || typeof value.stock === "number") &&
    (value.unit_price === null || typeof value.unit_price === "number") &&
    typeof value.currency === "string"
  );
}

/** Endpoint owner for GET /api/library/search, checked against SearchResponse. */
function isSearchResponse(value: unknown): value is SearchResponse {
  return isRecord(value) && Array.isArray(value.parts) && value.parts.every(isSearchRow) && typeof value.count === "number";
}

function isFacetOption(value: unknown): boolean {
  return isRecord(value) && typeof value.value === "string" && typeof value.count === "number";
}

function isParametricFacet(value: unknown): value is ParametricFacet {
  return (
    isRecord(value) &&
    typeof value.key === "string" &&
    typeof value.label === "string" &&
    (value.kind === "options" || value.kind === "range") &&
    typeof value.count === "number" &&
    (value.options === undefined || value.options === null || (Array.isArray(value.options) && value.options.every(isFacetOption))) &&
    (value.min === undefined || value.min === null || typeof value.min === "number") &&
    (value.max === undefined || value.max === null || typeof value.max === "number") &&
    (value.unit === undefined || value.unit === null || typeof value.unit === "string")
  );
}

/** Endpoint owner for GET /api/library/facets/parametric, checked against ParametricFacets. */
function isParametricFacets(value: unknown): value is ParametricFacets {
  return (
    isRecord(value) &&
    (value.category === null || typeof value.category === "string") &&
    Array.isArray(value.facets) && value.facets.every(isParametricFacet) &&
    typeof value.total === "number"
  );
}

export function createScenarioFixtureValidatorRegistry(
  validators: Readonly<Record<string, ScenarioFixtureValidator>>,
  fallback?: ScenarioFixtureValidatorRegistry,
): ScenarioFixtureValidatorRegistry {
  return {
    validate: (fixture) => {
      const validator = validators[`${fixture.method.toUpperCase()} ${fixture.path}`];
      return validator ? validator(fixture) : fallback?.validate(fixture) === true;
    },
  };
}

export const bootstrapFixtureValidators = createScenarioFixtureValidatorRegistry({
  "GET /api/onboarding": (fixture) => fixture.body === undefined && isOnboardingResponse(fixture.response),
  "POST /api/onboarding/library": isOnboardingMutation,
  "GET /api/update/check": (fixture) => fixture.body === undefined && isUpdateResponse(fixture.response),
  "GET /api/library/search": (fixture) => fixture.body === undefined && isSearchResponse(fixture.response),
  "GET /api/library/facets/parametric": (fixture) => fixture.body === undefined && isParametricFacets(fixture.response),
});
