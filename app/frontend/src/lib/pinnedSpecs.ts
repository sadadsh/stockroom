/**
 * The pinned-spec preference: which specifications a person wants at the top, per category.
 *
 * This is the half of the old `keySpecs` module that survived, and the only half that was ever a
 * frontend concern. WHICH specifications matter for a kind of component is a category schema
 * question, and the dossier answers it - `keySpecifications` arrives already chosen and already
 * promoted out of the groups. A curated table of per-category selectors here was a second answer
 * to that question, matched against distributor spellings by token containment, and it disagreed
 * with the backend's the moment either changed.
 *
 * What remains is a USER PREFERENCE, and preferences belong to the client. A pin now binds to the
 * dossier's canonical `key` (`supply_voltage`), which is the same identity for every part of every
 * category from every source - so a pin set on a part whose distributor said `Voltage - Supply`
 * still applies to one whose distributor said `Supply Voltage`, without any spelling rules here.
 *
 * The preference belongs in the machine config like the theme and the rail (localStorage alone
 * resets on every launch, because the host binds an ephemeral port and the origin moves with it -
 * see uiPrefs.ts). Unlike the scalar preferences this one is JSON, so a stored mirror can be
 * malformed, and `normalizePinnedSpecs` is what makes that degrade to "nothing pinned" rather than
 * throw during the first render of the surface that reads it.
 */

/** Canonical specification keys, per canonical category id. */
export type PinnedSpecs = Record<string, readonly string[]>;

/**
 * The category's own id.
 *
 * A category arrives as a display name (`Crystals & Oscillators`) and as a schema key
 * (`crystals_oscillators`); both fold to the same thing here, so a preference set while reading one
 * spelling is not lost when the other arrives.
 */
export function categoryKey(category: string): string {
  return (category || "")
    .trim()
    .toLowerCase()
    .replace(/[\s&]+/g, "_")
    .replace(/_+/g, "_")
    .replace(/^_|_$/g, "");
}

/**
 * A stored preference, reduced to what it can honestly mean.
 *
 * Anything that is not a string key under a named category is dropped rather than repaired: this
 * reads a file a person could have edited, and guessing at a malformed entry is how a preference
 * silently starts applying to the wrong category.
 */
export function normalizePinnedSpecs(pinned: PinnedSpecs | null | undefined): PinnedSpecs {
  const out: Record<string, string[]> = {};
  if (!pinned || typeof pinned !== "object" || Array.isArray(pinned)) return out;
  for (const [rawCategory, rawPins] of Object.entries(pinned)) {
    if (!Array.isArray(rawPins)) continue;
    const category = categoryKey(rawCategory);
    if (!category) continue;
    const keys = out[category] ?? [];
    const seen = new Set(keys);
    for (const rawPin of rawPins) {
      if (typeof rawPin !== "string") continue;
      const key = rawPin.trim();
      if (!key || seen.has(key)) continue;
      seen.add(key);
      keys.push(key);
    }
    if (keys.length) out[category] = keys;
  }
  return out;
}

function pinsFor(pinned: PinnedSpecs, category: string): readonly string[] {
  return normalizePinnedSpecs(pinned)[categoryKey(category)] ?? [];
}

/**
 * Pin or unpin one specification for one category, returning a NEW map.
 *
 * Immutable because this is persisted through `writePref`, which compares against the value it
 * already holds to avoid a pointless write - mutating in place would defeat that comparison and
 * PATCH the settings endpoint on every render.
 */
export function togglePinned(
  pinned: PinnedSpecs,
  category: string,
  specificationKey: string,
): PinnedSpecs {
  const normalized = normalizePinnedSpecs(pinned);
  const categoryId = categoryKey(category);
  const key = specificationKey.trim();
  if (!categoryId || !key) return normalized;
  const current = normalized[categoryId] ?? [];
  const next = current.includes(key)
    ? current.filter((entry) => entry !== key)
    : [...current, key];
  if (next.length === 0) {
    const { [categoryId]: _removed, ...rest } = normalized;
    return rest;
  }
  return { ...normalized, [categoryId]: next };
}

/** Whether a specification is pinned for this category. */
export function isPinned(
  pinned: PinnedSpecs,
  category: string,
  specificationKey: string,
): boolean {
  return pinsFor(pinned, category).includes(specificationKey.trim());
}

