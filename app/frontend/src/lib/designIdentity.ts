const GENERATED_DESIGN_ID = /^auto\.[a-z0-9-]+\.[a-z0-9]{7}$/;

export const DESIGN_TARGET_SELECTOR = "[data-dev-id],[data-design-id]";

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
      if (semanticId && (existing === null || isGeneratedDesignId(existing))) {
        element.setAttribute("data-design-id", semanticId);
        continue;
      }
    }
    if (designIdOf(element)) continue;
    assignDesignIdentity(element, `dom-${element.localName}`, fallbackSemanticKey(element, ordinal));
  }
}
