const GENERATED_DESIGN_ID = /^auto\.[a-z0-9-]+\.[a-z0-9]{7}$/;
const OCCURRENCE_DESIGN_ID = /^auto\.occurrence\.[a-z0-9]{7}$/;

export const DESIGN_TARGET_SELECTOR = "[data-dev-id],[data-design-id]";
export const DESIGN_OCCURRENCE_ATTRIBUTE = "data-design-occurrence-id";

export interface ExactDesignTargetAuthority {
  /** Semantic source/call-site identity shown to the owner. */
  id: string;
  /** Concrete override address; duplicate live occurrences never share it. */
  overrideId: string;
  /** Locator reserved at selection time, before a later duplicate can make the semantic id unsafe. */
  occurrenceId: string;
  /** True when a semantic override was originally proven to address only this live element. */
  semanticBinding: boolean;
  /** The exact clicked DOM occurrence. It remains authoritative only while connected. */
  element: Element;
  /** Live product/mount boundary that owns transient semantic-binding safety state. */
  bindingScope: Element | Document;
}

const ROOT_PROTECTED_PROPERTIES = new Set([
  "display", "visibility", "opacity", "filter", "content-visibility", "clip-path",
  "pointer-events", "position", "inset", "top", "right", "bottom", "left",
  "width", "height", "min-width", "min-height", "max-width", "max-height",
  "margin", "margin-top", "margin-right", "margin-bottom", "margin-left",
  "padding", "padding-top", "padding-right", "padding-bottom", "padding-left",
  "gap", "row-gap", "column-gap", "overflow", "overflow-x", "overflow-y",
  "transform", "translate", "rotate", "scale", "z-index", "order",
  "grid-column", "grid-row", "grid-template-columns", "grid-template-rows",
  "grid-template-areas", "grid-auto-flow", "flex", "flex-grow", "flex-shrink",
  "flex-basis", "flex-direction", "flex-wrap", "justify-content", "justify-items",
  "justify-self", "align-items", "align-content", "align-self", "place-content",
  "place-items", "place-self",
]);

interface ExactSemanticBinding {
  element: Element;
  occurrenceId: string;
  ambiguous: boolean;
}

const exactSemanticTargets = new Map<string, WeakMap<Element | Document, ExactSemanticBinding | null>>();

function designBindingScope(element: Element): Element | Document {
  const productRoot = element.closest("[data-design-product-root]");
  if (productRoot) return productRoot;
  if (!element.isConnected) {
    let root = element;
    while (root.parentElement) root = root.parentElement;
    return root;
  }
  const body = element.ownerDocument.body;
  let root = element;
  while (root.parentElement && root.parentElement !== body) root = root.parentElement;
  return root.parentElement === body ? root : element.ownerDocument;
}

function semanticBindingsFor(id: string): WeakMap<Element | Document, ExactSemanticBinding | null> {
  const existing = exactSemanticTargets.get(id);
  if (existing) return existing;
  const created = new WeakMap<Element | Document, ExactSemanticBinding | null>();
  exactSemanticTargets.set(id, created);
  return created;
}

