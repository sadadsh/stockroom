/**
 * The modular search's filter model - pure, React-free, and driven entirely by the parts' own
 * parametric facets (never a hardcoded per-category parameter list). The overlay holds one
 * SearchFilters value; these helpers encode it into the backend's repeatable `spec` tokens,
 * derive the active-filter chips, and choose the results table's columns from whichever facets
 * the data produced. A category that grows a new spec key gains a facet, a chip, and a column
 * here with zero code change.
 *
 * Contract with the backend (store/parametric.py): an OPTIONS constraint is `<key>:<value>`
 * (values on one key OR together); a RANGE constraint is `<key>:<min>~<max>` over SI-normalized
 * magnitudes (either bound may be blank for open-ended). Category rides the `category` param,
 * not a spec token.
 */
import type { ParametricFacet } from "../api/types";
import { normalizeSpecKey, prettifyValue, resolveSpec, type SpecGroupName } from "./specSchema";

export interface RangeSel {
  min: number | null;
  max: number | null;
}

export interface SearchFilters {
  category: string | null;
  // spec key -> selected option values (OR within a key)
  options: Record<string, string[]>;
  // spec key -> a numeric bound pair (either side may be null = open)
  ranges: Record<string, RangeSel>;
  inStock: boolean;
}

export function emptyFilters(): SearchFilters {
  return { category: null, options: {}, ranges: {}, inStock: false };
}

// --- SI magnitude formatting ------------------------------------------------
//
// The facet + filter magnitudes are SI-normalized to the base unit (1 kΩ -> 1000 Ω), so a range
// reads back in engineering notation only for units that actually take SI prefixes. A unit like
// "%", "°C", or "ppm" is left un-prefixed (0.1% must never render as "100m%").

const _PREFIXABLE = new Set(["Ω", "F", "H", "V", "A", "W", "Hz", "S", "J", "Wh", "Ah"]);
const _PREFIXES: [number, string][] = [
  [1e12, "T"], [1e9, "G"], [1e6, "M"], [1e3, "k"],
  [1, ""], [1e-3, "m"], [1e-6, "µ"], [1e-9, "n"], [1e-12, "p"],
];

function _sig(n: number): string {
  // up to 3 significant figures, trailing zeros trimmed ("1.10" -> "1.1", "1000" -> "1000")
  const s = Math.abs(n) >= 1 ? n.toPrecision(4) : n.toPrecision(3);
  return String(parseFloat(s));
}

/** Canonicalize a facet unit for display: a spelled-out "Ohm(s)" becomes the Ω symbol so it
 * prefixes and reads like the rest of the app; everything else passes through. */
export function normalizeUnit(unit: string | null | undefined): string {
  const u = (unit ?? "").trim();
  return /^ohms?$/i.test(u) ? "Ω" : u;
}

export function formatMagnitude(mag: number, unit: string | null | undefined): string {
  const u = normalizeUnit(unit);
  if (!Number.isFinite(mag)) return "";
  if (mag !== 0 && _PREFIXABLE.has(u)) {
    const abs = Math.abs(mag);
    for (const [scale, prefix] of _PREFIXES) {
      if (abs >= scale) return `${_sig(mag / scale)} ${prefix}${u}`.trim();
    }
  }
  return u ? `${_sig(mag)} ${u}`.replace(/\s+%/, "%") : _sig(mag);
}

const _SI_PARSE: Record<string, number> = {
  p: 1e-12, n: 1e-9, u: 1e-6, "µ": 1e-6, "μ": 1e-6,
  m: 1e-3, k: 1e3, K: 1e3, M: 1e6, G: 1e9, T: 1e12,
};

/** The SI-normalized magnitude of a spec value ("10 kΩ" -> 10000, "220 Ω" -> 220, "5%" -> 5),
 * or null when it is not a leading number. Mirrors the backend `_parse_numeric` so the frontend
 * sorts a numeric column exactly the way the range facet bounded it. */
export function parseMagnitude(value: string): number | null {
  const m = /^([+-]?(?:\d+\.?\d*|\.\d+))\s*(\S*)$/.exec(value.trim());
  if (!m) return null;
  let mag = parseFloat(m[1]);
  if (!Number.isFinite(mag)) return null;
  const unit = m[2];
  if (unit.length >= 2 && unit[0] in _SI_PARSE) mag *= _SI_PARSE[unit[0]];
  return mag;
}

// --- spec-token encoding ----------------------------------------------------

function _rangeToken(key: string, sel: RangeSel): string | null {
  if (sel.min == null && sel.max == null) return null;
  return `${key}:${sel.min ?? ""}~${sel.max ?? ""}`;
}

