/**
 * The masthead derivers the north-star detail header reads. A part's canonical fields are
 * dense and machine-shaped (display_name "1.10k 1% 0603 Panasonic ERJ-P03F1101V"); the
 * masthead wants a clean human headline and a row of attribute chips instead. Both are
 * data-driven and modular: a new category or a new attribute-worthy spec is a single
 * registry line, never a code change, and an unknown category or a spec-less part still
 * produces a sane result (never blank, never dropped).
 *
 * Pure functions, no React: DetailPanel calls `deriveTitle` for its headline and
 * `deriveAttributes` for its chip rail, so neither is re-derived per component. The
 * spec-bag filtering (hidden keys + empty-in-disguise values) is reused from specSchema
 * so every consumer treats the same values as real.
 */
import type { PartDetail } from "../api/types";
import {
  EMPTY_SPEC_VALUES,
  SPEC_HIDDEN_KEYS,
  applySign,
  normalizeSpecKey,
  prettifyValue,
  resolveSpec,
  type SpecGroupName,
} from "./specSchema";

// --- shared spec-bag helpers -------------------------------------------------

// True when a spec value is real, presentable data (not null, not an object like the
// pinout list, not blank, not an empty-in-disguise marker). Mirrors the private check in
// specSchema, sharing its EMPTY_SPEC_VALUES so the two modules agree on what is real.
function isPresentable(value: unknown): boolean {
  if (value == null || typeof value === "object") return false;
  const text = String(value).trim();
  if (text === "") return false;
  return !EMPTY_SPEC_VALUES.has(text.toLowerCase());
}

// A normalized-key -> trimmed-value lookup over the presentable, non-hidden specs (first
// occurrence of a normalized key wins), so a registry entry resolves a raw spec key no
// matter its casing or punctuation.
function normalizedSpecMap(specs: Record<string, unknown>): Map<string, string> {
  const map = new Map<string, string>();
  for (const [key, value] of Object.entries(specs)) {
    if (SPEC_HIDDEN_KEYS.has(key)) continue;
    if (!isPresentable(value)) continue;
    const norm = normalizeSpecKey(key);
    if (!map.has(norm)) map.set(norm, String(value).trim());
  }
  return map;
}

// Spec keys that describe commerce, provenance, or compliance rather than what the part IS.
// The generic first-spec title fallback must never headline one of these: specs arrive
// alphabetically, so "Assembly Country of Origin: China" lands first and would otherwise
// become the masthead ("China Connector"). Normalized at load so a raw key of any casing
// or punctuation matches. This is a denylist, not an allowlist: a real defining spec the
// list does not name still headlines, so a new junk key is one line here, never a code change.
const TITLE_SKIP_KEYS: Set<string> = new Set(
  [
    "Country of Origin",
    "Assembly Country of Origin",
    "Country of Diffusion",
    "Brand",
    "Manufacturer",
    "Series",
    "Color",
    "Colour",
    "ECCN",
    "HTS Code",
    "Part Status",
    "Lifecycle Status",
    "Lifecycle",
    "RoHS",
    "RoHS Status",
    "REACH",
    "REACH Status",
    "Moisture Sensitivity Level",
    "Factory Pack Quantity",
    "Standard Pack Quantity",
    "Packaging",
    "Flammability Rating",
    "Product Type",
    "Product Category",
    "Subcategory",
    "Contact Material",
    "Contact Plating",
  ].map(normalizeSpecKey),
);

