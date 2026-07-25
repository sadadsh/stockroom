/**
 * AfCheckPanel + buildAssignments: verify a set's proposed reconcile assignments for AF conflicts
 * (COMPAT reconcile support), extracted from CompatibilityWorkbench so the Bench redesign stays
 * readable. The held assignment is derived from the union in React state and posted to the pure
 * af-check read; nothing is persisted or written back (CONTEXT decision 8).
 */
import { useEffect, useMemo, useState } from "react";
import { useStmAfCheck } from "../../api/stmQueries";
import { ApiError } from "../../api/client";
import type { AfCheckBody, UnionDTO } from "../../api/types";
import { Badge, Button, Card, Eyebrow } from "../primitives";

// The per-ref assignment the union's reconcile proposes: for each part, the position -> { signal,
// af_index } swaps that make it carry the union's required signals. Derived purely from the union
// result already in React state, never persisted (CONTEXT decision 8) - the input to an af-check.
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

// AfCheckPanel: verify a part's proposed reconcile assignment for conflicts (COMPAT reconcile
// support). The held assignment is derived from the union in state and posted to the pure af-check
// read; nothing is persisted or written back (decision 8). Only rendered when the set actually
// proposes swaps to check.
export function AfCheckPanel({ union }: { union: UnionDTO }) {
  const assignmentsByRef = useMemo(() => buildAssignments(union), [union]);
  const checkableRefs = Object.keys(assignmentsByRef);
  const [selectedRef, setSelectedRef] = useState<string | null>(checkableRefs[0] ?? null);
  const afCheck = useStmAfCheck();

  // A new union invalidates the prior selection + result (the swaps may differ entirely).
  useEffect(() => {
    setSelectedRef(Object.keys(buildAssignments(union))[0] ?? null);
    afCheck.reset();
    // afCheck is stable enough for this reset-on-new-union intent; keying on the union is the point.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [union]);

  if (checkableRefs.length === 0) return null;

  const conflicts = afCheck.data?.conflicts ?? [];
  const notBuilt = afCheck.error instanceof ApiError && afCheck.error.status === 409;

  return (
    <Card className="flex flex-none flex-col gap-3 px-4 py-3" data-testid="af-check-panel">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <Eyebrow>AF Conflict Check</Eyebrow>
        <Button
          variant="soft"
          small
          disabled={!selectedRef || afCheck.isPending}
          onClick={() =>
            selectedRef &&
            afCheck.mutate({ part: selectedRef, assignment: assignmentsByRef[selectedRef] ?? {} })
          }
        >
          {afCheck.isPending ? "Checking..." : "Check Conflicts"}
        </Button>
      </div>

      <div className="flex flex-wrap gap-1.5">
        {checkableRefs.map((ref) => {
          const active = ref === selectedRef;
          return (
            <button
              key={ref}
              type="button"
              aria-pressed={active}
              onClick={() => setSelectedRef(ref)}
              className={
                "rounded-control border px-2 py-1 font-mono text-2xs " +
                (active ? "border-acc bg-acc-soft text-t1" : "border-line2 text-t2 hover:text-t1")
              }
            >
              {ref}
            </button>
          );
        })}
      </div>

      {afCheck.isSuccess ? (
        conflicts.length === 0 ? (
          <p className="text-xs text-ok" data-testid="af-check-clean">
            No conflicts for this assignment.
          </p>
        ) : (
          <ul className="flex flex-col gap-1.5" data-testid="af-check-conflicts">
            {conflicts.map((c, i) => (
              <li
                key={`${c.kind}-${i}`}
                className="flex flex-col gap-0.5 rounded-control bg-raise2 px-3 py-2"
              >
                <div className="flex items-center gap-2">
                  <Badge tone="err" size="sm">
                    {c.kind}
                  </Badge>
                  {c.peripheral ? (
                    <span className="font-mono text-2xs text-t3">{c.peripheral}</span>
                  ) : null}
                </div>
                <p className="text-2xs text-t2">{c.message}</p>
              </li>
            ))}
          </ul>
        )
      ) : notBuilt ? (
        <p className="text-xs text-t3">Build the index to check for conflicts.</p>
      ) : afCheck.isError ? (
        <p className="text-xs text-err">Could not check the assignment.</p>
      ) : (
        <p className="text-xs text-t3">
          Check the proposed swaps for the selected part against its peripheral mux.
        </p>
      )}
    </Card>
  );
}
