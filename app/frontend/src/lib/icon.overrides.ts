/**
 * Committed icon overrides, written by dev mode (Ctrl+Shift+D, then the Icon tab). This file is the
 * SOURCE OF TRUTH for any icon the owner has re-drawn: it is read on boot for everyone (not a per-machine
 * setting), so a saved icon ships with the app. A key is a stable icon id (see lib/iconRegistry.ts /
 * <Icon id="...">); an absent id falls back to the registry default. Each value is either `{ body }` -
 * sanitised inner SVG markup that replaces the glyph - or `{ swapToId }` - another registry id whose glyph
 * to render instead. Generated whole by POST /api/dev/save through a strict SVG validator; safe to
 * hand-edit but the backend validator is the authority on what may ship.
 */
export interface IconOverride {
  // Sanitised inner SVG markup (paths, shapes) that replaces the registry glyph's body.
  body?: string;
  // Another registry icon id whose glyph to render instead (a glyph swap).
  swapToId?: string;
}

export const ICON_OVERRIDES: Record<string, IconOverride> = {};
