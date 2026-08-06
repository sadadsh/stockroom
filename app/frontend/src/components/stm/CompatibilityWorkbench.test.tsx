import { describe, expect, it, vi, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createElement, type ReactNode } from "react";
import { CompatibilityWorkbench } from "./CompatibilityWorkbench";
import { benchExport, benchSets, packageKind, packagesForScope } from "./benchModel";
import { api, ApiError } from "../../api/client";
import type {
  FamiliesResponse,
  SocketSolutionDTO,
  SuggestionsResponse,
  TargetDefinitionDTO,
  TargetDefinitionPolicy,
  UnionDTO,
} from "../../api/types";
import {
  makeStmTargetRequest,
  stmAccessPlanCsv,
  stmPinPlanCsv,
  stmTargetExportFilename,
} from "../../lib/stmTargetExport";
import {
  stmSocketControlStatesCsv,
  stmSocketExportFilename,
  stmSocketPositionsCsv,
  stmSocketRequestJson,
} from "../../lib/stmSocketSolutionExport";

const FAMILIES: FamiliesResponse = {
  families: [
    { family: "STM32F4", lines: ["STM32F407"], mcu_count: 40, packages: ["LQFP100", "LQFP144"] },
    { family: "STM32F7", lines: ["STM32F746"], mcu_count: 20, packages: ["LQFP144"] },
  ],
};

const SUGGESTIONS: SuggestionsResponse = {
  groups: [
    {
      signature_id: "sig-base",
      tier: "baseline",
      package: "LQFP144",
      family: "STM32F4 + STM32F7",
      refs: ["STM32F429ZET6", "STM32F746ZGT6"],
      divergent_positions: 0,
    },
    {
      signature_id: "sig-div-a",
      tier: "divergent",
      package: "LQFP144",
      family: "STM32F4 + STM32F7",
      refs: ["STM32F407ZGT6"],
      divergent_positions: 12,
    },
  ],
};

function unionResult(): UnionDTO {
  return {
    parts: ["STM32F429ZET6", "STM32F746ZGT6", "STM32F407ZGT6"],
    resolved: [
      { ref: "STM32F429ZET6", mpn: "STM32F429ZET6" },
      { ref: "STM32F746ZGT6", mpn: "STM32F746ZGT6" },
      { ref: "STM32F407ZGT6", mpn: "STM32F407ZGT6" },
    ],
    package: "LQFP144",
    family: "STM32F4 + STM32F7",
    families: ["STM32F4", "STM32F7"],
    grain: "per-part",
    positions: [
      {
        position: "1",
        position_kind: "numeric",
        lqfp_side: "left",
        bga_row: null,
        bga_col: null,
        classification: "shared",
        present_on: 3,
        total: 3,
        per_part: [],
        reconcile: null,
      },
      {
        position: "23",
        position_kind: "numeric",
        lqfp_side: "left",
        bga_row: null,
        bga_col: null,
        classification: "divergent",
        present_on: 3,
        total: 3,
        per_part: [
          { ref: "STM32F429ZET6", canonical_pin_name: "PA9", roles: [], functions: ["USART1_TX"] },
          { ref: "STM32F746ZGT6", canonical_pin_name: "PA9", roles: [], functions: ["USART1_TX"] },
          { ref: "STM32F407ZGT6", canonical_pin_name: "PA9", roles: [], functions: ["ETH_TXD3"] },
        ],
        reconcile: {
          swappable: false,
          swaps: [],
          reason: "STM32F407ZGT6 offers no alternate function carrying USART1_TX here",
        },
      },
    ],
    verdict: {
      interchangeable: false,
      swaps_required: 0,
      blocking: [{ position: "23", signal: "USART1_TX", reason: "no AF carries it" }],
    },
  };
}

