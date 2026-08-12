import { useEffect, useMemo, useState } from "react";
import {
  useAssignProjectGroup,
  useLiveProjectBom,
  useProjectAssignments,
  useProjectBomExport,
  useProjectPlacementGeometry,
} from "../../api/queries";
import { api } from "../../api/client";
import type {
  DigiKeyQuantityPricing,
  ProjectAssignmentGroup,
  ProjectBom,
  ProjectBomLine,
  ProjectWorkspace,
} from "../../api/types";
import { Text, useCopyFormatter, useText } from "../../lib/copy";
import { downloadBlob } from "../../lib/download";
import { useToast } from "../../lib/toast";
import { useJob } from "../../lib/useJob";
import { DownloadIcon, RefreshIcon, SearchIcon } from "../icons";
import {
  Badge,
  Button,
  SectionHeading,
  SegmentedControl,
  type SegmentItem,
} from "../primitives";
import { ProjectInspectorFacts } from "./ProjectInspectorFacts";
import { ProjectPlacementStage } from "./ProjectPlacementStage";
import { AdaptiveChoice } from "../AdaptiveChoice";

type BomFilter = "all" | "unlinked" | "ready";

// One shared empty list stands in for a BOM that has not arrived. A fresh `[]` per render
// made every memo that reads the lines recompute on every render while the query was in
// flight, and each such memo declared a dependency it could never match.
const NO_LINES: readonly ProjectBomLine[] = [];

