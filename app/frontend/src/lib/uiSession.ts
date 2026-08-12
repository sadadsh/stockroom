/**
 * Durable, non-secret renderer continuity.
 *
 * The WebView origin can change when the host is replaced, so browser storage
 * is only a same-origin mirror. The server-owned snapshot is injected before
 * React boots and is the authority. Every field is bounded and allowlisted;
 * credentials, browser sessions, native handles, local paths, and CAD bytes
 * have no representation in this schema.
 */
import { useSyncExternalStore } from "react";
import { api } from "../api/client";
import type { EnrichmentResult } from "../api/types";

export const UI_SESSION_SCHEMA = "stockroom.ui-session" as const;
export const UI_SESSION_VERSION = 3 as const;
export const INTAKE_DRAFT_SCHEMA = "stockroom.intake-draft" as const;
export const INTAKE_DRAFT_VERSION = 1 as const;

export type UiSessionRoute = "components" | "projects" | "stm" | "settings";
export type DetailTab = "specs" | "sourcing" | "enrich" | "history" | "handoff";
export type SettingsGroup = "general" | "library" | "eda" | "sources" | "maintenance";
export type OpenSurface = "search" | "add_part" | "complete_part" | null;

/** The four questions the opened component answers. Closed vocabulary, persisted per component. */
export type ComponentInfoTab = "overview" | "specifications" | "sourcing" | "sources";
export type CadWorkspaceView = "models" | "manage-models";
/**
 * Which representation the column focuses. `all` shows the three stacked.
 *
 * Listed in the column's own reading order - 3D Model, Footprint, Symbol - so the vocabulary reads
 * the way the modules stack. Only membership is enforced (`REPRESENTATION_LAYOUTS.includes`), so the
 * sequence here is documentation rather than behaviour; `CAD_ASSET_KINDS` is what actually orders
 * anything on screen.
 */
export type RepresentationLayout = "all" | "model" | "footprint" | "symbol";

/** One opened component's view state. Bounded, non-secret, and meaningless without the record. */
export interface ComponentViewState {
  info_tab: ComponentInfoTab;
  cad_view: CadWorkspaceView;
  representation_layout: RepresentationLayout;
  representation_tool: { symbol: string; footprint: string; model: string };
}

/**
 * How many components may be open at once. A tab strip that can grow without limit stops being a
 * tab strip, and the snapshot must stay inside the host's 64 KB session budget.
 */
export const MAX_OPEN_COMPONENTS = 12;

export const COMPONENT_INFO_TABS: readonly ComponentInfoTab[] = [
  "overview",
  "specifications",
  "sourcing",
  "sources",
];

export const CAD_WORKSPACE_VIEWS: readonly CadWorkspaceView[] = ["models", "manage-models"];

export const REPRESENTATION_LAYOUTS: readonly RepresentationLayout[] = [
  "all",
  "model",
  "footprint",
  "symbol",
];

export function defaultComponentView(): ComponentViewState {
  return {
    info_tab: "overview",
    cad_view: "models",
    representation_layout: "all",
    representation_tool: { symbol: "", footprint: "", model: "" },
  };
}

export interface SearchOptionState {
  key: string;
  values: string[];
}

export interface SearchRangeState {
  key: string;
  min: number | null;
  max: number | null;
}

export type SearchSortState =
  | { kind: "name" | "stock" | "unit"; direction: "asc" | "desc" }
  | {
      kind: "spec";
      key: string;
      numeric: boolean;
      direction: "asc" | "desc";
    };

export interface UiSessionSnapshotV2 {
  schema: typeof UI_SESSION_SCHEMA;
  version: typeof UI_SESSION_VERSION;
  route: UiSessionRoute;
  selected_ids: {
    component: string | null;
    project: string | null;
    stm_part: string | null;
    stm_pin: string | null;
    workflow_batch: string | null;
    workflow_item: string | null;
  };
  component_filters: {
    query: string;
    category: string | null;
    complete_only: boolean;
    duplicates_only: boolean;
  };
  component_list_anchor: {
    part_id: string | null;
    offset_px: number;
  };
  search_filters: {
    query: string;
    category: string | null;
    in_stock: boolean;
    options: SearchOptionState[];
    ranges: SearchRangeState[];
  };
  search_sort: SearchSortState;
  search_results: {
    active_part_id: string | null;
    anchor_part_id: string | null;
    offset_px: number;
  };
  detail_tab: DetailTab;
  stm: {
    tab: "explorer" | "compatibility";
    families: string[];
    lines: string[];
    pin_view: "map" | "table";
  };
  settings_group: SettingsGroup;
  open_surface: OpenSurface;
  intake_draft_ref: { draft_id: string; revision: number } | null;
  event_sequence: number;
  /** Ordered open component ids. The order IS the tab order, so it never reorders on activation. */
  open_components: string[];
  /** The active tab. Always a member of `open_components`, enforced on read and on write. */
  active_component: string | null;
  /**
   * Per-component view state, keyed by component id.
   *
   * The KEY ORDER is the recency ledger the bound uses: the most recently activated component is
   * last, so eviction can name the least recently used tab without a second field (and without
   * reordering `open_components`, which would make tabs jump under the pointer).
   */
  component_views: Record<string, ComponentViewState>;
}

