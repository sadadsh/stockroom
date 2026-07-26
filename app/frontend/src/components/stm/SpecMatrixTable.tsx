/**
 * SpecMatrixTable (TABLE-01): the virtualized, faceted MCU spec matrix over the ST-MCU-FINDER
 * column set. It is a pure presenter of the McuSpecRow[] StmViewerPage fetched with useStmMcus,
 * so every facet toggle, sort, and the free-text search run client-side over the already-fetched
 * rows (never a network request, CONTEXT decision 3), and @tanstack/react-virtual keeps scrolling
 * smooth at all-family row counts. A row click emits the part upward (the seam the pinout map
 * consumes). The Part cell shows mpn_example, never the ref_name wildcard (Pitfall 1).
 */
import { useEffect, useMemo, useRef, useState } from "react";
import {
  type ColumnDef,
  type ColumnFiltersState,
  type SortingState,
  type VisibilityState,
  flexRender,
  getCoreRowModel,
  getFacetedMinMaxValues,
  getFacetedRowModel,
  getFacetedUniqueValues,
  getFilteredRowModel,
  getSortedRowModel,
  useReactTable,
} from "@tanstack/react-table";
import { useVirtualizer } from "@tanstack/react-virtual";
import type { McuSpecRow } from "../../api/types";
import { SearchIcon } from "../icons";

// The peripheral columns TABLE-01 names (a representative count column each), read from
// row.peripherals; NOT the full CubeMX peripheral set (the every-fact view is a deferred P2).
const PERIPHERALS = ["USART", "SPI", "I2C", "TIM", "ADC", "USB"] as const;

// A column's filter affordance: free text for identity columns, a numeric min/max range for the
// tabular figures. Carried in column meta so the header filter row renders the right control.
type FilterKind = "text" | "range";
interface ColMeta {
  filter: FilterKind;
  align?: "left" | "right";
  mono?: boolean;
  unit?: string;
}

const ROW_HEIGHT = 34;

// Per-column DEFAULT widths (px) for the shared grid template (header, filter row, and every
// body row). Fixed tracks so columns NEVER squish as visibility changes - the matrix scrolls
// horizontally instead - and every header carries a drag handle so a cut-off header is one
// resize away (TanStack columnSizing drives the live track width).
const COLUMN_WIDTHS: Record<string, number> = {
  mpn_example: 200,
  core: 92,
  series: 92,
  package: 112,
  io_count: 64,
  flash_kb: 84,
  ram_kb: 80,
  max_freq_mhz: 104,
};
const PERIPH_WIDTH = 60;
const MIN_COLUMN_WIDTH = 48;

interface Props {
  rows: McuSpecRow[];
  activePart: string | null;
  onSelectPart: (part: string) => void;
}

