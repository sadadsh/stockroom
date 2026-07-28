import { useEffect, useMemo, useState } from "react";
import type {
  TargetBoardAction,
  TargetDefinitionDTO,
  TargetDefinitionPosition,
} from "../../api/types";
import { Badge, Eyebrow, Panel } from "../primitives";

const ACTION_LABEL: Record<TargetBoardAction, string> = {
  hardwire: "Hardwire",
  breakout: "Breakout",
  direct: "Direct",
  switched: "Routed",
  selectable: "Selectable",
  isolate: "Isolate",
  unsupported: "Unsupported",
};

const ACTION_ABBR: Record<TargetBoardAction, string> = {
  hardwire: "HW",
  breakout: "BO",
  direct: "DR",
  switched: "RT",
  selectable: "SL",
  isolate: "ISO",
  unsupported: "NA",
};

const ACTION_COLOR: Record<TargetBoardAction, string> = {
  hardwire: "bg-stm-ground",
  breakout: "bg-stm-gpio",
  direct: "bg-stm-classify-shared",
  switched: "bg-stm-boot",
  selectable: "bg-stm-classify-divergent",
  isolate: "bg-err",
  unsupported: "bg-stm-classify-partial",
};

function selectedDefault(definition: TargetDefinitionDTO): string | null {
  return (
    definition.positions.find((position) =>
      ["isolate", "unsupported", "selectable"].includes(position.board_action),
    )?.position ??
    definition.positions[0]?.position ??
    null
  );
}

function accessLabel(
  target: TargetDefinitionPosition["per_target"][number],
): string {
  if (target.access_tags.length) return target.access_tags.join(", ");
  if (target.critical_identity) return "functional foundation";
  return target.electrical_class === "io" ? "general I/O" : "no service role";
}

export function TargetDefinitionPanel({ definition }: { definition: TargetDefinitionDTO }) {
  const [selectedPosition, setSelectedPosition] = useState<string | null>(() =>
    selectedDefault(definition),
  );

  useEffect(() => {
    setSelectedPosition(selectedDefault(definition));
  }, [definition.artifact_digest]);

  const selected = useMemo(
    () => definition.positions.find((position) => position.position === selectedPosition) ?? null,
    [definition.positions, selectedPosition],
  );
  const selectedSafetyRule = useMemo(
    () => definition.safety_rules.find((rule) => rule.position === selectedPosition) ?? null,
    [definition.safety_rules, selectedPosition],
  );
  const ready = definition.readiness.status === "ready";

  return (
    <div className="flex flex-col gap-3" data-testid="target-definition">
      <Panel
        className={ready ? "border-ok/40" : "border-err/40"}
        title={
          <span className="flex items-center gap-2">
            Target Definition
            <Badge tone={ready ? "ok" : "err"} size="sm">
              {ready ? "Build Ready" : "Blocked"}
            </Badge>
          </span>
        }
        actions={
          <span className="font-mono text-2xs text-t3">
            {definition.artifact_digest.slice(0, 12)}
          </span>
        }
      >
        <div className="grid gap-4 px-4 pb-4 lg:grid-cols-[minmax(0,1fr)_minmax(280px,0.36fr)]">
          <div className="min-w-0">
            <p className="text-sm text-t2">
              {definition.scope.target_count} device descriptions on{" "}
              <span className="font-mono text-t1">{definition.scope.package}</span>, compiled
              with <span className="font-mono text-t1">{definition.profile.id}</span>.
            </p>
            <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1 font-mono text-2xs text-t3">
              <span>{definition.provenance.silicon_source}</span>
              <span>source {definition.provenance.source_sha256.slice(0, 12)}</span>
              <span>classifier r{definition.provenance.classifier_rev}</span>
              <span>AF r{definition.provenance.af_schema_rev}</span>
              <span>compiler r{definition.compiler_rev}</span>
            </div>
          </div>

          <div className="rounded-control bg-field p-3">
            <Eyebrow>{ready ? "Warnings" : "Blocking Evidence"}</Eyebrow>
            <ul className="mt-2 max-h-28 space-y-1 overflow-y-auto text-xs text-t2">
              {(ready ? definition.readiness.warnings : definition.readiness.blockers).length ? (
                (ready ? definition.readiness.warnings : definition.readiness.blockers).map(
                  (item) => <li key={item}>{item}</li>,
                )
              ) : (
                <li>No unresolved definition checks.</li>
              )}
            </ul>
          </div>
        </div>
      </Panel>

      <ServiceMatrix definition={definition} />
      <BoardAccessCoverage definition={definition} />

      <Panel title="Continuity Rail" bodyClassName="p-0">
        <div className="px-4 pb-4">
          <p className="mb-3 text-xs text-t3">
            One tile per physical package position. Color shows the compiled board action, not
            optional peripheral similarity.
          </p>
          <div
            className="grid auto-cols-[42px] grid-flow-col gap-1 overflow-x-auto pb-2"
            data-testid="target-continuity-rail"
          >
            {definition.positions.map((position) => (
              <button
                key={position.position}
                type="button"
                aria-pressed={selectedPosition === position.position}
                aria-label={`Position ${position.position}: ${ACTION_LABEL[position.board_action]}`}
                onClick={() => setSelectedPosition(position.position)}
                className={
                  "group flex h-12 flex-col overflow-hidden rounded-control border text-left " +
                  (selectedPosition === position.position
                    ? "border-acc"
                    : "border-line2 hover:border-t3")
                }
              >
                <span className={`h-1.5 w-full ${ACTION_COLOR[position.board_action]}`} />
                <span className="px-1.5 pt-1 font-mono text-xs text-t1">
                  {position.position}
                </span>
                <span className="px-1.5 font-mono text-2xs text-t3">
                  {ACTION_ABBR[position.board_action]}
                </span>
              </button>
            ))}
          </div>

          <div className="mt-2 flex flex-wrap gap-3">
            {(Object.keys(ACTION_LABEL) as TargetBoardAction[]).map((action) => (
              <span key={action} className="flex items-center gap-1.5 text-2xs text-t3">
                <span className={`h-1.5 w-4 rounded-full ${ACTION_COLOR[action]}`} />
                {ACTION_LABEL[action]}
              </span>
            ))}
          </div>

          {selected ? (
            <PositionInspector position={selected} safetyRule={selectedSafetyRule} />
          ) : null}
        </div>
      </Panel>

      <div className="grid gap-3 xl:grid-cols-2">
        <RequirementLedger definition={definition} />
        <ChannelLedger definition={definition} />
      </div>
    </div>
  );
}

