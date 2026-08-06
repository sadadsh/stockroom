import { useMemo, useState } from "react";
import type { TargetDefinitionDTO } from "../../api/types";
import {
  compatibilityKind,
  formatPercent,
} from "../../lib/stmTargetInsights";
import {
  TARGET_LENSES,
  targetMatchesLegend,
  type TargetMapLens,
} from "../../lib/stmTargetVisuals";
import { Text, useText } from "../../lib/copy";
import { SegmentedControl } from "../primitives";
import { TargetDefinitionEvidence } from "./TargetDefinitionEvidence";
import { TargetPackageMap } from "./TargetPackageMap";
import { TargetPositionInspector } from "./TargetPositionInspector";
import { TargetSmartLegend } from "./TargetSmartLegend";

function selectedDefault(definition: TargetDefinitionDTO): string | null {
  return (
    definition.positions.find((position) => compatibilityKind(position) === "conflict")
      ?.position ??
    definition.positions.find((position) =>
      position.access_tags_union.some((tag) =>
        ["swdio", "swclk", "jtag", "swo"].includes(tag),
      ),
    )?.position ??
    definition.functional_foundation.unresolved_positions[0] ??
    definition.positions[0]?.position ??
    null
  );
}

// A new definition invalidates the lens, the legend selection and the selected position - a full
// state reset. This wrapper keys the body on the definition's content-addressed artifact_digest so
// React remounts it, instead of an effect that costs a render still showing the old definition's
// selection (and that had to read the whole `definition` while watching only its digest).
export function TargetDefinitionPanel({
  definition,
}: {
  definition: TargetDefinitionDTO;
}) {
  return (
    <TargetDefinitionBody key={definition.artifact_digest} definition={definition} />
  );
}

