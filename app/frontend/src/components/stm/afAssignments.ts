/**
 * buildAssignments: the per-ref AF assignment a union's reconcile proposes. Kept OUT of
 * AfCheckPanel so that component file exports only its component (Fast Refresh keeps the panel's
 * selected ref and check result across an edit instead of remounting).
 */
import type { AfCheckBody, UnionDTO } from "../../api/types";

// For each part, the position -> { signal, af_index } swaps that make it carry the union's required
// signals. Derived purely from the union result already in React state, never persisted (CONTEXT
// decision 8) - the input to an af-check.
export function buildAssignments(union: UnionDTO): Record<string, AfCheckBody["assignment"]> {
  const byRef: Record<string, AfCheckBody["assignment"]> = {};
  for (const pos of union.positions) {
    if (!pos.reconcile?.swappable) continue;
    for (const swap of pos.reconcile.swaps) {
      (byRef[swap.ref] ??= {})[pos.position] = {
        signal: swap.target_signal,
        af_index: swap.via_af_index,
      };
    }
  }
  return byRef;
}
