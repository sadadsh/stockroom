/**
 * The full-screen modular search (north-star search.html): a big query field, a live
 * active-filter chip bar, a facet rail generated from the parts' own parametric facets, and an
 * evidence-first results table. Identity, match evidence, package, lifecycle, and dual-EDA status
 * keep stable roles; up to two populated category parameters join them when room permits. Opens
 * (Ctrl+K or the Components search field), closes on Esc; ↑/↓ move the selection, ↵ opens a part.
 */
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import {
  observeElementRect,
  useVirtualizer,
} from "@tanstack/react-virtual";
import type { ParametricFacet, SearchRow } from "../api/types";
import { useFacetsQuery, useParametricFacets, useSearchQuery } from "../api/queries";
import {
  activeChips,
  applyClientFilters,
  cellValue,
  clearAll,
  deriveColumns,
  emptyFilters,
  formatMagnitude,
  hasAnyFilter,
  PRICE_KEY,
  isOptionOn,
  makeScale,
  normalizeUnit,
  parseMagnitude,
  rowPrimaryValue,
  rowMergedValue,
  sectionedRail,
  setRange,
  type RailSection as RailSectionData,
  type Scale,
  toSpecParams,
  toggleOption,
  type RangeSel,
  type SearchFilters,
  type SpecColumn,
  VALUE_COLUMN_KEY,
} from "../lib/searchFilters";
import { prettifyValue } from "../lib/specSchema";
import { SearchIcon } from "./icons";
import { Icon } from "./Icon";
import { PanelTitle } from "./primitives";
import { RowThumbnail } from "./PartsList";
import {
  readUiSession,
  updateUiSession,
  type SearchSortState,
} from "../lib/uiSession";
import { SEARCH_FACET_RAIL_WIDTH } from "../lib/libraryLayout";

// --- small inline glyphs (the artifact's own set) ---------------------------
// Each helper keeps its wrapper + className passthrough so every call site is unchanged, but now
// draws through <Icon id> so the glyph is inspectable / editable in dev mode. The weight / caps
// live in the registry entry; the sizes still come from the call sites via className.
const Chevron = ({ className = "" }: { className?: string }) => (
  <Icon id="overlay.chevron" className={className} />
);
const Check = () => <Icon id="overlay.check" className="h-2.5 w-2.5" />;
const XSmall = () => <Icon id="overlay.close" className="h-2.5 w-2.5" />;
const Spark = ({ className = "" }: { className?: string }) => (
  <Icon id="overlay.spark" className={className} />
);

interface Props {
  onClose: () => void;
  // opening a part carries its category so the picker can scope to it and reveal the selection
  onOpenPart: (id: string, category: string) => void;
}

type SortKey = { kind: "name" } | { kind: "stock" } | { kind: "unit" } | { kind: "spec"; key: string; numeric: boolean };
const SEARCH_QUERY_DEBOUNCE_MS = 120;

