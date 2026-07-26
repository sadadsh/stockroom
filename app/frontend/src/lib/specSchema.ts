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
  | "Device"
  | "Ratings & Compliance"
  | "Trade & Compliance"
  | "Other";

export const SPEC_GROUP_ORDER: readonly SpecGroupName[] = [
  "Electrical",
  "Physical",
  // WHAT THE PART IS AND DOES: its type, topology, channel count, what it is for. These are
  // real, first-class characteristics that are neither electrical quantities nor dimensions,
  // and with no home of their own every one of them fell into "Other".
  "Device",
  "Ratings & Compliance",
  "Trade & Compliance",
  "Other",
];

// The procurement group, rendered by the SOURCING tab rather than the Specs sheet.
//
// These keys are real vendor data the owner asked to stop discarding (origin, the page's own
// tariff rate, export classification, order quantities) but they are NOT physical parameters, and
// `derive.isReferenceOnlySpecKey` deliberately keeps them off the spec sheet so it does not read
// as a distributor page dump. Both rules hold at once by giving them a group of their own: a buyer
// looks for an import classification next to the prices, not next to the propagation delay.
export const TRADE_GROUP: SpecGroupName = "Trade & Compliance";

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

/**
 * TOKEN PATTERNS - the second classification tier, and the one that stops "Other" being a dumping
 * ground (owner, 2026-07-25: "the field classification needs to be modular and not just describe
 * things as other").
 *
 * WHY a second tier rather than more exact rows. `SPEC_REGISTRY` matches a key VERBATIM, and real
 * distributor parameter names are long and specific: "Voltage - Breakdown (Min)",
 * "Current - Peak Pulse (10/1000us)", "Voltage - Clamping (Max) @ Ipp". Every one of those is
 * plainly electrical and every one missed an exact `voltage` / `current` row, so on a real ESD
 * diode 13 of 18 specs rendered under "Other". Enumerating the exact strings cannot work: each
 * distributor spells them differently and new ones arrive with every part.
 *
 * A pattern matches on the key's TOKENS, so the family is recognised however the rest of the name
 * is decorated. This stays DATA - a new family is a row here, never a code change - which is the
 * modular half of the request.
 *
 * `leading: true` requires the token to START the key, which is how a parameter names its quantity
 * ("Voltage - Breakdown"). Without it a token matches anywhere, for families that trail instead
 * ("Operating Temperature"). Order matters: the first match wins, so put the specific first.
 */
export interface SpecPattern {
  /** A normalized token, matched against the key's own tokens. */
  token: string;
  /** Require the token to be the key's FIRST token. */
  leading?: boolean;
  group: SpecGroupName;
  order: number;
}

