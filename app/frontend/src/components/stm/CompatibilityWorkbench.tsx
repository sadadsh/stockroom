/**
 * CompatibilityWorkbench - the Bench (owner redesign 2026-07-23): the socket-union workbench
 * rebuilt around the build-card question. Pick a scope (families + one package) and the Bench
 * does the rest - no Build Set button, no per-set rebuilding:
 *
 * - The package chips are the UNION of the selected families' packages, each showing its family
 *   coverage (n/m when a family lacks it); building a set uses the covered families only, so an
 *   unsupported family is visible, never silently dropped. A filter row keeps the grid tame.
 * - The compatible sets (the suggestion groups) compute automatically and render as a stepper:
 *   All Parts, then Baseline, then each divergent group. Stepping auto-unions that set - the
 *   goal is every MCU in scope belonging to a set you can walk through.
 * - Each set shows the verdict, the part chips (click = that part's full pinout table; x = drop
 *   it into a custom set, auto-rebuilt), the SWITCH PLAN - every position that is not identical
 *   across the set, its baseline identity, who diverges, and whether an AF swap reconciles it or
 *   the socket board needs real switching hardware (the ZIF/build-card architecture readout) -
 *   then the union map and the AF conflict check.
 * - Export produces the machine-readable bundle the Obsidian build-card pipeline consumes.
 *
 * Still software/informational only: a swap is shown, never applied; nothing is persisted
 * client-side (CONTEXT decisions 4 and 8 unchanged).
 */
import { useEffect, useMemo, useState } from "react";
import { useStmCompatUnion, useStmFamilies, useStmSuggestions } from "../../api/stmQueries";
import { ApiError } from "../../api/client";
import type { CompatUnionBody, SuggestionGroupDTO, UnionDTO } from "../../api/types";
import type { StmScope } from "../../pages/StmViewerPage";
import { FamilyPicker } from "./FamilyPicker";
import { CompatUnionMap } from "./CompatUnionMap";
import { CompatVerdictBanner } from "./CompatVerdictBanner";
import { SwitchPlanTable } from "./SwitchPlanTable";
import { BenchPartModal } from "./BenchPartModal";
import { BuildIndexGate } from "./BuildIndexGate";
import { AfCheckPanel } from "./AfCheckPanel";
import { Button, Eyebrow } from "../primitives";

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

