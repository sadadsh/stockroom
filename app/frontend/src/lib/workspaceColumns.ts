/**
 * The three-column geometry of an opened component, and where it is remembered.
 *
 * The columns are a WORKSTATION preference, not a document: which of CAD, specifications and
 * sourcing a person wants wider is a property of the monitor they are sitting at, so it is kept in
 * local browser storage rather than in the durable UI session that travels with a library. That is
 * also why nothing here bumps a schema version - a machine that has never been dragged simply has
 * no entry and gets the proportions below.
 *
 * All exports are pure except the two that touch storage, and both of those swallow every failure:
 * a locked-down browser with `localStorage` disabled must render the workspace at its defaults, not
 * fail to render it at all.
 */

export type WorkspaceColumnId = "cad" | "specifications" | "sourcing";

export const WORKSPACE_COLUMN_IDS: readonly WorkspaceColumnId[] = [
  "cad",
  "specifications",
  "sourcing",
];

/**
 * Below these a column stops being a column. The CAD column has to hold a technical preview, the
 * specification column a label column plus a value column plus a source, and the sourcing column a
 * provider name beside a price. A layout that lets any of them go under is a layout that has
 * silently deleted one of the three questions the screen exists to answer.
 */
export const WORKSPACE_COLUMN_MIN: Record<WorkspaceColumnId, number> = {
  cad: 260,
  specifications: 390,
  sourcing: 250,
};

/** The proportions a machine that has never been dragged opens at. */
export const WORKSPACE_COLUMN_FRACTION: Record<WorkspaceColumnId, number> = {
  cad: 0.29,
  specifications: 0.45,
  sourcing: 0.26,
};

/** The splitter between one column and the next. Two splitters, three columns. */
export type WorkspaceSplitterId = "cad-specifications" | "specifications-sourcing";

export const WORKSPACE_SPLITTERS: readonly WorkspaceSplitterId[] = [
  "cad-specifications",
  "specifications-sourcing",
];

/** Which two columns a splitter moves between. Dragging never touches the third. */
export const SPLITTER_NEIGHBOURS: Record<
  WorkspaceSplitterId,
  readonly [WorkspaceColumnId, WorkspaceColumnId]
> = {
  "cad-specifications": ["cad", "specifications"],
  "specifications-sourcing": ["specifications", "sourcing"],
};

export type WorkspaceColumnWidths = Record<WorkspaceColumnId, number>;

export const WORKSPACE_COLUMNS_STORAGE_KEY = "stockroom.component-workspace.columns.v1";

/** The smallest viewport at which all three columns still clear their minimums. */
export const WORKSPACE_COLUMNS_MIN_TOTAL =
  WORKSPACE_COLUMN_MIN.cad + WORKSPACE_COLUMN_MIN.specifications + WORKSPACE_COLUMN_MIN.sourcing;

function isFiniteWidth(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value) && value > 0;
}

/**
 * The stored preference, as FRACTIONS of the workspace rather than pixels.
 *
 * Pixels would be wrong the first time the window changed size: a person who dragged the
 * specification column to 700px on a 1920 monitor does not want 700px on a 1366 one, they want the
 * same share of the screen. Fractions survive the move; pixels only survive the monitor.
 */
export interface StoredColumnFractions {
  cad: number;
  specifications: number;
  sourcing: number;
}

function normalizeFractions(value: unknown): StoredColumnFractions | null {
  if (!value || typeof value !== "object") return null;
  const record = value as Record<string, unknown>;
  const parts = WORKSPACE_COLUMN_IDS.map((id) => record[id]);
  if (!parts.every(isFiniteWidth)) return null;
  const total = (parts as number[]).reduce((sum, part) => sum + part, 0);
  if (!Number.isFinite(total) || total <= 0) return null;
  return {
    cad: (parts[0] as number) / total,
    specifications: (parts[1] as number) / total,
    sourcing: (parts[2] as number) / total,
  };
}

