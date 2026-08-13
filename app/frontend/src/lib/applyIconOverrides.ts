import { resolveIcon, sanitizeIconMarkup } from "../components/iconResolve";
import { designIdSelector, isGeneratedDesignId } from "./designIdentity";
import { runtimeDesignId } from "./designIdentity";
import { elementsForTargetDomainOverride } from "../design-studio/targetDomains";
import type { IconOverride } from "./icon.overrides";

type IconOverrides = Record<string, IconOverride>;

interface OriginalIcon {
  body: string;
  ariaLabel: string | null;
  role: string | null;
  fill: string | null;
  stroke: string | null;
  strokeWidth: string | null;
  opacity: string;
  verticalAlign: string;
  ariaHidden: string | null;
}

const originals = new WeakMap<SVGElement, OriginalIcon>();
const VOID_INSERTION_TARGETS = new Set([
  "area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta",
  "param", "source", "track", "wbr",
]);

function attributeSelector(attribute: string, value: string): string {
  if (typeof CSS !== "undefined" && typeof CSS.escape === "function") {
    return `[${attribute}=${CSS.escape(value)}]`;
  }
  return `[${attribute}="${value.replace(/["\\]/g, "\\$&")}"]`;
}

function generatedIcons(id: string): SVGElement[] {
  if (!isGeneratedDesignId(id)) return [];
  return Array.from(document.querySelectorAll(designIdSelector(id))).filter(
    (element): element is SVGElement => element instanceof SVGElement && !element.hasAttribute("data-icon-id"),
  );
}

function remember(icon: SVGElement): OriginalIcon {
  const existing = originals.get(icon);
  if (existing) return existing;
  const original = {
    body: icon.innerHTML,
    ariaLabel: icon.getAttribute("aria-label"),
    role: icon.getAttribute("role"),
    fill: icon.getAttribute("fill"),
    stroke: icon.getAttribute("stroke"),
    strokeWidth: icon.getAttribute("stroke-width"),
    opacity: icon.style.opacity,
    verticalAlign: icon.style.verticalAlign,
    ariaHidden: icon.getAttribute("aria-hidden"),
  };
  originals.set(icon, original);
  return original;
}

function setAttribute(icon: SVGElement, name: string, value: string | null): void {
  if (value === null) icon.removeAttribute(name);
  else icon.setAttribute(name, value);
}

function restore(icon: SVGElement): void {
  const original = originals.get(icon);
  if (!original) return;
  if (icon.innerHTML !== original.body) icon.innerHTML = original.body;
  setAttribute(icon, "aria-label", original.ariaLabel);
  setAttribute(icon, "role", original.role);
  setAttribute(icon, "fill", original.fill);
  setAttribute(icon, "stroke", original.stroke);
  setAttribute(icon, "stroke-width", original.strokeWidth);
  icon.style.opacity = original.opacity;
  icon.style.verticalAlign = original.verticalAlign;
  setAttribute(icon, "aria-hidden", original.ariaHidden);
}

function apply(icon: SVGElement, override: IconOverride): void {
  const original = remember(icon);
  const swappedBody = override.swapToId ? resolveIcon(override.swapToId)?.body : undefined;
  const body = override.body ?? swappedBody;
  if (body !== undefined) {
    const safe = sanitizeIconMarkup(body, override.a11yLabel);
    if (icon.innerHTML !== safe) icon.innerHTML = safe;
  } else if (icon.innerHTML !== original.body) {
    icon.innerHTML = original.body;
  }
  if (override.a11yLabel) {
    icon.removeAttribute("aria-hidden");
    setAttribute(icon, "aria-label", override.a11yLabel);
    setAttribute(icon, "role", "img");
  } else {
    setAttribute(icon, "aria-label", original.ariaLabel);
    setAttribute(icon, "role", original.role);
    setAttribute(icon, "aria-hidden", original.ariaHidden);
  }
  if (override.strokeWidth !== undefined) setAttribute(icon, "stroke-width", String(override.strokeWidth));
  else setAttribute(icon, "stroke-width", original.strokeWidth);
  if (override.treatment === "solid") {
    setAttribute(icon, "fill", "currentColor");
    setAttribute(icon, "stroke", "none");
  } else {
    setAttribute(icon, "fill", original.fill);
    setAttribute(icon, "stroke", original.stroke);
  }
  icon.style.opacity = override.treatment === "muted" ? "0.55" : original.opacity;
  icon.style.verticalAlign = override.alignment ?? original.verticalAlign;
}

