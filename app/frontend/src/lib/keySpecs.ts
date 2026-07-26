/**
 * KEY SPECIFICATIONS: the handful of parameters a person actually looks for when they open a part,
 * chosen per CATEGORY and overridable by pinning.
 *
 * Owner 2026-07-26: "the important specifications should be where the eda handoff is, formatted like
 * the specifications, but the most important details people care about when looking at this
 * component, similar to what the eda looks for." Offered three ways to decide "important", they
 * chose CURATED per category PLUS user pinning - not auto-ranking by source agreement.
 *
 * Why curated wins here, recorded so it is not re-litigated: an auto-ranked block surfaces whatever
 * the vendors happened to emphasise, and vendors emphasise what is easy to scrape. A TVS diode's
 * clamping voltage is the number that decides the part, and it appears in exactly one source.
 *
 * This is the same shape as the EDA registry the owner liked: a category's key set is DATA, so
 * supporting a new category is an entry here rather than an edit in a component.
 */
import type { SpecGroup, SpecRow } from "./specSchema";

/** How many rows the block shows. It sits where the handoff band sat, so it has that much room. */
export const KEY_SPEC_LIMIT = 8;

/**
 * Per-category key specs, in the order they should READ (not the order the sheet stores them).
 *
 * Matched as lowercase SUBSTRINGS against the spec's real key, because records name the same
 * parameter at different lengths: the registry says "peak pulse current" and a real record says
 * "Peak Pulse Current (10/1000us)". Substring matching is what makes one entry cover both.
 */
const KEY_SPECS_BY_CATEGORY: Record<string, readonly string[]> = {
  diodes: [
    "working voltage",
    "breakdown voltage",
    "clamping voltage",
    "peak pulse current",
    "capacitance",
    "channels",
    "package",
  ],
  resistors: ["resistance", "tolerance", "power", "voltage rating", "temperature coefficient", "package"],
  capacitors: ["capacitance", "tolerance", "voltage rating", "dielectric", "esr", "package"],
  inductors: ["inductance", "current rating", "dc resistance", "saturation", "tolerance", "package"],
  transistors: [
    "drain source voltage",
    "continuous drain current",
    "on resistance",
    "gate threshold",
    "power dissipation",
    "package",
  ],
  ics: ["supply voltage", "interface", "channels", "operating temperature", "package"],
  modules: ["supply voltage", "interface", "frequency", "output power", "package"],
  sensors: ["supply voltage", "interface", "range", "accuracy", "resolution", "package"],
  crystals_oscillators: ["frequency", "frequency tolerance", "load capacitance", "esr", "package"],
  connectors: ["positions", "pitch", "current rating", "voltage rating", "mounting", "package"],
  switches: ["current rating", "voltage rating", "actuator", "circuit", "mounting", "package"],
  electromechanical: ["coil voltage", "contact current", "contact configuration", "mounting", "package"],
};

/**
 * The set for a part whose category has no curated list.
 *
 * Deliberately NOT empty: this block occupies the slot the EDA handoff used to hold, and rendering
 * an empty card there would be a worse regression than showing approximately-right rows. These are
 * the parameters that matter for almost any component.
 */
const KEY_SPECS_FALLBACK: readonly string[] = [
  "voltage",
  "current",
  "power",
  "frequency",
  "tolerance",
  "operating temperature",
  "package",
  "mounting",
];

/** Category keys arrive as display names ("Crystals & Oscillators"); normalise to the registry's. */
function categoryKey(category: string): string {
  return (category || "")
    .trim()
    .toLowerCase()
    .replace(/[\s&]+/g, "_")
    .replace(/_+/g, "_")
    .replace(/^_|_$/g, "");
}

function termsFor(category: string): readonly string[] {
  const key = categoryKey(category);
  return KEY_SPECS_BY_CATEGORY[key] ?? KEY_SPECS_FALLBACK;
}

/** Pinned spec keys, per category display name. */
export type PinnedSpecs = Record<string, readonly string[]>;

/**
 * The rows for the Key Specifications block: the user's pins first, then the category's curated set
 * in registry order, capped at `KEY_SPEC_LIMIT`.
 *
 * A curated term the part does not carry is skipped silently - a hole would be worse than a shorter
 * block. Family rows are included like any other; they carry their own member count as their value.
 */