export function SpecMatrixTable({ rows, activePart, onSelectPart }: Props) {
  const [sorting, setSorting] = useState<SortingState>([]);
  const [columnFilters, setColumnFilters] = useState<ColumnFiltersState>([]);
  const [globalFilter, setGlobalFilter] = useState("");
  const [filtersOpen, setFiltersOpen] = useState(false);
  const [columnVisibility, setColumnVisibility] = useState<VisibilityState>({});
  const [columnSizing, setColumnSizing] = useState<Record<string, number>>({});
  const [columnsOpen, setColumnsOpen] = useState(false);
  const columnsRef = useRef<HTMLDivElement>(null);

  // Close the column picker on any outside click or Escape (a mini popover, not a modal).
  useEffect(() => {
    if (!columnsOpen) return;
    function onDown(e: MouseEvent) {
      if (columnsRef.current && !columnsRef.current.contains(e.target as Node)) {
        setColumnsOpen(false);
      }
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") setColumnsOpen(false);
    }
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [columnsOpen]);

  const columns = useMemo<ColumnDef<McuSpecRow>[]>(() => {
    const num = (key: keyof McuSpecRow, header: string, unit?: string): ColumnDef<McuSpecRow> => ({
      accessorKey: key,
      header,
      filterFn: "inNumberRange",
      size: COLUMN_WIDTHS[key as string] ?? PERIPH_WIDTH,
      meta: { filter: "range", align: "right", mono: true, unit } satisfies ColMeta,
      cell: (ctx) => <NumCell value={ctx.getValue() as number} unit={unit} />,
    });
    const periphCols: ColumnDef<McuSpecRow>[] = PERIPHERALS.map((name) => ({
      id: name,
      accessorFn: (row) => row.peripherals?.[name] ?? 0,
      header: name,
      filterFn: "inNumberRange",
      size: PERIPH_WIDTH,
      meta: { filter: "range", align: "right", mono: true } satisfies ColMeta,
      cell: (ctx) => {
        const v = ctx.getValue() as number;
        return (
          <span className={"tnum font-mono text-xs " + (v > 0 ? "text-t2" : "text-t3")}>
            {v > 0 ? v : "–"}
          </span>
        );
      },
    }));
    return [
      {
        accessorKey: "mpn_example",
        size: COLUMN_WIDTHS.mpn_example,
        header: "Part",
        filterFn: "includesString",
        meta: { filter: "text", mono: true } satisfies ColMeta,
        cell: (ctx) => (
          <span className="truncate font-mono text-sm font-semibold text-t1">
            {ctx.getValue() as string}
          </span>
        ),
      },
      {
        accessorKey: "core",
        size: COLUMN_WIDTHS.core,
        header: "Core",
        filterFn: "includesString",
        meta: { filter: "text" } satisfies ColMeta,
        // "Arm Cortex-M4" -> "M4": every STM32 core is an Arm Cortex, so the prefix is pure
        // noise at column width (it truncated to "Arm Corte..." on every row).
        cell: (ctx) => (
          <span className="text-xs text-t2">
            {((ctx.getValue() as string | null) ?? "").replace(/^(arm\s+)?cortex-/i, "")}
          </span>
        ),
      },
      {
        accessorKey: "series",
        size: COLUMN_WIDTHS.series,
        header: "Series",
        filterFn: "includesString",
        meta: { filter: "text", mono: true } satisfies ColMeta,
        cell: (ctx) => (
          <span className="truncate font-mono text-xs text-t2">{ctx.getValue() as string}</span>
        ),
      },
      {
        accessorKey: "package",
        size: COLUMN_WIDTHS.package,
        header: "Package",
        filterFn: "includesString",
        meta: { filter: "text", mono: true } satisfies ColMeta,
        cell: (ctx) => (
          <span className="truncate font-mono text-xs text-t2">{ctx.getValue() as string}</span>
        ),
      },
      num("io_count", "IOs"),
      num("flash_kb", "Flash", "KB"),
      num("ram_kb", "RAM", "KB"),
      num("max_freq_mhz", "Frequency", "MHz"),
      ...periphCols,
    ];
  }, []);

  const table = useReactTable({
    data: rows,
    columns,
    state: { sorting, columnFilters, globalFilter, columnVisibility, columnSizing },
    onSortingChange: setSorting,
    onColumnFiltersChange: setColumnFilters,
    onGlobalFilterChange: setGlobalFilter,
    onColumnVisibilityChange: setColumnVisibility,
    onColumnSizingChange: setColumnSizing,
    columnResizeMode: "onChange",
    defaultColumn: { minSize: MIN_COLUMN_WIDTH, size: PERIPH_WIDTH },
    globalFilterFn: "includesString",
    getCoreRowModel: getCoreRowModel(),
    getFilteredRowModel: getFilteredRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getFacetedRowModel: getFacetedRowModel(),
    getFacetedUniqueValues: getFacetedUniqueValues(),
    getFacetedMinMaxValues: getFacetedMinMaxValues(),
  });

  const modelRows = table.getRowModel().rows;

  const scrollRef = useRef<HTMLDivElement>(null);
  const virtualizer = useVirtualizer({
    count: modelRows.length,
    getScrollElement: () => scrollRef.current,
    estimateSize: () => ROW_HEIGHT,
    overscan: 14,
  });
  const virtualItems = virtualizer.getVirtualItems();
  // jsdom (and any 0-height first paint) measures no rows; fall back to a full render so the
  // content is present. In the real app the container has height, so virtualization drives.
  const useVirtual = virtualItems.length > 0;
  const totalSize = virtualizer.getTotalSize();

  // A shared grid template so the sticky header, the filter row, and every body row align down
  // the matrix, DERIVED from the visible columns so hiding one never squishes the rest (each
  // visible column keeps its fixed track; the matrix scrolls horizontally instead).
  const visibleColumns = table.getVisibleLeafColumns();
  const gridStyle = useMemo(
    () => ({
      display: "grid" as const,
      gridTemplateColumns: visibleColumns.map((c) => `${c.getSize()}px`).join(" "),
    }),
    [visibleColumns, columnSizing],
  );

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      {/* toolbar: client-side search + the live result count + the filter toggle */}
      <div className="mb-2.5 flex items-center gap-2.5">
        <div className="flex h-8 min-w-0 flex-1 items-center gap-2 rounded-control bg-field pl-2.5 pr-2">
          <SearchIcon className="flex-none text-t3" />
          <input
            value={globalFilter}
            onChange={(e) => setGlobalFilter(e.target.value)}
            placeholder="Search Parts"
            aria-label="Search Parts"
            className="min-w-0 flex-1 bg-transparent text-sm text-t1 outline-none placeholder:text-t3"
          />
        </div>
        <span className="tnum flex-none font-mono text-xs text-t3">
          {modelRows.length.toLocaleString()} of {rows.length.toLocaleString()}
        </span>
        <button
          type="button"
          onClick={() => setFiltersOpen((v) => !v)}
          aria-pressed={filtersOpen}
          className={
            "flex-none rounded-control border px-2.5 py-1 text-xs font-medium transition-colors " +
            (filtersOpen
              ? "border-line2 bg-raise2 text-t1"
              : "border-line bg-raise text-t2 hover:text-t1")
          }
        >
          Filters
        </button>
        {/* The column-visibility mini popover: every column toggleable except Part (the row
            identity is never hideable). Hidden columns free horizontal room; visible ones keep
            their fixed tracks (never squished). */}
        <div className="relative flex-none" ref={columnsRef}>
          <button
            type="button"
            onClick={() => setColumnsOpen((v) => !v)}
            aria-pressed={columnsOpen}
            aria-haspopup="true"
            className={
              "flex-none rounded-control border px-2.5 py-1 text-xs font-medium transition-colors " +
              (columnsOpen
                ? "border-line2 bg-raise2 text-t1"
                : "border-line bg-raise text-t2 hover:text-t1")
            }
          >
            Columns
          </button>
          {columnsOpen ? (
            <div
              data-testid="column-picker"
              className="absolute right-0 top-full z-[60] mt-1.5 w-44 rounded-card border border-line bg-popover p-2 shadow-pop"
            >
              {table
                .getAllLeafColumns()
                .filter((c) => c.id !== "mpn_example")
                .map((c) => (
                  <label
                    key={c.id}
                    className="flex cursor-pointer items-center gap-2 rounded-control px-2 py-1 text-xs text-t2 hover:bg-hover hover:text-t1"
                  >
                    <input
                      type="checkbox"
                      checked={c.getIsVisible()}
                      onChange={c.getToggleVisibilityHandler()}
                      className="accent-[var(--c-acc)]"
                    />
                    {String(c.columnDef.header)}
                  </label>
                ))}
            </div>
          ) : null}
        </div>
      </div>

      {/* the scroll container: header + filter row + virtualized body all share the grid */}
      <div
        ref={scrollRef}
        data-testid="spec-matrix-scroll"
        className="min-h-0 flex-1 overflow-auto rounded-card border border-line bg-raise"
      >
        <div className="min-w-max">
          {/* header (sticky), one hairline underline (the whole border budget for the grid) */}
          <div
            style={gridStyle}
            className="sticky top-0 z-[2] border-b border-line bg-[var(--c-sticky)] backdrop-blur"
          >
            {table.getHeaderGroups()[0].headers.map((header) => {
              const meta = header.column.columnDef.meta as ColMeta | undefined;
              const sorted = header.column.getIsSorted();
              return (
                <div key={header.id} className="relative flex min-w-0">
                  <button
                    type="button"
                    onClick={header.column.getToggleSortingHandler()}
                    className={
                      "flex min-w-0 flex-1 items-center gap-1 px-2.5 py-2 text-2xs font-semibold text-t3 hover:text-t1 " +
                      (meta?.align === "right" ? "justify-end" : "justify-start")
                    }
                  >
                    <span className="truncate">
                      {flexRender(header.column.columnDef.header, header.getContext())}
                    </span>
                    <span className="w-2 flex-none text-t2">
                      {sorted === "asc" ? "↑" : sorted === "desc" ? "↓" : ""}
                    </span>
                  </button>
                  {/* the drag handle: a hairline that widens on hover; double-click resets */}
                  <div
                    role="separator"
                    aria-label={`Resize ${String(header.column.columnDef.header)}`}
                    data-testid={`col-resize-${header.column.id}`}
                    onMouseDown={header.getResizeHandler()}
                    onTouchStart={header.getResizeHandler()}
                    onDoubleClick={() => header.column.resetSize()}
                    className="absolute right-0 top-0 h-full w-1.5 cursor-col-resize select-none border-r border-line hover:border-acc"
                  />
                </div>
              );
            })}
          </div>

          {/* the per-column filter row, revealed on demand (dense, not noisy) */}
          {filtersOpen ? (
            <div
              style={gridStyle}
              data-testid="spec-matrix-filters"
              className="sticky top-[33px] z-[1] border-b border-line bg-[var(--c-sticky)] backdrop-blur"
            >
              {table.getHeaderGroups()[0].headers.map((header) => (
                <div key={header.id} className="flex items-stretch px-1.5 py-1.5">
                  <ColumnFilter column={header.column} />
                </div>
              ))}
            </div>
          ) : null}

          {/* body */}
          {modelRows.length === 0 ? (
            <div className="px-4 py-16 text-center text-sm text-t3">
              No MCUs match the current filters.
            </div>
          ) : (
            <div
              style={{ height: useVirtual ? totalSize : undefined, position: "relative" }}
            >
              {(useVirtual ? virtualItems : modelRows.map((_, i) => ({ index: i, start: 0, key: modelRows[i].id }))).map(
                (vi) => {
                  const row = modelRows[vi.index];
                  const selected = row.original.part === activePart;
                  return (
                    <button
                      key={row.id}
                      type="button"
                      onClick={() => onSelectPart(row.original.part)}
                      aria-current={selected ? "true" : undefined}
                      style={{
                        ...gridStyle,
                        ...(useVirtual
                          ? {
                              position: "absolute",
                              top: 0,
                              left: 0,
                              right: 0,
                              height: ROW_HEIGHT,
                              transform: `translateY(${vi.start}px)`,
                            }
                          : { height: ROW_HEIGHT }),
                      }}
                      className={
                        "items-center border-b border-line/60 text-left transition-colors " +
                        (selected ? "bg-acc-soft" : "hover:bg-[var(--c-hover)]")
                      }
                    >
                      {row.getVisibleCells().map((cell) => {
                        const meta = cell.column.columnDef.meta as ColMeta | undefined;
                        return (
                          <div
                            key={cell.id}
                            className={
                              "flex min-w-0 items-center overflow-hidden px-2.5 " +
                              (meta?.align === "right" ? "justify-end" : "justify-start")
                            }
                          >
                            {flexRender(cell.column.columnDef.cell, cell.getContext())}
                          </div>
                        );
                      })}
                    </button>
                  );
                },
              )}
            </div>
          )}
          {/* End-of-results line: the space after a narrow result set reads as a finished list,
              not a dead void, and restates the match count where the eye already is. */}
          {modelRows.length > 0 ? (
            <div className="tnum border-t border-line px-2.5 py-2 text-center font-mono text-2xs text-t3">
              {modelRows.length === rows.length
                ? `All ${rows.length.toLocaleString()} parts shown`
                : `${modelRows.length.toLocaleString()} of ${rows.length.toLocaleString()} parts match`}
            </div>
          ) : null}
        </div>
      </div>
    </div>
  );
}

