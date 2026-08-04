import { useEffect, useMemo, useState } from "react";
import type {
  SocketSolutionDTO,
  SocketSolutionPosition,
  SocketSupportCell,
  SocketTargetCohort,
  TargetDefinitionPosition,
} from "../../api/types";
import { Text, useText } from "../../lib/copy";
import { Badge, Eyebrow } from "../primitives";
import {
  TargetPackageMap,
  type TargetMapPositionVisual,
} from "./TargetPackageMap";

type PositionFilter =
  | "all"
  | "direct"
  | "configurable"
  | "mixed"
  | "critical"
  | "proof";
type DetailView = "configurations" | "cells" | "contract";

interface TopologySpec {
  type: SocketSolutionPosition["cell_type"];
  label: string;
  color: string;
  explanation: string;
}

const TOPOLOGIES: TopologySpec[] = [
  {
    type: "fixed-network",
    label: "Fixed Network",
    color: "var(--stm-classify-shared)",
    explanation: "One electrical role is valid for every selected target.",
  },
  {
    type: "universal-io",
    label: "Universal I/O",
    color: "var(--stm-gpio)",
    explanation: "One common signal lane preserves every target's internal pin functions.",
  },
  {
    type: "selected-roles",
    label: "Selected Roles",
    color: "var(--stm-classify-divergent)",
    explanation: "Software selects one mutually exclusive socket role after target identity.",
  },
  {
    type: "critical-role-island",
    label: "Critical Isolation",
    color: "var(--c-err)",
    explanation: "Conflicting critical roles remain independently isolated and default open.",
  },
  {
    type: "passive-compatible-lane",
    label: "Passive-Compatible Lane",
    color: "var(--stm-debug)",
    explanation:
      "Weak bias and open-drain control preserve reset or boot behavior without switching the signal lane.",
  },
  {
    type: "shared-analog-network",
    label: "Shared Analog Network",
    color: "var(--stm-analog)",
    explanation:
      "Compatible analog-supply and reference identities share one proven filtered rail.",
  },
  {
    type: "reserved-open",
    label: "Reserved Open",
    color: "var(--stm-nc)",
    explanation: "The position remains electrically isolated.",
  },
  {
    type: "optional-absent",
    label: "Optional Position",
    color: "var(--stm-classify-partial)",
    explanation: "The common architecture cannot depend on a position absent from some targets.",
  },
  {
    type: "fixed-direct",
    label: "Fixed Direct",
    color: "var(--stm-classify-shared)",
    explanation: "A proven direct path needs no configurable branch.",
  },
  {
    type: "high-integrity-path",
    label: "High-Integrity Path",
    color: "var(--stm-debug)",
    explanation: "Bandwidth or loading requires a dedicated path outside the general fabric.",
  },
  {
    type: "dedicated-analog-path",
    label: "Dedicated Analog",
    color: "var(--stm-analog)",
    explanation: "Leakage or analog accuracy requires a dedicated path.",
  },
];

const TOPOLOGY_BY_TYPE = new Map(
  TOPOLOGIES.map((topology) => [topology.type, topology]),
);

function percent(value: number): string {
  if (value === 100 || value === 0) return `${value}%`;
  if (value >= 10) return `${value.toFixed(1)}%`;
  return `${value.toFixed(2)}%`;
}

function maskIncludes(mask: string, index: number): boolean {
  try {
    return (BigInt(mask) & (1n << BigInt(index))) !== 0n;
  } catch {
    return false;
  }
}

function masksOverlap(left: string, right: string): boolean {
  try {
    return (BigInt(left) & BigInt(right)) !== 0n;
  } catch {
    return false;
  }
}

function profileLabel(id: string): string {
  const suffix = id.replace(/^cohort-/, "");
  return `Profile ${suffix}`;
}

function mapPosition(position: SocketSolutionPosition): TargetDefinitionPosition {
  return {
    position: position.position,
    position_kind: position.position_kind,
    lqfp_side: position.lqfp_side,
    bga_row: position.bga_row,
    bga_col: position.bga_col,
    silicon_class: position.controlled
      ? "safety_collision"
      : position.cell_type === "optional-absent"
        ? "partial"
        : position.cell_type === "universal-io"
          ? "stable_io"
          : "fixed_critical",
    board_action: position.controlled
      ? "selectable"
      : position.cell_type === "reserved-open"
        ? "isolate"
        : "direct",
    universal_primitive: position.cell_type,
    active_path_count: position.branches.filter((branch) => branch.controlled).length,
    passive_path_count: 0,
    identities: position.modes.map((mode) => mode.label),
    access_tags: [
      ...new Set(position.modes.flatMap((mode) => mode.access_tags)),
    ],
    access_tags_union: [
      ...new Set(position.modes.flatMap((mode) => mode.access_tags)),
    ],
    present_on: position.modes
      .filter((mode) => mode.kind !== "absent")
      .reduce((sum, mode) => sum + mode.target_count, 0),
    total_targets: position.modes.reduce(
      (sum, mode) => sum + mode.target_count,
      0,
    ),
    route_ids: [],
    hazard: position.hazard,
    per_target: [],
  };
}

