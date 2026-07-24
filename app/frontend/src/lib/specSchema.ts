/**
 * The single, data-driven module that turns a part's free-form spec bag into a
 * presentation. It is the modular guarantee: a future part carrying a spec key we
 * have never seen still renders sanely (it lands in a fallback group, never dropped),
 * and refining a key's group / label / unit / order is a one-line registry edit with
 * no code change.
 *
 * DetailPanel consumes `groupSpecs` to lay out its Specifications block; the future
 * parametric search consumes `deriveFacets` for its filter rail. The backend builds
 * the server-side aggregation separately, so this stays pure and independently tested.
 */

// Spec keys that are NOT parametric specs: the asset references (shown in the Part
// Canvas) and the pinout (rendered as its own table). Everything else in specs is a
// real spec. Kept here (moved out of DetailPanel) so every consumer filters identically.
export const SPEC_HIDDEN_KEYS = new Set([
  "Symbol",
  "Footprint",
  "3D Model",
  "product_url",
  "pinout",
  // the pulled product photo URL: rendered as a real image (ProductPhoto), never a URL row
  "Image",
]);

// Spec values that mean "the distributor did not fill this" - dropped so an
// empty-in-disguise spec never takes a row (compared lowercased + trimmed).
export const EMPTY_SPEC_VALUES = new Set([
  "not available",
  "none",
  "n/a",
  "-",
  "unknown",
  "not applicable",
]);

// The presentation groups, mirroring the north-star spec sheet. "Other" is the fallback
// bucket every UNKNOWN key routes to, so a never-seen spec always has a sane home. The
// array order IS the render order of the groups.
export type SpecGroupName =
  | "Electrical"
  | "Physical"
  | "Ratings & Compliance"
  | "Other";

export const SPEC_GROUP_ORDER: readonly SpecGroupName[] = [
  "Electrical",
  "Physical",
  "Ratings & Compliance",
  "Other",
];

// The fallback group + a large default order so unknown keys sort AFTER every known
// key while keeping their own insertion order among themselves (a stable sort).
const FALLBACK_GROUP: SpecGroupName = "Other";
const FALLBACK_ORDER = 100000;

// One registry entry. `match` is a NORMALIZED key (see normalizeSpecKey); an entry
// refines an incoming key's group / label / unit / order. `category` optionally scopes
// an entry to one category (a category-scoped entry wins over a global one for that
// category); omit it and the entry applies everywhere. Adding a key needs no code
// change - a registry row only refines where it lands.
export interface SpecRegistryEntry {
  match: string;
  group: SpecGroupName;
  // The display label; defaults to the spec's own (raw) key when omitted.
  label?: string;
  // A canonical unit, used only as a fallback when the value is a bare number carrying
  // no unit of its own (the value's own inline unit always wins - never doubled up).
  unit?: string;
  // Within-group sort order (lower first). Only relative order inside a group matters.
  order: number;
  category?: string;
}