export function keySpecRows(
  groups: readonly SpecGroup[],
  category: string,
  pinned: PinnedSpecs,
): SpecRow[] {
  const all = groups.flatMap((g) => g.rows);
  if (all.length === 0) return [];

  const out: SpecRow[] = [];
  const taken = new Set<string>();
  const take = (r: SpecRow | undefined) => {
    if (!r || taken.has(r.key) || out.length >= KEY_SPEC_LIMIT) return;
    taken.add(r.key);
    out.push(r);
  };

  // PINS FIRST, and by exact key: a pin is a specific row the user chose, so it must not be
  // re-matched loosely onto a different spec that merely shares a word with it.
  for (const key of pinned[category] ?? []) {
    take(all.find((r) => r.key === key));
  }

  // then the curated set, matched as a substring in both directions so the registry term can be
  // shorter than the record's key (the usual case) or the record's key shorter than the term.
  for (const term of termsFor(category)) {
    if (out.length >= KEY_SPEC_LIMIT) break;
    take(
      all.find((r) => {
        // BOTH the raw key and the human label. Records key a spec the way the DISTRIBUTOR writes it
        // ("Voltage - Breakdown (Min)"), while these terms are written the way a person says it
        // ("breakdown voltage") - so matching the key alone promoted 2 of 7 curated specs on a real
        // diode and left the rest sitting below, which is what the render showed.
        const candidates = [r.key.toLowerCase(), (r.label ?? "").toLowerCase()];
        return candidates.some((c) => c.length > 0 && (c.includes(term) || term.includes(c)));
      }),
    );
  }
  return out;
}

/**
 * The Specifications groups with the promoted rows REMOVED - "promote, not copy" (owner 2026-07-26).
 *
 * A spec lifted into Key Specifications leaves the list below rather than appearing twice in the same
 * column. Researched before implementing rather than argued from taste: duplication in a data display
 * "adds extra items without any value", and NN/G frame progressive disclosure as SEQUENCING what
 * matters most rather than hiding it - so moving a row up the column loses nothing, while repeating it
 * costs a reader two lookups to discover the two entries are the same fact.
 *
 * Two things this has to get right, both of which were the argument AGAINST promoting:
 *   - the group's count must not lie. It cannot: every count is derived from `rows.length`, so
 *     filtering the rows updates the count by construction.
 *   - a group emptied by promotion is DROPPED, not rendered as a titled disclosure holding nothing.
 *
 * Pure and non-mutating: the panel re-renders on every pin, and mutating the caller's groups would
 * compound the removal until the list emptied itself.
 */
export function withoutPromoted(
  groups: readonly SpecGroup[],
  promoted: ReadonlySet<string>,
): SpecGroup[] {
  if (promoted.size === 0) return groups.map((g) => ({ ...g }));
  return groups
    .map((g) => ({ ...g, rows: g.rows.filter((r) => !promoted.has(r.key)) }))
    .filter((g) => g.rows.length > 0);
}

/**
 * Pin or unpin one spec for one category, returning a NEW map.
 *
 * Immutable because this is persisted through `writePref`, which compares against the value it
 * already holds to avoid a pointless write - mutating in place would defeat that comparison and
 * PATCH the settings endpoint on every render.
 */
export function togglePinned(
  pinned: PinnedSpecs,
  category: string,
  specKey: string,
): PinnedSpecs {
  const current = pinned[category] ?? [];
  const next = current.includes(specKey)
    ? current.filter((k) => k !== specKey)
    : [...current, specKey];
  return { ...pinned, [category]: next };
}

/** Whether a spec is pinned for this category - the star's filled state. */
export function isPinned(pinned: PinnedSpecs, category: string, specKey: string): boolean {
  return (pinned[category] ?? []).includes(specKey);
}

/**
 * The keys Top Specifications actually renders - a user pin OR a registry-curated match.
 *
 * Derived from `keySpecRows` rather than recomputed, so the star and the block can never disagree:
 * the cap, the ordering and the substring matching are all applied once, in one place. Recomputing
 * "is this curated" independently would drift the moment either rule changed, and the symptom would
 * be a star that lies rather than an obvious break.
 */
export function effectiveKeySpecKeys(
  groups: readonly SpecGroup[],
  category: string,
  pinned: PinnedSpecs,
): Set<string> {
  return new Set(keySpecRows(groups, category, pinned).map((r) => r.key));
}

/**
 * Whether a row sits in Top Specifications because the REGISTRY curated it, not because the user
 * pinned it (owner, 2026-07-26: "the pin system lets you pin a spec that is ALREADY in Top
 * Specifications").
 *
 * Such a row's star reads as filled but must not offer to pin it AGAIN: `togglePinned` would add a
 * redundant user pin, which changes nothing visible and silently spends one of the capped slots on
 * a row that already had one. It is deliberately not made UNpinnable either - removing a curated
 * row is not something the owner asked for, and inventing an exclusion list to allow it would be a
 * broader change than the instruction.
 */
export function isCuratedOnly(
  effective: ReadonlySet<string>,
  pinned: PinnedSpecs,
  category: string,
  specKey: string,
): boolean {
  return effective.has(specKey) && !(pinned[category] ?? []).includes(specKey);
}
