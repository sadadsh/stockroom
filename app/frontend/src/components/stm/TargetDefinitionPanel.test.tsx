import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { TargetDefinitionDTO } from "../../api/types";
import { TargetDefinitionPanel } from "./TargetDefinitionPanel";

const DEFINITION: TargetDefinitionDTO = {
  format: "stm-target-definition/1",
  compiler_rev: 4,
  artifact_digest: "a".repeat(64),
  profile: {
    id: "fixture-policy",
    revision: 1,
    coverage_mode: "explicit-device-set",
    policy_digest: "b".repeat(64),
  },
  scope: {
    package: "LQFP2",
    families: ["STM32TEST"],
    target_count: 2,
    targets: [],
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
  readiness: {
    status: "blocked",
    blockers: ["position 2 has a critical identity collision without a safety rule"],
    warnings: [],
  },
  summary: {
    silicon_classes: { stable_io: 1, safety_collision: 1 },
    board_actions: { direct: 1, isolate: 1 },
    required_routes: 1,
    switched_routes: 0,
    safety_rules: 0,
    service_groups: 1,
    foundation_groups: 1,
  },
  requirements: [
    {
      id: "service_tx",
      label: "Service TX",
      net: "SERVICE_TX",
      required: true,
      implementation_required: true,
      category: "recovery",
      service_group: "service-uart",
      protocol: "UART",
      direction: "output",
      access_plane: "function",
      purposes: ["recovery", "data-access"],
      claim_scope: "pin-capability",
      route_kind: "direct",
      implementation_kind: "direct",
      coverage_status: "complete",
      applicable_targets: ["STM32TESTA", "STM32TESTB"],
      not_applicable_targets: [],
      missing_targets: [],
      blocked_targets: [],
      routes: [
        {
          ref: "STM32TESTA",
          position: "1",
          canonical_pin_name: "PA0",
          signal: "SERVICE_TX",
          af_index: 1,
          usable: true,
          safety_branch: null,
        },
        {
          ref: "STM32TESTB",
          position: "1",
          canonical_pin_name: "PA0",
          signal: "SERVICE_TX",
          af_index: 1,
          usable: true,
          safety_branch: null,
        },
      ],
      candidates_by_target: {
        STM32TESTA: [
          {
            ref: "STM32TESTA",
            position: "1",
            canonical_pin_name: "PA0",
            signal: "SERVICE_TX",
            af_index: 1,
          },
        ],
        STM32TESTB: [
          {
            ref: "STM32TESTB",
            position: "1",
            canonical_pin_name: "PA0",
            signal: "SERVICE_TX",
            af_index: 1,
          },
        ],
      },
      candidate_counts: { STM32TESTA: 1, STM32TESTB: 1 },
      onehot_group: null,
      evidence: ["fixture"],
    },
  ],
  service_groups: [
    {
      id: "service-uart",
      label: "Service UART",
      category: "recovery",
      protocol: "UART",
      required: false,
      claim_scope: "pin-capability",
      purposes: ["recovery", "data-access"],
      requirement_ids: ["service_tx"],
      required_requirement_ids: ["service_tx"],
      status: "complete",
      applicable_target_count: 2,
      complete_target_count: 2,
      not_applicable_targets: [],
      per_target: [
        {
          ref: "STM32TESTA",
          family: "STM32TEST",
          line: "STM32TEST",
          status: "complete",
          missing_requirements: [],
          positions: { service_tx: "1" },
        },
        {
          ref: "STM32TESTB",
          family: "STM32TEST",
          line: "STM32TEST",
          status: "complete",
          missing_requirements: [],
          positions: { service_tx: "1" },
        },
      ],
      entry_conditions: [],
      protection_constraints: [],
      side_effects: [],
      procedure_refs: [],
      destructive: false,
      evidence: ["fixture"],
    },
  ],
  functional_foundation: {
    claim_scope: "pin-obligation",
    network_values_authority: "external-target-documentation-required",
    status: "partial",
    unresolved_positions: ["2"],
    groups: [
      {
        id: "ground-return",
        label: "Ground Returns",
        obligation: "Bond every ground return to the intended domain.",
        applicability: "when-present",
        claim_scope: "pin-obligation",
        network_evidence_required: true,
        status: "partial",
        present_target_count: 1,
        resolved_target_count: 0,
        positions: ["2"],
        unresolved_positions: ["2"],
        per_target: [
          {
            ref: "STM32TESTA",
            family: "STM32TEST",
            line: "STM32TEST",
            present: true,
            resolved: false,
            pins: [
              {
                position: "2",
                canonical_pin_name: "VSS",
                electrical_class: "ground",
                identity: "ground",
                board_action: "isolate",
                resolved: false,
              },
            ],
          },
          {
            ref: "STM32TESTB",
            family: "STM32TEST",
            line: "STM32TEST",
            present: false,
            resolved: false,
            pins: [],
          },
        ],
      },
    ],
  },
  safety_rules: [],
  channel_fabric: {
    part_mpn: "",
    channels_per_device: 0,
    max_devices: 0,
    default_state: "open",
    reference_prefix: "U_ROUTE",
    required_channels: 0,
    capacity: 0,
    used_devices: 0,
    allocations: [],
  },
  positions: [
    {
      position: "1",
      position_kind: "numeric",
      lqfp_side: "left",
      bga_row: null,
      bga_col: null,
      silicon_class: "stable_io",
      board_action: "direct",
      identities: ["PA0"],
      access_tags: ["usart"],
      access_tags_union: ["usart"],
      present_on: 2,
      total_targets: 2,
      route_ids: ["service_tx"],
      hazard: "",
      per_target: [
        {
          ref: "STM32TESTA",
          family: "STM32TEST",
          canonical_pin_name: "PA0",
          electrical_class: "io",
          critical_identity: null,
          roles: ["gpio"],
          functions: ["SERVICE_TX"],
          alternate_functions: [],
          access_tags: ["usart"],
        },
        {
          ref: "STM32TESTB",
          family: "STM32TEST",
          canonical_pin_name: "PA0",
          electrical_class: "io",
          critical_identity: null,
          roles: ["gpio"],
          functions: ["SERVICE_TX"],
          alternate_functions: [],
          access_tags: ["usart"],
        },
      ],
    },
    {
      position: "2",
      position_kind: "numeric",
      lqfp_side: "left",
      bga_row: null,
      bga_col: null,
      silicon_class: "safety_collision",
      board_action: "isolate",
      identities: ["ground", "vcap"],
      access_tags: [],
      access_tags_union: [],
      present_on: 2,
      total_targets: 2,
      route_ids: [],
      hazard: "critical electrical identities differ at this physical position",
      per_target: [
        {
          ref: "STM32TESTA",
          family: "STM32TEST",
          canonical_pin_name: "VSS",
          electrical_class: "ground",
          critical_identity: "ground",
          roles: ["ground"],
          functions: [],
          alternate_functions: [],
          access_tags: [],
        },
        {
          ref: "STM32TESTB",
          family: "STM32TEST",
          canonical_pin_name: "VCAP_1",
          electrical_class: "vcap",
          critical_identity: "vcap",
          roles: ["vcap"],
          functions: [],
          alternate_functions: [],
          access_tags: [],
        },
      ],
    },
  ],
};

describe("TargetDefinitionPanel", () => {
  it("puts build readiness and the physical continuity rail ahead of similarity", () => {
    render(<TargetDefinitionPanel definition={DEFINITION} />);
    expect(screen.getByText("Blocked")).toBeInTheDocument();
    expect(screen.getByTestId("target-continuity-rail")).toBeInTheDocument();
    expect(screen.getByText(DEFINITION.readiness.blockers[0])).toBeInTheDocument();
    expect(screen.getAllByText("Service TX").length).toBeGreaterThan(0);
    expect(screen.getByTestId("target-service-matrix")).toBeInTheDocument();
    expect(screen.getByTestId("target-board-access-coverage")).toBeInTheDocument();
    expect(screen.getAllByText("Service UART").length).toBeGreaterThan(0);
    expect(
      screen.getByText(/ROM-loader, debug-unlock, or data extraction claim/),
    ).toBeInTheDocument();
  });

  it("opens the exact per-target evidence behind a rail position", () => {
    render(<TargetDefinitionPanel definition={DEFINITION} />);
    expect(screen.getAllByText("functional foundation")).toHaveLength(2);
    expect(screen.queryByText("general I/O")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Position 1: Direct" }));
    expect(screen.getByText("Position 1")).toBeInTheDocument();
    expect(screen.getAllByText("PA0")).toHaveLength(2);
    expect(screen.getByText("stable io")).toBeInTheDocument();
    expect(screen.getAllByText("usart")).toHaveLength(2);
  });
});
