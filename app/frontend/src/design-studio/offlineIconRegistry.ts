import type { IconCatalogEntry } from "../lib/iconRegistry";
import { fontAwesomeEntries } from "./fontAwesomeRegistry";

type IconifyIcon = { body: string; width?: number; height?: number; hidden?: boolean };
type IconifyCollection = {
  prefix: string;
  width?: number;
  height?: number;
  icons: Record<string, IconifyIcon>;
};

export const OFFLINE_ICON_LIBRARY_NAMES = [
  "Lucide",
  "Tabler",
  "Phosphor",
  "Material Symbols",
  "Simple Icons",
] as const;

export const OFFLINE_ICON_FAMILIES = ["Font Awesome", ...OFFLINE_ICON_LIBRARY_NAMES] as const;
export type OfflineIconFamily = typeof OFFLINE_ICON_FAMILIES[number];
export const DEFAULT_OFFLINE_ICON_FAMILY: OfflineIconFamily = "Font Awesome";

const LOADERS: readonly { label: typeof OFFLINE_ICON_LIBRARY_NAMES[number]; load: () => Promise<IconifyCollection> }[] = [
  { label: "Lucide", load: () => import("@iconify-json/lucide/icons.json").then((value) => value.default as IconifyCollection) },
  { label: "Tabler", load: () => import("@iconify-json/tabler/icons.json").then((value) => value.default as IconifyCollection) },
  { label: "Phosphor", load: () => import("@iconify-json/ph/icons.json").then((value) => value.default as IconifyCollection) },
  { label: "Material Symbols", load: () => import("@iconify-json/material-symbols/icons.json").then((value) => value.default as IconifyCollection) },
  { label: "Simple Icons", load: () => import("@iconify-json/simple-icons/icons.json").then((value) => value.default as IconifyCollection) },
];

const cachedFamilies = new Map<OfflineIconFamily, readonly IconCatalogEntry[]>();
const loadingFamilies = new Map<OfflineIconFamily, Promise<readonly IconCatalogEntry[]>>();

function iconifyEntries(label: string, collection: IconifyCollection): IconCatalogEntry[] {
  return Object.entries(collection.icons).flatMap(([name, icon]) => {
    if (icon.hidden) return [];
    const width = icon.width ?? collection.width ?? 24;
    const height = icon.height ?? collection.height ?? 24;
    return [{
      id: `${collection.prefix}.${name}`,
      label: name,
      family: label,
      terms: [name, ...name.split("-"), label.toLowerCase()],
      body: icon.body,
      viewBox: `0 0 ${width} ${height}`,
    }];
  });
}

export function fontAwesomeCatalogEntries(): readonly IconCatalogEntry[] {
  return fontAwesomeEntries().map((entry) => ({ ...entry, family: `Font Awesome ${entry.family}` }));
}

export function loadOfflineIconCollections(family: OfflineIconFamily): Promise<readonly IconCatalogEntry[]> {
  const cached = cachedFamilies.get(family);
  if (cached) return Promise.resolve(cached);
  const active = loadingFamilies.get(family);
  if (active) return active;

  const loader = family === "Font Awesome"
    ? Promise.resolve().then(fontAwesomeCatalogEntries)
    : (() => {
      const selected = LOADERS.find((candidate) => candidate.label === family);
      if (!selected) return Promise.reject(new Error(`Unknown offline icon family: ${family}`));
      return selected.load().then((collection) => iconifyEntries(selected.label, collection));
    })();
  const loading = loader.then((entries) => {
    cachedFamilies.set(family, entries);
    loadingFamilies.delete(family);
    return entries;
  }, (error: unknown) => {
    loadingFamilies.delete(family);
    throw error;
  });
  loadingFamilies.set(family, loading);
  return loading;
}

export function offlineIconFamilies(): readonly OfflineIconFamily[] {
  return OFFLINE_ICON_FAMILIES;
}

export function searchOfflineIcons(query: string, family: OfflineIconFamily, entries: readonly IconCatalogEntry[]): readonly IconCatalogEntry[] {
  const terms = query.toLowerCase().trim().split(/\s+/).filter(Boolean);
  return entries.filter((entry) => {
    const inFamily = family === "Font Awesome"
      ? entry.family.startsWith("Font Awesome ")
      : entry.family === family;
    if (!inFamily) return false;
    if (terms.length === 0) return true;
    const haystack = [entry.label, entry.family, ...entry.terms].join(" ").toLowerCase();
    return terms.every((term) => haystack.includes(term));
  });
}