export function SearchOverlay({ onClose, onOpenPart }: Props) {
  const [q, setQ] = useState(() => readUiSession().search_filters.query);
  const [filters, setFilters] = useState<SearchFilters>(() =>
    filtersFromSession(),
  );
  const [sort, setSort] = useState<{ key: SortKey; dir: "asc" | "desc" }>(() =>
    sortFromSession(readUiSession().search_sort),
  );
  const [activeId, setActiveId] = useState<string | null>(
    () => readUiSession().search_results.active_part_id,
  );
  const inputRef = useRef<HTMLInputElement>(null);
  const [resultsScrollElement, setResultsScrollElement] =
    useState<HTMLDivElement | null>(null);
  const restoredResultsOffset = useRef(
    readUiSession().search_results.offset_px,
  ).current;

  const category = filters.category;
  const spec = useMemo(() => toSpecParams(filters), [filters]);
  const debouncedQuery = useDebouncedValue(q, SEARCH_QUERY_DEBOUNCE_MS);
  const categoryFacets = useFacetsQuery();
  // pass the live spec selections so the rail's counts narrow as you pick (faceted search)
  const paramFacets = useParametricFacets({
    q: debouncedQuery,
    category,
    spec,
  });
  const searchResults = useSearchQuery({
    q: debouncedQuery,
    category,
    spec,
  });

  const facets = paramFacets.data?.facets ?? [];
  const serverRows = searchResults.data?.parts ?? [];
  // the sourcing-derived Unit Price facet (not a spec) is synthesized from the rows and filtered
  // client-side; it rides the rail alongside the spec facets but never a column.
  const priceFacet = useMemo(() => makePriceFacet(serverRows), [serverRows]);
  const railFacets = useMemo(
    () => (priceFacet ? [...facets, priceFacet] : facets),
    [facets, priceFacet],
  );
  const sections = useMemo(() => sectionedRail(railFacets, category), [railFacets, category]);
  const candidateColumns = useMemo(
    () =>
      deriveColumns(facets, category, 2).filter(
        (column) => !isFixedEvidenceColumn(column),
      ),
    [facets, category],
  );
  const chips = useMemo(() => activeChips(filters, railFacets), [filters, railFacets]);

  const rows = useMemo(
    () => sortRows(applyClientFilters(serverRows, filters), sort, candidateColumns),
    [serverRows, filters, sort, candidateColumns],
  );
  // An all-empty parameter column is not a column; it is unused canvas filled with em dashes.
  const columns = useMemo(
    () =>
      candidateColumns.filter((column) =>
        rows.some((row) => resultSpecValue(row, column) !== ""),
      ),
    [candidateColumns, rows],
  );
  const active = useMemo(() => {
    const index = activeId
      ? rows.findIndex((row) => row.id === activeId)
      : -1;
    return index >= 0 ? index : rows.length > 0 ? 0 : -1;
  }, [activeId, rows]);
  const activePartId = active >= 0 ? rows[active]?.id ?? null : null;
  const activeIdRef = useRef(activePartId);
  activeIdRef.current = activePartId;

  // Focus the field on open. Selection is identity-based rather than
  // index-based, so a client-side sort cannot silently select another part.
  useEffect(() => inputRef.current?.focus(), []);
  useEffect(() => {
    if (searchResults.isLoading) return;
    if (activePartId !== activeId) setActiveId(activePartId);
  }, [activeId, activePartId, searchResults.isLoading]);

  // Persist the parametric state in its normalized wire form. Dynamic facet
  // bags become bounded key/value arrays, so neither the frontend nor backend
  // accepts hidden arbitrary fields.
  useEffect(() => {
    const current = readUiSession();
    const nextFilters = filtersToSession(q, filters);
    const nextSort = sortToSession(sort);
    if (
      JSON.stringify(current.search_filters) === JSON.stringify(nextFilters) &&
      JSON.stringify(current.search_sort) === JSON.stringify(nextSort) &&
      current.search_results.active_part_id === activePartId
    ) {
      return;
    }
    updateUiSession((snapshot) => ({
      ...snapshot,
      search_filters: nextFilters,
      search_sort: nextSort,
      search_results: {
        ...snapshot.search_results,
        active_part_id: activePartId,
      },
    }));
  }, [activePartId, filters, q, sort]);

  useEffect(() => {
    const element = resultsScrollElement;
    if (!element) return;
    if (element.scrollTop !== restoredResultsOffset) {
      element.scrollTop = restoredResultsOffset;
    }
    let pending: number | null = null;
    const checkpoint = () => {
      pending = null;
      const current = readUiSession();
      const offset = Math.max(0, Math.round(element.scrollTop));
      const anchor = activeIdRef.current;
      if (
        current.search_results.offset_px === offset &&
        current.search_results.anchor_part_id === anchor
      ) {
        return;
      }
      updateUiSession((snapshot) => ({
        ...snapshot,
        search_results: {
          ...snapshot.search_results,
          anchor_part_id: anchor,
          offset_px: offset,
        },
      }));
    };
    const onScroll = () => {
      if (pending !== null) window.clearTimeout(pending);
      pending = window.setTimeout(checkpoint, 40);
    };
    element.addEventListener("scroll", onScroll, { passive: true });
    return () => {
      element.removeEventListener("scroll", onScroll);
      if (pending !== null) window.clearTimeout(pending);
      checkpoint();
    };
  }, [restoredResultsOffset, resultsScrollElement]);

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") {
        e.preventDefault();
        onClose();
      } else if (e.key === "ArrowDown") {
        e.preventDefault();
        const next = Math.min(Math.max(active, 0) + 1, rows.length - 1);
        setActiveId(rows[next]?.id ?? null);
      } else if (e.key === "ArrowUp") {
        e.preventDefault();
        const next = Math.max(active - 1, 0);
        setActiveId(rows[next]?.id ?? null);
      } else if (e.key === "PageDown") {
        e.preventDefault();
        const next = Math.min(Math.max(active, 0) + 10, rows.length - 1);
        setActiveId(rows[next]?.id ?? null);
      } else if (e.key === "PageUp") {
        e.preventDefault();
        const next = Math.max(active - 10, 0);
        setActiveId(rows[next]?.id ?? null);
      } else if (e.key === "Home" && rows.length > 0) {
        e.preventDefault();
        setActiveId(rows[0].id);
      } else if (e.key === "End" && rows.length > 0) {
        e.preventDefault();
        setActiveId(rows[rows.length - 1].id);
      } else if (e.key === "Enter" && rows[active]) {
        e.preventDefault();
        onOpenPart(rows[active].id, rows[active].category);
      }
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [rows, active, onClose, onOpenPart]);

  const categories = categoryFacets.data
    ? Object.entries(categoryFacets.data.by_category).sort((a, b) => a[0].localeCompare(b[0]))
    : [];
  const shown = rows.length;

  return (
    // bg-canvas, not bg-surface: --c-surface is a ~1.6%-alpha WASH meant to sit on top of
    // an opaque parent inside the normal flow. This element is position:fixed, so it paints
    // above all app content with nothing opaque behind it -- the wash let the components
    // list and detail panel show straight through, which is why the overlay was unusable.
    // Every other modal escapes this by pairing an opaque popover card with a scrim; this
    // is the one full-screen surface with neither, so it needs a real opaque base.
    <div className="fixed inset-0 z-[100] flex flex-col bg-canvas" data-dev-id="search.root">
      {/* top band: the overlay's title strip with the docked query field + the close affordance,
          the same band + hairline family as every other panel header so the overlay reads as a
          docked workspace, not a floating spotlight */}
      <div className="flex h-[38px] flex-none items-center gap-3 border-b border-line bg-band px-3.5">
        <span className="hidden flex-none text-xs font-semibold text-t2 sm:inline">
          Parametric Search
        </span>
        <div
          className="flex h-[26px] min-w-0 flex-1 items-center gap-2 rounded-control border border-line bg-field px-2.5 focus-within:border-acc"
          data-dev-id="search.query"
        >
          <SearchIcon className="h-3.5 w-3.5 flex-none text-t3" />
          <input
            ref={inputRef}
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Search components using a name, MPN, value, or specification..."
            aria-label="Search components"
            data-dev-id="search.query-input"
            className="min-w-0 flex-1 bg-transparent text-sm text-t1 outline-none placeholder:text-t3"
          />
          {q ? (
            <button
              type="button"
              onClick={() => setQ("")}
              aria-label="Clear search"
              className="grid h-[18px] w-[18px] flex-none place-items-center rounded-control text-t3 hover:bg-raise2 hover:text-t1"
            >
              <XSmall />
            </button>
          ) : null}
        </div>
        <button
          type="button"
          onClick={onClose}
          className="ml-auto flex h-[26px] flex-none items-center gap-2 rounded-control border border-line bg-raise px-2.5 text-xs font-semibold text-t2 hover:bg-raise2 hover:text-t1"
          data-dev-id="search.close"
        >
          Close
          <kbd className="inline-flex h-[16px] min-w-[20px] items-center justify-center rounded-control border border-line2 bg-raise2 px-1 font-mono text-2xs font-medium text-t2">
            Esc
          </kbd>
        </button>
      </div>

      {/* sub-strip: result count, the active-filter chips, and the sort control */}
      <div
        className="flex min-h-[34px] flex-none flex-wrap items-center gap-x-3 gap-y-1 border-b border-line bg-surface px-3.5 py-1"
        data-dev-id="search.subbar"
      >
        <span className="flex-none text-sm font-bold text-t1" data-dev-id="search.result-count">
          {searchResults.isLoading ? "…" : shown}
          <span className="ml-1.5 text-xs font-medium text-t3">
            {shown === 1 ? "result" : "results"}
          </span>
        </span>
        <div className="flex min-w-0 flex-1 flex-wrap items-center gap-1.5" data-dev-id="search.chips">
          {chips.map((chip) => (
            <span
              key={chip.id}
              className="inline-flex items-center gap-1.5 rounded-control border border-line bg-raise2 py-0.5 pl-2 pr-1 text-xs font-semibold text-t1"
            >
              <span className="font-medium text-t3">{chip.keyLabel}:</span>
              {chip.value}
              <button
                type="button"
                onClick={() => setFilters(chip.remove)}
                aria-label={`Remove ${chip.keyLabel} filter`}
                className="grid h-4 w-4 place-items-center rounded-control text-t3 hover:bg-line2 hover:text-t1"
              >
                <XSmall />
              </button>
            </span>
          ))}
          {hasAnyFilter(filters) ? (
            <button
              type="button"
              onClick={() => setFilters(clearAll(filters))}
              className="text-xs font-semibold text-t2 hover:text-t1"
            >
              Clear All
            </button>
          ) : null}
        </div>
        <SortControl sort={sort} setSort={setSort} columns={columns} />
      </div>

      {/* main: the schema-driven facet rail + the results grid, border-split docked panes */}
      <div
        className="grid min-h-0 flex-1"
        style={{
          gridTemplateColumns: `${SEARCH_FACET_RAIL_WIDTH} minmax(0, 1fr)`,
        }}
      >
        <FacetRail
          categories={categories}
          category={category}
          onCategory={(name) =>
            setFilters((f) => ({ ...emptyFilters(), inStock: f.inStock, category: name }))
          }
          sections={sections}
          filters={filters}
          setFilters={setFilters}
          activeCount={chips.length}
        />

        <div className="flex min-h-0 min-w-0 flex-col border-l border-line">
          <PanelTitle>Results</PanelTitle>
          <div
            ref={setResultsScrollElement}
            className="min-h-0 flex-1 overflow-auto"
            data-dev-id="search.results"
          >
            <ResultsTable
              rows={rows}
              columns={columns}
              query={q}
              active={active}
              onHover={(index) => setActiveId(rows[index]?.id ?? null)}
              onOpen={onOpenPart}
              loading={searchResults.isLoading}
              scrollElement={resultsScrollElement}
              initialOffset={restoredResultsOffset}
            />
          </div>
        </div>
      </div>

      {/* bottom: the overlay's own status-bar band, full width like the shell's */}
      <div
        className="flex h-[24px] flex-none items-center gap-4 border-t border-line bg-band px-3 text-2xs text-t3"
        data-dev-id="search.footer"
      >
        <KbdHint keys={["↑", "↓"]} label="Navigate" />
        <KbdHint keys={["↵"]} label="Open Part" />
        <KbdHint keys={["Esc"]} label="Close" />
      </div>
    </div>
  );
}