export function insertedIconOverrideId(targetId: string): string {
  return runtimeDesignId("inserted-icon", targetId);
}

function insertedIcons(id: string): SVGElement[] {
  return Array.from(document.querySelectorAll(attributeSelector("data-design-inserted-icon", id)))
    .filter((element): element is SVGElement => element instanceof SVGElement);
}

function removeInsertedIcons(id: string): void {
  for (const icon of insertedIcons(id)) icon.remove();
}

function targetContainsInsertedIcon(target: Element): boolean {
  return !VOID_INSERTION_TARGETS.has(target.localName);
}

function iconMatchesTarget(
  icon: SVGElement,
  target: Element,
  placement: "before" | "after" | undefined,
): boolean {
  if (targetContainsInsertedIcon(target)) return icon.parentElement === target;
  return placement === "after"
    ? icon.previousElementSibling === target
    : icon.nextElementSibling === target;
}

function attachInsertedIcon(
  icon: SVGElement,
  target: Element,
  placement: "before" | "after" | undefined,
): boolean {
  if (targetContainsInsertedIcon(target)) {
    if (placement === "after") target.append(icon);
    else target.insertBefore(icon, target.firstChild);
    return true;
  }
  if (!target.parentElement) return false;
  if (placement === "after") target.after(icon);
  else target.before(icon);
  return true;
}

function syncInsertedIcons(current: IconOverrides, previous: IconOverrides): void {
  for (const [id, override] of Object.entries(previous)) {
    const next = current[id];
    if (override.insertInto && (!next?.insertInto || next.insertInto !== override.insertInto)) {
      removeInsertedIcons(id);
    }
  }
  for (const [id, override] of Object.entries(current)) {
    if (!override.insertInto) continue;
    const targets = elementsForTargetDomainOverride(override.insertInto);
    for (const icon of insertedIcons(id)) {
      if (!targets.some((target) => iconMatchesTarget(icon, target, override.placement))) icon.remove();
    }
    for (const target of targets) {
      if (target.closest('[data-design-technical-content="true"]')) continue;
      try {
        let icon = insertedIcons(id).find((candidate) => iconMatchesTarget(candidate, target, override.placement));
        if (!icon) {
          icon = document.createElementNS("http://www.w3.org/2000/svg", "svg");
          icon.setAttribute("data-design-id", id);
          icon.setAttribute("data-design-inserted-icon", id);
          icon.setAttribute("viewBox", "0 0 24 24");
          icon.setAttribute("aria-hidden", "true");
          icon.style.display = "inline-block";
          icon.style.width = "1em";
          icon.style.height = "1em";
          icon.style.flex = "none";
          if (override.placement === "after") icon.style.marginLeft = "0.35em";
          else icon.style.marginRight = "0.35em";
          if (!attachInsertedIcon(icon, target, override.placement)) continue;
        }
        apply(icon, override);
      } catch (error) {
        console.error(`Inserted design icon '${id}' was skipped after a DOM write failure.`, error);
      }
    }
  }
}

/** Apply persisted icon edits to raw interface SVGs that do not render through <Icon>. */
export function applyGeneratedIconOverrides(current: IconOverrides, previous: IconOverrides = {}): void {
  syncInsertedIcons(current, previous);
  for (const [id, override] of Object.entries(current)) {
    for (const icon of generatedIcons(id)) apply(icon, override);
  }
  for (const id of Object.keys(previous)) {
    if (id in current) continue;
    for (const icon of generatedIcons(id)) restore(icon);
  }
}

export function startGeneratedIconOverrideObserver(getOverrides: () => IconOverrides): () => void {
  const observer = new MutationObserver((records) => {
    if (records.some((record) => record.addedNodes.length > 0)) {
      applyGeneratedIconOverrides(getOverrides());
    }
  });
  observer.observe(document.body, { childList: true, subtree: true });
  return () => observer.disconnect();
}
