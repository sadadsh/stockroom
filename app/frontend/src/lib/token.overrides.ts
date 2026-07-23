/**
 * Committed design-token overrides, written by dev mode (Ctrl+Shift+D -> the Design panel).
 * This file is the SOURCE OF TRUTH for any token the owner has nudged: it is applied on boot for
 * everyone (not a per-machine setting), so a saved tweak ships with the app. Empty means "use the
 * shipped defaults in styles/index.css".
 *
 * `root` holds the dark-theme colours AND the theme-agnostic radii (they live on :root, like the
 * index.css defaults); `light` holds the light-theme colour overrides. Each value is a raw CSS
 * value (a hex / rgb(a) colour or a px length). This file is regenerated whole by POST
 * /api/dev/save - keep it to the single const export so the writer stays simple; it is safe to
 * hand-edit.
 */
export const TOKEN_OVERRIDES: {
  root: Record<string, string>;
  light: Record<string, string>;
} = {
  root: {},
  light: {},
};
