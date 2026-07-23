/**
 * The dev-mode Inspector: the DOM-delegation layer behind the inspect-first shell. While dev mode is
 * on it attaches capture-phase document listeners (locked decision 6) so the 196 `data-dev-id`
 * attributes stay pure static markup with no per-element React wiring. It owns three surfaces, all
 * rendered through a portal to document.body so they sit above the app AND open modals (z-[150],
 * above the modal scrim z-95 and below the panel z-200):
 *
 *  - Hover highlight + badge (only while Inspect is on): outlines the closest `[data-dev-id]` under
 *    the pointer and names it (id + label + a chip per used token).
 *  - Inspect-click select-and-swallow (locked decision 7): only while Inspect is on, a click on a
 *    `[data-dev-id]` element is preventDefault + stopPropagation'd (so no app action / copy click
 *    fires) and selects that element, driving the panel. Inspect OFF is zero behaviour change.
 *  - Show IDs overlay (locked decision 8, a SEPARATE toggle): one static badge over every
 *    `[data-dev-id]` node at once (the screenshot map), re-enumerated on toggle + window resize.
 *
 * Listeners attach ONLY while dev mode is enabled and detach on cleanup, so production users (for
 * whom dev mode never turns on) carry no listener and no overlay. All text is rendered as React
 * children (catalog labels + cssVar names) - never innerHTML, eval, or network.
 */
import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { useDevMode } from "../lib/devMode";
import { usedVarsForElement } from "../lib/inspectVars";
import { DEV_ID_BY_ID } from "../lib/devIds";

interface Badge {
  id: string;
  label: string;
  rect: { left: number; top: number; width: number; height: number };
}

interface Hover {
  id: string;
  vars: string[];
  rect: { left: number; top: number; width: number; height: number };
}

function rectOf(el: Element): { left: number; top: number; width: number; height: number } {
  const r = el.getBoundingClientRect();
  return { left: r.left, top: r.top, width: r.width, height: r.height };
}

export function DevInspector() {
  const dev = useDevMode();
  const { enabled, inspect, showIds, selectDevId, selectVars } = dev;
  const [hover, setHover] = useState<Hover | null>(null);
  const [badges, setBadges] = useState<Badge[]>([]);

  // Capture-phase document listeners live ONLY while dev mode is enabled; the whole surface is
  // inert (and leak-free) otherwise. Re-bound when inspect flips so the click handler swallows only
  // in inspect mode (decision 7). Reading state through refs would avoid the re-bind, but re-binding
  // on the two booleans is cheap and keeps the swallow logic obvious.
  useEffect(() => {
    if (!enabled) return;

    function onPointerMove(e: PointerEvent) {
      if (!inspect) return;
      const target = e.target as Element | null;
      const el = target && "closest" in target ? target.closest("[data-dev-id]") : null;
      if (!el) {
        setHover(null);
        return;
      }
      const id = el.getAttribute("data-dev-id");
      if (!id) {
        setHover(null);
        return;
      }
      setHover({ id, vars: usedVarsForElement(el), rect: rectOf(el) });
    }

    function onClick(e: MouseEvent) {
      if (!inspect) return; // inspect OFF: zero behaviour change, the click passes through untouched
      const target = e.target as Element | null;
      const el = target && "closest" in target ? target.closest("[data-dev-id]") : null;
      if (!el) return;
      const id = el.getAttribute("data-dev-id");
      if (!id) return;
      // Swallow the click so no app action / copy layer handler fires (the document-capture phase
      // runs before the React root, so stopPropagation keeps the event from ever reaching it).
      e.preventDefault();
      e.stopPropagation();
      selectDevId(id);
      selectVars(usedVarsForElement(el));
    }

    document.addEventListener("pointermove", onPointerMove, true);
    document.addEventListener("click", onClick, true);
    return () => {
      document.removeEventListener("pointermove", onPointerMove, true);
      document.removeEventListener("click", onClick, true);
    };
  }, [enabled, inspect, selectDevId, selectVars]);

  // Clear the hover highlight the moment Inspect (or dev mode) turns off, so no stale outline lingers.
  useEffect(() => {
    if (!enabled || !inspect) setHover(null);
  }, [enabled, inspect]);

  // Show IDs: one badge per [data-dev-id] node, enumerated when the toggle flips and re-measured on
  // window resize (jsdom returns zero-size rects, so tests assert badge COUNT, not pixel position).
  useEffect(() => {
    if (!enabled || !showIds) {
      setBadges([]);
      return;
    }
    function enumerate() {
      const nodes = Array.from(document.querySelectorAll("[data-dev-id]"));
      setBadges(
        nodes.map((el) => {
          const id = el.getAttribute("data-dev-id") ?? "";
          return { id, label: DEV_ID_BY_ID.get(id)?.label ?? id, rect: rectOf(el) };
        }),
      );
    }
    enumerate();
    window.addEventListener("resize", enumerate);
    return () => window.removeEventListener("resize", enumerate);
  }, [enabled, showIds]);

  if (!enabled) return null;

  return createPortal(
    <div className="pointer-events-none fixed inset-0 z-[150]" aria-hidden="true">
      {/* Hover highlight + badge, only while Inspect is on. */}
      {inspect && hover ? (
        <div
          data-testid="dev-hover"
          className="absolute rounded-[4px] outline outline-2 outline-acc"
          style={{
            left: hover.rect.left,
            top: hover.rect.top,
            width: hover.rect.width,
            height: hover.rect.height,
          }}
        >
          <div className="absolute left-0 top-full mt-1 flex max-w-[280px] flex-col gap-1 rounded-control border border-line2 bg-popover px-2 py-1.5 shadow-pop">
            <div className="flex items-baseline gap-1.5">
              <span className="font-mono text-2xs font-semibold text-t1">{hover.id}</span>
              <span className="truncate text-2xs text-t3">
                {DEV_ID_BY_ID.get(hover.id)?.label ?? ""}
              </span>
            </div>
            {hover.vars.length > 0 ? (
              <div className="flex flex-wrap gap-1">
                {hover.vars.map((v) => (
                  <span
                    key={v}
                    className="rounded-[3px] bg-raise2 px-1 py-0.5 font-mono text-[9px] text-t2"
                  >
                    {v}
                  </span>
                ))}
              </div>
            ) : null}
          </div>
        </div>
      ) : null}

      {/* Show IDs overlay: one static badge over every [data-dev-id] node, in every window. */}
      {showIds
        ? badges.map((b, i) => (
            <span
              key={`${b.id}-${i}`}
              data-testid="dev-id-badge"
              className="absolute rounded-[3px] bg-acc px-1 py-0.5 font-mono text-[9px] font-semibold text-acc-on shadow-card"
              style={{ left: b.rect.left, top: b.rect.top }}
            >
              {b.id}
            </span>
          ))
        : null}
    </div>,
    document.body,
  );
}
