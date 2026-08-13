/**
 * The persisted, personal Design Studio document.
 *
 * This module is deliberately pure: it knows how to parse and resolve versioned override data,
 * but never reads storage, the DOM, or an API. V1 scope records are migrated to global target
 * identities because their edits were already expanded to stable ids before persistence.
 */
import {
  REGION_LAYOUT_MODES,
  type AxisSize,
  type AxisSizeOverride,
  type LayoutDocument,
  type LayoutNode,
  type LayoutRegion,
  type LayoutSlot,
  type PiecePlacement,
  type SplitterSpec,
} from "../layout/document";
import {
  committedDevModeDraft,
  type DevModeDraft,
  type TokenOverrides,
} from "../lib/devModeDraft";
import type { BehaviorOverride } from "../lib/behavior.overrides";
import type { IconOverride } from "../lib/icon.overrides";
import type { Theme } from "../lib/theme";

export const DESIGN_DOCUMENT_SCHEMA_VERSION = 2;

export type DesignScope = "instance" | "role" | "screen" | "global";

export interface SymbolPresentationOverride {
  body?: boolean;
  pins?: boolean;
  names?: boolean;
  numbers?: boolean;
  fields?: boolean;
  hiddenPins?: boolean;
  stroke?: string;
  fill?: string;
}

export interface FootprintPresentationOverride {
  pads?: boolean;
  fabrication?: boolean;
  courtyard?: boolean;
  silkscreen?: boolean;
  reference?: boolean;
  value?: boolean;
  models3d?: boolean;
  layerColors?: Record<string, string>;
}

export interface Model3dPresentationOverride {
  models?: boolean;
  board?: boolean;
  axes?: boolean;
  grid?: boolean;
  background?: string;
  tint?: string;
  opacity?: number;
  material?: string;
}

export interface CadPresentationOverride {
  symbol?: SymbolPresentationOverride;
  footprint?: FootprintPresentationOverride;
  model3d?: Model3dPresentationOverride;
}

export interface GlobalTargetIdentity {
  id: string;
  identity: "authored" | "generated";
  label?: string;
}

export interface OrphanedDesignEdit {
  targetId: string;
  lastKnownLabel?: string;
  remapTo?: string;
}

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
  cadPresentation?: Record<string, CadPresentationOverride | null>;
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
  schemaVersion: 2;
  base: DevModeDraft;
  variations: Record<string, DesignVariation>;
  activeVariationId: string;
  globalTargets: Record<string, GlobalTargetIdentity>;
  orphanedEdits: Record<string, OrphanedDesignEdit>;
  cadPresentation: Record<string, CadPresentationOverride>;
}

/** A name for the draft produced by the resolver at the public Design Studio boundary. */
export type ResolvedDesign = DevModeDraft & {
  cadPresentation: Record<string, CadPresentationOverride>;
};

