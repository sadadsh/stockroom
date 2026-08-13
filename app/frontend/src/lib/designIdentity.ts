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

function fallbackSemanticKey(element: Element): string {
  const parent = element.parentElement?.closest(DESIGN_TARGET_SELECTOR);
  const parentId = parent ? designIdOf(parent) : "stockroom-root";
  return [parentId, element.localName, element.getAttribute("role") ?? "", element.getAttribute("type") ?? ""].join("|");
}

/** Cover DOM emitted through dynamic JSX tags, portals, clones, and imperative Stockroom renderers. */
export function ensureDesignIdentities(root: ParentNode): void {
  const elements = root instanceof Element
    ? [root, ...Array.from(root.querySelectorAll("*"))]
    : Array.from(root.querySelectorAll("*"));
  for (const element of elements) {
    if (element.closest('[data-design-technical-content="true"]')) continue;
    if (element.localName !== "svg" && element.closest("svg")) continue;
    if (designIdOf(element)) continue;
    assignDesignIdentity(element, `dom-${element.localName}`, fallbackSemanticKey(element));
  }
}