/** The shape a persisted v1 snapshot has. Kept only so the migration can be typed. */
export type UiSessionSnapshotV1 = Omit<
  UiSessionSnapshotV2,
  "version" | "open_components" | "active_component" | "component_views"
> & { version: 1 };

type JsonPrimitive = string | number | boolean | null;
export type JsonValue = JsonPrimitive | JsonValue[] | { [key: string]: JsonValue };

export interface IntakeDraftNetworkInput {
  kind: "mpn" | "product_url";
  value: string;
}

export interface IntakeDraftPurchase {
  vendor: string;
  url: string;
  part_number: string;
  price_breaks: { qty: number; price: number; currency: string }[];
  stock: number | null;
  currency: string;
  fetched_at: string;
}

export interface IntakeDraftCandidate {
  client_id: string;
  vendor: string;
  display_name: string;
  entry_name: string;
  category: string;
  mpn: string;
  manufacturer: string;
  description: string;
  tags: string[];
  purchase: IntakeDraftPurchase[];
  gaps: string[];
  specs: { key: string; value: JsonValue }[];
  alternates: {
    key: string;
    values: { value: JsonValue; source: string; confidence: string }[];
  }[];
  enrichment: { key: string; source: string; confidence: string }[];
  datasheet_url: string;
  conflicts: {
    key: string;
    values: { value: JsonValue; source: string }[];
  }[];
}

export interface IntakeDraftReview {
  lookup_input: IntakeDraftNetworkInput | null;
  enrichment_result: EnrichmentResult | null;
  candidates: IntakeDraftCandidate[];
}

export interface IntakeDraftBodyV1 {
  network_input: IntakeDraftNetworkInput;
  review: IntakeDraftReview;
}

export interface StoredIntakeDraftV1 extends IntakeDraftBodyV1 {
  schema: typeof INTAKE_DRAFT_SCHEMA;
  version: typeof INTAKE_DRAFT_VERSION;
  draft_id: string;
  revision: number;
}

export interface UiSessionExportV1 {
  snapshot: UiSessionSnapshotV2;
  intake_draft?: IntakeDraftBodyV1 & {
    draft_id: string | null;
    revision: number;
  };
}

declare global {
  interface Window {
    __STOCKROOM_SESSION__?: unknown;
    __STOCKROOM_EXPORT_UI_SESSION__?: () => UiSessionExportV1;
  }
}

const MIRROR_KEY = "stockroom.ui-session.v1";
const WRITE_DELAY_MS = 80;
const MAX_QUERY = 512;
const MAX_TEXT = 512;
const MAX_ID = 192;
const MAX_COLLECTION = 64;
const MAX_OFFSET = 10_000_000;
const MAX_DRAFT_BYTES = 256 * 1024;
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

export function defaultUiSession(): UiSessionSnapshotV2 {
  return {
    schema: UI_SESSION_SCHEMA,
    version: UI_SESSION_VERSION,
    route: "components",
    selected_ids: {
      component: null,
      project: null,
      stm_part: null,
      stm_pin: null,
      workflow_batch: null,
      workflow_item: null,
    },
    component_filters: {
      query: "",
      category: null,
      complete_only: false,
      duplicates_only: false,
    },
    component_list_anchor: { part_id: null, offset_px: 0 },
    search_filters: {
      query: "",
      category: null,
      in_stock: false,
      options: [],
      ranges: [],
    },
    search_sort: { kind: "name", direction: "asc" },
    search_results: {
      active_part_id: null,
      anchor_part_id: null,
      offset_px: 0,
    },
    detail_tab: "specs",
    stm: {
      tab: "explorer",
      families: [],
      lines: [],
      pin_view: "map",
    },
    settings_group: "general",
    open_surface: null,
    intake_draft_ref: null,
    event_sequence: 0,
    open_components: [],
    active_component: null,
    component_views: {},
  };
}

// The exact key set of the CURRENT version, in one place so the parser and the migration cannot
// disagree about what "complete" means.
const SNAPSHOT_KEYS = [
  "schema",
  "version",
  "route",
  "selected_ids",
  "component_filters",
  "component_list_anchor",
  "search_filters",
  "search_sort",
  "search_results",
  "detail_tab",
  "stm",
  "settings_group",
  "open_surface",
  "intake_draft_ref",
  "event_sequence",
  "open_components",
  "active_component",
  "component_views",
] as const;

