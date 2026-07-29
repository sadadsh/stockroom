import type {
  SocketSolutionDTO,
  TargetDefinitionPolicy,
} from "../api/types";

export type StmSocketExportKind =
  | "request"
  | "solution"
  | "support-cells"
  | "positions"
  | "control-states"
  | "proofs";

const CSV_BOM = "\uFEFF";

function json(value: unknown): string {
  return JSON.stringify(value, null, 2) + "\n";
}

function csvCell(value: unknown): string {
  return `"${String(value ?? "").replaceAll('"', '""')}"`;
}

function csv(rows: unknown[][]): string {
  return (
    CSV_BOM +
    rows.map((row) => row.map(csvCell).join(",")).join("\r\n") +
    "\r\n"
  );
}

function join(values: string[]): string {
  return [...new Set(values.filter(Boolean))].sort().join("; ");
}

export function stmSocketRequestJson(
  solution: SocketSolutionDTO,
  policy: TargetDefinitionPolicy,
): string {
  return json({
    format: "stm-socket-request/1",
    selection: {
      parts: solution.scope.target_index.map((target) => target.ref),
    },
    policy,
  });
}

export function stmSocketSolutionJson(solution: SocketSolutionDTO): string {
  return json(solution);
}

export function stmSocketSupportCellsCsv(solution: SocketSolutionDTO): string {
  const rows: unknown[][] = [
    [
      "artifact_digest",
      "cell_id",
      "signature",
      "type",
      "label",
      "positions",
      "position_count",
      "mode_count",
      "controlled",
      "safe_default",
      "hazard_level",
      "hazard_category",
      "cell_architecture",
      "selection_authority",
      "electrical_planes",
      "mandatory_features",
      "power_sequence",
      "failure_response",
      "branch_pattern",
      "default_open_required",
      "hardware_reset_required",
      "readback_required",
      "break_before_make_required",
      "bidirectional_required",
      "passive_conditioning_required",
      "shared_supply_required",
      "proof_required",
    ],
  ];
  for (const cell of solution.support_cells) {
    rows.push([
      solution.artifact_digest,
      cell.id,
      cell.signature,
      cell.type,
      cell.label,
      join(cell.positions),
      cell.position_count,
      cell.mode_count,
      cell.controlled,
      cell.safe_default,
      cell.hazard_contract.level,
      cell.hazard_contract.category,
      cell.cell_contract.architecture,
      cell.cell_contract.selection_authority,
      join(cell.cell_contract.planes.map((plane) => plane.id)),
      join(cell.cell_contract.mandatory_features),
      join(cell.cell_contract.power_sequence),
      cell.cell_contract.failure_response,
      join(
        cell.branch_pattern.map(
          (branch) =>
            `${branch.mode_id}:${branch.endpoint}:${
              branch.controlled ? "controlled" : "fixed"
            }`,
        ),
      ),
      cell.implementation_capabilities.default_open,
      cell.implementation_capabilities.hardware_reset,
      cell.implementation_capabilities.readback,
      cell.implementation_capabilities.break_before_make,
      cell.implementation_capabilities.bidirectional,
      cell.implementation_capabilities.passive_conditioning ?? false,
      cell.implementation_capabilities.shared_supply ?? false,
      cell.implementation_capabilities.proof_required ?? false,
    ]);
  }
  return csv(rows);
}

export function stmSocketPositionsCsv(solution: SocketSolutionDTO): string {
  const rows: unknown[][] = [
    [
      "artifact_digest",
      "package",
      "position",
      "package_side",
      "support_cell_id",
      "support_cell_type",
      "solution",
      "solution_reason",
      "network_requirements",
      "validation_checks",
      "hazard_level",
      "hazard_category",
      "hazard_reason",
      "cell_architecture",
      "selection_authority",
      "electrical_planes",
      "mandatory_features",
      "power_sequence",
      "failure_response",
      "controlled",
      "safe_default",
      "agreement_count",
      "target_count",
      "agreement_percentage",
      "mode_count",
      "modes",
      "branches",
      "universal_lane",
      "observation_node",
      "hazard",
      "implementation_designator",
      "implementation_pin_or_pad",
      "implementation_net",
      "implementation_status",
      "implementation_evidence",
      "implementation_notes",
    ],
  ];
  for (const position of solution.positions) {
    rows.push([
      solution.artifact_digest,
      solution.scope.package,
      position.position,
      position.lqfp_side ?? "",
      position.support_cell_id,
      position.cell_type,
      position.cell_label,
      position.solution_reason,
      join(position.network_requirements),
      join(position.validation_checks),
      position.hazard_contract.level,
      position.hazard_contract.category,
      position.hazard_contract.reason,
      position.cell_contract.architecture,
      position.cell_contract.selection_authority,
      join(position.cell_contract.planes.map((plane) => plane.id)),
      join(position.cell_contract.mandatory_features),
      join(position.cell_contract.power_sequence),
      position.cell_contract.failure_response,
      position.controlled,
      position.safe_default,
      position.agreement_count,
      solution.scope.target_count,
      position.agreement_percentage,
      position.mode_count,
      join(
        position.modes.map(
          (mode) =>
            `${mode.id}:${mode.target_count}:${mode.target_mask}:${mode.endpoint}`,
        ),
      ),
      join(
        position.branches.map(
          (branch) =>
            `${branch.id}:${branch.plane}:${branch.endpoint}:${branch.default_state}`,
        ),
      ),
      position.universal_lane,
      position.observation_node,
      position.hazard,
      "",
      "",
      "",
      "",
      "",
      "",
    ]);
  }
  return csv(rows);
}

