import type { DesignScope } from "./document";
import { nodesForDevId } from "../lib/componentDevIds";
import {
  DESIGN_TARGET_SELECTOR,
  designIdOf,
  designIdSelector,
  isGeneratedDesignId,
} from "../lib/designIdentity";

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
  editTargets: TargetDomainEditTargets;
}

export type EditableTargetDomain = "box" | "text" | "icon";

export interface TargetDomainEditTarget {
  domain: EditableTargetDomain;
  targetId: string;
  overrideId: string;
  selector: string;
  elements: Element[];
  contentIds: string[];
}

export type TargetDomainEditTargets = Record<EditableTargetDomain, TargetDomainEditTarget>;

export const TARGET_DOMAIN_SELECTORS: Readonly<Record<EditableTargetDomain, string>> = {
  box: ":scope",
  text: ":scope, :scope *",
  icon: ":scope [data-icon-id], :scope svg.ico, :scope svg",
};

const DOMAIN_OVERRIDE_SUFFIX = "::";

/** One persisted override key that keeps an internal edit separate from its owning box. */
export function targetDomainOverrideId(targetId: string, domain: EditableTargetDomain): string {
  return domain === "box" ? targetId : `${targetId}${DOMAIN_OVERRIDE_SUFFIX}${domain}`;
}

export function parseTargetDomainOverrideId(
  overrideId: string,
): { targetId: string; domain: EditableTargetDomain } {
  const separator = overrideId.lastIndexOf(DOMAIN_OVERRIDE_SUFFIX);
  if (separator === -1) return { targetId: overrideId, domain: "box" };
  const targetId = overrideId.slice(0, separator);
  const suffix = overrideId.slice(separator + DOMAIN_OVERRIDE_SUFFIX.length);
  if (suffix === "text" || suffix === "icon") return { targetId, domain: suffix };
  return { targetId: overrideId, domain: "box" };
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
  if (designIdOf(root) === id) return root;
  return root.querySelector(designIdSelector(id));
}

function belongsToTarget(element: Element, target: Element): boolean {
  const authoredBoundary = element.closest("[data-dev-id]");
  return authoredBoundary === target || authoredBoundary === null || !target.contains(authoredBoundary);
}

function textDomains(target: Element): TargetTextDomain[] {
  const texts: TargetTextDomain[] = [];
  const visit = (node: Node) => {
    if (node.nodeType === Node.ELEMENT_NODE) {
      const element = node as Element;
      if (element !== target && isTechnical(element)) return;
      if (element !== target && element.hasAttribute("data-dev-id")) return;
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
    if (!belongsToTarget(element, target)) continue;
    const iconOwner = element.closest("[data-icon-id]");
    const owner = iconOwner && target.contains(iconOwner) ? iconOwner : element;
    if (claimed.has(owner)) continue;
    claimed.add(owner);
    icons.push({ element: owner, iconId: owner.getAttribute("data-icon-id") });
  }
  return icons;
}

function behaviorDomains(target: Element): Element[] {
  return inclusiveElements(target, "[data-dev-control]").filter(
    (element) => !isTechnical(element) && belongsToTarget(element, target),
  );
}

function stateDomains(target: Element): TargetStateDomain[] {
  const states: TargetStateDomain[] = [];
  for (const element of inclusiveElements(target, "*")) {
    if (isTechnical(element)) continue;
    if (!belongsToTarget(element, target)) continue;
    for (const name of STATE_ATTRIBUTES) {
      const value = element.getAttribute(name);
      if (value !== null) states.push({ element, name, value });
    }
  }
  return states;
}

function uniqueElements(elements: readonly Element[]): Element[] {
  return [...new Set(elements)];
}

function domainElementsExceptTarget<T extends { element: Element }>(
  domains: readonly T[],
  target: Element,
): Element[] {
  const elements: Element[] = [];
  for (const domain of domains) {
    if (domain.element !== target) elements.push(domain.element);
  }
  return uniqueElements(elements);
}

function editTargets(
  id: string,
  target: Element,
  texts: readonly TargetTextDomain[],
  icons: readonly TargetIconDomain[],
): TargetDomainEditTargets {
  const make = (
    domain: EditableTargetDomain,
    elements: Element[],
    contentIds: string[],
  ): TargetDomainEditTarget => ({
    domain,
    targetId: id,
    overrideId: targetDomainOverrideId(id, domain),
    selector: TARGET_DOMAIN_SELECTORS[domain],
    elements,
    contentIds: [...new Set(contentIds)],
  });
  return {
    box: make("box", [target], []),
    text: make(
      "text",
      domainElementsExceptTarget(texts, target),
      texts.flatMap((text) => text.copyId ? [text.copyId] : []),
    ),
    icon: make(
      "icon",
      domainElementsExceptTarget(icons, target),
      icons.flatMap((icon) => icon.iconId ? [icon.iconId] : []),
    ),
  };
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
    editTargets: editTargets(id, target, texts, icons),
  };
}

/** Resolve a persisted domain override against every live instance of its owning stable target. */
export function elementsForTargetDomainOverride(
  overrideId: string,
  root: ParentNode = document,
): Element[] {
  const address = parseTargetDomainOverrideId(overrideId);
  const elements: Element[] = [];
  const targets = isGeneratedDesignId(address.targetId)
    ? Array.from(root.querySelectorAll(designIdSelector(address.targetId)))
    : nodesForDevId(address.targetId, root);
  for (const target of targets) {
    if (address.domain === "box") elements.push(target);
    else if (address.domain === "text") {
      elements.push(...domainElementsExceptTarget(textDomains(target), target));
    } else {
      elements.push(...domainElementsExceptTarget(iconDomains(target), target));
    }
  }
  return uniqueElements(elements);
}

function allTargetElements(root: Element): Element[] {
  return inclusiveElements(root, DESIGN_TARGET_SELECTOR);
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
    const candidate = designIdOf(element);
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