function targetDefinitionResult(): TargetDefinitionDTO {
  return {
    format: "stm-target-definition/2",
    compiler_rev: 8,
    artifact_digest: "a".repeat(64),
    profile: {
      id: "stm32-core-bring-up",
      revision: 1,
      coverage_mode: "explicit-device-set",
      policy_digest: "b".repeat(64),
    },
    scope: {
      package: "LQFP144",
      families: ["STM32F4", "STM32F7"],
      target_count: 3,
      targets: [
        {
          ref: "STM32F407ZGT6",
          family: "STM32F4",
          line: "STM32F407",
          verified_mpns: [],
        },
        {
          ref: "STM32F429ZET6",
          family: "STM32F4",
          line: "STM32F429",
          verified_mpns: [],
        },
        {
          ref: "STM32F746ZGT6",
          family: "STM32F7",
          line: "STM32F746",
          verified_mpns: [],
        },
      ],
    },
    provenance: {
      silicon_source: "STM32CubeMX XML",
      source_sha256: "c".repeat(64),
      source_built_at: "2026-07-23T00:00:00Z",
      classifier_rev: 2,
      af_schema_rev: 1,
      geometry_rev: 3,
      policy_digest: "b".repeat(64),
    },
    readiness: { status: "ready", blockers: [], warnings: [] },
    summary: {
      silicon_classes: { stable_io: 1 },
      board_actions: { direct: 1 },
      required_routes: 1,
      switched_routes: 0,
      safety_rules: 0,
      service_groups: 0,
      foundation_groups: 0,
    },
    requirements: [
      {
        id: "uart_tx",
        label: "USART1 TX",
        net: "USART1_TX",
        required: true,
        implementation_required: true,
        category: "serial",
        service_group: "serial-uart",
        protocol: "UART",
        direction: "output",
        access_plane: "function",
        purposes: ["communication"],
        claim_scope: "pin-capability",
        route_kind: "direct",
        implementation_kind: "direct",
        coverage_status: "complete",
        applicable_targets: [
          "STM32F407ZGT6",
          "STM32F429ZET6",
          "STM32F746ZGT6",
        ],
        not_applicable_targets: [],
        missing_targets: [],
        blocked_targets: [],
        routes: [
          {
            ref: "STM32F407ZGT6",
            position: "23",
            canonical_pin_name: "PA9",
            signal: "USART1_TX",
            af_index: 7,
            usable: true,
            safety_branch: null,
          },
          {
            ref: "STM32F429ZET6",
            position: "23",
            canonical_pin_name: "PA9",
            signal: "USART1_TX",
            af_index: 7,
            usable: true,
            safety_branch: null,
          },
          {
            ref: "STM32F746ZGT6",
            position: "23",
            canonical_pin_name: "PA9",
            signal: "USART1_TX",
            af_index: 7,
            usable: true,
            safety_branch: null,
          },
        ],
        candidates_by_target: {
          STM32F407ZGT6: [
            {
              ref: "STM32F407ZGT6",
              position: "23",
              canonical_pin_name: "PA9",
              signal: "USART1_TX",
              af_index: 7,
            },
          ],
          STM32F429ZET6: [
            {
              ref: "STM32F429ZET6",
              position: "23",
              canonical_pin_name: "PA9",
              signal: "USART1_TX",
              af_index: 7,
            },
          ],
          STM32F746ZGT6: [
            {
              ref: "STM32F746ZGT6",
              position: "23",
              canonical_pin_name: "PA9",
              signal: "USART1_TX",
              af_index: 7,
            },
          ],
        },
        candidate_counts: {
          STM32F407ZGT6: 1,
          STM32F429ZET6: 1,
          STM32F746ZGT6: 1,
        },
        onehot_group: null,
        evidence: ["fixture"],
      },
    ],
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
      summary: {
        direct_or_fixed: 1,
        selectable: 0,
        excluded_from_common_interface: 0,
      },
      strategies: [
        {
          position: "23",
          silicon_class: "stable_io",
          primitive: "universal-breakout",
          explanation: "One shared GPIO position can feed a common board net.",
          selection: "none",
          safe_default: null,
          identities: ["PA9"],
          branches: [],
          constraints: [],
          validation: {
            status: "not-required",
            required_checks: [],
            failure_action: "none",
          },
          evidence_status: "compiler-derived",
          implementation_owner: "consuming-design",
        },
      ],
    },
    positions: [
      {
        position: "23",
        position_kind: "numeric",
        lqfp_side: "left",
        bga_row: null,
        bga_col: null,
        silicon_class: "stable_io",
        board_action: "direct",
        identities: ["PA9"],
        access_tags: ["usart"],
        access_tags_union: ["usart"],
        present_on: 3,
        total_targets: 3,
        route_ids: ["uart_tx"],
        hazard: "",
        per_target: [
          {
            ref: "STM32F407ZGT6",
            family: "STM32F4",
            canonical_pin_name: "PA9",
            electrical_class: "io",
            critical_identity: null,
            roles: [],
            functions: ["USART1_TX", "ETH_TXD3"],
            alternate_functions: [],
            access_tags: ["usart"],
          },
          {
            ref: "STM32F429ZET6",
            family: "STM32F4",
            canonical_pin_name: "PA9",
            electrical_class: "io",
            critical_identity: null,
            roles: [],
            functions: ["USART1_TX"],
            alternate_functions: [],
            access_tags: ["usart"],
          },
          {
            ref: "STM32F746ZGT6",
            family: "STM32F7",
            canonical_pin_name: "PA9",
            electrical_class: "io",
            critical_identity: null,
            roles: [],
            functions: ["USART1_TX"],
            alternate_functions: [],
            access_tags: ["usart"],
          },
        ],
      },
    ],
  };
}