function useDebouncedValue<T>(value: T, delay: number): T {
  const [settled, setSettled] = useState(value);
  useEffect(() => {
    const timeout = window.setTimeout(() => setSettled(value), delay);
    return () => window.clearTimeout(timeout);
  }, [delay, value]);
  return settled;
}

function filtersFromSession(): SearchFilters {
  const saved = readUiSession().search_filters;
  return {
    category: saved.category,
    inStock: saved.in_stock,
    options: Object.fromEntries(saved.options.map((item) => [item.key, [...item.values]])),
    ranges: Object.fromEntries(
      saved.ranges.map((item) => [item.key, { min: item.min, max: item.max }]),
    ),
  };
}

function filtersToSession(q: string, filters: SearchFilters) {
  return {
    query: q,
    category: filters.category,
    in_stock: filters.inStock,
    options: Object.entries(filters.options)
      .sort(([left], [right]) => left.localeCompare(right))
      .map(([key, values]) => ({ key, values: [...values] })),
    ranges: Object.entries(filters.ranges)
      .sort(([left], [right]) => left.localeCompare(right))
      .map(([key, range]) => ({ key, min: range.min, max: range.max })),
  };
}

function sortFromSession(
  saved: SearchSortState,
): { key: SortKey; dir: "asc" | "desc" } {
  if (saved.kind === "spec") {
    return {
      key: { kind: "spec", key: saved.key, numeric: saved.numeric },
      dir: saved.direction,
    };
  }
  return { key: { kind: saved.kind }, dir: saved.direction };
}

function sortToSession(sort: {
  key: SortKey;
  dir: "asc" | "desc";
}): SearchSortState {
  return sort.key.kind === "spec"
    ? {
        kind: "spec",
        key: sort.key.key,
        numeric: sort.key.numeric,
        direction: sort.dir,
      }
    : { kind: sort.key.kind, direction: sort.dir };
}

function KbdHint({ keys, label }: { keys: string[]; label: string }) {
  return (
    <span className="inline-flex items-center gap-1.5">
      {keys.map((k) => (
        <kbd
          key={k}
          className="inline-flex h-[18px] min-w-[20px] items-center justify-center rounded-control border border-line2 bg-raise2 px-1.5 font-mono text-2xs font-medium text-t2"
        >
          {k}
        </kbd>
      ))}
      {label}
    </span>
  );
}

