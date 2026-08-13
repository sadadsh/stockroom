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

const LOADERS: readonly { label: string; load: () => Promise<IconifyCollection> }[] = [
  { label: "Lucide", load: () => import("@iconify-json/lucide/icons.json").then((value) => value.default as IconifyCollection) },
  { label: "Tabler", load: () => import("@iconify-json/tabler/icons.json").then((value) => value.default as IconifyCollection) },
  { label: "Phosphor", load: () => import("@iconify-json/ph/icons.json").then((value) => value.default as IconifyCollection) },
  { label: "Material Symbols", load: () => import("@iconify-json/material-symbols/icons.json").then((value) => value.default as IconifyCollection) },
  { label: "Simple Icons", load: () => import("@iconify-json/simple-icons/icons.json").then((value) => value.default as IconifyCollection) },
];

let cachedExtra: readonly IconCatalogEntry[] | undefined;
let loading: Promise<readonly IconCatalogEntry[]> | undefined;

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

export function loadOfflineIconCollections(): Promise<readonly IconCatalogEntry[]> {
  if (cachedExtra) return Promise.resolve(cachedExtra);
  loading ??= Promise.all(LOADERS.map(async ({ label, load }) => iconifyEntries(label, await load())))
    .then((groups) => {
      cachedExtra = groups.flat();
      return cachedExtra;
    });
  return loading;
}

export function offlineIconFamilies(): readonly string[] {
  return ["Font Awesome solid", "Font Awesome brands", "Font Awesome regular", ...OFFLINE_ICON_LIBRARY_NAMES];
}

export function searchOfflineIcons(query: string, family: string, extra: readonly IconCatalogEntry[]): readonly IconCatalogEntry[] {
  const terms = query.toLowerCase().trim().split(/\s+/).filter(Boolean);
  return [...fontAwesomeCatalogEntries(), ...extra].filter((entry) => {
    if (family && entry.family !== family) return false;
    if (terms.length === 0) return true;
    const haystack = [entry.label, entry.family, ...entry.terms].join(" ").toLowerCase();
    return terms.every((term) => haystack.includes(term));
  });
}