const COMPONENT_VIEW_KEYS = [
  "info_tab",
  "cad_view",
  "representation_layout",
  "representation_tool",
] as const;

const REPRESENTATION_TOOL_KEYS = ["symbol", "footprint", "model"] as const;

function plainObject(value: unknown): Record<string, unknown> | null {
  if (value === null || typeof value !== "object" || Array.isArray(value)) return null;
  const proto = Object.getPrototypeOf(value);
  return proto === Object.prototype || proto === null
    ? (value as Record<string, unknown>)
    : null;
}

function exactKeys(object: Record<string, unknown>, keys: readonly string[]): boolean {
  const actual = Object.keys(object).sort();
  const expected = [...keys].sort();
  return actual.length === expected.length && actual.every((key, index) => key === expected[index]);
}

function boundedString(value: unknown, maximum = MAX_TEXT): string | null {
  return typeof value === "string" && value.length <= maximum ? value : null;
}

function nullableString(value: unknown, maximum = MAX_TEXT): string | null | undefined {
  if (value === null) return null;
  const text = boundedString(value, maximum);
  return text === null ? undefined : text;
}

function nonNegativeInteger(value: unknown, maximum = Number.MAX_SAFE_INTEGER): number | null {
  return Number.isSafeInteger(value) && Number(value) >= 0 && Number(value) <= maximum
    ? Number(value)
    : null;
}

function finiteOrNull(value: unknown): number | null | undefined {
  if (value === null) return null;
  return typeof value === "number" && Number.isFinite(value) ? value : undefined;
}

function stringArray(value: unknown, maximumItems = MAX_COLLECTION): string[] | null {
  if (!Array.isArray(value) || value.length > maximumItems) return null;
  const result: string[] = [];
  for (const item of value) {
    const text = boundedString(item);
    if (text === null) return null;
    result.push(text);
  }
  return result;
}

function parseSearchSort(value: unknown): SearchSortState | null {
  const object = plainObject(value);
  if (!object) return null;
  const direction = object.direction;
  if (direction !== "asc" && direction !== "desc") return null;
  if (object.kind === "spec") {
    if (!exactKeys(object, ["kind", "key", "numeric", "direction"])) return null;
    const key = boundedString(object.key);
    if (key === null || typeof object.numeric !== "boolean") return null;
    return { kind: "spec", key, numeric: object.numeric, direction };
  }
  if (!exactKeys(object, ["kind", "direction"])) return null;
  if (object.kind !== "name" && object.kind !== "stock" && object.kind !== "unit") return null;
  return { kind: object.kind, direction };
}

function parseSearchOptions(value: unknown): SearchOptionState[] | null {
  if (!Array.isArray(value) || value.length > MAX_COLLECTION) return null;
  const seen = new Set<string>();
  const result: SearchOptionState[] = [];
  for (const item of value) {
    const object = plainObject(item);
    if (!object || !exactKeys(object, ["key", "values"])) return null;
    const key = boundedString(object.key);
    const values = stringArray(object.values);
    if (key === null || values === null || seen.has(key)) return null;
    seen.add(key);
    result.push({ key, values });
  }
  return result;
}

function parseSearchRanges(value: unknown): SearchRangeState[] | null {
  if (!Array.isArray(value) || value.length > MAX_COLLECTION) return null;
  const seen = new Set<string>();
  const result: SearchRangeState[] = [];
  for (const item of value) {
    const object = plainObject(item);
    if (!object || !exactKeys(object, ["key", "min", "max"])) return null;
    const key = boundedString(object.key);
    const min = finiteOrNull(object.min);
    const max = finiteOrNull(object.max);
    if (key === null || min === undefined || max === undefined || seen.has(key)) return null;
    seen.add(key);
    result.push({ key, min, max });
  }
  return result;
}

/**
 * The ordered open-component list.
 *
 * Duplicates are FOLDED rather than rejected: two tabs on one component is not a hostile payload,
 * it is a snapshot that lost a race, and the honest repair is one tab. Anything else about the
 * list (a non-string entry, an over-long id, more entries than the bound allows) is off-contract
 * and fails closed like every other field here.
 */
function parseOpenComponents(value: unknown): string[] | null {
  if (!Array.isArray(value)) return null;
  const seen = new Set<string>();
  const result: string[] = [];
  for (const item of value) {
    const text = boundedString(item, MAX_ID);
    if (text === null || text === "") return null;
    if (seen.has(text)) continue;
    seen.add(text);
    result.push(text);
  }
  return result.length > MAX_OPEN_COMPONENTS ? null : result;
}