// Spec keys that are commerce / provenance / logistics, not what the part physically IS:
// the manufacturer, brand, series, base product number, country of origin, packaging, and
// pack-quantity rows a distributor page carries. They are dropped from the detail spec sheet
// so the real parametric specs are not buried under a wall of catalog metadata (the record
// already carries the manufacturer and category as first-class fields). Normalized so any
// casing / punctuation matches; a denylist, so a real spec the list does not name still shows.
// This intentionally does NOT reuse TITLE_SKIP_KEYS: that set also holds real physical specs
// (Color, Contact Material, Plating) that must never headline but DO belong in the spec sheet.
const REFERENCE_ONLY_SPEC_KEYS: Set<string> = new Set(
  [
    "Manufacturer",
    "Brand",
    "Vendor",
    "Supplier",
    "Series",
    "Base Product Number",
    "Base Product",
    "Country of Origin",
    "Assembly Country of Origin",
    "Country of Diffusion",
    "Product",
    "Product Type",
    "Product Category",
    "Subcategory",
    "Category",
    "ECCN",
    "HTS Code",
    "HTSUS",
    "Number of Parts",
  ].map(normalizeSpecKey),
);

// A couple of families that vary too much to enumerate (Factory Pack Quantity, Standard Pack
// Quantity, Quantity per Reel; Base Product Number; catalog numbers) are matched by substring.
const _REFERENCE_ONLY_RE = /pack quantity|country of origin|base product|\bcatalog\b|packaging|tariff|\bweight\b/;

/**
 * True when a spec key is catalog metadata (commerce / provenance / logistics) rather than a
 * physical parameter, so the detail spec sheet can drop it. Exported so the one place that
 * decides "is this a real spec to show" stays shared.
 */
export function isReferenceOnlySpecKey(rawKey: string): boolean {
  const nk = normalizeSpecKey(rawKey);
  return REFERENCE_ONLY_SPEC_KEYS.has(nk) || _REFERENCE_ONLY_RE.test(nk);
}

// The first presentable, non-hidden, DEFINING spec value in insertion order (commerce /
// provenance / compliance keys in TITLE_SKIP_KEYS are skipped so a country or brand can
// never headline), or null when the bag holds nothing usable. The generic title fallback
// leans on this.
function firstDefiningValue(specs: Record<string, unknown>): string | null {
  for (const [key, value] of Object.entries(specs)) {
    if (SPEC_HIDDEN_KEYS.has(key)) continue;
    if (TITLE_SKIP_KEYS.has(normalizeSpecKey(key))) continue;
    if (!isPresentable(value)) continue;
    return String(value).trim();
  }
  return null;
}

// --- title -------------------------------------------------------------------

// One title rule: a normalized category, its singular masthead noun, and the ordered spec
// keys whose (clean) values compose the headline. Adding a category is one line here; the
// spec keys are matched normalized, so casing / punctuation of the stored key does not matter.
interface TitleRule {
  match: string;
  noun: string;
  specs: string[];
}

// The extensible title registry. Category nouns are domain terms, kept as-is. The `specs`
// order IS the order the values read in the headline (resistance before tolerance, etc.).
const TITLE_REGISTRY: TitleRule[] = [
  { match: "resistors", noun: "Resistor", specs: ["Resistance", "Tolerance"] },
  { match: "capacitors", noun: "Capacitor", specs: ["Capacitance", "Voltage", "Dielectric"] },
  { match: "inductors", noun: "Inductor", specs: ["Inductance", "Tolerance"] },
  { match: "ferrite beads", noun: "Ferrite Bead", specs: ["Impedance", "Current Rating"] },
  { match: "diodes", noun: "Diode", specs: ["Voltage Rating", "Current"] },
  { match: "leds", noun: "LED", specs: ["Color", "Wavelength"] },
  { match: "connectors", noun: "Connector", specs: ["Number of Positions", "Number of Contacts", "Pitch"] },
  { match: "ics", noun: "IC", specs: [] },
  { match: "integrated circuits", noun: "IC", specs: [] },
];

const _TITLE_INDEX: Map<string, TitleRule> = (() => {
  const index = new Map<string, TitleRule>();
  for (const rule of TITLE_REGISTRY) {
    if (!index.has(rule.match)) index.set(rule.match, rule);
  }
  return index;
})();

/** The primary (defining) spec key for a category, from the title registry's leading spec
 * (Resistors -> "Resistance", Capacitors -> "Capacitance", Ferrite Beads -> "Impedance"), or null
 * for a category with no registered primary spec (ICs). Shared with the search table's adaptive
 * Value column (FIX-05) so a row resolves its own value from the same registry the title uses. */
