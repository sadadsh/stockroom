import type { ApiRequestDescriptor } from "./requestAdapter";
import type { Route } from "../lib/router";
import type { TargetDefinitionDTO } from "../api/types";

/** The product surface a scenario belongs to. Route-specific areas grow with the product routes. */
export type ScenarioArea = "global" | Route;

/** A local result for a fixture that represents a product mutation. */
export interface ScenarioLocalOutcome {
  state: "succeeded" | "failed";
  target: string;
  detail?: string;
}

export interface ScenarioUiState {
  onboarding?: { mode?: "open" | "create" | "clone"; setupError?: string };
  rail?: { aboutOpen?: boolean };
  search?: { open?: boolean };
  service?: { error?: string };
  settings?: {
    group?: "general" | "library" | "eda" | "sources" | "maintenance";
    altiumDialog?: "setup" | "dblib";
    confirmResetCad?: boolean;
    picker?: "kicad" | "cubemx";
  };
  addParts?: { state: "empty" | "validating" | "exact" | "mismatch" | "duplicate" | "failure" };
  toast?: { message: string; tone: "neutral" | "ok" | "err" };
  confirmation?: { danger?: boolean };
  capture?: { status: "resolving" | "receiving" | "done" | "error"; backgrounded: boolean };
  theme?: "dark" | "light";
  railState?: "expanded" | "collapsed";
  sourcePromotion?: { state: "unavailable" | "ready" | "blocked" | "success" | "failure" };
  components?: {
    filters?: {
      query?: string;
      category?: string | null;
      completeOnly?: boolean;
      duplicatesOnly?: boolean;
    };
    selectedId?: string | null;
    autoSelect?: boolean;
    surface?: "identity" | "classification" | "cad-sources" | "provenance" | "offers" | "pinout";
    preview?: "symbol" | "footprint" | "model";
    confirmDelete?: boolean;
  };
  projects?: {
    selectedId?: string | null;
    activeTab?: "overview" | "bom" | "build" | "activity";
  };
  stm?: {
    tab?: "explorer" | "compatibility";
    activePart?: string | null;
    selectedPosition?: string | null;
    pinoutView?: "map" | "table";
    benchScope?: { families: string[]; mcus?: string[] };
    benchPackage?: string | null;
    targetDefinition?: TargetDefinitionDTO;
    showTargetPolicy?: boolean;
  };
  /** Native provider chrome is rendered by WindowHost, not duplicated in the React app tree. */
  provider?: {
    state: string;
    nativeHostTargets?: readonly ("provider-back" | "provider-forward" | "stockroom-tab" | "provider-tab")[];
  };
}

/** One typed API response used while a scenario preview is active. */
export interface ScenarioFixture<TResponse = unknown, TBody = unknown>
  extends ApiRequestDescriptor {
  body: TBody;
  response: TResponse;
  /** Deterministic transport state while preserving a schema-valid typed response fixture. */
  behavior?:
    | { state: "pending" }
    | { state: "error"; status: number; message: string };
  localOutcome?: ScenarioLocalOutcome;
}

/** A preview of real product markup, supplied entirely by fixtures and local UI state. */
export interface DesignScenario {
  id: string;
  title: string;
  area: ScenarioArea;
  group: string;
  route: Route;
  fixtures: readonly ScenarioFixture[];
  initialUi: Readonly<ScenarioUiState>;
  expectedTargets: readonly string[];
}

function canonicalScenarioValue(value: unknown): string {
  if (value === undefined) return '"<undefined>"';
  if (value === null || typeof value !== "object") return JSON.stringify(value);
  if (Array.isArray(value)) return `[${value.map(canonicalScenarioValue).join(",")}]`;
  return `{${Object.entries(value as Record<string, unknown>)
    .sort(([left], [right]) => left.localeCompare(right))
    .map(([key, item]) => `${JSON.stringify(key)}:${canonicalScenarioValue(item)}`)
    .join(",")}}`;
}

/** Exact non-title state fingerprint shared by production DOM, jsdom, and the browser projection. */
export function scenarioStateSignature(scenario: DesignScenario): string {
  if (scenario.id === "global.real-data") return "real-data";
  const material = canonicalScenarioValue({
    route: scenario.route,
    initialUi: scenario.initialUi,
    expectedTargets: scenario.expectedTargets,
    fixtures: scenario.fixtures.map(({ method, path, params, body, behavior, response, localOutcome }) => ({
      method: method.toUpperCase(), path, params, body, behavior, response, localOutcome,
    })),
  });
  let hash = 0x811c9dc5;
  for (let index = 0; index < material.length; index += 1) {
    hash ^= material.charCodeAt(index);
    hash = Math.imul(hash, 0x01000193);
  }
  return `state-${(hash >>> 0).toString(16).padStart(8, "0")}`;
}