// The Unit Price facet, synthesized from the rows' sourcing (it is not a spec, so the backend
// facets can never produce it). Null when too few rows carry a price to make a meaningful range.
function makePriceFacet(rows: SearchRow[]): ParametricFacet | null {
  const prices = rows
    .map((r) => r.unit_price)
    .filter((p): p is number => p != null && p > 0);
  if (prices.length < 2) return null;
  const min = Math.min(...prices);
  const max = Math.max(...prices);
  if (min === max) return null;
  return {
    key: PRICE_KEY,
    label: "Unit Price",
    kind: "range",
    count: prices.length,
    min,
    max,
    unit: "$",
  };
}

// --- sort ------------------------------------------------------------------

function sortRows(
  rows: SearchRow[],
  sort: { key: SortKey; dir: "asc" | "desc" },
  columns: SpecColumn[],
): SearchRow[] {
  const sign = sort.dir === "asc" ? 1 : -1;
  const cmp = (a: SearchRow, b: SearchRow): number => {
    switch (sort.key.kind) {
      case "name":
        return a.display_name.localeCompare(b.display_name) * sign;
      case "stock":
        return num(a.stock, b.stock) * sign;
      case "unit":
        return num(a.unit_price, b.unit_price) * sign;
      case "spec": {
        const { key, numeric } = sort.key;
        // The synthetic Value column has no real spec key: resolve each row's own primary value
        // and compare as text (its units are mixed across categories, so a magnitude sort is
        // meaningless). Keeps Value a first-class, sortable spec-style column.
        if (key === VALUE_COLUMN_KEY) {
          return (
            rowPrimaryValue(a.category, a.specs).localeCompare(
              rowPrimaryValue(b.category, b.specs),
            ) * sign
          );
        }
        const av = a.specs[key];
        const bv = b.specs[key];
        if (numeric) {
          return num(
            av == null ? null : parseMagnitude(String(av)),
            bv == null ? null : parseMagnitude(String(bv)),
          ) * sign;
        }
        return String(av ?? "").localeCompare(String(bv ?? "")) * sign;
      }
    }
  };
  void columns;
  return [...rows].sort(cmp);
}

// A null-safe numeric compare that always sinks missing values to the bottom.
function num(a: number | null, b: number | null): number {
  if (a == null && b == null) return 0;
  if (a == null) return 1;
  if (b == null) return -1;
  return a - b;
}

function SortControl({
  sort,
  setSort,
  columns,
}: {
  sort: { key: SortKey; dir: "asc" | "desc" };
  setSort: (s: { key: SortKey; dir: "asc" | "desc" }) => void;
  columns: SpecColumn[];
}) {
  const [open, setOpen] = useState(false);
  const options: { label: string; key: SortKey }[] = [
    { label: "Name", key: { kind: "name" } },
    ...columns.map((c) => ({
      label: c.label,
      key: { kind: "spec" as const, key: c.key, numeric: c.numeric },
    })),
    { label: "In Stock", key: { kind: "stock" } },
    { label: "Unit Price", key: { kind: "unit" } },
  ];
  const current = options.find((o) => sameKey(o.key, sort.key))?.label ?? "Name";
  return (
    <div className="relative flex-none">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex h-[26px] items-center gap-1.5 rounded-control border border-line bg-raise px-2.5 text-xs font-medium text-t2 hover:bg-raise2 hover:text-t1"
        data-dev-id="search.sort"
      >
        Sort <b className="font-semibold text-t1">{current}</b>
        <Chevron className="h-3 w-3 text-t3" />
      </button>
      {open ? (
        <>
          <button
            type="button"
            aria-hidden
            tabIndex={-1}
            className="fixed inset-0 z-[1] cursor-default"
            onClick={() => setOpen(false)}
          />
          <div className="absolute right-0 top-[calc(100%+6px)] z-[2] w-44 rounded-control border border-line2 bg-popover p-1 shadow-pop">
            {options.map((o) => {
              const on = sameKey(o.key, sort.key);
              return (
                <button
                  key={o.label}
                  type="button"
                  onClick={() => {
                    setSort({ key: o.key, dir: on && sort.dir === "asc" ? "desc" : "asc" });
                    setOpen(false);
                  }}
                  className={
                    "flex w-full items-center justify-between rounded-control px-2.5 py-1.5 text-left text-sm " +
                    (on ? "bg-raise2 font-semibold text-t1" : "text-t2 hover:bg-raise2 hover:text-t1")
                  }
                >
                  {o.label}
                  {on ? <span className="font-mono text-2xs text-t3">{sort.dir === "asc" ? "↑" : "↓"}</span> : null}
                </button>
              );
            })}
          </div>
        </>
      ) : null}
    </div>
  );
}

function sameKey(a: SortKey, b: SortKey): boolean {
  if (a.kind !== b.kind) return false;
  if (a.kind === "spec" && b.kind === "spec") return a.key === b.key;
  return true;
}

// --- facet rail ------------------------------------------------------------