// The export bundle for the Obsidian build-card pipeline: the scope, every set, and the active
// set's full union (positions + reconcile + verdict) - the switch-plan facts a card needs.
export function benchExport(
  scope: { families: string[]; package: string },
  sets: BenchSet[],
  union: UnionDTO,
): string {
  return JSON.stringify(
    {
      format: "stm-bench/1",
      purpose: "obsidian-build-card socket union",
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

  const families = useStmFamilies();
  const union = useStmCompatUnion();

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

  const err = union.error;
  const indexNotBuilt =
    (err instanceof ApiError && err.status === 409) ||
    (suggestions.error instanceof ApiError && suggestions.error.status === 409);

  const stepTo = (id: string) => {
    setCustomParts(null);
    setActiveSetId(id);
  };
  const stepBy = (delta: number) => {
    const idx = sets.findIndex((s) => s.id === (customParts ? "all" : activeSetId));
    const next = sets[(idx + delta + sets.length) % sets.length];
    if (next) stepTo(next.id);
  };

  const exportActive = () => {
    if (!union.data || !selectedPackage) return;
    const payload = benchExport(
      { families: coveredFamilies, package: selectedPackage },
      sets,
      union.data,
    );
    const blob = new Blob([payload], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `stm-bench_${selectedPackage}.json`;
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="flex min-h-0 min-w-0 flex-1">
      {/* scope rail: families + the package grid (union with coverage, filterable) */}
      <div className="flex w-[272px] flex-none flex-col gap-4 overflow-y-auto px-3 pt-1">
        <FamilyPicker scope={scope} onScopeChange={setScope} />

        <div>
          <Eyebrow className="mb-2 px-1">Package</Eyebrow>
          {selectedFamilies.length === 0 ? (
            <p className="px-1 text-xs text-t3">Select one or more families to see packages.</p>
          ) : (
            <div className="flex flex-col gap-2">
              <input
                value={pkgFilter}
                onChange={(e) => setPkgFilter(e.target.value)}
                placeholder="Filter Packages"
                aria-label="Filter Packages"
                className="w-full rounded-control bg-field px-2 py-1 text-xs text-t1 outline-none placeholder:text-t3"
              />
              <div className="flex flex-wrap gap-1">
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
                <p className="px-1 text-xs text-t3">No packages match this filter.</p>
              ) : (
                <div className="grid grid-cols-2 gap-1.5" data-testid="bench-packages">
                  {visiblePackages.map((p) => {
                    const active = selectedPackage === p.name;
                    const partial = p.missing.length > 0;
                    return (
                      <button
                        key={p.name}
                        type="button"
                        aria-pressed={active}
                        title={
                          partial
                            ? `Not offered by ${p.missing.join(", ")}`
                            : "Offered by every selected family"
                        }
                        onClick={() =>
                          setSelectedPackage((cur) => (cur === p.name ? null : p.name))
                        }
                        className={
                          "flex items-center justify-between gap-1 rounded-control border px-2 py-1 " +
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

      {/* the bench itself. overflow-x-hidden so a wide inner table scrolls in ITS OWN wrapper
          instead of stretching the whole pane past the window edge. */}
      <div className="flex min-w-0 flex-1 flex-col overflow-y-auto overflow-x-hidden border-l border-line px-4 pt-1">
        {indexNotBuilt ? (
          <BuildIndexGate />
        ) : !selectedPackage || coveredFamilies.length === 0 ? (
          <ChamberMessage>
            Pick families and a package. The Bench computes every compatible set for the scope.
          </ChamberMessage>
        ) : suggestions.isLoading ? (
          <ChamberMessage>Computing the compatible sets...</ChamberMessage>
        ) : suggestions.isError ? (
          <ChamberMessage>Could not compute the compatible sets.</ChamberMessage>
        ) : (
          <div className="flex min-h-0 flex-1 flex-col gap-3 pb-4">
            {/* the set stepper: every MCU in scope belongs to one of these; step, never rebuild */}
            <div className="flex flex-none items-center gap-2" data-testid="bench-stepper">
              <Button small onClick={() => stepBy(-1)} aria-label="Previous Set">
                ←
              </Button>
              <div className="flex min-w-0 flex-1 items-center gap-1.5 overflow-x-auto">
                {sets.map((s) => {
                  const active = !customParts && s.id === activeSetId;
                  return (
                    <button
                      key={s.id}
                      type="button"
                      aria-pressed={active}
                      onClick={() => stepTo(s.id)}
                      className={
                        "flex flex-none items-center gap-1.5 rounded-control border px-2 py-1 " +
                        (active
                          ? "border-acc bg-acc-soft text-t1"
                          : "border-line2 text-t2 hover:text-t1")
                      }
                    >
                      <span className="text-xs">{s.label}</span>
                      <span className="tnum font-mono text-2xs text-t3">{s.count}</span>
                      {s.tier === "divergent" ? (
                        <span className="tnum font-mono text-2xs text-warn">
                          {s.divergent} div
                        </span>
                      ) : null}
                    </button>
                  );
                })}
                {customParts ? (
                  <span className="flex flex-none items-center gap-1.5 rounded-control border border-acc bg-acc-soft px-2 py-1">
                    <span className="text-xs text-t1">Custom</span>
                    <span className="tnum font-mono text-2xs text-t3">{customParts.length}</span>
                  </span>
                ) : null}
              </div>
              <Button small onClick={() => stepBy(1)} aria-label="Next Set">
                →
              </Button>
              <Button small onClick={exportActive} disabled={!union.data}>
                Export
              </Button>
            </div>

            {union.isPending ? (
              <ChamberMessage>Building the socket-union...</ChamberMessage>
            ) : err && !indexNotBuilt ? (
              <div className="flex flex-col items-center gap-3 py-16 text-center">
                <p className="text-sm text-err">
                  {err instanceof ApiError && err.status === 0
                    ? "Cannot reach the Stockroom server."
                    : err.message}
                </p>
                <Button small onClick={() => body && union.mutate(body)}>
                  Try Again
                </Button>
              </div>
            ) : union.data ? (
              <>
                <CompatVerdictBanner verdict={union.data.verdict} />
                <SetStrip
                  union={union.data}
                  onOpenPart={setOpenPart}
                  onDropPart={(ref) =>
                    setCustomParts(
                      (union.data ? union.data.parts : []).filter((p) => p !== ref),
                    )
                  }
                />
                <SwitchPlanTable union={union.data} />
                <CompatUnionMap union={union.data} />
                <AfCheckPanel union={union.data} />
              </>
            ) : null}
          </div>
        )}
      </div>

      {openPart ? <BenchPartModal part={openPart} onClose={() => setOpenPart(null)} /> : null}
    </div>
  );
}

// The set strip: every part as a chip - CLICK the name for its full pinout table, x drops it
// into a custom set (auto-rebuilt). The per-part identity of the build card, kept visible.
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
  return (
    // Bounded: a whole-family set runs to dozens of chips; the strip scrolls internally so it
    // never pushes the switch plan and map below the fold (the bounded-list discipline).
    <div
      className="flex max-h-28 flex-none flex-wrap items-center gap-1.5 overflow-y-auto"
      data-testid="compat-set-strip"
    >
      <span className="text-2xs font-semibold text-t3">
        Set of {union.parts.length} on {union.package}
      </span>
      {union.resolved.map((r) => (
        <span
          key={r.ref}
          className="flex items-center gap-1.5 rounded-control bg-raise px-2 py-1 shadow-[inset_0_1px_0_var(--edge-hi)]"
        >
          <button
            type="button"
            onClick={() => onOpenPart?.(r.ref)}
            title="Open this part's pinout table"
            className="font-mono text-2xs text-t1 hover:underline"
          >
            {r.mpn || r.ref}
          </button>
          <span className="font-mono text-2xs text-t3">{familyOf(r.ref)}</span>
          {union.parts.length > 2 ? (
            <button
              type="button"
              aria-label={`Remove ${r.mpn || r.ref} from the set`}
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

function ChamberMessage({ children }: { children: React.ReactNode }) {
  return (
    <div className="m-4 flex flex-1 items-center justify-center rounded-card bg-stage px-6 py-16 text-center shadow-[inset_0_1px_0_var(--edge-hi)]">
      <p className="text-sm text-t3">{children}</p>
    </div>
  );
}
