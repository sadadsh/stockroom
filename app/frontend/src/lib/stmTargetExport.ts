import type {
  TargetDefinitionDTO,
  TargetDefinitionPolicy,
  TargetDefinitionPosition,
} from "../api/types";

export type StmTargetExportKind = "request" | "definition" | "pin-plan" | "access-plan";

export interface StmTargetRequest {
  format: "stm-target-request/2";
  selection: {
    parts: string[];
  };
  policy: TargetDefinitionPolicy;
}

const CSV_BOM = "\uFEFF";

function unique(values: string[]): string[] {
  return [...new Set(values.filter(Boolean))].sort((a, b) =>
    a.localeCompare(b, undefined, { numeric: true }),
  );
}

function csvCell(value: string | number | boolean | null | undefined): string {
  return `"${String(value ?? "").replaceAll('"', '""')}"`;
}

function csv(rows: Array<Array<string | number | boolean | null | undefined>>): string {
  return CSV_BOM + rows.map((row) => row.map(csvCell).join(",")).join("\r\n") + "\r\n";
}

function join(values: string[]): string {
  return unique(values).join("; ");
}

function packageLocation(position: TargetDefinitionPosition): string {
  if (position.lqfp_side) return position.lqfp_side;
  if (position.bga_row && position.bga_col != null) {
    return `${position.bga_row}${position.bga_col}`;
  }
  return "";
}

function positionRequirements(
  definition: TargetDefinitionDTO,
  position: TargetDefinitionPosition,
): string[] {
  // One pass per position: this is called for every row of the pin plan, so the requirement list
  // is walked once rather than once to select and again to format.
  const out: string[] = [];
  for (const requirement of definition.requirements) {
    if (!requirement.routes.some((route) => route.position === position.position)) continue;
    out.push(
      `${requirement.id}:${requirement.net}:${requirement.implementation_kind}:${requirement.coverage_status}`,
    );
  }
  return out;
}

function positionFoundation(
  definition: TargetDefinitionDTO,
  position: TargetDefinitionPosition,
): { obligations: string[]; unresolved: string[] } {
  // Both lists come out of ONE walk of the foundation groups (the obligations this position
  // carries, and the subset of those still unresolved for it), in group order as before.
  const obligations: string[] = [];
  const unresolved: string[] = [];
  for (const group of definition.functional_foundation.groups) {
    if (!group.positions.includes(position.position)) continue;
    obligations.push(`${group.id}:${group.status}`);
    if (group.unresolved_positions.includes(position.position)) unresolved.push(group.id);
  }
  return { obligations, unresolved };
}

function positionSafety(
  definition: TargetDefinitionDTO,
  position: TargetDefinitionPosition,
): { defaultState: string; branches: string[] } {
  const rule = definition.safety_rules.find(
    (candidate) => candidate.position === position.position,
  );
  if (!rule) return { defaultState: "", branches: [] };
  return {
    defaultState: rule.safe_default,
    branches: rule.branches.map((branch) => {
      const net = branch.net ? `:${branch.net}` : "";
      return `${branch.id}:${branch.action}${net}`;
    }),
  };
}

function positionRoutingPaths(
  definition: TargetDefinitionDTO,
  position: TargetDefinitionPosition,
): string[] {
  // One pass per position, as with the requirements above: the path list is walked once.
  const out: string[] = [];
  for (const path of definition.routing_requirements.paths) {
    if (path.position !== position.position) continue;
    const owner = path.branch_id ?? path.requirement_id ?? path.kind;
    out.push(`${path.path_id}:${owner}:${path.requested_net}:default-${path.safe_default}`);
  }
  return out;
}

/**
 * The scope targets that carry no entry for this position, in scope order.
 *
 * One pass over the scope's targets against a membership set built once from the position's own
 * per-target list, rather than re-scanning that list for every target of every row.
 */
function missingTargetRefs(
  definition: TargetDefinitionDTO,
  position: TargetDefinitionPosition,
): string[] {
  const present = new Set(position.per_target.map((candidate) => candidate.ref));
  const missing: string[] = [];
  for (const target of definition.scope.targets) {
    if (!present.has(target.ref)) missing.push(target.ref);
  }
  return missing;
}

function positionUniversalization(
  definition: TargetDefinitionDTO,
  position: TargetDefinitionPosition,
) {
  return definition.universalization.strategies.find(
    (strategy) => strategy.position === position.position,
  );
}

/**
 * The exact non-interactive compiler input for the definition currently on screen.
 *
 * The request deliberately pins the resolved device refs instead of re-expressing the wider
 * family/package scope. Re-running it therefore cannot silently gain newly indexed devices.
 */