function FacetRail({
  categories,
  category,
  onCategory,
  sections,
  filters,
  setFilters,
  activeCount,
}: {
  categories: [string, number][];
  category: string | null;
  onCategory: (name: string | null) => void;
  sections: RailSectionData[];
  filters: SearchFilters;
  setFilters: (updater: (f: SearchFilters) => SearchFilters) => void;
  activeCount: number;
}) {
  return (
    <div className="flex min-h-0 flex-col" data-dev-id="search.rail">
      <PanelTitle right={activeCount > 0 ? `${activeCount} active` : undefined}>
        Filters
      </PanelTitle>
      <div className="min-h-0 flex-1 overflow-y-auto px-3 pb-2 pt-1">
        <FacetGroup title="Category" first data-dev-id="search.rail-category">
          {categories.map(([name, count]) => (
            <OptionRow
              key={name}
              label={name}
              count={count}
              on={category === name}
              onToggle={() => onCategory(category === name ? null : name)}
            />
          ))}
          {categories.length === 0 ? (
            <div className="py-2 text-xs text-t3">No categories so far.</div>
          ) : null}
        </FacetGroup>

        {sections.length === 0 ? (
          <>
            <RailSection label={category ? `${category} Parameters` : "Parameters"} fromSpecs />
            <div className="px-0.5 py-3 text-xs text-t3">
              No parametric specs to filter on so far.
            </div>
          </>
        ) : (
          sections.map((sec) => (
            <div key={sec.title} data-dev-id="search.rail-facet">
              <RailSection label={sec.title} fromSpecs={sec.fromSpecs} />
              {sec.facets.map((facet, idx) =>
                facet.kind === "range" ? (
                  <RangeFacet
                    key={facet.key}
                    facet={facet}
                    first={idx === 0}
                    sel={filters.ranges[facet.key] ?? null}
                    onChange={(sel) => setFilters((f) => setRange(f, facet.key, sel))}
                  />
                ) : (
                  <OptionFacet
                    key={facet.key}
                    facet={facet}
                    first={idx === 0}
                    filters={filters}
                    setFilters={setFilters}
                  />
                ),
              )}
            </div>
          ))
        )}

        <div className="mt-3.5 flex gap-2 border-t border-line pt-3 text-2xs leading-relaxed text-t3">
          <Spark className="mt-0.5 h-3 w-3 flex-none" />
          <span>
            Filters are generated from each part's specs. Add a component with a new parameter
            and it becomes a filter here on its own.
          </span>
        </div>
      </div>

      <div className="flex-none border-t border-line px-3 py-2">
        <button
          type="button"
          aria-pressed={filters.inStock}
          onClick={() => setFilters((f) => ({ ...f, inStock: !f.inStock }))}
          className={
            "flex w-full items-center gap-2.5 py-[3px] text-left text-sm font-medium " +
            (filters.inStock ? "text-t1" : "text-t2 hover:text-t1")
          }
          data-dev-id="search.rail-instock"
        >
          <span
            className={
              "grid h-4 w-4 flex-none place-items-center rounded-control border-[1.5px] " +
              (filters.inStock
                ? "border-acc bg-acc text-acc-on"
                : "border-line2 bg-field text-transparent")
            }
          >
            <Check />
          </span>
          In Stock
        </button>
      </div>
    </div>
  );
}

function RailSection({ label, fromSpecs }: { label: string; fromSpecs?: boolean }) {
  return (
    <div className="flex items-center gap-2 pb-0.5 pt-5 text-ui-caption font-semibold text-copy first:pt-0.5">
      {label}
      {fromSpecs ? (
        <span
          className="inline-flex flex-none items-center gap-1 whitespace-nowrap rounded-control bg-acc-soft px-1.5 py-0.5 text-ui-meta font-semibold text-copy"
          title="These filters are generated from the category's part specs"
        >
          <Spark className="h-2.5 w-2.5" />
          From Specifications
        </span>
      ) : null}
      <span className="h-px flex-1 bg-line" />
    </div>
  );
}

function FacetGroup({
  title,
  unit,
  first,
  children,
  "data-dev-id": devId,
}: {
  title: string;
  unit?: string | null;
  first?: boolean;
  children: React.ReactNode;
  "data-dev-id"?: string;
}) {
  const [open, setOpen] = useState(true);
  return (
    <div className={"px-0.5 pb-1 pt-2.5 " + (first ? "" : "border-t border-line")} data-dev-id={devId}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="mb-2 flex w-full items-center text-sm font-semibold text-t1"
      >
        {title}
        {unit ? <span className="ml-auto mr-2 font-mono text-2xs font-medium text-t3">{unit}</span> : null}
        <Chevron className={"h-3 w-3 text-t3 transition-transform " + (open ? "" : "-rotate-90") + (unit ? "" : " ml-auto")} />
      </button>
      {open ? children : null}
    </div>
  );
}

function OptionRow({
  label,
  count,
  on,
  onToggle,
}: {
  label: string;
  count: number;
  on: boolean;
  onToggle: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onToggle}
      className={
        "flex w-full items-center gap-2.5 py-[4.5px] text-left text-sm " +
        (on ? "text-t1" : "text-t2 hover:text-t1")
      }
    >
      <span
        className={
          "grid h-4 w-4 flex-none place-items-center rounded-control border-[1.5px] " +
          (on ? "border-acc bg-acc text-acc-on" : "border-line2 bg-field text-transparent")
        }
      >
        <Check />
      </span>
      <span className="min-w-0 flex-1 truncate">{label}</span>
      <span className="tnum flex-none font-mono text-xs text-t3">{count}</span>
    </button>
  );
}

function OptionFacet({
  facet,
  first,
  filters,
  setFilters,
}: {
  facet: ParametricFacet;
  first?: boolean;
  filters: SearchFilters;
  setFilters: (updater: (f: SearchFilters) => SearchFilters) => void;
}) {
  const opts = facet.options ?? [];
  return (
    <FacetGroup title={facet.label} first={first}>
      {/* every value is shown - no "show more" gate; a long list just scrolls in place so the
          rail narrows live as selections are made rather than hiding options up front */}
      <div className={opts.length > 8 ? "max-h-[184px] overflow-y-auto pr-1" : ""}>
        {opts.map((o) => (
          <OptionRow
            key={o.value}
            label={prettifyValue(o.value)}
            count={o.count}
            on={isOptionOn(filters, facet.key, o.value)}
            onToggle={() => setFilters((f) => toggleOption(f, facet.key, o.value))}
          />
        ))}
      </div>
    </FacetGroup>
  );
}

// --- range facet + dual-thumb slider ---------------------------------------

