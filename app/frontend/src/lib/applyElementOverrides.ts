/**
 * The runtime that turns the committed per-element override map (lib/element.overrides.ts) into live
 * inline styles keyed by `data-dev-id`. It is applied on boot for EVERYONE (dev mode off or on), the
 * same way token.overrides.ts is, so a saved tweak ships with the app.
 *
 * Why inline styles: an inline style declaration outranks any stylesheet rule in the cascade, so a
 * per-element override beats class/token specificity WITHOUT `!important`. Removing the inline
 * declaration lets the element's token/class styling underneath re-emerge cleanly.
 *
 * Why this is safe: values are written via `el.style.setProperty(prop, value)`, which takes a
 * property + value PAIR. It applies the value structurally and cannot introduce a second declaration
 * or any markup, so a value is never parsed as CSS text (unlike `style.cssText` / `innerHTML`). The
 * backend `dev.py` `_valid_css_value` grammar is the sole authority on what may ever be written into
 * committed source; this runtime re-checks against that same grammar (mirrored in
 * `lib/elementLayout.ts`) for one reason only - a committed file can be hand-edited or can arrive
 * from an older revision, so an override that is no longer valid must be IGNORED rather than allowed
 * to throw during boot.
 *
 * INSTANCE vs SHARED: which elements an id reaches is decided by the id itself, in
 * `lib/componentDevIds.ts`. An id carrying a `[value]` segment names exactly one element; a
 * catalogue id names a role and reaches every element carrying it as `data-dev-id` OR as
 * `data-dev-role`. Selection goes through `CSS.escape`, so a record id holding a quote, a bracket or
 * a backslash is a miss, never a thrown selector.
 */
import {
  elementsForTargetDomainOverride,
  parseTargetDomainOverrideId,
} from "../design-studio/targetDomains";
import { isApplicableElementOverride } from "./elementLayout";

// devId -> (cssProp -> value). Mirrors ELEMENT_OVERRIDES exactly.
export type ElementOverrides = Record<string, Record<string, string>>;

function styled(element: Element): (Element & ElementCSSInlineStyle) | null {
  return "style" in element ? element as Element & ElementCSSInlineStyle : null;
}

function concreteIconPaintTargets(icon: Element): Array<{ element: Element & ElementCSSInlineStyle; property: "fill" | "stroke" }> {
  const targets: Array<{ element: Element & ElementCSSInlineStyle; property: "fill" | "stroke" }> = [];
  for (const element of [icon, ...icon.querySelectorAll("[fill], [stroke]")]) {
    const styleTarget = styled(element);
    if (!styleTarget) continue;
    for (const property of ["fill", "stroke"] as const) {
      const paint = element.getAttribute(property);
      if (paint && paint !== "none" && paint.toLowerCase() !== "currentcolor") {
        targets.push({ element: styleTarget, property });
      }
    }
  }
  return targets;
}

function writeOverrideProperty(id: string, property: string, value: string | null): void {
  const domain = parseTargetDomainOverrideId(id).domain;
  for (const element of elementsForTargetDomainOverride(id)) {
    const target = styled(element);
    if (!target) continue;
    if (value === null) target.style.removeProperty(property);
    else target.style.setProperty(property, value);
    if (domain === "icon" && property === "color") {
      for (const paint of concreteIconPaintTargets(element)) {
        if (value === null) paint.element.style.removeProperty(paint.property);
        else paint.element.style.setProperty(paint.property, value);
      }
    }
  }
}

/**
 * The subset of an override map this runtime will apply: the entries whose property is editable and
 * whose value is in the safe grammar. Exported so Save can send only what the writer would accept
 * and the panel can say which committed entries are being ignored.
 */
export function applicableOverrides(source: ElementOverrides): ElementOverrides {
  const out: ElementOverrides = {};
  for (const [id, props] of Object.entries(source)) {
    if (!id || typeof props !== "object" || props === null) continue;
    const clean: Record<string, string> = {};
    for (const [prop, value] of Object.entries(props)) {
      if (isApplicableElementOverride(prop, value)) clean[prop] = value;
    }
    if (Object.keys(clean).length > 0) out[id] = clean;
  }
  return out;
}

/**
 * Apply `current` as inline styles, and clear any property that was in `previous` but is gone from
 * `current` (so removing an override clears exactly that one declaration). Idempotent: applying the
 * same map twice is a no-op, which is what makes the observer's broad re-apply safe.
 *
 * `previous` is diffed on its RAW keys rather than its applicable subset, so a property that stops
 * being valid (or stops being editable) is still cleared off the element it was last written to.
 */
export function applyElementOverrides(current: ElementOverrides, previous?: ElementOverrides): void {
  const live = applicableOverrides(current);

  // Set every current prop on every element the id addresses.
  for (const [id, props] of Object.entries(live)) {
    for (const [prop, value] of Object.entries(props)) writeOverrideProperty(id, prop, value);
  }

  // Clear anything present in `previous` that no longer appears in `current` (a removed id, or a
  // removed prop within a still-present id).
  if (previous) {
    for (const [id, prevProps] of Object.entries(previous)) {
      const nextProps = live[id];
      const removed = Object.keys(prevProps).filter((prop) => !nextProps || !(prop in nextProps));
      if (removed.length === 0) continue;
      for (const prop of removed) writeOverrideProperty(id, prop, null);
    }
  }
}

/**
 * Watch `document.body` for added element nodes and re-apply the latest overrides to them, so an
 * element that mounts AFTER boot (a modal opening, a list row rendering) still receives its committed
 * override. `getOverrides` returns the current map at call time (the caller keeps it fresh).
 *
 * Observes `childList` + `subtree` ONLY, never `attributes`: writing a style attribute during a
 * re-apply must not retrigger the observer and loop. The re-apply is idempotent, so a broad re-apply
 * over the small overrides key-set on any DOM growth is cheap and correct. Returns a disconnect fn.
 */
export function startElementOverrideObserver(getOverrides: () => ElementOverrides): () => void {
  const observer = new MutationObserver((records) => {
    const grew = records.some((r) => r.addedNodes.length > 0);
    if (grew) applyElementOverrides(getOverrides());
  });
  observer.observe(document.body, { childList: true, subtree: true });
  return () => observer.disconnect();
}
