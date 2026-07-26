/**
 * <Icon id> - the one component that draws every glyph. It resolves the icon id through the
 * committed overrides (lib/icon.overrides.ts) and the registry (lib/iconRegistry.ts):
 *
 *   1. ICON_OVERRIDES[id].swapToId -> render that other registry glyph instead (a glyph swap),
 *   2. ICON_OVERRIDES[id].body     -> render the override's inner markup over the registry frame,
 *   3. otherwise                   -> the registry default body.
 *
 * The body is passed through a local sanitiser before it is injected, so an override can never
 * smuggle a <script>, an on* handler, an external/foreignObject ref, or a DOCTYPE into the DOM.
 * The backend validator on /api/dev/save is the authority on what may ship in icon.overrides.ts;
 * this client-side pass is defence-in-depth (the app must not blindly inject even trusted markup).
 *
 * Primary icons render through one preset (class `.ico` so `--icon-stroke` retunes the whole set,
 * viewBox 24, fill none, stroke currentColor, round caps). Bespoke / art / brand glyphs carry their
 * own viewBox / size / fill / stroke / weight from the registry entry. Like <Text>, there is no
 * behaviour change: outside dev mode <Icon> is a plain glyph, identical to the hand-written svg it
 * replaces. An unknown id renders nothing (a safe no-op).
 */
import { ICON_BY_ID, type IconEntry } from "../lib/iconRegistry";
import { ICON_OVERRIDES, type IconOverride } from "../lib/icon.overrides";
import { useDevMode } from "../lib/devMode";

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
interface ResolvedIcon {
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

// -- component ----------------------------------------------------------------------------------
export interface IconProps {
  /** Registry / override id (e.g. "action.trash"). Unknown ids render nothing. */
  id: string;
  /** Extra classes; for primary icons this rides alongside the shared `.ico` class. */
  className?: string;
  /** Accessible name. When set, the svg gets role="img" + aria-label + a <title>; else aria-hidden. */
  title?: string;
}

function sizeAttrs(size: IconEntry["size"]): { width?: number; height?: number } {
  if (size == null) return {};
  if (Array.isArray(size)) return { width: size[0], height: size[1] };
  return { width: size, height: size };
}

export function Icon({ id, className, title }: IconProps) {
  // D-02: resolve overrides through the dev-mode context (the working-state under a provider, the
  // committed ICON_OVERRIDES on the no-op DEFAULT), so a working edit renders live while an
  // unprovided <Icon> is byte-identical to today.
  const { enabled, resolveIconOverride } = useDevMode();
  const resolved = resolveIcon(id, resolveIconOverride);
  if (!resolved) return null;

  const { entry, body } = resolved;
  const safeBody = sanitizeIconBody(body);
  const inner = title ? `<title>${escapeXml(title)}</title>${safeBody}` : safeBody;
  // A titled icon is announced (role="img" + aria-label); an untitled one is decorative. Primary
  // glyphs default to aria-hidden (as the source `Svg` helper did); the bespoke/art/brand sources
  // set no aria attribute, so an untitled non-primary icon stays bare - a faithful refactor.
  const namedA11y = title ? ({ role: "img" as const, "aria-label": title }) : {};
  // D-02 / D-03: in dev mode the <svg> advertises which registry glyph it draws (the icon analog of
  // <Text>'s data-copy-id), so the Selection pane can map a selected element to its icon id. Gated
  // on `enabled` exactly like <Text> only wraps in dev mode: OFF dev mode this is the empty object,
  // so the rendered DOM is byte-identical to today and every render-diff guard still holds.
  const devId = enabled ? { "data-icon-id": id } : {};

  if (entry.category === "primary") {
    // The shared line-icon preset: `.ico` routes stroke-width through --icon-stroke; the
    // strokeWidth attribute is the offline fallback if the stylesheet has not applied yet.
    return (
      <svg
        className={`ico ${className ?? "h-3.5 w-3.5"}`}
        viewBox={entry.viewBox}
        fill="none"
        stroke="currentColor"
        strokeWidth={entry.strokeWidth}
        strokeLinecap="round"
        strokeLinejoin="round"
        aria-hidden={title ? undefined : true}
        {...namedA11y}
        {...devId}
        dangerouslySetInnerHTML={{ __html: inner }}
      />
    );
  }

  // Bespoke / art / brand: reproduce the source svg's own root presentation exactly. Undefined
  // props are dropped by React, so an entry only emits the attributes its source actually set.
  const { width, height } = sizeAttrs(entry.size);
  return (
    <svg
      className={className}
      width={width}
      height={height}
      viewBox={entry.viewBox}
      fill={entry.fill}
      stroke={entry.stroke}
      strokeWidth={entry.strokeWidth}
      strokeLinecap={entry.strokeLinecap}
      strokeLinejoin={entry.strokeLinejoin}
      style={entry.style}
      {...namedA11y}
      {...devId}
      dangerouslySetInnerHTML={{ __html: inner }}
    />
  );
}
