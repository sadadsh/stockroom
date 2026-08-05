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
  // `category`, `specs` and `display_name` are DERIVED values (stockroom.model.derived), which
  // is exactly why a title may be recomputed from them: dropping the block and re-deriving must
  // reproduce the record, so nothing read here is authored truth.
  const { category, specs, display_name: displayName } = part.derived;
  const rule = _TITLE_INDEX.get(normalizeSpecKey(category));
  const noun = rule ? rule.noun : singularize(category);
  const specMap = normalizedSpecMap(specs);

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
  const first = firstDefiningValue(specs);
  if (first) {
    const lead = prettifyValue(first);
    return noun ? `${lead} ${noun}` : lead;
  }
  // Nothing usable in the specs: the raw name is the honest last resort, then the category,
  // so the masthead is never empty.
  return displayName.trim() || category.trim();
}
