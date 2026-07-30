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
export const UI_SESSION_VERSION = 1 as const;
export const INTAKE_DRAFT_SCHEMA = "stockroom.intake-draft" as const;
export const INTAKE_DRAFT_VERSION = 1 as const;

export type UiSessionRoute = "components" | "stm" | "settings";
export type DetailTab = "specs" | "sourcing" | "enrich" | "history" | "handoff";
export type SettingsGroup = "general" | "library" | "eda" | "sources" | "maintenance";
export type OpenSurface = "search" | "add_part" | "complete_part" | null;

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

export interface UiSessionSnapshotV1 {
  schema: typeof UI_SESSION_SCHEMA;
  version: typeof UI_SESSION_VERSION;
  route: UiSessionRoute;
  selected_ids: {
    component: string | null;
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
}

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
  snapshot: UiSessionSnapshotV1;
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

export function defaultUiSession(): UiSessionSnapshotV1 {
  return {
    schema: UI_SESSION_SCHEMA,
    version: UI_SESSION_VERSION,
    route: "components",
    selected_ids: {
      component: null,
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
  };
}

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

export function parseUiSession(value: unknown): UiSessionSnapshotV1 | null {
  const object = plainObject(value);
  if (
    !object ||
    !exactKeys(object, [
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
    ]) ||
    object.schema !== UI_SESSION_SCHEMA ||
    object.version !== UI_SESSION_VERSION ||
    !["components", "stm", "settings"].includes(String(object.route))
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
  if (
    component === undefined ||
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

  let draftRef: UiSessionSnapshotV1["intake_draft_ref"] = null;
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
      tab: stm.tab as UiSessionSnapshotV1["stm"]["tab"],
      families,
      lines,
      pin_view: stm.pin_view as UiSessionSnapshotV1["stm"]["pin_view"],
    },
    settings_group: object.settings_group as SettingsGroup,
    open_surface: object.open_surface as OpenSurface,
    intake_draft_ref: draftRef,
    event_sequence: eventSequence,
  };
}

function clone<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T;
}

function initialSnapshot(): UiSessionSnapshotV1 {
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

function replaceState(next: UiSessionSnapshotV1, { persist }: { persist: boolean }): void {
  state = clone(next);
  changeGeneration += 1;
  mirror();
  notify();
  if (persist) scheduleWrite();
}

export function readUiSession(): UiSessionSnapshotV1 {
  return state;
}

export function updateUiSession(
  update: (current: UiSessionSnapshotV1) => UiSessionSnapshotV1,
): void {
  const next = parseUiSession(update(clone(state)));
  if (!next) throw new TypeError("UI session update violates the v1 contract");
  replaceState(next, { persist: true });
}

export function useUiSession(): UiSessionSnapshotV1 {
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
  ref: UiSessionSnapshotV1["intake_draft_ref"],
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
    const saved = parseUiSession(await api.putUiSession(snapshot));
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
export function resetUiSessionForTests(snapshot: UiSessionSnapshotV1 = defaultUiSession()): void {
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
