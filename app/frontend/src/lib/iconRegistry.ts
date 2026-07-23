/**
 * The icon registry: the single source of truth for every glyph the app draws. One entry per icon
 * id (dot-namespaced, mirroring the copy/dev id schemes), each carrying the inner SVG markup as a
 * string so the glyph is reproduced pixel-for-pixel by <Icon id="...">. Built from
 * `.planning/phases/02-icon-editor/icons.json` (the 57-icon inventory) and the real SVG bodies
 * lifted verbatim from their source components (components/icons.tsx, Rail.tsx, PartsList.tsx,
 * DetailPanel.tsx, SearchOverlay.tsx, CompletePartModal.tsx, ProjectsPage.tsx, Finder.tsx,
 * DevPanel.tsx).
 *
 * Categories:
 *  - primary : the shared line-icon set (the icons.tsx `Svg` helper + the rail `svgProps` glyphs).
 *              Rendered through one preset: class `.ico` (so `--icon-stroke` retunes the whole set),
 *              viewBox 0 0 24 24, fill none, stroke currentColor, round caps/joins. Only `strokeWidth`
 *              (1.9 for the icons.tsx set, 2 for the rail set) and `body` vary per entry; size comes
 *              from the call-site className.
 *  - bespoke : one-off inline svgs, each with its own width/size + stroke weight. The root
 *              presentation (size / fill / stroke / weight / caps) is stored per entry so <Icon>
 *              reproduces it exactly.
 *  - art     : the file-card line drawings (schematic / footprint / 3D cube) that theme through
 *              --c-icon-* vars carried on inner groups (or the root, for the cube).
 *  - brand   : the Stockroom wordmark (a stroked mark) plus the LinkedIn / GitHub fill logos.
 *
 * NOTE: `body` strings use real SVG attribute syntax (kebab-case: stroke-width, stroke-linecap, ...)
 * because <Icon> injects them as markup, not as JSX. The listed schema fields are
 * `{ id, category, viewBox, size?, strokeWidth?, body }`; the extra optional presentation fields
 * (fill/stroke/caps/style) exist only so the non-primary categories render byte-faithfully - a
 * primary entry never needs them.
 */
import type { CSSProperties } from "react";

export type IconCategory = "primary" | "bespoke" | "art" | "brand";

export interface IconEntry {
  /** Stable, dot-namespaced id (the persistence key; see icon.overrides.ts / <Icon id="...">). */
  id: string;
  /** Which rendering family this glyph belongs to. */
  category: IconCategory;
  /** The svg viewBox, e.g. "0 0 24 24". */
  viewBox: string;
  /**
   * Default rendered pixel size for a non-primary glyph: a number for square, [w, h] for
   * rectangular. Omitted for primary icons (and any glyph whose source sized it purely by
   * className), which take their size from the call-site className.
   */
  size?: number | [number, number];
  /** SVG root stroke-width. Primary: the shared set's weight (fallback for `.ico`). */
  strokeWidth?: number;
  /** SVG root fill (non-primary only; primary is always fill="none"). */
  fill?: string;
  /** SVG root stroke (non-primary only; primary is always stroke="currentColor"). */
  stroke?: string;
  /** SVG root stroke-linecap (non-primary only; primary is always "round"). */
  strokeLinecap?: "round" | "butt" | "square";
  /** SVG root stroke-linejoin (non-primary only; primary is always "round"). */
  strokeLinejoin?: "round" | "miter" | "bevel";
  /** SVG root inline style (non-primary only; used by the cube art to route a theme var to stroke). */
  style?: CSSProperties;
  /** The inner SVG markup (paths / shapes / groups) as a string, lifted verbatim from the source. */
  body: string;
}