function RangeFacet({
  facet,
  first,
  sel,
  onChange,
}: {
  facet: ParametricFacet;
  first?: boolean;
  sel: RangeSel | null;
  onChange: (sel: RangeSel) => void;
}) {
  const fmin = facet.min ?? 0;
  const fmax = facet.max ?? 1;
  const lo = sel?.min ?? fmin;
  const hi = sel?.max ?? fmax;
  const unit = normalizeUnit(facet.unit);
  // Keep the hook count stable as live facet data changes. A degenerate range
  // has no truthful slider scale, so it becomes a read-only value below.
  const scale = useMemo(
    () =>
      Number.isFinite(fmin) && Number.isFinite(fmax) && fmin < fmax
        ? makeScale(fmin, fmax)
        : null,
    [fmin, fmax],
  );
  if (!Number.isFinite(fmin) || !Number.isFinite(fmax) || fmin > fmax) return null;
  if (fmin === fmax) {
    return (
      <FacetGroup title={facet.label} unit={unit} first={first}>
        <div
          data-dev-id="search.single-value-facet"
          className="flex items-baseline justify-between py-1 text-xs"
        >
          <span className="text-t3">Only value</span>
          <span className="font-mono font-medium text-t1">
            {formatMagnitude(fmin, unit)}
          </span>
        </div>
      </FacetGroup>
    );
  }
  return (
    <FacetGroup title={facet.label} unit={unit} first={first}>
      <div className="mb-2 flex justify-between font-mono text-xs text-t2">
        <span>{formatMagnitude(lo, unit)}</span>
        <span>{formatMagnitude(hi, unit)}</span>
      </div>
      <RangeSlider
        scale={scale!}
        lo={lo}
        hi={hi}
        onChange={(nlo, nhi) =>
          onChange({
            min: nlo <= fmin ? null : nlo,
            max: nhi >= fmax ? null : nhi,
          })
        }
      />
      <div className="mt-2 flex justify-between px-1.5 font-mono text-2xs text-t3">
        {scale!.ticks.map((t, i) => (
          <span key={i}>{formatMagnitude(t, unit)}</span>
        ))}
      </div>
      <div className="mt-2.5 grid grid-cols-2 gap-2">
        <RangeInput value={lo} unit={unit} onCommit={(v) => onChange({ min: v <= fmin ? null : v, max: sel?.max ?? null })} />
        <RangeInput value={hi} unit={unit} onCommit={(v) => onChange({ min: sel?.min ?? null, max: v >= fmax ? null : v })} />
      </div>
    </FacetGroup>
  );
}

function RangeInput({
  value,
  unit,
  onCommit,
}: {
  value: number;
  unit: string;
  onCommit: (v: number) => void;
}) {
  // Show an engineering value ("22 µF", "1 MΩ") that round-trips through parseMagnitude, so the
  // field never reads "0.000022"; a bare number the user types (no unit) is taken verbatim.
  const [text, setText] = useState(() => formatMagnitude(value, unit));
  useEffect(() => setText(formatMagnitude(value, unit)), [value, unit]);
  const commit = () => {
    const v = parseMagnitude(text);
    const n = v ?? parseFloat(text);
    if (Number.isFinite(n)) onCommit(n);
    else setText(formatMagnitude(value, unit));
  };
  return (
    <input
      value={text}
      onChange={(e) => setText(e.target.value)}
      onBlur={commit}
      onKeyDown={(e) => e.key === "Enter" && commit()}
      className="h-[26px] w-full min-w-0 rounded-control border border-line bg-field px-2.5 text-center font-mono text-xs text-t1 outline-none focus:border-line2"
    />
  );
}

function RangeSlider({
  scale,
  lo,
  hi,
  onChange,
}: {
  scale: Scale;
  lo: number;
  hi: number;
  onChange: (lo: number, hi: number) => void;
}) {
  const trackRef = useRef<HTMLDivElement>(null);
  const loPct = scale.toPct(lo);
  const hiPct = scale.toPct(hi);

  const drag = (which: "lo" | "hi") => (e: React.PointerEvent) => {
    e.preventDefault();
    (e.target as HTMLElement).setPointerCapture(e.pointerId);
    const move = (clientX: number) => {
      const rect = trackRef.current?.getBoundingClientRect();
      if (!rect) return;
      const p = ((clientX - rect.left) / rect.width) * 100;
      const v = scale.fromPct(p);
      if (which === "lo") onChange(Math.min(v, hi), hi);
      else onChange(lo, Math.max(v, lo));
    };
    const onMove = (ev: PointerEvent) => move(ev.clientX);
    const onUp = () => {
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
    };
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
  };

  return (
    <div ref={trackRef} className="relative mx-2 h-[3px] bg-line">
      <div
        className="absolute h-full bg-t2"
        style={{ left: `${loPct}%`, right: `${100 - hiPct}%` }}
      />
      {(["lo", "hi"] as const).map((which) => (
        <button
          key={which}
          type="button"
          aria-label={which === "lo" ? "Minimum" : "Maximum"}
          onPointerDown={drag(which)}
          className="absolute top-1/2 h-[13px] w-[13px] -translate-x-1/2 -translate-y-1/2 cursor-grab touch-none rounded-control border border-line2 bg-raise2 hover:bg-raise active:cursor-grabbing"
          style={{ left: `${which === "lo" ? loPct : hiPct}%` }}
        />
      ))}
    </div>
  );
}

// --- results table ---------------------------------------------------------

export const SEARCH_RESULTS_VIRTUALIZATION_THRESHOLD = 100;
const SEARCH_RESULT_ROW_HEIGHT = 51;
const SEARCH_RESULTS_HEADER_HEIGHT = 33;
const SEARCH_RESULTS_OVERSCAN = 8;
const SEARCH_RESULTS_INITIAL_RECT = { width: 1024, height: 640 };
const PACKAGE_KEYS = ["Package", "Package / Case", "Case", "Footprint"];
const LIFECYCLE_KEYS = ["Lifecycle", "Part Status"];

