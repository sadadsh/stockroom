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
import type { IconEntry } from "../lib/iconRegistry";
import { useDevMode } from "../lib/devMode";
import { resolveIcon, sanitizeIconMarkup } from "./iconResolve";

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
  const override = resolveIconOverride(id);
  const accessibleTitle = override?.a11yLabel || title;
  const inner = sanitizeIconMarkup(body, accessibleTitle);
  // A titled icon is announced (role="img" + aria-label); an untitled one is decorative. Primary
  // glyphs default to aria-hidden (as the source `Svg` helper did); the bespoke/art/brand sources
  // set no aria attribute, so an untitled non-primary icon stays bare - a faithful refactor.
  const namedA11y = accessibleTitle ? ({ role: "img" as const, "aria-label": accessibleTitle }) : {};
  const presentationStyle = {
    verticalAlign: override?.alignment,
    opacity: override?.treatment === "muted" ? 0.55 : undefined,
  };
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
        fill={override?.treatment === "solid" ? "currentColor" : "none"}
        stroke={override?.treatment === "solid" ? "none" : "currentColor"}
        strokeWidth={override?.strokeWidth ?? entry.strokeWidth}
        style={presentationStyle}
        strokeLinecap="round"
        strokeLinejoin="round"
        aria-hidden={accessibleTitle ? undefined : true}
        {...namedA11y}
        {...devId}
        dangerouslySetInnerHTML={{ __html: inner }}
      />
    );
  }

  // Bespoke / art / brand: reproduce the source svg's own root presentation exactly. Undefined
  // props are dropped by React, so an entry only emits the attributes its source actually set.
  const { width, height } = sizeAttrs(entry.size);
  const solid = override?.treatment === "solid";
  return (
    <svg
      className={className}
      width={width}
      height={height}
      viewBox={entry.viewBox}
      fill={solid ? "currentColor" : entry.fill}
      stroke={solid ? "none" : entry.stroke}
      strokeWidth={override?.strokeWidth ?? entry.strokeWidth}
      strokeLinecap={entry.strokeLinecap}
      strokeLinejoin={entry.strokeLinejoin}
      style={{ ...entry.style, ...presentationStyle }}
      {...namedA11y}
      {...devId}
      dangerouslySetInnerHTML={{ __html: inner }}
    />
  );
}
