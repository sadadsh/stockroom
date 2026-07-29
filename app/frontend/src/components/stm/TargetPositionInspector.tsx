import { useEffect, useMemo, useState } from "react";
import type {
  TargetDefinitionDTO,
  TargetDefinitionPosition,
} from "../../api/types";
import {
  BOARD_ACTION_EXPLANATION,
  BOARD_ACTION_LABEL,
  TARGET_COMPATIBILITY_INSIGHTS,
  compatibilityKind,
  formatElectricalIdentity,
  formatPercent,
  formatToken,
  sentenceCase,
} from "../../lib/stmTargetInsights";
import { Eyebrow, SegmentedControl } from "../primitives";
import { TargetCoverageMeter } from "./TargetCoverageMeter";

type InspectorView = "decision" | "targets" | "evidence";

const INSPECTOR_VIEWS: ReadonlyArray<{
  id: InspectorView;
  label: string;
}> = [
  { id: "decision", label: "Decision" },
  { id: "targets", label: "MCUs" },
  { id: "evidence", label: "Evidence" },
];

export function TargetPositionInspector({
  definition,
  position,
}: {
  definition: TargetDefinitionDTO;
  position: TargetDefinitionPosition;
}) {
  const [view, setView] = useState<InspectorView>("decision");
  useEffect(() => setView("decision"), [position.position]);

  const foundation = definition.functional_foundation.groups.filter((group) =>
    group.positions.includes(position.position),
  );
  const requirements = definition.requirements.filter(
    (requirement) =>
      position.route_ids.includes(requirement.id) ||
      requirement.routes.some((route) => route.position === position.position),
  );
  const services = definition.service_groups.filter((group) =>
    group.requirement_ids.some((id) =>
      requirements.some((requirement) => requirement.id === id),
    ),
  );
  const safety = definition.safety_rules.find(
    (rule) => rule.position === position.position,
  );
  const routingPaths = definition.routing_requirements.paths.filter(
    (path) => path.position === position.position,
  );
  const strategy = definition.universalization.strategies.find(
    (candidate) => candidate.position === position.position,
  );
  const kind = compatibilityKind(position);
  const insight = TARGET_COMPATIBILITY_INSIGHTS[kind];
  const identityGroups = useMemo(() => {
    const groups = new Map<
      string,
      {
        canonicalPinName: string;
        electricalIdentity: string;
        refs: string[];
        functions: Set<string>;
      }
    >();
    for (const target of position.per_target) {
      const electricalIdentity =
        target.critical_identity ?? target.electrical_class;
      const key = `${target.canonical_pin_name}\u0000${electricalIdentity}`;
      const group = groups.get(key) ?? {
        canonicalPinName: target.canonical_pin_name,
        electricalIdentity,
        refs: [],
        functions: new Set<string>(),
      };
      group.refs.push(target.ref);
      target.functions.forEach((item) => group.functions.add(item));
      groups.set(key, group);
    }
    return [...groups.values()].sort((a, b) => b.refs.length - a.refs.length);
  }, [position.per_target]);

  return (
    <div
      data-dev-id="stm.target-inspector"
      className="flex h-full min-h-0 flex-col"
      data-testid="target-position-inspector"
    >
      <header className="flex-none border-b border-line bg-surface px-3 pb-2.5 pt-3">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <Eyebrow dense>Physical Position</Eyebrow>
            <div className="mt-0.5 flex items-baseline gap-2">
              <span className="font-mono text-xl font-semibold text-t1">
                {position.position}
              </span>
              <span className="truncate font-mono text-xs font-medium text-t1">
                {identityGroups[0]?.canonicalPinName ?? insight.label}
              </span>
            </div>
          </div>
          <div className="min-w-0 flex-none text-right">
            <span className="block truncate text-xs font-medium text-t1">
              {insight.label}
            </span>
            <span className="block font-mono text-2xs text-t3">
              {position.present_on} Of {position.total_targets} MCUs ·{" "}
              {formatPercent(position.present_on, position.total_targets)}
            </span>
          </div>
        </div>
        <SegmentedControl
          options={INSPECTOR_VIEWS}
          value={view}
          onChange={setView}
          size="small"
          className="mt-2 w-full [&>button]:flex-1"
          devIdBase="stm.inspector"
          aria-label="Position Inspector View"
        />
      </header>

      <div className="min-h-0 flex-1 overflow-y-auto p-3">
        {view === "decision" ? (
          <DecisionView
            position={position}
            insight={insight}
            kind={kind}
            identityCount={identityGroups.length}
            foundation={foundation}
            requirements={requirements}
            strategy={strategy}
          />
        ) : view === "targets" ? (
          <TargetsView
            groups={identityGroups}
            targetCount={position.total_targets}
            token={insight.token}
          />
        ) : (
          <EvidenceView
            position={position}
            foundation={foundation}
            requirements={requirements}
            services={services}
            strategy={strategy}
            safety={safety}
            routingPaths={routingPaths}
            stateContract={definition.universalization.state_contract}
          />
        )}
      </div>
    </div>
  );
}