export function stmSocketControlStatesCsv(solution: SocketSolutionDTO): string {
  const rows: unknown[][] = [
    [
      "artifact_digest",
      "cohort_id",
      "target_mask",
      "target_count",
      "percentage",
      "families",
      "target_examples",
      "position",
      "enabled_branch",
      "unknown_state",
      "target_change",
    ],
  ];
  for (const cohort of solution.target_cohorts) {
    const states = Object.entries(cohort.configuration);
    if (!states.length) {
      rows.push([
        solution.artifact_digest,
        cohort.id,
        cohort.target_mask,
        cohort.target_count,
        cohort.percentage,
        join(cohort.families),
        join(cohort.target_examples),
        "",
        "",
        solution.safe_state_contract.unknown_target,
        solution.safe_state_contract.target_change,
      ]);
      continue;
    }
    for (const [position, enabledBranch] of states) {
      rows.push([
        solution.artifact_digest,
        cohort.id,
        cohort.target_mask,
        cohort.target_count,
        cohort.percentage,
        join(cohort.families),
        join(cohort.target_examples),
        position,
        enabledBranch,
        solution.safe_state_contract.unknown_target,
        solution.safe_state_contract.target_change,
      ]);
    }
  }
  return csv(rows);
}

export function stmSocketProofsCsv(solution: SocketSolutionDTO): string {
  const rows: unknown[][] = [
    [
      "artifact_digest",
      "position",
      "status",
      "required_checks",
      "failure_action",
      "implementation_evidence",
      "verification_status",
      "notes",
    ],
  ];
  for (const proof of solution.proofs) {
    rows.push([
      solution.artifact_digest,
      proof.position,
      proof.status,
      join(proof.checks),
      proof.failure_action,
      "",
      "",
      "",
    ]);
  }
  return csv(rows);
}

export function stmSocketExport(
  solution: SocketSolutionDTO,
  policy: TargetDefinitionPolicy,
  kind: StmSocketExportKind,
): { content: string; type: string } {
  if (kind === "request") {
    return {
      content: stmSocketRequestJson(solution, policy),
      type: "application/json",
    };
  }
  if (kind === "solution") {
    return {
      content: stmSocketSolutionJson(solution),
      type: "application/json",
    };
  }
  if (kind === "support-cells") {
    return {
      content: stmSocketSupportCellsCsv(solution),
      type: "text/csv;charset=utf-8",
    };
  }
  if (kind === "positions") {
    return {
      content: stmSocketPositionsCsv(solution),
      type: "text/csv;charset=utf-8",
    };
  }
  if (kind === "control-states") {
    return {
      content: stmSocketControlStatesCsv(solution),
      type: "text/csv;charset=utf-8",
    };
  }
  return {
    content: stmSocketProofsCsv(solution),
    type: "text/csv;charset=utf-8",
  };
}

export function stmSocketExportFilename(
  solution: SocketSolutionDTO,
  kind: StmSocketExportKind,
): string {
  const packageName = solution.scope.package
    .toLowerCase()
    .replace(/[^a-z0-9._-]+/g, "-");
  const stem = `stm-${packageName}-${solution.artifact_digest.slice(0, 12)}`;
  if (kind === "request") return `${stem}.socket-request.json`;
  if (kind === "solution") return `${stem}.socket-solution.json`;
  return `${stem}.${kind}.csv`;
}
