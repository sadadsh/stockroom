/**
 * CompatibilityWorkbench - the Bench: a generic STM socket-solution workbench.
 * Pick a scope (families + one package) and the Bench derives an explicit device
 * set, then compiles it with the caller-owned policy:
 *
 * - The package chips are the UNION of the selected families' packages, each showing its family
 *   coverage (n/m when a family lacks it); building a set uses the covered families only, so an
 *   unsupported family is visible, never silently dropped. A filter row keeps the grid tame.
 * - The compatible sets (the suggestion groups) compute automatically and render as a stepper:
 *   All Parts, then Baseline, then each divergent group. Stepping auto-unions that set - the
 *   goal is every MCU in scope belonging to a set you can walk through.
 * - Each set compiles a content-addressed socket solution. Unique electrical modes,
 *   reusable support cells, target cohorts, and proof obligations remain distinct.
 * - Raw socket-union similarity and AF checks stay available as evidence, but
 *   do not dictate hardware switching.
 * - Export separates reproducible compiler input, signed solution authority,
 *   physical-position closure, control states, reusable cells, and proof closure.
 *
 * Still software/informational only: a swap is shown, never applied; nothing is persisted
 * client-side (CONTEXT decisions 4 and 8 unchanged).
 */
import { useEffect, useMemo, useRef, useState } from "react";
import {
  useStmCompatUnion,
  useStmFamilies,
  useStmSocketSolution,
  useStmSuggestions,
} from "../../api/stmQueries";
import { instanceDevId } from "../../lib/componentDevIds";
import { ApiError } from "../../api/client";
import { AdaptiveChoice } from "../AdaptiveChoice";
import type {
  CompatUnionBody,
  SuggestionGroupDTO,
  TargetDefinitionBody,
  TargetDefinitionPolicy,
  UnionDTO,
} from "../../api/types";
import type { StmScope } from "../../pages/StmViewerPage";
import { FamilyPicker } from "./FamilyPicker";
import { CompatUnionMap } from "./CompatUnionMap";
import { BenchPartModal } from "./BenchPartModal";
import { BuildIndexGate } from "./BuildIndexGate";
import { AfCheckPanel } from "./AfCheckPanel";
import { SocketSolutionPanel } from "./SocketSolutionPanel";
import {
  cloneCoreBringUpPolicy,
  TargetPolicyEditor,
} from "./TargetPolicyEditor";
import { Button, ErrorState, Eyebrow } from "../primitives";
import { Text, useCopyFormatter, useText } from "../../lib/copy";
import { downloadTextFile } from "../../lib/stmTargetExport";
import {
  stmSocketExport,
  stmSocketExportFilename,
  type StmSocketExportKind,
} from "../../lib/stmSocketSolutionExport";

// ── scope helpers (pure, tested) ─────────────────────────────────────────────

export interface PackageOption {
  name: string;
  /** the selected families that DO offer this package */
  covered: string[];
  /** the selected families that do NOT offer it (visible, never silently dropped) */
  missing: string[];
}

// The union of packages across the selected families, each with its coverage - the owner call
// superseding the earlier intersection (which hid every package any one family lacked).
export function packagesForScope(
  families: { family: string; packages: string[] }[],
  selected: string[],
): PackageOption[] {
  const byName = new Map<string, PackageOption>();
  for (const name of selected) {
    const packages = families.find((f) => f.family === name)?.packages ?? [];
    for (const pkg of packages) {
      const entry = byName.get(pkg) ?? { name: pkg, covered: [], missing: [] };
      entry.covered.push(name);
      byName.set(pkg, entry);
    }
  }
  for (const entry of byName.values()) {
    entry.missing = selected.filter((f) => !entry.covered.includes(f));
  }
  return [...byName.values()].sort((a, b) =>
    a.name.localeCompare(b.name, undefined, { numeric: true }),
  );
}

