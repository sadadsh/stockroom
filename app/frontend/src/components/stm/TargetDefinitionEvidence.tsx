import type { TargetDefinitionDTO } from "../../api/types";
import {
  compatibilityKind,
  formatToken,
  sentenceCase,
} from "../../lib/stmTargetInsights";
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
        <Eyebrow dense>Definition Checks</Eyebrow>
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
            <li className="text-t3">No unresolved definition checks.</li>
          ) : null}
        </ul>
      </div>

      <div>
        <Eyebrow dense>Definition Coverage</Eyebrow>
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
          <Eyebrow dense>Universal Support Plan</Eyebrow>
          <dl className="mt-2 grid grid-cols-[1fr_auto] gap-x-3 gap-y-1 text-t3">
            <dt>Direct Or Fixed Positions</dt>
            <dd className="font-mono text-t1">
              {definition.universalization.summary.direct_or_fixed}
            </dd>
            <dt>Routing Adaptation Positions</dt>
            <dd className="font-mono text-t1">
              {definition.universalization.summary.selectable}
            </dd>
            <dt>Compact Hybrid Positions</dt>
            <dd className="font-mono text-t1">
              {definition.universalization.summary.compact_hybrid ?? 0}
            </dd>
            <dt>Fully Exclusive Positions</dt>
            <dd className="font-mono text-t1">
              {definition.universalization.summary.fully_exclusive ??
                definition.universalization.summary.selectable}
            </dd>
            <dt>Active Routing Paths</dt>
            <dd className="font-mono text-t1">
              {definition.universalization.required_independent_paths}
            </dd>
            <dt>Passive Conditioned Paths</dt>
            <dd className="font-mono text-t1">
              {definition.universalization.passive_conditioned_paths ?? 0}
            </dd>
            <dt>Default State</dt>
            <dd className="text-t1">
              {formatToken(definition.universalization.safe_default)}
            </dd>
            <dt>Circuit Implementation</dt>
            <dd className="text-t1">Owned By Consumer</dd>
          </dl>
        </div>
      </div>

      <div>
        <Eyebrow dense>Source And Compiler</Eyebrow>
        <dl className="mt-2 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-t3">
          <dt>Silicon Source</dt>
          <dd className="truncate font-mono text-t1">
            {definition.provenance.silicon_source}
          </dd>
          <dt>Source Digest</dt>
          <dd className="font-mono text-t1">
            {definition.provenance.source_sha256.slice(0, 12)}
          </dd>
          <dt>Compiler Revision</dt>
          <dd className="font-mono text-t1">R{definition.compiler_rev}</dd>
          <dt>Policy</dt>
          <dd className="truncate font-mono text-t1">
            {formatToken(definition.profile.id)}
          </dd>
          <dt>Artifact</dt>
          <dd className="font-mono text-t1">
            {definition.artifact_digest.slice(0, 12)}
          </dd>
        </dl>
      </div>
    </div>
  );
}
