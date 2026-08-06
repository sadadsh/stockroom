/**
 * AfCheckPanel: verify a set's proposed reconcile assignments for AF conflicts (COMPAT reconcile
 * support), extracted from CompatibilityWorkbench so the Bench redesign stays readable. The held
 * assignment (./afAssignments) is derived from the union in React state and posted to the pure
 * af-check read; nothing is persisted or written back (CONTEXT decision 8).
 */
import { useEffect, useMemo, useState } from "react";
import { useStmAfCheck } from "../../api/stmQueries";
import { ApiError } from "../../api/client";
import type { UnionDTO } from "../../api/types";
import { Badge, Button, Card, Eyebrow } from "../primitives";
import { Text, useText } from "../../lib/copy";
import { buildAssignments } from "./afAssignments";

// AfCheckPanel: verify a part's proposed reconcile assignment for conflicts (COMPAT reconcile
// support). The held assignment is derived from the union in state and posted to the pure af-check
// read; nothing is persisted or written back (decision 8). Only rendered when the set actually
// proposes swaps to check.
export function AfCheckPanel({ union }: { union: UnionDTO }) {
  const assignmentsByRef = useMemo(() => buildAssignments(union), [union]);
  const checkableRefs = Object.keys(assignmentsByRef);
  const [selectedRef, setSelectedRef] = useState<string | null>(checkableRefs[0] ?? null);
  const afCheck = useStmAfCheck();
  const checkingLabel = useText("stm.af.check.checking", "Checking...");
  const checkLabel = useText("stm.af.check.action", "Check Conflicts");

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
        <Eyebrow>
          <Text id="stm.af.check.title">AF Conflict Check</Text>
        </Eyebrow>
        <Button
          variant="soft"
          small
          disabled={!selectedRef || afCheck.isPending}
          onClick={() =>
            selectedRef &&
            afCheck.mutate({ part: selectedRef, assignment: assignmentsByRef[selectedRef] ?? {} })
          }
        >
          {afCheck.isPending ? checkingLabel : checkLabel}
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
          <p className="text-xs text-ok-text" data-testid="af-check-clean">
            <Text id="stm.af.check.clean">No conflicts for this assignment.</Text>
          </p>
        ) : (
          <ul className="flex flex-col gap-1.5" data-testid="af-check-conflicts">
            {/* af_conflicts emits at most one conflict per assigned position and one per
                (peripheral, signal) double claim, and each message names that position or pair, so
                the message is the conflict's id. */}
            {conflicts.map((c) => (
              <li
                key={c.message}
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
        <p className="text-xs text-t3">
          <Text id="stm.af.check.not-built">Build the index to check for conflicts.</Text>
        </p>
      ) : afCheck.isError ? (
        <p className="text-xs text-err-text">
          <Text id="stm.af.check.failed">Could not check the assignment.</Text>
        </p>
      ) : (
        <p className="text-xs text-t3">
          <Text id="stm.af.check.prompt">
            Check the proposed swaps for the selected part against its peripheral mux.
          </Text>
        </p>
      )}
    </Card>
  );
}
