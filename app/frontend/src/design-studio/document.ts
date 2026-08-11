/**
 * The persisted, personal Design Studio document.
 *
 * This module is deliberately pure: it knows how to parse and resolve versioned override data,
 * but never reads storage, the DOM, or an API. A v1 scope records where an edit was authored after
 * that edit has already been expanded to stable target ids; it is not a second selector system.
 */
import type { LayoutDocument } from "../layout/document";
import {
  committedDevModeDraft,
  type DevModeDraft,
  type TokenOverrides,
} from "../lib/devModeDraft";
import type { BehaviorOverride } from "../lib/behavior.overrides";
import type { IconOverride } from "../lib/icon.overrides";
import type { Theme } from "../lib/theme";

export const DESIGN_DOCUMENT_SCHEMA_VERSION = 1;

export type DesignScope = "instance" | "role" | "screen" | "global";

/** A sparse layer: omitted values inherit and `null` removes the inherited keyed override. */
export interface DesignPatch {
  tokens?: {
    root?: Record<string, string | null>;
    light?: Record<string, string | null>;
  };
  copy?: Record<string, string | null>;
  icons?: Record<string, IconOverride | null>;
  elements?: Record<string, Record<string, string | null> | null>;
  behaviors?: Record<string, BehaviorOverride | null>;
  /** `null` explicitly returns the resolved layout to the shipped/default arrangement. */
  layout?: LayoutDocument | null;
}

export interface DesignVariation {
  id: string;
  title: string;
  extends?: string;
  patch: DesignPatch;
  themes?: Partial<Record<Theme, DesignPatch>>;
}

export interface DesignDocument {
  schemaVersion: 1;
  base: DevModeDraft;
  variations: Record<string, DesignVariation>;
  activeVariationId: string;
  targetScopes: Record<string, DesignScope>;
}

/** A name for the draft produced by the resolver at the public Design Studio boundary. */
export type ResolvedDesign = DevModeDraft;

export interface DesignDocumentParseError {
  code:
    | "invalid-document"
    | "invalid-schema-version"
    | "unsupported-schema-version"
    | "invalid-base"
    | "invalid-variation"
    | "invalid-variation-theme"
    | "duplicate-variation-id"
    | "missing-variation-parent"
    | "variation-inheritance-cycle"
    | "unknown-active-variation"
    | "invalid-target-scope";
  message: string;
}

export type DesignDocumentParseResult =
  | { ok: true; document: DesignDocument }
  | { ok: false; error: DesignDocumentParseError };

export const BUILT_IN_VARIATIONS = [
  { id: "full-data", title: "Full Data" },
  { id: "compact", title: "Compact" },
  { id: "purchasing", title: "Purchasing" },
  { id: "cad-review", title: "CAD Review" },
  { id: "minimal", title: "Minimal" },
  { id: "custom", title: "Custom" },
] as const;

type UnknownRecord = Record<string, unknown>;

