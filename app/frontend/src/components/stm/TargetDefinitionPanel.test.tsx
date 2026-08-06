import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { TargetDefinitionDTO } from "../../api/types";
import { TargetDefinitionPanel } from "./TargetDefinitionPanel";

const DEFINITION: TargetDefinitionDTO = {
  format: "stm-target-definition/2",
  compiler_rev: 8,
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
    board_actions: { direct: 1, selectable: 1 },
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
    required_independent_paths: 2,
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
      selectable: 1,
      excluded_from_common_interface: 0,
    },
    strategies: [
      {
        position: "1",
        silicon_class: "stable_io",
        primitive: "universal-breakout",
        explanation:
          "The same GPIO identity can feed one common assignable board net.",
        selection: "none",
        safe_default: null,
        identities: ["PA0"],
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
      {
        position: "2",
        silicon_class: "safety_collision",
        primitive: "exclusive-identity-branches",
        explanation:
          "Conflicting fixed identities require mutually exclusive target-specific branches.",
        selection: "one-of",
        safe_default: "open",
        identities: ["ground", "vcap"],
        branches: [
          {
            id: "identity-1",
            identity_patterns: ["ground"],
            matched_identities: ["ground"],
            matched_targets: ["STM32TESTA"],
            action: "selectable",
            net: "",
            safe_default: "open",
            evidence_status: "suggested",
          },
          {
            id: "identity-2",
            identity_patterns: ["vcap"],
            matched_identities: ["vcap"],
            matched_targets: ["STM32TESTB"],
            action: "selectable",
            net: "",
            safe_default: "open",
            evidence_status: "suggested",
          },
        ],
        constraints: ["Only the valid branch may conduct."],
        validation: {
          status: "required",
          required_checks: [],
          failure_action: "keep-independent-paths-open",
        },
        evidence_status: "suggested",
        implementation_owner: "consuming-design",
      },
    ],
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
      universal_primitive: "universal-breakout",
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
      board_action: "selectable",
      universal_primitive: "exclusive-identity-branches",
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
  it("leads with explained package compatibility and exact denominators", () => {
    render(<TargetDefinitionPanel definition={DEFINITION} />);
    expect(screen.getByText("Definition Blocked")).toBeInTheDocument();
    expect(screen.getByTestId("target-package-map-svg")).toBeInTheDocument();
    expect(screen.getByRole("radiogroup", { name: "Pinout Lens" })).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: "Compatibility" })).toHaveAttribute(
      "aria-checked",
      "true",
    );
    expect(screen.getByText("1/2 Shared")).toBeInTheDocument();
    const legend = screen.getByTestId("target-smart-legend");
    // The distribution bar is a GROUP of filter buttons, not an image: an img role would make its
    // whole subtree presentational and hide the per-class buttons a keyboard user can still reach.
    const distribution = within(legend).getByRole("group", {
      name: "Package Position Distribution",
    });
    expect(distribution).toBeInTheDocument();
    expect(
      within(distribution).getByRole("button", { name: "Filter Same Across All MCUs" }),
    ).toBeInTheDocument();
    expect(
      within(legend).getByRole("button", { name: "Show Same Across All MCUs" }),
    ).toHaveTextContent("Same1 · 50%");
    expect(
      within(legend).getByRole("button", { name: "Show Electrical Conflict" }),
    ).toHaveTextContent("Conflict1 · 50%");
    expect(legend).toHaveTextContent(
      "Shows whether one physical connection can work across every selected MCU",
    );
    expect(screen.getByTestId("target-position-inspector")).toBeInTheDocument();
    expect(
      screen.getByRole("radiogroup", { name: "Position Inspector View" }),
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        "Position 2 has a critical identity collision without a safety rule",
      ),
    ).toBeInTheDocument();
    expect(screen.getByText("Proof Required")).toBeInTheDocument();
    expect(screen.getByText(/Keep Independent Paths Open/)).toBeInTheDocument();
    expect(screen.queryByTestId("target-continuity-rail")).not.toBeInTheDocument();
    expect(screen.queryByTestId("target-service-matrix")).not.toBeInTheDocument();
  });

  it("filters conflicts and explains a selected position without raw taxonomy", () => {
    render(<TargetDefinitionPanel definition={DEFINITION} />);
    const conflictFilter = screen.getByRole("button", {
      name: "Show Electrical Conflict",
    });
    fireEvent.click(conflictFilter);
    expect(conflictFilter).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByTestId("target-smart-legend")).toHaveTextContent(
      "compact passive conditioning where safe",
    );
    expect(
      screen.getByRole("button", { name: "Position 1: Same Across All MCUs" }),
    ).toHaveAttribute("opacity", "0.18");
    expect(
      screen.getByRole("button", { name: "Position 2: Electrical Conflict" }),
    ).toHaveAttribute("opacity", "1");

    fireEvent.click(
      screen.getByRole("button", { name: "Position 1: Same Across All MCUs" }),
    );
    const inspector = screen.getByTestId("target-position-inspector");
    expect(inspector).toHaveTextContent("PA0");
    expect(inspector).toHaveTextContent("2 Of 2 MCUs · 100%");
    expect(inspector).toHaveTextContent("Same Across All MCUs");
    expect(inspector).not.toHaveTextContent("stable_io");
    expect(inspector).not.toHaveTextContent("usart");
    expect(inspector).toHaveTextContent("UART");
    expect(inspector).toHaveTextContent("Service TX");

    fireEvent.click(
      within(inspector).getByRole("radio", { name: "MCUs" }),
    );
    expect(inspector).toHaveTextContent(
      "Grouped per canonical pin name and electrical role",
    );
    expect(inspector).toHaveTextContent("PA0");

    fireEvent.click(
      within(inspector).getByRole("radio", { name: "Evidence" }),
    );
    expect(inspector).toHaveTextContent("Access Routes");
    expect(inspector).toHaveTextContent("Board Evidence");
    expect(inspector).toHaveTextContent("Safe State Contract");
    expect(inspector).toHaveTextContent("Unknown Target");
    expect(inspector).toHaveTextContent("All Independent Paths Open");

    fireEvent.click(screen.getByRole("radio", { name: "Service Access" }));
    expect(screen.getByRole("radio", { name: "Service Access" })).toHaveAttribute(
      "aria-checked",
      "true",
    );
    expect(screen.getByRole("button", { name: "Position 1: UART" })).toHaveAttribute(
      "data-lens",
      "access",
    );
    const routeFilter = screen.getByRole("button", {
      name: "Show Required Service Route",
    });
    fireEvent.click(routeFilter);
    expect(routeFilter).toHaveAttribute("aria-pressed", "true");
    expect(
      screen.getByRole("button", { name: "Position 1: UART" }),
    ).toHaveAttribute("opacity", "1");
    expect(
      screen.getByRole("button", { name: "Position 2: No Declared Access" }),
    ).toHaveAttribute("opacity", "0.18");

    fireEvent.click(screen.getByRole("radio", { name: "Routing Plan" }));
    expect(
      screen.getByRole("button", { name: "Show Direct Or Fixed" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Show Fully Exclusive" }),
    ).toBeInTheDocument();
  });
});
