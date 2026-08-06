/**
 * The map from a Tailwind utility class to the design-token CSS variable it consumes. Dev mode's inspect
 * surface reads an element's className, looks each class up here, and reports the tokens that element uses
 * so the panel can jump straight to editing them. Sourced from the DEV_TOKENS registry + tailwind.config.js:
 * Tailwind emits `bg-*`, `text-*`, and `border-*` from one colour token, so all three map to the same
 * cssVar. Only DEV_TOKENS-backed classes are here (structural greys are intentionally excluded, matching
 * what the panel exposes). NOTE: `--icon-stroke` has no class (it is an SVG stroke-width via `.ico`), so
 * icon usage is detected by element type in the inspector, not through this map.
 */
export const CLASS_TO_VAR: Readonly<Record<string, string>> = {
  "bg-acc": "--c-acc",
  "text-acc": "--c-acc",
  "border-acc": "--c-acc",
  "bg-canvas": "--c-canvas",
  "text-canvas": "--c-canvas",
  "border-canvas": "--c-canvas",
  "bg-raise": "--c-raise",
  "text-raise": "--c-raise",
  "border-raise": "--c-raise",
  "bg-field": "--c-field",
  "text-field": "--c-field",
  "border-field": "--c-field",
  "bg-line": "--c-line",
  "text-line": "--c-line",
  "border-line": "--c-line",
  "bg-t1": "--c-t1",
  "text-t1": "--c-t1",
  "border-t1": "--c-t1",
  "bg-t2": "--c-t2",
  "text-t2": "--c-t2",
  "border-t2": "--c-t2",
  "bg-t3": "--c-t3",
  "text-t3": "--c-t3",
  "border-t3": "--c-t3",
  "bg-ok": "--c-ok",
  "text-ok": "--c-ok",
  "border-ok": "--c-ok",
  "bg-warn": "--c-warn",
  "text-warn": "--c-warn",
  "border-warn": "--c-warn",
  "bg-err": "--c-err",
  "text-err": "--c-err",
  "border-err": "--c-err",
  "bg-ok-text": "--c-ok-text",
  "text-ok-text": "--c-ok-text",
  "border-ok-text": "--c-ok-text",
  "bg-warn-text": "--c-warn-text",
  "text-warn-text": "--c-warn-text",
  "border-warn-text": "--c-warn-text",
  "bg-err-text": "--c-err-text",
  "text-err-text": "--c-err-text",
  "border-err-text": "--c-err-text",
  "text-ui-meta": "--fs-ui-meta",
  "text-ui-caption": "--fs-ui-caption",
  "text-ui-body": "--fs-ui-body",
  "text-ui-label": "--fs-ui-label",
  "text-ui-heading": "--fs-ui-heading",
  "text-ui-subtitle": "--fs-ui-subtitle",
  "text-ui-title": "--fs-ui-title",
  "text-2xs": "--fs-ui-meta",
  "text-xs": "--fs-ui-caption",
  "text-sm": "--fs-ui-body",
  "text-base": "--fs-ui-label",
  "text-lg": "--fs-ui-heading",
  "text-xl": "--fs-ui-subtitle",
  "text-title": "--fs-ui-title",
  "rounded-card": "--r-card",
  "rounded-control": "--r-control",
  "shadow-card": "--shadow-card",
  "shadow-raise": "--shadow-raise",
  "shadow-pop": "--shadow-pop",
  "shadow-file": "--shadow-file",
};

// The design-token cssVars an element's className references, deduped and in first-seen order. Unknown
// classes are ignored, so passing a full className string returns only the DEV_TOKENS-backed tokens.
export function varsForClassName(className: string): string[] {
  const out: string[] = [];
  for (const cls of className.split(/\s+/)) {
    const cssVar = CLASS_TO_VAR[cls];
    if (cssVar && !out.includes(cssVar)) out.push(cssVar);
  }
  return out;
}
