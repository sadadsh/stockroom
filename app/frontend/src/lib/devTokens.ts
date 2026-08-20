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
  | "Drawing"
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
    default: { dark: "#d6d9d7", light: "#343936" },
  },
  {
    cssVar: "--c-acc-on",
    label: "Accent text",
    group: "Accent",
    kind: "color",
    themed: true,
    default: { dark: "#17191a", light: "#ffffff" },
  },
  {
    cssVar: "--c-acc-strong",
    label: "Accent strong",
    group: "Accent",
    kind: "color",
    themed: true,
    default: { dark: "#f0f1f0", light: "#202422" },
  },
  {
    cssVar: "--c-acc-soft",
    label: "Accent wash",
    group: "Accent",
    kind: "color",
    themed: true,
    default: { dark: "rgba(255, 255, 255, 0.1)", light: "rgba(0, 0, 0, 0.1)" },
  },
  {
    cssVar: "--c-focus",
    label: "Focus ring",
    group: "Accent",
    kind: "color",
    themed: true,
    default: { dark: "#f0f1f0", light: "#202422" },
  },
  {
    cssVar: "--c-hover",
    label: "Hover wash",
    group: "Accent",
    kind: "color",
    themed: true,
    default: { dark: "rgba(255, 255, 255, 0.05)", light: "rgba(0, 0, 0, 0.04)" },
  },
  // --- Surfaces ------------------------------------------------------------
  {
    cssVar: "--c-app",
    label: "App frame",
    group: "Surfaces",
    kind: "color",
    themed: true,
    default: { dark: "#17191a", light: "#f2f3f2" },
  },
  {
    cssVar: "--c-canvas",
    label: "Workspace",
    group: "Surfaces",
    kind: "color",
    themed: true,
    default: { dark: "#17191a", light: "#f2f3f2" },
  },
  {
    cssVar: "--c-rail",
    label: "Rail",
    group: "Surfaces",
    kind: "color",
    themed: true,
    default: { dark: "#17191a", light: "#f2f3f2" },
  },
  {
    cssVar: "--c-surface",
    label: "Panel",
    group: "Surfaces",
    kind: "color",
    themed: true,
    default: { dark: "#222527", light: "#fbfbfa" },
  },
  {
    cssVar: "--c-raise",
    label: "Card",
    group: "Surfaces",
    kind: "color",
    themed: true,
    default: { dark: "#222527", light: "#fbfbfa" },
  },
  {
    cssVar: "--c-raise2",
    label: "Card raised",
    group: "Surfaces",
    kind: "color",
    themed: true,
    default: { dark: "#2b2f31", light: "#f5f6f5" },
  },
  {
    cssVar: "--c-section",
    label: "Section",
    group: "Surfaces",
    kind: "color",
    themed: true,
    default: { dark: "#2b2f31", light: "#f5f6f5" },
  },
  {
    cssVar: "--c-active",
    label: "Active surface",
    group: "Surfaces",
    kind: "color",
    themed: true,
    default: { dark: "#353a3d", light: "#e5e7e5" },
  },
  {
    cssVar: "--c-field",
    label: "Field",
    group: "Surfaces",
    kind: "color",
    themed: true,
    default: { dark: "#1b1d1f", light: "#ffffff" },
  },
  {
    cssVar: "--c-popover",
    label: "Menu",
    group: "Surfaces",
    kind: "color",
    themed: true,
    default: { dark: "#2b2f31", light: "#ffffff" },
  },
  {
    cssVar: "--c-band",
    label: "Chrome band",
    group: "Surfaces",
    kind: "color",
    themed: true,
    // Opaque by contract: it backs sticky headers that rows scroll beneath.
    default: { dark: "#1d2022", light: "#f0f1f0" },
  },
  {
    cssVar: "--c-stage",
    label: "Specimen well",
    group: "Surfaces",
    kind: "color",
    themed: true,
    default: { dark: "#1a1c1e", light: "#eaebea" },
  },
  {
    cssVar: "--c-sticky",
    label: "Sticky header",
    group: "Surfaces",
    kind: "color",
    themed: true,
    default: { dark: "#1d2022", light: "#f0f1f0" },
  },
  {
    cssVar: "--c-ring-track",
    label: "Ring track",
    group: "Surfaces",
    kind: "color",
    themed: true,
    default: { dark: "#1a1c1e", light: "#e6e9e6" },
  },
  // --- The technical drawing sheet ------------------------------------------
  // Its own group, because these ten are adjusted together or not at all: the
  // sheet, the two ink tiers on it, and the six layer colours of a land pattern.
  // Nudging the sheet without the ink is how a symbol ends up drawn in near-black
  // on a near-black canvas, which is the exact failure this family exists to fix.
  {
    cssVar: "--c-technical",
    label: "Drawing sheet",
    group: "Drawing",
    kind: "color",
    themed: true,
    // Theme-aware: a bright sheet in dark theme was the brightest thing on screen.
    default: { dark: "#151615", light: "#fafaf8" },
  },
  {
    cssVar: "--c-technical-wash",
    label: "Symbol body wash",
    group: "Drawing",
    kind: "color",
    themed: true,
    default: { dark: "#252725", light: "#f1f1ec" },
  },
  {
    cssVar: "--c-technical-ink",
    label: "Drawing ink",
    group: "Drawing",
    kind: "color",
    themed: true,
    default: { dark: "#e6e8e7", light: "#242625" },
  },
  {
    cssVar: "--c-technical-note",
    label: "Drawing annotation",
    group: "Drawing",
    kind: "color",
    themed: true,
    default: { dark: "#9a9e9b", light: "#666a67" },
  },
  {
    cssVar: "--c-layer-copper",
    label: "Copper layer",
    group: "Drawing",
    kind: "color",
    themed: true,
    default: { dark: "#e09328", light: "#b06a2c" },
  },
  {
    cssVar: "--c-layer-mask",
    label: "Solder mask layer",
    group: "Drawing",
    kind: "color",
    themed: true,
    default: { dark: "#d087bd", light: "#9c4a86" },
  },
  {
    cssVar: "--c-layer-paste",
    label: "Solder paste layer",
    group: "Drawing",
    kind: "color",
    themed: true,
    default: { dark: "#8f8f8f", light: "#7a7a7a" },
  },
  {
    cssVar: "--c-layer-silk",
    label: "Silkscreen layer",
    group: "Drawing",
    kind: "color",
    themed: true,
    default: { dark: "#e8e8e8", light: "#3a3a3a" },
  },
  {
    cssVar: "--c-layer-fab",
    label: "Fabrication layer",
    group: "Drawing",
    kind: "color",
    themed: true,
    default: { dark: "#c2b862", light: "#96803a" },
  },
  {
    cssVar: "--c-layer-courtyard",
    label: "Courtyard layer",
    group: "Drawing",
    kind: "color",
    themed: true,
    default: { dark: "#63b963", light: "#4a7a4a" },
  },
  // --- Controls ------------------------------------------------------------
  {
    cssVar: "--c-control-top",
    label: "Button top",
    group: "Controls",
    kind: "color",
    themed: true,
    default: { dark: "#353a3d", light: "#ffffff" },
  },
  {
    cssVar: "--c-control-bottom",
    label: "Button bottom",
    group: "Controls",
    kind: "color",
    themed: true,
    default: { dark: "#2b2f31", light: "#f2f3f2" },
  },
  {
    cssVar: "--c-control-hover",
    label: "Button hover",
    group: "Controls",
    kind: "color",
    themed: true,
    default: { dark: "#353a3d", light: "#f7f8f7" },
  },
  {
    cssVar: "--c-control-pressed",
    label: "Button pressed",
    group: "Controls",
    kind: "color",
    themed: true,
    default: { dark: "#1d2022", light: "#e7e9e7" },
  },
  // Selection and active state, NEUTRAL. The fill steps away from the panel (up in dark, down in
  // light) and a solid 2px edge marker runs down the row; there is no hue involved. The value is
  // held by measurement rather than by hue - the former neutral #626262 dropped the metadata tier
  // to 2.0:1 on a selected row, so styles/visualLanguage.test.ts measures all five tiers on this
  // fill and its hover in both themes.
  {
    cssVar: "--c-selected",
    label: "Selected",
    group: "Controls",
    kind: "color",
    themed: true,
    default: { dark: "#303538", light: "#e4e7e5" },
  },
  {
    cssVar: "--c-selected-hover",
    label: "Selected hover",
    group: "Controls",
    kind: "color",
    themed: true,
    default: { dark: "#363b3e", light: "#e2e5e3" },
  },
  {
    cssVar: "--c-selected-edge",
    label: "Selected edge marker",
    group: "Controls",
    kind: "color",
    themed: true,
    default: { dark: "#e4e6e5", light: "#2c302e" },
  },
  {
    cssVar: "--c-row-alt",
    label: "Alternating grid row",
    group: "Surfaces",
    kind: "color",
    themed: true,
    default: { dark: "#1d2022", light: "#f6f7f6" },
  },
  // --- Borders -------------------------------------------------------------
  {
    cssVar: "--c-line-dark",
    label: "Groove",
    group: "Borders",
    kind: "color",
    themed: true,
    default: { dark: "#202325", light: "#f0f1f0" },
  },
  {
    cssVar: "--c-line",
    label: "Hairline",
    group: "Borders",
    kind: "color",
    themed: true,
    default: { dark: "#2b2e30", light: "#eceeec" },
  },
  {
    cssVar: "--c-line2",
    label: "Hairline strong",
    group: "Borders",
    kind: "color",
    themed: true,
    default: { dark: "#35383a", light: "#e3e5e3" },
  },
  {
    cssVar: "--c-edge",
    label: "Edge highlight",
    group: "Borders",
    kind: "color",
    themed: true,
    default: { dark: "#5e6467", light: "#ffffff" },
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
    default: { dark: "#eceeed", light: "#252826" },
  },
  {
    cssVar: "--c-t2",
    label: "Text secondary",
    group: "Text",
    kind: "color",
    themed: true,
    default: { dark: "#c9cdcb", light: "#454a47" },
  },
  {
    cssVar: "--c-t3",
    label: "Text label",
    group: "Text",
    kind: "color",
    themed: true,
    default: { dark: "#aeb3b1", light: "#5e6460" },
  },
  {
    cssVar: "--c-t4",
    label: "Text muted",
    group: "Text",
    kind: "color",
    themed: true,
    default: { dark: "#9fa5a2", light: "#737a76" },
  },
  {
    cssVar: "--c-t5",
    label: "Text disabled",
    group: "Text",
    kind: "color",
    themed: true,
    default: { dark: "#676d6a", light: "#a4aaa6" },
  },
  // --- Status --------------------------------------------------------------
  {
    cssVar: "--c-ok",
    label: "OK",
    group: "Status",
    kind: "color",
    themed: true,
    default: { dark: "#56a36c", light: "#2e7a4b" },
  },
  {
    // NEUTRAL, and deliberately so: a warning is the exact word plus the triangle `StatusText`
    // draws beside it, at the label text value. It was an amber, and amber ended up carrying every
    // warning state AND the selection accent, which made the warning colour the commonest colour
    // on screen. Green and red stay hues; this one does not.
    cssVar: "--c-warn",
    label: "Warn",
    group: "Status",
    kind: "color",
    themed: true,
    default: { dark: "#aeb3b1", light: "#5e6460" },
  },
  {
    cssVar: "--c-err",
    label: "Error",
    group: "Status",
    kind: "color",
    themed: true,
    default: { dark: "#c95b58", light: "#b33f3c" },
  },
  // The TEXT strength of the three states. A knob of their own rather than an alias onto the row
  // above, because they are not the same value at a different opacity: the three tokens above are
  // held to the 3:1 non-text bar a fill, a border and a glyph answer to, and these are held to the
  // 4.5:1 bar a WORD answers to. Adjusting one and not the other is a real choice, so both are
  // adjustable. `text-ok-text` / `text-warn-text` / `text-err-text` are the utilities.
  {
    cssVar: "--c-ok-text",
    label: "OK text",
    group: "Status",
    kind: "color",
    themed: true,
    default: { dark: "#78c08c", light: "#266840" },
  },
  {
    cssVar: "--c-warn-text",
    label: "Warn text",
    group: "Status",
    kind: "color",
    themed: true,
    default: { dark: "#c9cdcb", light: "#454a47" },
  },
  {
    cssVar: "--c-err-text",
    label: "Error text",
    group: "Status",
    kind: "color",
    themed: true,
    default: { dark: "#ec9a97", light: "#9c3633" },
  },
  {
    cssVar: "--c-danger-on",
    label: "Danger button text",
    group: "Status",
    kind: "color",
    themed: true,
    default: { dark: "#111214", light: "#ffffff" },
  },
  {
    cssVar: "--c-scrim",
    label: "Modal scrim",
    group: "Surfaces",
    kind: "color",
    themed: true,
    default: { dark: "rgba(0, 0, 0, 0.55)", light: "rgba(0, 0, 0, 0.55)" },
  },
  // --- Shape (theme-agnostic radii) ---------------------------------------
  {
    cssVar: "--r-card",
    label: "Card radius",
    group: "Shape",
    kind: "length",
    themed: false,
    // ZERO: a panel, a band and a row are square. Windows engineering chrome has no radius.
    default: { dark: "0px" },
    range: { min: 0, max: 6, step: 1 },
  },
  {
    cssVar: "--r-control",
    label: "Control radius",
    group: "Shape",
    kind: "length",
    themed: false,
    // One pixel: enough that the corner is not a hairline artefact, not enough to read as a card.
    default: { dark: "1px" },
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
    default: { dark: "2" },
    range: { min: 0.5, max: 3, step: 0.1 },
  },
];

// The groups in panel order.
export const DEV_TOKEN_GROUPS = [
  "Accent",
  "Surfaces",
  "Drawing",
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
