import * as regular from "@fortawesome/free-regular-svg-icons";
import * as solid from "@fortawesome/free-solid-svg-icons";
import { sanitizeIconBody } from "../components/iconResolve";
import type { IconCatalogEntry } from "../lib/iconRegistry";

type FontAwesomeDefinition = {
  prefix: "far" | "fas";
  iconName: string;
  icon: readonly [number, number, readonly (string | number)[], string, string | readonly string[]];
};

const FAMILIES: Record<FontAwesomeDefinition["prefix"], string> = {
  far: "regular",
  fas: "solid",
};

let cachedEntries: readonly IconCatalogEntry[] | undefined;

function isDefinition(value: unknown): value is FontAwesomeDefinition {
  if (!value || typeof value !== "object") return false;
  const candidate = value as Partial<FontAwesomeDefinition>;
  return (
    (candidate.prefix === "far" || candidate.prefix === "fas") &&
    typeof candidate.iconName === "string" &&
    Array.isArray(candidate.icon) &&
    typeof candidate.icon[0] === "number" &&
    typeof candidate.icon[1] === "number" &&
    typeof candidate.icon[4] !== "undefined"
  );
}

function searchableTerms(iconName: string, aliases: readonly (string | number)[], family: string) {
  return [...new Set([
    iconName,
    ...iconName.split("-"),
    ...aliases.filter((alias): alias is string => typeof alias === "string"),
    family,
  ].map((term) => term.toLowerCase()))];
}

function normalizeDefinition(definition: FontAwesomeDefinition): IconCatalogEntry | null {
  const [width, height, aliases, , sourceBody] = definition.icon;
  // Free icon packs supply a single path. Skipping an unsupported shape is safer than fabricating
  // a preview, and preserves the catalogue's interface-icon-only boundary.
  if (typeof sourceBody !== "string" || width <= 0 || height <= 0) return null;
  const family = FAMILIES[definition.prefix];
  const label = definition.iconName.toLowerCase();
  const body = sanitizeIconBody(`<path d="${sourceBody}"/>`);
  if (!body) return null;
  return {
    id: `font-awesome.${family}.${label}`,
    label,
    family,
    terms: searchableTerms(label, aliases, family),
    body,
    viewBox: `0 0 ${width} ${height}`,
  };
}

/**
 * Materialise the exact bundled Font Awesome Free libraries on first use. This module is only
 * dynamically imported by IconInspector, so the full catalogue remains out of the main bundle.
 */
export function fontAwesomeEntries(): readonly IconCatalogEntry[] {
  if (cachedEntries) return cachedEntries;
  const entries = new Map<string, IconCatalogEntry>();
  for (const pack of [solid, regular]) {
    for (const value of Object.values(pack)) {
      if (!isDefinition(value)) continue;
      const entry = normalizeDefinition(value);
      if (entry) entries.set(entry.id, entry);
    }
  }
  cachedEntries = [...entries.values()].sort((a, b) => a.label.localeCompare(b.label) || a.family.localeCompare(b.family));
  return cachedEntries;
}

/** Search across the label, alias terms, and style family without introducing a network source. */
export function searchIconCatalog(query: string): readonly IconCatalogEntry[] {
  const terms = query.toLowerCase().trim().split(/\s+/).filter(Boolean);
  const entries = fontAwesomeEntries();
  if (terms.length === 0) return entries;
  return entries.filter((entry) => {
    const haystack = [entry.label, entry.family, ...entry.terms].join(" ");
    return terms.every((term) => haystack.includes(term));
  });
}
