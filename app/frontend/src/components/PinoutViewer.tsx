/**
 * The pinout viewer (M6i): an interactive, filterable, sortable table of a part's
 * pins, read from the persisted record (specs.pinout), never a transient enrich
 * call. The data is {pin, name} only, so this is an honest pin table, not a
 * geometric package diagram (a diagram would need pin side/position data the
 * datasheet extractor does not yet produce). Provenance (source + confidence) is
 * shown when present so the user can judge where the pinout came from.
 */
import { useMemo, useState } from "react";
import type { PinoutPin } from "../api/types";
import { Badge, Card } from "./primitives";

// Read specs.pinout defensively: the record's `specs` is a free-form bag, so tolerate
// missing/malformed data and coerce pin/name to strings (the extractor may emit ints).
export function parsePinout(specs: Record<string, unknown> | undefined): PinoutPin[] {
  const raw = specs?.pinout;
  if (!Array.isArray(raw)) return [];
  const out: PinoutPin[] = [];
  for (const item of raw) {
    if (item && typeof item === "object") {
      const rec = item as Record<string, unknown>;
      const pin = rec.pin;
      const name = rec.name;
      if (pin != null || name != null) {
        out.push({ pin: pin == null ? "" : String(pin), name: name == null ? "" : String(name) });
      }
    }
  }
  return out;
}

type SortKey = "pin" | "name";
interface SortState {
  key: SortKey;
  dir: "asc" | "desc";
}

function provenanceLabel(source?: string, confidence?: string): string {
  return source ? (confidence ? `${source} · ${confidence}` : source) : "";
}

// Pin identifiers are usually numeric ("1".."64") but can be alphanumeric ("A1").
// Numeric-aware collation is the SINGLE mechanism: it orders "1","2","10" correctly
// (not lexicographic "1","10","2") AND handles "A1".."A10", so the numeric-sort test
// stays load-bearing — drop the `numeric` option and it goes red.
function comparePins(a: PinoutPin, b: PinoutPin, key: SortKey): number {
  return a[key].localeCompare(b[key], undefined, { numeric: true });
}

export function PinoutViewer({
  pins,
  source,
  confidence,
}: {
  pins: PinoutPin[];
  source?: string;
  confidence?: string;
}) {
  const [filter, setFilter] = useState("");
  const [sort, setSort] = useState<SortState | null>(null);

  const shown = useMemo(() => {
    const q = filter.trim().toLowerCase();
    let rows = q
      ? pins.filter(
          (p) => p.pin.toLowerCase().includes(q) || p.name.toLowerCase().includes(q),
        )
      : pins.slice();
    if (sort) {
      const factor = sort.dir === "asc" ? 1 : -1;
      rows = rows
        .map((p, i) => [p, i] as const)
        .sort(([a, ai], [b, bi]) => {
          const c = comparePins(a, b, sort.key);
          return c !== 0 ? c * factor : ai - bi; // stable
        })
        .map(([p]) => p);
    }
    return rows;
  }, [pins, filter, sort]);

  function toggleSort(key: SortKey) {
    setSort((prev) =>
      prev && prev.key === key
        ? { key, dir: prev.dir === "asc" ? "desc" : "asc" }
        : { key, dir: "asc" },
    );
  }

  const indicator = (key: SortKey) =>
    sort && sort.key === key ? (sort.dir === "asc" ? " ↑" : " ↓") : "";

  const provenance = provenanceLabel(source, confidence);

  return (
    <Card className="overflow-hidden">
      <div className="flex items-center gap-3 px-4 py-3">
        <span className="text-sm font-medium text-t1">{pins.length} Pins</span>
        {provenance ? (
          <Badge tone={confidence === "high" ? "ok" : "neutral"}>{provenance}</Badge>
        ) : null}
        <input
          type="text"
          aria-label="Filter Pins"
          placeholder="Filter Pins"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          className="ml-auto w-40 rounded-control border border-line2 bg-field px-2.5 py-1 text-sm text-t1 outline-none placeholder:text-t3 focus:border-acc"
        />
      </div>
      <table className="w-full border-t border-line text-sm">
        <thead>
          <tr className="text-t3">
            <th className="w-24 px-4 py-2 text-left font-medium">
              <button
                type="button"
                aria-label="Sort By Pin"
                onClick={() => toggleSort("pin")}
                className="inline-flex items-center text-xs font-medium text-t3 hover:text-t1"
              >
                Pin{indicator("pin")}
              </button>
            </th>
            <th className="px-4 py-2 text-left font-medium">
              <button
                type="button"
                aria-label="Sort By Name"
                onClick={() => toggleSort("name")}
                className="inline-flex items-center text-xs font-medium text-t3 hover:text-t1"
              >
                Name{indicator("name")}
              </button>
            </th>
          </tr>
        </thead>
        <tbody>
          {shown.length === 0 ? (
            <tr>
              <td colSpan={2} className="px-4 py-4 text-center text-sm text-t3">
                No pins match the filter.
              </td>
            </tr>
          ) : (
            shown.map((p, i) => (
              <tr key={`${p.pin}-${p.name}-${i}`} className="border-t border-line">
                <td className="tnum px-4 py-1.5 text-t2">{p.pin}</td>
                <td className="px-4 py-1.5 text-t1">{p.name}</td>
              </tr>
            ))
          )}
        </tbody>
      </table>
    </Card>
  );
}

