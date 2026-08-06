/**
 * What a pinout ROW is: the columns the record wrote, how one cell reads, and which rows a filter
 * keeps.
 *
 * A pinout arrives as a list of loose records rather than as a declared shape, because what a
 * manufacturer states per pin differs by part - a connector has positions and mating halves, an
 * MCU has alternate functions, a regulator has three pins and a note. So the columns are UNIONED
 * off the data instead of being listed anywhere, and every one of them is searchable for the same
 * reason: on a hundred-pin package, finding the signal is the whole task.
 *
 * Kept beside `PinoutTable.tsx` rather than inside it so the union and the match can be checked
 * against a record without rendering a table, which is how `WorkspaceSheets.test.tsx` reads them.
 *
 * A `.tsx` file with no JSX in it, on purpose: `formatPin` authors the two words a boolean cell
 * renders, and the copy gates next door read `.tsx` sources only.
 */

/** The pinout columns, in the order the record wrote them, unioned across every pin. */
export function pinoutColumns(pinout: Array<Record<string, unknown>>): string[] {
  const columns: string[] = [];
  for (const entry of pinout) {
    for (const key of Object.keys(entry)) {
      if (!columns.includes(key)) columns.push(key);
    }
  }
  return columns;
}

/** Does any cell of this pin match what was typed? Every column is searchable. */
export function pinMatches(
  entry: Record<string, unknown>,
  columns: string[],
  needle: string,
): boolean {
  if (!needle) return true;
  const hay = columns.map((column) => formatPin(entry[column])).join(" ").toLowerCase();
  return hay.includes(needle.toLowerCase());
}

export function formatPin(value: unknown): string {
  if (value == null) return "";
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (typeof value === "object") return "";
  return String(value);
}