export function makeStmTargetRequest(
  definition: TargetDefinitionDTO,
  policy: TargetDefinitionPolicy,
): StmTargetRequest {
  return {
    format: "stm-target-request/2",
    selection: {
      parts: definition.scope.targets.map((target) => target.ref),
    },
    policy,
  };
}

/**
 * One row per physical package position.
 *
 * The compiler-owned columns are populated and digest-bound. The implementation columns are
 * intentionally empty: a consuming design must account for the real symbol pin, pad, net,
 * connector/test point, evidence, and verification state without Stockroom inventing them.
 */
export function stmPinPlanCsv(definition: TargetDefinitionDTO): string {
  const header = [
    "artifact_digest",
    "policy_digest",
    "compiler_rev",
    "silicon_source_sha256",
    "classifier_rev",
    "af_schema_rev",
    "geometry_rev",
    "readiness",
    "package",
    "position",
    "package_location",
    "silicon_class",
    "board_action",
    "universal_primitive",
    "strategy_evidence_status",
    "selection_rule",
    "strategy_safe_default",
    "strategy_branches",
    "active_routing_paths",
    "passive_conditioned_paths",
    "fallback_topology",
    "strategy_constraints",
    "validation_status",
    "validation_checks",
    "validation_failure_action",
    "global_safe_state_contract",
    "present_on",
    "total_targets",
    "missing_targets",
    "identities",
    "target_pin_map",
    "target_mpn_map",
    "electrical_class_map",
    "roles",
    "signals",
    "access_tags",
    "route_ids",
    "route_commitments",
    "foundation_obligations",
    "foundation_unresolved",
    "safety_default",
    "safety_branches",
    "routing_path_requirements",
    "hazard",
    "implementation_designator",
    "implementation_pin_or_pad",
    "implementation_net",
    "implementation_endpoint",
    "implementation_evidence",
    "implementation_status",
    "implementation_notes",
  ];

  const rows = definition.positions.map((position) => {
    const foundation = positionFoundation(definition, position);
    const safety = positionSafety(definition, position);
    const strategy = positionUniversalization(definition, position);
    return [
      definition.artifact_digest,
      definition.profile.policy_digest,
      definition.compiler_rev,
      definition.provenance.source_sha256,
      definition.provenance.classifier_rev,
      definition.provenance.af_schema_rev,
      definition.provenance.geometry_rev,
      definition.readiness.status,
      definition.scope.package,
      position.position,
      packageLocation(position),
      position.silicon_class,
      position.board_action,
      strategy?.primitive ?? "",
      strategy?.evidence_status ?? "",
      strategy?.selection ?? "",
      strategy?.safe_default ?? "",
      join(
        strategy?.branches.map(
          (branch) =>
            `${branch.id}:${join(branch.matched_identities)}:${
              branch.connection_mode ?? branch.action
            }:${branch.uses_independent_path ? "active-path" : "no-active-path"}:${
              branch.net || "unassigned"
            }`,
        ) ?? [],
      ),
      strategy?.active_path_count ?? "",
      strategy?.passive_path_count ?? "",
      strategy?.fallback
        ? `${strategy.fallback.primitive}:${strategy.fallback.independent_paths}:${strategy.fallback.reason}`
        : "",
      join(strategy?.constraints ?? []),
      strategy?.validation.status ?? "",
      join(strategy?.validation.required_checks ?? []),
      strategy?.validation.failure_action ?? "",
      join(
        Object.entries(definition.universalization.state_contract).map(
          ([state, behavior]) => `${state}:${behavior}`,
        ),
      ),
      position.present_on,
      position.total_targets,
      join(missingTargetRefs(definition, position)),
      join(position.identities),
      join(
        position.per_target.map(
          (target) => `${target.ref}=${target.canonical_pin_name}`,
        ),
      ),
      join(
        definition.scope.targets.map(
          (target) =>
            `${target.ref}=${
              target.verified_mpns.length > 0
                ? target.verified_mpns.join("|")
                : "unverified"
            }`,
        ),
      ),
      join(
        position.per_target.map(
          (target) => `${target.ref}=${target.electrical_class}`,
        ),
      ),
      join(position.per_target.flatMap((target) => target.roles)),
      join(
        position.per_target.flatMap((target) => [
          ...target.functions,
          ...target.alternate_functions.map((alternate) => alternate.signal),
        ]),
      ),
      join(position.access_tags_union),
      join(position.route_ids),
      join(positionRequirements(definition, position)),
      join(foundation.obligations),
      join(foundation.unresolved),
      safety.defaultState,
      join(safety.branches),
      join(positionRoutingPaths(definition, position)),
      position.hazard,
      "",
      "",
      "",
      "",
      "",
      "",
      "",
    ];
  });

  return csv([header, ...rows]);
}

