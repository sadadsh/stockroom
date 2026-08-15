/**
 * Tailwind utilities to the design-token CSS variables they consume.
 *
 * Design Studio reads the selected element's complete className, including variant and opacity
 * modifiers, so the resolver normalizes those before lookup. Every editable color token exposes
 * the same background, text, border, outline, ring, and SVG-stroke vocabulary; non-color roles are
 * listed once below.
 */
export const TOKEN_COLOR_CLASSES: Readonly<Record<string, string>> = {
  app: "--c-app",
  canvas: "--c-canvas",
  rail: "--c-rail",
  surface: "--c-surface",
  raise: "--c-raise",
  raise2: "--c-raise2",
  section: "--c-section",
  active: "--c-active",
  stage: "--c-stage",
  field: "--c-field",
  popover: "--c-popover",
  band: "--c-band",
  technical: "--c-technical",
  "technical-wash": "--c-technical-wash",
  "technical-ink": "--c-technical-ink",
  "technical-note": "--c-technical-note",
  "layer-copper": "--c-layer-copper",
  "layer-mask": "--c-layer-mask",
  "layer-paste": "--c-layer-paste",
  "layer-silk": "--c-layer-silk",
  "layer-fab": "--c-layer-fab",
  "layer-courtyard": "--c-layer-courtyard",
  "control-top": "--c-control-top",
  "control-bottom": "--c-control-bottom",
  "control-hover": "--c-control-hover",
  "control-pressed": "--c-control-pressed",
  selected: "--c-selected",
  "selected-hover": "--c-selected-hover",
  "selected-edge": "--c-selected-edge",
  "row-alt": "--c-row-alt",
  "line-dark": "--c-line-dark",
  line: "--c-line",
  line2: "--c-line2",
  edge: "--c-edge",
  t1: "--c-t1",
  t2: "--c-t2",
  t3: "--c-t3",
  t4: "--c-t4",
  t5: "--c-t5",
  ok: "--c-ok",
  warn: "--c-warn",
  err: "--c-err",
  "ok-text": "--c-ok-text",
  "warn-text": "--c-warn-text",
  "err-text": "--c-err-text",
  "danger-on": "--c-danger-on",
  scrim: "--c-scrim",
  acc: "--c-acc",
  "acc-on": "--c-acc-on",
  "acc-strong": "--c-acc-strong",
  "acc-soft": "--c-acc-soft",
  focus: "--c-focus",
};

const COLOR_ROLES = ["bg", "text", "border", "outline", "ring", "stroke"] as const;
const colorEntries = Object.entries(TOKEN_COLOR_CLASSES).flatMap(([name, cssVar]) =>
  COLOR_ROLES.map((role) => [`${role}-${name}`, cssVar] as const),
);

export const CLASS_TO_VAR: Readonly<Record<string, string>> = Object.freeze({
  ...Object.fromEntries(colorEntries),
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
});

function baseUtility(cls: string): string {
  const afterVariant = cls.slice(cls.lastIndexOf(":") + 1);
  return afterVariant.replace(/\/[^/]+$/, "");
}

// The design-token cssVars an element's className references, deduped in first-seen order.
export function varsForClassName(className: string): string[] {
  const out: string[] = [];
  for (const cls of className.split(/\s+/)) {
    const cssVar = CLASS_TO_VAR[baseUtility(cls)];
    if (cssVar && !out.includes(cssVar)) out.push(cssVar);
  }
  return out;
}
