/**
 * PinoutTable: the selected part's ENTIRE pinout as a flat, scrollable table (owner ask
 * 2026-07-23) - the per-pin engineering reading of the same PinoutDTO the map draws, so nothing is
 * fetched. Columns: position, name, category (the shared color-is-data dot), type, 5V, and the
 * pin's AF set (each entry AF<n> SIGNAL, the mux fact the whole compatibility story runs on).
 * A row click selects the pin exactly like clicking its pad on the map (one selection model).
 */
import type { PinDTO, PinoutDTO } from "../../api/types";
import { LegendSwatch } from "../primitives";
import { Text } from "../../lib/copy";
import { categoryFill, categoryLabel, isFiveVoltTolerant } from "./pinEncoding";

const COLLATE = (a: PinDTO, b: PinDTO) =>
  a.position.localeCompare(b.position, undefined, { numeric: true });

export function PinoutTable({
  pinout,
  selectedPosition,
  onSelectPosition,
}: {
  pinout: PinoutDTO;
  selectedPosition: string | null;
  onSelectPosition: (position: string) => void;
}) {
  const pins = pinout.pins.slice().sort(COLLATE);
  // The rows carry aria-selected and answer a click, which is a single-select GRID, not a static
  // table - so say so, and give the grid the keyboard contract that goes with it. Roving tabIndex:
  // the selected row (or the first, before anything is selected) is the one tab stop, and the arrow
  // keys move the selection from there, so a 176-pin part is one stop rather than 176.
  const focusedIndex = Math.max(
    0,
    pins.findIndex((p) => p.position === selectedPosition),
  );
  const moveSelection = (from: number, delta: number) => {
    const next = pins[Math.min(pins.length - 1, Math.max(0, from + delta))];
    if (next) onSelectPosition(next.position);
  };
  const onRowKeyDown = (event: React.KeyboardEvent<HTMLTableRowElement>, index: number) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      onSelectPosition(pins[index].position);
      return;
    }
    const step =
      event.key === "ArrowDown"
        ? 1
        : event.key === "ArrowUp"
          ? -1
          : event.key === "Home"
            ? -pins.length
            : event.key === "End"
              ? pins.length
              : 0;
    if (step === 0) return;
    event.preventDefault();
    moveSelection(index, step);
    // The newly selected row becomes the tab stop, so move focus onto it too.
    const rows = event.currentTarget.parentElement?.children;
    const target = rows?.[Math.min(pins.length - 1, Math.max(0, index + step))];
    if (target instanceof HTMLElement) target.focus();
  };
  return (
    <div
      className="min-h-0 flex-1 overflow-auto rounded-card bg-stage shadow-[inset_0_1px_0_var(--edge-hi)]"
      data-testid="pinout-table"
    >
      <table role="grid" className="w-full border-collapse text-left">
        <thead className="sticky top-0 z-[1] bg-[var(--c-sticky)]">
          <tr className="border-b border-line text-2xs font-semibold text-t3">
            <th className="px-2.5 py-1.5">
              <Text id="stm.pinout.table.pin">Pin</Text>
            </th>
            <th className="px-2.5 py-1.5">
              <Text id="stm.pinout.table.name">Name</Text>
            </th>
            <th className="px-2.5 py-1.5">
              <Text id="stm.pinout.table.category">Class</Text>
            </th>
            <th className="px-2.5 py-1.5">
              <Text id="stm.pinout.table.five-v">5V</Text>
            </th>
            <th className="px-2.5 py-1.5">
              <Text id="stm.pinout.table.alternate-functions">Alternate Functions</Text>
            </th>
          </tr>
        </thead>
        <tbody>
          {pins.map((p, index) => {
            const selected = p.position === selectedPosition;
            return (
              <tr
                key={`${p.position}-${p.raw_pin_name}`}
                onClick={() => onSelectPosition(p.position)}
                onKeyDown={(event) => onRowKeyDown(event, index)}
                tabIndex={index === focusedIndex ? 0 : -1}
                aria-selected={selected}
                className={
                  "cursor-pointer border-b border-line/60 align-top outline-none " +
                  "focus-visible:ring-1 focus-visible:ring-inset focus-visible:ring-[var(--c-line2)] " +
                  (selected ? "bg-acc-soft" : "hover:bg-hover")
                }
              >
                <td className="tnum px-2.5 py-1 font-mono text-xs text-t3">{p.position}</td>
                <td className="px-2.5 py-1 font-mono text-xs font-semibold text-t1">
                  {p.canonical_pin_name}
                </td>
                <td className="px-2.5 py-1">
                  <span className="flex items-center gap-1.5">
                    <LegendSwatch token={categoryFill(p.category)} variant="dot" />
                    <span className="whitespace-nowrap text-xs text-t2">
                      {categoryLabel(p.category)}
                    </span>
                  </span>
                </td>
                <td className="px-2.5 py-1 text-xs text-t3">
                  {isFiveVoltTolerant(p) ? "FT" : ""}
                </td>
                <td className="px-2.5 py-1">
                  {p.alternate_functions.length > 0 ? (
                    <span className="font-mono text-2xs text-t2">
                      {p.alternate_functions
                        .map((af) => `AF${af.af_index} ${af.signal}`)
                        .join(" · ")}
                    </span>
                  ) : p.functions.length > 0 ? (
                    <span className="font-mono text-2xs text-t3">
                      {p.functions.map((fn) => fn.signal).join(" · ")}
                    </span>
                  ) : null}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
