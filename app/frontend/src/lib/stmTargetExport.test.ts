import { describe, expect, it } from "vitest";
import { stmAccessPlanCsv, stmPinPlanCsv } from "./stmTargetExport";
import type { TargetDefinitionDTO, TargetDefinitionPosition } from "../api/types";

/**
 * The two handoff CSVs, exercised on the per-row derivations rather than the header shape
 * (`CompatibilityWorkbench.test.tsx` already pins the columns and the digest binding).
 *
 * What is locked here is what each ROW says about ONE position or ONE requirement: which
 * requirements, foundation obligations and routing paths a position carries, which scope targets
 * it is absent from, and which service group a requirement resolves to when the definition
 * declares that id twice. Those are the answers a consuming design acts on, so they must not
 * shift with how the derivation is written.
 */

type Requirement = TargetDefinitionDTO["requirements"][number];
type ServiceGroup = TargetDefinitionDTO["service_groups"][number];
type FoundationGroup = TargetDefinitionDTO["functional_foundation"]["groups"][number];
type RoutingPath = TargetDefinitionDTO["routing_requirements"]["paths"][number];

const TARGETS = [
  { ref: "STM32F407ZGT6", family: "STM32F4", line: "STM32F407", verified_mpns: ["STM32F407ZGT6"] },
  { ref: "STM32F429ZET6", family: "STM32F4", line: "STM32F429", verified_mpns: [] },
];

function perTarget(ref: string, pinName: string) {
  return {
    ref,
    family: "STM32F4",
    canonical_pin_name: pinName,
    electrical_class: "io",
    critical_identity: null,
    roles: [],
    functions: [],
    alternate_functions: [],
    access_tags: [],
  };
}

function position(over: Partial<TargetDefinitionPosition> = {}): TargetDefinitionPosition {
  return {
    position: "23",
    position_kind: "numeric",
    lqfp_side: "left",
    bga_row: null,
    bga_col: null,
    silicon_class: "stable_io",
    board_action: "direct",
    identities: [],
    access_tags: [],
    access_tags_union: [],
    present_on: 2,
    total_targets: 2,
    route_ids: [],
    hazard: "",
    per_target: [perTarget("STM32F407ZGT6", "PA9"), perTarget("STM32F429ZET6", "PA9")],
    ...over,
  };
}

function requirement(over: Partial<Requirement> = {}): Requirement {
  return {
    id: "uart_tx",
    label: "UART Transmit",
    net: "UART_TX",
    required: true,
    implementation_required: true,
    category: "debug",
    service_group: "console",
    protocol: "uart",
    direction: "out",
    access_plane: "service",
    purposes: [],
    claim_scope: "pin-capability",
    route_kind: "direct",
    implementation_kind: "direct",
    coverage_status: "complete",
    applicable_targets: ["STM32F407ZGT6", "STM32F429ZET6"],
    not_applicable_targets: [],
    missing_targets: [],
    blocked_targets: [],
    routes: [],
    candidates_by_target: {},
    candidate_counts: {},
    onehot_group: null,
    evidence: [],
    ...over,
  };
}

function serviceGroup(over: Partial<ServiceGroup> = {}): ServiceGroup {
  return {
    id: "console",
    label: "Console",
    category: "debug",
    protocol: "uart",
    required: true,
    claim_scope: "pin-capability",
    purposes: [],
    requirement_ids: ["uart_tx"],
    required_requirement_ids: ["uart_tx"],
    status: "complete",
    applicable_target_count: 2,
    complete_target_count: 2,
    not_applicable_targets: [],
    per_target: [],
    entry_conditions: [],
    protection_constraints: [],
    side_effects: [],
    procedure_refs: [],
    destructive: false,
    evidence: [],
    ...over,
  };
}

function foundationGroup(over: Partial<FoundationGroup> = {}): FoundationGroup {
  return {
    id: "digital-supply",
    label: "Digital Supply",
    obligation: "decouple",
    applicability: "when-present",
    claim_scope: "pin-obligation",
    network_evidence_required: true,
    status: "complete",
    present_target_count: 2,
    resolved_target_count: 2,
    positions: [],
    unresolved_positions: [],
    per_target: [],
    ...over,
  };
}

function routingPath(over: Partial<RoutingPath> = {}): RoutingPath {
  return {
    kind: "route",
    position: "23",
    requested_net: "UART_TX",
    requirement_id: "uart_tx",
    exclusivity_group: null,
    safe_default: "open",
    path_id: "p1",
    ...over,
  };
}

