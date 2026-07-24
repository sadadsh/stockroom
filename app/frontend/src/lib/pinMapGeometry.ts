/**
 * Pin-map geometry: a pure, deterministic port of Hardware's pin_map_geometry
 * (tools/stm32_pins_tab.py:193-234) for LQFP/QFN perimeter packages, plus a genuinely new
 * BGA/WLCSP ball-grid layout Hardware never had. It computes per-pad screen rects only, never SVG
 * (INTERFACES.md section 6: pin_map_svg is explicitly NOT ported); PinoutMap draws the rects.
 *
 * Two rules from CONTEXT decision 6 + PITFALLS.md Pitfall 4 the port must honor:
 * - Perimeter pads are placed by each pin's REAL lqfp_side ("left"/"bottom"/"right"/"top"), never
 *   by re-splitting an index range (per = n // 4). Depopulated/irregular perimeter packages then
 *   render correctly rather than by a naive four-way index guess.
 * - A BGA ball is placed at its explicit (bga_row letter, bga_col) grid cell, the row letter
 *   mapped skipping the CubeMX-omitted 'I'. An absent ball is simply no pad at that cell; the grid
 *   is never a guessed square root of the pin count.
 */
import type { PinoutGeometryDTO } from "../api/types";

// The minimal per-pad geometry input the layout reads: a position label plus its placement hint
// (perimeter lqfp_side, or a BGA row/col cell). Both PinDTO (Phase 4's pinout) and UnionPositionDTO
// (Phase 5's socket-union) satisfy this structurally, so the SAME geometry path lays out both the
// pinout map and the compatibility union map (INTERFACES.md section 5, CONTEXT decision 3) with no
// reimplementation. The layout never reads any per-pin fact beyond these four fields.
export interface PinGeometryInput {
  position: string;
  lqfp_side?: string | null;
  bga_row?: string | null;
  bga_col?: number | null;
}

export interface PadRect {
  x: number;
  y: number;
  w: number;
  h: number;
}

export type PadSide = "left" | "bottom" | "right" | "top";

export interface PadLayout {
  position: string;
  rect: PadRect;
  side?: PadSide;
}

export interface PinMapLayout {
  body: PadRect;
  pins: PadLayout[];
  // the QFN exposed thermal pad, when the package carries one (not a <Pin>); drawn as a plain
  // center square, never encoded as a pin.
  centerPad?: PadRect;
}

const EMPTY: PinMapLayout = { body: { x: 0, y: 0, w: 0, h: 0 }, pins: [] };

// The BGA row-letter alphabet with 'I' removed (the letter CubeMX omits). Bijective base-25 so
// multi-letter rows (AA, AB, ...) continue past Z for large ball grids.
const BGA_ALPHABET = "ABCDEFGHJKLMNOPQRSTUVWXYZ";

// "A" -> 0, "H" -> 7, "J" -> 8 (I skipped), "Z" -> 24, "AA" -> 25, ... Returns -1 for an
// unparseable label so the caller can skip it rather than mislay a pad.
export function bgaRowIndex(label: string): number {
  if (!label) return -1;
  let n = 0;
  for (const ch of label.toUpperCase()) {
    const d = BGA_ALPHABET.indexOf(ch);
    if (d < 0) return -1;
    n = n * BGA_ALPHABET.length + (d + 1);
  }
  return n - 1;
}

function round2(v: number): number {
  return Math.round(v * 100) / 100;
}

function roundRect(r: PadRect): PadRect {
  return { x: round2(r.x), y: round2(r.y), w: round2(r.w), h: round2(r.h) };
}

