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

// The procurement group: origin, the page's own tariff rate, export classification, order
// quantities. Real vendor data, and not a physical parameter, so the parametric search ranks it
// last rather than mixing it in with the electrical dimensions.
const TRADE_GROUP: SpecGroupName = "Trade & Compliance";

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
  /**
   * Stable semantic identity. Omit when the normalized display label is already the right id.
   * This is what preferences and cross-source reconciliation bind to; the distributor's raw key
   * remains on the row for editing, provenance and round-tripping.
   */
  id?: string;
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
  { token: "features", group: "Device", order: 24 },
  { token: "feature", group: "Device", order: 24 },

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

  // --- Device ---------------------------------------------------------------
  { match: "composition", group: "Device", label: "Composition", order: 20 },
  { match: "operating mode", group: "Device", label: "Operating Mode", order: 21 },

  // --- Ratings & Compliance -------------------------------------------------
  { match: "operating temperature", group: "Ratings & Compliance", label: "Operating Temperature", order: 10 },
  { match: "temperature range", group: "Ratings & Compliance", label: "Temperature Range", order: 10 },
  { match: "operating temperature range", group: "Ratings & Compliance", label: "Operating Temperature", order: 10 },
  { match: "rohs", group: "Ratings & Compliance", label: "RoHS", order: 20 },
  { match: "reach", group: "Ratings & Compliance", label: "REACH", order: 21 },
  { match: "moisture sensitivity level", group: "Ratings & Compliance", label: "Moisture Sensitivity Level", order: 40 },
  { match: "msl", group: "Ratings & Compliance", label: "Moisture Sensitivity Level", order: 40 },
  { match: "qualification", group: "Ratings & Compliance", label: "Qualification", order: 50 },
  { match: "maximum operating temperature", group: "Ratings & Compliance", label: "Maximum Operating Temperature", order: 11 },
  { match: "minimum operating temperature", group: "Ratings & Compliance", label: "Minimum Operating Temperature", order: 12 },
  { match: "flammability rating", group: "Ratings & Compliance", label: "Flammability Rating", order: 45 },
  { match: "ul rating", group: "Ratings & Compliance", label: "UL Rating", order: 46 },
  { match: "aec q200", group: "Ratings & Compliance", label: "AEC-Q200", order: 51 },

  // --- Trade & Compliance (procurement, not physics; see TRADE_GROUP) ----------
  { match: "eccn", group: TRADE_GROUP, label: "ECCN", order: 10 },
  { match: "lifecycle", group: TRADE_GROUP, label: "Lifecycle", order: 12 },
  { match: "lifecycle status", group: TRADE_GROUP, label: "Lifecycle", order: 12 },
  { match: "part status", group: TRADE_GROUP, label: "Part Status", order: 13 },
  { match: "lead time", group: TRADE_GROUP, label: "Lead Time", order: 14 },
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
  { id: "factory pack quantity", match: "factory pack qty", group: TRADE_GROUP, label: "Factory Pack Quantity", order: 45 },
  { match: "standard pack quantity", group: TRADE_GROUP, label: "Standard Pack Quantity", order: 46 },
  { id: "standard pack quantity", match: "standard pack qty", group: TRADE_GROUP, label: "Standard Pack Quantity", order: 46 },
  { match: "unit weight kg", group: TRADE_GROUP, label: "Unit Weight", unit: "kg", order: 50 },
];

// A resolved spec: raw key + where the registry (or the fallback) places it.
interface ResolvedSpec {
  key: string;
  label: string;
  group: SpecGroupName;
  unit?: string;
  order: number;
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
    const scope = entry.category ? normalizeSpecKey(entry.category) : "*";
    index.set(`${scope}::${entry.match}`, entry);
  }
  return index;
})();

// Resolve where a raw key lands: a category-scoped entry wins, then a global entry, then
// the fallback (Other, at the fallback order) so an unknown key is placed, never dropped.
export function resolveSpec(rawKey: string, category: string): ResolvedSpec {
  const norm = normalizeSpecKey(rawKey);
  const categoryId = normalizeSpecKey(category);
  const scoped = categoryId
    ? _REGISTRY_INDEX.get(`${categoryId}::${norm}`)
    : undefined;
  const entry = scoped ?? _REGISTRY_INDEX.get(`*::${norm}`);
  if (entry) {
    const label = entry.label ?? rawKey;
    return {
      key: rawKey,
      label,
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
        const label = cleanSpecLabel(rawKey);
        return {
              key: rawKey,
          label,
          group: p.group,
          order: p.order,
        };
      }
    }
  }
  const label = cleanSpecLabel(rawKey);
  return {
    key: rawKey,
    label,
    group: FALLBACK_GROUP,
    order: FALLBACK_ORDER,
  };
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

// Spec keys whose value is inherently a ± quantity (a tolerance, a temperature coefficient):
// the north-star reads "±1%", not "1 %". Keyed normalized so any casing matches.
const SIGNED_KEYS = new Set(["tolerance", "temperature coefficient"].map(normalizeSpecKey));

// Prefix a ± when the resolved key is a signed quantity and the value does not already carry a
// sign (a value like "±1%" or "-40" passes through unchanged). Presentation only.
export function applySign(rawKey: string, value: string): string {
  if (!SIGNED_KEYS.has(normalizeSpecKey(rawKey))) return value;
  return /^[±+−-]/.test(value.trim()) ? value : `±${value}`;
}

/**
 * Tidy a distributor's own parameter name into something a person reads naturally.
 *
 * Owner, 2026-07-25, on being offered a wider Sourcing column: "why not clean up the names". Right
 * answer - the column was not too narrow, the labels were needlessly long and awkwardly ordered.
 *
 * Distributors lead with the QUANTITY and hang the qualifier off a dash, because that is how their
 * parametric search sorts: "Voltage - Clamping (Max) @ Ipp". Nobody says that out loud. Swapping
 * around the dash gives the phrase English word order - "Clamping Voltage (Max) @ Ipp" - at the
 * same length, so it costs no width and reads at a glance.
 *
 * Deliberately NOT a rename table. A table only fixes the names someone has already seen, and every
 * distributor invents new ones; this is the shape they all share. A specific name that still reads
 * badly gets an exact `SPEC_REGISTRY` row with its own `label`, which wins over this.
 *
 * Conservative by design: it only reorders around a single dash, only when both sides are real
 * words, and it never touches a name without one. Anything it does not recognise is returned
 * untouched, because a distributor's own wording is accurate even when it is ugly, and a wrong
 * "cleanup" loses meaning that a long label merely obscures.
 */
export function cleanSpecLabel(raw: string): string {
  const text = (raw ?? "").trim();
  if (!text) return "";
  // Hold back any trailing qualifier - "(Max)", "(10/1000us)", "@ Ipp" - so the swap happens on the
  // NAME and the condition stays where it belongs, at the end.
  const m = /^(.*?)(\s*(?:\((?:[^()]*)\)|@\s*\S+)(?:\s*(?:\([^()]*\)|@\s*\S+))*)\s*$/.exec(text);
  const base = (m ? m[1] : text).trim();
  const suffix = (m ? m[2] : "").trim();

  const parts = base.split(/\s+-\s+/);
  if (parts.length !== 2) return text;
  const [quantity, qualifier] = parts.map((p) => p.trim());
  // both halves must be words; a numeric or symbol half is not a phrase to reorder
  if (!/^[A-Za-z][A-Za-z /]*$/.test(quantity) || !/^[A-Za-z][A-Za-z /]*$/.test(qualifier)) {
    return text;
  }
  return [`${qualifier} ${quantity}`, suffix].filter(Boolean).join(" ");
}