function normalizedLabel(value: string): string {
  return value.toLowerCase().replace(/[^a-z0-9]+/g, "");
}

function firstSpec(
  specs: SearchRow["specs"],
  keys: readonly string[],
): string {
  const wanted = new Set(keys.map(normalizedLabel));
  for (const [key, raw] of Object.entries(specs)) {
    if (!wanted.has(normalizedLabel(key)) || raw == null || raw === "") continue;
    return prettifyValue(String(raw));
  }
  return "";
}

function isFixedEvidenceColumn(column: SpecColumn): boolean {
  const keys = column.keys ?? [column.key];
  const fixed = new Set(
    [...PACKAGE_KEYS, ...LIFECYCLE_KEYS].map(normalizedLabel),
  );
  return (
    fixed.has(normalizedLabel(column.label)) ||
    keys.some((key) => fixed.has(normalizedLabel(key)))
  );
}

function resultSpecValue(row: SearchRow, column: SpecColumn): string {
  const value = column.keys
    ? rowMergedValue(row.specs, column.keys)
    : column.key === VALUE_COLUMN_KEY
      ? rowPrimaryValue(row.category, row.specs)
      : cellValue(row.specs, column.key);
  return value === "—" ? "" : value;
}

export function searchEvidenceColumns(rows: SearchRow[]): {
  package: boolean;
  lifecycle: boolean;
} {
  return {
    package: rows.some((row) => firstSpec(row.specs, PACKAGE_KEYS) !== ""),
    lifecycle: rows.some((row) => firstSpec(row.specs, LIFECYCLE_KEYS) !== ""),
  };
}

export function searchMatchEvidence(
  row: SearchRow,
  query: string,
): { match: string; evidence: string } {
  const exactMpn =
    query.trim() !== "" &&
    row.mpn.trim().toLowerCase() === query.trim().toLowerCase();
  const missing = row.missing
    .map((item) =>
      item
        .replace(/^kicad[_\s-]*/i, "KiCad ")
        .replace(/^altium[_\s-]*/i, "Altium ")
        .replace(/[_-]+/g, " ")
        .replace(/\b\w/g, (letter) => letter.toUpperCase()),
    )
    .filter(Boolean);
  return {
    match: exactMpn ? "Exact MPN" : query.trim() ? "Catalog Match" : "Catalog Record",
    evidence: row.is_complete
      ? "Record Evidence Complete"
      : missing.length > 0
        ? `Needs ${missing.join(", ")}`
        : "Evidence Incomplete",
  };
}

function ResultsTable({
  rows,
  columns,
  query,
  active,
  onHover,
  onOpen,
  loading,
  scrollElement,
  initialOffset,
}: {
  rows: SearchRow[];
  columns: SpecColumn[];
  query: string;
  active: number;
  onHover: (i: number) => void;
  onOpen: (id: string, category: string) => void;
  loading: boolean;
  scrollElement: HTMLDivElement | null;
  initialOffset: number;
}) {
  const virtualized = rows.length > SEARCH_RESULTS_VIRTUALIZATION_THRESHOLD;
  const getItemKey = useCallback(
    (index: number) => rows[index]?.id ?? index,
    [rows],
  );
  const virtualizer = useVirtualizer({
    count: rows.length,
    enabled: virtualized,
    getScrollElement: () => scrollElement,
    getItemKey,
    estimateSize: () => SEARCH_RESULT_ROW_HEIGHT,
    overscan: SEARCH_RESULTS_OVERSCAN,
    initialRect: SEARCH_RESULTS_INITIAL_RECT,
    initialOffset,
    scrollMargin: SEARCH_RESULTS_HEADER_HEIGHT,
    scrollPaddingStart: SEARCH_RESULTS_HEADER_HEIGHT,
    observeElementRect: (instance, callback) =>
      observeElementRect(instance, (rect) =>
        callback(
          rect.height > 0 ? rect : SEARCH_RESULTS_INITIAL_RECT,
        ),
      ),
  });
  const virtualItems = virtualizer.getVirtualItems();

  // Keyboard selection can jump directly to an unmounted result. The stable
  // id has already been resolved to an index by the parent; make that index
  // visible without mounting any intervening rows.
  useEffect(() => {
    if (
      !virtualized ||
      active < 0 ||
      !scrollElement ||
      typeof scrollElement.scrollTo !== "function"
    ) {
      return;
    }
    virtualizer.scrollToIndex(active, { align: "auto" });
  }, [active, scrollElement, virtualized, virtualizer]);

  if (loading && rows.length === 0) {
    return <div className="px-4 py-10 text-center text-sm text-t3">Searching…</div>;
  }
  if (rows.length === 0) {
    return (
      <div className="px-4 py-14 text-center text-sm text-t3">
        No components match this search.
      </div>
    );
  }
  const presence = searchEvidenceColumns(rows);
  const th =
    "sticky top-0 z-[1] whitespace-nowrap border-b border-line bg-band px-3 py-2 text-left text-ui-caption font-semibold text-copy";
  const td = "whitespace-nowrap px-3 py-2.5 text-ui-body";
  const rendered = virtualized
    ? virtualItems
    : rows.map((row, index) => ({
        index,
        key: row.id,
        start: index * SEARCH_RESULT_ROW_HEIGHT,
        end: (index + 1) * SEARCH_RESULT_ROW_HEIGHT,
        size: SEARCH_RESULT_ROW_HEIGHT,
        lane: 0,
      }));
  const firstVirtual = virtualized ? virtualItems[0] : undefined;
  const lastVirtual = virtualized
    ? virtualItems[virtualItems.length - 1]
    : undefined;
  const paddingTop = firstVirtual
    ? Math.max(0, firstVirtual.start - SEARCH_RESULTS_HEADER_HEIGHT)
    : 0;
  const paddingBottom = lastVirtual
    ? Math.max(0, virtualizer.getTotalSize() - lastVirtual.end)
    : 0;
  const columnCount =
    columns.length + 3 + Number(presence.package) + Number(presence.lifecycle);
  return (
    <table
      className="w-max min-w-full border-collapse"
      data-dev-id="search.results-table"
      data-virtualized={virtualized ? "true" : "false"}
      aria-rowcount={rows.length + 1}
    >
      <thead>
        <tr>
          <th className={th + " min-w-[240px]"}>Identity</th>
          <th className={th + " min-w-[190px]"}>Match &amp; Evidence</th>
          {columns.map((c) => (
            <th
              key={c.key}
              className={
                th +
                " hidden min-[1320px]:table-cell" +
                (c.numeric ? " text-right" : "")
              }
            >
              {c.label}
            </th>
          ))}
          {presence.package ? <th className={th}>Package</th> : null}
          {presence.lifecycle ? <th className={th}>Lifecycle</th> : null}
          <th className={th + " min-w-[150px]"}>Dual-EDA</th>
        </tr>
      </thead>
      <tbody>
        {paddingTop > 0 ? (
          <tr aria-hidden data-virtual-spacer="top" style={{ height: paddingTop }}>
            <td colSpan={columnCount} className="p-0" />
          </tr>
        ) : null}
        {rendered.map((virtualRow) => {
          const row = rows[virtualRow.index];
          return row ? (
            <SearchResultRow
              key={virtualRow.key}
              row={row}
              index={virtualRow.index}
              active={virtualRow.index === active}
              columns={columns}
              query={query}
              showPackage={presence.package}
              showLifecycle={presence.lifecycle}
              td={td}
              virtualized={virtualized}
              onHover={onHover}
              onOpen={onOpen}
            />
          ) : null;
        })}
        {paddingBottom > 0 ? (
          <tr
            aria-hidden
            data-virtual-spacer="bottom"
            style={{ height: paddingBottom }}
          >
            <td colSpan={columnCount} className="p-0" />
          </tr>
        ) : null}
      </tbody>
    </table>
  );
}