function DecisionView({
  position,
  insight,
  kind,
  identityCount,
  foundation,
  requirements,
  strategy,
}: {
  position: TargetDefinitionPosition;
  insight: (typeof TARGET_COMPATIBILITY_INSIGHTS)[keyof typeof TARGET_COMPATIBILITY_INSIGHTS];
  kind: ReturnType<typeof compatibilityKind>;
  identityCount: number;
  foundation: TargetDefinitionDTO["functional_foundation"]["groups"];
  requirements: TargetDefinitionDTO["requirements"];
  strategy: TargetDefinitionDTO["universalization"]["strategies"][number] | undefined;
}) {
  return (
    <>
      <div
        className={`border-l-2 bg-raise2 px-3 py-2 ${
          kind === "conflict" ? "border-err" : "border-line2"
        }`}
      >
        <p className="text-xs leading-relaxed text-t2">{insight.consequence}</p>
        {position.present_on < position.total_targets ? (
          <p className="mt-1 text-2xs text-t3">
            Missing on {position.total_targets - position.present_on} selected MCU{" "}
            {position.total_targets - position.present_on === 1 ? "variant" : "variants"}.
          </p>
        ) : null}
      </div>

      <dl className="mt-3 grid grid-cols-[1fr_auto] gap-x-3 gap-y-1.5 border-y border-line py-2 text-xs">
        <dt className="text-t3">Electrical Identities</dt>
        <dd className="font-mono text-t1">{identityCount}</dd>
        <dt className="text-t3">Board Action</dt>
        <dd className="text-right text-t1">
          {BOARD_ACTION_LABEL[position.board_action]}
        </dd>
        <dt className="text-t3">Active Routing Paths</dt>
        <dd className="font-mono text-t1">
          {strategy?.active_path_count ?? strategy?.branches.length ?? 0}
        </dd>
        <dt className="text-t3">Safe Default</dt>
        <dd className="text-right text-t1">
          {strategy?.safe_default ? formatToken(strategy.safe_default) : "Not Declared"}
        </dd>
      </dl>

      <InspectorSection title="Universal Circuit">
        {strategy ? (
          <>
            <div className="flex items-baseline justify-between gap-2">
              <p className="text-xs font-medium text-t1">
                {formatToken(strategy.primitive)}
              </p>
              <span className="text-2xs text-t3">
                {formatToken(strategy.evidence_status)}
              </span>
            </div>
            <p className="mt-1 text-2xs leading-relaxed text-t2">
              {strategy.explanation}
            </p>
            <div className="mt-2 divide-y divide-line">
              {strategy.branches.map((branch) => (
                <div key={branch.id} className="py-1.5 text-2xs">
                  <div className="flex justify-between gap-2">
                    <span className="min-w-0 text-t2">
                      {branch.matched_identities
                        .map(formatElectricalIdentity)
                        .join(", ")}
                    </span>
                    <span className="flex-none font-mono text-t3">
                      {branch.matched_targets.length} MCU
                    </span>
                  </div>
                  <p className="mt-0.5 text-t3">
                    {formatToken(branch.connection_mode ?? branch.action)}
                    {branch.net ? ` · ${branch.net}` : ""}
                  </p>
                </div>
              ))}
            </div>
          </>
        ) : (
          <EmptyInspectorRow text="No routing adaptation is required at this position." />
        )}
      </InspectorSection>

      {strategy && strategy.validation.status !== "not-required" ? (
        <InspectorSection title="Proof Required">
          <p className="text-2xs leading-relaxed text-t2">
            {strategy.validation.required_checks.length
              ? strategy.validation.required_checks.map(formatToken).join(", ")
              : "Target-specific safety evidence"}
          </p>
          <p className="mt-1 text-2xs text-t3">
            If proof fails: {formatToken(strategy.validation.failure_action)}.
          </p>
        </InspectorSection>
      ) : null}

      <InspectorSection title="Obligations">
        {foundation.length || requirements.length ? (
          <div className="space-y-2">
            {foundation.map((group) => (
              <CompactStatusRow
                key={group.id}
                label={group.label}
                status={`${group.resolved_target_count}/${group.present_target_count}`}
                complete={group.status === "complete"}
              />
            ))}
            {requirements.map((requirement) => (
              <CompactStatusRow
                key={requirement.id}
                label={requirement.label}
                status={`${requirement.routes.filter((route) => route.usable).length}/${requirement.applicable_targets.length}`}
                complete={requirement.coverage_status === "complete"}
              />
            ))}
          </div>
        ) : (
          <EmptyInspectorRow text="No run-critical or service obligation is declared here." />
        )}
        {position.access_tags_union.length ? (
          <div className="mt-2 flex flex-wrap gap-1">
            {position.access_tags_union.map((tag) => (
              <span
                key={tag}
                className="rounded-control border border-line bg-raise2 px-1.5 py-0.5 text-2xs text-t2"
              >
                {formatToken(tag)}
              </span>
            ))}
          </div>
        ) : null}
      </InspectorSection>
    </>
  );
}