// The ordered, extensible registry. Grouped by concern for readability; `order` (not
// array position) drives within-group sorting, so inserting a row anywhere is safe.
export const SPEC_REGISTRY: SpecRegistryEntry[] = [
  // --- Electrical -----------------------------------------------------------
  { match: "resistance", group: "Electrical", label: "Resistance", order: 10 },
  { match: "capacitance", group: "Electrical", label: "Capacitance", order: 10 },
  { match: "inductance", group: "Electrical", label: "Inductance", order: 10 },
  { match: "tolerance", group: "Electrical", label: "Tolerance", order: 20 },
  { match: "voltage", group: "Electrical", label: "Voltage", order: 30 },
  { match: "voltage rating", group: "Electrical", label: "Voltage Rating", order: 31 },
  { match: "voltage rating dc", group: "Electrical", label: "Voltage Rating", order: 31 },
  { match: "current", group: "Electrical", label: "Current", order: 40 },
  { match: "current rating", group: "Electrical", label: "Current Rating", order: 41 },
  { match: "power", group: "Electrical", label: "Power", unit: "W", order: 50 },
  { match: "power rating", group: "Electrical", label: "Power Rating", unit: "W", order: 50 },
  { match: "frequency", group: "Electrical", label: "Frequency", order: 60 },
  { match: "esr", group: "Electrical", label: "ESR", order: 70 },
  { match: "impedance", group: "Electrical", label: "Impedance", order: 71 },
  { match: "dielectric", group: "Electrical", label: "Dielectric", order: 80 },
  { match: "temperature coefficient", group: "Electrical", label: "Temperature Coefficient", order: 81 },
  { match: "voltage rated", group: "Electrical", label: "Voltage Rating", order: 31 },
  { match: "max voltage", group: "Electrical", label: "Max Voltage", order: 32 },
  { match: "maximum voltage", group: "Electrical", label: "Max Voltage", order: 32 },
  { match: "ripple current", group: "Electrical", label: "Ripple Current", order: 42 },
  { match: "leakage current", group: "Electrical", label: "Leakage Current", order: 43 },
  { match: "saturation current", group: "Electrical", label: "Saturation Current", order: 44 },
  { match: "q factor", group: "Electrical", label: "Q Factor", order: 62 },
  { match: "insulation resistance", group: "Electrical", label: "Insulation Resistance", order: 72 },
  { match: "contact resistance", group: "Electrical", label: "Contact Resistance", order: 73 },
  { match: "dc resistance", group: "Electrical", label: "DC Resistance", order: 74 },
  { match: "dcr", group: "Electrical", label: "DC Resistance", order: 74 },

  // --- Physical -------------------------------------------------------------
  { match: "package", group: "Physical", label: "Package", order: 10 },
  { match: "case", group: "Physical", label: "Case", order: 11 },
  { match: "case code", group: "Physical", label: "Case Code", order: 11 },
  { match: "mounting type", group: "Physical", label: "Mounting Type", order: 20 },
  { match: "number of pins", group: "Physical", label: "Number Of Pins", order: 30 },
  { match: "number of positions", group: "Physical", label: "Number Of Positions", order: 31 },
  { match: "pitch", group: "Physical", label: "Pitch", order: 40 },
  { match: "size", group: "Physical", label: "Size", order: 50 },
  { match: "height", group: "Physical", label: "Height", order: 51 },
  { match: "length", group: "Physical", label: "Length", order: 52 },
  { match: "width", group: "Physical", label: "Width", order: 53 },
  { match: "weight", group: "Physical", label: "Weight", order: 60 },
  { match: "mounting", group: "Physical", label: "Mounting", order: 20 },
  { match: "mounting style", group: "Physical", label: "Mounting Style", order: 21 },
  { match: "mounting angle", group: "Physical", label: "Mounting Angle", order: 22 },
  { match: "orientation", group: "Physical", label: "Orientation", order: 23 },
  { match: "gender", group: "Physical", label: "Gender", order: 24 },
  { match: "number of contacts", group: "Physical", label: "Number Of Contacts", order: 32 },
  { match: "number of ports", group: "Physical", label: "Number Of Ports", order: 33 },
  { match: "number of rows", group: "Physical", label: "Number Of Rows", order: 34 },
  { match: "terminations", group: "Physical", label: "Terminations", order: 35 },
  { match: "termination", group: "Physical", label: "Termination", order: 35 },
  { match: "termination style", group: "Physical", label: "Termination Style", order: 35 },
  { match: "diameter", group: "Physical", label: "Diameter", order: 54 },
  { match: "thickness", group: "Physical", label: "Thickness", order: 55 },
  { match: "material", group: "Physical", label: "Material", order: 61 },
  { match: "body material", group: "Physical", label: "Body Material", order: 61 },
  { match: "housing material", group: "Physical", label: "Housing Material", order: 61 },
  { match: "contact material", group: "Physical", label: "Contact Material", order: 62 },
  { match: "contact plating", group: "Physical", label: "Contact Plating", order: 63 },
  { match: "plating", group: "Physical", label: "Plating", order: 64 },
  { match: "color", group: "Physical", label: "Color", order: 70 },
  { match: "colour", group: "Physical", label: "Color", order: 70 },

  // --- Ratings & Compliance -------------------------------------------------
  { match: "operating temperature", group: "Ratings & Compliance", label: "Operating Temperature", order: 10 },
  { match: "temperature range", group: "Ratings & Compliance", label: "Temperature Range", order: 10 },
  { match: "operating temperature range", group: "Ratings & Compliance", label: "Operating Temperature", order: 10 },
  { match: "rohs", group: "Ratings & Compliance", label: "RoHS", order: 20 },
  { match: "reach", group: "Ratings & Compliance", label: "REACH", order: 21 },
  { match: "lifecycle", group: "Ratings & Compliance", label: "Lifecycle", order: 30 },
  { match: "lead time", group: "Ratings & Compliance", label: "Lead Time", order: 31 },
  { match: "moisture sensitivity level", group: "Ratings & Compliance", label: "Moisture Sensitivity Level", order: 40 },
  { match: "msl", group: "Ratings & Compliance", label: "Moisture Sensitivity Level", order: 40 },
  { match: "qualification", group: "Ratings & Compliance", label: "Qualification", order: 50 },
  { match: "maximum operating temperature", group: "Ratings & Compliance", label: "Maximum Operating Temperature", order: 11 },
  { match: "minimum operating temperature", group: "Ratings & Compliance", label: "Minimum Operating Temperature", order: 12 },
  { match: "part status", group: "Ratings & Compliance", label: "Part Status", order: 31 },
  { match: "flammability rating", group: "Ratings & Compliance", label: "Flammability Rating", order: 45 },
  { match: "ul rating", group: "Ratings & Compliance", label: "UL Rating", order: 46 },
  { match: "aec q200", group: "Ratings & Compliance", label: "AEC-Q200", order: 51 },
  { match: "eccn", group: "Ratings & Compliance", label: "ECCN", order: 60 },
];