// The LQFP/QFN perimeter layout: pads grouped by their real lqfp_side, ordered along each side by
// numeric position, at a per-side even pitch (so an unequal/depopulated side still lays out
// correctly). Mirrors the Python body/pad proportions (body 0.66 of span, pad length 0.095).
function perimeterLayout(
  pins: PinGeometryInput[],
  geometry: PinoutGeometryDTO,
  w: number,
  h: number,
  margin: number,
): PinMapLayout {
  const span = Math.min(w, h) - 2 * margin;
  const body = span * 0.66;
  const plen = span * 0.095;
  const cx = w / 2;
  const cy = h / 2;
  const bl = cx - body / 2;
  const bt = cy - body / 2;
  const br = cx + body / 2;
  const bb = cy + body / 2;

  const bySide: Record<PadSide, PinGeometryInput[]> = { left: [], bottom: [], right: [], top: [] };
  for (const p of pins) {
    if (p.lqfp_side && p.lqfp_side in bySide) bySide[p.lqfp_side as PadSide].push(p);
  }
  const byPosition = (a: PinGeometryInput, b: PinGeometryInput) =>
    (parseInt(a.position, 10) || 0) - (parseInt(b.position, 10) || 0);

  const out: PadLayout[] = [];
  (Object.keys(bySide) as PadSide[]).forEach((side) => {
    const group = bySide[side].slice().sort(byPosition);
    const count = group.length;
    if (count === 0) return;
    const pitch = body / count;
    const pw = pitch * 0.6;
    group.forEach((p, i) => {
      let rect: PadRect;
      if (side === "left") {
        rect = { x: bl - plen, y: bt + i * pitch + (pitch - pw) / 2, w: plen, h: pw };
      } else if (side === "bottom") {
        rect = { x: bl + i * pitch + (pitch - pw) / 2, y: bb, w: pw, h: plen };
      } else if (side === "right") {
        rect = { x: br, y: bb - i * pitch - (pitch + pw) / 2, w: plen, h: pw };
      } else {
        rect = { x: br - i * pitch - (pitch + pw) / 2, y: bt - plen, w: pw, h: plen };
      }
      out.push({ position: p.position, rect: roundRect(rect), side });
    });
  });

  const layout: PinMapLayout = {
    body: roundRect({ x: bl, y: bt, w: body, h: body }),
    pins: out,
  };
  if (geometry.has_center_pad) {
    const size = body * 0.34;
    layout.centerPad = roundRect({ x: cx - size / 2, y: cy - size / 2, w: size, h: size });
  }
  return layout;
}

// The BGA/WLCSP ball-grid layout: each ball at its explicit (bga_row, bga_col) cell. rows/cols come
// from the geometry when present, else from the real ball maxima (never a guessed sqrt grid). An
// absent ball leaves an empty cell.
function ballGridLayout(
  pins: PinGeometryInput[],
  geometry: PinoutGeometryDTO,
  w: number,
  h: number,
  margin: number,
): PinMapLayout {
  const placed = pins
    .map((p) => ({ p, r: bgaRowIndex(p.bga_row ?? ""), c: (p.bga_col ?? 0) - 1 }))
    .filter((e) => e.r >= 0 && e.c >= 0);
  if (placed.length === 0) return EMPTY;

  const maxRow = Math.max(...placed.map((e) => e.r));
  const maxCol = Math.max(...placed.map((e) => e.c));
  const rows = geometry.rows && geometry.rows > 0 ? geometry.rows : maxRow + 1;
  const cols = geometry.cols && geometry.cols > 0 ? geometry.cols : maxCol + 1;

  const span = Math.min(w, h) - 2 * margin;
  const cell = span / Math.max(rows, cols);
  const pad = cell * 0.66;
  const gridW = cols * cell;
  const gridH = rows * cell;
  const gx = (w - gridW) / 2;
  const gy = (h - gridH) / 2;

  const out: PadLayout[] = placed.map(({ p, r, c }) => ({
    position: p.position,
    rect: roundRect({
      x: gx + c * cell + (cell - pad) / 2,
      y: gy + r * cell + (cell - pad) / 2,
      w: pad,
      h: pad,
    }),
  }));

  return { body: roundRect({ x: gx, y: gy, w: gridW, h: gridH }), pins: out };
}

// One pin-number label: where to draw a pad's position text and how to anchor/rotate it so it
// reads like a datasheet pinout (outside the pad on a perimeter package; grid-edge headers on a
// ball grid come from ballGridHeaders instead).
export interface PadLabel {
  position: string;
  x: number;
  y: number;
  anchor: "start" | "middle" | "end";
  /** degrees, applied around (x, y); vertical side labels stay horizontal (0) */
  rotate: number;
}

