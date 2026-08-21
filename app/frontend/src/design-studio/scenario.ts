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
  rail?: { aboutNote?: string };
  search?: { open?: boolean; query?: string; category?: string | null };
  service?: { error?: string };
  settings?: {
    section?: string;
    altiumDialog?: "setup" | "dblib";
    confirmResetCad?: boolean;
    picker?: "kicad" | "cubemx";
    libraryMode?: "create" | "open" | "clone" | "current";
    credentialsRefresh?: boolean;
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
    surface?: "identity" | "classification" | "provenance" | "offers" | "pinout";
    cadView?: "models" | "manage-models";
    sourcesTab?: "fields" | "records" | "changes" | "diagnostics";
    preview?: "symbol" | "footprint" | "model";
    confirmDelete?: boolean;
  };
  projects?: {
    selectedId?: string | null;
    activeTab?: "overview" | "schematic" | "pcb" | "bom" | "build" | "activity";
  };
  stm?: {
    tab?: "explorer" | "compatibility";
    activePart?: string | null;
    selectedPosition?: string | null;
    pinoutView?: "map" | "table";
    explorerScope?: { families: string[]; mcus?: string[] };
    benchScope?: { families: string[]; mcus?: string[] };
    benchPackage?: string | null;
    targetDefinition?: TargetDefinitionDTO;
    targetEvidenceOpen?: boolean;
    showTargetPolicy?: boolean;
    openBenchPart?: string;
    indexState?: "missing" | "building" | "error" | "blocked";
  };
  provider?: {
    state: string;
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
