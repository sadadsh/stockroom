import type { ApiRequestDescriptor } from "./requestAdapter";
import type { Route } from "../lib/router";

/** The product surface a scenario belongs to. Route-specific areas grow with the product routes. */
export type ScenarioArea = "global" | Route;

/** Coverage is explicit so an editor cannot silently omit a state or route it needs to exercise. */
export type ScenarioCoverageTag = `route:${Route}` | `state:${string}`;

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
  coverage: readonly ScenarioCoverageTag[];
}
