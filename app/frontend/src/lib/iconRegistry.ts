/**
 * The icon registry: the single source of truth for every glyph the app draws. One entry per icon
 * id (dot-namespaced, mirroring the copy/dev id schemes), each carrying the inner SVG markup as a
 * string so the glyph is reproduced pixel-for-pixel by <Icon id="...">. Original source artwork
 * and promoted product semantics live here; production call sites reference only stable IDs.
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

/**
 * A selectable icon from a separately-loaded library. Unlike `IconEntry`, a catalogue entry is
 * not a persisted application icon id: choosing one stores its sanitised SVG body as the selected
 * application's existing icon override.
 */
export interface IconCatalogEntry {
  id: string;
  label: string;
  family: string;
  terms: readonly string[];
  body: string;
  viewBox: string;
}

/**
 * The owner-selected interface glyphs promoted from a laptop Design Studio document into product
 * defaults. The application ids remain ours; only their artwork changes. Exact catalogue identity,
 * pinned version and licence are recorded in assets/interface-icons/README.md.
 */
const OWNER_SELECTED_INTERFACE_BODIES = {
  "action.external": '<g transform="translate(0 0) scale(1)" fill="currentColor" stroke="none"><path fill="currentColor" d="M17 3.34a10 10 0 1 1-14.995 8.984L2 12l.005-.324A10 10 0 0 1 17 3.34M15 8H9l-.117.007A1 1 0 0 0 8 9l.007.117A1 1 0 0 0 9 10h3.584l-4.291 4.293l-.083.094a1 1 0 0 0 1.497 1.32L14 11.414V15l.007.117A1 1 0 0 0 16 15V9l-.007-.117l-.029-.149l-.035-.105l-.054-.113l-.071-.111a1 1 0 0 0-.097-.112l-.09-.08l-.096-.067l-.098-.052l-.11-.044l-.112-.03l-.126-.017z"/></g>',
  "brand.wordmark": '<g transform="translate(0 2.4000000000000004) scale(0.0375)" fill="currentColor" stroke="none"><path d="M560.3 237.2c10.4 11.8 28.3 14.4 41.8 5.5 14.7-9.8 18.7-29.7 8.9-44.4l-48-72c-2.8-4.2-6.6-7.7-11.1-10.2L351.4 4.7c-19.3-10.7-42.8-10.7-62.2 0L88.8 116c-5.4 3-9.7 7.4-12.6 12.8L27.7 218.7c-12.6 23.4-3.8 52.5 19.6 65.1l33 17.7 0 53.3c0 23 12.4 44.3 32.4 55.7l176 99.7c19.6 11.1 43.5 11.1 63.1 0l176-99.7c20.1-11.4 32.4-32.6 32.4-55.7l0-117.5zm-240-9.8L170.2 144 320.3 60.6 470.4 144 320.3 227.4zm-41.5 50.2l-21.3 46.2-165.8-88.8 25.4-47.2 161.7 89.8z"/></g>',
  "nav.about": '<g transform="translate(0 0) scale(1)" fill="currentColor" stroke="none"><path fill="currentColor" d="M12.713 16.713Q13 16.425 13 16v-4q0-.425-.288-.712T12 11t-.712.288T11 12v4q0 .425.288.713T12 17t.713-.288m0-8Q13 8.425 13 8t-.288-.712T12 7t-.712.288T11 8t.288.713T12 9t.713-.288M12 22q-2.075 0-3.9-.788t-3.175-2.137T2.788 15.9T2 12t.788-3.9t2.137-3.175T8.1 2.788T12 2t3.9.788t3.175 2.137T21.213 8.1T22 12t-.788 3.9t-2.137 3.175t-3.175 2.138T12 22"/></g>',
  "nav.board": '<g transform="translate(1.5 0) scale(0.046875)" fill="currentColor" stroke="none"><path d="M335.1 16c20.7 0 40.1 10 52.1 26.8l48.9 68.5c7.7 10.8 11.9 23.9 11.9 37.2L448 416c0 35.3-28.7 64-64 64l-320 0-6.5-.3C25.2 476.4 0 449.1 0 416L0 148.5c0-11.7 3.2-23.1 9.2-33l2.7-4.2 48.9-68.5c10.5-14.7 26.7-24.2 44.4-26.3l7.7-.5 222.1 0zM248 128l121.3 0-34.3-48-87.1 0 0 48zM78.7 128l121.3 0 0-48-87.1 0-34.3 48z"/></g>',
  "nav.collapse-rail": '<g transform="translate(0 0) scale(1)" fill="currentColor" stroke="none"><path fill="currentColor" d="M12 2q-.327 0-.642.005l-.616.017l-.299.013l-.579.034l-.553.046c-4.785.464-6.732 2.411-7.196 7.196l-.046.553l-.034.579q-.008.147-.013.299l-.017.616l-.004.318L2 12q0 .327.005.642l.017.616l.013.299l.034.579l.046.553c.464 4.785 2.411 6.732 7.196 7.196l.553.046l.579.034q.147.008.299.013l.616.017L12 22l.642-.005l.616-.017l.299-.013l.579-.034l.553-.046c4.785-.464 6.732-2.411 7.196-7.196l.046-.553l.034-.579q.008-.147.013-.299l.017-.616L22 12l-.005-.642l-.017-.616l-.013-.299l-.034-.579l-.046-.553c-.464-4.785-2.411-6.732-7.196-7.196l-.553-.046l-.579-.034l-.299-.013l-.616-.017l-.318-.004zm-1.707 6.293a1 1 0 0 1 1.32-.083l.094.083l3 3a1 1 0 0 1 .083 1.32l-.083.094l-3 3a1 1 0 0 1-1.497-1.32l.083-.094L12.585 12l-2.292-2.293a1 1 0 0 1-.083-1.32z"/></g>',
  "nav.components": '<g transform="translate(0 0) scale(1)" fill="currentColor" stroke="none"><path fill="currentColor" d="M7.5 22q-1.45 0-2.475-1.025T4 18.5v-13q0-1.45 1.025-2.475T7.5 2H18q.825 0 1.413.587T20 4v12.525q0 .2-.162.363t-.588.362q-.35.175-.55.5t-.2.75t.2.763t.55.487t.55.413t.2.562v.25q0 .425-.288.725T19 22zm2.213-7.288Q10 14.425 10 14V5q0-.425-.288-.712T9 4t-.712.288T8 5v9q0 .425.288.713T9 15t.713-.288M7.5 20h9.325q-.15-.35-.237-.712T16.5 18.5q0-.4.075-.775t.25-.725H7.5q-.65 0-1.075.438T6 18.5q0 .65.425 1.075T7.5 20"/></g>',
  "nav.settings": '<g transform="translate(0 0) scale(0.09375)" fill="currentColor" stroke="none"><path fill="currentColor" d="M237.94 107.21a8 8 0 0 0-3.89-5.4l-29.83-17l-.12-33.62a8 8 0 0 0-2.83-6.08a111.9 111.9 0 0 0-36.72-20.67a8 8 0 0 0-6.46.59L128 41.85L97.88 25a8 8 0 0 0-6.47-.6a111.9 111.9 0 0 0-36.68 20.75a8 8 0 0 0-2.83 6.07l-.15 33.65l-29.83 17a8 8 0 0 0-3.89 5.4a106.5 106.5 0 0 0 0 41.56a8 8 0 0 0 3.89 5.4l29.83 17l.12 33.63a8 8 0 0 0 2.83 6.08a111.9 111.9 0 0 0 36.72 20.67a8 8 0 0 0 6.46-.59L128 214.15L158.12 231a7.9 7.9 0 0 0 3.9 1a8.1 8.1 0 0 0 2.57-.42a112.1 112.1 0 0 0 36.68-20.73a8 8 0 0 0 2.83-6.07l.15-33.65l29.83-17a8 8 0 0 0 3.89-5.4a106.5 106.5 0 0 0-.03-41.52M128 168a40 40 0 1 1 40-40a40 40 0 0 1-40 40"/></g>',
  "nav.stm": '<g transform="translate(0 0) scale(0.046875)" fill="currentColor" stroke="none"><path d="M176 24c0-13.3-10.7-24-24-24s-24 10.7-24 24l0 40c-35.3 0-64 28.7-64 64l-40 0c-13.3 0-24 10.7-24 24s10.7 24 24 24l40 0 0 56-40 0c-13.3 0-24 10.7-24 24s10.7 24 24 24l40 0 0 56-40 0c-13.3 0-24 10.7-24 24s10.7 24 24 24l40 0c0 35.3 28.7 64 64 64l0 40c0 13.3 10.7 24 24 24s24-10.7 24-24l0-40 56 0 0 40c0 13.3 10.7 24 24 24s24-10.7 24-24l0-40 56 0 0 40c0 13.3 10.7 24 24 24s24-10.7 24-24l0-40c35.3 0 64-28.7 64-64l40 0c13.3 0 24-10.7 24-24s-10.7-24-24-24l-40 0 0-56 40 0c13.3 0 24-10.7 24-24s-10.7-24-24-24l-40 0 0-56 40 0c13.3 0 24-10.7 24-24s-10.7-24-24-24l-40 0c0-35.3-28.7-64-64-64l0-40c0-13.3-10.7-24-24-24s-24 10.7-24 24l0 40-56 0 0-40c0-13.3-10.7-24-24-24s-24 10.7-24 24l0 40-56 0 0-40zM160 128l192 0c17.7 0 32 14.3 32 32l0 192c0 17.7-14.3 32-32 32l-192 0c-17.7 0-32-14.3-32-32l0-192c0-17.7 14.3-32 32-32zm16 48l0 160 160 0 0-160-160 0z"/></g>',
  "nav.theme": '<g transform="translate(0 0) scale(0.09375)" fill="currentColor" stroke="none"><path fill="currentColor" d="M235.54 150.21a104.84 104.84 0 0 1-37 52.91A104 104 0 0 1 32 120a103.1 103.1 0 0 1 20.88-62.52a104.84 104.84 0 0 1 52.91-37a8 8 0 0 1 10 10a88.08 88.08 0 0 0 109.8 109.8a8 8 0 0 1 10 10Z"/></g>',
  "nav.update": '<g transform="translate(0 0) scale(1)" fill="currentColor" stroke="none"><path fill="currentColor" d="m9 5l-.117.007A1 1 0 0 0 8 6v4.999L5.414 11A2 2 0 0 0 4 14.414L10.586 21a2 2 0 0 0 2.828 0L20 14.414a2 2 0 0 0 .434-2.18l-.068-.145A2 2 0 0 0 18.586 11L16 10.999V6a1 1 0 0 0-1-1zm6-3a1 1 0 0 1 .117 1.993L15 4H9a1 1 0 0 1-.117-1.993L9 2z"/></g>',
} as const;