/** The remembered proportions for this machine, or null when nothing usable is stored. */
export function readColumnFractions(): StoredColumnFractions | null {
  try {
    const raw = window.localStorage.getItem(WORKSPACE_COLUMNS_STORAGE_KEY);
    if (!raw) return null;
    return normalizeFractions(JSON.parse(raw) as unknown);
  } catch {
    return null;
  }
}

/** Remember these proportions for this machine. Failure is silent and harmless. */
export function writeColumnFractions(widths: WorkspaceColumnWidths): void {
  const total = widths.cad + widths.specifications + widths.sourcing;
  if (!Number.isFinite(total) || total <= 0) return;
  try {
    window.localStorage.setItem(
      WORKSPACE_COLUMNS_STORAGE_KEY,
      JSON.stringify({
        cad: widths.cad / total,
        specifications: widths.specifications / total,
        sourcing: widths.sourcing / total,
      }),
    );
  } catch {
    /* A browser that refuses storage still gets a working workspace. */
  }
}

/**
 * Turn proportions into pixels for a workspace this wide, honouring every minimum.
 *
 * The clamp is done in one pass and then the REMAINDER is redistributed across the columns that
 * are still above their floor, so raising one column to its minimum never quietly pushes another
 * below its own. Below `WORKSPACE_COLUMNS_MIN_TOTAL` nothing can satisfy all three; the minimums
 * are returned anyway and the workspace scrolls its column band horizontally rather than deleting
 * a column, which is the one outcome the layout forbids.
 */
export function resolveColumnWidths(
  total: number,
  fractions: StoredColumnFractions | null = null,
): WorkspaceColumnWidths {
  const source = fractions ?? WORKSPACE_COLUMN_FRACTION;
  if (!Number.isFinite(total) || total <= WORKSPACE_COLUMNS_MIN_TOTAL) {
    return { ...WORKSPACE_COLUMN_MIN };
  }
  const raw: WorkspaceColumnWidths = {
    cad: total * source.cad,
    specifications: total * source.specifications,
    sourcing: total * source.sourcing,
  };
  const widths: WorkspaceColumnWidths = { ...raw };
  for (const id of WORKSPACE_COLUMN_IDS) {
    widths[id] = Math.max(WORKSPACE_COLUMN_MIN[id], widths[id]);
  }
  // Give the rounding error (and whatever the floors just claimed) to the columns with slack.
  let drift = widths.cad + widths.specifications + widths.sourcing - total;
  for (let pass = 0; pass < WORKSPACE_COLUMN_IDS.length && Math.abs(drift) > 0.5; pass += 1) {
    const elastic = WORKSPACE_COLUMN_IDS.filter(
      (id) => widths[id] - WORKSPACE_COLUMN_MIN[id] > 0.5 || drift < 0,
    );
    if (elastic.length === 0) break;
    const share = drift / elastic.length;
    for (const id of elastic) {
      widths[id] = Math.max(WORKSPACE_COLUMN_MIN[id], widths[id] - share);
    }
    drift = widths.cad + widths.specifications + widths.sourcing - total;
  }
  return widths;
}

/**
 * Move one splitter by `delta` pixels.
 *
 * A splitter is a ZERO-SUM contract between its two neighbours: whatever one gains the other
 * loses, and the third column does not move. Both neighbours' minimums bound the travel, so a drag
 * that would take either under its floor stops at the floor instead of being ignored - the handle
 * has to keep following the pointer or it feels broken.
 */
export function moveSplitter(
  widths: WorkspaceColumnWidths,
  splitter: WorkspaceSplitterId,
  delta: number,
): WorkspaceColumnWidths {
  const [left, right] = SPLITTER_NEIGHBOURS[splitter];
  if (!Number.isFinite(delta) || delta === 0) return widths;
  const lowest = -(widths[left] - WORKSPACE_COLUMN_MIN[left]);
  const highest = widths[right] - WORKSPACE_COLUMN_MIN[right];
  const applied = Math.max(lowest, Math.min(highest, delta));
  if (applied === 0) return widths;
  return {
    ...widths,
    [left]: widths[left] + applied,
    [right]: widths[right] - applied,
  };
}

/** How far a keyboard press moves a splitter. Shift multiplies it; see the handle. */
export const SPLITTER_KEY_STEP = 16;