function parseComponentView(value: unknown): ComponentViewState | null {
  const object = plainObject(value);
  if (!object || !exactKeys(object, COMPONENT_VIEW_KEYS)) return null;
  const tools = plainObject(object.representation_tool);
  if (
    !tools ||
    !exactKeys(tools, REPRESENTATION_TOOL_KEYS) ||
    !COMPONENT_INFO_TABS.includes(object.info_tab as ComponentInfoTab) ||
    !CAD_WORKSPACE_VIEWS.includes(object.cad_view as CadWorkspaceView) ||
    !REPRESENTATION_LAYOUTS.includes(object.representation_layout as RepresentationLayout)
  ) {
    return null;
  }
  const symbol = boundedString(tools.symbol, MAX_ID);
  const footprint = boundedString(tools.footprint, MAX_ID);
  const model = boundedString(tools.model, MAX_ID);
  if (symbol === null || footprint === null || model === null) return null;
  return {
    info_tab: object.info_tab as ComponentInfoTab,
    cad_view: object.cad_view as CadWorkspaceView,
    representation_layout: object.representation_layout as RepresentationLayout,
    representation_tool: { symbol, footprint, model },
  };
}

/**
 * The per-component view map, PRUNED to the components that are actually open.
 *
 * View state for a closed tab is dead weight that would otherwise grow without bound, and the key
 * order carries the recency ledger, so a stale key would also corrupt eviction.
 */
function parseComponentViews(
  value: unknown,
  open: readonly string[],
): Record<string, ComponentViewState> | null {
  const object = plainObject(value);
  if (!object) return null;
  const entries = Object.entries(object);
  if (entries.length > MAX_OPEN_COMPONENTS) return null;
  const result: Record<string, ComponentViewState> = {};
  const openSet = new Set(open);
  for (const [key, raw] of entries) {
    if (key.length === 0 || key.length > MAX_ID) return null;
    const view = parseComponentView(raw);
    if (view === null) return null;
    if (!openSet.has(key)) continue;
    result[key] = view;
  }
  return result;
}

/**
 * Bring a persisted snapshot up to the CURRENT version before it is validated.
 *
 * Without this every existing install would fail closed to defaults on first boot after the bump -
 * the route, the filters, the picker anchor and the staged intake draft all silently discarded
 * because three fields were added. The migration only ever ADDS what the new version needs; every
 * value it produces still has to survive the same exact-key validation as a native v2 snapshot, so
 * a hostile v1 payload gains nothing by being old.
 */
export function migrateUiSession(value: unknown): unknown {
  const object = plainObject(value);
  if (!object || object.schema !== UI_SESSION_SCHEMA) return value;
  let migrated: Record<string, unknown> = object;
  if (migrated.version === 1) {
    const selected = plainObject(migrated.selected_ids);
    const component = typeof selected?.component === "string" ? selected.component : null;
    const { version: _version, ...rest } = migrated;
    migrated = {
      ...rest,
      version: 2,
      open_components: component ? [component] : [],
      active_component: component,
      component_views: {},
    };
  }
  if (migrated.version === 2) {
    const rawViews = plainObject(migrated.component_views);
    const views = Object.fromEntries(
      Object.entries(rawViews ?? {}).map(([id, raw]) => {
        const view = plainObject(raw);
        return [id, view ? { ...view, cad_view: "models" } : raw];
      }),
    );
    migrated = { ...migrated, version: UI_SESSION_VERSION, component_views: views };
  }
  return migrated;
}

