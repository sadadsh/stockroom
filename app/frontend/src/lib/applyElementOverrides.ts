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
 * or any markup, so a value is never parsed as CSS text (unlike `style.cssText` / `innerHTML`). This
 * runtime does NOT re-validate; the backend `dev.py` `_valid_css_value` grammar is the sole authority
 * on what may ever be written into committed source. Here we only apply what is already committed.
 */

// devId -> (cssProp -> value). Mirrors ELEMENT_OVERRIDES exactly.
export type ElementOverrides = Record<string, Record<string, string>>;

// Ids are dot-namespaced lowercase-kebab (e.g. `detail.spec-sheet`), so a quoted attribute selector
// is valid as-is; the quotes keep the dot from being read as a class combinator.
function selectorFor(id: string): string {
  return `[data-dev-id="${id}"]`;
}

/**
 * Apply `current` as inline styles, and clear any property that was in `previous` but is gone from
 * `current` (so removing an override clears exactly that one declaration). Idempotent: applying the
 * same map twice is a no-op, which is what makes the observer's broad re-apply safe.
 */
export function applyElementOverrides(current: ElementOverrides, previous?: ElementOverrides): void {
  // Set every current prop on every matching node.
  for (const [id, props] of Object.entries(current)) {
    const nodes = document.querySelectorAll<HTMLElement>(selectorFor(id));
    for (const el of nodes) {
      for (const [prop, value] of Object.entries(props)) el.style.setProperty(prop, value);
    }
  }

  // Clear anything present in `previous` that no longer appears in `current` (a removed id, or a
  // removed prop within a still-present id).
  if (previous) {
    for (const [id, prevProps] of Object.entries(previous)) {
      const nextProps = current[id];
      const removed = Object.keys(prevProps).filter((prop) => !nextProps || !(prop in nextProps));
      if (removed.length === 0) continue;
      const nodes = document.querySelectorAll<HTMLElement>(selectorFor(id));
      for (const el of nodes) {
        for (const prop of removed) el.style.removeProperty(prop);
      }
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
