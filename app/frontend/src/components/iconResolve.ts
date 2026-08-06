/**
 * Icon RESOLUTION and SANITISATION: the plain functions behind `<Icon>`.
 *
 * They live beside the component rather than in it because a module that exports both components
 * and plain functions is not a Fast Refresh boundary, and `<Icon>` is on nearly every screen. The
 * dev panel's icon editor and `Icon.test.tsx` both call straight into this module.
 */
import { ICON_BY_ID, type IconEntry } from "../lib/iconRegistry";
import { ICON_OVERRIDES, type IconOverride } from "../lib/icon.overrides";

// -- sanitiser ----------------------------------------------------------------------------------
// Elements that may never appear in an icon body (stripped whole, with their contents). Longer
// names first so the alternation cannot half-match (animateTransform before animate before a).
const FORBIDDEN_ELEMENTS =
  "script|foreignObject|iframe|object|embed|style|animateTransform|animateMotion|animate|set|use|image|a";

const sanitizeCache = new Map<string, string>();

/**
 * Strip the dangerous surface out of an icon body string: script/foreignObject/etc. elements,
 * on* event handlers, non-fragment href / xlink:href, javascript: URIs, remote url(...) refs, and
 * DOCTYPE / processing-instruction / comment / CDATA noise. Geometry, stroke/fill attributes and
 * inline `style` (used by the art glyphs to route a theme var) are preserved verbatim.
 */
export function sanitizeIconBody(raw: string): string {
  if (!raw) return "";
  const cached = sanitizeCache.get(raw);
  if (cached !== undefined) return cached;

  let out = raw;
  // DOCTYPE / XML declarations / comments / CDATA.
  out = out.replace(/<!doctype[^>]*>/gi, "");
  out = out.replace(/<\?[\s\S]*?\?>/g, "");
  out = out.replace(/<!--[\s\S]*?-->/g, "");
  out = out.replace(/<!\[cdata\[[\s\S]*?\]\]>/gi, "");
  // Forbidden elements: paired form (with contents), then any stray open/close/self-closing tag.
  out = out.replace(
    new RegExp(`<\\s*(${FORBIDDEN_ELEMENTS})\\b[\\s\\S]*?<\\s*/\\s*\\1\\s*>`, "gi"),
    "",
  );
  out = out.replace(new RegExp(`<\\s*/?\\s*(${FORBIDDEN_ELEMENTS})\\b[^>]*>`, "gi"), "");
  // on* event handler attributes (quoted or bare).
  out = out.replace(/\s+on[a-z-]+\s*=\s*"[^"]*"/gi, "");
  out = out.replace(/\s+on[a-z-]+\s*=\s*'[^']*'/gi, "");
  out = out.replace(/\s+on[a-z-]+\s*=\s*[^\s>]+/gi, "");
  // href / xlink:href that is not a local #fragment reference.
  out = out.replace(/\s+(?:xlink:)?href\s*=\s*"(?!\s*#)[^"]*"/gi, "");
  out = out.replace(/\s+(?:xlink:)?href\s*=\s*'(?!\s*#)[^']*'/gi, "");
  out = out.replace(/\s+(?:xlink:)?href\s*=\s*(?!["']?\s*#)[^\s>]+/gi, "");
  // javascript: URIs and remote url(...) references.
  out = out.replace(/javascript:/gi, "");
  out = out.replace(/url\(\s*['"]?\s*(?:https?:|\/\/|data:)[^)]*\)/gi, "url(#)");

  sanitizeCache.set(raw, out);
  return out;
}

function escapeXml(value: string): string {
  return value
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

// -- resolution ---------------------------------------------------------------------------------
export interface ResolvedIcon {
  entry: IconEntry;
  body: string;
}

/**
 * Walk the override chain for an id: follow `swapToId` hops (guarding against cycles and dangling
 * targets) to the terminal entry, then take that entry's `body` override if present, else its
 * registry default. Returns null for an unknown id so <Icon> can no-op.
 *
 * `overrideFor` supplies the override for an id. It defaults to reading the committed ICON_OVERRIDES
 * module, so the exported resolveIcon(id) keeps its original signature/behaviour; <Icon> passes the
 * dev-mode context's resolveIconOverride instead, so a working-state edit resolves live (D-02).
 */
export function resolveIcon(
  id: string,
  overrideFor: (id: string) => IconOverride | undefined = (i) => ICON_OVERRIDES[i],
): ResolvedIcon | null {
  const seen = new Set<string>();
  let currentId = id;

  // Follow swaps until a terminal (no swap / already-seen / missing target) is reached.
  for (;;) {
    if (seen.has(currentId)) break;
    seen.add(currentId);
    const override = overrideFor(currentId);
    if (override?.swapToId && ICON_BY_ID.has(override.swapToId)) {
      currentId = override.swapToId;
      continue;
    }
    break;
  }

  const entry = ICON_BY_ID.get(currentId);
  if (!entry) return null;

  const override = overrideFor(currentId);
  const body = override?.body != null ? override.body : entry.body;
  return { entry, body };
}

/**
 * The ONLY markup that may be injected into an icon's `<svg>`: the sanitised body, preceded by an
 * escaped `<title>` when the icon carries an accessible name.
 *
 * Both halves live in one function on purpose. Composing them at the call site meant the value
 * handed to `dangerouslySetInnerHTML` was assembled next to the sink, so nothing structural stopped
 * a future caller from assembling a slightly different one that skipped a step. Now the sink can
 * only ever receive this function's return value, and this function cannot return unsanitised text.
 */
export function sanitizeIconMarkup(body: string, title?: string): string {
  const safeBody = sanitizeIconBody(body);
  return title ? `<title>${escapeXml(title)}</title>${safeBody}` : safeBody;
}
