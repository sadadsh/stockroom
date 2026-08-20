import type { CSSProperties } from "react";

import { TABLER_SOURCE_BY_ID, tablerBody } from "./tablerIconSources";
import {
  STOCKROOM_ELECTRICAL_BODY_BY_ID,
  type StockroomElectricalIconId,
} from "./stockroomElectricalIconSources";

export type IconCategory = "primary" | "bespoke" | "art" | "brand";
export type IconFamily =
  | "tabler-outline"
  | "stockroom-electrical"
  | "stockroom-technical"
  | "brand";

export type IconId =
  | keyof typeof TABLER_SOURCE_BY_ID
  | StockroomElectricalIconId
  | "art.symbol"
  | "art.footprint"
  | "art.model"
  | "brand.linkedin"
  | "brand.github";

export interface IconEntry {
  /** Stable semantic persistence key used by application call sites and Design Studio overrides. */
  id: IconId;
  category: IconCategory;
  family: IconFamily;
  /** Pinned upstream asset name for curated Tabler defaults. */
  sourceIcon?: string;
  viewBox: string;
  size?: number | [number, number];
  strokeWidth?: number;
  fill?: string;
  stroke?: string;
  strokeLinecap?: "round" | "butt" | "square";
  strokeLinejoin?: "round" | "miter" | "bevel";
  style?: CSSProperties;
  body: string;
}

export interface IconCatalogEntry {
  id: string;
  label: string;
  family: string;
  terms: readonly string[];
  body: string;
  viewBox: string;
}

/**
 * Historical inventory groups remain stable for Design Studio browsing. They no longer imply a
 * second visual grammar: every entry in both groups uses the shared Tabler Outline frame.
 */
const BESPOKE_IDS = new Set<IconId>([
  "action.search",
  "status.warn",
  "status.info",
  "status.cad-missing",
  "action.upload",
  "action.close",
  "nav.back",
  "action.view",
  "action.external",
  "overlay.chevron",
  "overlay.check",
  "overlay.close",
  "overlay.spark",
  "modal.check",
  "detail.chevron-right",
  "detail.rename",
  "detail.ready-check",
  "detail.select-chevron",
  "detail.filing-folder",
  "detail.datasheet-link",
  "detail.tag-remove",
  "detail.embed-3d",
  "detail.tag-add",
  "finder.filter",
  "dev.reset",
  "dev.close",
]);

function tablerEntry(id: keyof typeof TABLER_SOURCE_BY_ID): IconEntry {
  const source = TABLER_SOURCE_BY_ID[id];
  if (!source) throw new Error(`Missing Tabler source for ${id}`);
  const category: IconCategory =
    id === "brand.wordmark" ? "brand" : BESPOKE_IDS.has(id) ? "bespoke" : "primary";
  return {
    id,
    category,
    family: "tabler-outline",
    sourceIcon: source.sourceIcon,
    viewBox: "0 0 24 24",
    strokeWidth: 2,
    body: tablerBody(source.raw),
  };
}

function typedKeys<T extends object>(value: T): Array<keyof T> {
  return Object.keys(value) as Array<keyof T>;
}

const TABLER_ENTRIES = typedKeys(TABLER_SOURCE_BY_ID).map(tablerEntry);

const STOCKROOM_ELECTRICAL_ENTRIES: IconEntry[] = typedKeys(
  STOCKROOM_ELECTRICAL_BODY_BY_ID,
).map((id) => ({
  id,
  category: "primary",
  family: "stockroom-electrical",
  sourceIcon: `stockroom-${id.slice("category.".length)}`,
  viewBox: "0 0 24 24",
  strokeWidth: 2,
  body: STOCKROOM_ELECTRICAL_BODY_BY_ID[id],
}));