// A resolved spec: raw key + where the registry (or the fallback) places it.
interface ResolvedSpec {
  key: string;
  label: string;
  group: SpecGroupName;
  unit?: string;
  order: number;
}

// One presented spec row: the raw key, the display label, the coerced value, and the
// unit split off it (for tabular alignment) when there was one.
export interface SpecRow {
  key: string;
  label: string;
  value: string;
  unit?: string;
}

export interface SpecGroup {
  title: SpecGroupName;
  rows: SpecRow[];
}

// One facet definition for the parametric-search rail. `kind` is "range" for a numeric
// spec (min/max, plus a shared unit when consistent) or "checkbox" for a categorical
// one (distinct values + counts). `group`/`order` mirror the same registry so a facet
// rail groups exactly like the detail spec sheet.
export interface FacetValue {
  value: string;
  count: number;
}

export interface FacetDef {
  key: string;
  label: string;
  group: SpecGroupName;
  order: number;
  kind: "range" | "checkbox";
  // present on a checkbox facet: distinct values, count desc then value asc
  values?: FacetValue[];
  // present on a range facet
  min?: number;
  max?: number;
  unit?: string;
}

// Fold casing + punctuation to a canonical key so "Voltage Rating", "voltage_rating",
// and "Voltage / Rating" all resolve to the same registry entry.
export function normalizeSpecKey(key: string): string {
  return key
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, " ")
    .trim();
}

// Build the (category, normalized-key) lookup once. A category-scoped entry is stored
// under `${category}::${match}`; a global one under `*::${match}`.
const _REGISTRY_INDEX: Map<string, SpecRegistryEntry> = (() => {
  const index = new Map<string, SpecRegistryEntry>();
  for (const entry of SPEC_REGISTRY) {
    const scope = entry.category ?? "*";
    index.set(`${scope}::${entry.match}`, entry);
  }
  return index;
})();

// Resolve where a raw key lands: a category-scoped entry wins, then a global entry, then
// the fallback (Other, at the fallback order) so an unknown key is placed, never dropped.
export function resolveSpec(rawKey: string, category: string): ResolvedSpec {
  const norm = normalizeSpecKey(rawKey);
  const scoped = category
    ? _REGISTRY_INDEX.get(`${category}::${norm}`)
    : undefined;
  const entry = scoped ?? _REGISTRY_INDEX.get(`*::${norm}`);
  if (entry) {
    return {
      key: rawKey,
      label: entry.label ?? rawKey,
      group: entry.group,
      unit: entry.unit,
      order: entry.order,
    };
  }
  return { key: rawKey, label: rawKey, group: FALLBACK_GROUP, order: FALLBACK_ORDER };
}

// Leading "number [unit]" matcher: a number (optional sign, thousands, decimal,
// exponent) then a unit made only of NON-digit characters through end-of-string. The
// no-digit tail is what keeps a range ("-40°C ~ 85°C") from splitting - a later digit
// means no match, so the value passes through whole.
const _NUM_UNIT_RE = /^([+-]?\d[\d,]*(?:\.\d+)?(?:[eE][+-]?\d+)?)\s*([^\d]*)$/;

// Split a value into its numeric lead + unit for tabular alignment. Returns the value
// unchanged (no unit) when it is not a clean "number [unit]" (a range, prose, or a bare
// code like "0603" keeps its whole string).
export function splitValueUnit(raw: string): { value: string; unit?: string } {
  const text = raw.trim();
  const m = _NUM_UNIT_RE.exec(text);
  if (!m) return { value: text };
  const num = m[1];
  const unit = (m[2] ?? "").trim();
  return unit ? { value: num, unit } : { value: num };
}