export const SPEC_PATTERNS: SpecPattern[] = [
  // --- 1. STRONG DEVICE WORDS, first. These name a FEATURE and never a quantity, so they must be
  // read before the quantity words below - "Power Line Protection" leads with "power" but is a
  // capability, not a measurement, and classifying it as Electrical was measurably wrong.
  { token: "protection", group: "Device", order: 21 },
  { token: "applications", group: "Device", order: 12 },
  { token: "application", group: "Device", order: 12 },
  { token: "topology", group: "Device", order: 14 },
  { token: "configuration", group: "Device", order: 15 },
  { token: "channels", group: "Device", order: 16 },
  { token: "circuits", group: "Device", order: 17 },
  { token: "elements", group: "Device", order: 18 },
  { token: "polarity", group: "Device", order: 19 },
  { token: "technology", group: "Device", order: 20 },
  { token: "interface", group: "Device", order: 22 },
  { token: "protocol", group: "Device", order: 23 },
  { token: "function", group: "Device", order: 13 },

  // --- 2. Physical form, before electrical: "Supplier Device Package" and "Package / Case" are
  // dimensions of the body whatever else their name carries.
  { token: "package", group: "Physical", order: 12 },
  { token: "case", group: "Physical", order: 13 },
  { token: "size", group: "Physical", order: 14 },
  { token: "dimension", group: "Physical", order: 14 },
  { token: "height", group: "Physical", order: 15 },
  { token: "width", group: "Physical", order: 15 },
  { token: "length", group: "Physical", order: 15 },
  { token: "thickness", group: "Physical", order: 15 },
  { token: "weight", group: "Physical", order: 16 },
  { token: "pitch", group: "Physical", order: 17 },
  { token: "mounting", group: "Physical", order: 18 },
  { token: "termination", group: "Physical", order: 19 },

  // --- 3. Compliance families, which trail as often as they lead ("Operating Temperature").
  { token: "temperature", group: "Ratings & Compliance", order: 15 },
  { token: "humidity", group: "Ratings & Compliance", order: 16 },
  { token: "moisture", group: "Ratings & Compliance", order: 17 },
  { token: "rohs", group: "Ratings & Compliance", order: 18 },
  { token: "reach", group: "Ratings & Compliance", order: 19 },
  { token: "qualification", group: "Ratings & Compliance", order: 20 },
  { token: "grade", group: "Ratings & Compliance", order: 21 },
  { token: "esd", group: "Ratings & Compliance", order: 22 },
  { token: "flammability", group: "Ratings & Compliance", order: 23 },
  { token: "certification", group: "Ratings & Compliance", order: 24 },

  // --- 4. Electrical quantities, matched ANYWHERE in the key rather than only in front. A
  // distributor decorates the quantity from both sides ("Voltage - Clamping (Max) @ Ipp",
  // "Output Voltage (Max)"), so requiring the leading position missed most real names.
  { token: "voltage", group: "Electrical", order: 35 },
  { token: "current", group: "Electrical", order: 45 },
  { token: "power", group: "Electrical", order: 55 },
  { token: "resistance", group: "Electrical", order: 75 },
  { token: "capacitance", group: "Electrical", order: 15 },
  { token: "inductance", group: "Electrical", order: 15 },
  { token: "impedance", group: "Electrical", order: 76 },
  { token: "frequency", group: "Electrical", order: 65 },
  { token: "energy", group: "Electrical", order: 57 },
  { token: "charge", group: "Electrical", order: 58 },
  { token: "gain", group: "Electrical", order: 66 },
  { token: "bandwidth", group: "Electrical", order: 67 },
  { token: "noise", group: "Electrical", order: 68 },
  { token: "propagation", group: "Electrical", order: 69 },
  { token: "efficiency", group: "Electrical", order: 59 },
  { token: "esr", group: "Electrical", order: 70 },

  // --- 5. WEAK device words, last. "Type" and "Output" appear inside plenty of electrical and
  // physical names, so they may only claim a key nothing above recognised.
  { token: "type", group: "Device", order: 10 },
  { token: "output", group: "Device", order: 24 },
  { token: "input", group: "Device", order: 25 },
];


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
  { match: "output current", group: "Electrical", label: "Output Current", order: 41 },
  { match: "input current", group: "Electrical", label: "Input Current", order: 42 },
  { match: "output voltage", group: "Electrical", label: "Output Voltage", order: 33 },
  { match: "input voltage", group: "Electrical", label: "Input Voltage", order: 34 },
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

  // --- Trade & Compliance (procurement, not physics; see TRADE_GROUP) ----------
  { match: "eccn", group: TRADE_GROUP, label: "ECCN", order: 10 },
  { match: "country of origin", group: TRADE_GROUP, label: "Country of Origin", order: 20 },
  { match: "assembly country of origin", group: TRADE_GROUP, label: "Assembly Country", order: 21 },
  { match: "country of diffusion", group: TRADE_GROUP, label: "Country of Diffusion", order: 22 },
  // unit "%" so a bare 0.0 reads as "0%": the value is the page's OWN measured rate, and 0.0 means
  // "checked, no tariff" - printed as a bare "0" it is indistinguishable from an empty cell.
  // label WITHOUT the percent sign: the unit supplies it, and "US Tariff %  0%" printed it twice.
  { match: "us tariff", group: TRADE_GROUP, label: "US Tariff", unit: "%", order: 30 },
  { match: "minimum order quantity", group: TRADE_GROUP, label: "Minimum Order Quantity", order: 40 },
  { match: "order multiple", group: TRADE_GROUP, label: "Order Multiple", order: 41 },
  { match: "maximum order quantity", group: TRADE_GROUP, label: "Maximum Order Quantity", order: 42 },
  { match: "standard package", group: TRADE_GROUP, label: "Standard Package", order: 43 },
  { match: "packaging", group: TRADE_GROUP, label: "Packaging", order: 44 },
  { match: "factory pack quantity", group: TRADE_GROUP, label: "Factory Pack Quantity", order: 45 },
  { match: "standard pack quantity", group: TRADE_GROUP, label: "Standard Pack Quantity", order: 46 },
  { match: "unit weight kg", group: TRADE_GROUP, label: "Unit Weight", unit: "kg", order: 50 },
];

// A FAMILY of spec keys that are the same fact stated once per jurisdiction, variant or
// channel, and therefore belong in ONE row with a member each rather than N rows of their own.
//
// This needs a pattern rather than N registry rows because the key space is open: Mouser emits
// six fixed HTS keys, but LCSC emits `HTS Code (<country name>)` for whatever countries a part
// has codes for, so a hand-listed set would silently miss the seventh country and go back to
// shouting a wall of near-identical rows over the specs that matter.
//
// A family is NOT a disagreement. Two sources contradicting each other is a different thing
// entirely and lives in the part's `alternates`; this is one source stating many related facts.
export interface SpecFamily {
  // The family's own display label - the collapsed row's name.
  family: string;
  // Matched against the NORMALIZED key (see normalizeSpecKey). Capture group 1, when present,
  // names the member ("us", "eu taric", "vietnam"); a match with no capture is the unqualified
  // form of the same fact and becomes a member with no name of its own.
  match: RegExp;
  group: SpecGroupName;
  order: number;
}

