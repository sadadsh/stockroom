import { resolveIcon, sanitizeIconMarkup } from "../components/iconResolve";
import { designIdSelector, isGeneratedDesignId } from "./designIdentity";
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
}

const originals = new WeakMap<SVGElement, OriginalIcon>();

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
    setAttribute(icon, "aria-label", override.a11yLabel);
    setAttribute(icon, "role", "img");
  } else {
    setAttribute(icon, "aria-label", original.ariaLabel);
    setAttribute(icon, "role", original.role);
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

/** Apply persisted icon edits to raw interface SVGs that do not render through <Icon>. */
export function applyGeneratedIconOverrides(current: IconOverrides, previous: IconOverrides = {}): void {
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
