import type { FamiliesResponse, McusResponse, PinoutDTO, TargetDefinitionDTO } from "../../api/types";
import type { ScenarioFixture } from "../scenario";
import { createScenarioFixtureValidatorRegistry } from "../scenarioFixtureValidation";
import { ONBOARDING_READY } from "./componentFixtures";
import { projectFixtureValidators } from "./projectFixtures";

export const STM_PART = "STM32F407V(E-G)Tx";

export const STM_STATUS = {
  built: true, building: false, source_path: "C:\\ST\\STM32CubeMX", source_present: true,
  all_families: true, device_xml_count: 2, family_count: 2, families: ["STM32F4", "STM32F7"],
  mcu_count: 2, classifier_rev: 1, af_schema_rev: 1, geometry_rev: 1, source_sha256: "fixture", built_at: "2026-08-11T00:00:00Z",
};

export const STM_FAMILIES: FamiliesResponse = {
  families: [
    { family: "STM32F4", lines: ["STM32F407"], mcu_count: 1, packages: ["LQFP100", "LQFP144"] },
    { family: "STM32F7", lines: ["STM32F746"], mcu_count: 1, packages: ["LQFP144"] },
  ],
};

export const STM_MCUS: McusResponse = {
  mcus: [{ part: STM_PART, mpn_example: "STM32F407VETx", series: "STM32F4", line: "STM32F407", core: "Cortex-M4", package: "LQFP100", pin_count: 100, io_count: 82, flash_kb: 512, ram_kb: 192, max_freq_mhz: 168, vdd_min: 1.8, vdd_max: 3.6, temp_min_c: -40, temp_max_c: 85, peripherals: { USART: 4, SPI: 3, I2C: 3, TIM: 4, ADC: 3, USB: 1 } }],
  count: 1,
  facets: { family: { STM32F4: 1 }, core: { "Cortex-M4": 1 }, package: { LQFP100: 1 }, series: { STM32F407: 1 } },
};

export const STM_PINOUT: PinoutDTO = {
  part: STM_PART, mpn_example: "STM32F407VETx", package: "LQFP100",
  geometry: { body_shape: "qfp", pin_count: 2, rows: null, cols: null, pitch_mm: 0.5, has_center_pad: false },
  pins: [
    { position: "23", position_kind: "numeric", lqfp_side: "left", bga_row: null, bga_col: null, canonical_pin_name: "PA9", raw_pin_name: "PA9", pin_type: "I/O", electrical_class: "io", category: "io", roles: [], functions: [{ signal: "USART1_TX", io_modes: "AF" }], alternate_functions: [{ af_index: 7, signal: "USART1_TX", peripheral: "USART1" }], five_v: { tolerant: true, by_family: { STM32F4: true }, caveat: "" }, supply: null },
    { position: "24", position_kind: "numeric", lqfp_side: "left", bga_row: null, bga_col: null, canonical_pin_name: "VDD", raw_pin_name: "VDD", pin_type: "Power", electrical_class: "power", category: "power", roles: [], functions: [], alternate_functions: [], five_v: null, supply: "VDD" },
  ],
};

/** A real TargetDefinitionPanel payload; preview state supplies it without a product mutation. */
export const STM_TARGET_DEFINITION = {
  format: "stm-target-definition/2", compiler_rev: 1, artifact_digest: "fixture-target-definition",
  profile: { id: "fixture", revision: 1, coverage_mode: "explicit-device-set", policy_digest: "fixture" },
  scope: { package: "LQFP144", families: ["STM32F4", "STM32F7"], target_count: 2, targets: [] },
  provenance: { silicon_source: "Fixture", source_sha256: "fixture", source_built_at: "", classifier_rev: 1, af_schema_rev: 1, geometry_rev: 1, policy_digest: "fixture" },
  readiness: { status: "ready", blockers: [], warnings: [] },
  summary: { silicon_classes: {}, board_actions: {}, required_routes: 0, switched_routes: 0, safety_rules: 0, service_groups: 0, foundation_groups: 0 },
  requirements: [], service_groups: [], functional_foundation: { claim_scope: "pin-obligation", network_values_authority: "fixture", status: "complete", unresolved_positions: [], groups: [] }, safety_rules: [], routing_requirements: { strategy: "fixture", safe_default: "open", required_independent_paths: 0, maximum_independent_paths: null, limit_status: "unbounded", paths: [] },
  universalization: { strategy: "fixture", implementation_owner: "fixture", implementation_technology: "unspecified", required_independent_paths: 0, safe_default: "open", state_contract: { unknown_target: "open", controller_startup: "open", controller_reset: "open", power_loss: "open", target_change: "open", identity_mismatch: "open", configured: "open" }, summary: { direct_or_fixed: 0, selectable: 0, excluded_from_common_interface: 0 }, strategies: [] },
  positions: [],
} as unknown as TargetDefinitionDTO;