export function parseUiSession(value: unknown): UiSessionSnapshotV2 | null {
  const object = plainObject(migrateUiSession(value));
  if (
    !object ||
    !exactKeys(object, SNAPSHOT_KEYS) ||
    object.schema !== UI_SESSION_SCHEMA ||
    object.version !== UI_SESSION_VERSION ||
    !["components", "projects", "stm", "settings"].includes(String(object.route))
  ) {
    return null;
  }

  const selected = plainObject(object.selected_ids);
  const componentFilters = plainObject(object.component_filters);
  const componentAnchor = plainObject(object.component_list_anchor);
  const searchFilters = plainObject(object.search_filters);
  const searchResults = plainObject(object.search_results);
  const stm = plainObject(object.stm);
  if (
    !selected ||
    !exactKeys(selected, [
      "component",
      "project",
      "stm_part",
      "stm_pin",
      "workflow_batch",
      "workflow_item",
    ]) ||
    !componentFilters ||
    !exactKeys(componentFilters, ["query", "category", "complete_only", "duplicates_only"]) ||
    !componentAnchor ||
    !exactKeys(componentAnchor, ["part_id", "offset_px"]) ||
    !searchFilters ||
    !exactKeys(searchFilters, ["query", "category", "in_stock", "options", "ranges"]) ||
    !searchResults ||
    !exactKeys(searchResults, ["active_part_id", "anchor_part_id", "offset_px"]) ||
    !stm ||
    !exactKeys(stm, ["tab", "families", "lines", "pin_view"])
  ) {
    return null;
  }

  const component = nullableString(selected.component, MAX_ID);
  const project = nullableString(selected.project, MAX_ID);
  const stmPart = nullableString(selected.stm_part, MAX_ID);
  const stmPin = nullableString(selected.stm_pin, MAX_ID);
  const workflowBatch = nullableString(selected.workflow_batch, MAX_ID);
  const workflowItem = nullableString(selected.workflow_item, MAX_ID);
  const componentQuery = boundedString(componentFilters.query, MAX_QUERY);
  const componentCategory = nullableString(componentFilters.category);
  const anchorPart = nullableString(componentAnchor.part_id, MAX_ID);
  const componentOffset = nonNegativeInteger(componentAnchor.offset_px, MAX_OFFSET);
  const searchQuery = boundedString(searchFilters.query, MAX_QUERY);
  const searchCategory = nullableString(searchFilters.category);
  const options = parseSearchOptions(searchFilters.options);
  const ranges = parseSearchRanges(searchFilters.ranges);
  const searchSort = parseSearchSort(object.search_sort);
  const activePart = nullableString(searchResults.active_part_id, MAX_ID);
  const searchAnchor = nullableString(searchResults.anchor_part_id, MAX_ID);
  const searchOffset = nonNegativeInteger(searchResults.offset_px, MAX_OFFSET);
  const families = stringArray(stm.families);
  const lines = stringArray(stm.lines);
  const eventSequence = nonNegativeInteger(object.event_sequence);
  const openComponents = parseOpenComponents(object.open_components);
  const componentViews =
    openComponents === null ? null : parseComponentViews(object.component_views, openComponents);
  const activeComponent = nullableString(object.active_component, MAX_ID);
  if (
    component === undefined ||
    project === undefined ||
    stmPart === undefined ||
    stmPin === undefined ||
    workflowBatch === undefined ||
    workflowItem === undefined ||
    componentQuery === null ||
    componentCategory === undefined ||
    anchorPart === undefined ||
    componentOffset === null ||
    searchQuery === null ||
    searchCategory === undefined ||
    options === null ||
    ranges === null ||
    searchSort === null ||
    activePart === undefined ||
    searchAnchor === undefined ||
    searchOffset === null ||
    families === null ||
    lines === null ||
    eventSequence === null ||
    openComponents === null ||
    componentViews === null ||
    activeComponent === undefined ||
    typeof componentFilters.complete_only !== "boolean" ||
    typeof componentFilters.duplicates_only !== "boolean" ||
    typeof searchFilters.in_stock !== "boolean" ||
    !["specs", "sourcing", "enrich", "history", "handoff"].includes(String(object.detail_tab)) ||
    !["explorer", "compatibility"].includes(String(stm.tab)) ||
    !["map", "table"].includes(String(stm.pin_view)) ||
    !["general", "library", "eda", "sources", "maintenance"].includes(
      String(object.settings_group),
    ) ||
    ![null, "search", "add_part", "complete_part"].includes(
      object.open_surface as OpenSurface,
    )
  ) {
    return null;
  }

  let draftRef: UiSessionSnapshotV2["intake_draft_ref"] = null;
  if (object.intake_draft_ref !== null) {
    const ref = plainObject(object.intake_draft_ref);
    if (!ref || !exactKeys(ref, ["draft_id", "revision"])) return null;
    const revision = nonNegativeInteger(ref.revision);
    if (
      typeof ref.draft_id !== "string" ||
      !UUID.test(ref.draft_id) ||
      revision === null ||
      revision < 1
    ) {
      return null;
    }
    draftRef = { draft_id: ref.draft_id, revision };
  }

  return {
    schema: UI_SESSION_SCHEMA,
    version: UI_SESSION_VERSION,
    route: object.route as UiSessionRoute,
    selected_ids: {
      component,
      project,
      stm_part: stmPart,
      stm_pin: stmPin,
      workflow_batch: workflowBatch,
      workflow_item: workflowItem,
    },
    component_filters: {
      query: componentQuery,
      category: componentCategory,
      complete_only: componentFilters.complete_only,
      duplicates_only: componentFilters.duplicates_only,
    },
    component_list_anchor: { part_id: anchorPart, offset_px: componentOffset },
    search_filters: {
      query: searchQuery,
      category: searchCategory,
      in_stock: searchFilters.in_stock,
      options,
      ranges,
    },
    search_sort: searchSort,
    search_results: {
      active_part_id: activePart,
      anchor_part_id: searchAnchor,
      offset_px: searchOffset,
    },
    detail_tab: object.detail_tab as DetailTab,
    stm: {
      tab: stm.tab as UiSessionSnapshotV2["stm"]["tab"],
      families,
      lines,
      pin_view: stm.pin_view as UiSessionSnapshotV2["stm"]["pin_view"],
    },
    settings_group: object.settings_group as SettingsGroup,
    open_surface: object.open_surface as OpenSurface,
    intake_draft_ref: draftRef,
    event_sequence: eventSequence,
    open_components: openComponents,
    // An active tab that is not open is not a tab. Dropped rather than rejected, because the
    // honest repair is "no component is active", not "discard the whole session".
    active_component:
      activeComponent !== null && openComponents.includes(activeComponent)
        ? activeComponent
        : null,
    component_views: componentViews,
  };
}

