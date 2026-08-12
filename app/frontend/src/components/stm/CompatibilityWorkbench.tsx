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
import { ApiError } from "../../api/client";
import type {
  CompatUnionBody,
  TargetDefinitionBody,
  TargetDefinitionPolicy,
  UnionDTO,
} from "../../api/types";
import type { StmScope } from "../../pages/StmViewerPage";
import { CompatUnionMap } from "./CompatUnionMap";
import { BenchPartModal } from "./BenchPartModal";
import { BuildIndexGate } from "./BuildIndexGate";
import { AfCheckPanel } from "./AfCheckPanel";
import { SocketSolutionPanel } from "./SocketSolutionPanel";
import { TargetPolicyEditor } from "./TargetPolicyEditor";
import { cloneCoreBringUpPolicy } from "./coreBringUpPolicy";
import { BenchScopeRail } from "./BenchScopeRail";
import { BenchStepper } from "./BenchStepper";
import { benchSets, packagesForScope } from "./benchModel";
import { Button, ErrorState } from "../primitives";
import { Text, useCopyFormatter, useText } from "../../lib/copy";
import { downloadTextFile } from "../../lib/stmTargetExport";
import { useScenarioUiState } from "../../design-studio/scenarioState";
import { TargetDefinitionPanel } from "./TargetDefinitionPanel";
import {
  stmSocketExport,
  stmSocketExportFilename,
  type StmSocketExportKind,
} from "../../lib/stmSocketSolutionExport";

// ── the Bench ────────────────────────────────────────────────────────────────

export function CompatibilityWorkbench() {
  const preview = useScenarioUiState().stm;
  const [scope, setScope] = useState<StmScope>(() => ({
    families: preview?.benchScope?.families ?? [],
    mcus: preview?.benchScope?.mcus ?? [],
  }));
  const [selectedPackage, setSelectedPackage] = useState<string | null>(preview?.benchPackage ?? null);
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

  const unreachableLabel = useText("stm.compat.unreachable", "Cannot reach the Stockroom server.");

  const selectedFamilies = scope.families;
  const familiesKey = selectedFamilies.join(",");

  const packageOptions = useMemo(
    () => packagesForScope(families.data?.families ?? [], selectedFamilies),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [families.data, familiesKey],
  );
  const activeOption = packageOptions.find((p) => p.name === selectedPackage) ?? null;
  const coveredFamilies = useMemo(() => activeOption?.covered ?? [], [activeOption]);
  const coveredKey = coveredFamilies.join(",");

  // A scope change invalidates the chosen package. That write belongs to the event that starts it
  // (changeScope below), not to an effect: as an effect it set selectedPackage, which set off the
  // stepping reset below - one action, two extra renders.
  //
  // The stepping reset stays an effect because coveredKey also moves when the families query
  // resolves or refetches, which is not an event this component owns.
  useEffect(() => {
    setActiveSetId("all");
    setCustomParts(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedPackage, coveredKey]);

  const changeScope = (next: StmScope) => {
    setScope(next);
    setSelectedPackage(null);
  };

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
      // a detached copy, so a later policy edit cannot mutate the compiled request. The policy is
      // plain JSON data, which structuredClone copies faithfully.
      policy: structuredClone(policy),
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

  if (preview?.targetDefinition) {
    return <TargetDefinitionPanel definition={preview.targetDefinition} />;
  }
  if (preview?.showTargetPolicy) {
    return (
      <div data-dev-id="stm.bench" className="flex min-h-0 min-w-0 flex-1">
        <BenchScopeRail
          scope={scope}
          onScopeChange={changeScope}
          packageOptions={packageOptions}
          selectedPackage={selectedPackage}
          onSelectPackage={setSelectedPackage}
        />
        <div className="min-w-0 flex-1 border-l border-line p-4">
          <TargetPolicyEditor policy={policy} onPolicyChange={setPolicy} />
        </div>
      </div>
    );
  }

  return (
    <div data-dev-id="stm.bench" className="flex min-h-0 min-w-0 flex-1">
      {/* scope rail: families + the package grid (union with coverage, filterable) */}
      <BenchScopeRail
        scope={scope}
        onScopeChange={changeScope}
        packageOptions={packageOptions}
        selectedPackage={selectedPackage}
        onSelectPackage={setSelectedPackage}
      />

      {/* The package stays in view. Scope and advanced evidence scroll inside their own regions. */}
      <div className="flex min-w-0 flex-1 flex-col overflow-hidden border-l border-line">
        {indexNotBuilt ? (
          <BuildIndexGate />
        ) : !selectedPackage || coveredFamilies.length === 0 ? (
          <ChamberMessage>
            <Text id="stm.compat.scope-prompt">
              Pick series and a package. The Bench computes each compatible set for the scope.
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
            <BenchStepper
              sets={sets}
              activeSetId={activeSetId}
              customParts={customParts}
              coveredCount={activeOption?.covered.length ?? ""}
              familyCount={selectedFamilies.length}
              selectedPackage={selectedPackage}
              exportDisabled={
                !socketSolution.data ||
                !compiledRequest ||
                socketSolution.isPending ||
                socketSolution.isError
              }
              onStepBy={stepBy}
              onStepTo={stepTo}
              onExport={exportActive}
            />

            {union.isPending ? (
              <ChamberMessage>
                <Text id="stm.compat.union-loading">Building the socket-union...</Text>
              </ChamberMessage>
            ) : err && !indexNotBuilt ? (
              <div className="flex flex-col items-center gap-3 py-16 text-center">
                <p className="text-sm text-err-text">
                  {err instanceof ApiError && err.status === 0 ? unreachableLabel : err.message}
                </p>
                <Button small onClick={() => body && union.mutate(body)}>
                  <Text id="stm.compat.union-retry">Rerun</Text>
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
                          // detached, so a later policy edit cannot mutate the retried request
                          policy: structuredClone(policy),
                        })
                      }
                    >
                      <Text id="stm.compat.solution-retry">Rerun</Text>
                    </Button>
                  </div>
                ) : socketSolution.data ? (
                  /* keyed on the content-addressed digest: a newly compiled solution remounts the
                     panel, so every control resets without an adjustment effect. */
                  <SocketSolutionPanel
                    key={socketSolution.data.artifact_digest}
                    solution={socketSolution.data}
                  />
                ) : null}

                <details className="flex-none border-t border-line bg-surface">
                  <summary className="cursor-pointer px-4 py-2 text-xs text-t2">
                    <Text id="stm.compat.target-summary">Target set and rules</Text>
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
function SetStrip({
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

function ChamberMessage({ children }: { children: React.ReactNode }) {
  return (
    <div className="m-4 flex flex-1 items-center justify-center rounded-card bg-stage px-6 py-16 text-center shadow-[inset_0_1px_0_var(--edge-hi)]">
      <p className="text-sm text-t3">{children}</p>
    </div>
  );
}