// A package's kind for the filter chips (LQFP / QFN / BGA / CSP / Other).
export function packageKind(name: string): string {
  const n = name.toUpperCase();
  if (n.includes("CSP")) return "CSP";
  if (n.includes("BGA")) return "BGA";
  if (n.includes("QFN") || n.includes("QFPN") || n.includes("SON")) return "QFN";
  if (n.includes("QFP")) return "LQFP";
  return "Other";
}

const PACKAGE_KINDS = ["All", "LQFP", "QFN", "BGA", "CSP", "Other"] as const;

// One steppable set: the whole scope, a suggestion group, or the user's custom edit.
export interface BenchSet {
  id: string;
  label: string;
  refs: string[] | null; // null = the whole (families, package) scope
  tier?: "baseline" | "divergent";
  divergent?: number;
  count: number;
}

export function benchSets(groups: SuggestionGroupDTO[], scopeCount: number): BenchSet[] {
  const sets: BenchSet[] = [{ id: "all", label: "All Parts", refs: null, count: scopeCount }];
  let divergentIndex = 0;
  for (const g of groups) {
    const label =
      g.tier === "baseline" ? "Baseline" : `Divergent ${String.fromCharCode(65 + divergentIndex)}`;
    if (g.tier !== "baseline") divergentIndex += 1;
    sets.push({
      id: g.signature_id,
      label,
      refs: g.refs,
      tier: g.tier as "baseline" | "divergent",
      divergent: g.divergent_positions,
      count: g.refs.length,
    });
  }
  return sets;
}

// The project-agnostic export bundle: the scope, every set, and the active set's full union.
export function benchExport(
  scope: { families: string[]; package: string },
  sets: BenchSet[],
  union: UnionDTO,
): string {
  return JSON.stringify(
    {
      format: "stm-bench/1",
      purpose: "socket-union analysis",
      scope,
      sets: sets.map((s) => ({
        id: s.id,
        label: s.label,
        tier: s.tier ?? "scope",
        divergent_positions: s.divergent ?? 0,
        refs: s.refs,
        count: s.count,
      })),
      active_set: {
        parts: union.parts,
        resolved: union.resolved,
        package: union.package,
        families: union.families,
        verdict: union.verdict,
        positions: union.positions,
      },
    },
    null,
    2,
  );
}

// ── the Bench ────────────────────────────────────────────────────────────────