/** The repeatable `spec` params for GET /parts | /search. Category is NOT encoded here (it is
 * its own param); the In Stock toggle is applied client-side over the rows, not as a spec. */
export function toSpecParams(filters: SearchFilters): string[] {
  const tokens: string[] = [];
  for (const [key, values] of Object.entries(filters.options)) {
    for (const value of values) tokens.push(`${key}:${value}`);
  }
  for (const [key, sel] of Object.entries(filters.ranges)) {
    const t = _rangeToken(key, sel);
    if (t) tokens.push(t);
  }
  return tokens;
}

// --- active-filter chips ----------------------------------------------------

export interface FilterChip {
  id: string; // stable handle for removal
  keyLabel: string; // "Category", "Package", "Resistance"
  value: string; // "Resistors", "0603", "1 kΩ – 10 kΩ"
  remove: SearchFilters; // the filters with exactly this chip removed
}

function _rangeLabel(sel: RangeSel, unit: string | null | undefined): string {
  const lo = sel.min == null ? "" : formatMagnitude(sel.min, unit);
  const hi = sel.max == null ? "" : formatMagnitude(sel.max, unit);
  if (lo && hi) return `${lo} – ${hi}`;
  if (lo) return `≥ ${lo}`;
  if (hi) return `≤ ${hi}`;
  return "";
}

/** The chips to render in the sub-bar, in a stable order: category first, then options, then
 * ranges. Each chip carries the `remove` filters so a click never has to re-derive removal. */
export function activeChips(
  filters: SearchFilters,
  facets: ParametricFacet[],
): FilterChip[] {
  const unitOf = (key: string) => facets.find((f) => f.key === key)?.unit ?? null;
  const chips: FilterChip[] = [];
  if (filters.category) {
    chips.push({
      id: "category",
      keyLabel: "Category",
      value: filters.category,
      remove: { ...filters, category: null },
    });
  }
  for (const [key, values] of Object.entries(filters.options)) {
    for (const value of values) {
      chips.push({
        id: `opt:${key}:${value}`,
        keyLabel: key,
        value: prettifyValue(value),
        remove: removeOption(filters, key, value),
      });
    }
  }
  for (const [key, sel] of Object.entries(filters.ranges)) {
    if (sel.min == null && sel.max == null) continue;
    chips.push({
      id: `range:${key}`,
      keyLabel: key,
      value: _rangeLabel(sel, unitOf(key)),
      remove: clearRange(filters, key),
    });
  }
  return chips;
}

export function hasAnyFilter(filters: SearchFilters): boolean {
  return (
    filters.category != null ||
    filters.inStock ||
    Object.values(filters.options).some((v) => v.length > 0) ||
    Object.values(filters.ranges).some((r) => r.min != null || r.max != null)
  );
}

// --- immutable mutators -----------------------------------------------------

export function isOptionOn(filters: SearchFilters, key: string, value: string): boolean {
  return (filters.options[key] ?? []).includes(value);
}

export function toggleOption(
  filters: SearchFilters,
  key: string,
  value: string,
): SearchFilters {
  const current = filters.options[key] ?? [];
  const next = current.includes(value)
    ? current.filter((v) => v !== value)
    : [...current, value];
  return _withOptions(filters, key, next);
}

export function removeOption(
  filters: SearchFilters,
  key: string,
  value: string,
): SearchFilters {
  return _withOptions(filters, key, (filters.options[key] ?? []).filter((v) => v !== value));
}

function _withOptions(filters: SearchFilters, key: string, values: string[]): SearchFilters {
  const options = { ...filters.options };
  if (values.length) options[key] = values;
  else delete options[key];
  return { ...filters, options };
}

export function setRange(filters: SearchFilters, key: string, sel: RangeSel): SearchFilters {
  const ranges = { ...filters.ranges };
  if (sel.min == null && sel.max == null) delete ranges[key];
  else ranges[key] = sel;
  return { ...filters, ranges };
}

export function clearRange(filters: SearchFilters, key: string): SearchFilters {
  if (!(key in filters.ranges)) return filters;
  const ranges = { ...filters.ranges };
  delete ranges[key];
  return { ...filters, ranges };
}

export function clearAll(filters: SearchFilters): SearchFilters {
  // keep the category (it scopes the schema); drop every parametric selection + the stock toggle
  return { category: filters.category, options: {}, ranges: {}, inStock: false };
}

// --- schema-driven results columns ------------------------------------------