function buildInstruction(position: SocketSolutionPosition): string {
  if (position.cell_type === "passive-compatible-lane") {
    return "Use one direct bidirectional lane. Add only weak bias and open-drain control; keep any capacitive load optional or isolated. No signal switch is required after the loading proof passes.";
  }
  if (position.cell_type === "shared-analog-network") {
    return "Connect this position to one filtered common analog rail with its required local decoupling. Provide an open option only when an independent external reference is needed.";
  }
  if (position.cell_type === "universal-io") {
    return "Connect this socket node to one bidirectional universal signal lane and a high-impedance observation point. MCU alternate functions remain software-selected.";
  }
  if (position.cell_type === "fixed-network") {
    const mode = position.modes.find((candidate) => candidate.conductive);
    return mode
      ? `Connect this position to the fixed ${mode.label.toLowerCase()} network required by every selected target.`
      : "Keep this position isolated.";
  }
  if (position.controlled) {
    return `Create ${position.branches.length} mutually exclusive branches from the socket node. All branches default open. Enable only the branch allowed for the identified target.`;
  }
  if (position.cell_type === "reserved-open") {
    return "Leave this socket position electrically open. Observation must remain non-conductive.";
  }
  return "Do not make the common architecture depend on this position. Offer only an optional target-specific connection.";
}

function filterLabel(filter: PositionFilter): string {
  const labels: Record<PositionFilter, string> = {
    all: "All Positions",
    direct: "Direct",
    configurable: "Configurable",
    mixed: "Mixed Roles",
    critical: "Critical Hazards",
    proof: "Open Verification",
  };
  return labels[filter];
}

