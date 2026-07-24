/**
 * CompatibilityWorkbench (COMPAT-01..05): assemble a set of STM32s, request the live socket-union,
 * and render the verdict + union map. This is the build-card socket-union philosophy made a live,
 * co-equal workflow. Software / informational only: a swap is shown, never applied (CONTEXT
 * decision 4); no in-progress state is ever persisted (decision 8).
 *
 * Set assembly reuses Phase 4's FamilyPicker (CONTEXT decision 2 - no second picker): the union
 * scope is one family plus one of its packages (the group path, POST { family, package }), OR an
 * explicit ref list (POST { parts }) that 05-02's suggestion list loads into the assembly. On a 409
 * the reused BuildIndexGate renders (decision 9), never a crash or a blank pane.
 */
import { useEffect, useMemo, useState } from "react";
import { useStmAfCheck, useStmCompatUnion, useStmFamilies } from "../../api/stmQueries";
import { ApiError } from "../../api/client";
import type { AfCheckBody, CompatUnionBody, UnionDTO } from "../../api/types";
import type { StmScope } from "../../pages/StmViewerPage";
import { FamilyPicker } from "./FamilyPicker";
import { CompatUnionMap } from "./CompatUnionMap";
import { CompatVerdictBanner } from "./CompatVerdictBanner";
import { SuggestionGroupList } from "./SuggestionGroupList";
import { BuildIndexGate } from "./BuildIndexGate";
import { Badge, Button, Card, Eyebrow } from "../primitives";

export interface Assembly {
  family: string | null;
  package: string | null;
  // an explicit ref list (loaded by 05-02's suggestions); takes precedence over the group path.
  parts: string[];
}

// The union body from the current assembly, or null when it is not yet buildable. An explicit ref
// list posts { parts }; otherwise a complete (family, package) group posts { family, package } -
// both shapes POST /api/stm/compat/union accepts (INTERFACES section 4). A partial group (a family
// but no package) is not buildable, so Build Set stays disabled rather than posting a bad request.
export function unionBody(a: Assembly): CompatUnionBody | null {
  if (a.parts.length > 0) return { parts: a.parts };
  if (a.family && a.package) return { family: a.family, package: a.package };
  return null;
}

export function CompatibilityWorkbench() {
  const [scope, setScope] = useState<StmScope>({ families: [], mcus: [] });
  const [selectedPackage, setSelectedPackage] = useState<string | null>(null);
  // The explicit-ref path; 05-02's SuggestionGroupList loads a set here as an explicit user action.
  const [parts, setParts] = useState<string[]>([]);

  const families = useStmFamilies();
  const union = useStmCompatUnion();

  // The union scope is a single family (the group path needs exactly one; the union requires all
  // parts share a family AND package). Zero or many selected families leaves the group path unset.
  const family = scope.families.length === 1 ? scope.families[0] : null;

  // A new family invalidates the previously chosen package (it may not exist on the new family).
  useEffect(() => {
    setSelectedPackage(null);
  }, [family]);

  const familyPackages = useMemo(() => {
    if (!family) return [];
    const fam = families.data?.families.find((f) => f.family === family);
    return fam?.packages ?? [];
  }, [family, families.data]);

  const assembly: Assembly = { family, package: selectedPackage, parts };
  const body = useMemo(
    () => unionBody(assembly),
    [family, selectedPackage, parts],
  );

  const err = union.error;
  const indexNotBuilt = err instanceof ApiError && err.status === 409;

  return (
    <div className="flex min-h-0 flex-1">
      {/* assembly */}
      <div className="flex w-[272px] flex-none flex-col gap-4 overflow-y-auto px-3 pt-1">
        <FamilyPicker scope={scope} onScopeChange={setScope} />

        <div>
          <Eyebrow className="mb-2 px-1">Package</Eyebrow>
          {parts.length > 0 ? (
            <p className="px-1 text-xs text-t3">
              Building from a loaded set of {parts.length} parts.
            </p>
          ) : !family ? (
            <p className="px-1 text-xs text-t3">Select one family to choose a package.</p>
          ) : familyPackages.length === 0 ? (
            <p className="px-1 text-xs text-t3">No packages for this family.</p>
          ) : (
            <div className="flex flex-wrap gap-1.5">
              {familyPackages.map((pkg) => {
                const active = selectedPackage === pkg;
                return (
                  <button
                    key={pkg}
                    type="button"
                    aria-pressed={active}
                    onClick={() => setSelectedPackage((cur) => (cur === pkg ? null : pkg))}
                    className={
                      "rounded-control border px-2 py-1 font-mono text-xs " +
                      (active
                        ? "border-acc bg-acc-soft text-t1"
                        : "border-line2 text-t2 hover:text-t1")
                    }
                  >
                    {pkg}
                  </button>
                );
              })}
            </div>
          )}
        </div>

        <div className="flex items-center gap-2 px-1">
          <Button
            variant="accent"
            disabled={!body || union.isPending}
            onClick={() => body && union.mutate(body)}
          >
            {union.isPending ? "Building Set..." : "Build Set"}
          </Button>
          {parts.length > 0 ? (
            <Button
              variant="ghost-danger"
              small
              onClick={() => setParts([])}
              disabled={union.isPending}
            >
              Clear Set
            </Button>
          ) : null}
        </div>

        {/* Auto-discovered compatible sets (COMPAT-04). Picking one loads its refs into the assembly
            as an explicit action; the user still presses Build Set (never auto-unioned). */}
        <SuggestionGroupList
          package={selectedPackage}
          family={family}
          onLoadSet={(refs) => setParts(refs)}
        />
      </div>

      {/* result */}
      <div className="flex min-w-0 flex-1 flex-col overflow-y-auto border-l border-line px-4 pt-1">
        {indexNotBuilt ? (
          <BuildIndexGate />
        ) : union.isPending ? (
          <ChamberMessage>Building the socket-union...</ChamberMessage>
        ) : err ? (
          <div className="flex flex-col items-center gap-3 py-16 text-center">
            <p className="text-sm text-err">
              {err instanceof ApiError && err.status === 0
                ? "Cannot reach the Stockroom server."
                : err.message}
            </p>
            <Button small disabled={!body} onClick={() => body && union.mutate(body)}>
              Try Again
            </Button>
          </div>
        ) : union.data ? (
          <div className="flex min-h-0 flex-1 flex-col gap-3 pb-4">
            {/* The verdict is the one dominant focal element, above the map (CONTEXT decision 5). */}
            <CompatVerdictBanner verdict={union.data.verdict} />
            <CompatUnionMap union={union.data} />
            <AfCheckPanel union={union.data} />
          </div>
        ) : (
          <ChamberMessage>Assemble a set and build the socket-union to compare it.</ChamberMessage>
        )}
      </div>
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