export interface SpecColumn {
  key: string;
  label: string;
  numeric: boolean; // range facet -> right-aligned mono column
  unit: string | null;
}

// A parameter's worth as a table column comes from its spec GROUP, so the columns are the
// meaningful electrical/physical parameters (Resistance, Tolerance, Power, Package) - never the
// commercial/logistics noise (pack quantity, tariff, weight) that a raw count would surface. The
// grouping is itself registry-driven, so a genuinely new *parameter* still ranks; provenance
// junk stays out.
const _GROUP_SCORE: Record<SpecGroupName, number> = {
  Electrical: 400,
  Physical: 250,
  "Ratings & Compliance": 120,
  Other: -1,
};

// Provenance / logistics / commercial keys that are never useful table columns even when the
// data carries them for many parts. Matched as substrings of the normalized key so label
// variants ("US Tariff %", "Factory Pack Quantity", "Unit Weight") are all caught.
const _COMMERCIAL = /tariff|packaging|pack quantity|standard pack|country of origin|lead time|unit weight|gross weight|base product|catalog|reach|export control|eccn|\bhts\b|number of parts/;

function _columnScore(facet: ParametricFacet, category: string): number {
  if (_COMMERCIAL.test(normalizeSpecKey(facet.key))) return -Infinity;
  const r = resolveSpec(facet.key, category);
  const base = _GROUP_SCORE[r.group];
  if (base < 0) {
    // unregistered / "Other": a genuinely new parameter can still fill a tail slot (a numeric
    // one leads a categorical one), but always below every registered electrical/physical param.
    return facet.kind === "range" ? 10 : 3;
  }
  return base - (r.order ?? 100) / 100;
}

/** Choose the results table's spec columns from the facets the data produced, ranked by how much
 * of a real PARAMETER each is (its spec group) so the table reads like a datasheet, not a
 * shipping manifest. A single-valued option (the same for every part) is dropped - a useless
 * column. Ties break on how many parts carry the parameter. Capped so the table stays legible;
 * everything else lives in the facet rail and the part detail. */
export function deriveColumns(
  facets: ParametricFacet[],
  category: string | null,
  maxCols = 5,
): SpecColumn[] {
  const cat = category ?? "";
  const scored = facets
    .filter((f) => f.kind === "range" || (f.options?.length ?? 0) > 1)
    .map((f) => ({ f, score: _columnScore(f, cat) }))
    .filter((s) => s.score > -Infinity)
    .sort((a, b) => (b.score - a.score) || (b.f.count - a.f.count));
  return scored.slice(0, maxCols).map(({ f }) => {
    const r = resolveSpec(f.key, cat);
    return {
      key: f.key,
      label: r.label,
      numeric: f.kind === "range",
      unit: f.unit ?? r.unit ?? null,
    };
  });
}

// Where a facet sits in the rail: the same parameter-importance signal the columns use, but
// kept finite for every facet so the whole rail just reorders - electrical ranges at the top,
// commercial / provenance dimensions sunk to the bottom, never hidden.
function _railScore(facet: ParametricFacet, category: string): number {
  if (_COMMERCIAL.test(normalizeSpecKey(facet.key))) return -1;
  const groupRank: Record<SpecGroupName, number> = {
    Electrical: 4,
    Physical: 3,
    "Ratings & Compliance": 2,
    Other: 1,
  };
  const r = resolveSpec(facet.key, category);
  const kindBoost = facet.kind === "range" ? 0.5 : 0; // a quantitative dimension is a prime filter
  // order is only a FINE within-group tiebreak (the fallback order is huge, so keep it << 1)
  return groupRank[r.group] + kindBoost - (r.order ?? 100) / 1e6;
}

/** The facets in rail order: the meaningful parameters first (electrical ranges lead), provenance
 * last. Every facet is kept - a parametric search rail is comprehensive - only reordered, so the
 * first thing the eye lands on is Resistance, not Country of Origin. Stable within a tier. */
export function orderFacetsForRail(
  facets: ParametricFacet[],
  category: string | null,
): ParametricFacet[] {
  const cat = category ?? "";
  return facets
    .map((f, i) => ({ f, i, s: _railScore(f, cat) }))
    .sort((a, b) => b.s - a.s || a.i - b.i)
    .map((x) => x.f);
}

/** A row's display value for a spec column: the part's own value, prettified (Ohms -> Ω, unit
 * spacing), or an em dash when the part does not carry that spec. */
export function cellValue(
  specs: Record<string, string | number | boolean>,
  key: string,
): string {
  const raw = specs[key];
  if (raw == null || raw === "") return "—";
  return prettifyValue(String(raw));
}