// Presentation-only unit prettifying. The stored specs keep the scraped spelling
// ("1.1 kOhms", "0.1 uF", "100 PPM"); the north-star shows the real symbols. Only SAFE,
// unambiguous substitutions (never invents or drops data): Ohm(s) -> Ω, a micro u-prefix on
// a known unit -> µ, PPM -> ppm. A bare code ("0603") or prose is returned unchanged.
export function prettifyValue(text: string): string {
  return text
    .replace(/ohm(s)?/gi, "Ω")
    .replace(/([\d\s(])u([FHAVWSs])\b/g, "$1µ$2")
    .replace(/\bPPM\b/g, "ppm")
    // a LEADING unary sign is always negative/positive, never a range dash: tighten the stray
    // space and normalize an ASCII hyphen to a true minus ("- 55" -> "−55", "+ 155" -> "+155")
    .replace(/^([+\-−])\s*(?=[\d.,])/, (_m, s) => (s === "+" ? "+" : "−"))
    // an interior unary +/− with a stray space ("~ + 85" -> "~ +85"); NOT a hyphen (a range dash)
    .replace(/([+−])\s+(?=\d)/g, "$1")
    .replace(/\/C\b/g, "/°C") // "ppm/C" -> "ppm/°C"
    // a bare Celsius "C" after "<number> " (a required space avoids mangling a part code like
    // "0603C" or an MPN's internal "1C1"): "155 C" -> "155 °C"
    .replace(/(\d)\s+C\b/g, "$1 °C");
}

// True when a value already carries its own unit / symbol (so the registry unit must NOT be
// appended on top of it - the source of the "200 mW (1/5 W) W" double-unit).
function hasInlineUnit(value: string): boolean {
  return /[a-zµΩ°%]/i.test(value);
}

// Spec keys whose value is inherently a ± quantity (a tolerance, a temperature coefficient):
// the north-star reads "±1%", not "1 %". Keyed normalized so any casing matches.
const SIGNED_KEYS = new Set(["tolerance", "temperature coefficient"].map(normalizeSpecKey));

// Prefix a ± when the resolved key is a signed quantity and the value does not already carry a
// sign (a value like "±1%" or "-40" passes through unchanged). Presentation only.
export function applySign(rawKey: string, value: string): string {
  if (!SIGNED_KEYS.has(normalizeSpecKey(rawKey))) return value;
  return /^[±+−-]/.test(value.trim()) ? value : `±${value}`;
}

// Numeric parse for faceting: the numeric lead (commas stripped) as a finite number,
// plus its unit, or null when the value is not numeric.
function parseNumericSpec(raw: string): { num: number; unit: string } | null {
  const m = _NUM_UNIT_RE.exec(raw.trim());
  if (!m) return null;
  const num = Number(m[1].replace(/,/g, ""));
  if (!Number.isFinite(num)) return null;
  return { num, unit: (m[2] ?? "").trim() };
}

// True when a spec value is real, presentable data (not null, not an object like the
// pinout list, not blank, not an empty-in-disguise marker).
function isPresentableValue(value: unknown): boolean {
  if (value == null || typeof value === "object") return false;
  const text = String(value).trim();
  if (text === "") return false;
  return !EMPTY_SPEC_VALUES.has(text.toLowerCase());
}

// Coerce a real spec entry to a display string (callers already gate on
// isPresentableValue, so this only ever sees scalars).
function coerceValue(value: unknown): string {
  return String(value).trim();
}

/**
 * Turn a part's spec bag into ordered, grouped presentation rows. Hidden keys and
 * empty-in-disguise values are dropped; each survivor is routed by the registry (an
 * unknown key lands in "Other", never dropped), its value split into value + unit,
 * groups ordered by SPEC_GROUP_ORDER, and rows ordered by the registry `order`
 * (unknown keys keep their insertion order, a stable sort). Empty groups are omitted.
 */
export function groupSpecs(
  category: string,
  specs: Record<string, unknown>,
): SpecGroup[] {
  // Bucket resolved rows by group, preserving insertion order within each bucket.
  const buckets = new Map<SpecGroupName, Array<{ row: SpecRow; order: number; seq: number }>>();
  let seq = 0;
  for (const [key, value] of Object.entries(specs)) {
    if (SPEC_HIDDEN_KEYS.has(key)) continue;
    if (!isPresentableValue(value)) continue;
    const resolved = resolveSpec(key, category);
    const split = splitValueUnit(coerceValue(value));
    const prettyUnit = split.unit ? prettifyValue(split.unit) : undefined;
    let dispValue = prettifyValue(split.value);
    // the value's own inline unit wins; the registry unit is only a fallback for a bare number
    // that carried none - never appended onto a value that already has a unit.
    let dispUnit = prettyUnit ?? (hasInlineUnit(split.value) ? undefined : resolved.unit);
    // a percent reads tight ("±1%", not "1 %"), so fold it into the value with no space
    if (dispUnit === "%") {
      dispValue += "%";
      dispUnit = undefined;
    }
    dispValue = applySign(key, dispValue);
    const row: SpecRow = {
      key: resolved.key,
      label: resolved.label,
      value: dispValue,
      unit: dispUnit,
    };
    const list = buckets.get(resolved.group) ?? [];
    list.push({ row, order: resolved.order, seq: seq++ });
    buckets.set(resolved.group, list);
  }

  const groups: SpecGroup[] = [];
  for (const title of SPEC_GROUP_ORDER) {
    const list = buckets.get(title);
    if (!list || list.length === 0) continue;
    list.sort((a, b) => a.order - b.order || a.seq - b.seq);
    groups.push({ title, rows: list.map((e) => e.row) });
  }
  return groups;
}

/**
 * Aggregate a set of parts' spec keys into facet definitions for the parametric-search
 * rail. For each spec key seen (after the same hidden/empty filtering), classify it as
 * a numeric range (every value parses to a finite number AND their units are consistent)
 * or a checkbox list (distinct string values + counts). Facets are grouped and ordered
 * by the same registry, so the rail mirrors the detail spec sheet. This is the FRONTEND
 * shape only; the backend builds its own server aggregation separately.
 */
export function deriveFacets(
  parts: Array<{ category: string; specs: Record<string, unknown> }>,
): FacetDef[] {
  // Aggregate values per RAW key, remembering the category of the first part that
  // carried it (for deterministic registry resolution across a mixed set).
  const acc = new Map<string, { key: string; category: string; values: string[]; seq: number }>();
  let seq = 0;
  for (const part of parts) {
    for (const [key, value] of Object.entries(part.specs)) {
      if (SPEC_HIDDEN_KEYS.has(key)) continue;
      if (!isPresentableValue(value)) continue;
      const bucket = acc.get(key);
      if (bucket) {
        bucket.values.push(coerceValue(value));
      } else {
        acc.set(key, { key, category: part.category, values: [coerceValue(value)], seq: seq++ });
      }
    }
  }

  const facets: Array<FacetDef & { _seq: number }> = [];
  for (const { key, category, values, seq: bucketSeq } of acc.values()) {
    const resolved = resolveSpec(key, category);
    facets.push({ ...classifyFacet(values), key, label: resolved.label, group: resolved.group, order: resolved.order, _seq: bucketSeq });
  }

  const groupIndex = (g: SpecGroupName) => SPEC_GROUP_ORDER.indexOf(g);
  facets.sort(
    (a, b) =>
      groupIndex(a.group) - groupIndex(b.group) ||
      a.order - b.order ||
      a._seq - b._seq,
  );
  return facets.map(({ _seq, ...facet }) => facet);
}

// Classify one key's aggregated values: a numeric range when every value parses to a
// finite number with a consistent unit, else a checkbox list.
function classifyFacet(
  values: string[],
): { kind: "range"; min: number; max: number; unit?: string } | { kind: "checkbox"; values: FacetValue[] } {
  const nums: number[] = [];
  const units = new Set<string>();
  let allNumeric = values.length > 0;
  for (const v of values) {
    const parsed = parseNumericSpec(v);
    if (!parsed) {
      allNumeric = false;
      break;
    }
    nums.push(parsed.num);
    if (parsed.unit) units.add(parsed.unit);
  }
  // A numeric spec whose values disagree on units is not a single honest range; treat
  // it as categorical instead of inventing a min/max across scales.
  if (allNumeric && units.size <= 1) {
    return {
      kind: "range",
      min: Math.min(...nums),
      max: Math.max(...nums),
      unit: units.size === 1 ? [...units][0] : undefined,
    };
  }
  const counts = new Map<string, number>();
  for (const v of values) counts.set(v, (counts.get(v) ?? 0) + 1);
  const distinct: FacetValue[] = [...counts.entries()]
    .map(([value, count]) => ({ value, count }))
    .sort((a, b) => b.count - a.count || a.value.localeCompare(b.value));
  return { kind: "checkbox", values: distinct };
}