function slug(value: string): string {
  return value
    .replace(/([a-z0-9])([A-Z])/g, "$1-$2")
    .replace(/[^A-Za-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .toLowerCase() || "element";
}

function fnv1a(value: string): string {
  let hash = 0x811c9dc5;
  for (let index = 0; index < value.length; index += 1) {
    hash ^= value.charCodeAt(index);
    hash = Math.imul(hash, 0x01000193) >>> 0;
  }
  return hash.toString(36).padStart(7, "0").slice(-7);
}

export function runtimeDesignId(owner: string, semanticKey: string): string {
  return `auto.${slug(owner)}.${fnv1a(`runtime|${owner}|${semanticKey}`)}`;
}

export function assignDesignIdentity<T extends Element>(
  element: T,
  owner: string,
  semanticKey: string,
): T {
  if (!element.hasAttribute("data-dev-id") && !element.hasAttribute("data-design-id")) {
    element.setAttribute("data-design-id", runtimeDesignId(owner, semanticKey));
  }
  return element;
}

export function isGeneratedDesignId(value: string): boolean {
  return GENERATED_DESIGN_ID.test(value);
}

export function isOccurrenceDesignId(value: string): boolean {
  return OCCURRENCE_DESIGN_ID.test(value);
}

export function isProtectedDesignRoot(element: Element): boolean {
  return element.hasAttribute("data-design-product-root")
    || element.getAttribute("data-dev-id") === "shell.root";
}

export function isRootProtectedDesignProperty(element: Element, property: string): boolean {
  return isProtectedDesignRoot(element) && ROOT_PROTECTED_PROPERTIES.has(property.trim().toLowerCase());
}

export function designIdOf(element: Element): string | null {
  return element.getAttribute("data-dev-id") ?? element.getAttribute("data-design-id");
}

export function designIdSelector(id: string): string {
  const attribute = isGeneratedDesignId(id) ? "data-design-id" : "data-dev-id";
  if (typeof CSS !== "undefined" && typeof CSS.escape === "function") {
    return `[${attribute}=${CSS.escape(id)}]`;
  }
  return `[${attribute}="${id.replace(/["\\]/g, "\\$&")}"]`;
}

export function designOverrideSelector(id: string): string {
  if (!isOccurrenceDesignId(id)) return designIdSelector(id);
  if (typeof CSS !== "undefined" && typeof CSS.escape === "function") {
    return `[${DESIGN_OCCURRENCE_ATTRIBUTE}=${CSS.escape(id)}]`;
  }
  return `[${DESIGN_OCCURRENCE_ATTRIBUTE}="${id.replace(/["\\]/g, "\\$&")}"]`;
}

/**
 * A semantic override may be durable while its id is unique. If later DOM growth makes that id
 * ambiguous, retain its original exact live binding or apply it nowhere; never broaden to peers.
 */
export function narrowDesignOverrideTargets(id: string, candidates: readonly Element[]): Element[] {
  const bindings = exactSemanticTargets.get(id);
  if (!bindings) return candidates.length <= 1 ? [...candidates] : [];
  const scopes = [...new Set(candidates.map(designBindingScope))];
  const recorded = scopes.filter((scope) => bindings.has(scope));
  if (recorded.length === 0) return candidates.length <= 1 ? [...candidates] : [];
  if (recorded.length !== 1) return [];
  const bound = bindings.get(recorded[0]);
  if (!bound) return [];
  if (candidates.length > 1) bound.ambiguous = true;
  if (bound.element.isConnected && candidates.includes(bound.element)) return [bound.element];
  if (candidates.length === 1) {
    if (bound.ambiguous) return [];
    const occurrenceId = occurrenceIdFor(candidates[0]);
    if (!occurrenceId) return [];
    bound.element = candidates[0];
    bound.occurrenceId = occurrenceId;
    return [candidates[0]];
  }
  const replacements = candidates.filter(
    (candidate) => occurrenceIdFor(candidate) === bound.occurrenceId,
  );
  if (replacements.length !== 1) return [];
  bound.element = replacements[0];
  return replacements;
}

const OCCURRENCE_PATH_ATTRIBUTES = [
  "data-dev-id",
  "data-copy-id",
  "data-icon-id",
  "data-layout-piece",
  "data-design-key",
  "data-spec-key",
  "data-quality-segment",
  "data-spec-filter",
  "data-spec-anchor",
  "data-splitter",
  "data-spec-section",
  "data-sourcing-provider",
  "data-offer-provider",
  "data-provider",
  "data-document-type",
  "data-document-preferred",
  "data-conflict-field",
  "data-testid",
  "id",
] as const;

function occurrencePathSegment(element: Element): string | null {
  const identities = OCCURRENCE_PATH_ATTRIBUTES.flatMap((attribute) => {
    const value = element.getAttribute(attribute)?.trim();
    return value ? [`${attribute}=${JSON.stringify(value)}`] : [];
  });
  return identities.length > 0 ? `${element.localName}[${identities.join("|")}]` : null;
}

/** A locator contains semantic identities only: DOM order and editable visible copy are excluded. */
function occurrencePathFor(element: Element): string {
  const segments: string[] = [];
  let current: Element | null = element;
  while (current) {
    const segment = occurrencePathSegment(current);
    if (segment) segments.unshift(segment);
    current = current.parentElement;
  }
  return segments.join(">");
}

function inclusiveDesignTargets(root: ParentNode): Element[] {
  return root instanceof Element
    ? [
        ...(root.matches(DESIGN_TARGET_SELECTOR) ? [root] : []),
        ...Array.from(root.querySelectorAll(DESIGN_TARGET_SELECTOR)),
      ]
    : Array.from(root.querySelectorAll(DESIGN_TARGET_SELECTOR));
}

/** Resolve every live target once. Layers and bulk actions must not rescan the document per row. */
export function designOverrideIdsFor(root: ParentNode): Map<Element, string | null> {
  ensureDesignOccurrenceIdentities(root);
  const scope = durableOccurrenceScope(root);
  const scopedTargets = inclusiveDesignTargets(scope)
    .filter((element) => !element.closest("[data-design-studio-chrome]"));
  const semanticCounts = new Map<string, number>();
  for (const element of scopedTargets) {
    const id = designIdOf(element);
    if (id) semanticCounts.set(id, (semanticCounts.get(id) ?? 0) + 1);
  }
  const requested = inclusiveDesignTargets(root)
    .filter((element) => !element.closest("[data-design-studio-chrome]"));
  return new Map(requested.map((element) => {
    const id = designIdOf(element);
    if (!id) return [element, null];
    if (semanticCounts.get(id) === 1) return [element, id];
    const occurrenceId = element.getAttribute(DESIGN_OCCURRENCE_ATTRIBUTE);
    return [element, occurrenceId && isOccurrenceDesignId(occurrenceId) ? occurrenceId : null];
  }));
}

function durableOccurrenceScope(root: ParentNode): ParentNode {
  if (root instanceof Document) return root;
  if (root instanceof Element && root.isConnected) return root.ownerDocument;
  return root;
}

function occurrenceScopeForElement(element: Element): ParentNode {
  if (element.isConnected) return element.ownerDocument;
  let root = element;
  while (root.parentElement) root = root.parentElement;
  return root;
}

/**
 * Recreate every concrete occurrence address from a stable semantic ancestor path. If two live
 * elements have the same path, neither receives an address: order cannot silently become identity.
 */
export function ensureDesignOccurrenceIdentities(root: ParentNode): void {
  const scope = durableOccurrenceScope(root);
  const candidates = inclusiveDesignTargets(scope)
    .filter((element) => !element.closest("[data-design-studio-chrome]"))
    .map((element) => {
      const semanticId = designIdOf(element);
      if (!semanticId) return null;
      const locator = `${semanticId}|${occurrencePathFor(element)}`;
      return {
        element,
        semanticId,
        locator,
        occurrenceId: runtimeDesignId("occurrence", locator),
      };
    })
    .filter((candidate): candidate is NonNullable<typeof candidate> => candidate !== null);
  const locatorCounts = new Map<string, number>();
  const idCounts = new Map<string, number>();
  const semanticCounts = new Map<string, number>();
  for (const candidate of candidates) {
    locatorCounts.set(candidate.locator, (locatorCounts.get(candidate.locator) ?? 0) + 1);
    idCounts.set(candidate.occurrenceId, (idCounts.get(candidate.occurrenceId) ?? 0) + 1);
    semanticCounts.set(candidate.semanticId, (semanticCounts.get(candidate.semanticId) ?? 0) + 1);
  }
  for (const candidate of candidates) {
    const unambiguous = locatorCounts.get(candidate.locator) === 1
      && idCounts.get(candidate.occurrenceId) === 1;
    if (unambiguous && (semanticCounts.get(candidate.semanticId) ?? 0) > 1) {
      candidate.element.setAttribute(DESIGN_OCCURRENCE_ATTRIBUTE, candidate.occurrenceId);
    } else {
      candidate.element.removeAttribute(DESIGN_OCCURRENCE_ATTRIBUTE);
    }
  }
}

function occurrenceIdFor(element: Element): string | null {
  const scope = occurrenceScopeForElement(element);
  ensureDesignOccurrenceIdentities(scope);
  const id = element.getAttribute(DESIGN_OCCURRENCE_ATTRIBUTE);
  if (id && isOccurrenceDesignId(id)) {
    const matches = inclusiveDesignTargets(scope).filter(
      (candidate) => candidate.getAttribute(DESIGN_OCCURRENCE_ATTRIBUTE) === id,
    );
    return matches.length === 1 && matches[0] === element ? id : null;
  }
  const semanticId = designIdOf(element);
  if (!semanticId) return null;
  const semanticMatches = inclusiveDesignTargets(scope).filter(
    (candidate) => designIdOf(candidate) === semanticId,
  );
  if (semanticMatches.length !== 1 || semanticMatches[0] !== element) return null;
  const occurrenceId = runtimeDesignId("occurrence", `${semanticId}|${occurrencePathFor(element)}`);
  const collisionCount = inclusiveDesignTargets(scope).filter((candidate) => {
    const candidateId = designIdOf(candidate);
    return candidateId
      ? runtimeDesignId("occurrence", `${candidateId}|${occurrencePathFor(candidate)}`) === occurrenceId
      : false;
  }).length;
  return collisionCount === 1 ? occurrenceId : null;
}

/**
 * Bind an inspector selection to one live element. A semantic id is sufficient only while it has
 * one live occurrence; duplicates receive a deterministic semantic-path address so saved writes
 * survive a remount. Structurally ambiguous duplicates return no authority instead of using order.
 */
export function exactDesignTargetAuthority(element: Element | null): ExactDesignTargetAuthority | null {
  if (!element) return null;
  const id = designIdOf(element);
  if (!id) return null;
  const scope = occurrenceScopeForElement(element);
  const occurrences = inclusiveDesignTargets(scope).filter((candidate) => designIdOf(candidate) === id);
  const occurrenceId = occurrenceIdFor(element);
  if (!occurrenceId) return null;
  const semanticBinding = occurrences.length === 1 && occurrences[0] === element;
  const bindingScope = designBindingScope(element);
  if (semanticBinding) semanticBindingsFor(id).set(bindingScope, {
    element,
    occurrenceId,
    ambiguous: false,
  });
  return {
    id,
    overrideId: semanticBinding ? id : occurrenceId,
    occurrenceId,
    semanticBinding,
    element,
    bindingScope,
  };
}

/** Upgrade a still-connected formerly unique target as soon as its semantic id becomes ambiguous. */
export function upgradeExactDesignTargetAuthority(
  authority: ExactDesignTargetAuthority,
): ExactDesignTargetAuthority | null {
  if (!authority.element.isConnected) return authority;
  ensureDesignOccurrenceIdentities(authority.element.ownerDocument);
  if (authority.overrideId !== authority.id) {
    return authority.element.getAttribute(DESIGN_OCCURRENCE_ATTRIBUTE) === authority.occurrenceId
      ? authority
      : null;
  }
  const matches = Array.from(authority.element.ownerDocument.querySelectorAll(designIdSelector(authority.id)))
    .filter((element) => !element.closest("[data-design-studio-chrome]"));
  if (matches.length <= 1) return authority;
  if (authority.element.getAttribute(DESIGN_OCCURRENCE_ATTRIBUTE) !== authority.occurrenceId) return null;
  semanticBindingsFor(authority.id).set(authority.bindingScope, null);
  return { ...authority, overrideId: authority.occurrenceId };
}

/** Transfer an exact locator only after one replacement with the same semantic id is proven. */
export function rebindExactDesignTargetAuthority(
  authority: ExactDesignTargetAuthority,
  replacement: Element,
): ExactDesignTargetAuthority | null {
  if (designIdOf(replacement) !== authority.id) return null;
  ensureDesignOccurrenceIdentities(replacement.ownerDocument);
  const replacementOccurrenceId = occurrenceIdFor(replacement);
  if (!replacementOccurrenceId) return null;
  if (authority.semanticBinding) {
    const matches = Array.from(replacement.ownerDocument.querySelectorAll(designIdSelector(authority.id)))
      .filter((element) => !element.closest("[data-design-studio-chrome]"));
    if (matches.length !== 1 || matches[0] !== replacement) return null;
    const bindingScope = designBindingScope(replacement);
    semanticBindingsFor(authority.id).set(bindingScope, {
      element: replacement,
      occurrenceId: replacementOccurrenceId,
      ambiguous: false,
    });
    return {
      ...authority,
      element: replacement,
      occurrenceId: replacementOccurrenceId,
      bindingScope,
    };
  }
  if (replacementOccurrenceId !== authority.occurrenceId) return null;
  return { ...authority, element: replacement };
}

/** Retire a semantic binding so its old override cannot migrate to a surviving or future peer. */
export function releaseExactDesignTargetAuthority(authority: ExactDesignTargetAuthority): void {
  const bindings = exactSemanticTargets.get(authority.id);
  if (bindings?.get(authority.bindingScope)?.element === authority.element) {
    bindings.set(authority.bindingScope, null);
  }
}

function elementSignature(element: Element): string {
  return [
    element.localName,
    element.getAttribute("role") ?? "",
    element.getAttribute("type") ?? "",
  ].join("|");
}

function fallbackSemanticKey(element: Element, siblingOrdinal: number): string {
  const parent = element.parentElement?.closest(DESIGN_TARGET_SELECTOR);
  const parentId = parent ? designIdOf(parent) : "stockroom-root";
  return [parentId, elementSignature(element), siblingOrdinal].join("|");
}

function semanticGeneratedId(element: Element): string | null {
  for (const [attribute, owner] of [
    ["data-copy-id", "copy"],
    ["data-icon-id", "icon"],
    ["data-layout-piece", "layout"],
  ] as const) {
    const value = element.getAttribute(attribute)?.trim();
    if (value) return runtimeDesignId(owner, value);
  }
  return null;
}

/** Cover DOM emitted through dynamic JSX tags, portals, clones, and imperative Stockroom renderers. */
export function ensureDesignIdentities(root: ParentNode): void {
  const elements = root instanceof Element
    ? [root, ...Array.from(root.querySelectorAll("*"))]
    : Array.from(root.querySelectorAll("*"));
  const siblingCounts = new WeakMap<Element, Map<string, number>>();
  for (const element of elements) {
    const parent = element.parentElement;
    const signature = elementSignature(element);
    const counts = parent ? (siblingCounts.get(parent) ?? new Map<string, number>()) : new Map<string, number>();
    const ordinal = counts.get(signature) ?? 0;
    counts.set(signature, ordinal + 1);
    if (parent) siblingCounts.set(parent, counts);
    if (element.closest('[data-design-technical-content="true"]')) continue;
    if (element.localName !== "svg" && element.closest("svg")) continue;
    if (!element.hasAttribute("data-dev-id")) {
      const semanticId = semanticGeneratedId(element);
      const existing = element.getAttribute("data-design-id");
      if (semanticId && (existing === null || !isGeneratedDesignId(existing))) {
        element.setAttribute("data-design-id", semanticId);
        continue;
      }
    }
    if (designIdOf(element)) continue;
    assignDesignIdentity(element, `dom-${element.localName}`, fallbackSemanticKey(element, ordinal));
  }
  ensureDesignOccurrenceIdentities(root);
}
