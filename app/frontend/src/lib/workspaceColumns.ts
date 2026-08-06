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

/**
 * The sourcing column's floor when there is nothing to source.
 *
 * 250 exists for ONE reason, stated above: the column has to hold a provider name beside a price. A
 * component nobody has sourced has no provider and no price - the column holds the five lifecycle
 * rows and the control that reveals the blank sections, whose widest label is `Manufacturer Status`
 * beside `Unknown` - so the reason for 250 is not present and the number is not either.
 *
 * MEASURED: at 1600x900 the default proportions gave the column 416px to draw five label/value rows
 * in, which is the "sourcing is so dead space" the owner reported. It was NOT a design fault in the
 * column and it was not a fault in the sections either - the seeded capacitor genuinely has no
 * offers, no documents, no related parts and no provenance, so the column was correctly empty. But
 * being correctly empty is not a reason to hold a quarter of the window, so the width follows the
 * content: the surplus goes to the two columns that always have something in it, and it comes back
 * the moment an offer, a document, a related part or a provenance record arrives.
 *
 * THE COLUMN NEVER COLLAPSES AND NEVER HIDES. Same title strip, same name, same six sections in the
 * same order, same blank-section control: only the width changes. The alternative - a collapsed
 * vertical strip - would be a fourth kind of chrome with its own affordance to learn, and a strip
 * narrow enough to be worth collapsing to cannot render a label beside a value at all, so it would
 * be the same dead space in a thinner shape plus a control to undo it.
 */
export const WORKSPACE_SOURCING_SPARSE_MIN = 190;

/** The proportions a machine that has never been dragged opens at. */
export const WORKSPACE_COLUMN_FRACTION: Record<WorkspaceColumnId, number> = {
  cad: 0.29,
  specifications: 0.45,
  sourcing: 0.26,
};

/**
 * The proportions it opens at when there is nothing to source. The 10 points sourcing gives up go
 * mostly to Specifications, which is the dominant surface and the one that always has more to show.
 */
export const WORKSPACE_COLUMN_FRACTION_SPARSE: Record<WorkspaceColumnId, number> = {
  cad: 0.31,
  specifications: 0.53,
  sourcing: 0.16,
};

/** Every column's floor, for a workspace whose sourcing column is carrying lifecycle rows or more. */
export function columnMinimums(sparseSourcing = false): WorkspaceColumnWidths {
  return sparseSourcing
    ? { ...WORKSPACE_COLUMN_MIN, sourcing: WORKSPACE_SOURCING_SPARSE_MIN }
    : { ...WORKSPACE_COLUMN_MIN };
}

/** The smallest viewport at which all three columns still clear their floors. */
export function columnsMinTotal(sparseSourcing = false): number {
  const min = columnMinimums(sparseSourcing);
  return min.cad + min.specifications + min.sourcing;
}

/** The splitter between one column and the next. Two splitters, three columns. */
export type WorkspaceSplitterId = "cad-specifications" | "specifications-sourcing";

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
 * below its own. Below the three columns' combined minimum nothing can satisfy all of them; the
 * minimums are returned anyway and the workspace scrolls its column band horizontally rather than
 * deleting a column, which is the one outcome the layout forbids.
 */
export function resolveColumnWidths(
  total: number,
  fractions: StoredColumnFractions | null = null,
  sparseSourcing = false,
): WorkspaceColumnWidths {
  // A STORED PREFERENCE ALWAYS WINS over the content-aware default. Somebody who dragged this
  // splitter told the workstation what they want; narrowing the column under them the next time they
  // open a part with no offers would be the layout arguing with them.
  const source =
    fractions ??
    (sparseSourcing ? WORKSPACE_COLUMN_FRACTION_SPARSE : WORKSPACE_COLUMN_FRACTION);
  const min = columnMinimums(sparseSourcing);
  const minTotal = min.cad + min.specifications + min.sourcing;
  if (!Number.isFinite(total) || total <= minTotal) {
    return { ...min };
  }
  const raw: WorkspaceColumnWidths = {
    cad: total * source.cad,
    specifications: total * source.specifications,
    sourcing: total * source.sourcing,
  };
  const widths: WorkspaceColumnWidths = { ...raw };
  for (const id of WORKSPACE_COLUMN_IDS) {
    widths[id] = Math.max(min[id], widths[id]);
  }
  // Give the rounding error (and whatever the floors just claimed) to the columns with slack.
  let drift = widths.cad + widths.specifications + widths.sourcing - total;
  for (let pass = 0; pass < WORKSPACE_COLUMN_IDS.length && Math.abs(drift) > 0.5; pass += 1) {
    const elastic = WORKSPACE_COLUMN_IDS.filter(
      (id) => widths[id] - min[id] > 0.5 || drift < 0,
    );
    if (elastic.length === 0) break;
    const share = drift / elastic.length;
    for (const id of elastic) {
      widths[id] = Math.max(min[id], widths[id] - share);
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
  sparseSourcing = false,
): WorkspaceColumnWidths {
  const [left, right] = SPLITTER_NEIGHBOURS[splitter];
  if (!Number.isFinite(delta) || delta === 0) return widths;
  // The SAME floors the automatic width uses. A width the layout is willing to choose has to be one
  // a person is allowed to drag to, or the handle stops following the pointer somewhere the column
  // has already sat by itself.
  const min = columnMinimums(sparseSourcing);
  const lowest = -(widths[left] - min[left]);
  const highest = widths[right] - min[right];
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