const union = { parts: [STM_PART, "STM32F746ZGT6"], resolved: [{ ref: STM_PART, mpn: "STM32F407VETx" }, { ref: "STM32F746ZGT6", mpn: "STM32F746ZGT6" }], package: "LQFP144", family: "STM32F4 + STM32F7", families: ["STM32F4", "STM32F7"], grain: "per-part", positions: [], verdict: { interchangeable: true, swaps_required: 0, blocking: [] } };
const socket = { format: "stm-socket-solution/1", compiler_rev: 1, artifact_digest: "fixture", source_definition_digest: "fixture", scope: { package: "LQFP144", families: ["STM32F4", "STM32F7"], target_count: 2, targets: [], target_index: [] }, provenance: {}, status: { solution: "solved", evidence: "complete", bootstrap: "automatic", blockers: [], warnings: [] }, closure: { verdict: "architecture-complete", release: "ready", zero_omission: true, supported_target_count: 2, unsupported_target_count: 0, target_coverage_percentage: 100, gates: [], required_requirement_coverage: [], configuration_errors: [] }, summary: { target_count: 2, target_cohort_count: 0, position_count: 0, support_cell_count: 0, direct_positions: 0, configurable_positions: 0, critical_positions: 0, universal_lanes: 0, observation_nodes: 0, controlled_branches: 0, critical_hazard_positions: 0, high_hazard_positions: 0, proof_open_positions: 0, supported_targets: 2, direct_percentage: 0, configurable_percentage: 0, shared_route_savings_percentage: 0 }, safe_state_contract: { unknown_target: "open", target_change: "open" }, bootstrap: { status: "automatic", debug_positions: [], rule: "Fixture-only preview." }, fabric: { strategy: "fixture", universal_lanes: 0, observation_nodes: 0, controlled_branches: 0, control_bits_required: 0, cohort_configurations: 0, capacity_limit: null, configuration_authority: "fixture", mandatory_interlocks: [] }, target_cohorts: [], support_cells: [], positions: [], proofs: [] };

export type StmFixtureOptions = {
  status?: typeof STM_STATUS;
  mcus?: McusResponse;
  mcusBehavior?: ScenarioFixture["behavior"];
  pinoutBehavior?: ScenarioFixture["behavior"];
};

/** Typed endpoint fixtures cover the complete production STM query surface. */
export function stmReadFixtures(options: StmFixtureOptions = {}): ScenarioFixture[] {
  const status = options.status ?? STM_STATUS;
  const mcus = options.mcus ?? STM_MCUS;
  return [
    { method: "GET", path: "/api/onboarding", params: {}, body: undefined, response: ONBOARDING_READY },
    { method: "GET", path: "/api/stm/status", params: {}, body: undefined, response: status },
    { method: "GET", path: "/api/stm/families", params: {}, body: undefined, response: STM_FAMILIES },
    { method: "GET", path: "/api/stm/mcus", params: {}, body: undefined, response: mcus, behavior: options.mcusBehavior },
    { method: "GET", path: "/api/stm/mcus", params: { family: "STM32F4" }, body: undefined, response: mcus, behavior: options.mcusBehavior },
    { method: "GET", path: "/api/stm/pinout", params: { part: STM_PART }, body: undefined, response: STM_PINOUT, behavior: options.pinoutBehavior },
    { method: "GET", path: "/api/stm/pin/af", params: { part: STM_PART, position: "23" }, body: undefined, response: { position: "23", alternate_functions: STM_PINOUT.pins[0].alternate_functions } },
    { method: "GET", path: "/api/stm/signal/candidates", params: { part: STM_PART, signal: "USART1_TX" }, body: undefined, response: { part: STM_PART, signal: "USART1_TX", candidates: [{ position: "23", canonical_pin_name: "PA9", af_index: 7 }] } },
    { method: "GET", path: "/api/stm/compat/suggestions", params: { package: "LQFP144", family: "STM32F4,STM32F7" }, body: undefined, response: { groups: [] } },
    { method: "POST", path: "/api/stm/compat/union", params: {}, body: { families: ["STM32F4", "STM32F7"], package: "LQFP144" }, response: union, localOutcome: { state: "succeeded", target: "stm.bench" } },
    { method: "POST", path: "/api/stm/target-definition", params: {}, body: expectBody(), response: { format: "stm-target-definition/2", artifact_digest: "fixture", scope: { package: "LQFP144", targets: [] }, readiness: { status: "ready", blockers: [], warnings: [] }, positions: [] }, localOutcome: { state: "succeeded", target: "stm.bench" } },
    { method: "POST", path: "/api/stm/socket-solution", params: {}, body: expectBody(), response: socket, localOutcome: { state: "succeeded", target: "stm.bench" } },
  ];
}

function expectBody() { return { parts: [STM_PART], policy: { id: "fixture", revision: 1, requirements: [], safety_rules: [] } }; }

function isRecord(value: unknown): value is Record<string, unknown> { return value !== null && typeof value === "object" && !Array.isArray(value); }
export const stmFixtureValidators = createScenarioFixtureValidatorRegistry({
  "GET /api/stm/status": (fixture) => fixture.body === undefined && isRecord(fixture.response) && typeof fixture.response.built === "boolean",
  "GET /api/stm/families": (fixture) => fixture.body === undefined && isRecord(fixture.response) && Array.isArray(fixture.response.families),
  "GET /api/stm/mcus": (fixture) => fixture.body === undefined && isRecord(fixture.response) && Array.isArray(fixture.response.mcus),
  "GET /api/stm/pinout": (fixture) => fixture.body === undefined && isRecord(fixture.response) && Array.isArray(fixture.response.pins),
  "GET /api/stm/pin/af": (fixture) => fixture.body === undefined && isRecord(fixture.response) && Array.isArray(fixture.response.alternate_functions),
  "GET /api/stm/signal/candidates": (fixture) => fixture.body === undefined && isRecord(fixture.response) && Array.isArray(fixture.response.candidates),
  "GET /api/stm/compat/suggestions": (fixture) => fixture.body === undefined && isRecord(fixture.response) && Array.isArray(fixture.response.groups),
  "POST /api/stm/compat/union": (fixture) => isRecord(fixture.body) && isRecord(fixture.response) && Array.isArray(fixture.response.parts),
  "POST /api/stm/target-definition": (fixture) => isRecord(fixture.body) && isRecord(fixture.response) && fixture.response.format === "stm-target-definition/2",
  "POST /api/stm/socket-solution": (fixture) => isRecord(fixture.body) && isRecord(fixture.response) && fixture.response.format === "stm-socket-solution/1",
}, projectFixtureValidators);
