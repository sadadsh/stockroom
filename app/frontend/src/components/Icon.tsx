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
 * Tabler Outline defaults render through one preset (class `.ico` so `--icon-stroke` retunes the
 * whole set, viewBox 24, fill none, stroke currentColor, round caps). Technical art and social-brand
 * exceptions carry their source presentation from the registry entry. Like <Text>, outside dev mode
 * <Icon> is a plain glyph. An unknown id renders nothing (a safe no-op).
 */
import type { IconEntry, IconId } from "../lib/iconRegistry";
import { useDevMode } from "../lib/devMode";
import { runtimeDesignId } from "../lib/designIdentity";
import { resolveIcon, sanitizeIconMarkup } from "./iconResolve";

// -- component ----------------------------------------------------------------------------------
export interface IconProps {
  /** Registry / override id (e.g. "action.trash"). Unknown ids render nothing. */
  id: IconId;
  /** Extra classes; Tabler defaults receive these alongside the shared `.ico` class. */
  className?: string;
  /** Accessible name. When set, the svg gets role="img" + aria-label + a <title>; else aria-hidden. */
  title?: string;
  /** Build-generated call-site identity; wins over the reusable component fallback. */
  "data-design-id"?: string;
  /** Authored public identity; wins over every generated identity. */
  "data-dev-id"?: string;
}

function sizeAttrs(size: IconEntry["size"]): { width?: number; height?: number } {
  if (size == null) return {};
  if (Array.isArray(size)) return { width: size[0], height: size[1] };
  return { width: size, height: size };
}

export function Icon({
  id,
  className,
  title,
  "data-design-id": callerDesignId,
  "data-dev-id": callerDevId,
}: IconProps) {
  // D-02: resolve overrides through the dev-mode context (the working-state under a provider, the
  // committed ICON_OVERRIDES on the no-op DEFAULT), so a working edit renders live.
  const { enabled, resolveIconOverride } = useDevMode();
  const resolved = resolveIcon(id, resolveIconOverride);
  if (!resolved) return null;

  const { entry, body } = resolved;
  const override = resolveIconOverride(id);
  const accessibleTitle = override?.a11yLabel || title;
  const inner = sanitizeIconMarkup(body, accessibleTitle);
  // A titled icon is announced (role="img" + aria-label); every untitled icon is decorative,
  // regardless of category. Interactive consequences belong to the enclosing control's label.
  const namedA11y = accessibleTitle ? ({ role: "img" as const, "aria-label": accessibleTitle }) : {};
  const presentationStyle = {
    verticalAlign: override?.alignment,
    opacity: override?.treatment === "muted" ? 0.55 : undefined,
  };
  // Historical drafts could persist `solid` for any outline body. Filling an open-path glyph and
  // removing its stroke erases it, so legacy values deliberately fall back to the source geometry.
  const legacySolid = override?.treatment === "solid";
  const treatmentState = legacySolid ? { "data-icon-treatment": "legacy-solid-fallback" } : {};
  // D-02 / D-03: in dev mode the <svg> advertises which registry glyph it draws (the icon analog of
  // <Text>'s data-copy-id), so the Selection pane can map a selected element to its icon id. Gated
  // on `enabled` exactly like <Text> only wraps in dev mode: OFF dev mode this is the empty object.
  const devId = enabled ? { "data-icon-id": id } : {};
  // Geometry edits target the icon itself, not its component-specific parent. Keep that semantic
  // identity outside Studio too so a committed size/alignment override survives the editor closing.
  const designId = callerDesignId ?? (callerDevId ? undefined : runtimeDesignId("icon", id));

  if (entry.family === "tabler-outline" || entry.family === "stockroom-electrical") {
    // The shared line-icon preset: `.ico` routes stroke-width through --icon-stroke; the
    // strokeWidth attribute is the offline fallback if the stylesheet has not applied yet.
    return (
      <svg
        className={`ico ${className ?? "h-3.5 w-3.5"}`}
        viewBox={entry.viewBox}
        fill="none"
        stroke="currentColor"
        strokeWidth={override?.strokeWidth ?? entry.strokeWidth}
        style={presentationStyle}
        strokeLinecap="round"
        strokeLinejoin="round"
        aria-hidden={accessibleTitle ? undefined : true}
        {...namedA11y}
        data-dev-id={callerDevId}
        data-design-id={designId}
        {...devId}
        {...treatmentState}
        dangerouslySetInnerHTML={{ __html: inner }}
      />
    );
  }

  // Technical art / social brands: reproduce the source svg's own root presentation exactly. Undefined
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
      strokeWidth={override?.strokeWidth ?? entry.strokeWidth}
      strokeLinecap={entry.strokeLinecap}
      strokeLinejoin={entry.strokeLinejoin}
      style={{ ...entry.style, ...presentationStyle }}
      aria-hidden={accessibleTitle ? undefined : true}
      {...namedA11y}
      data-dev-id={callerDevId}
      data-design-id={designId}
      {...devId}
      {...treatmentState}
      dangerouslySetInnerHTML={{ __html: inner }}
    />
  );
}