function socketSolutionResult(): SocketSolutionDTO {
  const envelope = {
    authority: "family-envelope",
    families: ["STM32F4", "STM32F7"],
    operating_v: [1.7, 3.6] as [number, number],
    per_pin_current_ma: 20,
    injection_current_ma: 5,
    five_v_tolerant: false,
    citations: ["STM32 family electrical limits"],
  };
  const hazard = {
    level: "high" as const,
    rank: 2,
    category: "exclusive-roles",
    label: "Mutually Exclusive Electrical Roles",
    reason: "Only the branch declared for the installed target may conduct.",
  };
  const cellContract = {
    architecture: "fail-closed-universal-position-cell" as const,
    selection_authority: "declared-target-profile" as const,
    default_state: "all-branches-open" as const,
    planes: [
      {
        id: "signal",
        requirements: ["bidirectional high-impedance signal path"],
      },
      {
        id: "dedicated-network",
        requirements: ["electrically isolated target-specific support network"],
      },
    ],
    mandatory_features: [
      "hardware-enforced one-hot branch selection",
      "target profile is declared and locked before any target rail is enabled",
    ],
    power_sequence: [
      "hold every target-facing source and return branch open",
      "load and verify the exact target cohort",
    ],
    failure_response: "force-all-branches-open" as const,
    hazard,
  };
  return {
    format: "stm-socket-solution/1",
    compiler_rev: 1,
    artifact_digest: "d".repeat(64),
    source_definition_digest: "a".repeat(64),
    scope: {
      package: "LQFP144",
      families: ["STM32F4", "STM32F7"],
      target_count: 3,
      targets: targetDefinitionResult().scope.targets,
      target_index: [
        { index: 0, ref: "STM32F407ZGT6", family: "STM32F4", line: "STM32F407" },
        { index: 1, ref: "STM32F429ZET6", family: "STM32F4", line: "STM32F429" },
        { index: 2, ref: "STM32F746ZGT6", family: "STM32F7", line: "STM32F746" },
      ],
    },
    provenance: { silicon_source: "STM32CubeMX XML" },
    status: {
      solution: "conditional",
      evidence: "complete",
      bootstrap: "requires-declared-target",
      blockers: [],
      warnings: ["Target identity must be declared before configurable branches close."],
    },
    closure: {
      verdict: "architecture-complete",
      release: "ready",
      zero_omission: true,
      supported_target_count: 3,
      unsupported_target_count: 0,
      target_coverage_percentage: 100,
      gates: [
        {
          id: "target-coverage",
          label: "Target Coverage",
          status: "pass",
          value: "3/3",
          detail: "Every target has one complete configuration.",
        },
        {
          id: "configuration-integrity",
          label: "Configuration Integrity",
          status: "pass",
          value: "0 Errors",
          detail: "Every target belongs to one cohort.",
        },
        {
          id: "safe-before-power",
          label: "Safe Before Power",
          status: "pass",
          value: "Declared Target Required",
          detail: "The target profile is applied before target power.",
        },
        {
          id: "required-access",
          label: "Required Access",
          status: "pass",
          value: "5/5 Complete",
          detail: "All required access routes are covered.",
        },
        {
          id: "electrical-verification",
          label: "Electrical Verification",
          status: "pass",
          value: "Closed",
          detail: "All checks are closed.",
        },
      ],
      required_requirement_coverage: [],
      configuration_errors: [],
    },
    summary: {
      target_count: 3,
      target_cohort_count: 2,
      position_count: 1,
      support_cell_count: 1,
      direct_positions: 0,
      configurable_positions: 1,
      critical_positions: 0,
      universal_lanes: 1,
      observation_nodes: 1,
      controlled_branches: 2,
      critical_hazard_positions: 0,
      high_hazard_positions: 1,
      proof_open_positions: 0,
      supported_targets: 3,
      direct_percentage: 0,
      configurable_percentage: 100,
      shared_route_savings_percentage: 33.3,
    },
    safe_state_contract: {
      unknown_target: "all-controlled-branches-open",
      target_change: "open-before-reconfigure",
    },
    bootstrap: {
      status: "requires-declared-target",
      debug_positions: [],
      rule: "Declare and verify target identity before enabling a branch.",
    },
    fabric: {
      strategy: "shared-universal-lanes-with-selected-role-islands",
      universal_lanes: 1,
      observation_nodes: 1,
      controlled_branches: 2,
      control_bits_required: 1,
      cohort_configurations: 2,
      capacity_limit: null,
      configuration_authority: "declared-target-before-power",
      mandatory_interlocks: [
        "all branches default open",
        "hardware one-hot selection per position",
      ],
    },
    target_cohorts: [
      {
        id: "cohort-1",
        target_mask: "03",
        target_count: 2,
        percentage: 66.7,
        families: ["STM32F4"],
        target_examples: ["STM32F407ZGT6", "STM32F429ZET6"],
        configuration: { "23": "pos-23-usart1-tx" },
      },
      {
        id: "cohort-2",
        target_mask: "04",
        target_count: 1,
        percentage: 33.3,
        families: ["STM32F7"],
        target_examples: ["STM32F746ZGT6"],
        configuration: { "23": "pos-23-eth-txd3" },
      },
    ],
    support_cells: [
      {
        id: "cell-selected-roles-1",
        signature: "selected-roles:universal-io,eth-txd3",
        type: "selected-roles",
        label: "Selected Socket Roles",
        positions: ["23"],
        position_count: 1,
        mode_count: 2,
        controlled: true,
        safe_default: "open",
        hazard_contract: hazard,
        cell_contract: cellContract,
        branch_pattern: [
          {
            mode_id: "universal-io",
            label: "Universal I/O",
            endpoint: "universal-io",
            controlled: true,
            plane: "signal",
          },
          {
            mode_id: "eth-txd3",
            label: "ETH TXD3",
            endpoint: "critical:eth-txd3",
            controlled: true,
            plane: "dedicated-network",
          },
        ],
        implementation_capabilities: {
          default_open: true,
          hardware_reset: true,
          readback: true,
          break_before_make: true,
          bidirectional: true,
        },
      },
    ],
    positions: [
      {
        position: "23",
        position_kind: "numeric",
        lqfp_side: "left",
        bga_row: null,
        bga_col: null,
        cell_type: "selected-roles",
        cell_label: "Selected Socket Roles",
        solution_reason: "The two roles require mutually exclusive branches.",
        network_requirements: [],
        validation_checks: [],
        hazard_contract: hazard,
        cell_contract: cellContract,
        controlled: true,
        safe_default: "open",
        observation_node: true,
        universal_lane: true,
        modes: [
          {
            id: "universal-io",
            label: "Universal I/O",
            kind: "signal",
            conductive: true,
            endpoint: "universal-io",
            target_mask: "03",
            target_count: 2,
            percentage: 66.7,
            target_examples: ["STM32F407ZGT6", "STM32F429ZET6"],
            functions: ["USART1_TX"],
            access_tags: ["usart"],
            electrical_envelope: envelope,
          },
          {
            id: "eth-txd3",
            label: "ETH TXD3",
            kind: "critical",
            conductive: true,
            endpoint: "critical:eth-txd3",
            target_mask: "04",
            target_count: 1,
            percentage: 33.3,
            target_examples: ["STM32F746ZGT6"],
            functions: ["ETH_TXD3"],
            access_tags: ["ethernet"],
            electrical_envelope: envelope,
          },
        ],
        branches: [
          {
            id: "pos-23-usart1-tx",
            mode_id: "universal-io",
            label: "Universal I/O",
            endpoint: "universal-io",
            target_mask: "03",
            controlled: true,
            default_state: "open",
            direction: "bidirectional",
            break_before_make: true,
            plane: "signal",
            electrical_envelope: envelope,
          },
          {
            id: "pos-23-eth-txd3",
            mode_id: "eth-txd3",
            label: "ETH TXD3",
            endpoint: "critical:eth-txd3",
            target_mask: "04",
            controlled: true,
            default_state: "open",
            direction: "bidirectional",
            break_before_make: true,
            plane: "dedicated-network",
            electrical_envelope: envelope,
          },
        ],
        mode_count: 2,
        agreement_count: 2,
        agreement_percentage: 66.7,
        support_cell_id: "cell-selected-roles-1",
        hazard: "",
      },
    ],
    proofs: [],
  };
}