/**
 * One row per requirement and applicable target.
 *
 * This is the companion to the physical pin plan: it keeps selected routes, alternate candidates,
 * claim authority, protection limits, and procedure evidence together so capability cannot be
 * mistaken for a validated debug, recovery, or extraction path.
 */
export function stmAccessPlanCsv(definition: TargetDefinitionDTO): string {
  const header = [
    "artifact_digest",
    "policy_digest",
    "compiler_rev",
    "silicon_source_sha256",
    "classifier_rev",
    "af_schema_rev",
    "geometry_rev",
    "readiness",
    "package",
    "requirement_id",
    "requirement",
    "category",
    "service_group",
    "protocol",
    "direction",
    "access_plane",
    "purposes",
    "claim_scope",
    "required",
    "implementation_required",
    "requested_net",
    "route_kind",
    "implementation_kind",
    "coverage_status",
    "target_ref",
    "target_family",
    "target_line",
    "verified_mpns",
    "target_applicable",
    "selected_position",
    "selected_pin_name",
    "selected_signal",
    "af_index",
    "route_usable",
    "safety_branch",
    "candidate_positions",
    "candidate_count",
    "target_missing",
    "target_blocked",
    "requirement_evidence",
    "service_status",
    "entry_conditions",
    "protection_constraints",
    "side_effects",
    "procedure_refs",
    "destructive",
    "implementation_designator",
    "implementation_pin_or_pad",
    "implementation_net",
    "implementation_endpoint",
    "implementation_evidence",
    "implementation_status",
    "implementation_notes",
  ];

  // The service group each requirement names, indexed once instead of scanned per requirement.
  // FIRST entry wins for a duplicated id, which is what `find` returned before.
  const serviceById = new Map<string, (typeof definition.service_groups)[number]>();
  for (const group of definition.service_groups) {
    if (!serviceById.has(group.id)) serviceById.set(group.id, group);
  }

  const rows: Array<Array<string | number | boolean | null | undefined>> = [];
  for (const requirement of definition.requirements) {
    const service = serviceById.get(requirement.service_group);
    for (const target of definition.scope.targets) {
      const targetRef = target.ref;
      const route = requirement.routes.find((candidate) => candidate.ref === targetRef);
      const candidates = requirement.candidates_by_target[targetRef] ?? [];
      rows.push([
        definition.artifact_digest,
        definition.profile.policy_digest,
        definition.compiler_rev,
        definition.provenance.source_sha256,
        definition.provenance.classifier_rev,
        definition.provenance.af_schema_rev,
        definition.provenance.geometry_rev,
        definition.readiness.status,
        definition.scope.package,
        requirement.id,
        requirement.label,
        requirement.category,
        requirement.service_group,
        requirement.protocol,
        requirement.direction,
        requirement.access_plane,
        join(requirement.purposes),
        requirement.claim_scope,
        requirement.required,
        requirement.implementation_required,
        requirement.net,
        requirement.route_kind,
        requirement.implementation_kind,
        requirement.coverage_status,
        targetRef,
        target.family,
        target.line,
        join(target.verified_mpns),
        requirement.applicable_targets.includes(targetRef),
        route?.position ?? "",
        route?.canonical_pin_name ?? "",
        route?.signal ?? "",
        route?.af_index ?? "",
        route?.usable ?? false,
        route?.safety_branch ?? "",
        join(candidates.map((candidate) => `${candidate.position}:${candidate.signal}`)),
        requirement.candidate_counts[targetRef] ?? 0,
        requirement.missing_targets.includes(targetRef),
        requirement.blocked_targets.includes(targetRef),
        join(requirement.evidence),
        service?.status ?? "",
        join(service?.entry_conditions ?? []),
        join(service?.protection_constraints ?? []),
        join(service?.side_effects ?? []),
        join(service?.procedure_refs ?? []),
        service?.destructive ?? false,
        "",
        "",
        "",
        "",
        "",
        "",
        "",
      ]);
    }
  }

  return csv([header, ...rows]);
}

export function stmTargetExportFilename(
  definition: TargetDefinitionDTO,
  kind: StmTargetExportKind,
): string {
  const packageName = definition.scope.package
    .toLowerCase()
    .replace(/[^a-z0-9._-]+/g, "-");
  const stem = `stm-${packageName}-${definition.artifact_digest.slice(0, 12)}`;
  if (kind === "request") return `${stem}.request.json`;
  if (kind === "definition") return `${stem}.target-definition.json`;
  if (kind === "pin-plan") return `${stem}.pin-plan.csv`;
  return `${stem}.access-plan.csv`;
}

export function downloadTextFile(filename: string, content: string, type: string): void {
  const blob = new Blob([content], { type });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
}