export function categoryPrimarySpecKey(category: string): string | null {
  const rule = _TITLE_INDEX.get(normalizeSpecKey(category));
  return rule && rule.specs.length > 0 ? rule.specs[0] : null;
}

// A naive singular form of a category, used as the masthead noun for a category the
// registry does not name (Thermistors -> Thermistor, Batteries -> Battery). Category nouns
// are domain terms, so the result is kept as-is even where it carries an unusual letter.
function singularize(category: string): string {
  const trimmed = category.trim();
  const lower = trimmed.toLowerCase();
  if (lower.length > 3 && lower.endsWith("ies")) return trimmed.slice(0, -3) + "y";
  if (/(ses|xes|zes|ches|shes)$/.test(lower)) return trimmed.slice(0, -2);
  if (lower.endsWith("s") && !lower.endsWith("ss")) return trimmed.slice(0, -1);
  return trimmed;
}

/**
 * A clean masthead title for a part, derived from its category + a few key specs
 * (a resistor -> "1.1 kΩ ±1% Resistor", a capacitor -> "0.1 µF 16V X7R Capacitor"),
 * so the dense display_name never has to be shown raw.
 *
 * The chain is fully modular and never returns empty:
 *   1. a registered category pulls its ordered title specs (each present, clean value),
 *      joined with spaces, then its singular noun;
 *   2. any category still missing those specs (or an unregistered one) falls back to the
 *      first meaningful spec value + the category noun (registered, else singularized);
 *   3. a part with nothing usable in its specs falls back to the raw display_name, then
 *      the category, so the header is never blank.
 * A brand-new category needs only a TITLE_REGISTRY line, never a code change.
 */
export function deriveTitle(part: PartDetail): string {
  const rule = _TITLE_INDEX.get(normalizeSpecKey(part.category));
  const noun = rule ? rule.noun : singularize(part.category);
  const specMap = normalizedSpecMap(part.specs);

  const values: string[] = [];
  if (rule) {
    for (const key of rule.specs) {
      const value = specMap.get(normalizeSpecKey(key));
      if (value) values.push(applySign(key, value));
    }
  }
  if (values.length > 0) {
    const lead = prettifyValue(values.join(" "));
    return noun ? `${lead} ${noun}` : lead;
  }

  // No registered title spec resolved (an IC, a diode with no rating specs, ...). The MPN is a
  // recognizable identifier and far better here than the first raw spec, which tends to grab a
  // junk fragment ("LVC" -> "LVC IC", "Single" -> "Single Diode"). Prefer it before that fallback.
  const mpn = part.mpn?.trim();
  if (mpn) return mpn;

  // A registered category with none of its title specs, or any unregistered one, still earns a
  // sane headline from the first meaningful (non-commerce) spec + the noun.
  const first = firstDefiningValue(part.specs);
  if (first) {
    const lead = prettifyValue(first);
    return noun ? `${lead} ${noun}` : lead;
  }
  // Nothing usable in the specs: the raw name is the honest last resort, then the category,
  // so the masthead is never empty.
  return part.display_name.trim() || part.category.trim();
}

// --- attributes --------------------------------------------------------------

// One attribute rule: a normalized spec key + a formatter that turns its value into a chip
// label (or null to skip). Adding an attribute-worthy spec is one line here.
interface AttributeRule {
  match: string;
  format: (value: string) => string | null;
}

// The full ranked set the attributes card may hold; it shows only the first several as a glance
// and reveals the rest behind "Show All", so this is the ceiling, not what is shown at rest.
const MAX_ATTRIBUTES = 14;

// Mounting codes normalized to a spoken label; a value that is already a label passes
// through formatMounting unchanged.
const MOUNTING_LABEL: Record<string, string> = {
  smd: "Surface Mount",
  smt: "Surface Mount",
  "surface mount": "Surface Mount",
  tht: "Through Hole",
  th: "Through Hole",
  "through hole": "Through Hole",
  "thru hole": "Through Hole",
};