// ---------------------------------------------------------------- opened components

/** The least-recently-activated open component, ignoring `active`. Null when there is nobody to evict. */
function leastRecentlyUsed(
  snapshot: UiSessionSnapshotV2,
  active: string | null,
): string | null {
  const recency = Object.keys(snapshot.component_views);
  const candidates = snapshot.open_components.filter((id) => id !== active);
  if (candidates.length === 0) return null;
  // A component with no view entry has never been activated, so it is older than anything the
  // ledger knows about - and `indexOf` already reports that as -1, which sorts before every real
  // rank. Ties keep the earliest-opened tab, so the strip evicts left to right.
  let worst = candidates[0];
  let worstRank = recency.indexOf(worst);
  for (const id of candidates.slice(1)) {
    const rank = recency.indexOf(id);
    if (rank < worstRank) {
      worst = id;
      worstRank = rank;
    }
  }
  return worst;
}

/**
 * Open a component's tab, or activate it if it is already open.
 *
 * Never duplicates a tab, never reorders the strip, and holds the bound by evicting the least
 * recently used tab that is not the one being activated. Closing a tab does not touch the record.
 */
export function openComponentInSession(
  snapshot: UiSessionSnapshotV2,
  id: string,
): UiSessionSnapshotV2 {
  if (!id) return snapshot;
  let open = snapshot.open_components.includes(id)
    ? [...snapshot.open_components]
    : [...snapshot.open_components, id];
  const views = { ...snapshot.component_views };
  while (open.length > MAX_OPEN_COMPONENTS) {
    const evicted = leastRecentlyUsed({ ...snapshot, open_components: open }, id);
    if (evicted === null) break;
    open = open.filter((other) => other !== evicted);
    delete views[evicted];
  }
  // Re-inserting moves the key to the end of the ledger, which is what makes it a recency order.
  const view = views[id] ?? defaultComponentView();
  delete views[id];
  views[id] = view;
  return { ...snapshot, open_components: open, active_component: id, component_views: views };
}

/**
 * Close one tab. The component itself is untouched; only this view of it goes away.
 *
 * Activation falls to the neighbour on the right, then the left, so closing the last tab in a run
 * does not dump the person back to an empty workspace while other tabs are still open.
 */
export function closeComponentInSession(
  snapshot: UiSessionSnapshotV2,
  id: string,
): UiSessionSnapshotV2 {
  const index = snapshot.open_components.indexOf(id);
  if (index === -1) return snapshot;
  const open = snapshot.open_components.filter((other) => other !== id);
  const views = { ...snapshot.component_views };
  delete views[id];
  const active =
    snapshot.active_component === id
      ? (open[index] ?? open[index - 1] ?? null)
      : snapshot.active_component;
  return { ...snapshot, open_components: open, active_component: active, component_views: views };
}

/**
 * Drop tabs whose component is no longer in the library.
 *
 * A deleted part must not leave a tab that can never render. `available` is the settled list; an
 * empty list is treated as "nothing is known yet" and changes nothing, so a page that has not
 * loaded cannot wipe the restored strip.
 */
export function pruneOpenComponents(
  snapshot: UiSessionSnapshotV2,
  available: ReadonlySet<string>,
): UiSessionSnapshotV2 {
  if (available.size === 0) return snapshot;
  const open = snapshot.open_components.filter((id) => available.has(id));
  if (open.length === snapshot.open_components.length) return snapshot;
  const views: Record<string, ComponentViewState> = {};
  for (const [id, view] of Object.entries(snapshot.component_views)) {
    if (available.has(id)) views[id] = view;
  }
  const active =
    snapshot.active_component && open.includes(snapshot.active_component)
      ? snapshot.active_component
      : (open[0] ?? null);
  return { ...snapshot, open_components: open, active_component: active, component_views: views };
}

/** Read one component's view state, defaulted. Never returns a shape the contract would reject. */
export function componentView(
  snapshot: UiSessionSnapshotV2,
  id: string | null,
): ComponentViewState {
  if (!id) return defaultComponentView();
  return snapshot.component_views[id] ?? defaultComponentView();
}

/**
 * Patch one open component's view state. A component that is not open has no view to write.
 *
 * The tool map is patchable per kind, because every call site changes exactly one representation's
 * tool and would otherwise have to restate the other two - which is how a caller eventually resets
 * a value it never meant to touch.
 */