function TargetDefinitionBody({
  definition,
}: {
  definition: TargetDefinitionDTO;
}) {
  const [lens, setLens] = useState<TargetMapLens>("compatibility");
  const [activeLegendKey, setActiveLegendKey] = useState<string | null>(null);
  const [selectedPosition, setSelectedPosition] = useState<string | null>(() =>
    selectedDefault(definition),
  );

  const selected = useMemo(
    () =>
      definition.positions.find(
        (position) => position.position === selectedPosition,
      ) ?? null,
    [definition.positions, selectedPosition],
  );
  const universalPositions = useMemo(
    () =>
      definition.positions.filter(
        (position) => compatibilityKind(position) === "identical",
      ).length,
    [definition.positions],
  );
  const ready = definition.readiness.status === "ready";
  const adaptedPositions = definition.universalization.summary.selectable;
  const workbenchLabel = useText(
    "stm.target.workbench.aria",
    "Universal MCU Support Workbench",
  );
  const lensLabel = useText("stm.target.lens.aria", "Pinout Lens");

  const selectLegend = (key: string | null) => {
    setActiveLegendKey(key);
    if (!key) return;
    const first = definition.positions.find(
      (position) => targetMatchesLegend(position, lens, key),
    );
    if (first) setSelectedPosition(first.position);
  };

  return (
    <section
      data-dev-id="stm.target-definition"
      className="flex min-h-0 flex-1 flex-col"
      data-testid="target-definition"
      aria-label={workbenchLabel}
    >
      <header className="flex flex-none items-center justify-between gap-5 border-b border-line px-4 py-2">
        <div className="flex min-w-0 items-center gap-3">
          <div className="min-w-0">
            <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
              <h2 className="font-mono text-sm font-semibold text-t1">
                <Text
                  id="stm.target.definition.heading"
                  values={{ packageName: definition.scope.package }}
                >
                  {"{packageName} Universal Support"}
                </Text>
              </h2>
              <span
                className={`flex items-center gap-1.5 text-2xs font-medium ${
                  ready ? "text-ok-text" : "text-err-text"
                }`}
              >
                <span className="h-1.5 w-1.5 rounded-full bg-current" />
                {ready ? (
                  <Text id="stm.target.definition-prepared">Definition Prepared</Text>
                ) : (
                  <Text id="stm.target.definition-blocked">Definition Blocked</Text>
                )}
              </span>
            </div>
            <p className="mt-0.5 truncate text-2xs text-t3">
              {definition.scope.families.length}{" "}
              {definition.scope.families.length === 1 ? "Family" : "Families"} ·{" "}
              {definition.scope.target_count} MCU Variants ·{" "}
              {definition.scope.families.join(", ")} ·{" "}
              {definition.universalization.required_independent_paths} Active
              Routing{" "}
              {definition.universalization.required_independent_paths === 1
                ? "Path"
                : "Paths"}
            </p>
          </div>
        </div>

        <div className="flex flex-none items-center divide-x divide-line text-right">
          <div className="pr-4">
            <span className="block font-mono text-xs font-semibold text-t1">
              {formatPercent(universalPositions, definition.positions.length)}
            </span>
            <span className="block text-2xs text-t3">
              <Text
                id="stm.target.definition.shared-count"
                values={{ shared: universalPositions, total: definition.positions.length }}
              >
                {"{shared}/{total} Shared"}
              </Text>
            </span>
          </div>
          <div className="pl-4">
            <span
              className={`block font-mono text-xs font-semibold ${
                adaptedPositions ? "text-warn" : "text-ok-text"
              }`}
            >
              {adaptedPositions}
            </span>
            <span className="block text-2xs text-t3">
              <Text id="stm.target.routing-adaptations">
                Routing Adaptations
              </Text>
            </span>
          </div>
        </div>
      </header>

      <div className="grid min-h-0 flex-1 grid-cols-[minmax(0,1fr)_344px]">
        <div className="flex min-h-0 min-w-0 flex-col">
          <div className="flex flex-none items-center justify-between gap-3 border-b border-line px-3 py-1.5">
            <span className="text-2xs font-medium text-t3">
              <Text id="stm.target.map-lens">Map Lens</Text>
            </span>
            <SegmentedControl
              options={TARGET_LENSES}
              value={lens}
              onChange={(nextLens) => {
                setLens(nextLens);
                setActiveLegendKey(null);
              }}
              size="small"
              devIdBase="stm.lens"
              aria-label={lensLabel}
            />
          </div>

          <TargetSmartLegend
            positions={definition.positions}
            lens={lens}
            activeKey={activeLegendKey}
            onSelect={selectLegend}
          />

          <div className="flex min-h-0 flex-1 flex-col p-3">
            <TargetPackageMap
              packageName={definition.scope.package}
              positions={definition.positions}
              lens={lens}
              activeLegendKey={activeLegendKey}
              selectedPosition={selectedPosition}
              onSelectPosition={setSelectedPosition}
            />
          </div>
        </div>

        <aside className="min-h-0 overflow-hidden border-l border-line bg-surface">
          {selected ? (
            /* keyed on the position: a new position remounts the inspector, so its view resets to
               "decision" without an adjustment effect. */
            <TargetPositionInspector
              key={selected.position}
              definition={definition}
              position={selected}
            />
          ) : (
            <div className="p-4 text-xs text-t3">
              <Text id="stm.target.select-position">
                Select a package position.
              </Text>
            </div>
          )}
        </aside>
      </div>

      <details className="flex-none border-t border-line bg-surface">
        <summary className="cursor-pointer px-4 py-2 text-xs text-t2">
          <Text id="stm.target.definition-evidence">Definition Evidence</Text>
          <span className="ml-2 font-mono text-2xs text-t3">
            {definition.readiness.blockers.length} Blocking{" "}
            {definition.readiness.blockers.length === 1 ? "Check" : "Checks"} ·{" "}
            {definition.artifact_digest.slice(0, 12)}
          </span>
        </summary>
        <TargetDefinitionEvidence definition={definition} />
      </details>
    </section>
  );
}
