/**
 * What a CAD drawing PROVES about the file it was drawn from, measured off the geometry itself.
 *
 * The symbol and the land pattern are drawn from data rather than shown as pictures precisely so
 * that the questions a person checks them for - how many terminals, does a number repeat, is there
 * a courtyard, what pitch is this actually on - can be ANSWERED instead of squinted at. These are
 * those answers, and they are a module of their own because three surfaces need them and only one
 * of the three draws anything: the module header's status word, the focused module's evidence
 * footer, and the tests that check the arithmetic without a DOM.
 *
 * Every value is measured, never claimed. Where the component's own specification supplies the
 * other side of a comparison it is carried through untouched, and where it does not the comparison
 * is honestly absent rather than assumed to pass.
 */
import type {
  LandGraphic,
  LandPad,
  LandPattern,
  SymbolGeometry,
} from "../../api/client";

/**
 * What the drawing proves about this land pattern.
 *
 * Every value is MEASURED off the geometry that is on screen. `expectedPins` and
 * `expectedPitch` come from the component's own specification, so each comparison has two
 * independent sides; when the specification does not state one, the comparison is honestly
 * absent rather than assumed to pass.
 */
export interface FootprintEvidence {
  pads: number;
  expectedPins: number | null;
  /** Numbers carried by more than one pad. Two pads answering to "3" is a real fault. */
  duplicates: string[];
  unnumbered: number;
  /** Whether a pad numbered "1" exists at all - the marker every orientation check starts from. */
  hasPinOne: boolean;
  /** The most common centre-to-centre spacing between neighbouring pads, in mm. */
  pitch: number | null;
  expectedPitch: number | null;
  courtyard: boolean;
  /** The copper extent in millimetres. What the part actually occupies. */
  size: { width: number; height: number } | null;
}

/** Whether this piece of line work was drawn on the layer whose name ends in `suffix`. */
export function onLayer(graphic: LandGraphic, suffix: string): boolean {
  return graphic.layer.endsWith(suffix);
}

/**
 * The pitch, as the most common nearest-neighbour distance rounded to 0.01 mm.
 *
 * Nearest-neighbour rather than "adjacent in the file", because pad order in a `.kicad_mod` is
 * whatever the exporter wrote and a dual-row package interleaves its rows in some of them. The
 * MODE rather than the mean, because one deliberately offset pad (an exposed pad, a polarity
 * key) would drag an average away from the pitch every other pad actually sits on.
 */
export function padPitch(pads: LandPad[]): number | null {
  if (pads.length < 2) return null;
  const distances: number[] = [];
  for (const pad of pads) {
    let best = Infinity;
    for (const other of pads) {
      if (other === pad) continue;
      const distance = Math.hypot(other.at[0] - pad.at[0], other.at[1] - pad.at[1]);
      if (distance > 0 && distance < best) best = distance;
    }
    if (Number.isFinite(best)) distances.push(Math.round(best * 100) / 100);
  }
  if (distances.length === 0) return null;
  const counts = new Map<number, number>();
  for (const value of distances) counts.set(value, (counts.get(value) ?? 0) + 1);
  const ranked = [...counts.entries()].sort((a, b) => b[1] - a[1] || a[0] - b[0]);
  return ranked[0][0];
}

export function footprintEvidence(
  land: LandPattern,
  expected: { pins: number | null; pitch: number | null },
): FootprintEvidence {
  const seen = new Map<string, number>();
  for (const pad of land.pads) {
    if (!pad.number) continue;
    seen.set(pad.number, (seen.get(pad.number) ?? 0) + 1);
  }
  const box = copperBounds(land.pads);
  return {
    pads: land.pads.length,
    expectedPins: expected.pins,
    duplicates: [...seen.entries()].filter(([, count]) => count > 1).map(([number]) => number),
    unnumbered: land.pads.filter((pad) => !pad.number).length,
    hasPinOne: land.pads.some((pad) => pad.number === "1"),
    pitch: padPitch(land.pads),
    expectedPitch: expected.pitch,
    courtyard: land.graphics.some((graphic) => onLayer(graphic, ".CrtYd")),
    size: box ? { width: box.width, height: box.height } : null,
  };
}

/** The copper extent of a set of pads, in the footprint's own millimetre frame. */
export function copperBounds(pads: LandPad[]) {
  if (pads.length === 0) return null;
  const xs: number[] = [];
  const ys: number[] = [];
  for (const pad of pads) {
    // Rotation is respected by taking the pad's circumscribed extent, so a 90-degree pad is not
    // measured as though it were still lying the other way.
    const half = Math.hypot(pad.size[0], pad.size[1]) / 2;
    xs.push(pad.at[0] - half, pad.at[0] + half);
    ys.push(pad.at[1] - half, pad.at[1] + half);
  }
  const x = Math.min(...xs);
  const y = Math.min(...ys);
  return { x, y, width: Math.max(...xs) - x, height: Math.max(...ys) - y };
}

/**
 * The evidence the footer states, measured from the geometry.
 *
 * Every number here is counted off the pins that were actually drawn. `expectedPins` comes from
 * the component's own specification (its pin count), so "5 pins matched" is a comparison and not
 * a restatement of one side of it - and when the specification does not say, the comparison is
 * honestly absent rather than assumed to pass.
 */
export interface SymbolEvidence {
  pins: number;
  expectedPins: number | null;
  /** Numbers that appear on more than one pin. A real fault, not a style choice. */
  duplicates: string[];
  /** Pins carrying no number at all: a terminal nothing can be mapped to. */
  unnumbered: number;
  hidden: number;
  /** Whether the symbol draws a body at all, and how big it is in millimetres. */
  bounds: { width: number; height: number } | null;
}

export function symbolEvidence(
  geometry: SymbolGeometry,
  expectedPins: number | null,
): SymbolEvidence {
  const seen = new Map<string, number>();
  for (const pin of geometry.pins) {
    if (!pin.number) continue;
    seen.set(pin.number, (seen.get(pin.number) ?? 0) + 1);
  }
  return {
    pins: geometry.pins.length,
    expectedPins,
    duplicates: [...seen.entries()].filter(([, count]) => count > 1).map(([number]) => number),
    unnumbered: geometry.pins.filter((pin) => !pin.number).length,
    hidden: geometry.pins.filter((pin) => pin.hidden).length,
    bounds: geometry.bounds
      ? { width: geometry.bounds.width, height: geometry.bounds.height }
      : null,
  };
}
