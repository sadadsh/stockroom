/**
 * The Bench's pure scope/set model: which packages a family selection offers, how a package is
 * classified for the filter chips, the steppable set list, and the export bundle. Kept OUT of
 * CompatibilityWorkbench so that component file exports only its components (Fast Refresh keeps
 * the Bench's scope and stepping state across an edit instead of remounting).
 */
import type { SuggestionGroupDTO, UnionDTO } from "../../api/types";

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
  // Index the families by name once, so the per-selection lookup below is O(1) rather than a scan
  // of the whole family list. First entry wins, exactly as the .find() it replaces did.
  const packagesByFamily = new Map<string, string[]>();
  for (const f of families) {
    if (!packagesByFamily.has(f.family)) packagesByFamily.set(f.family, f.packages);
  }
  const byName = new Map<string, PackageOption>();
  for (const name of selected) {
    const packages = packagesByFamily.get(name) ?? [];
    for (const pkg of packages) {
      const entry = byName.get(pkg) ?? { name: pkg, covered: [], missing: [] };
      entry.covered.push(name);
      byName.set(pkg, entry);
    }
  }
  for (const entry of byName.values()) {
    const covered = new Set(entry.covered);
    entry.missing = selected.filter((f) => !covered.has(f));
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

export const PACKAGE_KINDS = ["All", "LQFP", "QFN", "BGA", "CSP", "Other"] as const;

export type PackageKind = (typeof PACKAGE_KINDS)[number];

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