export function ProjectBomWorkbench({
  projectId,
  workspace,
}: {
  projectId: string;
  workspace: ProjectWorkspace;
}) {
  // The committed build quantity is always a valid 1..999 - the BOM query and the export are
  // never issued with anything else. The DRAFT is whatever is in the field, including the empty
  // string: `Number(event.target.value) || 1` snapped a cleared field straight back to 1, so the
  // count could not be emptied to type a fresh one (typing 12 over 1 required selecting the 1).
  const [boards, setBoards] = useState(1);
  const [boardsDraft, setBoardsDraft] = useState("1");
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<BomFilter>("all");
  const [selectedKey, setSelectedKey] = useState("");
  const bom = useLiveProjectBom(projectId, boards);
  const assignments = useProjectAssignments(projectId);
  const geometry = useProjectPlacementGeometry(projectId);
  const exportBom = useProjectBomExport(projectId);
  const { toast } = useToast();
  const allLinesLabel = useText("projects.bom.filter-all", "All Lines");
  const needsLinkLabel = useText("projects.bom.filter-needs-link", "Needs Link");
  const linkedLabel = useText("projects.bom.filter-linked", "Linked");
  const compactFilterLabel = useText("projects.bom.status-aria", "BOM status");
  const lineLabel = useText("projects.bom.line-aria", "BOM line");
  const quantityLabel = useText("projects.bom.board-quantity-aria", "Board Count");
  const searchPlaceholder = useText("projects.bom.search-placeholder", "Ref, MPN, value");
  const identityNeeded = useText("projects.identity-needed", "Identification Needed");
  const exportedToast = useText("projects.bom.toast-exported", "BOM exported");
  const exportFailed = useText("projects.bom.toast-export-failed", "Could not export BOM");
  const filters = [
    { id: "all" as const, label: allLinesLabel },
    { id: "unlinked" as const, label: needsLinkLabel },
    { id: "ready" as const, label: linkedLabel },
  ];
  const lines = bom.data?.lines ?? NO_LINES;
  const groups = assignments.data?.groups ?? [];

  const filtered = useMemo(() => {
    const needle = query.trim().toLocaleLowerCase();
    return lines.filter((line) => {
      if (filter === "unlinked" && line.in_library) return false;
      if (filter === "ready" && !line.in_library) return false;
      if (!needle) return true;
      return `${line.refs.join(" ")} ${line.mpn} ${line.manufacturer} ${line.value} ${line.footprint}`
        .toLocaleLowerCase()
        .includes(needle);
    });
  }, [lines, query, filter]);

  // The chosen line is a preference; the line actually shown is resolved DURING render, so a
  // view that no longer carries the chosen line opens on its first line in the same render.
  // Writing that fallback into state instead took a second render to settle - the inspector
  // read "Select a BOM line" for a frame - and it overwrote the operator's own choice, so
  // clearing a search left the search's first line selected rather than the chosen one.
  const activeKey = filtered.some((line) => lineKey(line) === selectedKey)
    ? selectedKey
    : filtered.length
      ? lineKey(filtered[0])
      : "";

  const selected = filtered.find((line) => lineKey(line) === activeKey) ?? null;
  const selectedGroup = selected ? findGroup(groups, selected) : undefined;

  async function download() {
    try {
      const file = await exportBom.mutateAsync(boards);
      downloadBlob(file.filename, file.blob);
      toast(exportedToast, "ok");
    } catch (error) {
      toast(error instanceof Error ? error.message : exportFailed, "err");
    }
  }

  if (bom.isLoading || assignments.isLoading) {
    return (
      <CenteredMessage>
        <Text id="projects.bom.loading">Loading BOM...</Text>
      </CenteredMessage>
    );
  }
  if (bom.error || assignments.error) {
    return (
      <CenteredMessage tone="err">
        {(bom.error ?? assignments.error)?.message ?? (
          <Text id="projects.bom.error">Could not load BOM.</Text>
        )}
      </CenteredMessage>
    );
  }

  const summary = bom.data?.summary;
  const linked = lines.filter((line) => line.in_library).length;

  return (
    <div data-dev-id="projects.bom" className="flex min-h-0 flex-1 flex-col">
      <div className="flex flex-none flex-wrap items-center gap-3 pb-3">
        <div>
          <SectionHeading>
            <Text id="projects.bom.title">BOM</Text>
          </SectionHeading>
          <p className="mt-0.5 text-xs text-t3">
            {bom.data?.evidence?.variant || "Default"} · {workspace.eda_label} ·{" "}
            <Text
              id="projects.bom.placement-count"
              values={{ count: bom.data?.component_count ?? 0 }}
            >
              {"{count} placements"}
            </Text>
          </p>
        </div>
        <div className="ml-auto flex items-center gap-2">
          <label className="flex h-[31px] items-center gap-2 rounded-control border border-line bg-field px-2.5 text-xs text-t2">
            <Text id="projects.bom.boards">Boards</Text>
            <input
              aria-label={quantityLabel}
              type="number"
              min={1}
              max={999}
              value={boardsDraft}
              onChange={(event) => {
                const next = event.target.value;
                setBoardsDraft(next);
                const parsed = Number.parseInt(next, 10);
                // An empty or out-of-range field keeps the last committed count in force.
                if (parsed >= 1 && parsed <= 999) setBoards(parsed);
              }}
              // Leaving the field settles it back onto the count actually in force, so an
              // abandoned empty (or 0, or 1000) never lingers as if it were the quantity.
              onBlur={() => setBoardsDraft(String(boards))}
              className="w-12 bg-transparent text-right font-mono text-t1 outline-none"
            />
          </label>
          <Button
            icon={<RefreshIcon />}
            onClick={() => {
              bom.refetch();
              assignments.refetch();
            }}
          >
            <Text id="projects.refresh">Refresh</Text>
          </Button>
          <Button
            variant="accent"
            icon={<DownloadIcon />}
            disabled={exportBom.isPending || !lines.length}
            onClick={download}
          >
            {exportBom.isPending ? (
              <Text id="projects.bom.exporting">Exporting...</Text>
            ) : (
              <Text id="projects.bom.export">Export CSV</Text>
            )}
          </Button>
        </div>
      </div>

      <BomMetrics
        lineCount={lines.length}
        linkedCount={linked}
        placementCount={bom.data?.component_count ?? 0}
        summary={summary}
      />

      <div className="grid min-h-0 flex-1 grid-cols-[minmax(0,1fr)_228px] overflow-hidden rounded-card border border-line bg-surface @[60rem]:grid-cols-[220px_minmax(420px,1fr)_250px]">
        <BomLineList
          lines={filtered}
          activeKey={activeKey}
          onSelect={setSelectedKey}
          filters={filters}
          filter={filter}
          onFilterChange={setFilter}
          query={query}
          onQueryChange={setQuery}
        />
        <div className="flex min-h-0 min-w-0 flex-col border-r border-line">
          <div className="flex-none border-b border-line px-3 py-2 @[60rem]:hidden">
            <div className="flex items-center gap-2">
              <label className="relative min-w-0 flex-1">
                <span className="sr-only">
                  <Text id="projects.bom.filter-compact">Find BOM Line</Text>
                </span>
                <span
                  aria-hidden
                  className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-t3"
                >
                  <SearchIcon />
                </span>
                <input
                  value={query}
                  onChange={(event) => setQuery(event.target.value)}
                  placeholder={searchPlaceholder}
                  className="h-8 w-full rounded-control border border-line bg-field pl-8 pr-2 text-xs text-t1 outline-none placeholder:text-t3 focus:border-acc focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-acc"
                />
              </label>
              <AdaptiveChoice
                devId="projects.bom-filter-control"
                label={compactFilterLabel}
                value={filter}
                onChange={(next) => setFilter(next as BomFilter)}
                className="h-8 w-[108px]"
                options={filters.map((option) => ({ value: option.id, label: option.label }))}
              />
            </div>
            <label className="mt-2 grid grid-cols-[4.5rem_minmax(0,1fr)] items-center gap-2">
              <span className="text-xs font-medium text-t2">{lineLabel}</span>
              <AdaptiveChoice
                devId="projects.bom-line-control"
                label={lineLabel}
                value={activeKey}
                onChange={setSelectedKey}
                disabled={!filtered.length}
                className="h-8 w-full"
                options={filtered.map((line) => ({
                  value: lineKey(line),
                  label: `${line.final_qty} × ${line.mpn || line.value || identityNeeded} · ${line.in_library ? linkedLabel : needsLinkLabel}`,
                }))}
              />
            </label>
          </div>
          <ProjectPlacementStage
            projectId={projectId}
            geometry={geometry.data}
            unavailable={!!geometry.error}
            onRetry={() => geometry.refetch()}
            selectedReferences={selected?.refs ?? []}
            onSelectReference={(reference) => {
              const line = lines.find((candidate) => candidate.refs.includes(reference));
              if (line) setSelectedKey(lineKey(line));
            }}
            className="min-h-0 flex-1 !rounded-none !border-0"
          />
        </div>
        <BomLineInspector
          projectId={projectId}
          line={selected}
          group={selectedGroup}
          writable={assignments.data?.binding?.writable ?? false}
        />
      </div>
    </div>
  );
}

