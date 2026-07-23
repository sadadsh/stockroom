/**
 * The registry of design tokens the dev-mode Design panel can nudge. Each entry names a CSS
 * variable (defined in styles/index.css), how to edit it (a colour, a px length, a unitless
 * number, or a raw shadow string), whether it is theme-specific (a colour or shadow differs dark
 * vs light; a radius / type size / icon stroke does not), and its shipped default so a reset can
 * revert it exactly. This is the ONLY list the panel reads, so adding a knob is one row here.
 * Colours are curated to the tokens that actually change the app's character; the deep structural
 * greys stay out so a nudge can't quietly break contrast. Shadows are included as their own
 * Elevation group (a raw text field) since they carry the app's whole sense of depth.
 */

export type TokenKind = "color" | "length" | "number" | "shadow";

export interface DevToken {
  // The CSS variable, e.g. "--c-acc". Themed tokens target the dark value on :root and the light
  // value on :root[data-theme="light"]; shared tokens (radii, type, icon stroke) target :root and
  // apply to both themes.
  cssVar: string;
  label: string;
  group: "Accent" | "Surfaces" | "Text" | "Status" | "Shape" | "Type" | "Elevation" | "Icons";
  // color: a hex/rgb(a) value + native picker. length: a px slider+number. number: a unitless
  // slider+number (icon stroke-width). shadow: a raw CSS box-shadow string (text field).
  kind: TokenKind;
  // A themed token edits the active theme (colours, shadows); a shared token is the same on both.
  themed: boolean;
  // The shipped defaults from styles/index.css, for an exact reset + an honest panel readout.
  // `light` is omitted for a shared token; present (and different) for a themed one.
  default: { dark: string; light?: string };
  // For a slider-driven token (length / number): the slider bounds + step. Defaults to
  // {min:0,max:28,step:1} (the radii) when omitted; type sizes and the icon stroke set their own.
  range?: { min: number; max: number; step: number };
}

