/**
 * The full-screen modular search (north-star search.html): a big query field, a live
 * active-filter chip bar, a facet rail GENERATED from the parts' own parametric facets, and a
 * schema-driven results table. Nothing about the parameters is hardcoded - the rail's ranges +
 * checkboxes and the table's columns all come from /facets/parametric and the rows' specs, so a
 * category that grows a new spec gains a filter and a column here on its own. Opens over the app
 * (Ctrl+K or the Components search field), closes on Esc; ↑/↓ move the selection, ↵ opens a part.
 */
import { useEffect, useMemo, useRef, useState } from "react";
import type { ParametricFacet, SearchRow } from "../api/types";
import { useFacetsQuery, useParametricFacets, useSearchQuery } from "../api/queries";
import {
  activeChips,
  cellValue,
  clearAll,
  deriveColumns,
  emptyFilters,
  formatMagnitude,
  hasAnyFilter,
  isOptionOn,
  makeScale,
  normalizeUnit,
  parseMagnitude,
  sectionedRail,
  setRange,
  type RailSection as RailSectionData,
  type Scale,
  toSpecParams,
  toggleOption,
  type RangeSel,
  type SearchFilters,
  type SpecColumn,
} from "../lib/searchFilters";
import { SearchIcon } from "./icons";
import { RowThumbnail } from "./PartsList";

// --- small inline glyphs (the artifact's own set) ---------------------------
const stroke = {
  viewBox: "0 0 24 24",
  fill: "none",
  stroke: "currentColor",
  strokeLinecap: "round" as const,
  strokeLinejoin: "round" as const,
};
const Chevron = ({ className = "" }: { className?: string }) => (
  <svg {...stroke} strokeWidth={2} className={className}>
    <path d="m6 9 6 6 6-6" />
  </svg>
);
const Check = () => (
  <svg {...stroke} strokeWidth={3.4} className="h-2.5 w-2.5">
    <path d="M20 6 9 17l-5-5" />
  </svg>
);
const XSmall = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.4} strokeLinecap="round" className="h-2.5 w-2.5">
    <path d="M18 6 6 18M6 6l12 12" />
  </svg>
);
const Spark = ({ className = "" }: { className?: string }) => (
  <svg {...stroke} strokeWidth={2} className={className}>
    <path d="M9.94 15.5A2 2 0 0 0 8.5 14.06l-6.14-1.58a.5.5 0 0 1 0-.96L8.5 9.94A2 2 0 0 0 9.94 8.5l1.58-6.14a.5.5 0 0 1 .96 0L14.06 8.5A2 2 0 0 0 15.5 9.94l6.14 1.58a.5.5 0 0 1 0 .96L15.5 14.06a2 2 0 0 0-1.44 1.44l-1.58 6.14a.5.5 0 0 1-.96 0z" />
  </svg>
);

interface Props {
  onClose: () => void;
  // opening a part carries its category so the picker can scope to it and reveal the selection
  onOpenPart: (id: string, category: string) => void;
}

type SortKey = { kind: "name" } | { kind: "stock" } | { kind: "unit" } | { kind: "spec"; key: string; numeric: boolean };