export const ICON_REGISTRY: IconEntry[] = [
  // ---- primary: the icons.tsx `Svg` helper set (viewBox 24, strokeWidth 1.9, class .ico) --------
  {
    id: "nav.library",
    category: "primary",
    viewBox: "0 0 24 24",
    strokeWidth: 1.9,
    body:
      '<rect x="3" y="4" width="7" height="16" rx="1"/>' +
      '<rect x="14" y="4" width="7" height="16" rx="1"/>' +
      '<path d="M6.5 8h0M6.5 12h0M17.5 8h0M17.5 12h0"/>',
  },
  {
    id: "action.add",
    category: "primary",
    viewBox: "0 0 24 24",
    strokeWidth: 1.9,
    body: '<path d="M12 5v14M5 12h14"/>',
  },
  {
    id: "action.duplicate",
    category: "primary",
    viewBox: "0 0 24 24",
    strokeWidth: 1.9,
    body:
      '<rect x="9" y="9" width="11" height="11" rx="2"/>' +
      '<path d="M5 15V5a2 2 0 0 1 2-2h8"/>',
  },
  {
    id: "nav.projects.alt",
    category: "primary",
    viewBox: "0 0 24 24",
    strokeWidth: 1.9,
    body: '<path d="M12 3l9 5-9 5-9-5 9-5Z"/><path d="M3 13l9 5 9-5"/>',
  },
  {
    id: "action.doctor",
    category: "primary",
    viewBox: "0 0 24 24",
    strokeWidth: 1.9,
    body: '<path d="M3 12h4l2 5 4-12 2 7h6"/>',
  },
  {
    id: "action.settings",
    category: "primary",
    viewBox: "0 0 24 24",
    strokeWidth: 1.9,
    body:
      '<circle cx="12" cy="12" r="3"/>' +
      '<path d="M12 2v3M12 19v3M4.2 4.2l2.1 2.1M17.7 17.7l2.1 2.1M2 12h3M19 12h3M4.2 19.8l2.1-2.1M17.7 6.3l2.1-2.1"/>',
  },
  {
    id: "action.download",
    category: "primary",
    viewBox: "0 0 24 24",
    strokeWidth: 1.9,
    body: '<path d="M12 3v12M7 10l5 5 5-5"/><path d="M4 20h16"/>',
  },
  {
    id: "action.build",
    category: "primary",
    viewBox: "0 0 24 24",
    strokeWidth: 1.9,
    body: '<path d="M7 4v16l13-8Z"/>',
  },
  {
    id: "action.refresh",
    category: "primary",
    viewBox: "0 0 24 24",
    strokeWidth: 1.9,
    body:
      '<path d="M20 11a8 8 0 0 0-14-4.5L3 9M4 13a8 8 0 0 0 14 4.5L21 15"/>' +
      '<path d="M3 4v5h5M21 20v-5h-5"/>',
  },
  {
    id: "action.edit",
    category: "primary",
    viewBox: "0 0 24 24",
    strokeWidth: 1.9,
    body:
      '<path d="M4 20h4L18.5 9.5a2.1 2.1 0 0 0-3-3L5 17v3Z"/>' +
      '<path d="M13.5 6.5l3 3"/>',
  },
  {
    id: "action.trash",
    category: "primary",
    viewBox: "0 0 24 24",
    strokeWidth: 1.9,
    body:
      '<path d="M4 7h16M9 7V5a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2M6 7l1 13a1 1 0 0 0 1 1h8a1 1 0 0 0 1-1l1-13"/>',
  },
  {
    id: "action.enrich",
    category: "primary",
    viewBox: "0 0 24 24",
    strokeWidth: 1.9,
    body:
      '<path d="M12 3l1.8 4.7L18.5 9.5 13.8 11.3 12 16l-1.8-4.7L5.5 9.5 10.2 7.7 12 3Z"/>' +
      '<path d="M19 15l.7 1.8L21.5 17.5l-1.8.7L19 20l-.7-1.8L16.5 17.5l1.8-.7L19 15Z"/>',
  },
  {
    id: "action.git",
    category: "primary",
    viewBox: "0 0 24 24",
    strokeWidth: 1.9,
    body:
      '<circle cx="6" cy="6" r="2.5"/>' +
      '<circle cx="6" cy="18" r="2.5"/>' +
      '<circle cx="18" cy="8" r="2.5"/>' +
      '<path d="M6 8.5v7M18 10.5c0 4-4 3.5-6 5.5"/>',
  },
  {
    id: "nav.board",
    category: "primary",
    viewBox: "0 0 24 24",
    strokeWidth: 1.9,
    body:
      '<rect x="4" y="4" width="16" height="16" rx="2"/>' +
      '<circle cx="9" cy="9" r="1.3"/>' +
      '<circle cx="15" cy="15" r="1.3"/>' +
      '<path d="M9 10.3v3.4M15 10.3v3.4M10.3 9h3.4"/>',
  },

  // ---- primary: the rail `svgProps` nav glyphs (viewBox 24, strokeWidth 2, class .ico) ----------
  {
    id: "nav.components",
    category: "primary",
    viewBox: "0 0 24 24",
    strokeWidth: 2,
    body:
      '<path d="M12 20v2"/><path d="M12 2v2"/><path d="M17 20v2"/><path d="M17 2v2"/>' +
      '<path d="M2 12h2"/><path d="M2 17h2"/><path d="M2 7h2"/><path d="M20 12h2"/>' +
      '<path d="M20 17h2"/><path d="M20 7h2"/><path d="M7 20v2"/><path d="M7 2v2"/>' +
      '<rect x="4" y="4" width="16" height="16" rx="2"/>' +
      '<rect x="8" y="8" width="8" height="8" rx="1"/>',
  },
  {
    id: "nav.projects",
    category: "primary",
    viewBox: "0 0 24 24",
    strokeWidth: 2,
    body:
      '<rect width="18" height="18" x="3" y="3" rx="2"/>' +
      '<path d="M11 9h4a2 2 0 0 0 2-2V3"/>' +
      '<circle cx="9" cy="9" r="2"/>' +
      '<path d="M7 21v-4a2 2 0 0 1 2-2h4"/>' +
      '<circle cx="15" cy="15" r="2"/>',
  },
  {
    id: "nav.settings",
    category: "primary",
    viewBox: "0 0 24 24",
    strokeWidth: 2,
    body:
      '<path d="M9.671 4.136a2.34 2.34 0 0 1 4.659 0 2.34 2.34 0 0 0 3.319 1.915 2.34 2.34 0 0 1 2.33 4.033 2.34 2.34 0 0 0 0 3.831 2.34 2.34 0 0 1-2.33 4.033 2.34 2.34 0 0 0-3.319 1.915 2.34 2.34 0 0 1-4.659 0 2.34 2.34 0 0 0-3.32-1.915 2.34 2.34 0 0 1-2.33-4.033 2.34 2.34 0 0 0 0-3.831A2.34 2.34 0 0 1 6.35 6.051a2.34 2.34 0 0 0 3.319-1.915"/>' +
      '<circle cx="12" cy="12" r="3"/>',
  },
  {
    id: "nav.about",
    category: "primary",
    viewBox: "0 0 24 24",
    strokeWidth: 2,
    body: '<circle cx="12" cy="12" r="10"/><path d="M12 16v-4M12 8h.01"/>',
  },
  {
    id: "nav.update",
    category: "primary",
    viewBox: "0 0 24 24",
    strokeWidth: 2,
    body: '<path d="M12 17V3"/><path d="m6 11 6 6 6-6"/><path d="M19 21H5"/>',
  },
  {
    // The idle "Up to Date" check. Its --c-ok tint is a call-site inline style (color), not glyph
    // geometry, so the registry stores the plain check; the tint is reapplied where it is placed.
    id: "nav.up-to-date",
    category: "primary",
    viewBox: "0 0 24 24",
    strokeWidth: 2,
    body: '<path d="M20 6 9 17l-5-5"/>',
  },
  {
    id: "nav.theme",
    category: "primary",
    viewBox: "0 0 24 24",
    strokeWidth: 2,
    body:
      '<circle cx="12" cy="12" r="4"/>' +
      '<path d="M12 2v2"/><path d="M12 20v2"/>' +
      '<path d="m4.93 4.93 1.41 1.41"/><path d="m17.66 17.66 1.41 1.41"/>' +
      '<path d="M2 12h2"/><path d="M20 12h2"/>' +
      '<path d="m6.34 17.66-1.41 1.41"/><path d="m19.07 4.93-1.41 1.41"/>',
  },

  // ---- bespoke: the icons.tsx one-off exports (each its own size + weight) ----------------------
  {
    id: "action.search",
    category: "bespoke",
    viewBox: "0 0 24 24",
    size: 14,
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 2,
    body: '<circle cx="11" cy="11" r="7"/><path d="M21 21l-4.3-4.3"/>',
  },
  {
    id: "status.warn",
    category: "bespoke",
    viewBox: "0 0 24 24",
    size: 15,
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 2,
    body:
      '<path d="M12 3.4l9.3 16.1H2.7z" stroke-linejoin="round"/>' +
      '<path d="M12 10v4.2" stroke-linecap="round"/>' +
      '<circle cx="12" cy="17.4" r="0.5" fill="currentColor" stroke="none"/>',
  },
  {
    id: "status.info",
    category: "bespoke",
    viewBox: "0 0 24 24",
    size: 15,
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 2,
    body:
      '<circle cx="12" cy="12" r="9"/>' +
      '<path d="M12 11v5" stroke-linecap="round"/>' +
      '<circle cx="12" cy="7.8" r="0.6" fill="currentColor" stroke="none"/>',
  },
  {
    id: "action.upload",
    category: "bespoke",
    viewBox: "0 0 24 24",
    size: 24,
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 1.4,
    body:
      '<path d="M12 15V3m0 0L8 7m4-4l4 4"/>' +
      '<path d="M4 17v2a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-2"/>',
  },
  {
    id: "action.close",
    category: "bespoke",
    viewBox: "0 0 24 24",
    size: 15,
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 1.8,
    body: '<path d="M6 6l12 12M18 6L6 18" stroke-linecap="round"/>',
  },
  {
    id: "nav.back",
    category: "bespoke",
    viewBox: "0 0 24 24",
    size: 15,
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 1.8,
    body: '<path d="M15 5l-7 7 7 7" stroke-linecap="round" stroke-linejoin="round"/>',
  },
  {
    id: "action.external",
    category: "bespoke",
    viewBox: "0 0 24 24",
    size: 13,
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 2,
    body:
      '<path d="M14 4h6v6M20 4l-9 9M18 13v5a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h5" stroke-linecap="round" stroke-linejoin="round"/>',
  },

  // ---- bespoke: SearchOverlay inline glyphs -----------------------------------------------------
  {
    id: "overlay.chevron",
    category: "bespoke",
    viewBox: "0 0 24 24",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 2,
    strokeLinecap: "round",
    strokeLinejoin: "round",
    body: '<path d="m6 9 6 6 6-6"/>',
  },
  {
    id: "overlay.check",
    category: "bespoke",
    viewBox: "0 0 24 24",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 3.4,
    strokeLinecap: "round",
    strokeLinejoin: "round",
    body: '<path d="M20 6 9 17l-5-5"/>',
  },
  {
    id: "overlay.close",
    category: "bespoke",
    viewBox: "0 0 24 24",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 2.4,
    strokeLinecap: "round",
    body: '<path d="M18 6 6 18M6 6l12 12"/>',
  },
  {
    id: "overlay.spark",
    category: "bespoke",
    viewBox: "0 0 24 24",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 2,
    strokeLinecap: "round",
    strokeLinejoin: "round",
    body:
      '<path d="M9.94 15.5A2 2 0 0 0 8.5 14.06l-6.14-1.58a.5.5 0 0 1 0-.96L8.5 9.94A2 2 0 0 0 9.94 8.5l1.58-6.14a.5.5 0 0 1 .96 0L14.06 8.5A2 2 0 0 0 15.5 9.94l6.14 1.58a.5.5 0 0 1 0 .96L15.5 14.06a2 2 0 0 0-1.44 1.44l-1.58 6.14a.5.5 0 0 1-.96 0z"/>',
  },

  // ---- bespoke: PartsList category row thumbnails (viewBox 32x18, weight 1.6) --------------------
  {
    id: "glyph.resistor",
    category: "bespoke",
    viewBox: "0 0 32 18",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 1.6,
    strokeLinecap: "round",
    strokeLinejoin: "round",
    body: '<path d="M2 9h5l1.5-4 3 8 3-8 3 8 1.5-4H32"/>',
  },
  {
    id: "glyph.capacitor",
    category: "bespoke",
    viewBox: "0 0 32 18",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 1.6,
    strokeLinecap: "round",
    strokeLinejoin: "round",
    body: '<path d="M2 9h11M19 9h11M13 3v12M19 3v12"/>',
  },
  {
    id: "glyph.inductor",
    category: "bespoke",
    viewBox: "0 0 32 18",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 1.6,
    strokeLinecap: "round",
    strokeLinejoin: "round",
    body: '<path d="M2 9h4a3 3 0 0 1 6 0 3 3 0 0 1 6 0 3 3 0 0 1 6 0h4"/>',
  },
  {
    id: "glyph.diode",
    category: "bespoke",
    viewBox: "0 0 32 18",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 1.6,
    strokeLinecap: "round",
    strokeLinejoin: "round",
    body: '<path d="M2 9h10M20 9h10M12 4v10l8-5-8-5zM20 4v10"/>',
  },
  {
    id: "glyph.connector",
    category: "bespoke",
    viewBox: "0 0 32 18",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 1.6,
    strokeLinecap: "round",
    strokeLinejoin: "round",
    body: '<rect x="4" y="4" width="24" height="10" rx="2"/><path d="M10 14v2M16 14v2M22 14v2"/>',
  },
  {
    id: "glyph.crystal",
    category: "bespoke",
    viewBox: "0 0 32 18",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 1.6,
    strokeLinecap: "round",
    strokeLinejoin: "round",
    body: '<rect x="9" y="4" width="14" height="10" rx="4"/><path d="M2 9h7M23 9h7"/>',
  },
  {
    id: "glyph.ic",
    category: "bespoke",
    viewBox: "0 0 32 18",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 1.6,
    strokeLinecap: "round",
    strokeLinejoin: "round",
    body:
      '<rect x="9" y="3" width="14" height="12" rx="1.5"/>' +
      '<path d="M6 6h3M6 9h3M6 12h3M23 6h3M23 9h3M23 12h3"/>',
  },

  // ---- bespoke: ProjectsPage card thumbnail -----------------------------------------------------
  {
    id: "glyph.project",
    category: "bespoke",
    viewBox: "0 0 24 24",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 1.8,
    strokeLinecap: "round",
    strokeLinejoin: "round",
    body:
      '<rect x="3" y="3" width="18" height="18" rx="2"/>' +
      '<path d="M9 3v18M15 3v18M3 9h18M3 15h18" opacity="0.55"/>',
  },

  // ---- bespoke: CompletePartModal glyphs --------------------------------------------------------
  {
    id: "modal.check",
    category: "bespoke",
    viewBox: "0 0 24 24",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 3,
    strokeLinecap: "round",
    strokeLinejoin: "round",
    body: '<path d="M20 6 9 17l-5-5"/>',
  },
  {
    id: "modal.close",
    category: "bespoke",
    viewBox: "0 0 24 24",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 2.2,
    strokeLinecap: "round",
    body: '<path d="M18 6 6 18M6 6l12 12"/>',
  },

  // ---- bespoke: DetailPanel glyphs --------------------------------------------------------------
  {
    id: "detail.chevron-right",
    category: "bespoke",
    viewBox: "0 0 24 24",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 2.2,
    strokeLinecap: "round",
    strokeLinejoin: "round",
    body: '<path d="m9 18 6-6-6-6"/>',
  },
  {
    id: "detail.rename",
    category: "bespoke",
    viewBox: "0 0 24 24",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 2,
    strokeLinecap: "round",
    strokeLinejoin: "round",
    body: '<path d="M12 20h9"/><path d="M16.5 3.5a2.12 2.12 0 0 1 3 3L7 19l-4 1 1-4Z"/>',
  },
  {
    // The part-ready check: its --c-ok tint is a root stroke here (not currentColor), so it is
    // stored on the entry and reproduced verbatim.
    id: "detail.ready-check",
    category: "bespoke",
    viewBox: "0 0 24 24",
    fill: "none",
    stroke: "var(--c-ok)",
    strokeWidth: 3,
    strokeLinecap: "round",
    strokeLinejoin: "round",
    body: '<path d="M20 6 9 17l-5-5"/>',
  },
  {
    id: "detail.select-chevron",
    category: "bespoke",
    viewBox: "0 0 16 16",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 1.5,
    body: '<path d="M4 6l4 4 4-4" stroke-linecap="round" stroke-linejoin="round"/>',
  },
  {
    // The Filing row's folder mark (lucide folder-open, ISC).
    id: "detail.filing-folder",
    category: "bespoke",
    viewBox: "0 0 24 24",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 2,
    strokeLinecap: "round",
    strokeLinejoin: "round",
    body: '<path d="m6 14 1.5-2.9A2 2 0 0 1 9.24 10H20a2 2 0 0 1 1.94 2.5l-1.54 6a2 2 0 0 1-1.95 1.5H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h3.9a2 2 0 0 1 1.69.9l.81 1.2a2 2 0 0 0 1.67.9H18a2 2 0 0 1 2 2v2"/>',
  },
  {
    id: "detail.tag-remove",
    category: "bespoke",
    viewBox: "0 0 24 24",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 2.4,
    strokeLinecap: "round",
    body: '<path d="M18 6 6 18M6 6l12 12"/>',
  },
  {
    id: "detail.tag-add",
    category: "bespoke",
    viewBox: "0 0 24 24",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 2.2,
    strokeLinecap: "round",
    body: '<path d="M12 5v14M5 12h14"/>',
  },

  // ---- bespoke: Finder filter toggle ------------------------------------------------------------
  {
    id: "finder.filter",
    category: "bespoke",
    viewBox: "0 0 24 24",
    size: 15,
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 2,
    body: '<path d="M3 5h18M6 12h12M10 19h4" stroke-linecap="round"/>',
  },

  // ---- bespoke: DevPanel glyphs -----------------------------------------------------------------
  {
    id: "dev.reset",
    category: "bespoke",
    viewBox: "0 0 24 24",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 2.2,
    strokeLinecap: "round",
    strokeLinejoin: "round",
    body: '<path d="M3 12a9 9 0 1 0 3-6.7L3 8"/><path d="M3 3v5h5"/>',
  },
  {
    id: "dev.close",
    category: "bespoke",
    viewBox: "0 0 24 24",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 2.2,
    strokeLinecap: "round",
    body: '<path d="M18 6 6 18M6 6l12 12"/>',
  },

  // ---- art: the file-card line drawings ---------------------------------------------------------
  {
    id: "art.symbol",
    category: "art",
    viewBox: "0 0 132 94",
    size: [132, 94],
    body:
      '<g style="stroke:var(--c-icon-line)" stroke-width="1.5" fill="none">' +
      '<rect x="40" y="20" width="52" height="54" rx="3"/>' +
      '<path d="M40 33H24M40 47H24M40 61H24M92 33h16M92 47h16M92 61h16"/>' +
      "</g>",
  },
  {
    id: "art.footprint",
    category: "art",
    viewBox: "0 0 132 94",
    size: [132, 94],
    body:
      '<g style="fill:var(--c-icon-fill)">' +
      '<rect x="34" y="26" width="9" height="7" rx="1"/>' +
      '<rect x="48" y="26" width="9" height="7" rx="1"/>' +
      '<rect x="62" y="26" width="9" height="7" rx="1"/>' +
      '<rect x="76" y="26" width="9" height="7" rx="1"/>' +
      '<rect x="90" y="26" width="9" height="7" rx="1"/>' +
      '<rect x="34" y="61" width="9" height="7" rx="1"/>' +
      '<rect x="48" y="61" width="9" height="7" rx="1"/>' +
      '<rect x="62" y="61" width="9" height="7" rx="1"/>' +
      '<rect x="76" y="61" width="9" height="7" rx="1"/>' +
      '<rect x="90" y="61" width="9" height="7" rx="1"/>' +
      "</g>" +
      '<rect x="38" y="37" width="60" height="20" rx="2" fill="none" style="stroke:var(--c-icon-edge)" stroke-width="1.3"/>',
  },
  {
    id: "art.model",
    category: "art",
    viewBox: "0 0 90 90",
    size: [70, 70],
    fill: "none",
    strokeWidth: 1.4,
    style: { stroke: "var(--c-icon-cube)" },
    body:
      '<path d="M45 12l30 17v32L45 78 15 61V29z"/>' +
      '<path d="M45 12v18M45 30l30-17M45 30L15 13" opacity="0.5"/>',
  },

  // ---- brand: the wordmark + social fill marks --------------------------------------------------
  {
    // The Stockroom shipping-box mark. Drawn like the primary set (svgProps: fill none, stroke
    // currentColor, weight 2, round caps) and carries `.ico` at its call sites; kept in the brand
    // category per the inventory.
    id: "brand.wordmark",
    category: "brand",
    viewBox: "0 0 24 24",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 2,
    strokeLinecap: "round",
    strokeLinejoin: "round",
    body:
      '<path d="M11 21.73a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73z"/>' +
      '<path d="M12 22V12"/>' +
      '<polyline points="3.29 7 12 12 20.71 7"/>' +
      '<path d="m7.5 4.27 9 5.15"/>',
  },
  {
    id: "brand.linkedin",
    category: "brand",
    viewBox: "0 0 24 24",
    fill: "currentColor",
    body:
      '<path d="M20.45 20.45h-3.56v-5.57c0-1.33-.02-3.04-1.85-3.04-1.85 0-2.14 1.45-2.14 2.94v5.67H9.35V9h3.42v1.56h.05c.48-.9 1.64-1.85 3.37-1.85 3.6 0 4.27 2.37 4.27 5.46v6.28zM5.34 7.43a2.06 2.06 0 1 1 0-4.13 2.06 2.06 0 0 1 0 4.13zM7.12 20.45H3.55V9h3.57v11.45zM22.22 0H1.77C.79 0 0 .77 0 1.73v20.54C0 23.22.79 24 1.77 24h20.45c.98 0 1.78-.78 1.78-1.73V1.73C24 .77 23.2 0 22.22 0z"/>',
  },
  {
    id: "brand.github",
    category: "brand",
    viewBox: "0 0 24 24",
    fill: "currentColor",
    body:
      '<path d="M12 .5C5.37.5 0 5.87 0 12.5c0 5.3 3.44 9.8 8.21 11.39.6.11.82-.26.82-.58l-.02-2.05c-3.34.73-4.04-1.61-4.04-1.61-.55-1.39-1.33-1.76-1.33-1.76-1.09-.74.08-.73.08-.73 1.2.09 1.84 1.24 1.84 1.24 1.07 1.83 2.8 1.3 3.49.99.11-.78.42-1.3.76-1.6-2.67-.3-5.47-1.34-5.47-5.96 0-1.32.47-2.39 1.24-3.23-.13-.31-.54-1.53.12-3.18 0 0 1.01-.32 3.3 1.23a11.5 11.5 0 0 1 6.01 0c2.29-1.55 3.3-1.23 3.3-1.23.66 1.65.25 2.87.12 3.18.77.84 1.24 1.91 1.24 3.23 0 4.63-2.8 5.65-5.48 5.95.43.37.81 1.1.81 2.22l-.01 3.29c0 .32.21.7.82.58A12.01 12.01 0 0 0 24 12.5C24 5.87 18.63.5 12 .5z"/>',
  },
];

/** Every icon id resolved to its entry (the primary lookup path for <Icon>). */
export const ICON_BY_ID: Map<string, IconEntry> = new Map(
  ICON_REGISTRY.map((entry) => [entry.id, entry]),
);

/** The category names, in inventory order. */
export const ICON_CATEGORIES: IconCategory[] = ["primary", "bespoke", "art", "brand"];

/** Icon ids grouped by category (inventory order), for the catalogue / glyph picker. */
export const ICON_IDS_BY_CATEGORY: Record<IconCategory, string[]> = ICON_CATEGORIES.reduce(
  (acc, category) => {
    acc[category] = ICON_REGISTRY.filter((entry) => entry.category === category).map(
      (entry) => entry.id,
    );
    return acc;
  },
  { primary: [], bespoke: [], art: [], brand: [] } as Record<IconCategory, string[]>,
);