export const SPEC_FAMILIES: readonly SpecFamily[] = [
  {
    family: "HTS Code",
    // "HTS Code (US)", "HTS Code (EU TARIC)", LCSC's "HTS Code (Vietnam)", or a bare "HTS Code".
    match: /^hts code(?:\s+(.+))?$/,
    group: TRADE_GROUP,
    // just below ECCN: both are export classification, and ECCN is the single-value one.
    order: 11,
  },
];

// The member's own label, recovered from the raw key so it reads as the source wrote it
// ("US", "EU TARIC", "Vietnam") rather than as the normalized lowercase form. Falls back to the
// family name for the unqualified key, which has no member name of its own.
function memberLabel(rawKey: string, family: SpecFamily, captured: string | undefined): string {
  if (!captured) return family.family;
  // find the captured run inside the raw key, case-insensitively, so the source's own casing and
  // punctuation survive: normalizeSpecKey stripped the parentheses to match, and reading the
  // label back off the raw key avoids having to reconstruct them.
  const stripped = rawKey.trim().replace(/[()]/g, " ").replace(/\s+/g, " ").trim();
  const at = stripped.toLowerCase().lastIndexOf(captured.toLowerCase());
  return at >= 0 ? stripped.slice(at, at + captured.length).trim() : captured;
}

/** The family a raw spec key belongs to, with the member's label, or null when it is an
 * ordinary standalone spec. */
export function resolveFamily(
  rawKey: string,
): { family: SpecFamily; member: string } | null {
  const norm = normalizeSpecKey(rawKey);
  for (const family of SPEC_FAMILIES) {
    const m = family.match.exec(norm);
    if (m) return { family, member: memberLabel(rawKey, family, m[1]) };
  }
  return null;
}

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
  // The value as STORED, before prettifying / unit-splitting / the ± prefix. A consumer comparing
  // this row against another source's answer must compare stored-to-stored: "1%" renders as "±1%",
  // so comparing the presented string made the value already in force look like a different
  // answer, and the panel offered to "use" what it was already using.
  raw: string;
  unit?: string;
  // Present only on a FAMILY row (see SPEC_FAMILIES): the individual per-jurisdiction values,
  // sorted by member label. The family row itself carries no value of its own - `value` is the
  // member count, so the collapsed row still says how much is behind it.
  members?: SpecRow[];
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
  // No verbatim entry: fall to the TOKEN PATTERNS before giving up on the key. This is what keeps
  // a specific distributor parameter name ("Voltage - Breakdown (Min)") with its family instead of
  // in "Other". The label stays the raw key - the pattern decides WHERE it goes, never what it is
  // called, because the distributor's own wording is the accurate one.
  const tokens = norm.split(" ").filter(Boolean);
  if (tokens.length) {
    const first = tokens[0];
    const present = new Set(tokens);
    for (const p of SPEC_PATTERNS) {
      const hit = p.leading ? first === p.token : present.has(p.token);
      if (hit) {
        return { key: rawKey, label: rawKey, group: p.group, order: p.order };
      }
    }
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
  // One accumulator per family encountered, so N per-jurisdiction keys become one row.
  const families = new Map<string, { family: SpecFamily; rows: SpecRow[]; seq: number }>();
  let seq = 0;
  for (const [key, value] of Object.entries(specs)) {
    if (SPEC_HIDDEN_KEYS.has(key)) continue;
    if (!isPresentableValue(value)) continue;
    const inFamily = resolveFamily(key);
    if (inFamily) {
      const bucket = families.get(inFamily.family.family) ?? {
        family: inFamily.family, rows: [], seq: seq++,
      };
      bucket.rows.push({
        key,
        label: inFamily.member,
        value: prettifyValue(coerceValue(value)),
        raw: coerceValue(value),
      });
      families.set(inFamily.family.family, bucket);
      continue;
    }
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
      raw: coerceValue(value),
      unit: dispUnit,
    };
    const list = buckets.get(resolved.group) ?? [];
    list.push({ row, order: resolved.order, seq: seq++ });
    buckets.set(resolved.group, list);
  }

  // Fold each family into a single row. Members sort by their own label so the list reads the
  // same on every part regardless of the order the distributor's payload happened to arrive in.
  for (const { family, rows, seq: familySeq } of families.values()) {
    rows.sort((a, b) => a.label.localeCompare(b.label));
    const list = buckets.get(family.group) ?? [];
    list.push({
      row: {
        key: family.family,
        label: family.family,
        raw: "",  // a family row is a count of its members, not a value any source offered
        // The collapsed row states HOW MANY facts are behind it rather than picking one
        // jurisdiction to stand for the rest - which region is "the" region depends on who is
        // reading, and the panel must not decide that for them.
        value: String(rows.length),
        members: rows,
      },
      order: family.order,
      seq: familySeq,
    });
    buckets.set(family.group, list);
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