export function SearchOverlay({ onClose, onOpenPart }: Props) {
  const [q, setQ] = useState("");
  const [filters, setFilters] = useState<SearchFilters>(emptyFilters());
  const [sort, setSort] = useState<{ key: SortKey; dir: "asc" | "desc" }>({
    key: { kind: "name" },
    dir: "asc",
  });
  const [active, setActive] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);

  const category = filters.category;
  const spec = useMemo(() => toSpecParams(filters), [filters]);
  const categoryFacets = useFacetsQuery();
  const paramFacets = useParametricFacets({ q, category });
  const searchResults = useSearchQuery({ q, category, spec });

  const facets = paramFacets.data?.facets ?? [];
  const sections = useMemo(() => sectionedRail(facets, category), [facets, category]);
  const columns = useMemo(() => deriveColumns(facets, category, 4), [facets, category]);
  const chips = useMemo(() => activeChips(filters, facets), [filters, facets]);

  const rows = useMemo(() => {
    let out = searchResults.data?.parts ?? [];
    if (filters.inStock) out = out.filter((r) => (r.stock ?? 0) > 0);
    return sortRows(out, sort, columns);
  }, [searchResults.data, filters.inStock, sort, columns]);

  // Focus the field on open; keep the keyboard selection in range as the row set changes.
  useEffect(() => inputRef.current?.focus(), []);
  useEffect(() => {
    setActive((i) => Math.min(i, Math.max(0, rows.length - 1)));
  }, [rows.length]);

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") {
        e.preventDefault();
        onClose();
      } else if (e.key === "ArrowDown") {
        e.preventDefault();
        setActive((i) => Math.min(i + 1, rows.length - 1));
      } else if (e.key === "ArrowUp") {
        e.preventDefault();
        setActive((i) => Math.max(i - 1, 0));
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
  const total = searchResults.data?.count ?? 0;
  const shown = rows.length;

  return (
    <div className="fixed inset-0 z-[100] flex flex-col bg-canvas">
      {/* top: the query field + a close affordance */}
      <div className="flex-none px-6 pt-6">
        <div className="flex items-center gap-4">
          <div className="flex h-[52px] flex-1 items-center gap-3.5 rounded-[13px] border border-line bg-raise px-[18px] shadow-card focus-within:border-line2">
            <SearchIcon className="h-5 w-5 flex-none text-t3" />
            <input
              ref={inputRef}
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="Search components by name, MPN, value, or spec…"
              aria-label="Search components"
              className="min-w-0 flex-1 bg-transparent text-[17px] font-medium text-t1 outline-none placeholder:font-normal placeholder:text-t3"
            />
            {q ? (
              <button
                type="button"
                onClick={() => setQ("")}
                aria-label="Clear search"
                className="grid h-[26px] w-[26px] flex-none place-items-center rounded-full text-t3 hover:bg-raise2 hover:text-t1"
              >
                <XSmall />
              </button>
            ) : null}
          </div>
          <button
            type="button"
            onClick={onClose}
            className="flex h-[52px] flex-none items-center gap-2 rounded-control border border-line bg-raise px-4 text-sm font-semibold text-t2 shadow-card hover:border-line2 hover:text-t1"
          >
            Close
            <kbd className="rounded-[5px] border border-line px-1.5 py-0.5 font-mono text-[11px] text-t3">
              Esc
            </kbd>
          </button>
        </div>

        {/* sub-bar: result count, the active-filter chips, and the sort control */}
        <div className="flex items-center gap-3 py-4">
          <span className="flex-none text-sm font-bold text-t1">
            {searchResults.isLoading ? "…" : total}
            <span className="ml-1.5 text-xs font-medium text-t3">
              {total === 1 ? "result" : "results"}
            </span>
          </span>
          <div className="flex min-w-0 flex-1 flex-wrap items-center gap-1.5">
            {chips.map((chip) => (
              <span
                key={chip.id}
                className="inline-flex items-center gap-1.5 rounded-full border border-line bg-raise2 py-1 pl-2.5 pr-1.5 text-xs font-semibold text-t1"
              >
                <span className="font-medium text-t3">{chip.keyLabel}:</span>
                {chip.value}
                <button
                  type="button"
                  onClick={() => setFilters(chip.remove)}
                  aria-label={`Remove ${chip.keyLabel} filter`}
                  className="grid h-4 w-4 place-items-center rounded-full text-t3 hover:bg-line2 hover:text-t1"
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
      </div>

      {/* main: the schema-driven facet rail + the results table */}
      <div className="grid min-h-0 flex-1 grid-cols-[260px_1fr] gap-5 px-6 pb-6">
        <FacetRail
          categories={categories}
          category={category}
          onCategory={(name) =>
            setFilters((f) => ({ ...emptyFilters(), inStock: f.inStock, category: name }))
          }
          sections={sections}
          filters={filters}
          setFilters={setFilters}
        />

        <div className="flex min-h-0 flex-col">
          <div className="min-h-0 flex-1 overflow-auto rounded-t-card border border-b-0 border-line bg-raise shadow-card">
            <ResultsTable
              rows={rows}
              columns={columns}
              active={active}
              onHover={setActive}
              onOpen={onOpenPart}
              loading={searchResults.isLoading}
            />
          </div>
          <div className="flex flex-none items-center gap-4 rounded-b-card border border-line bg-raise px-[18px] py-2.5 text-xs text-t3 shadow-card">
            <KbdHint keys={["↑", "↓"]} label="Navigate" />
            <KbdHint keys={["↵"]} label="Open Part" />
            <KbdHint keys={["Esc"]} label="Close" />
            <span className="ml-auto">
              {shown === total ? `${total} shown` : `Showing ${shown} of ${total}`}
            </span>
          </div>
        </div>
      </div>
    </div>
  );
}

function KbdHint({ keys, label }: { keys: string[]; label: string }) {
  return (
    <span className="inline-flex items-center gap-1.5">
      {keys.map((k) => (
        <kbd
          key={k}
          className="min-w-[18px] rounded border border-line px-1.5 text-center font-mono text-[10.5px] text-t2"
        >
          {k}
        </kbd>
      ))}
      {label}
    </span>
  );
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
        className="flex h-[34px] items-center gap-2 rounded-control border border-line bg-raise px-3 text-sm font-medium text-t2 shadow-card hover:border-line2 hover:text-t1"
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
                    "flex w-full items-center justify-between rounded-[6px] px-2.5 py-1.5 text-left text-sm " +
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
}: {
  categories: [string, number][];
  category: string | null;
  onCategory: (name: string | null) => void;
  sections: RailSectionData[];
  filters: SearchFilters;
  setFilters: (updater: (f: SearchFilters) => SearchFilters) => void;
}) {
  return (
    <div className="flex min-h-0 flex-col">
      <div className="min-h-0 flex-1 overflow-y-auto pr-2">
        <RailSection label="Category" />
        <FacetGroup title="Category" first>
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
            <div className="py-2 text-xs text-t3">No categories yet.</div>
          ) : null}
        </FacetGroup>

        {sections.length === 0 ? (
          <>
            <RailSection label={category ? `${category} Parameters` : "Parameters"} fromSpecs />
            <div className="px-0.5 py-3 text-xs text-t3">
              No parametric specs to filter on yet.
            </div>
          </>
        ) : (
          sections.map((sec) => (
            <div key={sec.title}>
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

        <div className="mt-3.5 flex gap-2 border-t border-line pt-3 text-[10.5px] leading-relaxed text-t3">
          <Spark className="mt-0.5 h-3 w-3 flex-none" />
          <span>
            Filters are generated from each part's specs. Add a component with a new parameter
            and it becomes a filter here on its own.
          </span>
        </div>
      </div>

      <div className="flex-none border-t border-line pt-3.5">
        <button
          type="button"
          onClick={() => setFilters((f) => ({ ...f, inStock: !f.inStock }))}
          className="flex w-full items-center justify-between text-sm font-medium text-t1"
        >
          In Stock
          <span
            className={
              "relative h-[21px] w-9 flex-none rounded-full transition-colors " +
              (filters.inStock ? "bg-ok" : "bg-field")
            }
          >
            <span
              className={
                "absolute top-[2.5px] h-4 w-4 rounded-full bg-white shadow transition-all " +
                (filters.inStock ? "left-[17.5px]" : "left-[2.5px]")
              }
            />
          </span>
        </button>
      </div>
    </div>
  );
}

function RailSection({ label, fromSpecs }: { label: string; fromSpecs?: boolean }) {
  return (
    <div className="flex items-center gap-2 pb-0.5 pt-5 text-[10px] font-bold uppercase tracking-[0.07em] text-t3 first:pt-0.5">
      {label}
      {fromSpecs ? (
        <span
          className="inline-flex items-center gap-1 rounded-full bg-acc-soft px-1.5 py-0.5 text-[9px] font-semibold normal-case tracking-normal text-t2"
          title="These filters are generated from the category's part specs"
        >
          <Spark className="h-2.5 w-2.5" />
          from specs
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
}: {
  title: string;
  unit?: string | null;
  first?: boolean;
  children: React.ReactNode;
}) {
  const [open, setOpen] = useState(true);
  return (
    <div className={"px-0.5 pb-1 pt-2.5 " + (first ? "" : "border-t border-line")}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="mb-2 flex w-full items-center text-sm font-semibold text-t1"
      >
        {title}
        {unit ? <span className="ml-auto mr-2 font-mono text-[10px] font-medium text-t3">{unit}</span> : null}
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
          "grid h-4 w-4 flex-none place-items-center rounded-[5px] border-[1.5px] " +
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
  const [expanded, setExpanded] = useState(false);
  const opts = facet.options ?? [];
  const LIMIT = 5;
  const shown = expanded ? opts : opts.slice(0, LIMIT);
  const more = opts.length - shown.length;
  return (
    <FacetGroup title={facet.label} first={first}>
      {shown.map((o) => (
        <OptionRow
          key={o.value}
          label={o.value}
          count={o.count}
          on={isOptionOn(filters, facet.key, o.value)}
          onToggle={() => setFilters((f) => toggleOption(f, facet.key, o.value))}
        />
      ))}
      {more > 0 ? (
        <button
          type="button"
          onClick={() => setExpanded(true)}
          className="py-1 text-xs font-semibold text-t2 hover:text-t1"
        >
          + {more} More
        </button>
      ) : null}
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
  const scale = useMemo(() => makeScale(fmin, fmax), [fmin, fmax]);
  return (
    <FacetGroup title={facet.label} unit={unit} first={first}>
      <div className="mb-2 flex justify-between font-mono text-xs text-t2">
        <span>{formatMagnitude(lo, unit)}</span>
        <span>{formatMagnitude(hi, unit)}</span>
      </div>
      <RangeSlider
        scale={scale}
        lo={lo}
        hi={hi}
        onChange={(nlo, nhi) =>
          onChange({
            min: nlo <= fmin ? null : nlo,
            max: nhi >= fmax ? null : nhi,
          })
        }
      />
      <div className="mt-2 flex justify-between px-1.5 font-mono text-[9.5px] text-t3">
        {scale.ticks.map((t, i) => (
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
      className="h-[30px] w-full min-w-0 rounded-control border border-line bg-field px-2.5 text-center font-mono text-[11px] text-t1 outline-none focus:border-line2"
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
    <div ref={trackRef} className="relative mx-2 h-1 rounded-full bg-field shadow-[inset_0_1px_2px_rgba(0,0,0,.3)]">
      <div
        className="absolute h-full rounded-full bg-t2"
        style={{ left: `${loPct}%`, right: `${100 - hiPct}%` }}
      />
      {(["lo", "hi"] as const).map((which) => (
        <button
          key={which}
          type="button"
          aria-label={which === "lo" ? "Minimum" : "Maximum"}
          onPointerDown={drag(which)}
          className="absolute top-1/2 h-[15px] w-[15px] -translate-x-1/2 -translate-y-1/2 cursor-grab touch-none rounded-full border border-line2 bg-raise shadow-raise active:cursor-grabbing"
          style={{ left: `${which === "lo" ? loPct : hiPct}%` }}
        />
      ))}
    </div>
  );
}

// --- results table ---------------------------------------------------------

function ResultsTable({
  rows,
  columns,
  active,
  onHover,
  onOpen,
  loading,
}: {
  rows: SearchRow[];
  columns: SpecColumn[];
  active: number;
  onHover: (i: number) => void;
  onOpen: (id: string, category: string) => void;
  loading: boolean;
}) {
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
  const th = "sticky top-0 z-[1] whitespace-nowrap border-b border-line bg-raise px-3 py-3 text-left text-[10px] font-bold uppercase tracking-[0.06em] text-t3";
  const td = "whitespace-nowrap px-3 py-2.5 text-sm";
  return (
    <table className="w-full border-collapse">
      <thead>
        <tr>
          <th className={th + " w-[204px]"}>Part</th>
          {columns.map((c) => (
            <th key={c.key} className={th + (c.numeric ? " text-right" : "")}>
              {c.label}
            </th>
          ))}
          <th className={th}>Mfr</th>
          <th className={th + " text-right"}>In Stock</th>
          <th className={th + " text-right"}>Unit</th>
          <th className={th}>Lifecycle</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((row, i) => (
          <tr
            key={row.id}
            aria-selected={i === active}
            onMouseEnter={() => onHover(i)}
            onClick={() => onOpen(row.id, row.category)}
            className={
              "cursor-pointer border-t border-line first:border-t-0 " +
              (i === active
                ? "bg-[color-mix(in_srgb,var(--c-acc)_8%,var(--c-raise))] shadow-[inset_2.5px_0_0_var(--c-acc)]"
                : "hover:bg-raise2")
            }
          >
            <td className={td}>
              <div className="flex items-center gap-2.5">
                <RowThumbnail id={row.id} category={row.category} />
                <div className="min-w-0 max-w-[152px]">
                  <div className="truncate font-semibold text-t1">{row.display_name}</div>
                  <div className="tnum truncate font-mono text-[11px] text-t2">{row.mpn}</div>
                </div>
              </div>
            </td>
            {columns.map((c) => (
              <td
                key={c.key}
                className={
                  td +
                  (c.numeric ? " text-right font-mono text-t1" : " font-mono text-[11.5px] text-t2")
                }
              >
                {cellValue(row.specs, c.key)}
              </td>
            ))}
            <td className={td + " text-t2"}>{row.manufacturer || "—"}</td>
            <td className={td + " tnum text-right font-mono text-t1"}>
              {row.stock == null ? "—" : row.stock.toLocaleString()}
            </td>
            <td className={td + " tnum text-right font-mono text-t1"}>
              {row.unit_price == null ? "—" : formatUnit(row.unit_price, row.currency)}
            </td>
            <td className={td}>
              <Lifecycle specs={row.specs} />
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function Lifecycle({ specs }: { specs: Record<string, string | number | boolean> }) {
  const raw = String(specs["Lifecycle"] ?? specs["Part Status"] ?? "").trim();
  if (!raw) return <span className="text-t3">—</span>;
  const isActive = /active/i.test(raw);
  return (
    <span
      className="inline-flex rounded-[6px] px-2 py-0.5 text-[11px] font-semibold"
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

function formatUnit(price: number, currency: string): string {
  const symbol = currency === "USD" || !currency ? "$" : `${currency} `;
  return `${symbol}${price.toFixed(price < 0.1 ? 3 : 2)}`;
}
