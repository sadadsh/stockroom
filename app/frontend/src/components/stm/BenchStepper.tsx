/**
 * The Bench's set stepper: the previous/next controls, the target-set chooser, the scope summary,
 * and the export menu. Extracted from CompatibilityWorkbench so that file stays the Bench's data
 * flow; this file is the one control band, and it resolves its own copy.
 */
import { AdaptiveChoice } from "../AdaptiveChoice";
import { Icon } from "../Icon";
import { Button } from "../primitives";
import { Text, useCopyFormatter, useText } from "../../lib/copy";
import type { StmSocketExportKind } from "../../lib/stmSocketSolutionExport";
import type { BenchSet } from "./benchModel";

export function BenchStepper({
  sets,
  activeSetId,
  customParts,
  coveredCount,
  familyCount,
  selectedPackage,
  exportDisabled,
  onStepBy,
  onStepTo,
  onExport,
}: {
  sets: BenchSet[];
  activeSetId: string;
  customParts: string[] | null;
  coveredCount: number | "";
  familyCount: number;
  selectedPackage: string | null;
  exportDisabled: boolean;
  onStepBy: (delta: number) => void;
  onStepTo: (id: string) => void;
  onExport: (kind: StmSocketExportKind) => void;
}) {
  const previousSetLabel = useText("stm.compat.previous-set.aria", "Previous Set");
  const nextSetLabel = useText("stm.compat.next-set.aria", "Next Set");
  const targetSetControlLabel = useText("stm.compat.target-set-control.label", "Target Set");
  const customSetLabel = useCopyFormatter("stm.compat.custom-set.option", "Custom · {count}");
  return (
    <div
      className="flex flex-none items-center gap-2 border-b border-line px-3 py-1.5"
      data-testid="bench-stepper"
    >
      <Button
        small
        icon={<Icon id="nav.back" className="h-3.5 w-3.5" />}
        onClick={() => onStepBy(-1)}
        aria-label={previousSetLabel}
      />
      <label className="flex min-w-0 items-center gap-2">
        <span className="text-xs text-t3">
          <Text id="stm.compat.target-set-label">Target set</Text>
        </span>
        <AdaptiveChoice
          devId="stm.target-set-control"
          label={targetSetControlLabel}
          value={customParts ? "custom" : activeSetId}
          onChange={(next) => next !== "custom" && onStepTo(next)}
          options={[
            ...sets.map((set) => ({
              value: set.id,
              label: `${set.label} · ${set.count}${set.tier === "divergent" ? ` · ${set.divergent} divergent` : ""}`,
            })),
            ...(customParts
              ? [
                  {
                    value: "custom",
                    label: customSetLabel({ count: customParts.length }),
                    disabled: true,
                  },
                ]
              : []),
          ]}
        />
      </label>
      <Button
        small
        icon={<Icon id="nav.back" className="h-3.5 w-3.5 rotate-180" />}
        onClick={() => onStepBy(1)}
        aria-label={nextSetLabel}
      />
      <span className="min-w-0 flex-1 truncate font-mono text-2xs text-t3">
        <Text
          id="stm.compat.scope-summary"
          values={{
            covered: coveredCount,
            total: familyCount,
            package: selectedPackage ?? "",
          }}
        >
          {"{covered}/{total} series · {package}"}
        </Text>
      </span>
      <ExportMenu disabled={exportDisabled} onExport={onExport} />
    </div>
  );
}

// The export kinds in menu order; each kind's label and description resolve through the copy layer
// inside the menu (a hook cannot run out here).
const EXPORT_KINDS: StmSocketExportKind[] = [
  "request",
  "solution",
  "support-cells",
  "positions",
  "control-states",
  "proofs",
];

function ExportMenu({
  disabled,
  onExport,
}: {
  disabled: boolean;
  onExport: (kind: StmSocketExportKind) => void;
}) {
  const exportLabel = useText("stm.compat.export", "Export");
  const exportMenuLabel = useText("stm.compat.export-menu.aria", "Export Target Data");
  const options: Record<StmSocketExportKind, { label: string; description: string }> = {
    request: {
      label: useText("stm.compat.export.request.label", "Socket Request"),
      description: useText(
        "stm.compat.export.request.description",
        "Exact target set and solution rules",
      ),
    },
    solution: {
      label: useText("stm.compat.export.solution.label", "Socket Solution"),
      description: useText(
        "stm.compat.export.solution.description",
        "Digest-bound support cells, cohorts, and fabric",
      ),
    },
    "support-cells": {
      label: useText("stm.compat.export.support-cells.label", "Support Cells"),
      description: useText(
        "stm.compat.export.support-cells.description",
        "Reusable structure and capabilities",
      ),
    },
    positions: {
      label: useText("stm.compat.export.positions.label", "Package Positions"),
      description: useText(
        "stm.compat.export.positions.description",
        "Each package position and assigned solution",
      ),
    },
    "control-states": {
      label: useText("stm.compat.export.control-states.label", "Control States"),
      description: useText(
        "stm.compat.export.control-states.description",
        "Behavioral cohorts and permitted branch states",
      ),
    },
    proofs: {
      label: useText("stm.compat.export.proofs.label", "Electrical Proofs"),
      description: useText(
        "stm.compat.export.proofs.description",
        "Implementation checks and failure actions",
      ),
    },
  };
  return (
    <details className="relative flex-none">
      <summary
        aria-disabled={disabled || undefined}
        onClick={(event) => disabled && event.preventDefault()}
        className={
          "flex h-[27px] cursor-pointer list-none items-center rounded-control border " +
          "border-line bg-raise px-2.5 text-xs font-medium text-t2 transition-colors " +
          "hover:bg-raise2 hover:text-t1 focus-visible:outline focus-visible:outline-2 " +
          "focus-visible:outline-offset-2 focus-visible:outline-focus " +
          (disabled ? "cursor-not-allowed opacity-50" : "")
        }
      >
        {exportLabel}
      </summary>
      <div
        role="menu"
        aria-label={exportMenuLabel}
        className="absolute right-0 top-full z-30 mt-1 w-72 overflow-hidden rounded-card border border-line bg-popover py-1 shadow-pop"
      >
        {EXPORT_KINDS.map((kind) => (
          <button
            key={kind}
            type="button"
            role="menuitem"
            onClick={(event) => {
              onExport(kind);
              event.currentTarget.closest("details")?.removeAttribute("open");
            }}
            className="block w-full px-3 py-2 text-left hover:bg-raise2 focus-visible:bg-raise2 focus-visible:outline-none"
          >
            <span className="block text-xs font-medium text-t1">{options[kind].label}</span>
            <span className="mt-0.5 block text-2xs text-t3">{options[kind].description}</span>
          </button>
        ))}
      </div>
    </details>
  );
}