export function SocketSolutionPanel({
  solution,
}: {
  solution: SocketSolutionDTO;
}) {
  const [selectedPosition, setSelectedPosition] = useState<string | null>(
    solution.positions.find((position) => position.controlled)?.position ??
      solution.positions[0]?.position ??
      null,
  );
  const [search, setSearch] = useState("");
  const [filter, setFilter] = useState<PositionFilter>("all");
  const [topology, setTopology] = useState<string | null>(null);
  const [detailView, setDetailView] = useState<DetailView>("configurations");
  const [cohortSearch, setCohortSearch] = useState("");
  const [selectedCohortId, setSelectedCohortId] = useState<string | null>(null);
  const panelLabel = useText(
    "stm.socket.panel.aria",
    "Universal STM Socket Solution",
  );
  const searchPlaceholder = useText(
    "stm.socket.search.placeholder",
    "Find Position, Role, Function, MCU",
  );
  const searchLabel = useText("stm.socket.search.aria", "Filter Socket Solution");
  const clearCohortLabel = useText(
    "stm.socket.cohort.clear.aria",
    "Clear Active Configuration",
  );

  useEffect(() => {
    setSelectedPosition(
      solution.positions.find((position) => position.controlled)?.position ??
        solution.positions[0]?.position ??
        null,
    );
    setSearch("");
    setFilter("all");
    setTopology(null);
    setDetailView("configurations");
    setCohortSearch("");
    setSelectedCohortId(null);
  }, [solution.artifact_digest, solution.positions]);

  const mappedPositions = useMemo(
    () => solution.positions.map(mapPosition),
    [solution.positions],
  );
  const byPosition = useMemo(
    () =>
      new Map(
        solution.positions.map((position) => [position.position, position]),
      ),
    [solution.positions],
  );
  const proofPositions = useMemo(
    () => new Set(solution.proofs.map((proof) => proof.position)),
    [solution.proofs],
  );
  const selected = selectedPosition
    ? byPosition.get(selectedPosition) ?? null
    : null;
  const selectedCohort =
    solution.target_cohorts.find((cohort) => cohort.id === selectedCohortId) ??
    null;
  const cohortMembers = useMemo(
    () =>
      new Map(
        solution.target_cohorts.map((cohort) => [
          cohort.id,
          solution.scope.target_index
            .filter((target) => maskIncludes(cohort.target_mask, target.index))
            .map((target) => target.ref),
        ]),
      ),
    [solution.scope.target_index, solution.target_cohorts],
  );
  const matchingTargetIndices = useMemo(() => {
    const needle = search.trim().toLowerCase();
    if (!needle) return [];
    return solution.scope.target_index
      .filter((target) =>
        [target.ref, target.family, target.line].some((value) =>
          value.toLowerCase().includes(needle),
        ),
      )
      .map((target) => target.index);
  }, [search, solution.scope.target_index]);

  const matches = (position: SocketSolutionPosition): boolean => {
    const needle = search.trim().toLowerCase();
    const textMatch = [
        position.position,
        position.cell_label,
        position.cell_type,
        position.hazard_contract.label,
        position.hazard_contract.category,
        ...position.modes.flatMap((mode) => [
          mode.label,
          ...mode.functions,
          ...mode.access_tags,
          ...mode.target_examples,
        ]),
      ].some((value) => value.toLowerCase().includes(needle));
    const targetMatch =
      matchingTargetIndices.length > 0 &&
      position.modes.some((mode) =>
        matchingTargetIndices.some((index) => maskIncludes(mode.target_mask, index)),
      );
    if (needle && !textMatch && !targetMatch) {
      return false;
    }
    if (topology && position.cell_type !== topology) return false;
    if (filter === "direct" && position.controlled) return false;
    if (filter === "configurable" && !position.controlled) return false;
    if (filter === "mixed" && position.mode_count < 2) return false;
    if (filter === "critical" && position.hazard_contract.level !== "critical") {
      return false;
    }
    if (filter === "proof" && !proofPositions.has(position.position)) return false;
    return true;
  };

  const matchingCount = solution.positions.filter(matches).length;
  const visuals = useMemo(() => {
    const result: Record<string, TargetMapPositionVisual> = {};
    for (const position of solution.positions) {
      const spec = TOPOLOGY_BY_TYPE.get(position.cell_type);
      const hazardLevel = position.hazard_contract.level;
      result[position.position] = {
        fill: spec?.color ?? "var(--c-line2)",
        stroke:
          hazardLevel === "critical"
            ? "var(--c-err)"
            : hazardLevel === "high" || proofPositions.has(position.position)
              ? "var(--c-warn)"
              : undefined,
        dashed: position.cell_type === "optional-absent",
        marker: position.mode_count,
        agreement: position.agreement_percentage,
        active: Boolean(selectedCohort && position.controlled),
        hazard:
          hazardLevel === "critical" || hazardLevel === "high" || hazardLevel === "medium"
            ? hazardLevel
            : undefined,
        description: `${position.cell_label} · ${position.mode_count} ${
          position.mode_count === 1 ? "Mode" : "Modes"
        } · ${percent(position.agreement_percentage)} Agreement${
          selectedCohort
            ? ` · ${
                position.modes.find((mode) =>
                  masksOverlap(mode.target_mask, selectedCohort.target_mask),
                )?.label ?? "Open"
              } For ${profileLabel(selectedCohort.id)}`
            : ""
        }`,
      };
    }
    return result;
  }, [proofPositions, selectedCohort, solution.positions]);

  const topologyCounts = useMemo(
    () =>
      TOPOLOGIES.map((spec) => ({
        ...spec,
        count: solution.positions.filter(
          (position) => position.cell_type === spec.type,
        ).length,
      })).filter((spec) => spec.count > 0),
    [solution.positions],
  );

  const selectCell = (cell: SocketSupportCell) => {
    setTopology((current) => (current === cell.type ? null : cell.type));
    if (cell.positions[0]) setSelectedPosition(cell.positions[0]);
  };

  const visibleCohorts = useMemo(() => {
    const needle = cohortSearch.trim().toLowerCase();
    if (!needle) return solution.target_cohorts;
    return solution.target_cohorts.filter((cohort) =>
      [
        cohort.id,
        ...cohort.families,
        ...(cohortMembers.get(cohort.id) ?? []),
      ].some((value) => value.toLowerCase().includes(needle)),
    );
  }, [cohortMembers, cohortSearch, solution.target_cohorts]);

  return (
    <section
      data-dev-id="stm.socket-solution"
      data-testid="socket-solution"
      className="flex min-h-0 flex-1 flex-col"
      aria-label={panelLabel}
    >
      <header className="flex flex-none items-center gap-5 border-b border-line px-4 py-2.5">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-baseline gap-2">
            <h2 className="font-mono text-sm font-semibold text-t1">
              {solution.scope.package} Socket Solution
            </h2>
            <Badge
              size="sm"
              tone={
                solution.closure.zero_omission
                  ? "ok"
                  : "err"
              }
            >
              {solution.closure.zero_omission
                ? `Supports ${solution.closure.supported_target_count}/${solution.summary.target_count}`
                : `${solution.closure.unsupported_target_count} Unsupported`}
            </Badge>
            {solution.closure.release !== "ready" ? (
              <Badge size="sm" tone="warn">
                <Text id="stm.socket.verification-open">Verification Open</Text>
              </Badge>
            ) : null}
          </div>
          <p className="mt-0.5 truncate text-xs text-t3">
            Any selected target uses this socket after its{" "}
            {solution.summary.target_cohort_count.toLocaleString()}-profile configuration
            is applied and verified
            {solution.bootstrap.status === "requires-declared-target"
              ? " before target power"
              : ""}
            .
          </p>
        </div>
        <Metric
          value={percent(solution.closure.target_coverage_percentage)}
          label="Targets Covered"
        />
        <Metric
          value={String(solution.summary.target_cohort_count)}
          label="Target Profiles"
        />
        <Metric
          value={String(solution.summary.critical_hazard_positions)}
          label="Critical Hazards"
        />
        <Metric
          value={String(solution.summary.proof_open_positions)}
          label="Verification Open"
        />
      </header>
      <ClosureGateStrip solution={solution} />

      <div className="flex flex-none items-center gap-2 border-b border-line px-3 py-2">
        <input
          value={search}
          onChange={(event) => setSearch(event.target.value)}
          placeholder={searchPlaceholder}
          aria-label={searchLabel}
          className="min-w-52 flex-1 rounded-control bg-field px-2.5 py-1.5 text-xs text-t1 outline-none placeholder:text-t3"
        />
        {(
          [
            "all",
            "direct",
            "configurable",
            "mixed",
            "critical",
            "proof",
          ] as PositionFilter[]
        ).map((item) => (
            <button
              key={item}
              type="button"
              aria-pressed={filter === item}
              onClick={() => setFilter(item)}
              className={
                "rounded-control border px-2 py-1 text-xs " +
                (filter === item
                  ? "border-acc bg-acc-soft text-t1"
                  : "border-line text-t2 hover:text-t1")
              }
            >
              {filterLabel(item)}
            </button>
          ))}
        <span className="tnum min-w-14 text-right font-mono text-xs text-t3">
          {matchingCount}/{solution.positions.length}
        </span>
      </div>

      <div className="flex flex-none flex-wrap items-stretch gap-1 border-b border-line px-3 py-1.5">
        {topologyCounts.map((item) => {
          const active = topology === item.type;
          return (
            <button
              key={item.type}
              type="button"
              aria-pressed={active}
              title={`${item.explanation} ${item.count} of ${solution.positions.length} positions.`}
              onClick={() => setTopology(active ? null : item.type)}
              className={
                "flex min-w-fit items-center gap-2 rounded-control border px-2 py-1.5 text-left " +
                (active
                  ? "border-acc bg-acc-soft"
                  : "border-line bg-raise hover:border-line2")
              }
            >
              <span
                className="h-2.5 w-2.5 flex-none rounded-sm"
                style={{ backgroundColor: item.color }}
              />
              <span>
                <span className="block text-xs text-t1">{item.label}</span>
                <span className="block font-mono text-2xs text-t3">
                  {item.count} ·{" "}
                  {percent((item.count / solution.positions.length) * 100)}
                </span>
              </span>
            </button>
          );
        })}
        <div className="ml-auto flex min-w-fit items-center gap-3 px-2 text-2xs text-t3">
          <span>
            <span className="mr-1 inline-block h-2 w-2 border border-err bg-err/10" />
            Red Cross = Critical Collision
          </span>
          <span>
            <span className="mr-1 inline-block h-2 w-2 border border-warn" />
            Amber Outline = Isolated Or Open
          </span>
          <span>Inset Bar = Target Share</span>
          <span>Blue Center = Selected Profile</span>
        </div>
      </div>
      {topology || selectedCohort ? (
        <div className="flex flex-none items-center gap-3 border-b border-line bg-raise px-3 py-1.5 text-xs">
          {topology ? (
            <>
              <span className="font-medium text-t1">
                {TOPOLOGY_BY_TYPE.get(topology as SocketSolutionPosition["cell_type"])?.label}
              </span>
              <span className="min-w-0 flex-1 truncate text-t3">
                {TOPOLOGY_BY_TYPE.get(topology as SocketSolutionPosition["cell_type"])?.explanation}
              </span>
            </>
          ) : (
            <span className="min-w-0 flex-1 text-t3">
              <Text id="stm.socket.cohort.hint">
                Blue center marks show the configurable positions applied by the selected target
                cohort.
              </Text>
            </span>
          )}
          {selectedCohort ? (
            <button
              type="button"
              onClick={() => setSelectedCohortId(null)}
              className="flex min-w-fit items-center gap-2 rounded-control border border-acc bg-acc-soft px-2 py-1 text-t1"
              aria-label={clearCohortLabel}
            >
              <span className="font-mono">{profileLabel(selectedCohort.id)}</span>
              <span>{selectedCohort.target_count.toLocaleString()} MCUs</span>
              <span aria-hidden="true">×</span>
            </button>
          ) : null}
        </div>
      ) : null}

      <div className="grid min-h-0 flex-1 grid-cols-[minmax(0,1fr)_360px]">
        <div className="flex min-h-0 min-w-0 flex-col p-3">
          <TargetPackageMap
            packageName={solution.scope.package}
            positions={mappedPositions}
            lens="board"
            positionVisuals={visuals}
            positionMatches={(position) => {
              const contract = byPosition.get(position.position);
              return contract ? matches(contract) : false;
            }}
            selectedPosition={selectedPosition}
            onSelectPosition={setSelectedPosition}
          />
        </div>

        <aside className="flex min-h-0 flex-col border-l border-line bg-surface">
          {selected ? (
            <PositionSolution
              position={selected}
              totalTargets={solution.summary.target_count}
              proofNeeded={proofPositions.has(selected.position)}
              activeCohort={selectedCohort}
            />
          ) : (
            <div className="p-4 text-xs text-t3">
              <Text id="stm.socket.select-position">
                Select a package position.
              </Text>
            </div>
          )}

          <div className="flex min-h-0 flex-1 flex-col border-t border-line">
            <div className="grid flex-none grid-cols-3 border-b border-line">
              {(
                [
                  ["configurations", "Target Profiles"],
                  ["cells", "Circuit Cells"],
                  ["contract", "Safety And Proof"],
                ] as [DetailView, string][]
              ).map(([view, label]) => (
                <button
                  key={view}
                  type="button"
                  aria-pressed={detailView === view}
                  onClick={() => setDetailView(view)}
                  className={
                    "border-b-2 px-2 py-2 text-2xs font-medium " +
                    (detailView === view
                      ? "border-acc text-t1"
                      : "border-transparent text-t3 hover:text-t1")
                  }
                >
                  {label}
                </button>
              ))}
            </div>
            {detailView === "configurations" ? (
              <ConfigurationList
                cohorts={visibleCohorts}
                members={cohortMembers}
                search={cohortSearch}
                onSearch={setCohortSearch}
                selectedId={selectedCohortId}
                onSelect={(cohort) =>
                  setSelectedCohortId((current) =>
                    current === cohort.id ? null : cohort.id,
                  )
                }
              />
            ) : detailView === "cells" ? (
              <SolutionGroupList cells={solution.support_cells} onSelect={selectCell} />
            ) : (
              <SafetyContract solution={solution} />
            )}
          </div>
        </aside>
      </div>
    </section>
  );
}

