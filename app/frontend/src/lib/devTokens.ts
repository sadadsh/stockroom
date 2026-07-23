/**
 * The registry of design tokens the dev-mode Design panel can nudge. Each entry names a CSS
 * variable (defined in styles/index.css), how to edit it (a colour or a px length), whether it
 * is theme-specific (a colour differs dark vs light; a radius does not), and its shipped default
 * so a reset can revert it exactly. This is the ONLY list the panel reads, so adding a knob is
 * one line here. Colours are curated to the tokens that actually change the app's character;
 * the deep structural greys and shadows stay out so a nudge can't quietly break contrast.
 */

export type TokenKind = "color" | "length";

export interface DevToken {
  // The CSS variable, e.g. "--c-acc". Colours target the dark value on :root and the light value
  // on :root[data-theme="light"]; lengths (radii) target :root and apply to both themes.
  cssVar: string;
  label: string;
  group: "Accent" | "Surfaces" | "Text" | "Status" | "Shape";
  kind: TokenKind;
  // A colour is theme-specific (edit the active theme); a length is shared across themes.
  themed: boolean;
  // The shipped defaults from styles/index.css, for an exact reset. `light` is omitted for a
  // shared (length) token.
  default: { dark: string; light?: string };
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
];

// The groups in panel order.
export const DEV_TOKEN_GROUPS = ["Accent", "Surfaces", "Text", "Status", "Shape"] as const;