const TECHNICAL_ART: IconEntry[] = [
  {
    id: "art.symbol",
    category: "art",
    family: "stockroom-technical",
    viewBox: "0 0 132 94",
    size: [132, 94],
    body:
      '<g style="stroke:var(--c-icon-line)" stroke-width="1.5" fill="none">' +
      '<rect x="40" y="20" width="52" height="54" rx="3"/>' +
      '<path d="M40 33H24M40 47H24M40 61H24M92 33h16M92 47h16M92 61h16"/>' +
      "</g>",
  },
  {
    id: "art.footprint",
    category: "art",
    family: "stockroom-technical",
    viewBox: "0 0 132 94",
    size: [132, 94],
    body:
      '<g style="fill:var(--c-icon-fill)">' +
      '<rect x="34" y="26" width="9" height="7" rx="1"/>' +
      '<rect x="48" y="26" width="9" height="7" rx="1"/>' +
      '<rect x="62" y="26" width="9" height="7" rx="1"/>' +
      '<rect x="76" y="26" width="9" height="7" rx="1"/>' +
      '<rect x="90" y="26" width="9" height="7" rx="1"/>' +
      '<rect x="34" y="61" width="9" height="7" rx="1"/>' +
      '<rect x="48" y="61" width="9" height="7" rx="1"/>' +
      '<rect x="62" y="61" width="9" height="7" rx="1"/>' +
      '<rect x="76" y="61" width="9" height="7" rx="1"/>' +
      '<rect x="90" y="61" width="9" height="7" rx="1"/>' +
      "</g>" +
      '<rect x="38" y="37" width="60" height="20" rx="2" fill="none" style="stroke:var(--c-icon-edge)" stroke-width="1.3"/>',
  },
  {
    id: "art.model",
    category: "art",
    family: "stockroom-technical",
    viewBox: "0 0 90 90",
    size: [70, 70],
    fill: "none",
    strokeWidth: 1.4,
    style: { stroke: "var(--c-icon-cube)" },
    body:
      '<path d="M45 12l30 17v32L45 78 15 61V29z"/>' +
      '<path d="M45 12v18M45 30l30-17M45 30L15 13" opacity="0.5"/>',
  },
];

const BRAND_MARKS: IconEntry[] = [
  {
    id: "brand.linkedin",
    category: "brand",
    family: "brand",
    viewBox: "0 0 24 24",
    fill: "currentColor",
    body:
      '<path d="M20.45 20.45h-3.56v-5.57c0-1.33-.02-3.04-1.85-3.04-1.85 0-2.14 1.45-2.14 2.94v5.67H9.35V9h3.42v1.56h.05c.48-.9 1.64-1.85 3.37-1.85 3.6 0 4.27 2.37 4.27 5.46v6.28zM5.34 7.43a2.06 2.06 0 1 1 0-4.13 2.06 2.06 0 0 1 0 4.13zM7.12 20.45H3.55V9h3.57v11.45zM22.22 0H1.77C.79 0 0 .77 0 1.73v20.54C0 23.22.79 24 1.77 24h20.45c.98 0 1.78-.78 1.78-1.73V1.73C24 .77 23.2 0 22.22 0z"/>',
  },
  {
    id: "brand.github",
    category: "brand",
    family: "brand",
    viewBox: "0 0 24 24",
    fill: "currentColor",
    body:
      '<path d="M12 .5C5.37.5 0 5.87 0 12.5c0 5.3 3.44 9.8 8.21 11.39.6.11.82-.26.82-.58l-.02-2.05c-3.34.73-4.04-1.61-4.04-1.61-.55-1.39-1.33-1.76-1.33-1.76-1.09-.74.08-.73.08-.73 1.2.09 1.84 1.24 1.84 1.24 1.07 1.83 2.8 1.3 3.49.99.11-.78.42-1.3.76-1.6-2.67-.3-5.47-1.34-5.47-5.96 0-1.32.47-2.39 1.24-3.23-.13-.31-.54-1.53.12-3.18 0 0 1.01-.32 3.3 1.23a11.5 11.5 0 0 1 6.01 0c2.29-1.55 3.3-1.23 3.3-1.23.66 1.65.25 2.87.12 3.18.77.84 1.24 1.91 1.24 3.23 0 4.63-2.8 5.65-5.48 5.95.43.37.81 1.1.81 2.22l-.01 3.29c0 .32.21.7.82.58A12.01 12.01 0 0 0 24 12.5C24 5.87 18.63.5 12 .5z"/>',
  },
];

export const ICON_REGISTRY: IconEntry[] = [
  ...TABLER_ENTRIES,
  ...STOCKROOM_ELECTRICAL_ENTRIES,
  ...TECHNICAL_ART,
  ...BRAND_MARKS,
];

export const ICON_BY_ID: Map<string, IconEntry> = new Map(
  ICON_REGISTRY.map((entry) => [entry.id, entry]),
);

export function isIconId(id: string): id is IconId {
  return ICON_BY_ID.has(id);
}

export const ICON_CATEGORIES: IconCategory[] = ["primary", "bespoke", "art", "brand"];

export const ICON_IDS_BY_CATEGORY: Record<IconCategory, IconId[]> = (() => {
  const byCategory = {} as Record<IconCategory, IconId[]>;
  for (const category of ICON_CATEGORIES) byCategory[category] = [];
  for (const entry of ICON_REGISTRY) byCategory[entry.category].push(entry.id);
  return byCategory;
})();