export function CompatibilityWorkbench() {
  const [scope, setScope] = useState<StmScope>({ families: [], mcus: [] });
  const [selectedPackage, setSelectedPackage] = useState<string | null>(null);
  const [pkgFilter, setPkgFilter] = useState("");
  const [pkgKind, setPkgKind] = useState<(typeof PACKAGE_KINDS)[number]>("All");
  const [activeSetId, setActiveSetId] = useState<string>("all");
  // A chip drop edits the active set into a custom one (auto-rebuilt, still explicit).
  const [customParts, setCustomParts] = useState<string[] | null>(null);
  const [openPart, setOpenPart] = useState<string | null>(null);
  const [policy, setPolicy] = useState<TargetDefinitionPolicy>(() =>
    cloneCoreBringUpPolicy(),
  );
  const [compiledRequest, setCompiledRequest] = useState<TargetDefinitionBody | null>(
    null,
  );
  const compileSequence = useRef(0);

  const families = useStmFamilies();
  const union = useStmCompatUnion();
  const socketSolution = useStmSocketSolution();

  const packageFilterLabel = useText("stm.compat.package-filter.placeholder", "Filter Packages");
  const previousSetLabel = useText("stm.compat.previous-set.aria", "Previous Set");
  const nextSetLabel = useText("stm.compat.next-set.aria", "Next Set");
  const targetSetControlLabel = useText("stm.compat.target-set-control.label", "Target Set");
  const unreachableLabel = useText("stm.compat.unreachable", "Cannot reach the Stockroom server.");
  const packageOfferedLabel = useText(
    "stm.compat.package-offered.title",
    "Offered by every selected family",
  );
  const packageMissingLabel = useCopyFormatter(
    "stm.compat.package-missing.title",
    "Not offered by {families}",
  );
  const customSetLabel = useCopyFormatter("stm.compat.custom-set.option", "Custom · {count}");

  const selectedFamilies = scope.families;
  const familiesKey = selectedFamilies.join(",");

  const packageOptions = useMemo(
    () => packagesForScope(families.data?.families ?? [], selectedFamilies),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [families.data, familiesKey],
  );
  const visiblePackages = useMemo(() => {
    const needle = pkgFilter.trim().toUpperCase();
    return packageOptions.filter(
      (p) =>
        (pkgKind === "All" || packageKind(p.name) === pkgKind) &&
        (!needle || p.name.toUpperCase().includes(needle)),
    );
  }, [packageOptions, pkgFilter, pkgKind]);

  const activeOption = packageOptions.find((p) => p.name === selectedPackage) ?? null;
  const coveredFamilies = useMemo(() => activeOption?.covered ?? [], [activeOption]);
  const coveredKey = coveredFamilies.join(",");

  // A scope change invalidates the chosen package and any set stepping.
  useEffect(() => {
    setSelectedPackage(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [familiesKey]);
  useEffect(() => {
    setActiveSetId("all");
    setCustomParts(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedPackage, coveredKey]);

  // The compatible sets compute automatically for the chosen scope (no button).
  const suggestions = useStmSuggestions(
    selectedPackage,
    coveredFamilies.length > 0 ? coveredFamilies.join(",") : null,
  );
  const scopeCount = useMemo(
    () => (suggestions.data?.groups ?? []).reduce((n, g) => n + g.refs.length, 0),
    [suggestions.data],
  );
  const sets = useMemo(
    () => benchSets(suggestions.data?.groups ?? [], scopeCount),
    [suggestions.data, scopeCount],
  );
  const activeSet = sets.find((s) => s.id === activeSetId) ?? sets[0];

  // The active set's union body - custom edit wins, then the set's refs, then the whole scope.
  const body: CompatUnionBody | null = useMemo(() => {
    if (!selectedPackage || coveredFamilies.length === 0) return null;
    if (customParts) return customParts.length >= 2 ? { parts: customParts } : null;
    if (activeSet?.refs) return { parts: activeSet.refs };
    return { families: coveredFamilies, package: selectedPackage };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedPackage, coveredKey, customParts, activeSet]);
  const bodyKey = useMemo(() => JSON.stringify(body), [body]);

  // Auto-union: the whole point of the redesign - stepping sets never asks for a rebuild.
  useEffect(() => {
    if (body) union.mutate(body);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [bodyKey]);

  const compileSolution = (request: TargetDefinitionBody) => {
    const sequence = ++compileSequence.current;
    setCompiledRequest(null);
    socketSolution.mutate(request, {
      onSuccess: () => {
        if (sequence === compileSequence.current) setCompiledRequest(request);
      },
    });
  };

  const definitionPartsKey = union.data?.parts.join("|") ?? "";
  const policyKey = useMemo(() => JSON.stringify(policy), [policy]);
  useEffect(() => {
    if (!union.data) return;
    const request = {
      parts: [...union.data.parts],
      policy: JSON.parse(JSON.stringify(policy)) as TargetDefinitionPolicy,
    };
    compileSolution(request);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [definitionPartsKey, policyKey]);

  const err = union.error;
  const indexNotBuilt =
    (err instanceof ApiError && err.status === 409) ||
    (suggestions.error instanceof ApiError && suggestions.error.status === 409) ||
    (socketSolution.error instanceof ApiError && socketSolution.error.status === 409);

  const stepTo = (id: string) => {
    setCustomParts(null);
    setActiveSetId(id);
  };
  const stepBy = (delta: number) => {
    const idx = sets.findIndex((s) => s.id === (customParts ? "all" : activeSetId));
    const next = sets[(idx + delta + sets.length) % sets.length];
    if (next) stepTo(next.id);
  };

  const exportActive = (kind: StmSocketExportKind) => {
    if (!socketSolution.data || !compiledRequest) return;
    const selected = stmSocketExport(
      socketSolution.data,
      compiledRequest.policy,
      kind,
    );
    downloadTextFile(
      stmSocketExportFilename(socketSolution.data, kind),
      selected.content,
      selected.type,
    );
  };

  return (
    <div data-dev-id="stm.bench" className="flex min-h-0 min-w-0 flex-1">
      {/* scope rail: families + the package grid (union with coverage, filterable) */}
      <div className="flex w-[220px] flex-none flex-col gap-2 overflow-hidden px-2 py-1">
        <div
          className={`min-h-0 ${
            selectedFamilies.length ? "order-2 flex-1" : "order-1 flex-1"
          }`}
        >
          <FamilyPicker scope={scope} onScopeChange={setScope} />
        </div>

        <div
          className={`flex min-h-0 flex-col border-line ${
            selectedFamilies.length
              ? "order-1 max-h-[44%] min-h-40 border-b pb-2"
              : "order-2 flex-none border-t pt-2"
          }`}
        >
          <Eyebrow className="mb-1.5 px-1">
            <Text id="stm.compat.package-title">Package</Text>
          </Eyebrow>
          {selectedFamilies.length === 0 ? (
            <p className="px-1 text-xs text-t3">
              <Text id="stm.compat.package-prompt">Select one or more families to see packages.</Text>
            </p>
          ) : (
            <div className="flex min-h-0 flex-1 flex-col gap-1.5">
              <input
                value={pkgFilter}
                onChange={(e) => setPkgFilter(e.target.value)}
                placeholder={packageFilterLabel}
                aria-label={packageFilterLabel}
                className="w-full rounded-control bg-field px-2 py-1 text-xs text-t1 outline-none placeholder:text-t3"
              />
              <div className="flex flex-wrap gap-0.5">
                {PACKAGE_KINDS.map((kind) => (
                  <button
                    key={kind}
                    type="button"
                    aria-pressed={pkgKind === kind}
                    onClick={() => setPkgKind(kind)}
                    className={
                      "rounded-control px-1.5 py-0.5 text-2xs " +
                      (pkgKind === kind ? "bg-acc-soft text-t1" : "text-t3 hover:text-t1")
                    }
                  >
                    {kind}
                  </button>
                ))}
              </div>
              {visiblePackages.length === 0 ? (
                <p className="px-1 text-xs text-t3">
                  <Text id="stm.compat.package-empty">No packages match this filter.</Text>
                </p>
              ) : (
                <div
                  className="grid min-h-0 grid-cols-2 gap-1 overflow-y-auto pr-0.5"
                  data-testid="bench-packages"
                >
                  {visiblePackages.map((p) => {
                    const active = selectedPackage === p.name;
                    const partial = p.missing.length > 0;
                    return (
                      <button
                        key={p.name}
                        type="button"
                        data-dev-id={instanceDevId("stm.package", p.name)}
                        data-dev-role="stm.package"
                        aria-pressed={active}
                        title={
                          partial
                            ? packageMissingLabel({ families: p.missing.join(", ") })
                            : packageOfferedLabel
                        }
                        onClick={() =>
                          setSelectedPackage((cur) => (cur === p.name ? null : p.name))
                        }
                        className={
                          "flex items-center justify-between gap-1 rounded-control border px-1.5 py-1 " +
                          (active
                            ? "border-acc bg-acc-soft text-t1"
                            : "border-line2 text-t2 hover:text-t1")
                        }
                      >
                        <span className="truncate font-mono text-xs">{p.name}</span>
                        {partial ? (
                          <span className="tnum flex-none font-mono text-2xs text-t3">
                            {p.covered.length}/{selectedFamilies.length}
                          </span>
                        ) : null}
                      </button>
                    );
                  })}
                </div>
              )}
            </div>
          )}
        </div>
      </div>

      {/* The package stays in view. Scope and advanced evidence scroll inside their own regions. */}
      <div className="flex min-w-0 flex-1 flex-col overflow-hidden border-l border-line">
        {indexNotBuilt ? (
          <BuildIndexGate />
        ) : !selectedPackage || coveredFamilies.length === 0 ? (
          <ChamberMessage>
            <Text id="stm.compat.scope-prompt">
              Pick families and a package. The Bench computes every compatible set for the scope.
            </Text>
          </ChamberMessage>
        ) : suggestions.isLoading ? (
          <ChamberMessage>
            <Text id="stm.compat.sets-loading">Computing the compatible sets...</Text>
          </ChamberMessage>
        ) : suggestions.isError ? (
          <ChamberMessage>
            <Text id="stm.compat.sets-failed">Could not compute the compatible sets.</Text>
          </ChamberMessage>
        ) : (
          <div className="flex min-h-0 flex-1 flex-col">
            <div
              className="flex flex-none items-center gap-2 border-b border-line px-3 py-1.5"
              data-testid="bench-stepper"
            >
              <Button small onClick={() => stepBy(-1)} aria-label={previousSetLabel}>
                ←
              </Button>
              <label className="flex min-w-0 items-center gap-2">
                <span className="text-xs text-t3">
                  <Text id="stm.compat.target-set-label">Target set</Text>
                </span>
                <AdaptiveChoice
                  devId="stm.target-set-control"
                  label={targetSetControlLabel}
                  value={customParts ? "custom" : activeSetId}
                  onChange={(next) => next !== "custom" && stepTo(next)}
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
              <Button small onClick={() => stepBy(1)} aria-label={nextSetLabel}>
                →
              </Button>
              <span className="min-w-0 flex-1 truncate font-mono text-2xs text-t3">
                <Text
                  id="stm.compat.scope-summary"
                  values={{
                    covered: activeOption?.covered.length ?? "",
                    total: selectedFamilies.length,
                    package: selectedPackage ?? "",
                  }}
                >
                  {"{covered}/{total} families · {package}"}
                </Text>
              </span>
              <ExportMenu
                disabled={
                  !socketSolution.data ||
                  !compiledRequest ||
                  socketSolution.isPending ||
                  socketSolution.isError
                }
                onExport={exportActive}
              />
            </div>

            {union.isPending ? (
              <ChamberMessage>
                <Text id="stm.compat.union-loading">Building the socket-union...</Text>
              </ChamberMessage>
            ) : err && !indexNotBuilt ? (
              <div className="flex flex-col items-center gap-3 py-16 text-center">
                <p className="text-sm text-err">
                  {err instanceof ApiError && err.status === 0 ? unreachableLabel : err.message}
                </p>
                <Button small onClick={() => body && union.mutate(body)}>
                  <Text id="stm.compat.union-retry">Try Again</Text>
                </Button>
              </div>
            ) : union.data ? (
              <div className="flex min-h-0 flex-1 flex-col">
                {socketSolution.isPending ? (
                  <ChamberMessage>
                    <Text id="stm.compat.solution-loading">Solving the universal socket...</Text>
                  </ChamberMessage>
                ) : socketSolution.error && !indexNotBuilt ? (
                  <div className="flex flex-col items-center gap-3 py-12 text-center">
                    <ErrorState dense id="stm.socket-failed">
                      The universal socket could not be solved.
                    </ErrorState>
                    <Button
                      small
                      onClick={() =>
                        union.data &&
                        compileSolution({
                          parts: [...union.data.parts],
                          policy: JSON.parse(JSON.stringify(policy)) as TargetDefinitionPolicy,
                        })
                      }
                    >
                      <Text id="stm.compat.solution-retry">Try Again</Text>
                    </Button>
                  </div>
                ) : socketSolution.data ? (
                  <SocketSolutionPanel solution={socketSolution.data} />
                ) : null}

                <details className="flex-none border-t border-line bg-surface">
                  <summary className="cursor-pointer px-4 py-2 text-xs text-t2">
                    <Text id="stm.compat.target-summary">Target set and policy</Text>
                  </summary>
                  <div className="max-h-[50vh] overflow-y-auto border-t border-line p-3">
                    <SetStrip
                      union={union.data}
                      onOpenPart={setOpenPart}
                      onDropPart={(ref) =>
                        setCustomParts(
                          (union.data ? union.data.parts : []).filter((p) => p !== ref),
                        )
                      }
                    />
                    <div className="mt-3">
                      <TargetPolicyEditor policy={policy} onPolicyChange={setPolicy} />
                    </div>
                    <details className="mt-3 border-t border-line pt-3">
                      <summary className="cursor-pointer text-xs text-t2">
                        <Text id="stm.compat.evidence-summary">
                          Raw silicon compatibility evidence
                        </Text>
                      </summary>
                      <div className="mt-3 flex flex-col gap-3">
                        <CompatUnionMap union={union.data} />
                        <AfCheckPanel union={union.data} />
                      </div>
                    </details>
                  </div>
                </details>
              </div>
            ) : null}
          </div>
        )}
      </div>

      {openPart ? <BenchPartModal part={openPart} onClose={() => setOpenPart(null)} /> : null}
    </div>
  );
}

// The set strip: every part as a chip - CLICK the name for its full pinout table, x drops it
// into a custom set (auto-rebuilt). The per-part identity remains visible.
export function SetStrip({
  union,
  onDropPart,
  onOpenPart,
}: {
  union: UnionDTO;
  onDropPart: (ref: string) => void;
  onOpenPart?: (ref: string) => void;
}) {
  const familyOf = (ref: string) => {
    const m = /^STM32([A-Z]+\d)/.exec(ref);
    return m ? `STM32${m[1]}` : union.family;
  };
  const openPartLabel = useText("stm.compat.open-part.title", "Open this part's pinout table");
  const removePartLabel = useCopyFormatter(
    "stm.compat.remove-part.aria",
    "Remove {part} from the set",
  );
  return (
    // Bounded: a whole-family set runs to dozens of chips; the strip scrolls internally so it
    // never pushes the switch plan and map below the fold (the bounded-list discipline).
    <div
      className="flex max-h-28 flex-none flex-wrap items-center gap-1.5 overflow-y-auto"
      data-testid="compat-set-strip"
    >
      <span className="text-2xs font-semibold text-t3">
        <Text
          id="stm.compat.set-of"
          values={{ count: union.parts.length, package: union.package }}
        >
          {"Set of {count} on {package}"}
        </Text>
      </span>
      {union.resolved.map((r) => (
        <span
          key={r.ref}
          className="flex items-center gap-1.5 rounded-control bg-raise px-2 py-1 shadow-[inset_0_1px_0_var(--edge-hi)]"
        >
          <button
            type="button"
            onClick={() => onOpenPart?.(r.ref)}
            title={openPartLabel}
            className="font-mono text-2xs text-t1 hover:underline"
          >
            {r.mpn || r.ref}
          </button>
          <span className="font-mono text-2xs text-t3">{familyOf(r.ref)}</span>
          {union.parts.length > 2 ? (
            <button
              type="button"
              aria-label={removePartLabel({ part: r.mpn || r.ref })}
              onClick={() => onDropPart(r.ref)}
              className="text-t3 hover:text-t1"
            >
              ×
            </button>
          ) : null}
        </span>
      ))}
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
        "Exact target set and solution policy",
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
        "Reusable topology and capability requirements",
      ),
    },
    positions: {
      label: useText("stm.compat.export.positions.label", "Physical Positions"),
      description: useText(
        "stm.compat.export.positions.description",
        "Every package position and assigned solution",
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
          "focus-visible:outline-offset-2 focus-visible:outline-acc " +
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

function ChamberMessage({ children }: { children: React.ReactNode }) {
  return (
    <div className="m-4 flex flex-1 items-center justify-center rounded-card bg-stage px-6 py-16 text-center shadow-[inset_0_1px_0_var(--edge-hi)]">
      <p className="text-sm text-t3">{children}</p>
    </div>
  );
}