/** The count strip above the workbench: what the BOM holds and what it is worth. */
function BomMetrics({
  lineCount,
  linkedCount,
  placementCount,
  summary,
}: {
  lineCount: number;
  linkedCount: number;
  placementCount: number;
  summary: ProjectBom["summary"] | undefined;
}) {
  const linesMetric = useText("projects.bom.metric-lines", "Lines");
  const linkedMetric = useText("projects.bom.metric-linked", "Linked");
  const placementsMetric = useText("projects.bom.metric-placements", "Placements");
  const costMetric = useText("projects.bom.metric-cost", "Estimated Cost");
  const notPriced = useText("projects.bom.not-priced", "Not priced");
  return (
    <div className="mb-3 flex flex-none flex-wrap items-center gap-x-5 gap-y-1 px-1 text-xs">
      <span className="text-t3">
        {linesMetric}{" "}
        <strong className="font-mono font-semibold text-t1">{lineCount}</strong>
      </span>
      <span className="text-t3">
        {linkedMetric}{" "}
        <strong
          className={`font-mono font-semibold ${
            linkedCount === lineCount ? "text-ok-text" : "text-warn"
          }`}
        >
          {linkedCount}/{lineCount}
        </strong>
      </span>
      <span className="text-t3">
        {placementsMetric}{" "}
        <strong className="font-mono font-semibold text-t1">{placementCount}</strong>
      </span>
      <span className="text-t3">
        {costMetric}{" "}
        <strong
          className={`font-mono font-semibold ${
            summary?.state === "costed" ? "text-ok-text" : "text-t2"
          }`}
        >
          {summary?.state === "costed"
            ? `${summary.currency} ${summary.total_cost.toFixed(2)}`
            : notPriced}
        </strong>
      </span>
    </div>
  );
}