function ClosureGateStrip({ solution }: { solution: SocketSolutionDTO }) {
  const closureLabel = useText(
    "stm.socket.closure.aria",
    "Socket Support Closure",
  );
  return (
    <div
      className="grid flex-none grid-cols-5 border-b border-line bg-stage"
      aria-label={closureLabel}
    >
      {solution.closure.gates.map((gate) => (
        <div
          key={gate.id}
          className="min-w-0 border-r border-line px-3 py-2 last:border-r-0"
          title={gate.detail}
        >
          <div className="flex items-center justify-between gap-2">
            <span className="truncate text-2xs font-medium text-t2">{gate.label}</span>
            <span
              className={
                "h-1.5 w-1.5 flex-none rounded-full " +
                (gate.status === "pass"
                  ? "bg-ok"
                  : gate.status === "open"
                    ? "bg-warn"
                    : "bg-err")
              }
              aria-label={gate.status}
            />
          </div>
          <span
            className={
              "mt-0.5 block truncate font-mono text-xs " +
              (gate.status === "pass"
                ? "text-t1"
                : gate.status === "open"
                  ? "text-warn"
                  : "text-err")
            }
          >
            {gate.value}
          </span>
        </div>
      ))}
    </div>
  );
}

function Metric({ value, label }: { value: string; label: string }) {
  return (
    <div className="min-w-20 flex-none border-l border-line pl-4 text-right">
      <span className="block font-mono text-sm font-semibold text-t1">{value}</span>
      <span className="block text-2xs text-t3">{label}</span>
    </div>
  );
}