function SearchResultRow({
  row,
  index,
  active,
  columns,
  query,
  showPackage,
  showLifecycle,
  td,
  virtualized,
  onHover,
  onOpen,
}: {
  row: SearchRow;
  index: number;
  active: boolean;
  columns: SpecColumn[];
  query: string;
  showPackage: boolean;
  showLifecycle: boolean;
  td: string;
  virtualized: boolean;
  onHover: (index: number) => void;
  onOpen: (id: string, category: string) => void;
}) {
  const evidence = searchMatchEvidence(row, query);
  const packageValue = firstSpec(row.specs, PACKAGE_KEYS);
  return (
    <tr
      data-dev-id="search.results-row"
      data-part-id={row.id}
      aria-rowindex={index + 2}
      aria-selected={active}
      tabIndex={active ? 0 : -1}
      onMouseEnter={() => onHover(index)}
      onFocus={() => onHover(index)}
      onClick={() => onOpen(row.id, row.category)}
      onKeyDown={(event) => {
        if (event.key !== "Enter" && event.key !== " ") return;
        event.preventDefault();
        onOpen(row.id, row.category);
      }}
      style={virtualized ? { height: SEARCH_RESULT_ROW_HEIGHT } : undefined}
      className={
        "cursor-pointer border-t border-line first:border-t-0 " +
        (active
          ? "bg-[color-mix(in_srgb,var(--c-acc)_8%,var(--c-surface))] shadow-[inset_2.5px_0_0_var(--c-acc)]"
          : "hover:bg-raise2")
      }
    >
      <td className={td}>
        <div className="flex items-center gap-2.5">
          <RowThumbnail category={row.category} />
          <div className="min-w-0 max-w-[190px]">
            <div className="truncate font-semibold text-ink">
              {row.display_name}
            </div>
            <div className="tnum truncate font-mono text-ui-caption text-copy">
              {[row.manufacturer, row.mpn].filter(Boolean).join(" · ") || "Identity missing"}
            </div>
          </div>
        </div>
      </td>
      <td className={td}>
        <div className="font-semibold text-ink">{evidence.match}</div>
        <div
          className={
            "max-w-[230px] truncate text-ui-caption " +
            (row.is_complete ? "text-ok" : "text-warn")
          }
          title={evidence.evidence}
        >
          {evidence.evidence}
        </div>
      </td>
      {columns.map((column) => (
        <td
          key={column.key}
          className={
            td +
            " hidden min-[1320px]:table-cell" +
            (column.numeric
              ? " text-right font-mono text-ink"
              : " font-mono text-ui-caption text-copy")
          }
        >
          {resultSpecValue(row, column) || "—"}
        </td>
      ))}
      {showPackage ? (
        <td className={td + " font-mono text-ui-caption text-copy"}>
          {packageValue || "—"}
        </td>
      ) : null}
      {showLifecycle ? (
        <td className={td}>
          <Lifecycle specs={row.specs} />
        </td>
      ) : null}
      <td
        className={td}
        title="Search results do not carry per-tool verification evidence. Open the record for the authoritative KiCad and Altium verdicts."
      >
        <div className="font-semibold text-ink">KiCad + Altium</div>
        <div className="text-ui-caption text-warn">
          {row.is_complete ? "Open To Verify" : "Needs Evidence"}
        </div>
      </td>
    </tr>
  );
}

function Lifecycle({ specs }: { specs: Record<string, string | number | boolean> }) {
  const raw = firstSpec(specs, LIFECYCLE_KEYS);
  if (!raw) return <span className="text-t3">—</span>;
  const isActive = /active/i.test(raw);
  return (
    <span
      className="inline-flex rounded-control px-2 py-0.5 text-ui-caption font-semibold"
      style={
        isActive
          ? { color: "var(--c-ok)", background: "color-mix(in srgb, var(--c-ok) 16%, transparent)" }
          : { color: "var(--c-t2)", background: "var(--c-field)" }
      }
    >
      {isActive ? "Active" : raw}
    </span>
  );
}