/** The wide queue: the view's filter row and one row per line it admits. */
function BomLineList({
  lines,
  activeKey,
  onSelect,
  filters,
  filter,
  onFilterChange,
  query,
  onQueryChange,
}: {
  lines: ProjectBomLine[];
  activeKey: string;
  onSelect: (key: string) => void;
  filters: readonly SegmentItem<BomFilter>[];
  filter: BomFilter;
  onFilterChange: (next: BomFilter) => void;
  query: string;
  onQueryChange: (next: string) => void;
}) {
  const filterLabel = useText("projects.bom.filter-aria", "BOM line filter");
  const searchPlaceholder = useText("projects.bom.search-placeholder", "Ref, MPN, value");
  const linkedLabel = useText("projects.bom.filter-linked", "Linked");
  const needsLinkLabel = useText("projects.bom.filter-needs-link", "Needs Link");
  const identityNeeded = useText("projects.identity-needed", "Identification Needed");
  const noFootprint = useText("projects.bom.no-footprint", "No footprint");
  return (
    <section className="hidden min-h-0 min-w-0 flex-col border-r border-line @[60rem]:flex">
      <div className="flex flex-none flex-wrap items-center gap-2 border-b border-line px-3 py-2.5">
        <SegmentedControl
          options={filters}
          value={filter}
          onChange={onFilterChange}
          size="small"
          aria-label={filterLabel}
        />
        <label className="relative ml-auto min-w-[180px] flex-1 max-[1180px]:min-w-0 @xl:max-w-[280px]">
          <span className="sr-only">
            <Text id="projects.bom.filter">Filter BOM</Text>
          </span>
          <span
            aria-hidden
            className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-t3"
          >
            <SearchIcon />
          </span>
          <input
            value={query}
            onChange={(event) => onQueryChange(event.target.value)}
            placeholder={searchPlaceholder}
            className="h-8 w-full rounded-control border border-line bg-field pl-8 pr-2 text-xs text-t1 outline-none placeholder:text-t3 focus:border-acc"
          />
        </label>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto">
        {lines.length ? (
          lines.map((line) => {
            const key = lineKey(line);
            const active = key === activeKey;
            return (
              <button
                type="button"
                key={key}
                onClick={() => onSelect(key)}
                className={
                  "relative grid w-full grid-cols-[36px_minmax(0,1fr)] " +
                  "items-start gap-2.5 border-b border-line px-3 py-2.5 text-left transition-colors " +
                  "focus-visible:z-10 focus-visible:outline focus-visible:outline-2 " +
                  "focus-visible:-outline-offset-2 focus-visible:outline-acc " +
                  (active ? "bg-raise2" : "hover:bg-raise")
                }
              >
                <span
                  aria-hidden
                  className={
                    "absolute inset-y-2 left-0 w-0.5 rounded-full " +
                    (active ? "bg-acc" : "bg-transparent")
                  }
                />
                <span className="pt-0.5 text-center font-mono text-sm font-semibold text-t1">
                  {line.final_qty}
                </span>
                <span className="min-w-0">
                  <span className="flex min-w-0 items-center gap-2">
                    <span className="min-w-0 flex-1 truncate text-sm font-semibold text-t1">
                      {line.mpn || line.value || identityNeeded}
                    </span>
                    <Badge size="sm" tone={line.in_library ? "ok" : "warn"}>
                      {line.in_library ? linkedLabel : needsLinkLabel}
                    </Badge>
                  </span>
                  <span className="mt-0.5 block truncate text-xs text-t3">
                    {line.refs.join(", ")}
                  </span>
                  <span className="mt-1 block truncate font-mono text-2xs text-t3">
                    {line.footprint || noFootprint}
                  </span>
                </span>
              </button>
            );
          })
        ) : (
          <CenteredMessage>
            <Text id="projects.bom.no-match">No BOM lines match this view.</Text>
          </CenteredMessage>
        )}
      </div>
    </section>
  );
}

