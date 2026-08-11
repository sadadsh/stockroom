import type { DesignScope } from "./document";

/** Stable opt-out boundary for engineering drawings and model canvases inside editable UI. */
export const TECHNICAL_CONTENT_ATTRIBUTE = "data-design-technical-content";
export const TECHNICAL_CONTENT_SELECTOR = `[${TECHNICAL_CONTENT_ATTRIBUTE}="true"]`;

export interface TargetDomainSummary {
  boxes: number;
  texts: number;
  icons: number;
  behaviors: number;
  layout: number;
  states: number;
}

export interface TargetTextDomain {
  element: Element;
  copyId: string | null;
  value: string;
}

export interface TargetIconDomain {
  element: Element;
  iconId: string | null;
}

export interface TargetStateDomain {
  element: Element;
  name: string;
  value: string;
}

export interface TargetInspection {
  id: string;
  target: Element;
  role: string | null;
  screen: string;
  semanticRole: string;
  accessibleName: string;
  summary: TargetDomainSummary;
  boxes: Element[];
  texts: TargetTextDomain[];
  icons: TargetIconDomain[];
  behaviors: Element[];
  layout: Element[];
  states: TargetStateDomain[];
}

export interface ScopePreview {
  scope: DesignScope;
  affectedTargetIds: string[];
}

const STATE_ATTRIBUTES = [
  "data-state",
  "data-status",
  "aria-expanded",
  "aria-pressed",
  "aria-selected",
  "aria-disabled",
] as const;

function inclusiveElements(root: Element, selector: string): Element[] {
  const result: Element[] = [];
  if (root.matches(selector)) result.push(root);
  result.push(...root.querySelectorAll(selector));
  return result;
}

function isTechnical(element: Element): boolean {
  return element.closest(TECHNICAL_CONTENT_SELECTOR) !== null;
}

function targetIn(root: Element, id: string): Element | null {
  return inclusiveElements(root, "[data-dev-id]").find(
    (element) => element.getAttribute("data-dev-id") === id,
  ) ?? null;
}

function textDomains(target: Element): TargetTextDomain[] {
  const texts: TargetTextDomain[] = [];
  const visit = (node: Node) => {
    if (node.nodeType === Node.ELEMENT_NODE) {
      const element = node as Element;
      if (element !== target && isTechnical(element)) return;
      if (element.matches("script, style, template")) return;
    }
    if (node.nodeType === Node.TEXT_NODE) {
      const value = node.textContent?.replace(/\s+/g, " ").trim() ?? "";
      const parent = node.parentElement;
      if (value && parent && !isTechnical(parent)) {
        const copyElement = parent.closest("[data-copy-id]");
        texts.push({ element: parent, copyId: copyElement?.getAttribute("data-copy-id") ?? null, value });
      }
      return;
    }
    for (const child of node.childNodes) visit(child);
  };
  visit(target);
  return texts;
}

function iconDomains(target: Element): TargetIconDomain[] {
  const icons: TargetIconDomain[] = [];
  const claimed = new Set<Element>();
  for (const element of inclusiveElements(target, "[data-icon-id], svg.ico, svg")) {
    if (isTechnical(element)) continue;
    const iconOwner = element.closest("[data-icon-id]");
    const owner = iconOwner && target.contains(iconOwner) ? iconOwner : element;
    if (claimed.has(owner)) continue;
    claimed.add(owner);
    icons.push({ element: owner, iconId: owner.getAttribute("data-icon-id") });
  }
  return icons;
}

function behaviorDomains(target: Element): Element[] {
  return inclusiveElements(target, "[data-dev-control]").filter((element) => !isTechnical(element));
}

function stateDomains(target: Element): TargetStateDomain[] {
  const states: TargetStateDomain[] = [];
  for (const element of inclusiveElements(target, "*")) {
    if (isTechnical(element)) continue;
    for (const name of STATE_ATTRIBUTES) {
      const value = element.getAttribute(name);
      if (value !== null) states.push({ element, name, value });
    }
  }
  return states;
}

/** Inspect one exact stable target without collapsing its independent editing domains. */
export function inspectTarget(root: Element, id: string): TargetInspection {
  const target = targetIn(root, id);
  if (!target) throw new Error(`Design target '${id}' is not present under the supplied root.`);
  const texts = textDomains(target);
  const icons = iconDomains(target);
  const behaviors = behaviorDomains(target);
  const states = stateDomains(target);
  const screen = id.split(".", 1)[0] || id;
  const semanticRole = target.getAttribute("role") ?? target.tagName.toLowerCase();
  const accessibleName =
    target.getAttribute("aria-label") ?? target.getAttribute("title") ?? texts[0]?.value ?? id;
  return {
    id,
    target,
    role: target.getAttribute("data-dev-role"),
    screen,
    semanticRole,
    accessibleName,
    summary: {
      boxes: 1,
      texts: texts.length,
      icons: icons.length,
      behaviors: behaviors.length,
      layout: 1,
      states: states.length,
    },
    boxes: [target],
    texts,
    icons,
    behaviors,
    layout: [target],
    states,
  };
}

function allTargetElements(root: Element): Element[] {
  return inclusiveElements(root, "[data-dev-id]");
}

/** Resolve a scope to its concrete stable ids before an inspector command writes anything. */
export function previewTargetScope(
  root: Element,
  id: string,
  scope: DesignScope,
): ScopePreview {
  const target = targetIn(root, id);
  if (!target) return { scope, affectedTargetIds: [] };
  const role = target.getAttribute("data-dev-role");
  const screen = id.split(".", 1)[0] || id;
  const ids = new Set<string>();
  for (const element of allTargetElements(root)) {
    const candidate = element.getAttribute("data-dev-id");
    if (!candidate) continue;
    const include =
      scope === "global" ||
      (scope === "screen" && (candidate === screen || candidate.startsWith(`${screen}.`))) ||
      (scope === "role" &&
        (candidate === id ||
          (role !== null &&
            (element.getAttribute("data-dev-role") === role || candidate === role)))) ||
      (scope === "instance" && candidate === id);
    if (include) ids.add(candidate);
  }
  if (ids.size === 0) ids.add(id);
  return { scope, affectedTargetIds: [...ids] };
}