export interface DesignDocumentParseError {
  code:
    | "invalid-document"
    | "invalid-schema-version"
    | "unsupported-schema-version"
    | "invalid-base"
    | "invalid-layout"
    | "invalid-variation"
    | "invalid-variation-theme"
    | "duplicate-variation-id"
    | "missing-variation-parent"
    | "variation-inheritance-cycle"
    | "unknown-active-variation"
    | "invalid-target-scope"
    | "invalid-global-target"
    | "invalid-orphaned-edit"
    | "invalid-cad-presentation";
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

/** Fresh built-in records; callers may edit the returned document without mutating shipped data. */
export function builtInVariationDocument(): Record<string, DesignVariation> {
  return Object.fromEntries(BUILT_IN_VARIATIONS.map(({ id, title }) => [
    id,
    {
      id,
      title,
      ...(id === "full-data"
        ? {}
        : { extends: id === "minimal" ? "compact" : "full-data" }),
      patch: {},
    },
  ]));
}

type UnknownRecord = Record<string, unknown>;

function isRecord(value: unknown): value is UnknownRecord {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function dictionary<T>(): Record<string, T> {
  return Object.create(null) as Record<string, T>;
}

function hasOwn(record: object, key: string): boolean {
  return Object.prototype.hasOwnProperty.call(record, key);
}

function hasOnlyKeys(record: UnknownRecord, allowed: readonly string[]): boolean {
  const keys = new Set(allowed);
  return Object.keys(record).every((key) => keys.has(key));
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
  const out = dictionary<string | null>();
  for (const [key, entry] of Object.entries(value)) {
    if (typeof entry !== "string" && (!nullable || entry !== null)) return null;
    out[key] = entry;
  }
  return out;
}

function copyIcon(value: unknown): IconOverride | null {
  if (!isRecord(value)) return null;
  const { body, swapToId, strokeWidth, treatment, a11yLabel, alignment } = value;
  if (body !== undefined && typeof body !== "string") return null;
  if (swapToId !== undefined && typeof swapToId !== "string") return null;
  if (strokeWidth !== undefined && (typeof strokeWidth !== "number" || !Number.isFinite(strokeWidth))) return null;
  if (treatment !== undefined && treatment !== "line" && treatment !== "solid" && treatment !== "muted") return null;
  if (a11yLabel !== undefined && typeof a11yLabel !== "string") return null;
  if (
    alignment !== undefined &&
    alignment !== "baseline" &&
    alignment !== "middle" &&
    alignment !== "text-top" &&
    alignment !== "text-bottom"
  ) return null;
  return {
    ...(body === undefined ? {} : { body }),
    ...(swapToId === undefined ? {} : { swapToId }),
    ...(strokeWidth === undefined ? {} : { strokeWidth }),
    ...(treatment === undefined ? {} : { treatment }),
    ...(a11yLabel === undefined ? {} : { a11yLabel }),
    ...(alignment === undefined ? {} : { alignment }),
  };
}

function copyIcons(value: unknown, nullable: boolean): Record<string, IconOverride | null> | null {
  if (!isRecord(value)) return null;
  const out = dictionary<IconOverride | null>();
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
  const out = dictionary<Record<string, string | null> | null>();
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
  const out = dictionary<BehaviorOverride | null>();
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

function copyBooleanAndStringFields<T extends object>(
  value: unknown,
  booleanKeys: readonly string[],
  stringKeys: readonly string[],
): T | null {
  if (!isRecord(value) || !hasOnlyKeys(value, [...booleanKeys, ...stringKeys])) return null;
  const out: Record<string, boolean | string> = {};
  for (const key of booleanKeys) {
    const entry = value[key];
    if (entry !== undefined && typeof entry !== "boolean") return null;
    if (entry !== undefined) out[key] = entry;
  }
  for (const key of stringKeys) {
    const entry = value[key];
    if (entry !== undefined && typeof entry !== "string") return null;
    if (entry !== undefined) out[key] = entry;
  }
  return out as T;
}

function copyCadPresentation(value: unknown): CadPresentationOverride | null {
  if (!isRecord(value) || !hasOnlyKeys(value, ["symbol", "footprint", "model3d"])) return null;
  const out: CadPresentationOverride = {};
  if (value.symbol !== undefined) {
    const symbol = copyBooleanAndStringFields<SymbolPresentationOverride>(
      value.symbol,
      ["body", "pins", "names", "numbers", "fields", "hiddenPins"],
      ["stroke", "fill"],
    );
    if (!symbol) return null;
    out.symbol = symbol;
  }
  if (value.footprint !== undefined) {
    if (!isRecord(value.footprint) || !hasOnlyKeys(value.footprint, [
      "pads",
      "fabrication",
      "courtyard",
      "silkscreen",
      "reference",
      "value",
      "models3d",
      "layerColors",
    ])) return null;
    const footprint = copyBooleanAndStringFields<FootprintPresentationOverride>(
      Object.fromEntries(Object.entries(value.footprint).filter(([key]) => key !== "layerColors")),
      ["pads", "fabrication", "courtyard", "silkscreen", "reference", "value", "models3d"],
      [],
    );
    if (!footprint) return null;
    if (value.footprint.layerColors !== undefined) {
      const layerColors = copyStringMap(value.footprint.layerColors, false);
      if (!layerColors || Object.values(layerColors).some((entry) => entry === null)) return null;
      footprint.layerColors = layerColors as Record<string, string>;
    }
    out.footprint = footprint;
  }
  if (value.model3d !== undefined) {
    if (!isRecord(value.model3d) || !hasOnlyKeys(value.model3d, [
      "models",
      "board",
      "axes",
      "grid",
      "background",
      "tint",
      "opacity",
      "material",
    ])) return null;
    const model3d = copyBooleanAndStringFields<Model3dPresentationOverride>(
      Object.fromEntries(Object.entries(value.model3d).filter(([key]) => key !== "opacity")),
      ["models", "board", "axes", "grid"],
      ["background", "tint", "material"],
    );
    if (!model3d) return null;
    if (value.model3d.opacity !== undefined) {
      if (!isFiniteNumber(value.model3d.opacity) || value.model3d.opacity < 0 || value.model3d.opacity > 1) return null;
      model3d.opacity = value.model3d.opacity;
    }
    out.model3d = model3d;
  }
  return out;
}

function copyCadPresentationMap(
  value: unknown,
  nullable: boolean,
): Record<string, CadPresentationOverride | null> | null {
  if (!isRecord(value)) return null;
  const out = dictionary<CadPresentationOverride | null>();
  for (const [targetId, entry] of Object.entries(value)) {
    if (entry === null && nullable) {
      out[targetId] = null;
      continue;
    }
    const parsed = copyCadPresentation(entry);
    if (!parsed) return null;
    out[targetId] = parsed;
  }
  return out;
}

function isFiniteNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

function parseStringRecord(value: unknown): Record<string, string> | null {
  const parsed = copyStringMap(value, false);
  if (!parsed) return null;
  const out = dictionary<string>();
  for (const [key, entry] of Object.entries(parsed)) {
    if (entry === null) return null;
    out[key] = entry;
  }
  return out;
}

function parseAxisSizeOverride(value: unknown): AxisSizeOverride | null {
  if (!isRecord(value)) return null;
  const out: AxisSizeOverride = {};
  for (const key of ["min", "preferred", "fraction"] as const) {
    const entry = value[key];
    if (entry !== undefined && !isFiniteNumber(entry)) return null;
    if (entry !== undefined) out[key] = entry;
  }
  return out;
}

function parseAxisSize(value: unknown): AxisSize | null {
  const base = parseAxisSizeOverride(value);
  if (!base || !isRecord(value)) return null;
  const out: AxisSize = { ...base };
  if (value.grow !== undefined) {
    if (typeof value.grow !== "boolean") return null;
    out.grow = value.grow;
  }
  if (value.when !== undefined) {
    if (!isRecord(value.when)) return null;
    const when = dictionary<AxisSizeOverride>();
    for (const [condition, override] of Object.entries(value.when)) {
      const parsed = parseAxisSizeOverride(override);
      if (!parsed) return null;
      when[condition] = parsed;
    }
    out.when = when;
  }
  return out;
}

function parsePlacementSize(value: unknown): PiecePlacement["size"] | null {
  const base = parseAxisSize(value);
  if (!base || !isRecord(value)) return null;
  const out: NonNullable<PiecePlacement["size"]> = { ...base };
  for (const dimension of ["width", "height"] as const) {
    const entry = value[dimension];
    if (entry !== undefined && !isFiniteNumber(entry)) return null;
    if (entry !== undefined) out[dimension] = entry;
  }
  return out;
}

function positiveLayoutInteger(value: unknown): value is number {
  return isFiniteNumber(value) && Number.isInteger(value) && value >= 1 && value <= 1000;
}

function parseSplitter(value: unknown): SplitterSpec | null {
  if (!isRecord(value) || typeof value.id !== "string" || !Array.isArray(value.between)) return null;
  const [before, after] = value.between;
  if (value.between.length !== 2 || typeof before !== "string" || typeof after !== "string") return null;
  if (!isFiniteNumber(value.keyStep) || !isFiniteNumber(value.lineThickness) || !isFiniteNumber(value.grabWidth)) return null;
  if (value.persistenceKey !== undefined && typeof value.persistenceKey !== "string") return null;
  return {
    id: value.id,
    between: [before, after],
    keyStep: value.keyStep,
    lineThickness: value.lineThickness,
    grabWidth: value.grabWidth,
    ...(value.persistenceKey === undefined ? {} : { persistenceKey: value.persistenceKey }),
  };
}

function isRegionLayoutMode(value: unknown): value is LayoutRegion["mode"] {
  return REGION_LAYOUT_MODES.some((mode) => mode === value);
}

function parseLayoutRegion(value: unknown, ancestors: WeakSet<object>): LayoutRegion | null {
  if (!isRecord(value) || ancestors.has(value)) return null;
  const mode = value.mode;
  if (value.kind !== "region" || typeof value.id !== "string" || !isRegionLayoutMode(mode)) return null;
  if (!Array.isArray(value.slots)) return null;
  ancestors.add(value);
  const slots: LayoutSlot[] = [];
  for (const rawSlot of value.slots) {
    const slot = parseLayoutSlot(rawSlot, ancestors);
    if (!slot) {
      ancestors.delete(value);
      return null;
    }
    slots.push(slot);
  }
  ancestors.delete(value);
  const out: LayoutRegion = { kind: "region", id: value.id, mode, slots };
  if (value.devId !== undefined) {
    if (typeof value.devId !== "string") return null;
    out.devId = value.devId;
  }
  if (value.size !== undefined) {
    const size = parseAxisSize(value.size);
    if (!size) return null;
    out.size = size;
  }
  if (value.scroll !== undefined) {
    if (value.scroll !== "vertical" && value.scroll !== "horizontal" && value.scroll !== "both") return null;
    out.scroll = value.scroll;
  }
  if (value.splitters !== undefined) {
    if (!Array.isArray(value.splitters)) return null;
    const splitters: SplitterSpec[] = [];
    for (const rawSplitter of value.splitters) {
      const splitter = parseSplitter(rawSplitter);
      if (!splitter) return null;
      splitters.push(splitter);
    }
    out.splitters = splitters;
  }
  if (value.positioning !== undefined) {
    if (value.positioning !== "free") return null;
    out.positioning = "free";
  }
  if (value.grid !== undefined) {
    if (!isRecord(value.grid) || !positiveLayoutInteger(value.grid.columns)) return null;
    if (value.grid.rows !== undefined && !positiveLayoutInteger(value.grid.rows)) return null;
    out.grid = {
      columns: value.grid.columns,
      ...(value.grid.rows === undefined ? {} : { rows: value.grid.rows }),
    };
  }
  return out;
}

function parseLayoutSlot(value: unknown, ancestors: WeakSet<object>): LayoutSlot | null {
  if (!isRecord(value) || ancestors.has(value) || value.kind !== "slot" || typeof value.id !== "string") return null;
  if (value.content === null) return { kind: "slot", id: value.id, content: null };
  ancestors.add(value);
  const content = parseLayoutNode(value.content, ancestors);
  ancestors.delete(value);
  return content ? { kind: "slot", id: value.id, content } : null;
}

function parseLayoutPlacement(value: unknown): PiecePlacement | null {
  if (!isRecord(value) || value.kind !== "placement" || typeof value.id !== "string" || typeof value.piece !== "string") return null;
  const out: PiecePlacement = { kind: "placement", id: value.id, piece: value.piece };
  if (value.collapsed !== undefined && typeof value.collapsed !== "boolean") return null;
  if (value.collapsed !== undefined) out.collapsed = value.collapsed;
  if (value.hidden !== undefined && typeof value.hidden !== "boolean") return null;
  if (value.hidden !== undefined) out.hidden = value.hidden;
  if (value.size !== undefined) {
    const size = parsePlacementSize(value.size);
    if (!size) return null;
    out.size = size;
  }
  if (value.position !== undefined) {
    if (
      !isRecord(value.position) ||
      !isFiniteNumber(value.position.x) ||
      !isFiniteNumber(value.position.y)
    ) return null;
    out.position = { x: value.position.x, y: value.position.y };
  }
  if (value.gridSlot !== undefined) {
    if (
      !isRecord(value.gridSlot) ||
      !positiveLayoutInteger(value.gridSlot.column) ||
      !positiveLayoutInteger(value.gridSlot.row)
    ) return null;
    out.gridSlot = { column: value.gridSlot.column, row: value.gridSlot.row };
  }
  if (value.styleRoles !== undefined) {
    const styleRoles = parseStringRecord(value.styleRoles);
    if (!styleRoles) return null;
    out.styleRoles = styleRoles;
  }
  if (value.params !== undefined) {
    if (!isRecord(value.params)) return null;
    const params = dictionary<string | number | boolean>();
    for (const [key, param] of Object.entries(value.params)) {
      if (typeof param !== "string" && typeof param !== "number" && typeof param !== "boolean") return null;
      params[key] = param;
    }
    out.params = params;
  }
  if (value.visibility !== undefined) {
    if (
      !isRecord(value.visibility) ||
      !Array.isArray(value.visibility.anyOf) ||
      value.visibility.anyOf.length === 0 ||
      value.visibility.anyOf.length > 100
    ) return null;
    const anyOf: string[] = [];
    for (const id of value.visibility.anyOf) {
      if (typeof id !== "string") return null;
      anyOf.push(id);
    }
    out.visibility = { anyOf };
  }
  if (value.repeat !== undefined) {
    if (!isRecord(value.repeat) || typeof value.repeat.over !== "string") return null;
    out.repeat = { over: value.repeat.over };
  }
  return out;
}

function parseLayoutNode(value: unknown, ancestors: WeakSet<object>): LayoutNode | null {
  if (!isRecord(value)) return null;
  if (value.kind === "region") return parseLayoutRegion(value, ancestors);
  if (value.kind === "placement") return parseLayoutPlacement(value);
  return null;
}

function parseLayoutDocument(value: unknown): LayoutDocument | null {
  if (!isRecord(value) || !isFiniteNumber(value.schemaVersion) || typeof value.id !== "string") return null;
  const root = parseLayoutRegion(value.root, new WeakSet<object>());
  return root ? { schemaVersion: value.schemaVersion, id: value.id, root } : null;
}

function copyLayout(value: unknown): LayoutDocument | null | undefined {
  if (value === undefined || value === null) return value;
  return parseLayoutDocument(value) ?? undefined;
}

function hasMalformedLayout(value: unknown): boolean {
  return value !== undefined && value !== null && parseLayoutDocument(value) === null;
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
  if (value.cadPresentation !== undefined) {
    const cadPresentation = copyCadPresentationMap(value.cadPresentation, true);
    if (!cadPresentation) return null;
    patch.cadPresentation = cadPresentation;
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
    if (variation.extends && !hasOwn(variations, variation.extends)) {
      return error("missing-variation-parent", `Variation '${variation.id}' extends missing '${variation.extends}'.`);
    }
  }
  const visiting = new Set<string>();
  const visited = new Set<string>();
  const visit = (id: string): string | null => {
    if (visited.has(id)) return null;
    if (visiting.has(id)) return id;
    visiting.add(id);
    const parent = variations[id]?.extends;
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

function parseGlobalTargets(value: unknown): Record<string, GlobalTargetIdentity> | null {
  if (value === undefined) return dictionary<GlobalTargetIdentity>();
  if (!isRecord(value)) return null;
  const out = dictionary<GlobalTargetIdentity>();
  for (const [targetId, raw] of Object.entries(value)) {
    if (
      !isRecord(raw)
      || !hasOnlyKeys(raw, ["id", "identity", "label"])
      || raw.id !== targetId
      || (raw.identity !== "authored" && raw.identity !== "generated")
      || (raw.label !== undefined && typeof raw.label !== "string")
    ) return null;
    out[targetId] = {
      id: targetId,
      identity: raw.identity,
      ...(raw.label === undefined ? {} : { label: raw.label }),
    };
  }
  return out;
}

function parseOrphanedEdits(value: unknown): Record<string, OrphanedDesignEdit> | null {
  if (value === undefined) return dictionary<OrphanedDesignEdit>();
  if (!isRecord(value)) return null;
  const out = dictionary<OrphanedDesignEdit>();
  for (const [targetId, raw] of Object.entries(value)) {
    if (
      !isRecord(raw)
      || !hasOnlyKeys(raw, ["targetId", "lastKnownLabel", "remapTo"])
      || raw.targetId !== targetId
      || (raw.lastKnownLabel !== undefined && typeof raw.lastKnownLabel !== "string")
      || (raw.remapTo !== undefined && typeof raw.remapTo !== "string")
    ) return null;
    out[targetId] = {
      targetId,
      ...(raw.lastKnownLabel === undefined ? {} : { lastKnownLabel: raw.lastKnownLabel }),
      ...(raw.remapTo === undefined ? {} : { remapTo: raw.remapTo }),
    };
  }
  return out;
}

function patchTargetIds(patch: DesignPatch): string[] {
  return [
    ...Object.keys(patch.elements ?? {}),
    ...Object.keys(patch.behaviors ?? {}),
    ...Object.keys(patch.cadPresentation ?? {}),
  ];
}

function globalTargetId(id: string): string {
  return id.endsWith("::text") || id.endsWith("::icon")
    ? id.slice(0, id.lastIndexOf("::"))
    : id;
}

function migratedGlobalTargets(
  base: DevModeDraft,
  variations: Record<string, DesignVariation>,
  cadPresentation: Record<string, CadPresentationOverride>,
  targetScopes: Record<string, DesignScope>,
): Record<string, GlobalTargetIdentity> {
  const ids = new Set([
    ...Object.keys(base.elements),
    ...Object.keys(base.behaviors),
    ...Object.keys(cadPresentation),
    ...Object.keys(targetScopes),
  ]);
  for (const variation of Object.values(variations)) {
    for (const id of patchTargetIds(variation.patch)) ids.add(id);
    for (const themePatch of Object.values(variation.themes ?? {})) {
      if (!themePatch) continue;
      for (const id of patchTargetIds(themePatch)) ids.add(id);
    }
  }
  return Object.fromEntries(Array.from(ids, globalTargetId).sort().map((id) => [
    id,
    {
      id,
      identity: id.startsWith("auto.") ? "generated" : "authored",
    } satisfies GlobalTargetIdentity,
  ]));
}

/** Parse untrusted persisted data, keeping malformed input and version errors as structured data. */
export function parseDesignDocument(value: unknown): DesignDocumentParseResult {
  if (!isRecord(value)) return error("invalid-document", "Design document must be an object.");
  if (typeof value.schemaVersion !== "number") return error("invalid-schema-version", "Design document schemaVersion must be a number.");
  if (value.schemaVersion > DESIGN_DOCUMENT_SCHEMA_VERSION) {
    return error("unsupported-schema-version", `Design document schemaVersion ${value.schemaVersion} is newer than supported.`);
  }
  if (value.schemaVersion !== 1 && value.schemaVersion !== DESIGN_DOCUMENT_SCHEMA_VERSION) {
    return error("invalid-schema-version", "Design document schemaVersion must be 1 or 2.");
  }
  const sourceVersion = value.schemaVersion;
  if (isRecord(value.base) && hasMalformedLayout(value.base.layout)) {
    return error("invalid-layout", "Design document base layout is malformed.");
  }
  const base = parseDraft(value.base);
  if (!base) return error("invalid-base", "Design document base must contain only valid override slices.");

  const variations = dictionary<DesignVariation>();
  Object.assign(variations, builtInVariationDocument());
  if (value.variations !== undefined) {
    if (!isRecord(value.variations)) return error("invalid-variation", "Design document variations must be an object.");
    for (const [key, rawVariation] of Object.entries(value.variations)) {
      if (
        isRecord(rawVariation) &&
        ((isRecord(rawVariation.patch) && hasMalformedLayout(rawVariation.patch.layout)) ||
          (isRecord(rawVariation.themes) &&
            Object.values(rawVariation.themes).some(
              (themePatch) => isRecord(themePatch) && hasMalformedLayout(themePatch.layout),
            )))
      ) {
        return error("invalid-layout", `Variation '${key}' contains a malformed layout.`);
      }
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
  if (activeVariationId && !hasOwn(variations, activeVariationId)) {
    return error("unknown-active-variation", `Active variation '${activeVariationId}' does not exist.`);
  }

  const targetScopes = dictionary<DesignScope>();
  if (value.targetScopes !== undefined) {
    if (sourceVersion !== 1) {
      return error("invalid-target-scope", "Design document v2 does not accept targetScopes.");
    }
    if (!isRecord(value.targetScopes)) return error("invalid-target-scope", "targetScopes must be an object.");
    for (const [targetId, scope] of Object.entries(value.targetScopes)) {
      if (scope !== "instance" && scope !== "role" && scope !== "screen" && scope !== "global") {
        return error("invalid-target-scope", `Target '${targetId}' has an invalid design scope.`);
      }
      targetScopes[targetId] = scope;
    }
  }
  const parsedCadPresentation = value.cadPresentation === undefined
    ? dictionary<CadPresentationOverride | null>()
    : copyCadPresentationMap(value.cadPresentation, false);
  if (!parsedCadPresentation || Object.values(parsedCadPresentation).some((entry) => entry === null)) {
    return error("invalid-cad-presentation", "cadPresentation must contain valid typed CAD presentation overrides.");
  }
  const cadPresentation = parsedCadPresentation as Record<string, CadPresentationOverride>;
  const inferredTargets = migratedGlobalTargets(base, variations, cadPresentation, targetScopes);
  const parsedTargets = sourceVersion === 1
    ? dictionary<GlobalTargetIdentity>()
    : parseGlobalTargets(value.globalTargets);
  if (!parsedTargets) {
    return error("invalid-global-target", "globalTargets must contain valid global target identities.");
  }
  for (const target of Object.values(parsedTargets)) {
    const expected = target.id.startsWith("auto.") ? "generated" : "authored";
    if (target.identity !== expected) {
      return error("invalid-global-target", `Global target '${target.id}' has the wrong identity kind.`);
    }
  }
  const orphanedEdits = sourceVersion === 1
    ? dictionary<OrphanedDesignEdit>()
    : parseOrphanedEdits(value.orphanedEdits);
  if (!orphanedEdits) {
    return error("invalid-orphaned-edit", "orphanedEdits must contain valid remapping metadata.");
  }

  return {
    ok: true,
    document: {
      schemaVersion: DESIGN_DOCUMENT_SCHEMA_VERSION,
      base,
      variations,
      activeVariationId,
      globalTargets: { ...inferredTargets, ...parsedTargets },
      orphanedEdits,
      cadPresentation,
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

function cloneCadPresentation(
  overrides: Record<string, CadPresentationOverride>,
): Record<string, CadPresentationOverride> {
  return structuredClone(overrides);
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
function applyPatch(draft: ResolvedDesign, patch: DesignPatch): ResolvedDesign {
  const next: ResolvedDesign = {
    ...cloneDraft(draft),
    cadPresentation: cloneCadPresentation(draft.cadPresentation),
  };
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
  if (patch.cadPresentation) {
    const cadPresentation = { ...next.cadPresentation };
    for (const [id, override] of Object.entries(patch.cadPresentation)) {
      if (override === null) delete cadPresentation[id];
      else cadPresentation[id] = structuredClone(override);
    }
    next.cadPresentation = cadPresentation;
  }
  if (patch.layout !== undefined) next.layout = patch.layout ? structuredClone(patch.layout) : null;
  return next;
}

function patchFromDraft(draft: DevModeDraft): DesignPatch {
  return cloneDraft(draft);
}

function diffNullableMap<T>(
  baseline: Record<string, T>,
  target: Record<string, T>,
): Record<string, T | null> | undefined {
  const patch: Record<string, T | null> = {};
  for (const key of new Set([...Object.keys(baseline), ...Object.keys(target)])) {
    if (!hasOwn(target, key)) patch[key] = null;
    else if (!hasOwn(baseline, key) || JSON.stringify(baseline[key]) !== JSON.stringify(target[key])) {
      patch[key] = target[key];
    }
  }
  return Object.keys(patch).length > 0 ? patch : undefined;
}

/** Produce the sparse, deletion-aware patch which resolves `baseline` to exactly `target`. */
export function diffDesignDraft(baseline: DevModeDraft, target: DevModeDraft): DesignPatch {
  const patch: DesignPatch = {};
  const root = diffNullableMap(baseline.tokens.root, target.tokens.root);
  const light = diffNullableMap(baseline.tokens.light, target.tokens.light);
  if (root || light) patch.tokens = { ...(root ? { root } : {}), ...(light ? { light } : {}) };
  patch.copy = diffNullableMap(baseline.copy, target.copy);
  patch.icons = diffNullableMap(baseline.icons, target.icons);
  patch.behaviors = diffNullableMap(baseline.behaviors, target.behaviors);
  const elementPatch: NonNullable<DesignPatch["elements"]> = {};
  for (const id of new Set([...Object.keys(baseline.elements), ...Object.keys(target.elements)])) {
    if (!hasOwn(target.elements, id)) {
      elementPatch[id] = null;
      continue;
    }
    const props = diffNullableMap(baseline.elements[id] ?? {}, target.elements[id]);
    if (props) elementPatch[id] = props;
  }
  if (Object.keys(elementPatch).length > 0) patch.elements = elementPatch;
  if (JSON.stringify(baseline.layout) !== JSON.stringify(target.layout)) {
    patch.layout = target.layout ? structuredClone(target.layout) : null;
  }
  return patch;
}

function variationLineage(variations: Record<string, DesignVariation>, id: string): DesignVariation[] {
  const lineage: DesignVariation[] = [];
  let current: DesignVariation | undefined = hasOwn(variations, id) ? variations[id] : undefined;
  const seen = new Set<string>();
  while (current && !seen.has(current.id)) {
    lineage.unshift(current);
    seen.add(current.id);
    current = current.extends && hasOwn(variations, current.extends)
      ? variations[current.extends]
      : undefined;
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
  let resolved: ResolvedDesign = {
    ...cloneDraft(committedDevModeDraft()),
    cadPresentation: cloneCadPresentation(document.cadPresentation),
  };
  resolved = applyPatch(resolved, patchFromDraft(document.base));
  const lineage = variationLineage(document.variations, variationId);
  for (const variation of lineage) resolved = applyPatch(resolved, variation.patch);
  const selected = hasOwn(document.variations, variationId)
    ? document.variations[variationId]
    : undefined;
  if (selected?.themes?.[theme]) resolved = applyPatch(resolved, selected.themes[theme]);
  return resolved;
}