function definition(over: Partial<TargetDefinitionDTO> = {}): TargetDefinitionDTO {
  return {
    format: "stm-target-definition/2",
    compiler_rev: 2,
    artifact_digest: "aaaaaaaaaaaabbbb",
    profile: { id: "default", revision: 1, coverage_mode: "strict", policy_digest: "pppp" },
    scope: { package: "LQFP144", families: ["STM32F4"], target_count: 2, targets: TARGETS },
    provenance: {
      silicon_source: "cube",
      source_sha256: "ssss",
      source_built_at: "2026-01-01",
      classifier_rev: 1,
      af_schema_rev: 1,
      geometry_rev: 1,
      policy_digest: "pppp",
    },
    readiness: { status: "ready", blockers: [], warnings: [] },
    summary: {
      silicon_classes: {},
      board_actions: {},
      required_routes: 1,
      switched_routes: 0,
      safety_rules: 0,
      service_groups: 1,
      foundation_groups: 0,
    },
    requirements: [],
    service_groups: [],
    functional_foundation: {
      claim_scope: "pin-obligation",
      network_values_authority: "external-target-documentation-required",
      status: "complete",
      unresolved_positions: [],
      groups: [],
    },
    safety_rules: [],
    routing_requirements: {
      strategy: "implementation-neutral-independent-paths",
      safe_default: "open",
      required_independent_paths: 0,
      maximum_independent_paths: null,
      limit_status: "unbounded",
      paths: [],
    },
    universalization: {
      strategy: "one-package-universal-support",
      implementation_owner: "consuming-design",
      implementation_technology: "unspecified",
      required_independent_paths: 0,
      safe_default: "open",
      state_contract: {
        unknown_target: "all-independent-paths-open",
        controller_startup: "all-independent-paths-open",
        controller_reset: "all-independent-paths-open",
        power_loss: "all-independent-paths-open",
        target_change: "open-before-reconfigure",
        identity_mismatch: "refuse-activation",
        configured: "only-target-permitted-paths-may-conduct",
      },
      summary: { direct_or_fixed: 1, selectable: 0, excluded_from_common_interface: 0 },
      strategies: [],
    },
    positions: [],
    ...over,
  };
}

/** The CSV body split into rows of already-unquoted cells (the header row dropped). */
function dataRows(csv: string): string[][] {
  return csv
    .replace(/^﻿/, "")
    .trimEnd()
    .split("\r\n")
    .slice(1)
    .map((row) => row.slice(1, -1).split('","'));
}

function column(csv: string, header: string): string[] {
  const headers = csv.replace(/^﻿/, "").split("\r\n")[0].slice(1, -1).split('","');
  const index = headers.indexOf(header);
  expect(index, `${header} column`).toBeGreaterThanOrEqual(0);
  return dataRows(csv).map((row) => row[index]);
}

