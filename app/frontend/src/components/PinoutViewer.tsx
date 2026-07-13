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

// Pin identifiers are usually numeric ("1".."64") but can be alphanumeric ("A1");
// compare numerically when both sides parse as numbers, else fall back to a locale
// compare so "10" never sorts before "2".
function comparePins(a: PinoutPin, b: PinoutPin, key: SortKey): number {
  const av = a[key];
  const bv = b[key];
  if (key === "pin") {
    const an = Number(av);
    const bn = Number(bv);
    if (Number.isFinite(an) && Number.isFinite(bn) && an !== bn) return an - bn;
  }
  return av.localeCompare(bv, undefined, { numeric: true });
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

  const provenance =
    source ? (confidence ? `${source} · ${confidence}` : source) : "";

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
                className="inline-flex items-center text-xs uppercase tracking-wide text-t3 hover:text-t1"
              >
                Pin{indicator("pin")}
              </button>
            </th>
            <th className="px-4 py-2 text-left font-medium">
              <button
                type="button"
                aria-label="Sort By Name"
                onClick={() => toggleSort("name")}
                className="inline-flex items-center text-xs uppercase tracking-wide text-t3 hover:text-t1"
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