function wrapperWith(qc: QueryClient) {
  return ({ children }: { children: ReactNode }) =>
    createElement(QueryClientProvider, { client: qc }, children);
}

function freshClient() {
  return new QueryClient({ defaultOptions: { queries: { retry: false } } });
}

afterEach(() => vi.restoreAllMocks());

describe("packagesForScope", () => {
  it("unions packages across the selected families with honest coverage", () => {
    const out = packagesForScope(FAMILIES.families, ["STM32F4", "STM32F7"]);
    const byName = Object.fromEntries(out.map((p) => [p.name, p]));
    // LQFP100 exists on F4 only: still LISTED, with F7 named as missing
    expect(byName.LQFP100.covered).toEqual(["STM32F4"]);
    expect(byName.LQFP100.missing).toEqual(["STM32F7"]);
    // LQFP144 is fully covered
    expect(byName.LQFP144.covered).toEqual(["STM32F4", "STM32F7"]);
    expect(byName.LQFP144.missing).toEqual([]);
  });
});

describe("packageKind", () => {
  it("classifies package names for the filter chips", () => {
    expect(packageKind("LQFP144")).toBe("LQFP");
    expect(packageKind("UFQFPN48")).toBe("QFN");
    expect(packageKind("UFBGA176")).toBe("BGA");
    expect(packageKind("WLCSP81")).toBe("CSP");
    expect(packageKind("TSSOP20")).toBe("Other");
  });
});