describe("stmPinPlanCsv — the per-position derivations", () => {
  const twoPositions = definition({
    positions: [position({ position: "23" }), position({ position: "24" })],
    requirements: [
      requirement({ id: "uart_tx", routes: [{ ref: "STM32F407ZGT6", position: "23", canonical_pin_name: "PA9", signal: "USART1_TX", af_index: 7, usable: true, safety_branch: null }] }),
      requirement({ id: "swdio", net: "SWDIO", implementation_kind: "switched", coverage_status: "partial", routes: [{ ref: "STM32F407ZGT6", position: "24", canonical_pin_name: "PA13", signal: "SWDIO", af_index: 0, usable: true, safety_branch: null }] }),
    ],
    functional_foundation: {
      claim_scope: "pin-obligation",
      network_values_authority: "external-target-documentation-required",
      status: "partial",
      unresolved_positions: ["24"],
      groups: [
        foundationGroup({ id: "digital-supply", status: "complete", positions: ["23", "24"], unresolved_positions: ["24"] }),
        foundationGroup({ id: "analog-supply", status: "partial", positions: ["24"], unresolved_positions: [] }),
      ],
    },
    routing_requirements: {
      strategy: "implementation-neutral-independent-paths",
      safe_default: "open",
      required_independent_paths: 1,
      maximum_independent_paths: null,
      limit_status: "unbounded",
      paths: [
        routingPath({ path_id: "p1", position: "23" }),
        routingPath({ path_id: "p2", position: "24", requirement_id: null, branch_id: "b1", requested_net: "SWDIO" }),
      ],
    },
  });

  it("gives each position only the requirements that route to it", () => {
    expect(column(stmPinPlanCsv(twoPositions), "route_commitments")).toEqual([
      "uart_tx:UART_TX:direct:complete",
      "swdio:SWDIO:switched:partial",
    ]);
  });

  it("splits a position's foundation obligations from the ones still unresolved for it", () => {
    const plan = stmPinPlanCsv(twoPositions);
    // position 23 carries the digital-supply obligation and it is resolved there; position 24
    // carries both groups and only digital-supply is unresolved for it.
    expect(column(plan, "foundation_obligations")).toEqual([
      "digital-supply:complete",
      "analog-supply:partial; digital-supply:complete",
    ]);
    expect(column(plan, "foundation_unresolved")).toEqual(["", "digital-supply"]);
  });

  it("names each position's own routing paths, owned by branch id when there is no requirement", () => {
    expect(column(stmPinPlanCsv(twoPositions), "routing_path_requirements")).toEqual([
      "p1:uart_tx:UART_TX:default-open",
      "p2:b1:SWDIO:default-open",
    ]);
  });

  it("lists the scope targets a position is absent from, and nothing when it is on all of them", () => {
    const plan = stmPinPlanCsv(
      definition({
        positions: [
          position({ position: "23" }),
          position({ position: "24", per_target: [perTarget("STM32F429ZET6", "PA13")], present_on: 1 }),
          position({ position: "25", per_target: [] , present_on: 0 }),
        ],
      }),
    );
    expect(column(plan, "missing_targets")).toEqual([
      "",
      "STM32F407ZGT6",
      "STM32F407ZGT6; STM32F429ZET6",
    ]);
  });

  it("leaves the per-position columns empty when nothing matches, and emits no data row for no positions", () => {
    const bare = stmPinPlanCsv(
      definition({
        positions: [position({ position: "99" })],
        requirements: [requirement()],
        functional_foundation: {
          claim_scope: "pin-obligation",
          network_values_authority: "external-target-documentation-required",
          status: "complete",
          unresolved_positions: [],
          groups: [foundationGroup({ positions: ["23"] })],
        },
        routing_requirements: {
          strategy: "implementation-neutral-independent-paths",
          safe_default: "open",
          required_independent_paths: 0,
          maximum_independent_paths: null,
          limit_status: "unbounded",
          paths: [routingPath({ position: "23" })],
        },
      }),
    );
    expect(column(bare, "route_commitments")).toEqual([""]);
    expect(column(bare, "foundation_obligations")).toEqual([""]);
    expect(column(bare, "foundation_unresolved")).toEqual([""]);
    expect(column(bare, "routing_path_requirements")).toEqual([""]);
    expect(dataRows(stmPinPlanCsv(definition()))).toEqual([]);
  });
});

describe("stmAccessPlanCsv — the per-requirement service group", () => {
  it("emits one row per requirement and target, carrying that requirement's service group", () => {
    const plan = stmAccessPlanCsv(
      definition({
        requirements: [requirement({ id: "uart_tx" }), requirement({ id: "swdio", service_group: "debug-port" })],
        service_groups: [
          serviceGroup({ id: "console", status: "complete", entry_conditions: ["powered"] }),
          serviceGroup({ id: "debug-port", status: "partial", entry_conditions: ["halted"], destructive: true }),
        ],
      }),
    );
    expect(column(plan, "requirement_id")).toEqual(["uart_tx", "uart_tx", "swdio", "swdio"]);
    expect(column(plan, "target_ref")).toEqual([
      "STM32F407ZGT6",
      "STM32F429ZET6",
      "STM32F407ZGT6",
      "STM32F429ZET6",
    ]);
    expect(column(plan, "service_status")).toEqual([
      "complete",
      "complete",
      "partial",
      "partial",
    ]);
    expect(column(plan, "entry_conditions")).toEqual(["powered", "powered", "halted", "halted"]);
    expect(column(plan, "destructive")).toEqual(["false", "false", "true", "true"]);
  });

  it("keeps the FIRST declaration when a service group id is repeated", () => {
    const plan = stmAccessPlanCsv(
      definition({
        requirements: [requirement()],
        service_groups: [
          serviceGroup({ id: "console", status: "complete", side_effects: ["first"] }),
          serviceGroup({ id: "console", status: "unavailable", side_effects: ["second"] }),
        ],
      }),
    );
    expect(column(plan, "service_status")).toEqual(["complete", "complete"]);
    expect(column(plan, "side_effects")).toEqual(["first", "first"]);
  });

  it("blanks the service columns for a requirement whose group is not declared", () => {
    const plan = stmAccessPlanCsv(
      definition({
        requirements: [requirement({ service_group: "nowhere" })],
        service_groups: [serviceGroup({ id: "console" })],
      }),
    );
    expect(column(plan, "service_status")).toEqual(["", ""]);
    expect(column(plan, "procedure_refs")).toEqual(["", ""]);
    expect(column(plan, "destructive")).toEqual(["false", "false"]);
  });
});
