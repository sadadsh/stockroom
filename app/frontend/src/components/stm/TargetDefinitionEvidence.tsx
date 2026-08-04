import type { TargetDefinitionDTO } from "../../api/types";
import {
  compatibilityKind,
  formatToken,
  sentenceCase,
} from "../../lib/stmTargetInsights";
import { Text } from "../../lib/copy";
import { Eyebrow } from "../primitives";
import { TargetCoverageMeter } from "./TargetCoverageMeter";

export function TargetDefinitionEvidence({
  definition,
}: {
  definition: TargetDefinitionDTO;
}) {
  const foundation = definition.functional_foundation.groups;
  const completeFoundation = foundation.filter(
    (group) => group.status === "complete",
  ).length;
  const services = definition.service_groups;
  const completeServices = services.filter(
    (service) => service.status === "complete",
  ).length;
  const requiredRoutes = definition.requirements.filter(
    (requirement) => requirement.required,
  );
  const completeRoutes = requiredRoutes.filter(
    (requirement) => requirement.coverage_status === "complete",
  ).length;
  const conflicts = definition.positions.filter(
    (position) => compatibilityKind(position) === "conflict",
  );
  const resolvedConflicts = conflicts.filter((position) =>
    definition.safety_rules.some(
      (rule) => rule.position === position.position,
    ),
  ).length;

  return (
    <div className="grid max-h-72 grid-cols-[minmax(0,1.2fr)_minmax(260px,0.8fr)_minmax(240px,0.7fr)] gap-6 overflow-y-auto border-t border-line px-4 py-3 text-xs">
      <div>
        <Eyebrow dense>
          <Text id="stm.target.evidence.checks">Definition Checks</Text>
        </Eyebrow>
        <ul className="mt-2 space-y-1.5 text-t2">
          {[...definition.readiness.blockers, ...definition.readiness.warnings].map(
            (item) => (
              <li key={item} className="border-l border-line pl-2">
                {sentenceCase(item)}
              </li>
            ),
          )}
          {!definition.readiness.blockers.length &&
          !definition.readiness.warnings.length ? (
            <li className="text-t3">
              <Text id="stm.target.evidence.checks.none">
                No unresolved definition checks.
              </Text>
            </li>
          ) : null}
        </ul>
      </div>

      <div>
        <Eyebrow dense>
          <Text id="stm.target.evidence.coverage">Definition Coverage</Text>
        </Eyebrow>
        <div className="mt-2 space-y-3">
          <TargetCoverageMeter
            value={completeFoundation}
            total={foundation.length}
            label="Run-Critical Groups"
            compact
          />
          <TargetCoverageMeter
            value={completeServices}
            total={services.length}
            label="Service Groups"
            compact
          />
          <TargetCoverageMeter
            value={completeRoutes}
            total={requiredRoutes.length}
            label="Required Routes"
            compact
          />
          <TargetCoverageMeter
            value={resolvedConflicts}
            total={conflicts.length}
            label="Conflict Safety Rules"
            compact
            token={
              resolvedConflicts === conflicts.length
                ? "var(--stm-classify-shared)"
                : "var(--c-err)"
            }
          />
        </div>
        <div className="mt-4 border-t border-line pt-3">
          <Eyebrow dense>
            <Text id="stm.target.evidence.support-plan">
              Universal Support Plan
            </Text>
          </Eyebrow>
          <dl className="mt-2 grid grid-cols-[1fr_auto] gap-x-3 gap-y-1 text-t3">
            <dt>
              <Text id="stm.target.evidence.direct-or-fixed">
                Direct Or Fixed Positions
              </Text>
            </dt>
            <dd className="font-mono text-t1">
              {definition.universalization.summary.direct_or_fixed}
            </dd>
            <dt>
              <Text id="stm.target.evidence.routing-adaptation">
                Routing Adaptation Positions
              </Text>
            </dt>
            <dd className="font-mono text-t1">
              {definition.universalization.summary.selectable}
            </dd>
            <dt>
              <Text id="stm.target.evidence.compact-hybrid">
                Compact Hybrid Positions
              </Text>
            </dt>
            <dd className="font-mono text-t1">
              {definition.universalization.summary.compact_hybrid ?? 0}
            </dd>
            <dt>
              <Text id="stm.target.evidence.fully-exclusive">
                Fully Exclusive Positions
              </Text>
            </dt>
            <dd className="font-mono text-t1">
              {definition.universalization.summary.fully_exclusive ??
                definition.universalization.summary.selectable}
            </dd>
            <dt>
              <Text id="stm.target.evidence.active-paths">
                Active Routing Paths
              </Text>
            </dt>
            <dd className="font-mono text-t1">
              {definition.universalization.required_independent_paths}
            </dd>
            <dt>
              <Text id="stm.target.evidence.passive-paths">
                Passive Conditioned Paths
              </Text>
            </dt>
            <dd className="font-mono text-t1">
              {definition.universalization.passive_conditioned_paths ?? 0}
            </dd>
            <dt>
              <Text id="stm.target.evidence.default-state">Default State</Text>
            </dt>
            <dd className="text-t1">
              {formatToken(definition.universalization.safe_default)}
            </dd>
            <dt>
              <Text id="stm.target.evidence.circuit-implementation">
                Circuit Implementation
              </Text>
            </dt>
            <dd className="text-t1">
              <Text id="stm.target.evidence.owned-by-consumer">
                Owned By Consumer
              </Text>
            </dd>
          </dl>
        </div>
      </div>

      <div>
        <Eyebrow dense>
          <Text id="stm.target.evidence.source">Source And Compiler</Text>
        </Eyebrow>
        <dl className="mt-2 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-t3">
          <dt>
            <Text id="stm.target.evidence.silicon-source">Silicon Source</Text>
          </dt>
          <dd className="truncate font-mono text-t1">
            {definition.provenance.silicon_source}
          </dd>
          <dt>
            <Text id="stm.target.evidence.source-digest">Source Digest</Text>
          </dt>
          <dd className="font-mono text-t1">
            {definition.provenance.source_sha256.slice(0, 12)}
          </dd>
          <dt>
            <Text id="stm.target.evidence.compiler-revision">
              Compiler Revision
            </Text>
          </dt>
          <dd className="font-mono text-t1">R{definition.compiler_rev}</dd>
          <dt>
            <Text id="stm.target.evidence.policy">Policy</Text>
          </dt>
          <dd className="truncate font-mono text-t1">
            {formatToken(definition.profile.id)}
          </dd>
          <dt>
            <Text id="stm.target.evidence.artifact">Artifact</Text>
          </dt>
          <dd className="font-mono text-t1">
            {definition.artifact_digest.slice(0, 12)}
          </dd>
        </dl>
      </div>
    </div>
  );
}