function formatMounting(value: string): string {
  return MOUNTING_LABEL[value.trim().toLowerCase()] ?? value.trim();
}

// Values that read as "this attribute does NOT apply", so a compliance / boolean-ish spec
// carrying one produces no chip rather than a misleading positive.
const NEGATIVE = new Set([
  "no",
  "n",
  "none",
  "false",
  "non-compliant",
  "not compliant",
  "not applicable",
]);

function isNegative(value: string): boolean {
  return NEGATIVE.has(value.trim().toLowerCase());
}

// The extensible attribute registry: each line maps a normalized spec key to the chip it
// contributes. The chip labels are Title Case (they are interactive-style tags); domain
// terms (RoHS, AEC-Q200, ...) keep their canonical form.
const ATTRIBUTE_REGISTRY: AttributeRule[] = [
  // physical case / package prints its own code verbatim ("0603", "SOT-23")
  { match: "package", format: (v) => v },
  { match: "case", format: (v) => v },
  { match: "case code", format: (v) => v },
  // mounting normalizes a short code to a spoken label, else keeps the data's own label
  { match: "mounting type", format: formatMounting },
  { match: "mounting", format: formatMounting },
  // element material / composition is itself the attribute ("Thick Film")
  { match: "composition", format: (v) => v },
  // an automotive qualification prints as-is ("AEC-Q200"); a boolean form maps to the label
  { match: "qualification", format: (v) => v },
  { match: "aec q200", format: (v) => (isNegative(v) ? null : "AEC-Q200") },
  // compliance: a positive value becomes the spoken compliance chip
  { match: "rohs", format: (v) => (isNegative(v) ? null : "RoHS Compliant") },
  { match: "reach", format: (v) => (isNegative(v) ? null : "REACH Compliant") },
  // salient boolean-ish features print their canonical label when they apply
  { match: "anti surge", format: (v) => (isNegative(v) ? null : "Anti-Surge") },
  { match: "sulfur resistant", format: (v) => (isNegative(v) ? null : "Sulfur Resistant") },
  { match: "sulphur resistant", format: (v) => (isNegative(v) ? null : "Sulfur Resistant") },
  // more parametric categoricals (Mouser-style): dielectric, connector gender / termination,
  // element / contact material + plating, orientation, mounting style, feature flags.
  { match: "dielectric", format: (v) => v },
  { match: "gender", format: (v) => v },
  { match: "termination", format: (v) => v },
  { match: "termination style", format: (v) => v },
  { match: "termination type", format: (v) => v },
  { match: "orientation", format: (v) => v },
  { match: "mounting style", format: (v) => v },
  { match: "mounting angle", format: (v) => v },
  { match: "contact material", format: (v) => v },
  { match: "contact plating", format: (v) => v },
  { match: "shielding", format: (v) => (isNegative(v) ? null : v) },
  { match: "lifecycle", format: (v) => (/active/i.test(v) ? "Active" : null) },
  { match: "part status", format: (v) => (/active/i.test(v) ? "Active" : null) },
  { match: "features", format: (v) => (v.length <= 24 ? v : null) },
  { match: "automotive", format: (v) => (isNegative(v) ? null : "Automotive") },
];

const _ATTR_INDEX: Map<string, AttributeRule> = (() => {
  const index = new Map<string, AttributeRule>();
  for (const rule of ATTRIBUTE_REGISTRY) {
    if (!index.has(rule.match)) index.set(rule.match, rule);
  }
  return index;
})();

// How a spec's group weighs into "is this what people care about": the electrical parameters
// first, then the physical form, then compliance. Mirrors the search columns' ranking so the
// glance-chips and the parametric columns agree on what matters. "Other" is admitted, but last.
const _ATTR_GROUP_SCORE: Record<SpecGroupName, number> = {
  Electrical: 400,
  Physical: 250,
  "Ratings & Compliance": 120,
  Other: 0,
};

