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
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import {
  observeElementRect,
  useVirtualizer,
} from "@tanstack/react-virtual";
import { Kbd } from "@astryxdesign/core/Kbd";
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
  type FilterChip,
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
import { Text, useCopyFormatter, useText } from "../lib/copy";
import { SearchIcon } from "./icons";
import { Icon } from "./Icon";
import { RouteHeader } from "./primitives";
import { RowThumbnail } from "./PartsList";
import {
  readUiSession,
  updateUiSession,
  type SearchSortState,
} from "../lib/uiSession";
import { SEARCH_FACET_RAIL_WIDTH } from "../lib/libraryLayout";
import { useScenarioUiState } from "../design-studio/scenarioState";
import {
  LIFECYCLE_KEYS,
  PACKAGE_KEYS,
  firstSpec,
  normalizedLabel,
  searchEvidenceColumns,
  searchMatchEvidence,
} from "./searchEvidence";

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
  const preview = useScenarioUiState().search;
  const [q, setQ] = useState(() => preview?.query ?? readUiSession().search_filters.query);
  const [filters, setFilters] = useState<SearchFilters>(() => ({
    ...filtersFromSession(),
    category: preview?.category === undefined ? filtersFromSession().category : preview.category,
  }));
  const [sort, setSort] = useState<{ key: SortKey; dir: "asc" | "desc" }>(() =>
    sortFromSession(readUiSession().search_sort),
  );
  const [activeId, setActiveId] = useState<string | null>(
    () => readUiSession().search_results.active_part_id,
  );
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

  // The `?? []` these used to end in allocated a FRESH array on every render while the query was
  // still in flight, so every downstream useMemo saw a changed dependency and recomputed each
  // render - the memo was doing the work of no memo at all, plus a comparison. One shared empty
  // array per shape fixes it without changing a single rendered value.
  const facets = paramFacets.data?.facets ?? NO_FACETS;
  const serverRows = searchResults.data?.parts ?? NO_ROWS;
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
  // Synced in a layout effect, not during render: render can be replayed or thrown away, and a ref
  // written there would carry an anchor from a tree that never committed. Layout effects land before
  // this commit's passive effects, so the scroll checkpoint below (and its teardown flush) still
  // sees this render's anchor.
  useLayoutEffect(() => {
    activeIdRef.current = activePartId;
  });

  // Selection is identity-based rather than index-based, so a client-side sort cannot silently
  // select another part. (Focusing the query field on open belongs to the field, and lives with it
  // in `SearchQueryBar`.)
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
      <SearchQueryBar q={q} onQuery={setQ} onClose={onClose} />

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
          <SearchSubBar
            loading={searchResults.isLoading}
            shown={shown}
            chips={chips}
            filters={filters}
            setFilters={setFilters}
            sort={sort}
            setSort={setSort}
            columns={columns}
          />
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

/**
 * The overlay's title strip: the docked query field and the way out.
 *
 * Same band + hairline family as every other panel header, so the overlay reads as a docked
 * workspace rather than a floating spotlight.
 *
 * It owns the field, so it owns the two things that belong to a field and to nothing else: the
 * element reference, and the focus that has to land in it the moment the overlay opens. Neither
 * was ever read anywhere else in the overlay - the arrow keys move a row, not a caret - and both
 * used to sit at the top of a 360-line component, a long way from the one input they describe.
 */