// A tabular figure with its unit demoted to t3 (a spec reads distinctly from a bare count).
function NumCell({ value, unit }: { value: number; unit?: string }) {
  if (value == null || Number.isNaN(value)) {
    return <span className="font-mono text-xs text-t3">{"–"}</span>;
  }
  return (
    <span className="tnum font-mono text-xs text-t1">
      {value.toLocaleString()}
      {unit ? <span className="ml-0.5 text-t3">{unit}</span> : null}
    </span>
  );
}

// The per-column filter control: a text box for identity columns, a compact min/max pair for the
// numeric columns (seeded from the faceted min/max). Mutates only the table's columnFilters state.
function ColumnFilter({
  column,
}: {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  column: any;
}) {
  const meta = column.columnDef.meta as ColMeta | undefined;
  const value = column.getFilterValue();
  if (meta?.filter === "range") {
    const [min, max] = (column.getFacetedMinMaxValues() as [number, number] | undefined) ?? [];
    const range = (value as [number | "", number | ""]) ?? ["", ""];
    return (
      // Stacked min-over-max inside ONE field container (a hairline divider between the halves),
      // so every filter cell reads as a single control and the row keeps one rhythm. Side-by-side
      // inputs cannot fit the 52px peripheral columns at a usable width.
      <div className="flex w-full flex-col overflow-hidden rounded-control bg-field">
        <input
          type="number"
          inputMode="numeric"
          aria-label={`${column.columnDef.header} minimum`}
          placeholder={min != null ? String(min) : "min"}
          value={range[0] === "" || range[0] == null ? "" : range[0]}
          onChange={(e) =>
            column.setFilterValue((old: [unknown, unknown]) => [
              e.target.value === "" ? undefined : Number(e.target.value),
              (old?.[1] as number) ?? undefined,
            ])
          }
          className="tnum w-full min-w-0 bg-transparent px-1.5 py-0.5 text-2xs font-mono text-t1 outline-none placeholder:text-t3"
        />
        <input
          type="number"
          inputMode="numeric"
          aria-label={`${column.columnDef.header} maximum`}
          placeholder={max != null ? String(max) : "max"}
          value={range[1] === "" || range[1] == null ? "" : range[1]}
          onChange={(e) =>
            column.setFilterValue((old: [unknown, unknown]) => [
              (old?.[0] as number) ?? undefined,
              e.target.value === "" ? undefined : Number(e.target.value),
            ])
          }
          className="tnum w-full min-w-0 border-t border-line bg-transparent px-1.5 py-0.5 text-2xs font-mono text-t1 outline-none placeholder:text-t3"
        />
      </div>
    );
  }
  return (
    <input
      type="text"
      aria-label={`Filter ${column.columnDef.header}`}
      placeholder="Filter"
      value={(value as string) ?? ""}
      onChange={(e) => column.setFilterValue(e.target.value)}
      className="h-full w-full min-w-0 rounded-control bg-field px-1.5 py-0.5 text-2xs text-t1 outline-none placeholder:text-t3"
    />
  );
}