function ConfigurationList({
  cohorts,
  members,
  search,
  onSearch,
  selectedId,
  onSelect,
}: {
  cohorts: SocketTargetCohort[];
  members: Map<string, string[]>;
  search: string;
  onSearch: (value: string) => void;
  selectedId: string | null;
  onSelect: (cohort: SocketTargetCohort) => void;
}) {
  const cohortPlaceholder = useText(
    "stm.socket.cohort.search.placeholder",
    "Find MCU, Family, or Profile",
  );
  const cohortSearchLabel = useText(
    "stm.socket.cohort.search.aria",
    "Find Target Profile",
  );
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex-none p-2">
        <input
          value={search}
          onChange={(event) => onSearch(event.target.value)}
          placeholder={cohortPlaceholder}
          aria-label={cohortSearchLabel}
          className="w-full rounded-control bg-field px-2.5 py-1.5 text-xs text-t1 outline-none placeholder:text-t3"
        />
        <p className="mt-1.5 text-2xs leading-relaxed text-t3">
          <Text id="stm.socket.cohort.explanation">
            MCUs in one profile use the same branch state at every configurable socket position.
            Declare the installed MCU before target power.
          </Text>
        </p>
      </div>
      <div className="min-h-0 flex-1 space-y-1 overflow-y-auto px-2 pb-2">
        {cohorts.map((cohort) => {
          const active = cohort.id === selectedId;
          const targetRefs = members.get(cohort.id) ?? [];
          return (
            <button
              key={cohort.id}
              type="button"
              aria-pressed={active}
              onClick={() => onSelect(cohort)}
              className={
                "w-full rounded-control border px-2.5 py-2 text-left " +
                (active
                  ? "border-acc bg-acc-soft"
                  : "border-line bg-raise hover:border-line2")
              }
            >
              <span className="flex items-start justify-between gap-3">
                <span>
                  <span className="block font-mono text-xs font-semibold text-t1">
                    {profileLabel(cohort.id)}
                  </span>
                  <span className="mt-0.5 block text-2xs text-t3">
                    {cohort.families.join(" + ") || "Unclassified family"}
                  </span>
                </span>
                <span className="text-right">
                  <span className="block font-mono text-xs text-t1">
                    {cohort.target_count.toLocaleString()}
                  </span>
                  <span className="block font-mono text-2xs text-t3">
                    {percent(cohort.percentage)}
                  </span>
                </span>
              </span>
              <span className="mt-2 flex items-center justify-between gap-2 text-2xs">
                <span className="text-t2">
                  {Object.keys(cohort.configuration).length} Branch{" "}
                  {Object.keys(cohort.configuration).length === 1 ? "State" : "States"}
                </span>
                <span className="truncate font-mono text-t3">
                  {targetRefs.slice(0, 3).join(", ")}
                  {targetRefs.length > 3 ? "…" : ""}
                </span>
              </span>
            </button>
          );
        })}
        {!cohorts.length ? (
          <p className="px-2 py-4 text-center text-xs text-t3">
            <Text id="stm.socket.cohort.empty">
              No target configuration matches this search.
            </Text>
          </p>
        ) : null}
      </div>
    </div>
  );
}