// The part's HEADLINE value already leads the title (deriveTitle), so it is redundant as a chip.
// Exported as the single source of truth for "a passive's primary parametric value", reused by
// the search table's adaptive Value column (FIX-05) so the two never fork the mapping.
export const PRIMARY_VALUE_KEYS = new Set(
  ["resistance", "capacitance", "inductance"].map(normalizeSpecKey),
);

// Provenance / logistics keys are never "what people care about" when choosing a part.
const _COMMERCIAL_ATTR =
  /tariff|packaging|pack quantity|standard pack|country of origin|lead time|weight|base product|catalog|reach|export|eccn|\bhts\b|series|subcategory|moisture|number of parts|^product$/;

// The package/case is a headline physical attribute (footprint choice), so it rides near the
// electrical parameters rather than sinking with the rest of the physical form.
const _PRIME_PHYSICAL = new Set(["package", "case", "case code"].map(normalizeSpecKey));

// Raw physical dimensions read as noise in a summary chip ("0.8 mm", "2 mm") - the package code
// already conveys the footprint - so they sink below every other attribute and surface only when
// a part has nothing better to say.
const _DIMENSION_KEYS = new Set(
  ["height", "length", "width", "thickness", "depth", "diameter", "size", "lead spacing", "lead pitch"].map(
    normalizeSpecKey,
  ),
);

/**
 * The "Attributes" chips: the FEW parameters that actually matter when choosing this part -
 * derived purely from its specs and ranked by importance (electrical first, then form, then
 * compliance), capped small so the card reads as a summary, not a data dump. The headline value
 * (in the title) and commercial/provenance keys are skipped; a registry formatter gives a
 * spoken label where one exists ("SMD" -> "Surface Mount", "RoHS" -> "RoHS Compliant"), else the
 * value is prettified and signed (±1%, 200 mW, ±100 ppm/°C, 0603). Curated tags are NO LONGER
 * folded in - a user's manual attributes live in `tags` and are shown/edited separately.
 */
export function deriveAttributes(part: PartDetail): string[] {
  const scored: { label: string; score: number; order: number }[] = [];
  let seq = 0;
  for (const [key, value] of Object.entries(part.specs)) {
    seq += 1;
    if (SPEC_HIDDEN_KEYS.has(key)) continue;
    if (!isPresentable(value)) continue;
    const nk = normalizeSpecKey(key);
    if (PRIMARY_VALUE_KEYS.has(nk) || _COMMERCIAL_ATTR.test(nk)) continue;
    const text = String(value).trim();
    if (isNegative(text)) continue;
    const rule = _ATTR_INDEX.get(nk);
    const label = rule ? rule.format(text) : prettifyValue(applySign(key, text));
    if (!label) continue;
    if (label.length > 22 || EMPTY_SPEC_VALUES.has(label.toLowerCase())) continue;
    const r = resolveSpec(key, part.category);
    let score = _ATTR_GROUP_SCORE[r.group] - (r.order ?? 100) / 100;
    // a spec curated as attribute-worthy (a registry rule) is at least mid-tier, so a key
    // characteristic the spec schema doesn't rank (composition, dielectric) still surfaces;
    // the package/case leads the physical form.
    if (rule) score = Math.max(score, 150);
    if (_PRIME_PHYSICAL.has(nk)) score += 130;
    if (_DIMENSION_KEYS.has(nk)) score = -100; // a bare dimension is a last-resort chip
    scored.push({ label, score, order: seq });
  }
  // Rank first, THEN dedup by label - so when two keys yield the same chip ("Package" and a
  // "Case Code" both -> "0603"), the higher-scored occurrence is the one that survives.
  const out: string[] = [];
  const seen = new Set<string>();
  for (const c of scored.sort((a, b) => b.score - a.score || a.order - b.order)) {
    const norm = c.label.toLowerCase();
    if (seen.has(norm)) continue;
    seen.add(norm);
    out.push(c.label);
    if (out.length >= MAX_ATTRIBUTES) break;
  }
  return out;
}