export const ICON_REGISTRY: IconEntry[] = [
  // ---- primary: the icons.tsx `Svg` helper set (viewBox 24, strokeWidth 1.9, class .ico) --------
  {
    id: "nav.library",
    category: "primary",
    viewBox: "0 0 24 24",
    strokeWidth: 1.9,
    body: '<path d="m16 6 4 14"/><path d="M12 6v14"/><path d="M8 8v12"/><path d="M4 4v16"/>',
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
    body: '<rect width="14" height="14" x="8" y="8" rx="2" ry="2"/><path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2"/>',
  },
  {
    id: "action.doctor",
    category: "primary",
    viewBox: "0 0 24 24",
    strokeWidth: 1.9,
    body: '<path d="M22 12h-2.48a2 2 0 0 0-1.93 1.46l-2.35 8.36a.25.25 0 0 1-.48 0L9.24 2.18a.25.25 0 0 0-.48 0l-2.35 8.36A2 2 0 0 1 4.49 12H2"/>',
  },
  {
    id: "action.settings",
    category: "primary",
    viewBox: "0 0 24 24",
    strokeWidth: 1.9,
    body: '<path d="M9.671 4.136a2.34 2.34 0 0 1 4.659 0 2.34 2.34 0 0 0 3.319 1.915 2.34 2.34 0 0 1 2.33 4.033 2.34 2.34 0 0 0 0 3.831 2.34 2.34 0 0 1-2.33 4.033 2.34 2.34 0 0 0-3.319 1.915 2.34 2.34 0 0 1-4.659 0 2.34 2.34 0 0 0-3.32-1.915 2.34 2.34 0 0 1-2.33-4.033 2.34 2.34 0 0 0 0-3.831A2.34 2.34 0 0 1 6.35 6.051a2.34 2.34 0 0 0 3.319-1.915"/><circle cx="12" cy="12" r="3"/>',
  },
  {
    id: "action.download",
    category: "primary",
    viewBox: "0 0 24 24",
    strokeWidth: 1.9,
    body: '<path d="M12 15V3"/><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><path d="m7 10 5 5 5-5"/>',
  },
  {
    id: "action.build",
    category: "primary",
    viewBox: "0 0 24 24",
    strokeWidth: 1.9,
    body: '<path d="M5 5a2 2 0 0 1 3.008-1.728l11.997 6.998a2 2 0 0 1 .003 3.458l-12 7A2 2 0 0 1 5 19z"/>',
  },
  {
    id: "action.refresh",
    category: "primary",
    viewBox: "0 0 24 24",
    strokeWidth: 1.9,
    body: '<path d="M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8"/><path d="M21 3v5h-5"/><path d="M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16"/><path d="M8 16H3v5"/>',
  },
  {
    id: "action.edit",
    category: "primary",
    viewBox: "0 0 24 24",
    strokeWidth: 1.9,
    body: '<path d="M21.174 6.812a1 1 0 0 0-3.986-3.987L3.842 16.174a2 2 0 0 0-.5.83l-1.321 4.352a.5.5 0 0 0 .623.622l4.353-1.32a2 2 0 0 0 .83-.497z"/><path d="m15 5 4 4"/>',
  },
  {
    id: "action.trash",
    category: "primary",
    viewBox: "0 0 24 24",
    strokeWidth: 1.9,
    body: '<path d="M10 11v6"/><path d="M14 11v6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6"/><path d="M3 6h18"/><path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>',
  },
  {
    id: "action.enrich",
    category: "primary",
    viewBox: "0 0 24 24",
    strokeWidth: 1.9,
    body: '<path d="M11.017 2.814a1 1 0 0 1 1.966 0l1.051 5.558a2 2 0 0 0 1.594 1.594l5.558 1.051a1 1 0 0 1 0 1.966l-5.558 1.051a2 2 0 0 0-1.594 1.594l-1.051 5.558a1 1 0 0 1-1.966 0l-1.051-5.558a2 2 0 0 0-1.594-1.594l-5.558-1.051a1 1 0 0 1 0-1.966l5.558-1.051a2 2 0 0 0 1.594-1.594z"/><path d="M20 2v4"/><path d="M22 4h-4"/><circle cx="4" cy="20" r="2"/>',
  },
  {
    id: "action.git",
    category: "primary",
    viewBox: "0 0 24 24",
    strokeWidth: 1.9,
    body: '<path d="M15 6a9 9 0 0 0-9 9V3"/><circle cx="18" cy="6" r="3"/><circle cx="6" cy="18" r="3"/>',
  },
  {
    id: "action.measure",
    category: "primary",
    viewBox: "0 0 24 24",
    strokeWidth: 1.9,
    body: '<path d="M3 15 15 3l6 6L9 21z"/><path d="m7 11 2 2m2-6 2 2m-4 8 2-2"/>',
  },
  {
    id: "action.maximize",
    category: "primary",
    viewBox: "0 0 24 24",
    strokeWidth: 1.9,
    body: '<path d="M8 3H3v5m13-5h5v5m0 8v5h-5M3 16v5h5"/>',
  },
  {
    id: "action.contract",
    category: "primary",
    viewBox: "0 0 24 24",
    strokeWidth: 1.9,
    body: '<path d="M8 3v5H3m18 0h-5V3m0 18v-5h5M3 16h5v5"/>',
  },
  {
    id: "action.zoom-in",
    category: "primary",
    viewBox: "0 0 24 24",
    strokeWidth: 1.9,
    body: '<circle cx="11" cy="11" r="7"/><path d="m20 20-4-4M11 8v6M8 11h6"/>',
  },
  {
    id: "action.zoom-out",
    category: "primary",
    viewBox: "0 0 24 24",
    strokeWidth: 1.9,
    body: '<circle cx="11" cy="11" r="7"/><path d="m20 20-4-4M8 11h6"/>',
  },
  {
    id: "action.rotate",
    category: "primary",
    viewBox: "0 0 24 24",
    strokeWidth: 1.9,
    body: '<path d="M20 11a8 8 0 1 0-2.34 5.66L20 14"/><path d="M20 7v4h-4"/>',
  },
  {
    id: "media.photo",
    category: "primary",
    viewBox: "0 0 24 24",
    strokeWidth: 1.9,
    body: '<rect x="3" y="5" width="18" height="14" rx="2"/><circle cx="9" cy="11" r="2"/><path d="m21 15-3.5-3.5L13 16l-2-2-5 5"/>',
  },
  {
    id: "detail.provider",
    category: "primary",
    viewBox: "0 0 24 24",
    strokeWidth: 1.9,
    body: '<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3c3 3.3 3 14.7 0 18M12 3c-3 3.3-3 14.7 0 18"/>',
  },
  {
    id: "settings.cad-tools",
    category: "primary",
    viewBox: "0 0 24 24",
    strokeWidth: 1.9,
    body: '<rect x="6" y="6" width="12" height="12" rx="2"/><path d="M9 1v3m6-3v3M9 20v3m6-3v3M20 9h3m-3 6h3M1 9h3m-3 6h3"/><path d="M10 10h4v4h-4z"/>',
  },
  {
    id: "settings.sources",
    category: "primary",
    viewBox: "0 0 24 24",
    strokeWidth: 1.9,
    body: '<path d="M10 13a5 5 0 0 0 7.54.54l2-2a5 5 0 0 0-7.07-7.07l-1.15 1.15"/><path d="M14 11a5 5 0 0 0-7.54-.54l-2 2a5 5 0 0 0 7.07 7.07l1.15-1.15"/>',
  },
  {
    id: "nav.assets",
    category: "primary",
    viewBox: "0 0 24 24",
    strokeWidth: 1.9,
    body: '<path d="m21 8-9-5-9 5 9 5z"/><path d="m3 8 9 5v8l-9-5z"/><path d="m21 8-9 5v8l9-5z"/>',
  },
  {
    id: "nav.board",
    category: "primary",
    viewBox: "0 0 24 24",
    strokeWidth: 1.9,
    body: OWNER_SELECTED_INTERFACE_BODIES["nav.board"],
  },

  // ---- primary: the rail `svgProps` nav glyphs (viewBox 24, strokeWidth 2, class .ico) ----------
  {
    id: "nav.components",
    category: "primary",
    viewBox: "0 0 24 24",
    strokeWidth: 2,
    body: OWNER_SELECTED_INTERFACE_BODIES["nav.components"],
  },
  {
    // The STM Viewer rail glyph. Its siblings all carried an icon and it did not, which read as an
    // unfinished nav entry; a chip with its four pin rows is the same visual family as nav.components.
    id: "nav.stm",
    category: "primary",
    viewBox: "0 0 24 24",
    strokeWidth: 2,
    body: OWNER_SELECTED_INTERFACE_BODIES["nav.stm"],
  },
  {
    id: "nav.settings",
    category: "primary",
    viewBox: "0 0 24 24",
    strokeWidth: 2,
    body: OWNER_SELECTED_INTERFACE_BODIES["nav.settings"],
  },
  {
    id: "nav.about",
    category: "primary",
    viewBox: "0 0 24 24",
    strokeWidth: 2,
    body: OWNER_SELECTED_INTERFACE_BODIES["nav.about"],
  },
  {
    id: "nav.update",
    category: "primary",
    viewBox: "0 0 24 24",
    strokeWidth: 2,
    body: OWNER_SELECTED_INTERFACE_BODIES["nav.update"],
  },
  {
    // Collapse the rail. A PANEL glyph (the rail's own edge, plus a chevron moving toward it), not a
    // bare chevron: this is a docked panel closing against the window edge, which is the same thing
    // Altium and every other workspace shell draws here, and a lone chevron would read as "go back".
    // ONE asset serves both directions - the call site mirrors it on the x axis to mean "expand" -
    // so the two states can never drift apart the way two hand-drawn glyphs would.
    id: "nav.collapse-rail",
    category: "primary",
    viewBox: "0 0 24 24",
    strokeWidth: 2,
    body: OWNER_SELECTED_INTERFACE_BODIES["nav.collapse-rail"],
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
    // The 3D viewer's SHADING and VIEW controls, as glyphs. The mini tile is ~280px and ten
    // text-labelled chips wrapped to three rows there, taking a third of the stage; the owner chose
    // icon-only for the tile (2026-07-26) so the stage keeps its height. The modal still shows text.
    // Names stay reachable: every chip keeps its `title` and an aria-label.
    // PURPOSE-DRAWN AT 14px. The first cut reused `art.model` / `art.footprint`, which are authored in
    // a 70-90px box for the file cards - at 14px the cube collapsed to a plain hexagon and the
    // footprint to an equals-sign. A glyph has to be drawn for the size it is used at.
    id: "layer.model",
    category: "primary",
    viewBox: "0 0 24 24",
    strokeWidth: 1.8,
    // a solid little package body with its top face read separately
    body: '<path d="M4 9l8-4 8 4v6l-8 4-8-4z"/><path d="M4 9l8 4 8-4"/>',
  },
  {
    id: "layer.pads",
    category: "primary",
    viewBox: "0 0 24 24",
    strokeWidth: 1.6,
    // a land pattern: two rows of pads, which is what the layer actually is
    body:
      '<rect x="4" y="6" width="5" height="2.6" rx="1"/><rect x="15" y="6" width="5" height="2.6" rx="1"/>' +
      '<rect x="4" y="11" width="5" height="2.6" rx="1"/><rect x="15" y="11" width="5" height="2.6" rx="1"/>' +
      '<rect x="4" y="16" width="5" height="2.6" rx="1"/><rect x="15" y="16" width="5" height="2.6" rx="1"/>',
  },
  {
    id: "layer.board",
    category: "primary",
    viewBox: "0 0 24 24",
    strokeWidth: 1.7,
    // a substrate slab seen slightly from the side, so it reads as the thing pads sit ON
    body: '<path d="M3 10l9-4 9 4-9 4z"/><path d="M3 10v3l9 4 9-4v-3"/>',
  },
  {
    id: "view.shade-realistic",
    category: "primary",
    viewBox: "0 0 24 24",
    strokeWidth: 1.8,
    // a lit sphere: outline plus a terminator arc and a highlight, i.e. shading itself
    body:
      '<circle cx="12" cy="12" r="8"/>' +
      '<path d="M12 4a8 8 0 0 1 0 16 6 10 0 0 0 0-16" fill="currentColor" stroke="none" opacity="0.55"/>' +
      '<circle cx="9" cy="9" r="1.4" fill="currentColor" stroke="none"/>',
  },
  {
    id: "view.shade-studio",
    category: "primary",
    viewBox: "0 0 24 24",
    strokeWidth: 1.8,
    // FLAT shading: the same sphere with no gradient, just an even outline and a hard equator
    body: '<circle cx="12" cy="12" r="8"/><path d="M4 12h16"/>',
  },
  {
    id: "view.shade-xray",
    category: "primary",
    viewBox: "0 0 24 24",
    strokeWidth: 1.8,
    // see-through: a dashed sphere with an interior edge showing through it
    body:
      '<circle cx="12" cy="12" r="8" stroke-dasharray="3 2.4"/>' +
      '<path d="M12 6v12" opacity="0.7"/>',
  },
  {
    id: "view.iso",
    category: "primary",
    viewBox: "0 0 24 24",
    strokeWidth: 1.8,
    // a cube seen three-quarter, which is what the iso view is
    body:
      '<path d="M12 3l8 4.5v9L12 21l-8-4.5v-9z"/>' +
      '<path d="M12 3v9l8-4.5M12 12l-8-4.5M12 12v9" opacity="0.75"/>',
  },
  {
    id: "view.top",
    category: "primary",
    viewBox: "0 0 24 24",
    strokeWidth: 1.8,
    // looking straight DOWN a face: the face square with the axis coming at you
    body: '<rect x="4.5" y="4.5" width="15" height="15" rx="1.5"/><circle cx="12" cy="12" r="1.8" fill="currentColor" stroke="none"/>',
  },
  {
    id: "view.front",
    category: "primary",
    viewBox: "0 0 24 24",
    strokeWidth: 1.8,
    // an ELEVATION: the face square standing on a ground line, which is how a datasheet draws height
    body: '<rect x="4.5" y="4" width="15" height="12" rx="1.5"/><path d="M3 20h18"/>',
  },
  {
    id: "nav.theme",
    category: "primary",
    viewBox: "0 0 24 24",
    strokeWidth: 2,
    body: OWNER_SELECTED_INTERFACE_BODIES["nav.theme"],
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
    strokeLinecap: "round",
    strokeLinejoin: "round",
    body: '<path d="m21 21-4.34-4.34"/><circle cx="11" cy="11" r="8"/>',
  },
  {
    id: "status.warn",
    category: "bespoke",
    viewBox: "0 0 24 24",
    size: 15,
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 2,
    strokeLinecap: "round",
    strokeLinejoin: "round",
    body: '<path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3"/><path d="M12 9v4"/><path d="M12 17h.01"/>',
  },
  {
    id: "status.info",
    category: "bespoke",
    viewBox: "0 0 24 24",
    size: 15,
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 2,
    strokeLinecap: "round",
    strokeLinejoin: "round",
    body: '<circle cx="12" cy="12" r="10"/><path d="M12 16v-4"/><path d="M12 8h.01"/>',
  },
  {
    // Font Awesome Free 7.3.1 `circle-question`, used only for a genuinely absent CAD asset.
    // It is separate from art.symbol/footprint/model: unreadable attached files keep their own art.
    id: "status.cad-missing",
    category: "bespoke",
    viewBox: "0 0 512 512",
    fill: "currentColor",
    stroke: "none",
    body: '<path d="M256 512a256 256 0 1 0 0-512 256 256 0 1 0 0 512zm0-336c-17.7 0-32 14.3-32 32 0 13.3-10.7 24-24 24s-24-10.7-24-24c0-44.2 35.8-80 80-80s80 35.8 80 80c0 47.2-36 67.2-56 74.5l0 3.8c0 13.3-10.7 24-24 24s-24-10.7-24-24l0-8.1c0-20.5 14.8-35.2 30.1-40.2 6.4-2.1 13.2-5.5 18.2-10.3 4.3-4.2 7.7-10 7.7-19.6 0-17.7-14.3-32-32-32zM224 368a32 32 0 1 1 64 0 32 32 0 1 1 -64 0z"/>',
  },
  {
    id: "action.upload",
    category: "bespoke",
    viewBox: "0 0 24 24",
    size: 24,
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 1.4,
    strokeLinecap: "round",
    strokeLinejoin: "round",
    body: '<path d="M12 3v12"/><path d="m17 8-5-5-5 5"/><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>',
  },
  {
    id: "action.close",
    category: "bespoke",
    viewBox: "0 0 24 24",
    size: 15,
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 1.8,
    strokeLinecap: "round",
    strokeLinejoin: "round",
    body: '<path d="M18 6 6 18"/><path d="m6 6 12 12"/>',
  },
  {
    id: "nav.back",
    category: "bespoke",
    viewBox: "0 0 24 24",
    size: 15,
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 1.8,
    strokeLinecap: "round",
    strokeLinejoin: "round",
    body: '<path d="m15 18-6-6 6-6"/>',
  },
  {
    // "this can be opened for a look". Replaces the literal word "View" on an asset tile, where the
    // tile is already a button whose aria-label says "Open <name> Preview" (punch 11).
    id: "action.view",
    category: "bespoke",
    viewBox: "0 0 24 24",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 2,
    strokeLinecap: "round",
    strokeLinejoin: "round",
    body: '<path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7-10-7-10-7Z"/><circle cx="12" cy="12" r="3"/>',
  },
  {
    id: "action.external",
    category: "bespoke",
    viewBox: "0 0 24 24",
    size: 13,
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 2,
    strokeLinecap: "round",
    strokeLinejoin: "round",
    body: OWNER_SELECTED_INTERFACE_BODIES["action.external"],
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
    body: '<path d="M18 6 6 18"/><path d="m6 6 12 12"/>',
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
    body: '<path d="M18 6 6 18"/><path d="m6 6 12 12"/>',
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
    body: '<path d="M13 21h8"/><path d="M21.174 6.812a1 1 0 0 0-3.986-3.987L3.842 16.174a2 2 0 0 0-.5.83l-1.321 4.352a.5.5 0 0 0 .623.622l4.353-1.32a2 2 0 0 0 .83-.497z"/>',
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
    viewBox: "0 0 24 24",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 2,
    strokeLinecap: "round",
    strokeLinejoin: "round",
    body: '<path d="m6 9 6 6 6-6"/>',
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
    // The datasheet row's leading glyph: a document. It exists so the row can carry the SAME anatomy
    // as Filing directly below it ([icon] LABEL [value] [affordance]) - before this the datasheet was
    // a bordered pill beside a bare pencil, two shapes at two heights (punch 8).
    id: "detail.datasheet-link",
    category: "bespoke",
    viewBox: "0 0 24 24",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 2,
    strokeLinecap: "round",
    strokeLinejoin: "round",
    body: '<path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z"/><path d="M14 2v5h6"/><path d="M8 13h8"/><path d="M8 17h5"/>',
  },
  {
    id: "detail.tag-remove",
    category: "bespoke",
    viewBox: "0 0 24 24",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 2.4,
    strokeLinecap: "round",
    body: '<path d="M18 6 6 18"/><path d="m6 6 12 12"/>',
  },
  {
    // Embed 3D Model: a cube with an arrow entering it. A chevron was wrong here, because a chevron
    // means navigate and this control WRITES a 3D body into the footprint library.
    id: "detail.embed-3d",
    category: "bespoke",
    viewBox: "0 0 24 24",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 1.9,
    strokeLinecap: "round",
    body:
      '<path d="M20 8.5v7l-6 3.5-6-3.5v-7L14 5z" stroke-linejoin="round"/>' +
      '<path d="M14 5v3.5m0 0 6-3.5m-6 3.5L8 5" opacity="0.45"/>' +
      '<path d="M4 12.5h4m0 0-1.6-1.7M8 12.5l-1.6 1.7"/>',
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
    strokeLinecap: "round",
    strokeLinejoin: "round",
    body: '<path d="M2 5h20"/><path d="M6 12h12"/><path d="M9 19h6"/>',
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
    body: '<path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/><path d="M3 3v5h5"/>',
  },
  {
    id: "dev.close",
    category: "bespoke",
    viewBox: "0 0 24 24",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 2.2,
    strokeLinecap: "round",
    body: '<path d="M18 6 6 18"/><path d="m6 6 12 12"/>',
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
    // The owner-selected open-box brand mark. Its fitted body is solid, while the stable brand id
    // and call-site `.ico` sizing token remain unchanged.
    id: "brand.wordmark",
    category: "brand",
    viewBox: "0 0 24 24",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 2,
    strokeLinecap: "round",
    strokeLinejoin: "round",
    body: OWNER_SELECTED_INTERFACE_BODIES["brand.wordmark"],
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
export const ICON_IDS_BY_CATEGORY: Record<IconCategory, string[]> = (() => {
  // Seeded from ICON_CATEGORIES so every declared category has a list (and the keys read in
  // inventory order) even when the registry carries no entry for it, then filled in ONE pass
  // over the registry rather than one pass per category.
  const byCategory = {} as Record<IconCategory, string[]>;
  for (const category of ICON_CATEGORIES) byCategory[category] = [];
  for (const entry of ICON_REGISTRY) byCategory[entry.category]?.push(entry.id);
  return byCategory;
})();