function SolutionGroupList({
  cells,
  onSelect,
}: {
  cells: SocketSupportCell[];
  onSelect: (cell: SocketSupportCell) => void;
}) {
  return (
    <div className="min-h-0 flex-1 space-y-1 overflow-y-auto px-2 py-2">
      <p className="px-1 pb-1 text-2xs leading-relaxed text-t3">
        <Text id="stm.socket.cells.explanation">
          Positions in one group share the same electrical behavior and can reuse one proven
          circuit pattern.
        </Text>
      </p>
      {cells.map((cell) => (
        <button
          key={cell.id}
          type="button"
          onClick={() => onSelect(cell)}
          className="w-full rounded-control border border-line bg-raise px-2.5 py-2 text-left hover:border-line2"
        >
          <span className="flex items-start gap-2">
            <span
              className="mt-0.5 h-3 w-3 flex-none rounded-sm"
              style={{
                backgroundColor:
                  TOPOLOGY_BY_TYPE.get(cell.type)?.color ?? "var(--c-line2)",
              }}
            />
            <span className="min-w-0 flex-1">
              <span className="flex items-center justify-between gap-2">
                <span className="truncate text-xs font-medium text-t1">{cell.label}</span>
                <span className="font-mono text-2xs text-t3">{cell.position_count}</span>
              </span>
              <span className="mt-0.5 block truncate font-mono text-2xs text-t3">
                Positions {cell.positions.join(", ")}
              </span>
              <span className="mt-1 block text-2xs text-t2">
                {cell.controlled
                  ? `${cell.mode_count} modes · Default open · Readback required`
                  : "No configurable branch"}
              </span>
            </span>
          </span>
        </button>
      ))}
    </div>
  );
}

function SafetyContract({ solution }: { solution: SocketSolutionDTO }) {
  const transitions = [
    ["Unknown Target", solution.safe_state_contract.unknown_target],
    ["Controller Startup", solution.safe_state_contract.controller_startup],
    ["Target Change", solution.safe_state_contract.target_change],
    ["Identity Mismatch", solution.safe_state_contract.identity_mismatch],
  ].filter((entry): entry is [string, string] => Boolean(entry[1]));
  const missingRequirements = solution.closure.required_requirement_coverage.filter(
    (requirement) => requirement.status === "fail",
  );
  const siliconLimitedRequirements =
    solution.closure.required_requirement_coverage.filter(
      (requirement) => requirement.missing_targets.length > 0,
    );
  const orderingWarnings = solution.status.warnings.filter((warning) =>
    warning.includes("verified ordering MPN"),
  );
  const sourceMessages = [...solution.status.blockers, ...solution.status.warnings].filter(
    (message) => !message.includes("verified ordering MPN"),
  );
  return (
    <div className="min-h-0 flex-1 overflow-y-auto p-3">
      <Eyebrow>
        <Text id="stm.socket.safety.identity-startup">Identity And Startup</Text>
      </Eyebrow>
      <div className="mt-1.5 rounded-control border border-line bg-raise p-2.5">
        <div className="flex items-center justify-between gap-3">
          <span className="text-xs font-medium text-t1">
            {solution.bootstrap.status === "automatic"
              ? "Common Debug Bootstrap"
              : "Declared Target Required"}
          </span>
          <Badge size="sm" tone={solution.bootstrap.status === "automatic" ? "ok" : "warn"}>
            {solution.bootstrap.status === "automatic" ? "Automatic" : "Gated"}
          </Badge>
        </div>
        <p className="mt-1 text-2xs leading-relaxed text-t3">{solution.bootstrap.rule}</p>
      </div>
      <Eyebrow className="mt-4 block">
        <Text id="stm.socket.safety.safe-states">Mandatory Safe States</Text>
      </Eyebrow>
      <div className="mt-1.5 divide-y divide-line rounded-control border border-line bg-stage">
        {transitions.map(([label, value]) => (
          <div key={label} className="grid grid-cols-[110px_1fr] gap-2 px-2.5 py-2 text-2xs">
            <span className="text-t2">{label}</span>
            <span className="font-mono text-t1">{value.replaceAll("-", " ")}</span>
          </div>
        ))}
      </div>
      <Eyebrow className="mt-4 block">
        <Text id="stm.socket.safety.interlocks">Mandatory Interlocks</Text>
      </Eyebrow>
      <div className="mt-1.5 grid grid-cols-2 gap-1">
        {solution.fabric.mandatory_interlocks.map((interlock) => (
          <div
            key={interlock}
            className="rounded-control border border-line bg-stage px-2 py-1.5 text-2xs leading-relaxed text-t2"
          >
            {interlock}
          </div>
        ))}
      </div>

      <Eyebrow className="mt-4 block">
        <Text id="stm.socket.safety.closure">Closure</Text>
      </Eyebrow>
      <div className="mt-1.5 space-y-1.5">
        {solution.closure.configuration_errors.length ? (
          <EvidenceSummary
            tone="err"
            title={`${solution.closure.configuration_errors.length} Configuration Errors`}
            detail="At least one selected target does not resolve to exactly one safe socket state."
            items={solution.closure.configuration_errors.map(
              (error) =>
                `${error.target} · Position ${error.position || "scope"} · ${error.reason}`,
            )}
          />
        ) : (
          <EvidenceSummary
            tone="ok"
            title={`${solution.closure.supported_target_count}/${solution.summary.target_count} Targets Covered`}
            detail="Every selected target resolves to one complete configuration profile."
            items={[]}
          />
        )}
        {missingRequirements.length ? (
          <EvidenceSummary
            tone="err"
            title={`${missingRequirements.length} Required Access Gaps`}
            detail="These required functions are not available on every selected target."
            items={missingRequirements.map(
              (requirement) =>
                `${requirement.label}: ${requirement.covered_targets}/${
                  requirement.available_target_count
                } available targets · Socket missing ${
                  requirement.architecture_missing_targets.slice(0, 6).join(", ")
                }${
                  requirement.architecture_missing_targets.length > 6 ? "…" : ""
                }`,
            )}
          />
        ) : null}
        {siliconLimitedRequirements.length ? (
          <EvidenceSummary
            tone="warn"
            title={`${siliconLimitedRequirements.length} Silicon Capability Limits`}
            detail="The socket routes every available function; these MCU variants do not expose the function itself."
            items={siliconLimitedRequirements.map(
              (requirement) =>
                `${requirement.label}: available on ${requirement.available_target_count}/${
                  requirement.target_count
                } targets · Not exposed by ${requirement.missing_targets
                  .slice(0, 6)
                  .join(", ")}${requirement.missing_targets.length > 6 ? "…" : ""}`,
            )}
          />
        ) : null}
        {solution.proofs.length ? (
          <EvidenceSummary
            tone="warn"
            title={`${solution.summary.proof_open_positions} Positions Need Electrical Verification`}
            detail="The socket architecture covers these positions, but their exact electrical limits remain open."
            items={solution.proofs.map(
              (proof) =>
                `Position ${proof.position}: ${proof.checks.join(", ") || proof.failure_action}`,
            )}
          />
        ) : null}
        {orderingWarnings.length ? (
          <EvidenceSummary
            tone="warn"
            title={`${orderingWarnings.length} Target Masks Need Ordering MPNs`}
            detail="The architecture covers the indexed silicon masks; exact purchasable order codes remain unverified."
            items={orderingWarnings}
          />
        ) : null}
        {sourceMessages.length ? (
          <EvidenceSummary
            tone="warn"
            title={`${sourceMessages.length} Source Findings`}
            detail="Detailed target-definition findings retained for audit."
            items={sourceMessages}
          />
        ) : null}
      </div>
    </div>
  );
}

