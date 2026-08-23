import type { ScenarioFixture } from "./scenario";
import type {
  GuidedRepositoryBody,
  GuidedSourceDataBody,
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

function isNullableString(value: unknown): boolean {
  return value === null || typeof value === "string";
}

function isEdaToolChoice(value: unknown): boolean {
  return (
    isRecord(value) &&
    typeof value.key === "string" &&
    typeof value.label === "string" &&
    typeof value.detected === "boolean" &&
    typeof value.selected === "boolean" &&
    typeof value.pending === "boolean" &&
    isStringArray(value.setup_checks) &&
    typeof value.settings_target === "string"
  );
}

export function isPrimaryEdaInfo(value: Record<string, unknown>): boolean {
  return (
    isNullableString(value.primary_eda) &&
    isNullableString(value.primary_eda_pending) &&
    typeof value.primary_eda_confirmation_required === "boolean" &&
    isNullableString(value.recommended_primary_eda) &&
    isStringArray(value.primary_eda_requirements) &&
    isStringArray(value.retained_optional_eda) &&
    Array.isArray(value.eda_tools) &&
    value.eda_tools.every(isEdaToolChoice)
  );
}

function isGitHubRepository(value: unknown): boolean {
  return (
    isRecord(value) &&
    typeof value.owner === "string" &&
    typeof value.name === "string" &&
    typeof value.url === "string" &&
    (value.visibility === "public" || value.visibility === "private" || value.visibility === "internal") &&
    (value.permission === "admin" || value.permission === "maintain" || value.permission === "write" || value.permission === "triage" || value.permission === "read") &&
    typeof value.writable === "boolean"
  );
}

function isGuidedSetup(value: unknown): boolean {
  if (!isRecord(value)) return false;
  const steps = ["choose_cad_tool", "catalog_repository", "connect_the_tool"];
  const states = [...steps, "ready"];
  const repository = value.repository;
  const github = value.github;
  const tool = value.tool_connection;
  const source = value.source_data;
  return (
    value.schema === 1 &&
    typeof value.step === "string" && states.includes(value.step) &&
    Array.isArray(value.steps) && value.steps.length === steps.length && value.steps.every((step, index) => step === steps[index]) &&
    typeof value.ready === "boolean" &&
    typeof value.repository_ready === "boolean" &&
    (repository === null || (isRecord(repository) && typeof repository.owner === "string" && typeof repository.name === "string" && typeof repository.url === "string")) &&
    isRecord(github) &&
    typeof github.available === "boolean" &&
    (github.version === null || typeof github.version === "string") &&
    typeof github.authenticated === "boolean" &&
    typeof github.online === "boolean" &&
    (github.viewer === null || (isRecord(github.viewer) && typeof github.viewer.login === "string" && (github.viewer.name === null || typeof github.viewer.name === "string"))) &&
    Array.isArray(github.owners) && github.owners.every((owner) => isRecord(owner) && typeof owner.login === "string" && (owner.kind === "personal" || owner.kind === "organization")) &&
    (github.verified_repository === undefined || isGitHubRepository(github.verified_repository)) &&
    isRecord(tool) &&
    (tool.tool === null || typeof tool.tool === "string") &&
    typeof tool.installed === "boolean" &&
    typeof tool.connected === "boolean" &&
    typeof tool.restart_required === "boolean" &&
    typeof tool.detail === "string" &&
    isRecord(source) &&
    typeof source.decided === "boolean" &&
    typeof source.skipped === "boolean" &&
    typeof source.mouser_connected === "boolean" &&
    typeof source.digikey_connected === "boolean"
  );
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
    isPrimaryEdaInfo(value) &&
    typeof value.onboarded === "boolean" &&
    typeof value.first_run === "boolean" &&
    typeof value.libraries_root === "string" &&
    isStringArray(value.profiles) &&
    typeof value.under_git === "boolean" &&
    typeof value.default_dir === "string" &&
    Array.isArray(value.libraries) && value.libraries.every(isOnboardingLibrary) &&
    isGuidedSetup(value.guided_setup)
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
  return isSetLibraryBody(fixture.body) && isOnboardingResponse(fixture.response);
}

function hasOnlyKeys(value: Record<string, unknown>, keys: readonly string[]): boolean {
  return Object.keys(value).every((key) => keys.includes(key));
}

function isGuidedRepositoryBody(value: unknown): value is GuidedRepositoryBody {
  return (
    isRecord(value) &&
    hasOnlyKeys(value, ["mode", "owner", "name", "visibility", "path"]) &&
    (value.mode === "create" || value.mode === "connect") &&
    typeof value.owner === "string" &&
    typeof value.name === "string" &&
    (value.visibility === undefined || value.visibility === "public" || value.visibility === "private") &&
    typeof value.path === "string"
  );
}

function isGuidedSourceDataBody(value: unknown): value is GuidedSourceDataBody {
  return (
    isRecord(value) &&
    hasOnlyKeys(value, ["skipped", "mouser_api_key", "digikey_client_id", "digikey_client_secret"]) &&
    (value.skipped === undefined || typeof value.skipped === "boolean") &&
    isOptionalString(value.mouser_api_key) &&
    isOptionalString(value.digikey_client_id) &&
    isOptionalString(value.digikey_client_secret)
  );
}

function isJobRef(value: unknown): boolean {
  return isRecord(value) && typeof value.job_id === "string";
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
      const rawKey = `${fixture.method.toUpperCase()} ${fixture.path}`;
      const key = /^GET \/api\/onboarding\/github\/repositories\/[^/]+$/.test(rawKey)
        ? "GET /api/onboarding/github/repositories/{owner}"
        : rawKey;
      const validator = validators[key];
      return validator ? validator(fixture) : fallback?.validate(fixture) === true;
    },
  };
}

export const bootstrapFixtureValidators = createScenarioFixtureValidatorRegistry({
  "GET /api/onboarding": (fixture) => fixture.body === undefined && isOnboardingResponse(fixture.response),
  "POST /api/onboarding/library": isOnboardingMutation,
  "POST /api/onboarding/github/login": (fixture) => fixture.body === undefined && isJobRef(fixture.response),
  "GET /api/onboarding/github/repositories/{owner}": (fixture) => fixture.body === undefined && isRecord(fixture.response) && Array.isArray(fixture.response.repositories) && fixture.response.repositories.every(isGitHubRepository),
  "POST /api/onboarding/repository": (fixture) => isGuidedRepositoryBody(fixture.body) && isOnboardingResponse(fixture.response),
  "POST /api/onboarding/tool/connect": (fixture) => fixture.body === undefined && isJobRef(fixture.response),
  "POST /api/onboarding/source-data": (fixture) => isGuidedSourceDataBody(fixture.body) && isOnboardingResponse(fixture.response),
  "POST /api/onboarding/complete": (fixture) => fixture.body === undefined && isOnboardingResponse(fixture.response),
  "GET /api/update/check": (fixture) => fixture.body === undefined && isUpdateResponse(fixture.response),
  "GET /api/library/search": (fixture) => fixture.body === undefined && isSearchResponse(fixture.response),
  "GET /api/library/facets/parametric": (fixture) => fixture.body === undefined && isParametricFacets(fixture.response),
});