/**
 * The narrow, persistent pinout card used in the specimen/CAD rail.
 *
 * A pinout is a property of the accepted component representation, not a separate workflow
 * destination. This compact form keeps the complete persisted datasheet extraction beside CAD,
 * uses its own bounded scroller for large packages, and retains filtering without forcing the
 * whole page (or the specimen rail) to become a long table.
 */
export function CompactPinoutCard({
  pins,
  source,
  confidence,
}: {
  pins: PinoutPin[];
  source?: string;
  confidence?: string;
}) {
  const [filter, setFilter] = useState("");
  const query = filter.trim().toLowerCase();
  const shown = useMemo(
    () =>
      query
        ? pins.filter(
            (pin) =>
              pin.pin.toLowerCase().includes(query) ||
              pin.name.toLowerCase().includes(query),
          )
        : pins,
    [pins, query],
  );
  const provenance = provenanceLabel(source, confidence);

  return (
    <section
      data-dev-id="detail.pinout"
      aria-labelledby="detail-pinout-heading"
      className="flex min-h-[112px] max-h-[300px] flex-1 flex-col overflow-hidden rounded-card border border-line bg-s1"
    >
      <div className="flex-none border-b border-line px-2.5 py-2">
        <div className="flex min-w-0 items-baseline gap-2">
          <h3
            id="detail-pinout-heading"
            className="min-w-0 truncate text-xs font-semibold text-t1"
          >
            Datasheet Pinout
          </h3>
          <span className="tnum flex-none text-2xs text-t3">
            {pins.length} {pins.length === 1 ? "Pin" : "Pins"}
          </span>
          {provenance ? (
            <Badge
              tone={confidence === "high" ? "ok" : "neutral"}
              size="sm"
              className="ml-auto max-w-[92px] truncate"
            >
              {provenance}
            </Badge>
          ) : null}
        </div>
        <input
          type="search"
          aria-label="Filter Datasheet Pins"
          placeholder="Filter pin or signal"
          value={filter}
          onChange={(event) => setFilter(event.target.value)}
          className="mt-1.5 h-6 w-full rounded-control border border-line2 bg-field px-2 text-2xs text-t1 outline-none placeholder:text-t3 focus:border-acc"
        />
      </div>

      <div className="grid flex-none grid-cols-2 border-b border-line bg-band text-2xs font-medium text-t3">
        {[0, 1].map((column) => (
          <div
            key={column}
            className="grid grid-cols-[1.75rem_minmax(0,1fr)] px-2 py-1 odd:border-r odd:border-line"
          >
            <span>Pin</span>
            <span>Signal</span>
          </div>
        ))}
      </div>
      <div
        data-dev-id="detail.pinout-list"
        className="grid min-h-0 flex-1 auto-rows-min grid-cols-2 content-start overflow-y-auto"
      >
        {shown.length > 0 ? (
          shown.map((pin, index) => (
            <div
              key={`${pin.pin}-${pin.name}-${index}`}
              className="grid min-h-6 grid-cols-[1.75rem_minmax(0,1fr)] items-center border-b border-line px-2 py-1 odd:border-r"
            >
              <span className="tnum truncate font-mono text-2xs text-t2" title={pin.pin}>
                {pin.pin || "—"}
              </span>
              <span className="truncate text-xs text-t1" title={pin.name}>
                {pin.name || "—"}
              </span>
            </div>
          ))
        ) : (
          <p className="col-span-2 px-2.5 py-3 text-center text-2xs text-t3">
            No pins match this filter.
          </p>
        )}
      </div>
    </section>
  );
}
