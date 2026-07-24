/**
 * PinoutTable: the selected part's ENTIRE pinout as a flat, scrollable table (owner ask
 * 2026-07-23) - the per-pin build-card reading of the same PinoutDTO the map draws, so nothing is
 * fetched. Columns: position, name, category (the shared color-is-data dot), type, 5V, and the
 * pin's AF set (each entry AF<n> SIGNAL, the mux fact the whole compatibility story runs on).
 * A row click selects the pin exactly like clicking its pad on the map (one selection model).
 */
import type { PinDTO, PinoutDTO } from "../../api/types";
import { LegendSwatch } from "../primitives";
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
  return (
    <div
      className="min-h-0 flex-1 overflow-auto rounded-card bg-stage shadow-[inset_0_1px_0_var(--edge-hi)]"
      data-testid="pinout-table"
    >
      <table className="w-full border-collapse text-left">
        <thead className="sticky top-0 z-[1] bg-[var(--c-sticky)] backdrop-blur">
          <tr className="border-b border-line text-2xs font-semibold text-t3">
            <th className="px-2.5 py-1.5">Pin</th>
            <th className="px-2.5 py-1.5">Name</th>
            <th className="px-2.5 py-1.5">Category</th>
            <th className="px-2.5 py-1.5">5V</th>
            <th className="px-2.5 py-1.5">Alternate Functions</th>
          </tr>
        </thead>
        <tbody>
          {pins.map((p) => {
            const selected = p.position === selectedPosition;
            return (
              <tr
                key={`${p.position}-${p.raw_pin_name}`}
                onClick={() => onSelectPosition(p.position)}
                aria-selected={selected}
                className={
                  "cursor-pointer border-b border-line/60 align-top " +
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