function TargetsView({
  groups,
  targetCount,
  token,
}: {
  groups: {
    canonicalPinName: string;
    electricalIdentity: string;
    refs: string[];
    functions: Set<string>;
  }[];
  targetCount: number;
  token: string;
}) {
  return (
    <>
      <p className="mb-2 text-2xs leading-relaxed text-t3">
        Grouped by canonical pin name and electrical identity across the selected MCU set.
      </p>
      <div className="divide-y divide-line border-y border-line">
        {groups.map((group) => (
          <details
            key={`${group.canonicalPinName}:${group.electricalIdentity}`}
            className="py-2"
          >
            <summary className="cursor-pointer list-none">
              <div className="grid grid-cols-[minmax(0,1fr)_auto] gap-3">
                <div className="min-w-0">
                  <span className="block truncate font-mono text-xs text-t1">
                    {group.canonicalPinName}
                  </span>
                  <span className="text-2xs text-t3">
                    {formatElectricalIdentity(group.electricalIdentity)}
                  </span>
                </div>
                <span className="text-right font-mono text-2xs text-t2">
                  {group.refs.length}/{targetCount} ·{" "}
                  {formatPercent(group.refs.length, targetCount)}
                </span>
              </div>
              <div className="mt-1 h-1 overflow-hidden rounded-control bg-raise2">
                <div
                  className="h-full rounded-control"
                  style={{
                    width: `${(group.refs.length / targetCount) * 100}%`,
                    backgroundColor: token,
                  }}
                />
              </div>
            </summary>
            {group.functions.size ? (
              <p className="mt-2 text-2xs text-t3">
                Declared Functions: {[...group.functions].map(formatToken).join(", ")}
              </p>
            ) : null}
            <div className="mt-2 max-h-40 overflow-y-auto border-l border-line pl-2 font-mono text-2xs text-t3">
              {group.refs.map((ref) => (
                <div key={ref} className="truncate" title={ref}>
                  {ref}
                </div>
              ))}
            </div>
          </details>
        ))}
      </div>
    </>
  );
}