function EvidenceSummary({
  tone,
  title,
  detail,
  items,
}: {
  tone: "ok" | "warn" | "err";
  title: string;
  detail: string;
  items: string[];
}) {
  return (
    <details
      className={
        "rounded-control border-l-2 bg-raise " +
        (tone === "ok"
          ? "border-ok"
          : tone === "warn"
            ? "border-warn"
            : "border-err")
      }
    >
      <summary className="cursor-pointer list-none px-2.5 py-2">
        <span className="block text-xs font-medium text-t1">{title}</span>
        <span className="mt-0.5 block text-2xs leading-relaxed text-t3">{detail}</span>
      </summary>
      {items.length ? (
        <div className="max-h-48 space-y-1 overflow-y-auto border-t border-line px-2.5 py-2">
          {items.map((item) => (
            <p key={item} className="text-2xs leading-relaxed text-t2">
              {item}
            </p>
          ))}
        </div>
      ) : null}
    </details>
  );
}

function PositionSolution({
  position,
  totalTargets,
  proofNeeded,
  activeCohort,
}: {
  position: SocketSolutionPosition;
  totalTargets: number;
  proofNeeded: boolean;
  activeCohort: SocketTargetCohort | null;
}) {
  const activeMode = activeCohort
    ? position.modes.find((mode) =>
        masksOverlap(mode.target_mask, activeCohort.target_mask),
      ) ?? null
    : null;
  const activeBranchId = activeCohort?.configuration[position.position] ?? null;
  const activeBranch = position.branches.find((branch) => branch.id === activeBranchId) ?? null;
  return (
    <div className="max-h-[54%] flex-none overflow-y-auto p-3">
      <div className="flex items-start justify-between gap-3">
        <div>
          <Eyebrow>
            <Text id="stm.socket.position.physical">Physical Position</Text>
          </Eyebrow>
          <h3 className="mt-1 font-mono text-base font-semibold text-t1">
            {position.position}
          </h3>
        </div>
        <div className="text-right">
          <span className="block text-xs font-medium text-t1">
            {position.cell_label}
          </span>
          <span className="block font-mono text-2xs text-t3">
            {position.agreement_count}/{totalTargets} ·{" "}
            {percent(position.agreement_percentage)}
          </span>
        </div>
      </div>

      {activeCohort ? (
        <div className="mt-3 rounded-control border border-acc bg-acc-soft px-3 py-2">
          <div className="flex items-center justify-between gap-2">
            <span className="text-xs font-semibold text-t1">
              {activeMode?.label ?? "Open"}
            </span>
            <span className="font-mono text-2xs text-t3">
              {profileLabel(activeCohort.id)}
            </span>
          </div>
          <p className="mt-0.5 text-2xs text-t2">
            {activeBranch
              ? `Enable ${activeBranch.label}. Every other branch at this position remains open.`
              : position.controlled
                ? "No branch closes at this position for the active configuration."
                : "This position is fixed and does not change with the active configuration."}
          </p>
        </div>
      ) : null}

      <div
        className={
          "mt-3 rounded-control border-l-2 bg-raise px-3 py-2 " +
          (proofNeeded ? "border-warn" : "border-ok")
        }
      >
        <span className="text-xs font-semibold text-t1">
          <Text id="stm.socket.position.build-this">Build This</Text>
        </span>
        <p className="mt-1 text-xs leading-relaxed text-t2">
          {buildInstruction(position)}
        </p>
        {position.solution_reason ? (
          <p className="mt-1.5 border-t border-line pt-1.5 text-2xs leading-relaxed text-t3">
            {position.solution_reason}
          </p>
        ) : null}
      </div>

      {position.network_requirements.length ? (
        <div className="mt-3">
          <Eyebrow>
            <Text id="stm.socket.position.circuit-contract">
              Circuit Contract
            </Text>
          </Eyebrow>
          <div className="mt-1.5 flex flex-wrap gap-1">
            {position.network_requirements.map((requirement) => (
              <span
                key={requirement}
                className="rounded-control border border-line bg-stage px-2 py-1 text-2xs text-t2"
              >
                {requirement}
              </span>
            ))}
          </div>
        </div>
      ) : null}

      <div className="mt-3 flex items-center gap-2 text-2xs text-t3">
        <Badge size="sm" tone={position.controlled ? "warn" : "ok"}>
          {position.controlled ? "Software Selected" : "Fixed"}
        </Badge>
        {position.hazard_contract.level !== "none" ? (
          <Badge
            size="sm"
            tone={
              position.hazard_contract.level === "critical" ? "err" : "warn"
            }
          >
            {position.hazard_contract.label}
          </Badge>
        ) : null}
        <span>Safe Default: {position.safe_default === "open" ? "Open" : "Connected"}</span>
        {position.observation_node ? (
          <span>
            <Text id="stm.socket.position.observation-node">
              Observation Node
            </Text>
          </span>
        ) : null}
      </div>

      <div className="mt-3">
        <Eyebrow>
          <Text id="stm.socket.position.universal-cell">Universal Cell</Text>
        </Eyebrow>
        <p className="mt-1 text-xs leading-relaxed text-t2">
          {position.cell_contract.architecture ===
          "fail-closed-universal-position-cell"
            ? "A fail-closed cell selects exactly one target-approved electrical plane."
            : "One common network is valid across the selected targets."}
        </p>
        <div className="mt-1.5 flex flex-wrap gap-1">
          {position.cell_contract.planes.map((plane) => (
            <span
              key={plane.id}
              title={plane.requirements.join(". ")}
              className="rounded-control border border-line bg-stage px-2 py-1 font-mono text-2xs text-t2"
            >
              {plane.id.replaceAll("-", " ")}
            </span>
          ))}
        </div>
        {position.controlled ? (
          <p className="mt-1.5 text-2xs leading-relaxed text-t3">
            <Text id="stm.socket.position.interlock-summary">
              Hardware one-hot · Break before make · State readback · Fault opens all
            </Text>
          </p>
        ) : null}
      </div>

      <div className="mt-3 space-y-1.5">
        {position.modes.map((mode) => (
          <div
            key={mode.id}
            className={
              "rounded-control border px-2.5 py-2 " +
              (activeMode?.id === mode.id
                ? "border-acc bg-acc-soft"
                : "border-line bg-stage")
            }
          >
            <div className="flex items-center justify-between gap-2">
              <span className="text-xs font-medium text-t1">{mode.label}</span>
              <span className="font-mono text-2xs text-t3">
                {mode.target_count}/{totalTargets} · {percent(mode.percentage)}
              </span>
            </div>
            <p className="mt-0.5 text-2xs text-t3">
              {mode.conductive
                ? `Connects to ${mode.endpoint.replace("fixed:", "").replace("-", " ")}`
                : "No conductive branch"}
            </p>
            {mode.target_examples.length ? (
              <p className="mt-1 truncate font-mono text-2xs text-t3">
                {mode.target_examples.join(", ")}
                {mode.target_count > mode.target_examples.length ? "…" : ""}
              </p>
            ) : null}
          </div>
        ))}
      </div>

      {position.branches.length ? (
        <div className="mt-3">
          <Eyebrow>
            <Text id="stm.socket.position.node-topology">
              Socket Node Topology
            </Text>
          </Eyebrow>
          <div className="mt-1.5 flex items-center gap-1 overflow-x-auto rounded-control border border-line bg-stage p-2">
            <span className="min-w-fit rounded-control bg-raise px-2 py-1 font-mono text-2xs text-t1">
              Socket {position.position}
            </span>
            <span className="text-t3">→</span>
            <div className="min-w-0 flex-1 space-y-1">
              {position.branches.map((branch) => (
                <div
                  key={branch.id}
                  className={
                    "flex items-center gap-1 rounded-control font-mono text-2xs " +
                    (activeBranch?.id === branch.id ? "bg-acc-soft" : "")
                  }
                >
                  <span
                    className={
                      "rounded-control px-1.5 py-0.5 " +
                      (branch.controlled
                        ? "bg-warn/10 text-warn"
                        : "bg-ok/10 text-ok")
                    }
                  >
                    {branch.controlled ? "SELECT" : "DIRECT"}
                  </span>
                  <span className="truncate text-t2">{branch.label}</span>
                  <span className="text-t3">→ {branch.endpoint}</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