const LABEL_GAP = 5;

/**
 * Per-pad position labels for a PERIMETER layout, placed just outside each pad's outer end,
 * anchored toward the body so the number column hugs the pin row (the datasheet reading). Returns
 * [] for a ball grid (use ballGridHeaders there - per-ball text would collide at density).
 */
export function perimeterLabels(layout: PinMapLayout): PadLabel[] {
  const out: PadLabel[] = [];
  for (const pad of layout.pins) {
    const { x, y, w, h } = pad.rect;
    if (!pad.side) continue;
    if (pad.side === "left") {
      out.push({ position: pad.position, x: x - LABEL_GAP, y: y + h / 2, anchor: "end", rotate: 0 });
    } else if (pad.side === "right") {
      out.push({ position: pad.position, x: x + w + LABEL_GAP, y: y + h / 2, anchor: "start", rotate: 0 });
    } else if (pad.side === "top") {
      const cx = x + w / 2;
      out.push({ position: pad.position, x: cx, y: y - LABEL_GAP, anchor: "start", rotate: -90 });
    } else {
      const cx = x + w / 2;
      out.push({ position: pad.position, x: cx, y: y + h + LABEL_GAP, anchor: "end", rotate: -90 });
    }
  }
  return out;
}

// One ball-grid edge header (a row letter or a column number), mirrored on both edges so the
// grid reads like a real BGA map from any side.
export interface GridHeader {
  text: string;
  x: number;
  y: number;
}

/**
 * Row-letter and column-number headers for a BALL-GRID layout, derived from the real placed balls
 * (never a guessed span). Row letters sit left and right of the grid; column numbers above and
 * below. Returns { rows: [], cols: [] } for a perimeter layout or an empty grid.
 */
export function ballGridHeaders(
  pins: ReadonlyArray<Pick<PinGeometryInput, "position" | "bga_row" | "bga_col">>,
  layout: PinMapLayout,
): { rows: GridHeader[]; cols: GridHeader[] } {
  const rows: GridHeader[] = [];
  const cols: GridHeader[] = [];
  if (layout.pins.length === 0) return { rows, cols };
  const byPosition = new Map(layout.pins.map((p) => [p.position, p.rect]));
  const seenRows = new Map<string, { y: number }>();
  const seenCols = new Map<number, { x: number }>();
  for (const p of pins) {
    const rect = byPosition.get(p.position);
    if (!rect || p.bga_row == null || p.bga_col == null) continue;
    if (!seenRows.has(p.bga_row)) seenRows.set(p.bga_row, { y: rect.y + rect.h / 2 });
    if (!seenCols.has(p.bga_col)) seenCols.set(p.bga_col, { x: rect.x + rect.w / 2 });
  }
  const left = layout.body.x - 12;
  const right = layout.body.x + layout.body.w + 12;
  const top = layout.body.y - 8;
  const bottom = layout.body.y + layout.body.h + 14;
  for (const [row, { y }] of seenRows) {
    rows.push({ text: row, x: left, y }, { text: row, x: right, y });
  }
  for (const [col, { x }] of seenCols) {
    cols.push({ text: String(col), x, y: top }, { text: String(col), x, y: bottom });
  }
  return { rows, cols };
}

/**
 * Lay a package's pins onto a centered body for a `w` x `h` viewport. Pure and deterministic; an
 * empty pin list returns an empty, zero-body layout (never throws). The `body_shape` picks the
 * algorithm: qfp/qfn -> perimeter (by real lqfp_side); bga/wlcsp -> ball grid.
 */
export function pinMapGeometry(
  pins: PinGeometryInput[],
  geometry: PinoutGeometryDTO,
  w: number,
  h: number,
  margin = 46,
): PinMapLayout {
  if (!pins || pins.length === 0) return EMPTY;
  if (geometry.body_shape === "bga" || geometry.body_shape === "wlcsp") {
    return ballGridLayout(pins, geometry, w, h, margin);
  }
  return perimeterLayout(pins, geometry, w, h, margin);
}