function BoardAccessCoverage({ definition }: { definition: TargetDefinitionDTO }) {
  const foundation = definition.functional_foundation;
  const fixed = definition.positions.filter(
    (position) => position.silicon_class === "fixed_critical",
  );
  const collisions = definition.positions.filter(
    (position) => position.silicon_class === "safety_collision",
  );
  const resolvedPositions = new Set(
    definition.safety_rules.map((rule) => String(rule.position)),
  );
  const resolved = collisions.filter((position) => resolvedPositions.has(position.position));
  const breakout = definition.positions.filter(
    (position) => position.board_action === "breakout",
  );
  const inaccessible = definition.positions.filter((position) =>
    ["isolate", "unsupported"].includes(position.board_action),
  );
  const metrics = [
    { label: "Fixed electrical", value: fixed.length, detail: "power, ground, reset, reference" },
    {
      label: "Collision rules",
      value: `${resolved.length}/${collisions.length}`,
      detail: "target-safe physical positions",
    },
    { label: "Default breakout", value: breakout.length, detail: "raw package positions" },
    { label: "Inaccessible", value: inaccessible.length, detail: "isolated or unsupported" },
  ];

  return (
    <Panel
      title="Functional Foundation"
      actions={
        <Badge tone={foundation.status === "complete" ? "ok" : "err"} size="sm">
          {foundation.status}
        </Badge>
      }
    >
      <div className="px-4 pb-4" data-testid="target-board-access-coverage">
        <p className="mb-3 text-xs text-t3">
          Every run-critical package obligation: digital and analog power, returns, VBAT, VREF,
          regulator pins, reset, boot configuration, clock choices, and reserved pins. CubeMX
          locates the pins; exact bias, decoupling, and sequencing still require target
          documentation.
        </p>
        <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-4">
          {metrics.map((metric) => (
            <div key={metric.label} className="rounded-control bg-field p-3">
              <span className="font-mono text-lg font-semibold text-t1">{metric.value}</span>
              <span className="mt-0.5 block text-xs font-medium text-t2">{metric.label}</span>
              <span className="mt-1 block text-2xs text-t3">{metric.detail}</span>
            </div>
          ))}
        </div>
        {fixed.length ? (
          <div className="mt-3 flex flex-wrap gap-1.5">
            {fixed.map((position) => (
              <span
                key={position.position}
                className="rounded-control border border-line2 bg-field px-2 py-1 font-mono text-2xs text-t2"
              >
                {position.position} · {position.identities.join("/")} ·{" "}
                {position.board_action}
              </span>
            ))}
          </div>
        ) : null}

        <div className="mt-3 overflow-x-auto">
          <table className="w-full text-left text-xs">
            <thead className="text-2xs uppercase tracking-wide text-t3">
              <tr>
                <th className="pb-2 pr-3 font-medium">Obligation</th>
                <th className="pb-2 pr-3 font-medium">Positions</th>
                <th className="pb-2 pr-3 font-medium">Targets safe</th>
                <th className="pb-2 font-medium">Result</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {foundation.groups.map((group) => (
                <tr key={group.id}>
                  <td className="py-2 pr-3">
                    <span className="block text-t1">{group.label}</span>
                    <span className="block max-w-xl text-2xs text-t3">{group.obligation}</span>
                  </td>
                  <td className="py-2 pr-3 font-mono text-t2">
                    {group.positions.join(", ") || "not exposed"}
                  </td>
                  <td className="py-2 pr-3 font-mono text-t3">
                    {group.resolved_target_count}/{group.present_target_count}
                  </td>
                  <td className="py-2">
                    <Badge
                      size="sm"
                      tone={
                        group.status === "complete"
                          ? "ok"
                          : group.status === "partial"
                            ? "err"
                            : "neutral"
                      }
                    >
                      {group.status}
                    </Badge>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {foundation.unresolved_positions.length ? (
          <details className="mt-3 border-t border-line pt-3">
            <summary className="cursor-pointer text-xs text-err">
              Functional obligations unresolved at position
              {foundation.unresolved_positions.length === 1 ? " " : "s "}
              {foundation.unresolved_positions.join(", ")}
            </summary>
            <div className="mt-2 max-h-52 overflow-auto font-mono text-2xs text-t3">
              {foundation.groups.flatMap((group) =>
                group.per_target
                  .filter((target) => target.present && !target.resolved)
                  .map((target) => (
                    <p key={`${group.id}:${target.ref}`}>
                      {group.id} · {target.ref}:{" "}
                      {target.pins
                        .filter((pin) => !pin.resolved)
                        .map(
                          (pin) =>
                            `${pin.position}/${pin.canonical_pin_name}/${pin.board_action}`,
                        )
                        .join(", ")}
                    </p>
                  )),
              )}
            </div>
          </details>
        ) : null}
      </div>
    </Panel>
  );
}

function ServiceMatrix({ definition }: { definition: TargetDefinitionDTO }) {
  const groups = definition.service_groups;
  const [selectedId, setSelectedId] = useState<string | null>(
    () =>
      groups.find((group) => group.required && group.status !== "complete")?.id ??
      groups[0]?.id ??
      null,
  );

  useEffect(() => {
    setSelectedId(
      groups.find((group) => group.required && group.status !== "complete")?.id ??
        groups[0]?.id ??
        null,
    );
  }, [definition.artifact_digest, groups]);

  if (groups.length === 0) {
    return (
      <Panel title="Access Services">
        <p className="px-4 pb-4 text-xs text-t3">
          This policy declares no grouped debug, recovery, trace, or communication services.
        </p>
      </Panel>
    );
  }

  const selected = groups.find((group) => group.id === selectedId) ?? groups[0];
  const requirements = selected.requirement_ids
    .map((id) => definition.requirements.find((requirement) => requirement.id === id))
    .filter(
      (
        requirement,
      ): requirement is TargetDefinitionDTO["requirements"][number] => !!requirement,
    );
  const incomplete = selected.per_target.filter((target) => target.status === "incomplete");
  const pinCapabilityOnly = selected.claim_scope === "pin-capability";

  return (
    <Panel
      title="Access Services"
      actions={
        <span className="font-mono text-2xs text-t3">
          {groups.filter((group) => group.status === "complete").length}/{groups.length} complete
        </span>
      }
      bodyClassName="p-0"
    >
      <div className="px-4 pb-4" data-testid="target-service-matrix">
        <p className="mb-3 text-xs text-t3">
          Grouped routes for debug, identification, boot control, trace, clock, recovery, and data
          access. Coverage is evaluated per selected target.
        </p>
        <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-4">
          {groups.map((group) => (
            <button
              key={group.id}
              type="button"
              aria-pressed={selected.id === group.id}
              onClick={() => setSelectedId(group.id)}
              className={
                "rounded-control border p-2.5 text-left " +
                (selected.id === group.id
                  ? "border-acc bg-acc-soft"
                  : "border-line2 bg-field hover:border-t3")
              }
            >
              <span className="flex items-start justify-between gap-2">
                <span className="text-xs font-semibold text-t1">{group.label}</span>
                <Badge
                  size="sm"
                  tone={
                    group.status === "complete"
                      ? "ok"
                      : group.required
                        ? "err"
                        : "warn"
                  }
                >
                  {group.status}
                </Badge>
              </span>
              <span className="mt-1 block font-mono text-2xs text-t3">
                {group.protocol || group.category} · {group.complete_target_count}/
                {group.applicable_target_count}
              </span>
            </button>
          ))}
        </div>

        <div className="mt-3 rounded-control bg-field p-3">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <Eyebrow>{selected.category}</Eyebrow>
              <h4 className="mt-1 text-sm font-semibold text-t1">{selected.label}</h4>
              <p className="mt-1 text-xs text-t3">
                {selected.purposes.join(" · ") || "No purposes declared"}
              </p>
            </div>
            <span className="font-mono text-2xs text-t3">
              authority: {selected.claim_scope.replaceAll("-", " ")}
            </span>
          </div>

          {pinCapabilityOnly &&
          selected.purposes.some((purpose) =>
            ["recovery", "data-access"].includes(purpose),
          ) ? (
            <p className="mt-3 rounded-control border border-warn/30 bg-warn/10 px-2.5 py-2 text-xs text-t2">
              These pins prove interface capability only. A ROM-loader, debug-unlock, or data
              extraction claim still needs an external, target-specific policy and citation.
            </p>
          ) : null}
          {selected.destructive ? (
            <p className="mt-3 rounded-control border border-err/30 bg-err/10 px-2.5 py-2 text-xs text-t2">
              This declared access path can be destructive. Its side effects and procedure
              evidence must be reviewed before use.
            </p>
          ) : null}

          {selected.entry_conditions.length ||
          selected.protection_constraints.length ||
          selected.side_effects.length ||
          selected.procedure_refs.length ? (
            <div className="mt-3 grid gap-2 md:grid-cols-2 xl:grid-cols-4">
              {[
                ["Entry conditions", selected.entry_conditions],
                ["Protection constraints", selected.protection_constraints],
                ["Side effects", selected.side_effects],
                ["Procedure evidence", selected.procedure_refs],
              ].map(([label, values]) => (
                <div key={label as string} className="rounded-control border border-line2 p-2.5">
                  <span className="text-2xs font-semibold uppercase tracking-wide text-t3">
                    {label as string}
                  </span>
                  <ul className="mt-1.5 space-y-1 text-xs text-t2">
                    {(values as string[]).map((value) => (
                      <li key={value}>{value}</li>
                    ))}
                    {(values as string[]).length === 0 ? <li>Not declared</li> : null}
                  </ul>
                </div>
              ))}
            </div>
          ) : null}

          <div className="mt-3 overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead className="text-2xs uppercase tracking-wide text-t3">
                <tr>
                  <th className="pb-2 pr-3 font-medium">Signal</th>
                  <th className="pb-2 pr-3 font-medium">Route</th>
                  <th className="pb-2 pr-3 font-medium">Position(s)</th>
                  <th className="pb-2 pr-3 font-medium">Candidates</th>
                  <th className="pb-2 font-medium">Coverage</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {requirements.map((requirement) => (
                  <tr key={requirement.id}>
                    <td className="py-2 pr-3">
                      <span className="block text-t1">{requirement.label}</span>
                      <span className="font-mono text-2xs text-t3">{requirement.direction}</span>
                    </td>
                    <td className="py-2 pr-3">
                      <Badge
                        size="sm"
                        tone={
                          requirement.route_kind === "blocked"
                            ? "err"
                            : requirement.coverage_status === "complete"
                              ? "ok"
                              : "warn"
                        }
                      >
                        {requirement.route_kind}
                      </Badge>
                    </td>
                    <td className="py-2 pr-3 font-mono text-t2">
                      {[...new Set(requirement.routes.map((route) => route.position))].join(", ") ||
                        "none"}
                    </td>
                    <td className="py-2 pr-3 font-mono text-t3">
                      {Math.min(...Object.values(requirement.candidate_counts))}-
                      {Math.max(...Object.values(requirement.candidate_counts))}
                    </td>
                    <td className="py-2 font-mono text-t3">
                      {requirement.applicable_targets.length -
                        requirement.missing_targets.length -
                        requirement.blocked_targets.length}
                      /
                      {requirement.applicable_targets.length}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {incomplete.length ? (
            <details className="mt-3 border-t border-line pt-3">
              <summary className="cursor-pointer text-xs text-t2">
                {incomplete.length} incomplete target
                {incomplete.length === 1 ? "" : "s"}
              </summary>
              <div className="mt-2 max-h-36 overflow-auto font-mono text-2xs text-t3">
                {incomplete.map((target) => (
                  <p key={target.ref}>
                    {target.ref}: {target.missing_requirements.join(", ")}
                  </p>
                ))}
              </div>
            </details>
          ) : null}

          <details className="mt-3 border-t border-line pt-3">
            <summary className="cursor-pointer text-xs text-t2">
              Per-target alternate pin candidates
            </summary>
            <div className="mt-2 max-h-52 overflow-auto font-mono text-2xs text-t3">
              {requirements.flatMap((requirement) =>
                Object.entries(requirement.candidates_by_target).map(([ref, candidates]) => (
                  <p key={`${requirement.id}:${ref}`}>
                    {requirement.id} · {ref}:{" "}
                    {candidates
                      .map(
                        (candidate) =>
                          `${candidate.position}/${candidate.canonical_pin_name}/${candidate.signal}`,
                      )
                      .join(", ") || "none"}
                  </p>
                )),
              )}
            </div>
          </details>
        </div>
      </div>
    </Panel>
  );
}

function PositionInspector({
  position,
  safetyRule,
}: {
  position: TargetDefinitionPosition;
  safetyRule: TargetDefinitionDTO["safety_rules"][number] | null;
}) {
  return (
    <div className="mt-4 grid gap-3 rounded-control bg-field p-3 lg:grid-cols-[180px_minmax(0,1fr)]">
      <div>
        <Eyebrow>Position {position.position}</Eyebrow>
        <p className="mt-1 text-sm font-semibold text-t1">
          {ACTION_LABEL[position.board_action]}
        </p>
        <p className="mt-1 font-mono text-2xs text-t3">
          {position.silicon_class.replaceAll("_", " ")}
        </p>
        {position.hazard ? <p className="mt-2 text-xs text-err">{position.hazard}</p> : null}
      </div>
      <div className="min-w-0 overflow-x-auto">
        <table className="w-full text-left text-xs">
          <thead className="text-2xs uppercase tracking-wide text-t3">
            <tr>
              <th className="pb-1 pr-3 font-medium">Device</th>
              <th className="pb-1 pr-3 font-medium">Pin</th>
              <th className="pb-1 pr-3 font-medium">Electrical</th>
              <th className="pb-1 font-medium">Access</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-line">
            {position.per_target.map((target) => (
              <tr key={target.ref}>
                <td className="py-1.5 pr-3 font-mono text-t2">{target.ref}</td>
                <td className="py-1.5 pr-3 font-mono text-t1">
                  {target.canonical_pin_name}
                </td>
                <td className="py-1.5 pr-3 text-t2">
                  {target.critical_identity ?? target.electrical_class}
                </td>
                <td className="py-1.5 text-t3">{accessLabel(target)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {safetyRule ? (
        <div className="border-t border-line pt-3 lg:col-span-2" data-testid="safety-branches">
          <Eyebrow>Safety Resolution</Eyebrow>
          {safetyRule.branches.length === 0 ? (
            <p className="mt-2 text-xs text-t3">
              One position-level action; no identity branches were declared.
            </p>
          ) : (
            <div className="mt-2 grid gap-2 md:grid-cols-2 xl:grid-cols-3">
              {safetyRule.branches.map((branch) => (
                <div key={branch.id} className="rounded-control border border-line2 bg-surface p-2.5">
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-mono text-xs text-t1">{branch.id}</span>
                    <Badge
                      size="sm"
                      tone={
                        branch.action === "unsupported"
                          ? "err"
                          : branch.uses_channel
                            ? "warn"
                            : "neutral"
                      }
                    >
                      {branch.uses_channel ? "Controlled" : branch.action}
                    </Badge>
                  </div>
                  <p className="mt-1 font-mono text-2xs text-t2">
                    {branch.net || "no routed net"}
                  </p>
                  <p className="mt-1 text-2xs text-t3">
                    {branch.matched_identities.join(", ") || "no matched identities"} ·{" "}
                    {branch.matched_targets.length} target
                    {branch.matched_targets.length === 1 ? "" : "s"}
                  </p>
                </div>
              ))}
            </div>
          )}
        </div>
      ) : position.silicon_class === "safety_collision" ? (
        <p className="border-t border-line pt-3 text-xs text-err lg:col-span-2">
          No safety resolution is declared for this critical collision.
        </p>
      ) : null}
    </div>
  );
}

function RequirementLedger({ definition }: { definition: TargetDefinitionDTO }) {
  return (
    <Panel title="Route Ledger">
      <div className="max-h-72 overflow-auto px-4 pb-4">
        {definition.requirements.length === 0 ? (
          <p className="text-xs text-t3">This policy declares no service routes.</p>
        ) : (
          <table className="w-full text-left text-xs">
            <thead className="sticky top-0 bg-surface text-2xs uppercase tracking-wide text-t3">
              <tr>
                <th className="pb-2 pr-3 font-medium">Route</th>
                <th className="pb-2 pr-3 font-medium">Kind</th>
                <th className="pb-2 pr-3 font-medium">Positions</th>
                <th className="pb-2 font-medium">Coverage</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {definition.requirements.map((requirement) => (
                <tr key={requirement.id}>
                  <td className="py-2 pr-3">
                    <span className="block text-t1">{requirement.label}</span>
                    <span className="font-mono text-2xs text-t3">
                      {requirement.net} ·{" "}
                      {requirement.implementation_required ? "must implement" : "capability audit"}
                    </span>
                  </td>
                  <td className="py-2 pr-3">
                    <Badge
                      size="sm"
                      tone={
                        requirement.route_kind === "blocked"
                          ? "err"
                          : requirement.route_kind === "switched"
                            ? "warn"
                            : "ok"
                      }
                    >
                      {requirement.route_kind === "switched"
                        ? "Routed"
                        : requirement.route_kind}
                    </Badge>
                  </td>
                  <td className="py-2 pr-3 font-mono text-t2">
                    {[...new Set(requirement.routes.map((route) => route.position))].join(", ") ||
                      "none"}
                  </td>
                  <td className="py-2 font-mono text-t3">
                    {requirement.applicable_targets.length -
                      requirement.missing_targets.length -
                      requirement.blocked_targets.length}
                    /{requirement.applicable_targets.length}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </Panel>
  );
}

function ChannelLedger({ definition }: { definition: TargetDefinitionDTO }) {
  const fabric = definition.channel_fabric;
  return (
    <Panel
      title="Channel Allocation"
      actions={
        <span className="font-mono text-2xs text-t3">
          {fabric.required_channels}/{fabric.capacity || 0}
        </span>
      }
    >
      <div className="max-h-72 overflow-auto px-4 pb-4">
        {fabric.allocations.length === 0 ? (
          <p className="text-xs text-t3">No controllable channels are required.</p>
        ) : (
          <table className="w-full text-left text-xs">
            <thead className="sticky top-0 bg-surface text-2xs uppercase tracking-wide text-t3">
              <tr>
                <th className="pb-2 pr-3 font-medium">Reference</th>
                <th className="pb-2 pr-3 font-medium">Channel</th>
                <th className="pb-2 pr-3 font-medium">Position</th>
                <th className="pb-2 pr-3 font-medium">Route</th>
                <th className="pb-2 font-medium">Net</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {fabric.allocations.map((allocation) => (
                <tr
                  key={`${allocation.reference}-${allocation.channel}-${allocation.position}`}
                >
                  <td className="py-2 pr-3 font-mono text-t1">{allocation.reference}</td>
                  <td className="py-2 pr-3 font-mono text-t2">
                    {allocation.channel} / {allocation.register_label}
                  </td>
                  <td className="py-2 pr-3 font-mono text-t2">{allocation.position}</td>
                  <td className="py-2 pr-3 font-mono text-t3">
                    {allocation.branch_id ?? allocation.route_id ?? "safety"}
                  </td>
                  <td className="py-2 font-mono text-t3">{allocation.net}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </Panel>
  );
}