function isRecord(value: unknown): value is UnknownRecord {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function error(code: DesignDocumentParseError["code"], message: string): DesignDocumentParseResult {
  return { ok: false, error: { code, message } };
}

function emptyDraft(): DevModeDraft {
  return {
    tokens: { root: {}, light: {} },
    copy: {},
    icons: {},
    elements: {},
    behaviors: {},
    layout: null,
  };
}

function copyStringMap(value: unknown, nullable: boolean): Record<string, string | null> | null {
  if (!isRecord(value)) return null;
  const out: Record<string, string | null> = {};
  for (const [key, entry] of Object.entries(value)) {
    if (typeof entry !== "string" && (!nullable || entry !== null)) return null;
    out[key] = entry;
  }
  return out;
}

function copyIcon(value: unknown): IconOverride | null {
  if (!isRecord(value)) return null;
  const { body, swapToId } = value;
  if (body !== undefined && typeof body !== "string") return null;
  if (swapToId !== undefined && typeof swapToId !== "string") return null;
  return { ...(body === undefined ? {} : { body }), ...(swapToId === undefined ? {} : { swapToId }) };
}

function copyIcons(value: unknown, nullable: boolean): Record<string, IconOverride | null> | null {
  if (!isRecord(value)) return null;
  const out: Record<string, IconOverride | null> = {};
  for (const [key, entry] of Object.entries(value)) {
    if (entry === null && nullable) {
      out[key] = null;
      continue;
    }
    const icon = copyIcon(entry);
    if (!icon) return null;
    out[key] = icon;
  }
  return out;
}

function copyElements(
  value: unknown,
  nullable: boolean,
): Record<string, Record<string, string | null> | null> | null {
  if (!isRecord(value)) return null;
  const out: Record<string, Record<string, string | null> | null> = {};
  for (const [key, entry] of Object.entries(value)) {
    if (entry === null && nullable) {
      out[key] = null;
      continue;
    }
    const props = copyStringMap(entry, nullable);
    if (!props) return null;
    out[key] = props;
  }
  return out;
}

function copyBehavior(value: unknown): BehaviorOverride | null {
  if (!isRecord(value)) return null;
  const { preset, disabled } = value;
  if (
    preset !== undefined &&
    preset !== "dropdown" &&
    preset !== "segmented" &&
    preset !== "radio" &&
    preset !== "searchable"
  ) return null;
  if (disabled !== undefined && typeof disabled !== "boolean") return null;
  return {
    ...(preset === undefined ? {} : { preset }),
    ...(disabled === undefined ? {} : { disabled }),
  };
}

function copyBehaviors(value: unknown, nullable: boolean): Record<string, BehaviorOverride | null> | null {
  if (!isRecord(value)) return null;
  const out: Record<string, BehaviorOverride | null> = {};
  for (const [key, entry] of Object.entries(value)) {
    if (entry === null && nullable) {
      out[key] = null;
      continue;
    }
    const behavior = copyBehavior(entry);
    if (!behavior) return null;
    out[key] = behavior;
  }
  return out;
}

function copyLayout(value: unknown): LayoutDocument | null | undefined {
  if (value === undefined || value === null) return value;
  return isRecord(value) ? structuredClone(value) as unknown as LayoutDocument : undefined;
}

function parseDraft(value: unknown): DevModeDraft | null {
  if (!isRecord(value)) return null;
  const out = emptyDraft();
  if (value.tokens !== undefined) {
    if (!isRecord(value.tokens)) return null;
    const root = value.tokens.root === undefined ? {} : copyStringMap(value.tokens.root, false);
    const light = value.tokens.light === undefined ? {} : copyStringMap(value.tokens.light, false);
    if (!root || !light) return null;
    out.tokens = { root: root as Record<string, string>, light: light as Record<string, string> };
  }
  if (value.copy !== undefined) {
    const copy = copyStringMap(value.copy, false);
    if (!copy) return null;
    out.copy = copy as Record<string, string>;
  }
  if (value.icons !== undefined) {
    const icons = copyIcons(value.icons, false);
    if (!icons) return null;
    out.icons = icons as Record<string, IconOverride>;
  }
  if (value.elements !== undefined) {
    const elements = copyElements(value.elements, false);
    if (!elements) return null;
    out.elements = elements as Record<string, Record<string, string>>;
  }
  if (value.behaviors !== undefined) {
    const behaviors = copyBehaviors(value.behaviors, false);
    if (!behaviors) return null;
    out.behaviors = behaviors as Record<string, BehaviorOverride>;
  }
  if (value.layout !== undefined) {
    const layout = copyLayout(value.layout);
    if (layout === undefined) return null;
    out.layout = layout;
  }
  return out;
}

function parsePatch(value: unknown): DesignPatch | null {
  if (!isRecord(value)) return null;
  const patch: DesignPatch = {};
  if (value.tokens !== undefined) {
    if (!isRecord(value.tokens)) return null;
    const root = value.tokens.root === undefined ? undefined : copyStringMap(value.tokens.root, true);
    const light = value.tokens.light === undefined ? undefined : copyStringMap(value.tokens.light, true);
    if (root === null || light === null) return null;
    patch.tokens = { ...(root === undefined ? {} : { root }), ...(light === undefined ? {} : { light }) };
  }
  if (value.copy !== undefined) {
    const copy = copyStringMap(value.copy, true);
    if (!copy) return null;
    patch.copy = copy;
  }
  if (value.icons !== undefined) {
    const icons = copyIcons(value.icons, true);
    if (!icons) return null;
    patch.icons = icons;
  }
  if (value.elements !== undefined) {
    const elements = copyElements(value.elements, true);
    if (!elements) return null;
    patch.elements = elements;
  }
  if (value.behaviors !== undefined) {
    const behaviors = copyBehaviors(value.behaviors, true);
    if (!behaviors) return null;
    patch.behaviors = behaviors;
  }
  if (value.layout !== undefined) {
    const layout = copyLayout(value.layout);
    if (layout === undefined) return null;
    patch.layout = layout;
  }
  return patch;
}

function parseVariation(key: string, value: unknown): DesignVariation | null {
  if (!isRecord(value) || value.id !== key || typeof value.title !== "string") return null;
  if (value.extends !== undefined && typeof value.extends !== "string") return null;
  const patch = parsePatch(value.patch);
  if (!patch) return null;
  const themes: Partial<Record<Theme, DesignPatch>> = {};
  if (value.themes !== undefined) {
    if (!isRecord(value.themes)) return null;
    for (const [theme, themePatch] of Object.entries(value.themes)) {
      if (theme !== "dark" && theme !== "light") return null;
      const parsed = parsePatch(themePatch);
      if (!parsed) return null;
      themes[theme] = parsed;
    }
  }
  return {
    id: key,
    title: value.title,
    ...(value.extends === undefined ? {} : { extends: value.extends }),
    patch,
    ...(Object.keys(themes).length === 0 ? {} : { themes }),
  };
}

function validateVariationGraph(variations: Record<string, DesignVariation>): DesignDocumentParseResult | null {
  for (const variation of Object.values(variations)) {
    if (variation.extends && !variations[variation.extends]) {
      return error("missing-variation-parent", `Variation '${variation.id}' extends missing '${variation.extends}'.`);
    }
  }
  const visiting = new Set<string>();
  const visited = new Set<string>();
  const visit = (id: string): string | null => {
    if (visited.has(id)) return null;
    if (visiting.has(id)) return id;
    visiting.add(id);
    const parent = variations[id].extends;
    const loop = parent ? visit(parent) : null;
    visiting.delete(id);
    visited.add(id);
    return loop;
  };
  for (const id of Object.keys(variations)) {
    const loop = visit(id);
    if (loop) return error("variation-inheritance-cycle", `Variation inheritance contains a cycle at '${loop}'.`);
  }
  return null;
}

/** Parse untrusted persisted data, keeping malformed input and version errors as structured data. */
export function parseDesignDocument(value: unknown): DesignDocumentParseResult {
  if (!isRecord(value)) return error("invalid-document", "Design document must be an object.");
  if (typeof value.schemaVersion !== "number") return error("invalid-schema-version", "Design document schemaVersion must be a number.");
  if (value.schemaVersion > DESIGN_DOCUMENT_SCHEMA_VERSION) {
    return error("unsupported-schema-version", `Design document schemaVersion ${value.schemaVersion} is newer than supported.`);
  }
  if (value.schemaVersion !== DESIGN_DOCUMENT_SCHEMA_VERSION) {
    return error("invalid-schema-version", `Design document schemaVersion must be ${DESIGN_DOCUMENT_SCHEMA_VERSION}.`);
  }
  const base = parseDraft(value.base);
  if (!base) return error("invalid-base", "Design document base must contain only valid override slices.");

  const variations: Record<string, DesignVariation> = {};
  if (value.variations !== undefined) {
    if (!isRecord(value.variations)) return error("invalid-variation", "Design document variations must be an object.");
    for (const [key, rawVariation] of Object.entries(value.variations)) {
      const variation = parseVariation(key, rawVariation);
      if (!variation) {
        if (isRecord(rawVariation) && typeof rawVariation.id === "string" && rawVariation.id !== key) {
          return error("duplicate-variation-id", `Variation key '${key}' does not match id '${rawVariation.id}'.`);
        }
        return error("invalid-variation", `Variation '${key}' is malformed.`);
      }
      variations[key] = variation;
    }
  }
  const graphError = validateVariationGraph(variations);
  if (graphError) return graphError;

  const activeVariationId = value.activeVariationId === undefined ? "" : value.activeVariationId;
  if (typeof activeVariationId !== "string") return error("unknown-active-variation", "activeVariationId must be a string.");
  if (activeVariationId && !variations[activeVariationId]) {
    return error("unknown-active-variation", `Active variation '${activeVariationId}' does not exist.`);
  }

  const targetScopes: Record<string, DesignScope> = {};
  if (value.targetScopes !== undefined) {
    if (!isRecord(value.targetScopes)) return error("invalid-target-scope", "targetScopes must be an object.");
    for (const [targetId, scope] of Object.entries(value.targetScopes)) {
      if (scope !== "instance" && scope !== "role" && scope !== "screen" && scope !== "global") {
        return error("invalid-target-scope", `Target '${targetId}' has an invalid design scope.`);
      }
      targetScopes[targetId] = scope;
    }
  }

  return {
    ok: true,
    document: {
      schemaVersion: DESIGN_DOCUMENT_SCHEMA_VERSION,
      base,
      variations,
      activeVariationId,
      targetScopes,
    },
  };
}

function cloneDraft(draft: DevModeDraft): DevModeDraft {
  return {
    tokens: { root: { ...draft.tokens.root }, light: { ...draft.tokens.light } },
    copy: { ...draft.copy },
    icons: Object.fromEntries(Object.entries(draft.icons).map(([id, icon]) => [id, { ...icon }])),
    elements: Object.fromEntries(
      Object.entries(draft.elements).map(([id, props]) => [id, { ...props }]),
    ),
    behaviors: Object.fromEntries(
      Object.entries(draft.behaviors).map(([id, behavior]) => [id, { ...behavior }]),
    ),
    layout: draft.layout ? structuredClone(draft.layout) : null,
  };
}

function applyNullableMap<T>(target: Record<string, T>, patch: Record<string, T | null>): Record<string, T> {
  const next = { ...target };
  for (const [key, value] of Object.entries(patch)) {
    if (value === null) delete next[key];
    else next[key] = value;
  }
  return next;
}

/** Apply one sparse layer without mutating either the existing draft or the persisted patch. */
function applyPatch(draft: DevModeDraft, patch: DesignPatch): DevModeDraft {
  const next = cloneDraft(draft);
  if (patch.tokens) {
    const tokens: TokenOverrides = { ...next.tokens };
    if (patch.tokens.root) tokens.root = applyNullableMap(tokens.root, patch.tokens.root);
    if (patch.tokens.light) tokens.light = applyNullableMap(tokens.light, patch.tokens.light);
    next.tokens = tokens;
  }
  if (patch.copy) next.copy = applyNullableMap(next.copy, patch.copy);
  if (patch.icons) {
    const icons = { ...next.icons };
    for (const [id, override] of Object.entries(patch.icons)) {
      if (override === null) delete icons[id];
      else icons[id] = { ...override };
    }
    next.icons = icons;
  }
  if (patch.elements) {
    const elements = { ...next.elements };
    for (const [id, props] of Object.entries(patch.elements)) {
      if (props === null) {
        delete elements[id];
        continue;
      }
      const merged = applyNullableMap(elements[id] ?? {}, props);
      if (Object.keys(merged).length === 0) delete elements[id];
      else elements[id] = merged;
    }
    next.elements = elements;
  }
  if (patch.behaviors) {
    const behaviors = { ...next.behaviors };
    for (const [id, override] of Object.entries(patch.behaviors)) {
      if (override === null) delete behaviors[id];
      else behaviors[id] = { ...override };
    }
    next.behaviors = behaviors;
  }
  if (patch.layout !== undefined) next.layout = patch.layout ? structuredClone(patch.layout) : null;
  return next;
}

function patchFromDraft(draft: DevModeDraft): DesignPatch {
  return cloneDraft(draft);
}

function variationLineage(variations: Record<string, DesignVariation>, id: string): DesignVariation[] {
  const lineage: DesignVariation[] = [];
  let current: DesignVariation | undefined = variations[id];
  const seen = new Set<string>();
  while (current && !seen.has(current.id)) {
    lineage.unshift(current);
    seen.add(current.id);
    current = current.extends ? variations[current.extends] : undefined;
  }
  return lineage;
}

/**
 * Resolve the immutable draft used by the current viewport.
 *
 * Scope metadata does not participate here: broad scope edits are expanded to target ids before
 * persistence. Parent variation patches apply oldest-first; only the selected variation's theme
 * layer follows its patch.
 */
export function resolveDesign(
  document: DesignDocument,
  variationId: string,
  theme: Theme,
): ResolvedDesign {
  let resolved = applyPatch(committedDevModeDraft(), patchFromDraft(document.base));
  const lineage = variationLineage(document.variations, variationId);
  for (const variation of lineage) resolved = applyPatch(resolved, variation.patch);
  const selected = document.variations[variationId];
  if (selected?.themes?.[theme]) resolved = applyPatch(resolved, selected.themes[theme]);
  return resolved;
}
