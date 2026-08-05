/**
 * The registry of design tokens the dev-mode Design panel can nudge. Each entry names a CSS
 * variable (declared in styles/index.css), how to edit it (a colour, a px length, a unitless
 * number, or a raw shadow string), whether it is theme-specific (a colour or shadow differs dark
 * vs light; a radius / type size / icon stroke does not), and its shipped default so a reset can
 * revert it exactly. This is the ONLY list the panel reads, so adding a knob is one row here.
 *
 * EVERY chrome token has a row. The previous registry deliberately withheld the structural greys
 * "so a nudge can't quietly break contrast", which had the opposite effect: the surfaces that
 * decide whether the app reads as a desktop tool or a web page were the exact ones nobody could
 * try a value on, so they were adjusted by editing the stylesheet and reloading. Contrast is
 * guarded by styles/visualLanguage.test.ts, which measures the shipped values; the panel is for
 * finding the next shipped value.
 *
 * Defaults MUST stay in sync with styles/index.css. `devTokens.parity.test.ts` reads the
 * stylesheet and asserts it, so the two can no longer drift silently (they had: the registry still
 * claimed a blue #6183a1 accent that the stylesheet had not carried for weeks).
 */

export type TokenKind = "color" | "length" | "number" | "shadow";

export type TokenGroup =
  | "Accent"
  | "Surfaces"
  | "Controls"
  | "Borders"
  | "Text"
  | "Status"
  | "Shape"
  | "Type"
  | "Elevation"
  | "Icons";

export interface DevToken {
  // The CSS variable, e.g. "--c-acc". Themed tokens target the dark value on :root and the light
  // value on :root[data-theme="light"]; shared tokens (radii, type, icon stroke) target :root and
  // apply to both themes.
  cssVar: string;
  label: string;
  group: TokenGroup;
  // color: a hex/rgb(a) value + native picker. length: a px slider+number. number: a unitless
  // slider+number (icon stroke-width). shadow: a raw CSS box-shadow string (text field).
  kind: TokenKind;
  // A themed token edits the active theme (colours, shadows); a shared token is the same on both.
  themed: boolean;
  // The shipped defaults from styles/index.css, for an exact reset + an honest panel readout.
  // `light` is omitted for a shared token; present for a themed one.
  default: { dark: string; light?: string };
  // For a slider-driven token (length / number): the slider bounds + step. Defaults to
  // {min:0,max:28,step:1} (the radii) when omitted; type sizes and the icon stroke set their own.
  range?: { min: number; max: number; step: number };
}

// The type scale is FIXED (no clamp, no viewport response), so its slider bounds are narrow:
// the four shipped steps are 10 / 11 / 13 / 14, and a nudge is meant to test a neighbouring
// step, not to reopen the question of whether the app has a 20px heading.
const TYPE_RANGE = { min: 9, max: 20, step: 0.5 } as const;