export const DEV_TOKENS: DevToken[] = [
  // --- Accent --------------------------------------------------------------
  {
    cssVar: "--c-acc",
    label: "Accent",
    group: "Accent",
    kind: "color",
    themed: true,
    default: { dark: "#f4f4f5", light: "#1b1b1e" },
  },
  // --- Surfaces ------------------------------------------------------------
  {
    cssVar: "--c-canvas",
    label: "Canvas",
    group: "Surfaces",
    kind: "color",
    themed: true,
    default: { dark: "#242427", light: "#e9eaee" },
  },
  {
    cssVar: "--c-raise",
    label: "Card",
    group: "Surfaces",
    kind: "color",
    themed: true,
    default: { dark: "rgba(255, 255, 255, 0.07)", light: "#ffffff" },
  },
  {
    cssVar: "--c-field",
    label: "Field",
    group: "Surfaces",
    kind: "color",
    themed: true,
    default: { dark: "rgba(0, 0, 0, 0.28)", light: "rgba(0, 0, 0, 0.05)" },
  },
  {
    cssVar: "--c-line",
    label: "Hairline",
    group: "Surfaces",
    kind: "color",
    themed: true,
    default: { dark: "rgba(255, 255, 255, 0.07)", light: "rgba(0, 0, 0, 0.1)" },
  },
  // --- Text ----------------------------------------------------------------
  {
    cssVar: "--c-t1",
    label: "Text",
    group: "Text",
    kind: "color",
    themed: true,
    default: { dark: "#f4f4f4", light: "#17181b" },
  },
  {
    cssVar: "--c-t2",
    label: "Text muted",
    group: "Text",
    kind: "color",
    themed: true,
    default: { dark: "rgba(244, 244, 244, 0.66)", light: "rgba(23, 24, 27, 0.68)" },
  },
  {
    cssVar: "--c-t3",
    label: "Text faint",
    group: "Text",
    kind: "color",
    themed: true,
    default: { dark: "rgba(244, 244, 244, 0.4)", light: "rgba(23, 24, 27, 0.46)" },
  },
  // --- Status --------------------------------------------------------------
  {
    cssVar: "--c-ok",
    label: "OK",
    group: "Status",
    kind: "color",
    themed: true,
    default: { dark: "#5fd39a", light: "#2f9e63" },
  },
  {
    cssVar: "--c-warn",
    label: "Warn",
    group: "Status",
    kind: "color",
    themed: true,
    default: { dark: "#e0b354", light: "#a9761b" },
  },
  {
    cssVar: "--c-err",
    label: "Error",
    group: "Status",
    kind: "color",
    themed: true,
    default: { dark: "#e8756c", light: "#cf4a40" },
  },
  // --- Shape (theme-agnostic radii) ---------------------------------------
  {
    cssVar: "--r-card",
    label: "Card radius",
    group: "Shape",
    kind: "length",
    themed: false,
    default: { dark: "14px" },
  },
  {
    cssVar: "--r-control",
    label: "Control radius",
    group: "Shape",
    kind: "length",
    themed: false,
    default: { dark: "8px" },
  },
  // --- Type (theme-agnostic type scale; px size only, line-heights stay bundled in tailwind) ---
  {
    cssVar: "--fs-2xs",
    label: "2XS",
    group: "Type",
    kind: "length",
    themed: false,
    default: { dark: "10.5px" },
    range: { min: 8, max: 26, step: 0.5 },
  },
  {
    cssVar: "--fs-xs",
    label: "XS",
    group: "Type",
    kind: "length",
    themed: false,
    default: { dark: "11.5px" },
    range: { min: 8, max: 26, step: 0.5 },
  },
  {
    cssVar: "--fs-sm",
    label: "SM",
    group: "Type",
    kind: "length",
    themed: false,
    default: { dark: "12.5px" },
    range: { min: 8, max: 26, step: 0.5 },
  },
  {
    cssVar: "--fs-base",
    label: "Base",
    group: "Type",
    kind: "length",
    themed: false,
    default: { dark: "13px" },
    range: { min: 8, max: 26, step: 0.5 },
  },
  {
    cssVar: "--fs-lg",
    label: "LG",
    group: "Type",
    kind: "length",
    themed: false,
    default: { dark: "15px" },
    range: { min: 10, max: 30, step: 0.5 },
  },
  {
    cssVar: "--fs-xl",
    label: "XL",
    group: "Type",
    kind: "length",
    themed: false,
    default: { dark: "16px" },
    range: { min: 10, max: 32, step: 0.5 },
  },
  {
    cssVar: "--fs-title",
    label: "Title",
    group: "Type",
    kind: "length",
    themed: false,
    default: { dark: "22px" },
    range: { min: 14, max: 40, step: 0.5 },
  },
  // --- Elevation (shadows; theme-specific raw CSS box-shadow strings) ----------------------------
  {
    cssVar: "--shadow-card",
    label: "Card",
    group: "Elevation",
    kind: "shadow",
    themed: true,
    default: {
      dark: "inset 0 1px 0 var(--edge-hi), 0 1px 2px rgba(0, 0, 0, 0.32), 0 3px 10px rgba(0, 0, 0, 0.22)",
      light: "inset 0 1px 0 var(--edge-hi), 0 1px 2px rgba(17, 18, 20, 0.05), 0 3px 9px rgba(17, 18, 20, 0.05)",
    },
  },
  {
    cssVar: "--shadow-raise",
    label: "Raise",
    group: "Elevation",
    kind: "shadow",
    themed: true,
    default: {
      dark: "inset 0 1px 0 var(--edge-hi), 0 2px 6px rgba(0, 0, 0, 0.5), 0 16px 38px rgba(0, 0, 0, 0.44)",
      light: "inset 0 1px 0 var(--edge-hi), 0 2px 6px rgba(17, 18, 20, 0.09), 0 14px 30px rgba(17, 18, 20, 0.11)",
    },
  },
  {
    cssVar: "--shadow-pop",
    label: "Pop",
    group: "Elevation",
    kind: "shadow",
    themed: true,
    default: {
      dark: "inset 0 1px 0 var(--edge-hi), 0 2px 8px rgba(0, 0, 0, 0.4), 0 28px 64px rgba(0, 0, 0, 0.62)",
      light: "inset 0 1px 0 var(--edge-hi), 0 2px 8px rgba(17, 18, 20, 0.1), 0 28px 64px rgba(17, 18, 20, 0.2)",
    },
  },
  {
    cssVar: "--shadow-file",
    label: "File",
    group: "Elevation",
    kind: "shadow",
    themed: true,
    default: {
      dark: "0 6px 20px rgba(0, 0, 0, 0.16)",
      light: "0 6px 20px rgba(0, 0, 0, 0.08)",
    },
  },
  // --- Icons (theme-agnostic; the primary UI icon weight as a unitless stroke-width) ------------
  {
    cssVar: "--icon-stroke",
    label: "Icon stroke",
    group: "Icons",
    kind: "number",
    themed: false,
    default: { dark: "1.9" },
    range: { min: 0.5, max: 3, step: 0.1 },
  },
];

// The groups in panel order.
export const DEV_TOKEN_GROUPS = [
  "Accent",
  "Surfaces",
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

// The slider bounds a length/number row uses when a token omits its own range (the radii).
export const DEFAULT_RANGE = { min: 0, max: 28, step: 1 } as const;