function EvidenceView({
  position,
  foundation,
  requirements,
  services,
  strategy,
  safety,
  routingPaths,
  stateContract,
}: {
  position: TargetDefinitionPosition;
  foundation: TargetDefinitionDTO["functional_foundation"]["groups"];
  requirements: TargetDefinitionDTO["requirements"];
  services: TargetDefinitionDTO["service_groups"];
  strategy: TargetDefinitionDTO["universalization"]["strategies"][number] | undefined;
  safety: TargetDefinitionDTO["safety_rules"][number] | undefined;
  routingPaths: TargetDefinitionDTO["routing_requirements"]["paths"];
  stateContract: TargetDefinitionDTO["universalization"]["state_contract"];
}) {
  return (
    <>
      <InspectorSection title="Run Critical" first>
        {foundation.length ? (
          <div className="space-y-3">
            {foundation.map((group) => (
              <div key={group.id}>
                <TargetCoverageMeter
                  value={group.resolved_target_count}
                  total={group.present_target_count}
                  label={group.label}
                  compact
                  token={
                    group.status === "complete"
                      ? "var(--stm-classify-shared)"
                      : "var(--c-err)"
                  }
                />
                <p className="mt-1 text-2xs leading-relaxed text-t3">
                  {sentenceCase(group.obligation)}
                </p>
              </div>
            ))}
          </div>
        ) : (
          <EmptyInspectorRow text="No run-critical obligation is declared here." />
        )}
      </InspectorSection>

      <InspectorSection title="Access Routes">
        {requirements.length || services.length ? (
          <div className="space-y-3">
            {requirements.map((requirement) => (
              <div key={requirement.id}>
                <TargetCoverageMeter
                  value={requirement.routes.filter((route) => route.usable).length}
                  total={requirement.applicable_targets.length}
                  label={requirement.label}
                  compact
                  token={
                    requirement.coverage_status === "complete"
                      ? "var(--stm-classify-shared)"
                      : "var(--stm-classify-partial)"
                  }
                />
                <p className="mt-1 text-2xs text-t3">
                  {formatToken(requirement.protocol || requirement.category)}
                  {requirement.direction
                    ? ` · ${formatToken(requirement.direction)}`
                    : ""}
                  {` · ${formatToken(requirement.route_kind)}`}
                </p>
              </div>
            ))}
            {services.map((service) => (
              <TargetCoverageMeter
                key={service.id}
                value={service.complete_target_count}
                total={service.applicable_target_count}
                label={service.label}
                compact
                token={
                  service.status === "complete"
                    ? "var(--stm-classify-shared)"
                    : "var(--stm-classify-partial)"
                }
              />
            ))}
          </div>
        ) : (
          <EmptyInspectorRow text="No debug, recovery, or extraction route is declared here." />
        )}
      </InspectorSection>

      <InspectorSection title="Board Evidence">
        <p className="text-xs font-medium text-t1">
          {BOARD_ACTION_LABEL[position.board_action]}
        </p>
        <p className="mt-1 text-2xs leading-relaxed text-t3">
          {BOARD_ACTION_EXPLANATION[position.board_action]}
        </p>
        {safety ? (
          <div className="mt-2 border-y border-line py-2">
            <div className="flex justify-between gap-3 text-xs">
              <span className="text-t3">Safe Default</span>
              <span className="text-t1">{formatToken(safety.safe_default)}</span>
            </div>
            {safety.branches.map((branch) => (
              <div key={branch.id} className="mt-2 border-l border-line pl-2 text-2xs">
                <p className="text-t2">{formatToken(branch.id)}</p>
                <p className="mt-0.5 text-t3">
                  {formatToken(branch.action)} · {branch.net || "No Net Assigned"}
                </p>
              </div>
            ))}
          </div>
        ) : null}
        {routingPaths.map((path) => (
          <p
            key={path.path_id}
            className="mt-2 text-2xs text-t3"
          >
            {formatToken(path.path_id)} · {path.requested_net}
          </p>
        ))}
      </InspectorSection>

      {strategy?.fallback || strategy?.constraints.length ? (
        <InspectorSection title="Constraints">
          {strategy.fallback ? (
            <>
              <div className="flex justify-between gap-2 text-2xs">
                <span className="font-medium text-t1">Conservative Fallback</span>
                <span className="font-mono text-t2">
                  {strategy.fallback.independent_paths} Active Paths
                </span>
              </div>
              <p className="mt-1 text-2xs leading-relaxed text-t3">
                {strategy.fallback.reason}
              </p>
            </>
          ) : null}
          {strategy.constraints.length ? (
            <ul className="mt-2 space-y-1 text-2xs leading-relaxed text-t3">
              {strategy.constraints.map((constraint) => (
                <li key={constraint} className="border-l border-line pl-2">
                  {constraint}
                </li>
              ))}
            </ul>
          ) : null}
        </InspectorSection>
      ) : null}

      <InspectorSection title="Safe State Contract">
        <dl className="grid grid-cols-[minmax(0,1fr)_auto] gap-x-3 gap-y-1 text-2xs">
          {Object.entries(stateContract).map(([state, behavior]) => (
            <div key={state} className="contents">
              <dt className="text-t3">{formatToken(state)}</dt>
              <dd className="text-right text-t2">{formatToken(behavior)}</dd>
            </div>
          ))}
        </dl>
      </InspectorSection>
    </>
  );
}

function InspectorSection({
  title,
  first = false,
  children,
}: {
  title: string;
  first?: boolean;
  children: React.ReactNode;
}) {
  return (
    <section className={first ? "" : "mt-4 border-t border-line pt-3"}>
      <Eyebrow dense>{title}</Eyebrow>
      <div className="mt-2">{children}</div>
    </section>
  );
}

function CompactStatusRow({
  label,
  status,
  complete,
}: {
  label: string;
  status: string;
  complete: boolean;
}) {
  return (
    <div className="flex items-center justify-between gap-2 text-xs">
      <span className="min-w-0 truncate text-t2">{label}</span>
      <span className={`flex-none font-mono text-2xs ${complete ? "text-ok" : "text-warn"}`}>
        {status}
      </span>
    </div>
  );
}

function EmptyInspectorRow({ text }: { text: string }) {
  return <p className="text-xs text-t3">{text}</p>;
}