export const DEV_TOKENS: DevToken[] = [
  // --- Accent + focus ------------------------------------------------------
  // Neutral by construction. The app has no brand hue, and focus is explicitly not blue.
  {
    cssVar: "--c-acc",
    label: "Accent",
    group: "Accent",
    kind: "color",
    themed: true,
    default: { dark: "#d6d6d6", light: "#303030" },
  },
  {
    cssVar: "--c-acc-on",
    label: "Accent text",
    group: "Accent",
    kind: "color",
    themed: true,
    default: { dark: "#1c1c1c", light: "#f5f5f5" },
  },
  {
    cssVar: "--c-acc-strong",
    label: "Accent strong",
    group: "Accent",
    kind: "color",
    themed: true,
    default: { dark: "#ffffff", light: "#1c1c1c" },
  },
  {
    cssVar: "--c-acc-soft",
    label: "Accent wash",
    group: "Accent",
    kind: "color",
    themed: true,
    default: { dark: "rgba(255, 255, 255, 0.1)", light: "rgba(0, 0, 0, 0.12)" },
  },
  {
    cssVar: "--c-focus",
    label: "Focus ring",
    group: "Accent",
    kind: "color",
    themed: true,
    default: { dark: "#f2f2f2", light: "#141414" },
  },
  {
    cssVar: "--c-hover",
    label: "Hover wash",
    group: "Accent",
    kind: "color",
    themed: true,
    default: { dark: "rgba(255, 255, 255, 0.045)", light: "rgba(0, 0, 0, 0.045)" },
  },
  // --- Surfaces ------------------------------------------------------------
  {
    cssVar: "--c-app",
    label: "App frame",
    group: "Surfaces",
    kind: "color",
    themed: true,
    default: { dark: "#353535", light: "#eaeaea" },
  },
  {
    cssVar: "--c-canvas",
    label: "Workspace",
    group: "Surfaces",
    kind: "color",
    themed: true,
    default: { dark: "#3b3b3b", light: "#f0f0f0" },
  },
  {
    cssVar: "--c-rail",
    label: "Rail",
    group: "Surfaces",
    kind: "color",
    themed: true,
    default: { dark: "#353535", light: "#eaeaea" },
  },
  {
    cssVar: "--c-surface",
    label: "Panel",
    group: "Surfaces",
    kind: "color",
    themed: true,
    default: { dark: "#404040", light: "#f5f5f5" },
  },
  {
    cssVar: "--c-raise",
    label: "Card",
    group: "Surfaces",
    kind: "color",
    themed: true,
    default: { dark: "#404040", light: "#f5f5f5" },
  },
  {
    cssVar: "--c-raise2",
    label: "Card raised",
    group: "Surfaces",
    kind: "color",
    themed: true,
    default: { dark: "#484848", light: "#e4e4e4" },
  },
  {
    cssVar: "--c-section",
    label: "Section",
    group: "Surfaces",
    kind: "color",
    themed: true,
    default: { dark: "#484848", light: "#e4e4e4" },
  },
  {
    cssVar: "--c-active",
    label: "Active surface",
    group: "Surfaces",
    kind: "color",
    themed: true,
    default: { dark: "#585858", light: "#d6d6d6" },
  },
  {
    cssVar: "--c-field",
    label: "Field",
    group: "Surfaces",
    kind: "color",
    themed: true,
    default: { dark: "#2f2f2f", light: "#ffffff" },
  },
  {
    cssVar: "--c-popover",
    label: "Menu",
    group: "Surfaces",
    kind: "color",
    themed: true,
    default: { dark: "#3e3e3e", light: "#f7f7f7" },
  },
  {
    cssVar: "--c-band",
    label: "Chrome band",
    group: "Surfaces",
    kind: "color",
    themed: true,
    // Opaque by contract: it backs sticky headers that rows scroll beneath.
    default: { dark: "#353535", light: "#e2e2e2" },
  },
  {
    cssVar: "--c-stage",
    label: "Specimen well",
    group: "Surfaces",
    kind: "color",
    themed: true,
    default: { dark: "#2f2f2f", light: "#dcdcdc" },
  },
  {
    cssVar: "--c-sticky",
    label: "Sticky header",
    group: "Surfaces",
    kind: "color",
    themed: true,
    default: { dark: "#353535", light: "#e2e2e2" },
  },
  {
    cssVar: "--c-ring-track",
    label: "Ring track",
    group: "Surfaces",
    kind: "color",
    themed: true,
    default: { dark: "#2f2f2f", light: "#d6d6d6" },
  },
  {
    cssVar: "--c-technical",
    label: "Drawing sheet",
    group: "Surfaces",
    kind: "color",
    themed: true,
    // Paper does not invert when the chrome does, so both themes carry one value.
    default: { dark: "#f5f5f2", light: "#f5f5f2" },
  },
  // --- Controls ------------------------------------------------------------
  {
    cssVar: "--c-control-top",
    label: "Button top",
    group: "Controls",
    kind: "color",
    themed: true,
    default: { dark: "#555555", light: "#fdfdfd" },
  },
  {
    cssVar: "--c-control-bottom",
    label: "Button bottom",
    group: "Controls",
    kind: "color",
    themed: true,
    default: { dark: "#464646", light: "#e6e6e6" },
  },
  {
    cssVar: "--c-control-hover",
    label: "Button hover",
    group: "Controls",
    kind: "color",
    themed: true,
    default: { dark: "#5d5d5d", light: "#eaeaea" },
  },
  {
    cssVar: "--c-control-pressed",
    label: "Button pressed",
    group: "Controls",
    kind: "color",
    themed: true,
    default: { dark: "#3e3e3e", light: "#d4d4d4" },
  },
  {
    cssVar: "--c-selected",
    label: "Selected",
    group: "Controls",
    kind: "color",
    themed: true,
    default: { dark: "#626262", light: "#cfcfcf" },
  },
  {
    cssVar: "--c-selected-hover",
    label: "Selected hover",
    group: "Controls",
    kind: "color",
    themed: true,
    default: { dark: "#696969", light: "#c6c6c6" },
  },
  // --- Borders -------------------------------------------------------------
  {
    cssVar: "--c-line-dark",
    label: "Groove",
    group: "Borders",
    kind: "color",
    themed: true,
    default: { dark: "#222222", light: "#a0a0a0" },
  },
  {
    cssVar: "--c-line",
    label: "Hairline",
    group: "Borders",
    kind: "color",
    themed: true,
    default: { dark: "#353535", light: "#c8c8c8" },
  },
  {
    cssVar: "--c-line2",
    label: "Hairline strong",
    group: "Borders",
    kind: "color",
    themed: true,
    default: { dark: "#585858", light: "#b4b4b4" },
  },
  {
    cssVar: "--c-edge",
    label: "Edge highlight",
    group: "Borders",
    kind: "color",
    themed: true,
    default: { dark: "#666666", light: "#ffffff" },
  },
  // --- Text ----------------------------------------------------------------
  // Five tiers, opaque. Not everything is near-white: t1 is reserved for identity,
  // selected content and current values, and the ladder falls from there.
  {
    cssVar: "--c-t1",
    label: "Text primary",
    group: "Text",
    kind: "color",
    themed: true,
    default: { dark: "#ececec", light: "#1c1c1c" },
  },
  {
    cssVar: "--c-t2",
    label: "Text secondary",
    group: "Text",
    kind: "color",
    themed: true,
    default: { dark: "#c4c4c4", light: "#3d3d3d" },
  },
  {
    cssVar: "--c-t3",
    label: "Text label",
    group: "Text",
    kind: "color",
    themed: true,
    default: { dark: "#aaaaaa", light: "#5a5a5a" },
  },
  {
    cssVar: "--c-t4",
    label: "Text muted",
    group: "Text",
    kind: "color",
    themed: true,
    default: { dark: "#929292", light: "#6e6e6e" },
  },
  {
    cssVar: "--c-t5",
    label: "Text disabled",
    group: "Text",
    kind: "color",
    themed: true,
    default: { dark: "#747474", light: "#9a9a9a" },
  },
  // --- Status --------------------------------------------------------------
  {
    cssVar: "--c-ok",
    label: "OK",
    group: "Status",
    kind: "color",
    themed: true,
    default: { dark: "#7cb98f", light: "#2f7d4c" },
  },
  {
    cssVar: "--c-warn",
    label: "Warn",
    group: "Status",
    kind: "color",
    themed: true,
    default: { dark: "#cfa14f", light: "#8a6115" },
  },
  {
    cssVar: "--c-err",
    label: "Error",
    group: "Status",
    kind: "color",
    themed: true,
    default: { dark: "#d9776e", light: "#b53c33" },
  },
  // --- Shape (theme-agnostic radii) ---------------------------------------
  {
    cssVar: "--r-card",
    label: "Card radius",
    group: "Shape",
    kind: "length",
    themed: false,
    // 0-2px is the whole budget: Windows engineering chrome is square.
    default: { dark: "2px" },
    range: { min: 0, max: 6, step: 1 },
  },
  {
    cssVar: "--r-control",
    label: "Control radius",
    group: "Shape",
    kind: "length",
    themed: false,
    default: { dark: "2px" },
    range: { min: 0, max: 6, step: 1 },
  },
  // --- Type (theme-agnostic; four fixed sizes, four fixed leadings) -------------------------
  {
    cssVar: "--fs-ui-mpn",
    label: "Component MPN",
    group: "Type",
    kind: "length",
    themed: false,
    default: { dark: "14px" },
    range: TYPE_RANGE,
  },
  {
    cssVar: "--fs-ui-title",
    label: "Title",
    group: "Type",
    kind: "length",
    themed: false,
    default: { dark: "13px" },
    range: TYPE_RANGE,
  },
  {
    cssVar: "--fs-ui-subtitle",
    label: "Subtitle",
    group: "Type",
    kind: "length",
    themed: false,
    default: { dark: "13px" },
    range: TYPE_RANGE,
  },
  {
    cssVar: "--fs-ui-heading",
    label: "Heading",
    group: "Type",
    kind: "length",
    themed: false,
    default: { dark: "13px" },
    range: TYPE_RANGE,
  },
  {
    cssVar: "--fs-ui-label",
    label: "Label",
    group: "Type",
    kind: "length",
    themed: false,
    default: { dark: "11px" },
    range: TYPE_RANGE,
  },
  {
    cssVar: "--fs-ui-body",
    label: "Body",
    group: "Type",
    kind: "length",
    themed: false,
    default: { dark: "11px" },
    range: TYPE_RANGE,
  },
  {
    cssVar: "--fs-ui-caption",
    label: "Caption",
    group: "Type",
    kind: "length",
    themed: false,
    default: { dark: "11px" },
    range: TYPE_RANGE,
  },
  {
    cssVar: "--fs-ui-meta",
    label: "Metadata",
    group: "Type",
    kind: "length",
    themed: false,
    default: { dark: "10px" },
    range: TYPE_RANGE,
  },
  {
    cssVar: "--lh-ui-mpn",
    label: "MPN leading",
    group: "Type",
    kind: "length",
    themed: false,
    default: { dark: "18px" },
    range: { min: 12, max: 28, step: 1 },
  },
  {
    cssVar: "--lh-ui-title",
    label: "Title leading",
    group: "Type",
    kind: "length",
    themed: false,
    default: { dark: "18px" },
    range: { min: 12, max: 28, step: 1 },
  },
  {
    cssVar: "--lh-ui-body",
    label: "Body leading",
    group: "Type",
    kind: "length",
    themed: false,
    default: { dark: "15px" },
    range: { min: 12, max: 28, step: 1 },
  },
  {
    cssVar: "--lh-ui-meta",
    label: "Metadata leading",
    group: "Type",
    kind: "length",
    themed: false,
    default: { dark: "14px" },
    range: { min: 10, max: 24, step: 1 },
  },
  // --- Elevation (raw CSS box-shadow strings) --------------------------------------------------
  // A resting panel is flat: a border and a 1px top bevel. Only a floating surface casts a shadow.
  {
    cssVar: "--shadow-card",
    label: "Card",
    group: "Elevation",
    kind: "shadow",
    themed: true,
    default: {
      dark: "inset 0 1px 0 var(--edge-hi)",
      light: "inset 0 1px 0 var(--edge-hi)",
    },
  },
  {
    cssVar: "--shadow-raise",
    label: "Raise",
    group: "Elevation",
    kind: "shadow",
    themed: true,
    default: {
      dark: "inset 0 1px 0 var(--edge-hi), 0 1px 2px rgba(0, 0, 0, 0.35)",
      light: "inset 0 1px 0 var(--edge-hi), 0 1px 2px rgba(20, 22, 26, 0.12)",
    },
  },
  {
    cssVar: "--shadow-pop",
    label: "Pop",
    group: "Elevation",
    kind: "shadow",
    themed: true,
    default: {
      dark: "0 2px 8px rgba(0, 0, 0, 0.45)",
      light: "0 2px 8px rgba(20, 22, 26, 0.18)",
    },
  },
  {
    cssVar: "--shadow-file",
    label: "File",
    group: "Elevation",
    kind: "shadow",
    themed: true,
    default: {
      dark: "0 1px 3px rgba(0, 0, 0, 0.3)",
      light: "0 1px 3px rgba(20, 22, 26, 0.12)",
    },
  },
  {
    cssVar: "--edge-hi",
    label: "Bevel",
    group: "Elevation",
    kind: "color",
    themed: true,
    default: { dark: "rgba(255, 255, 255, 0.05)", light: "rgba(255, 255, 255, 0.9)" },
  },
  // --- Icons (theme-agnostic; the primary UI icon weight as a unitless stroke-width) ------------
  {
    cssVar: "--icon-stroke",
    label: "Icon stroke",
    group: "Icons",
    kind: "number",
    themed: false,
    default: { dark: "1.8" },
    range: { min: 0.5, max: 3, step: 0.1 },
  },
];

// The groups in panel order.
export const DEV_TOKEN_GROUPS = [
  "Accent",
  "Surfaces",
  "Controls",
  "Borders",
  "Text",
  "Status",
  "Shape",
  "Type",
  "Elevation",
  "Icons",
] as const;

// A by-variable lookup so consumers resolve a token in one call instead of re-scanning the list.
export const DEV_TOKEN_BY_VAR: ReadonlyMap<string, DevToken> = new Map(
  DEV_TOKENS.map((token) => [token.cssVar, token]),
);

// The slider bounds a length/number row uses when a token omits its own range.
export const DEFAULT_RANGE = { min: 0, max: 28, step: 1 } as const;