describe("benchSets", () => {
  it("builds the stepper: All Parts first, then Baseline, then lettered divergent groups", () => {
    const sets = benchSets(SUGGESTIONS.groups, 3);
    expect(sets.map((s) => s.label)).toEqual(["All Parts", "Baseline", "Divergent A"]);
    expect(sets[0].refs).toBeNull();
    expect(sets[0].count).toBe(3);
    expect(sets[2].divergent).toBe(12);
  });
});

describe("benchExport", () => {
  it("bundles the scope, every set, and the active union as a generic analysis", () => {
    const sets = benchSets(SUGGESTIONS.groups, 3);
    const parsed = JSON.parse(
      benchExport({ families: ["STM32F4", "STM32F7"], package: "LQFP144" }, sets, unionResult()),
    );
    expect(parsed.format).toBe("stm-bench/1");
    expect(parsed.scope.package).toBe("LQFP144");
    expect(parsed.sets).toHaveLength(3);
    expect(parsed.active_set.verdict.interchangeable).toBe(false);
    expect(parsed.active_set.positions.some((p: { position: string }) => p.position === "23")).toBe(
      true,
    );
  });
});

describe("STM target handoff exports", () => {
  const policy: TargetDefinitionPolicy = {
    id: "stm32-core-bring-up",
    revision: 1,
    requirements: [],
    safety_rules: [],
    routing_constraints: {
      safe_default: "open",
    },
  };

  it("pins the compiled device refs in a reproducible compiler request", () => {
    const request = makeStmTargetRequest(targetDefinitionResult(), policy);
    expect(request.format).toBe("stm-target-request/2");
    expect(request.selection).toEqual({
      parts: ["STM32F407ZGT6", "STM32F429ZET6", "STM32F746ZGT6"],
    });
    expect(request.policy).toBe(policy);
  });

  it("exports one digest-bound physical closure row per package position", () => {
    const definition = targetDefinitionResult();
    const plan = stmPinPlanCsv(definition);
    expect(plan.startsWith("\uFEFF")).toBe(true);
    expect(plan).toContain('"artifact_digest"');
    expect(plan).toContain('"universal_primitive"');
    expect(plan).toContain('"active_routing_paths"');
    expect(plan).toContain('"passive_conditioned_paths"');
    expect(plan).toContain('"fallback_topology"');
    expect(plan).toContain('"strategy_constraints"');
    expect(plan).toContain('"validation_checks"');
    expect(plan).toContain('"global_safe_state_contract"');
    expect(plan).toContain('"routing_path_requirements"');
    expect(plan).toContain('"implementation_endpoint"');
    expect(plan).toContain(`"${definition.artifact_digest}"`);
    expect(plan).toContain(
      '"LQFP144","23","left","stable_io","direct","universal-breakout","compiler-derived","none"',
    );
    expect(plan).toContain('"uart_tx:USART1_TX:direct:complete"');
    expect(plan.trimEnd().split("\r\n")).toHaveLength(2);
  });

  it("exports target-specific access routes and their implementation closure fields", () => {
    const plan = stmAccessPlanCsv(targetDefinitionResult());
    expect(plan).toContain('"claim_scope"');
    expect(plan).toContain('"protection_constraints"');
    expect(plan).toContain('"implementation_evidence"');
    expect(plan).toContain(
      '"STM32F407ZGT6","STM32F4","STM32F407","","true","23","PA9","USART1_TX","7","true"',
    );
    expect(plan.trimEnd().split("\r\n")).toHaveLength(4);
  });

  it("uses the package and definition digest in every handoff filename", () => {
    const definition = targetDefinitionResult();
    expect(stmTargetExportFilename(definition, "request")).toBe(
      "stm-lqfp144-aaaaaaaaaaaa.request.json",
    );
    expect(stmTargetExportFilename(definition, "pin-plan")).toBe(
      "stm-lqfp144-aaaaaaaaaaaa.pin-plan.csv",
    );
  });

  it("exports a compact socket contract with blank downstream implementation fields", () => {
    const solution = socketSolutionResult();
    const positions = stmSocketPositionsCsv(solution);
    const states = stmSocketControlStatesCsv(solution);
    const request = JSON.parse(stmSocketRequestJson(solution, policy));
    expect(positions).toContain('"implementation_designator"');
    expect(positions).toContain('"implementation_evidence"');
    expect(positions.trimEnd().split("\r\n")).toHaveLength(2);
    expect(states.trimEnd().split("\r\n")).toHaveLength(3);
    expect(states).toContain('"cohort-2","04","1","33.3"');
    expect(request.format).toBe("stm-socket-request/1");
    expect(request.selection.parts).toEqual([
      "STM32F407ZGT6",
      "STM32F429ZET6",
      "STM32F746ZGT6",
    ]);
    expect(stmSocketExportFilename(solution, "positions")).toBe(
      "stm-lqfp144-dddddddddddd.positions.csv",
    );
  });
});

