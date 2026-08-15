/**
 * The complete pinout, one row per pin.
 *
 * A pinout is genuinely tabular - one row per pin, one column per recorded attribute - and a
 * hundred-pin package needs the width to be read at all. It is therefore the one part of the
 * specification record that keeps a dedicated surface of its own rather than living in the
 * specification column beside the ordinary property rows.
 */
import { useMemo, useState, type ReactNode } from "react";
import { useText } from "../../lib/copy";
import { DataTable, EmptyState, Section } from "../primitives";
import { formatPin, pinMatches, pinoutColumns } from "./pinoutRows";

/**
 * The complete pinout, one row per pin. Never truncated: this is the exhaustive surface.
 *
 * The filter is here rather than in a second pinout component. `components/PinoutViewer.tsx` used
 * to be a separate filterable/sortable pin table reading `specs.pinout` directly; it lost its only
 * importer when `DetailPanel` was deleted, and re-surfacing it would have put two pinout tables in
 * one sheet reading two different shapes of the same data. This table already renders every
 * column the record wrote, which is strictly more than that one could, so the one capability worth
 * keeping - finding a signal in a 100-pin package - moved onto it and the duplicate went.
 */
export function PinoutTable({
  pinout,
  action,
}: {
  pinout: Array<Record<string, unknown>>;
  action?: ReactNode;
}) {
  const [filter, setFilter] = useState("");
  const tableLabel = useText("component-browser.pinout-table", "Pinout");
  const filterLabel = useText("component-browser.pinout-filter", "Filter pins");
  const columns = pinoutColumns(pinout);
  const needle = filter.trim();
  // Each kept pin carries its ORDINAL IN THE RECORD, which is what identifies a row here. The
  // rendered list is filtered as somebody types, so a row's position on screen names a different
  // pin on every keystroke; "the seventh pin the record wrote" names the same pin whatever the
  // filter is showing. The record itself supplies no id - a pinout is a list of loose per-pin
  // records whose keys differ by part - so the ordinal is the identity there is.
  const shown = useMemo(() => {
    const rows: Array<{ entry: Record<string, unknown>; position: number }> = [];
    for (let position = 0; position < pinout.length; position += 1) {
      if (pinMatches(pinout[position], columns, needle)) {
        rows.push({ entry: pinout[position], position });
      }
    }
    return rows;
    // `columns` is derived from `pinout` on every render, so `pinout` is the real dependency.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pinout, needle]);
  return (
    <Section
      title="Pinout"
      copyId="component-browser.pinout-title"
      count={pinout.length}
      action={action}
    >
      {pinout.length === 0 ? (
        <EmptyState id="component-browser.pinout-empty">No pinout on record.</EmptyState>
      ) : (
        <>
          <input
            data-dev-id="component-browser.pinout-filter"
            type="search"
            value={filter}
            aria-label={filterLabel}
            placeholder={filterLabel}
            onChange={(event) => setFilter(event.target.value)}
            className="h-7 w-full rounded-control border border-line bg-field px-2 text-xs text-t1 outline-none focus:border-focus"
          />
          {shown.length === 0 ? (
            <EmptyState id="component-browser.pinout-no-match">
              No pin matches this filter.
            </EmptyState>
          ) : (
            <DataTable
              devId="component-browser.pinout-table"
              label={tableLabel}
              headings={columns.map((column) => column.replace(/_/g, " "))}
            >
              {shown.map(({ entry, position }) => (
                <tr key={position} className="border-b border-line/60 last:border-b-0">
                  {columns.map((column) => (
                    <td key={column} className="tnum whitespace-nowrap px-3 py-1 font-mono">
                      {formatPin(entry[column])}
                    </td>
                  ))}
                </tr>
              ))}
            </DataTable>
          )}
        </>
      )}
    </Section>
  );
}