function SearchQueryBar({
  q,
  onQuery,
  onClose,
}: {
  q: string;
  onQuery: (value: string) => void;
  onClose: () => void;
}) {
  const inputRef = useRef<HTMLInputElement>(null);
  const queryPlaceholder = useText(
    "search.query-placeholder",
    "Search components using a name, MPN, value, or specification...",
  );
  const queryAriaLabel = useText("search.query-label", "Search components");
  const clearSearchLabel = useText("search.clear-query", "Clear search");
  // Focus the field on open.
  useEffect(() => inputRef.current?.focus(), []);
  return (
    <div className="flex h-[38px] flex-none items-center gap-3 border-b border-line bg-band px-3.5">
      <span className="hidden flex-none text-xs font-semibold text-t2 sm:inline">
        <Text id="search.title">Parametric Search</Text>
      </span>
      <div
        className="flex h-[26px] min-w-0 flex-1 items-center gap-2 rounded-control border border-line bg-field px-2.5 focus-within:border-acc"
        data-dev-id="search.query"
      >
        <SearchIcon className="h-3.5 w-3.5 flex-none text-t3" />
        <input
          ref={inputRef}
          value={q}
          onChange={(e) => onQuery(e.target.value)}
          placeholder={queryPlaceholder}
          aria-label={queryAriaLabel}
          data-dev-id="search.query-input"
          className="min-w-0 flex-1 bg-transparent text-sm text-t1 outline-none placeholder:text-t3"
        />
        {q ? (
          <button
            type="button"
            onClick={() => onQuery("")}
            aria-label={clearSearchLabel}
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
        <Text id="search.close">Close</Text>
        <Kbd keys="escape" className="text-2xs" />
        <span className="sr-only"><Text id="search.close-key">Esc</Text></span>
      </button>
    </div>
  );
}

/**
 * The sub-strip: how many results, which narrowings are in force, and how they are ordered.
 *
 * Everything on this strip answers "what is this list showing", which is why the three sit
 * together on one band rather than beside the query field or above the table. The chip remover's
 * accessible name resolves here because the chips are drawn in a callback where no hook can run,
 * and it names a field off the wire.
 */
function SearchSubBar({
  loading,
  shown,
  chips,
  filters,
  setFilters,
  sort,
  setSort,
  columns,
}: {
  loading: boolean;
  shown: number;
  chips: FilterChip[];
  filters: SearchFilters;
  setFilters: (next: SearchFilters) => void;
  sort: { key: SortKey; dir: "asc" | "desc" };
  setSort: (next: { key: SortKey; dir: "asc" | "desc" }) => void;
  columns: SpecColumn[];
}) {
  const removeChipName = useCopyFormatter("search.chip-remove-aria", "Remove {field} filter");
  return (
    <div
      className="flex min-h-[34px] flex-none flex-wrap items-center gap-x-3 gap-y-1 border-b border-line bg-surface px-3 py-1"
      data-dev-id="search.subbar"
    >
        <span className="flex-none text-xs font-semibold text-t2">
          <Text id="search.results.header">Results</Text>
        </span>
        <span className="flex-none text-xs font-semibold text-t1" data-dev-id="search.result-count">
          {loading ? "…" : shown}
          <span className="ml-1.5 text-xs font-medium text-t3">
            {shown === 1 ? (
              <Text id="search.count-noun-one">result</Text>
            ) : (
              <Text id="search.count-noun-many">results</Text>
            )}
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
                aria-label={removeChipName({ field: chip.keyLabel })}
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
              <Text id="search.clear-all">Clear All</Text>
            </button>
          ) : null}
        </div>
        <SortControl sort={sort} setSort={setSort} columns={columns} />
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

const ASTRYX_KEY: Record<string, string> = {
  "↑": "up",
  "↓": "down",
  "↵": "enter",
  Esc: "escape",
};

function KbdHint({ keys, label }: { keys: string[]; label: string }) {
  return (
    <span className="inline-flex items-center gap-1.5">
      {keys.map((key) => <Kbd key={key} keys={ASTRYX_KEY[key] ?? key} />)}
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
        className="flex h-[22px] items-center gap-1.5 rounded-control border border-line bg-raise px-2 text-xs font-medium text-t2 hover:bg-raise2 hover:text-t1"
        data-dev-id="search.sort"
      >
        <Text id="search.sort.label">Sort</Text>{" "}
        <b className="font-semibold text-t1">{current}</b>
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
  // `FacetGroup` takes a plain string for its heading, so the copy layer is read here and the
  // resolved value handed down. Class, not Category: the value under it is a component's own
  // classification, and Class is this product's word for that everywhere else.
  const classHeading = useText("search.rail.class-heading", "Class");
  return (
    <div className="flex min-h-0 flex-col" data-dev-id="search.rail">
      <RouteHeader className="h-[34px]" right={activeCount > 0 ? `${activeCount} active` : undefined}>
        <Text id="search.filters.header">Filters</Text>
      </RouteHeader>
      <div className="min-h-0 flex-1 overflow-y-auto px-3 pb-2 pt-1">
        <FacetGroup title={classHeading} first data-dev-id="search.rail-category">
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
            <div className="py-2 text-xs text-t3">
              <Text id="search.filters.no-categories">No classes so far.</Text>
            </div>
          ) : null}
        </FacetGroup>

        {sections.length === 0 ? (
          <>
            <RailSection label={category ? `${category} Parameters` : "Parameters"} fromSpecs />
            <div className="px-0.5 py-3 text-xs text-t3">
              <Text id="search.filters.no-specs">No parametric specs to filter on so far.</Text>
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
            <Text id="search.filters.generated-note">
              Filters are generated from each part's specs. Add a component with a new parameter and
              it becomes a filter here on its own.
            </Text>
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
          <Text id="search.filters.in-stock">In Stock</Text>
        </button>
      </div>
    </div>
  );
}

function RailSection({ label, fromSpecs }: { label: string; fromSpecs?: boolean }) {
  // A tooltip is interface text, so it belongs in the copy layer like any label.
  const fromSpecsHint = useText(
    "search.filters.from-specs.hint",
    "These filters are generated from the part specs in this class",
  );
  return (
    <div className="flex items-center gap-2 pb-0.5 pt-5 text-ui-caption font-semibold text-copy first:pt-0.5">
      {label}
      {fromSpecs ? (
        <span
          className="inline-flex flex-none items-center gap-1 whitespace-nowrap rounded-control bg-acc-soft px-1.5 py-0.5 text-ui-meta font-semibold text-copy"
          title={fromSpecsHint}
        >
          <Spark className="h-2.5 w-2.5" />
          <Text id="search.filters.from-specs">From Specifications</Text>
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
  // The two bound fields are numeric inputs with no visible label of their own - the facet's name
  // sits in the group heading above them, which a screen reader does not read as their name. The
  // BOUND is copy and the facet name is DATA, so the sentence is a formatter with the spec name
  // substituted in. Resolved above the early returns below, so the hook count is stable.
  const minBoundLabel = useCopyFormatter("search.filters.range-min", "Minimum {facet}");
  const maxBoundLabel = useCopyFormatter("search.filters.range-max", "Maximum {facet}");
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
          <span className="text-t3">
            <Text id="search.filters.only-value">Sole value</Text>
          </span>
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
        {/* A tick's identity IS its value: keying on the position reassigned labels between
            scales when the facet's range changed under a filter. */}
        {scale!.ticks.map((t) => (
          <span key={t}>{formatMagnitude(t, unit)}</span>
        ))}
      </div>
      <div className="mt-2.5 grid grid-cols-2 gap-2">
        <RangeInput
          label={minBoundLabel({ facet: facet.label })}
          value={lo}
          unit={unit}
          onCommit={(v) => onChange({ min: v <= fmin ? null : v, max: sel?.max ?? null })}
        />
        <RangeInput
          label={maxBoundLabel({ facet: facet.label })}
          value={hi}
          unit={unit}
          onCommit={(v) => onChange({ min: sel?.min ?? null, max: v >= fmax ? null : v })}
        />
      </div>
    </FacetGroup>
  );
}

function RangeInput({
  label,
  value,
  unit,
  onCommit,
}: {
  /** The whole accessible name, e.g. "Minimum Capacitance". Not a truncated visible label. */
  label: string;
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
      aria-label={label}
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
  // The two handles are drawn in a callback, so their names are resolved here. A drag handle has no
  // visible text at all, which makes these the whole of what a screen reader can announce.
  const minimumName = useText("search.range-minimum", "Minimum");
  const maximumName = useText("search.range-maximum", "Maximum");
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
          aria-label={which === "lo" ? minimumName : maximumName}
          onPointerDown={drag(which)}
          className="absolute top-1/2 h-[13px] w-[13px] -translate-x-1/2 -translate-y-1/2 cursor-grab touch-none rounded-control border border-line2 bg-raise2 hover:bg-raise active:cursor-grabbing"
          style={{ left: `${which === "lo" ? loPct : hiPct}%` }}
        />
      ))}
    </div>
  );
}

// --- results table ---------------------------------------------------------

// Stable empty fallbacks for the two query payloads. Shared, never mutated: they exist only so an
// absent result reads as the SAME empty list every render.
const NO_FACETS: ParametricFacet[] = [];
const NO_ROWS: SearchRow[] = [];

export const SEARCH_RESULTS_VIRTUALIZATION_THRESHOLD = 100;
const SEARCH_RESULT_ROW_HEIGHT = 51;
const SEARCH_RESULTS_HEADER_HEIGHT = 33;
const SEARCH_RESULTS_OVERSCAN = 8;
const SEARCH_RESULTS_INITIAL_RECT = { width: 1024, height: 640 };
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

  // The row the pointer last activated. Scrolling a hovered row into view moves the rows
  // under the cursor, which fires another mouseenter, which scrolls again - moving the mouse
  // dragged the list along with it. A pointer already put the row where the user can see it,
  // so only a selection the pointer did NOT make is worth scrolling to.
  const pointerActiveIndex = useRef(-1);
  const activateFromPointer = (index: number) => {
    pointerActiveIndex.current = index;
    onHover(index);
  };

  // Keyboard selection can jump directly to an unmounted result. The stable
  // id has already been resolved to an index by the parent; make that index
  // visible without mounting any intervening rows.
  useEffect(() => {
    const fromPointer = pointerActiveIndex.current === active;
    pointerActiveIndex.current = -1;
    if (
      fromPointer ||
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
    return (
      <div className="px-4 py-10 text-center text-sm text-t3">
        <Text id="search.results.searching">Searching…</Text>
      </div>
    );
  }
  if (rows.length === 0) {
    return (
      <div className="px-4 py-14 text-center text-sm text-t3">
        <Text id="search.results.empty">No components match this search.</Text>
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
          <th className={th + " min-w-[240px]"}>
            <Text id="search.results.col-identity">Identification</Text>
          </th>
          <th className={th + " min-w-[190px]"}>
            <Text id="search.results.col-match">Match &amp; Evidence</Text>
          </th>
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
          {presence.package ? (
            <th className={th}>
              <Text id="search.results.col-package">Package</Text>
            </th>
          ) : null}
          {presence.lifecycle ? (
            <th className={th}>
              <Text id="search.results.col-lifecycle">Product Status</Text>
            </th>
          ) : null}
          <th className={th + " min-w-[150px]"}>
            <Text id="search.results.col-dual-eda">Dual-EDA</Text>
          </th>
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
              onHover={activateFromPointer}
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
  // A native tooltip takes a resolved string, so the caveat about what a search row can and cannot
  // prove is read here rather than wrapped at its cell.
  const evidenceCaveat = useText(
    "search.results.eda-caveat",
    "Search results do not hold per-tool validation evidence. Open the record for the authoritative KiCad and Altium verdicts.",
  );
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
            (row.is_complete ? "text-ok-text" : "text-warn")
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
        title={evidenceCaveat}
      >
        <div className="font-semibold text-ink">
          <Text id="search.results.dual-eda-tools">KiCad + Altium</Text>
        </div>
        <div className="text-ui-caption text-warn">
          {row.is_complete ? (
            <Text id="search.results.open-to-validate">Open To Validate</Text>
          ) : (
            <Text id="search.results.needs-evidence">Needs Evidence</Text>
          )}
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
      {isActive ? <Text id="search.results.lifecycle-active">Active</Text> : raw}
    </span>
  );
}