describe("CompatibilityWorkbench (the Bench)", () => {
  function mockScope() {
    vi.spyOn(api, "getStmFamilies").mockResolvedValue(FAMILIES);
    const suggSpy = vi.spyOn(api, "getStmCompatSuggestions").mockResolvedValue(SUGGESTIONS);
    const unionSpy = vi.spyOn(api, "postStmCompatUnion").mockResolvedValue(unionResult());
    const definitionSpy = vi
      .spyOn(api, "postStmTargetDefinition")
      .mockResolvedValue(targetDefinitionResult());
    const solutionSpy = vi
      .spyOn(api, "postStmSocketSolution")
      .mockResolvedValue(socketSolutionResult());
    return { suggSpy, unionSpy, definitionSpy, solutionSpy };
  }

  async function pickScope() {
    fireEvent.click(await screen.findByText("STM32F4"));
    fireEvent.click(await screen.findByText("STM32F7"));
    fireEvent.click(await screen.findByRole("button", { name: /LQFP144/ }));
  }

  it("shows the UNION of packages with coverage badges, and filters them", async () => {
    mockScope();
    render(<CompatibilityWorkbench />, { wrapper: wrapperWith(freshClient()) });
    fireEvent.click(await screen.findByText("STM32F4"));
    fireEvent.click(await screen.findByText("STM32F7"));

    const grid = await screen.findByTestId("bench-packages");
    // LQFP100 is present despite F7 lacking it, badged 1/2
    const lqfp100 = within(grid).getByRole("button", { name: /LQFP100/ });
    expect(within(lqfp100).getByText("1/2")).toBeInTheDocument();
    // full-coverage LQFP144 carries no badge
    const lqfp144 = within(grid).getByRole("button", { name: /LQFP144/ });
    expect(within(lqfp144).queryByText("2/2")).toBeNull();

    // the text filter narrows the grid
    fireEvent.change(screen.getByLabelText("Filter Packages"), { target: { value: "144" } });
    expect(within(grid).queryByRole("button", { name: /LQFP100/ })).toBeNull();
  });

  it("auto-computes the sets and auto-unions the scope - no Build Set button anywhere", async () => {
    const { suggSpy, unionSpy } = mockScope();
    render(<CompatibilityWorkbench />, { wrapper: wrapperWith(freshClient()) });
    await pickScope();

    await waitFor(() =>
      expect(suggSpy).toHaveBeenCalledWith("LQFP144", "STM32F4,STM32F7", undefined),
    );
    // the whole-scope union fires automatically with the COVERED families
    await waitFor(() =>
      expect(unionSpy).toHaveBeenCalledWith({
        families: ["STM32F4", "STM32F7"],
        package: "LQFP144",
      }),
    );
    expect(screen.queryByRole("button", { name: "Build Set" })).toBeNull();
    // The compact selector keeps every computed set available without a chip rail.
    const stepper = await screen.findByTestId("bench-stepper");
    const selector = within(stepper).getByRole("combobox", { name: "Target Set" });
    expect(within(selector).getByRole("option", { name: /All Parts/ })).toBeInTheDocument();
    expect(within(selector).getByRole("option", { name: /Baseline/ })).toBeInTheDocument();
    expect(within(selector).getByRole("option", { name: /Divergent A/ })).toBeInTheDocument();
  });

  it("stepping to a divergent set auto-unions its refs (no rebuild)", async () => {
    const { unionSpy } = mockScope();
    render(<CompatibilityWorkbench />, { wrapper: wrapperWith(freshClient()) });
    await pickScope();
    await screen.findByTestId("bench-stepper");

    fireEvent.change(screen.getByRole("combobox", { name: "Target Set" }), {
      target: { value: "sig-div-a" },
    });
    await waitFor(() => expect(unionSpy).toHaveBeenCalledWith({ parts: ["STM32F407ZGT6"] }));
  });

  it("keeps capability differences as evidence and shows the compiled physical action", async () => {
    mockScope();
    render(<CompatibilityWorkbench />, { wrapper: wrapperWith(freshClient()) });
    await pickScope();

    const map = await screen.findByTestId("target-package-map");
    expect(
      within(map).getByRole("button", {
        name: "Position 23: Selected Socket Roles · 2 Modes · 66.7% Agreement",
      }),
    ).toBeInTheDocument();
    expect(screen.getByText("Build This")).toBeInTheDocument();
    expect(screen.getByText("Software Selected")).toBeInTheDocument();
    expect(screen.queryByTestId("switch-plan")).toBeNull();
  });

  it("dropping a chip switches to a custom set and auto-rebuilds with the remaining refs", async () => {
    const { unionSpy } = mockScope();
    render(<CompatibilityWorkbench />, { wrapper: wrapperWith(freshClient()) });
    await pickScope();
    await screen.findByTestId("compat-set-strip");
    unionSpy.mockClear();

    fireEvent.click(screen.getByRole("button", { name: "Remove STM32F407ZGT6 from the set" }));
    await waitFor(() =>
      expect(unionSpy).toHaveBeenCalledWith({ parts: ["STM32F429ZET6", "STM32F746ZGT6"] }),
    );
    expect(screen.getByRole("combobox", { name: "Target Set" })).toHaveValue("custom");
  });

  it("a chip click opens that part's full pinout table modal", async () => {
    mockScope();
    vi.spyOn(api, "getStmPinout").mockResolvedValue({
      part: "STM32F746ZGT6",
      mpn_example: "STM32F746ZGT6",
      package: "LQFP144",
      geometry: {
        body_shape: "qfp",
        pin_count: 1,
        rows: null,
        cols: null,
        pitch_mm: null,
        has_center_pad: false,
      },
      pins: [
        {
          position: "1",
          position_kind: "numeric",
          lqfp_side: "left",
          bga_row: null,
          bga_col: null,
          canonical_pin_name: "VDD",
          raw_pin_name: "VDD",
          pin_type: "Power",
          electrical_class: "power",
          category: "power",
          roles: [],
          functions: [],
          alternate_functions: [],
          five_v: null,
          supply: "VDD",
        },
      ],
    });
    render(<CompatibilityWorkbench />, { wrapper: wrapperWith(freshClient()) });
    await pickScope();
    const strip = await screen.findByTestId("compat-set-strip");

    fireEvent.click(within(strip).getByRole("button", { name: "STM32F746ZGT6" }));
    const modal = await screen.findByTestId("bench-part-modal");
    expect(await within(modal).findByTestId("pinout-table")).toBeInTheDocument();
    expect(within(modal).getByText("VDD")).toBeInTheDocument();
  });

  it("exports the selected digest-bound handoff from the compact export menu", async () => {
    mockScope();
    const createUrl = vi.fn(() => "blob:x");
    const revokeUrl = vi.fn();
    vi.stubGlobal("URL", { ...URL, createObjectURL: createUrl, revokeObjectURL: revokeUrl });
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});

    render(<CompatibilityWorkbench />, { wrapper: wrapperWith(freshClient()) });
    await pickScope();
    await screen.findByTestId("target-package-map-svg");

    fireEvent.click(screen.getByText("Export"));
    fireEvent.click(screen.getByRole("menuitem", { name: /Package Positions/ }));
    expect(createUrl).toHaveBeenCalledTimes(1);
    expect(click).toHaveBeenCalledTimes(1);
    vi.unstubAllGlobals();
  });

  it("finds an exact target, selects its compact cohort, and applies its map state", async () => {
    mockScope();
    render(<CompatibilityWorkbench />, { wrapper: wrapperWith(freshClient()) });
    await pickScope();
    const map = await screen.findByTestId("target-package-map");

    fireEvent.change(screen.getByLabelText("Find Target Profile"), {
      target: { value: "STM32F746ZGT6" },
    });
    expect(screen.queryByText("Profile 1")).toBeNull();
    const cohortLabel = screen.getByText("Profile 2");
    fireEvent.click(cohortLabel.closest("button")!);

    expect(screen.getByRole("button", { name: "Clear Active Configuration" })).toBeInTheDocument();
    expect(
      within(map).getByRole("button", {
        name: /Position 23:.*ETH TXD3 For Profile 2/,
      }),
    ).toBeInTheDocument();
  });

  it("renders the reused Build the Index state when the scope 409s", async () => {
    vi.spyOn(api, "getStmFamilies").mockResolvedValue(FAMILIES);
    vi.spyOn(api, "getStmCompatSuggestions").mockRejectedValue(
      new ApiError(409, "STM index not built"),
    );
    vi.spyOn(api, "postStmCompatUnion").mockRejectedValue(
      new ApiError(409, "STM index not built"),
    );
    render(<CompatibilityWorkbench />, { wrapper: wrapperWith(freshClient()) });
    await pickScope();
    expect(await screen.findByRole("heading", { name: "Build the Index" })).toBeInTheDocument();
  });
});