function BomLineInspector({
  projectId,
  line,
  group,
  writable,
}: {
  projectId: string;
  line: ProjectBomLine | null;
  group: ProjectAssignmentGroup | undefined;
  writable: boolean;
}) {
  const assign = useAssignProjectGroup(projectId);
  const pricing = useJob<DigiKeyQuantityPricing>();
  const { toast } = useToast();
  const inspectorLabel = useText("projects.bom.inspector-aria", "BOM line details");
  const identityNeeded = useText("projects.identity-needed", "Identification Needed");
  const manufacturerMissing = useText(
    "projects.bom.manufacturer-missing",
    "Manufacturer not set",
  );
  const referencesLabel = useText("projects.bom.field-references", "References");
  const perBoardLabel = useText("projects.bom.field-per-board", "Per Board");
  const buildQuantityLabel = useText("projects.bom.field-build-quantity", "Build Count");
  const valueLabel = useText("projects.bom.field-value", "Value");
  const footprintLabel = useText("projects.bom.field-footprint", "Footprint");
  const packageLabel = useText("projects.bom.field-package", "Package");
  const partIdLabel = useText("projects.bom.field-part-id", "Part ID");
  const componentLinkTitle = useText("projects.bom.component-link", "Component Link");
  const notSet = useText("projects.bom.not-set", "Not set");
  const linkedLabel = useText("projects.bom.filter-linked", "Linked");
  const needsLinkLabel = useText("projects.bom.filter-needs-link", "Needs Link");
  const linkFailed = useText("projects.bom.toast-link-failed", "Could not link component");
  const pricingUnreadable = useText(
    "projects.bom.toast-pricing-failed",
    "Could not read DigiKey pricing.",
  );
  // Which references were linked is only known inside the mutation callback, so the sentence is
  // resolved here and formatted there.
  const groupLinked = useCopyFormatter("projects.bom.toast-linked", "{refs} linked");
  useEffect(() => pricing.reset(), [line?.mpn, line?.final_qty, pricing.reset]);

  async function checkPricing() {
    if (!line?.mpn || pricing.status === "running") return;
    try {
      const ref = await api.startDigiKeyQuantityPricing(line.mpn, line.final_qty, false);
      const final = await pricing.run(ref.job_id);
      if (final.status !== "done") {
        toast(final.error ?? pricingUnreadable, "err");
      }
    } catch (error) {
      toast(error instanceof Error ? error.message : pricingUnreadable, "err");
    }
  }
  if (!line) {
    return (
      <CenteredMessage>
        <Text id="projects.bom.select-line">Select a BOM line to inspect it.</Text>
      </CenteredMessage>
    );
  }

  return (
    <aside className="min-h-0 overflow-y-auto p-4" aria-label={inspectorLabel}>
      <div className="flex items-start gap-3">
        <div className="min-w-0 flex-1">
          <p className="text-xs font-semibold text-t3">
            <Text id="projects.bom.selected-line">Selected Line</Text>
          </p>
          <h3 className="mt-1 break-words text-lg font-semibold text-t1">
            {line.mpn || line.value || identityNeeded}
          </h3>
          <p className="mt-1 text-xs text-t3">
            {line.manufacturer || manufacturerMissing}
          </p>
        </div>
        <Badge tone={line.in_library ? "ok" : "warn"}>
          {line.in_library ? linkedLabel : needsLinkLabel}
        </Badge>
      </div>

      <ProjectInspectorFacts
        items={[
          { label: referencesLabel, value: line.refs.join(", "), mono: true },
          { label: perBoardLabel, value: line.qty, mono: true },
          { label: buildQuantityLabel, value: line.final_qty, mono: true },
          { label: valueLabel, value: line.value || notSet },
          { label: footprintLabel, value: line.footprint || notSet, mono: true },
          { label: packageLabel, value: line.package || notSet },
        ]}
      />

      {line.mpn ? (
        <section className="mt-4 border-t border-line pt-4">
          <div className="flex items-center justify-between gap-2">
            <SectionHeading>
              <Text id="projects.bom.digikey-pricing">DigiKey Price Breaks</Text>
            </SectionHeading>
            <Button small onClick={() => void checkPricing()} disabled={pricing.status === "running"}>
              {pricing.status === "running" ? (
                <Text id="projects.bom.checking">Checking...</Text>
              ) : (
                <Text id="projects.bom.check-pricing">Check Pricing</Text>
              )}
            </Button>
          </div>
          {pricing.result ? (
            pricing.result.options.length ? (
              <div className="mt-2 space-y-1">
                {pricing.result.options.map((option) => (
                  <div
                    key={`${option.product_number}:${option.packaging}`}
                    className="flex items-start justify-between gap-3 rounded-control bg-field px-2.5 py-2 text-xs"
                  >
                    <div className="min-w-0">
                      <p className="truncate font-medium text-t1">
                        {option.product_number || line.mpn}
                      </p>
                      <p className="truncate text-2xs text-t3">
                        {option.packaging || "Standard packaging"}
                      </p>
                    </div>
                    <p className="flex-none font-mono text-t1">
                      {option.currency} {option.unit_price.toFixed(4)}
                    </p>
                  </div>
                ))}
              </div>
            ) : (
              <p className="mt-2 text-xs text-t3">
                <Text id="projects.bom.no-pricing-option">
                  No pricing option was returned for this count.
                </Text>
              </p>
            )
          ) : (
            <p className="mt-2 text-xs leading-5 text-t3">
              <Text id="projects.bom.exact-quantity">
                Uses the exact build count. DigiReel is not requested until an order is prepared.
              </Text>
            </p>
          )}
        </section>
      ) : null}

      {!line.in_library ? (
        <div className="mt-4">
          <SectionHeading>
            <Text id="projects.bom.link-component">Link Component</Text>
          </SectionHeading>
          <p className="mt-1 text-xs leading-5 text-t3">
            <Text id="projects.bom.link-scope" values={{ count: line.final_qty }}>
              {"Applies to all {count} matching placements."}
            </Text>
          </p>
          {!writable ? (
            <p className="mt-3 rounded-card border border-line bg-field p-3 text-xs leading-5 text-t3">
              <Text id="projects.bom.link-storage">
                Component links are saved with this project.
              </Text>
            </p>
          ) : null}
          {group?.candidates.length ? (
            <div className="mt-3 space-y-2">
              {group.candidates.map((candidate) => (
                <button
                  type="button"
                  key={candidate.part_id}
                  disabled={assign.isPending}
                  onClick={() =>
                    assign.mutate(
                      { refs: group.refs, partId: candidate.part_id },
                      {
                        onSuccess: () =>
                          toast(groupLinked({ refs: group.refs.join(", ") }), "ok"),
                        onError: (error) =>
                          toast(
                            error instanceof Error ? error.message : linkFailed,
                            "err",
                          ),
                      },
                    )
                  }
                  className="w-full rounded-card border border-line bg-surface p-3 text-left transition-colors hover:border-line2 hover:bg-raise focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-acc disabled:opacity-50"
                >
                  <span className="block text-sm font-semibold text-t1">
                    {candidate.mpn || candidate.display_name}
                  </span>
                  <span className="mt-1 block text-xs text-t2">
                    {candidate.display_name}
                  </span>
                  <span className="mt-2 flex flex-wrap gap-1">
                    <Badge size="sm" tone="neutral">
                      {candidate.confidence.replaceAll("+", " + ")}
                    </Badge>
                    {candidate.distinguish.map((fact) => (
                      <Badge key={fact} size="sm" tone="neutral">
                        {fact}
                      </Badge>
                    ))}
                  </span>
                </button>
              ))}
            </div>
          ) : (
            <p className="mt-3 rounded-card border border-line bg-field p-3 text-xs leading-5 text-t3">
              <Text id="projects.bom.no-candidate">
                No safe match found. Add the exact part in Components, then link it here.
              </Text>
            </p>
          )}
        </div>
      ) : (
        <section className="mt-5 border-t border-line pt-4">
          <SectionHeading>{componentLinkTitle}</SectionHeading>
          <ProjectInspectorFacts
            className="mt-3"
            items={[
              {
                label: partIdLabel,
                value: line.library_part_id || notSet,
                mono: true,
              },
            ]}
          />
          <p className="mt-2 text-xs leading-5 text-t3">
            <Text id="projects.bom.link-detail">
              The BOM and Build use this component. Reviews validate it.
            </Text>
          </p>
        </section>
      )}
    </aside>
  );
}

function CenteredMessage({
  children,
  tone = "neutral",
}: {
  children: React.ReactNode;
  tone?: "neutral" | "err";
}) {
  return (
    <div
      className={`flex min-h-[220px] flex-1 items-center justify-center p-6 text-center text-sm ${
        tone === "err" ? "text-err-text" : "text-t3"
      }`}
    >
      {children}
    </div>
  );
}

function lineKey(line: ProjectBomLine) {
  return `${line.refs.join("|")}:${line.mpn}:${line.footprint}`;
}

function findGroup(groups: ProjectAssignmentGroup[], line: ProjectBomLine) {
  // The line's references are scanned once per group otherwise, and a group carries one entry
  // per reference. Membership is the only question asked, so a set answers it directly.
  const lineRefs = new Set(line.refs);
  return groups.find((group) => group.refs.some((ref) => lineRefs.has(ref)));
}