export function setComponentViewInSession(
  snapshot: UiSessionSnapshotV2,
  id: string,
  patch: Partial<Omit<ComponentViewState, "representation_tool">> & {
    representation_tool?: Partial<ComponentViewState["representation_tool"]>;
  },
): UiSessionSnapshotV2 {
  if (!snapshot.open_components.includes(id)) return snapshot;
  const current = componentView(snapshot, id);
  return {
    ...snapshot,
    component_views: {
      ...snapshot.component_views,
      [id]: {
        ...current,
        ...patch,
        representation_tool: {
          ...current.representation_tool,
          ...(patch.representation_tool ?? {}),
        },
      },
    },
  };
}

// A structural copy, not a JSON round trip. Everything cloned here is a snapshot that has already
// been through `parseUiSession` / `plainObject` / `exactKeys`, so it holds nothing a structured
// clone cannot carry - and unlike the round trip it neither serialises the whole tree to a string
// to throw the string away, nor silently rewrites a value on the way through.
function clone<T>(value: T): T {
  return structuredClone(value);
}

function initialSnapshot(): UiSessionSnapshotV2 {
  try {
    if (window.__STOCKROOM_SESSION__ !== undefined) {
      return parseUiSession(window.__STOCKROOM_SESSION__) ?? defaultUiSession();
    }
    const mirrored = localStorage.getItem(MIRROR_KEY);
    if (mirrored) return parseUiSession(JSON.parse(mirrored)) ?? defaultUiSession();
  } catch {
    // A malformed or unavailable browser mirror has no authority.
  }
  return defaultUiSession();
}

let state = initialSnapshot();
let pendingDraft: IntakeDraftBodyV1 | null = null;
let changeGeneration = 0;
let writeTimer: number | null = null;
let writeChain: Promise<void> = Promise.resolve();
const listeners = new Set<() => void>();

function notify(): void {
  for (const listener of listeners) listener();
}

function mirror(): void {
  try {
    localStorage.setItem(MIRROR_KEY, JSON.stringify(state));
  } catch {
    // Same-origin recovery only; the server-owned copy remains authoritative.
  }
}

function installExportHook(): void {
  try {
    window.__STOCKROOM_EXPORT_UI_SESSION__ = () => {
      const result: UiSessionExportV1 = { snapshot: clone(state) };
      if (pendingDraft) {
        const ref = state.intake_draft_ref;
        result.intake_draft = {
          draft_id: ref?.draft_id ?? null,
          revision: ref?.revision ?? 0,
          ...clone(pendingDraft),
        };
      }
      return result;
    };
  } catch {
    // Dev/test runtimes without a writable window still use the in-memory store.
  }
}

installExportHook();

function scheduleWrite(): void {
  if (typeof window === "undefined") return;
  if (writeTimer !== null) window.clearTimeout(writeTimer);
  writeTimer = window.setTimeout(() => {
    writeTimer = null;
    void flushUiSession();
  }, WRITE_DELAY_MS);
}

function replaceState(next: UiSessionSnapshotV2, { persist }: { persist: boolean }): void {
  state = clone(next);
  changeGeneration += 1;
  mirror();
  notify();
  if (persist) scheduleWrite();
}

export function readUiSession(): UiSessionSnapshotV2 {
  return state;
}

export function updateUiSession(
  update: (current: UiSessionSnapshotV2) => UiSessionSnapshotV2,
): void {
  const next = parseUiSession(update(clone(state)));
  if (!next) throw new TypeError("UI session update violates the v2 contract");
  replaceState(next, { persist: true });
}

export function useUiSession(): UiSessionSnapshotV2 {
  return useSyncExternalStore(
    (listener) => {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    () => state,
    () => state,
  );
}

function jsonBytes(value: unknown): number {
  return new TextEncoder().encode(JSON.stringify(value)).byteLength;
}

export function setPendingIntakeDraft(draft: IntakeDraftBodyV1 | null): void {
  if (draft !== null) {
    if (!parseDraftBody(draft) || jsonBytes(draft) > MAX_DRAFT_BYTES) {
      throw new TypeError("intake draft violates the v1 contract");
    }
  }
  pendingDraft = draft === null ? null : clone(draft);
  changeGeneration += 1;
  scheduleWrite();
}

function parseNetworkInput(value: unknown): IntakeDraftNetworkInput | null {
  const object = plainObject(value);
  if (
    !object ||
    !exactKeys(object, ["kind", "value"]) ||
    (object.kind !== "mpn" && object.kind !== "product_url") ||
    typeof object.value !== "string" ||
    object.value.length === 0 ||
    object.value.length > 2_000
  ) {
    return null;
  }
  return { kind: object.kind, value: object.value };
}

function parseDraftBody(value: unknown): IntakeDraftBodyV1 | null {
  const object = plainObject(value);
  if (
    !object ||
    !exactKeys(object, ["network_input", "review"]) ||
    jsonBytes(object) > MAX_DRAFT_BYTES
  ) {
    return null;
  }
  const network = parseNetworkInput(object.network_input);
  const review = plainObject(object.review);
  if (
    !network ||
    !review ||
    !exactKeys(review, ["lookup_input", "enrichment_result", "candidates"]) ||
    (review.lookup_input !== null && parseNetworkInput(review.lookup_input) === null) ||
    (review.enrichment_result !== null && plainObject(review.enrichment_result) === null) ||
    !Array.isArray(review.candidates) ||
    review.candidates.length > 16
  ) {
    return null;
  }
  return clone(object) as unknown as IntakeDraftBodyV1;
}

function parseStoredDraft(value: unknown): StoredIntakeDraftV1 | null {
  const object = plainObject(value);
  if (
    !object ||
    !exactKeys(object, [
      "schema",
      "version",
      "draft_id",
      "revision",
      "network_input",
      "review",
    ]) ||
    object.schema !== INTAKE_DRAFT_SCHEMA ||
    object.version !== INTAKE_DRAFT_VERSION ||
    typeof object.draft_id !== "string" ||
    !UUID.test(object.draft_id)
  ) {
    return null;
  }
  const revision = nonNegativeInteger(object.revision);
  const body = parseDraftBody({
    network_input: object.network_input,
    review: object.review,
  });
  if (revision === null || revision < 1 || body === null) return null;
  return {
    schema: INTAKE_DRAFT_SCHEMA,
    version: INTAKE_DRAFT_VERSION,
    draft_id: object.draft_id,
    revision,
    ...body,
  };
}

async function persistDraft(
  draft: IntakeDraftBodyV1,
  ref: UiSessionSnapshotV2["intake_draft_ref"],
): Promise<StoredIntakeDraftV1> {
  const raw =
    ref === null
      ? await api.createIntakeDraft(draft)
      : await api.updateIntakeDraft(ref.draft_id, {
          revision: ref.revision,
          ...draft,
        });
  const stored = parseStoredDraft(raw);
  if (!stored) throw new TypeError("server returned an invalid intake draft");
  return stored;
}

export function flushUiSession(): Promise<void> {
  const queued = async () => {
    const startedAt = changeGeneration;
    const draft = pendingDraft ? clone(pendingDraft) : null;
    let snapshot = clone(state);
    if (draft) {
      const stored = await persistDraft(draft, snapshot.intake_draft_ref);
      snapshot.intake_draft_ref = {
        draft_id: stored.draft_id,
        revision: stored.revision,
      };
      // A newer local interaction keeps its state but still adopts the durable
      // reference returned for the staged draft.
      state = {
        ...state,
        intake_draft_ref: clone(snapshot.intake_draft_ref),
      };
      mirror();
      notify();
    }
    const echoed = await api.putUiSession(snapshot);
    const saved = parseUiSession(echoed);
    if (!saved) throw new TypeError("server returned an invalid UI session");
    if (changeGeneration === startedAt) {
      state = saved;
      mirror();
      notify();
    } else {
      scheduleWrite();
    }
  };
  writeChain = writeChain.then(queued, queued).catch(() => {
    // Interaction remains usable offline. The synchronous host export hook is
    // still the last-keystroke authority during a planned update.
  });
  return writeChain;
}

export async function loadIntakeDraft(): Promise<StoredIntakeDraftV1 | null> {
  const ref = state.intake_draft_ref;
  if (!ref) return null;
  const draft = parseStoredDraft(await api.getIntakeDraft(ref.draft_id, ref.revision));
  if (!draft || draft.revision !== ref.revision) return null;
  return draft;
}

export async function discardIntakeDraft(): Promise<void> {
  const ref = state.intake_draft_ref;
  pendingDraft = null;
  updateUiSession((current) => ({ ...current, intake_draft_ref: null }));
  if (ref) {
    try {
      await api.deleteIntakeDraft(ref.draft_id);
    } catch {
      // The snapshot no longer references it; backend retention can reap an
      // unreachable draft without blocking the interaction.
    }
  }
}

/** Test-only reset kept explicit so global durable state cannot leak between specs. */
export function resetUiSessionForTests(snapshot: UiSessionSnapshotV2 = defaultUiSession()): void {
  if (writeTimer !== null && typeof window !== "undefined") {
    window.clearTimeout(writeTimer);
    writeTimer = null;
  }
  pendingDraft = null;
  changeGeneration = 0;
  writeChain = Promise.resolve();
  state = clone(snapshot);
  mirror();
  installExportHook();
  notify();
}
