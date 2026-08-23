/**
 * The dev-mode Inspector: the DOM-delegation layer behind the inspect-first shell. While dev mode is
 * on it attaches capture-phase document listeners (locked decision 6) so the 196 `data-dev-id`
 * attributes stay pure static markup with no per-element React wiring. It owns three surfaces, all
 * rendered through a portal to document.body so they sit above the app AND open modals (z-[190],
 * above every layer the modal stack can hand out and below the panel z-200). It was z-[150], which
 * a five-deep modal stack now reaches: layers start at 110 and step by 10, so a fixed 150 would
 * have put the inspector UNDER the very window a person was inspecting.):
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
import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type KeyboardEvent as ReactKeyboardEvent,
  type PointerEvent as ReactPointerEvent,
} from "react";
import { createPortal } from "react-dom";
import { useDevMode } from "../lib/devMode";
import type { DevModeDraft } from "../lib/devModeDraft";
import { usedVarsForElement } from "../lib/inspectVars";
import { DEV_ID_BY_ID } from "../lib/devIds";
import { devIdScope, sharedRoleOf } from "../lib/componentDevIds";
import {
  DESIGN_TARGET_SELECTOR,
  designIdOf,
  ensureDesignIdentities,
  exactDesignTargetAuthority,
  isGeneratedDesignId,
  isProtectedDesignRoot,
  isRootProtectedDesignProperty,
  type ExactDesignTargetAuthority,
} from "../lib/designIdentity";
import { elementsForTargetDomainOverride, TECHNICAL_CONTENT_SELECTOR } from "../design-studio/targetDomains";
import { useOptionalDesignStudio } from "../design-studio/DesignStudioProvider";
import {
  DESIGN_TARGET_Z_INDEX_MAX,
  DESIGN_TARGET_Z_INDEX_MIN,
} from "../design-studio/designLayers";
import { useEscapeDismiss } from "../lib/useEscapeDismiss";

interface Badge {
  id: string;
  label: string;
  rect: { left: number; top: number; width: number; height: number };
}

interface Hover {
  id: string;
  label: string;
  vars: string[];
  rect: { left: number; top: number; width: number; height: number };
}

interface SelectedTarget extends ExactDesignTargetAuthority {
  label: string;
  element: Element & ElementCSSInlineStyle;
}

type ResizeDirection = "north" | "northeast" | "east" | "southeast" | "south" | "southwest" | "west" | "northwest";
type GestureKind = "move" | "rotate" | ResizeDirection;

interface GesturePreview {
  target: SelectedTarget;
  original: Record<"position" | "left" | "top" | "width" | "height" | "transform", string>;
  baseLeft: number;
  baseTop: number;
  baseWidth: number;
  baseHeight: number;
  baseRotation: number;
  baseTransform: string;
  renderedLeft: number;
  renderedTop: number;
  renderedRight: number;
  renderedBottom: number;
}

interface Gesture {
  pointerId: number;
  captureTarget: HTMLButtonElement;
  kind: GestureKind;
  startX: number;
  startY: number;
  scale: number;
  grid: number;
  centerX: number;
  centerY: number;
  startAngle: number;
  changed: boolean;
  previews: GesturePreview[];
}

const RESIZE_DIRECTIONS: readonly ResizeDirection[] = [
  "north", "northeast", "east", "southeast", "south", "southwest", "west", "northwest",
];

const HANDLE_POSITION: Record<ResizeDirection, { left: string; top: string; cursor: string }> = {
  north: { left: "50%", top: "0%", cursor: "ns-resize" },
  northeast: { left: "100%", top: "0%", cursor: "nesw-resize" },
  east: { left: "100%", top: "50%", cursor: "ew-resize" },
  southeast: { left: "100%", top: "100%", cursor: "nwse-resize" },
  south: { left: "50%", top: "100%", cursor: "ns-resize" },
  southwest: { left: "0%", top: "100%", cursor: "nesw-resize" },
  west: { left: "0%", top: "50%", cursor: "ew-resize" },
  northwest: { left: "0%", top: "0%", cursor: "nwse-resize" },
};

function rectOf(el: Element): { left: number; top: number; width: number; height: number } {
  const r = el.getBoundingClientRect();
  return { left: r.left, top: r.top, width: r.width, height: r.height };
}

function px(value: string | undefined): number {
  const parsed = Number.parseFloat(value ?? "");
  return Number.isFinite(parsed) ? parsed : 0;
}

function snap(value: number, grid: number): number {
  return Math.round(value / grid) * grid;
}

const ROTATION_COMPONENT_RE = /rotate\((-?(?:\d+|\d*\.\d+))deg\)/;

function rotationOf(value: string | undefined): number {
  const match = ROTATION_COMPONENT_RE.exec(value?.trim() ?? "");
  return match ? Number(match[1]) : 0;
}

function roundedCssPixel(value: number): string {
  const normalized = Math.round(value * 1000) / 1000;
  return `${Object.is(normalized, -0) ? 0 : normalized}px`;
}

function rotationValue(value: number): string {
  const normalized = Math.round(value * 1000) / 1000;
  return `rotate(${Object.is(normalized, -0) ? 0 : normalized}deg)`;
}

function transformWithRotation(transform: string | undefined, rotation: number): string {
  const nextRotation = rotationValue(rotation);
  const current = transform?.trim() ?? "";
  if (!current || current === "none") return nextRotation;
  return ROTATION_COMPONENT_RE.test(current)
    ? current.replace(ROTATION_COMPONENT_RE, nextRotation)
    : `${current} ${nextRotation}`;
}

function gridFor(element: Element): number {
  const root = element.closest("[data-snap]");
  return root?.getAttribute("data-snap") === "on"
    ? Math.max(1, Number.parseInt(root.getAttribute("data-grid-size") ?? "8", 10) || 8)
    : 1;
}

function rotationStepFor(element: Element): number {
  return element.closest("[data-snap]")?.getAttribute("data-snap") === "on" ? 15 : 1;
}

interface EffectivePaintSibling {
  element: Element & ElementCSSInlineStyle;
  index: number;
  position: string;
}

function effectiveSiblingPaintEntries(element: Element): EffectivePaintSibling[] {
  const parent = element.parentElement;
  if (!parent) return [];
  const parentDisplay = getComputedStyle(parent).display;
  const flexOrGridItem = parentDisplay.includes("flex") || parentDisplay.includes("grid");
  const entries: EffectivePaintSibling[] = [];
  for (const sibling of Array.from(parent.children)) {
    if (sibling === element || !("style" in sibling)) continue;
    const style = getComputedStyle(sibling);
    const value = Number.parseInt(style.zIndex, 10);
    if (!Number.isFinite(value)) continue;
    if (style.position === "static" && !flexOrGridItem) continue;
    entries.push({
      element: sibling as Element & ElementCSSInlineStyle,
      index: value,
      position: style.position,
    });
  }
  return entries;
}

function displayLabel(id: string, element: Element): string {
  const text = element.textContent?.replace(/\s+/g, " ").trim();
  return text ? text.slice(0, 48) : labelFor(id, element) || id;
}

function selectedTargetFor(element: Element & ElementCSSInlineStyle): SelectedTarget | null {
  const authority = exactDesignTargetAuthority(element);
  if (!authority) return null;
  return {
    ...authority,
    label: displayLabel(authority.id, element),
    element,
  };
}

function withElementChanges(
  draft: DevModeDraft,
  changes: ReadonlyMap<string, Record<string, string | null> | null>,
): DevModeDraft {
  const elements = Object.fromEntries(
    Object.entries(draft.elements).map(([id, props]) => [id, { ...props }]),
  );
  for (const [id, patch] of changes) {
    if (patch === null) {
      delete elements[id];
      continue;
    }
    const next = { ...(elements[id] ?? {}) };
    for (const [property, value] of Object.entries(patch)) {
      if (value === null) delete next[property];
      else next[property] = value;
    }
    if (Object.keys(next).length) elements[id] = next;
    else delete elements[id];
  }
  return { ...draft, elements };
}

/** Technical drawings select their registered presentation root, never an engineering descendant. */
function selectableTarget(target: Element): Element | null {
  if (target.closest("[data-design-studio-chrome]")) return null;
  const productRoot = target.closest("[data-design-product-root]");
  const localRoot = target.closest(DESIGN_TARGET_SELECTOR);
  if (!productRoot && !localRoot) return null;
  ensureDesignIdentities(productRoot ?? localRoot!);
  const technicalRoot = target.closest(TECHNICAL_CONTENT_SELECTOR);
  return (technicalRoot?.closest(DESIGN_TARGET_SELECTOR) ?? target.closest(DESIGN_TARGET_SELECTOR));
}

/**
 * The human name for an id. A catalogue id has one; a per-instance id does not and cannot, so it
 * borrows the label of the shared role its element declares and says which contract it is under.
 * The ID ITSELF is always shown verbatim beside this - the label is context, never a substitute.
 */
function labelFor(id: string, el: Element | null): string {
  if (isGeneratedDesignId(id)) {
    const explicit = el?.getAttribute("aria-label") || el?.getAttribute("title");
    if (explicit) return explicit;
    const names: Record<string, string> = {
      a: "Link", button: "Button", div: "Container", footer: "Footer", header: "Header",
      img: "Image", input: "Input", label: "Label", li: "List Item", main: "Main Content",
      nav: "Navigation", section: "Section", select: "Select", span: "Text", svg: "Icon",
      table: "Table", textarea: "Text Area", ul: "List",
    };
    return names[el?.tagName.toLowerCase() ?? ""] ?? "Stockroom Element";
  }
  const entry = DEV_ID_BY_ID.get(id);
  if (entry) return entry.label;
  if (devIdScope(id) !== "instance") return "";
  const role = sharedRoleOf(el);
  const roleLabel = role ? DEV_ID_BY_ID.get(role)?.label : undefined;
  return roleLabel ? `${roleLabel} (one instance)` : "One instance";
}

export function DevInspector() {
  const dev = useDevMode();
  const studio = useOptionalDesignStudio();
  const {
    enabled,
    inspect,
    showIds,
    selectTarget,
    selectVars,
    selectCopy,
    clearSelectedCopy,
  } = dev;
  const [hover, setHover] = useState<Hover | null>(null);
  const [badges, setBadges] = useState<Badge[]>([]);
  const [selection, setSelection] = useState<SelectedTarget[]>([]);
  const [selectionRect, setSelectionRect] = useState<Hover["rect"] | null>(null);
  const [selectionActionsOpen, setSelectionActionsOpen] = useState(false);
  const selectionActionsButtonRef = useRef<HTMLButtonElement | null>(null);
  const selectionActionsMenuRef = useRef<HTMLDivElement | null>(null);
  const closeSelectionActions = useCallback(() => {
    setSelectionActionsOpen(false);
    window.setTimeout(() => selectionActionsButtonRef.current?.focus(), 0);
  }, []);
  useEscapeDismiss(selectionActionsOpen, closeSelectionActions);
  useEffect(() => {
    if (!selectionActionsOpen) return;
    window.setTimeout(() => selectionActionsMenuRef.current?.querySelector<HTMLButtonElement>("button")?.focus(), 0);
  }, [selectionActionsOpen]);
  const gestureRef = useRef<Gesture | null>(null);
  const draftRef = useRef(dev.draft);
  useEffect(() => {
    draftRef.current = dev.draft;
  }, [dev.draft]);

  const commitChanges = useCallback((changes: ReadonlyMap<string, Record<string, string | null> | null>) => {
    const safeChanges = new Map<string, Record<string, string | null> | null>();
    for (const [id, patch] of changes) {
      if (patch === null) {
        safeChanges.set(id, null);
        continue;
      }
      const elements = elementsForTargetDomainOverride(id);
      const safe = Object.fromEntries(Object.entries(patch).filter(
        ([property]) => !elements.some((element) => isRootProtectedDesignProperty(element, property)),
      ));
      if (Object.keys(safe).length > 0) safeChanges.set(id, safe);
    }
    const next = withElementChanges(draftRef.current, safeChanges);
    if (studio) studio.replaceResolvedDraftAtomically(next);
    else dev.replaceDraft(next);
  }, [dev, studio]);

  const measureSelection = useCallback(() => {
    const primary = selection[selection.length - 1];
    if (!primary?.element.isConnected) {
      setSelectionRect(null);
      return;
    }
    setSelectionRect(rectOf(primary.element));
  }, [selection]);

  // Capture-phase document listeners live ONLY while dev mode is enabled; the whole surface is
  // inert (and leak-free) otherwise. Re-bound when inspect flips so the click handler swallows only
  // in inspect mode (decision 7). Reading state through refs would avoid the re-bind, but re-binding
  // on the two booleans is cheap and keeps the swallow logic obvious.
  useEffect(() => {
    if (!enabled) return;

    function selectFromEvent(e: MouseEvent | PointerEvent): boolean {
      const target = e.target as Element | null;
      const el = target && "closest" in target ? selectableTarget(target) : null;
      if (!el) return false;
      const id = designIdOf(el);
      if (!id) return false;
      e.preventDefault();
      e.stopPropagation();
      const selected = selectedTargetFor(el as Element & ElementCSSInlineStyle);
      if (!selected) return false;
      setSelection((current) => {
        if (!e.shiftKey) return [selected];
        const withoutDuplicate = current.filter(
          (item) => item.element !== selected.element,
        );
        return [...withoutDuplicate, selected];
      });
      setSelectionActionsOpen(false);
      selectTarget(el);
      selectVars(usedVarsForElement(el));
      const copy = target?.closest("[data-copy-id]") ?? null;
      if (copy && (copy === el || copy.contains(el) || el.contains(copy))) {
        selectCopy(
          copy.getAttribute("data-copy-id") ?? "",
          copy.getAttribute("data-copy-default") ?? copy.textContent ?? "",
        );
      } else {
        clearSelectedCopy();
      }
      return true;
    }

    function onPointerMove(e: PointerEvent) {
      if (!inspect) return;
      const target = e.target as Element | null;
      const el = target && "closest" in target ? selectableTarget(target) : null;
      if (!el) {
        setHover(null);
        return;
      }
      const id = designIdOf(el);
      if (!id) {
        setHover(null);
        return;
      }
      setHover({ id, label: labelFor(id, el), vars: usedVarsForElement(el), rect: rectOf(el) });
    }

    function onClick(e: MouseEvent) {
      if (!inspect) return; // inspect OFF: zero behaviour change, the click passes through untouched
      // Browser pointer clicks were already selected on pointerdown. Detail zero is the keyboard
      // and synthetic-click path, which has no pointerdown and therefore selects here.
      if (e.detail === 0) selectFromEvent(e);
    }

    function onPointerDown(e: PointerEvent) {
      if (!inspect || e.button !== 0) return;
      selectFromEvent(e);
    }

    document.addEventListener("pointermove", onPointerMove, true);
    document.addEventListener("pointerdown", onPointerDown, true);
    document.addEventListener("click", onClick, true);
    return () => {
      document.removeEventListener("pointermove", onPointerMove, true);
      document.removeEventListener("pointerdown", onPointerDown, true);
      document.removeEventListener("click", onClick, true);
    };
  }, [clearSelectedCopy, enabled, inspect, selectCopy, selectTarget, selectVars]);

  useEffect(() => {
    if (!enabled || !inspect || !dev.selectedTarget) {
      if (selection.length > 0) setSelection([]);
      return;
    }
    if (selection[selection.length - 1]?.element === dev.selectedTarget.element) return;
    const element = dev.selectedTarget.element;
    if (element.isConnected && "style" in element) {
      setSelection([{
        ...dev.selectedTarget,
        label: displayLabel(dev.selectedTarget.id, element),
        element: element as Element & ElementCSSInlineStyle,
      }]);
    }
  }, [dev.selectedTarget, enabled, inspect, selection]);

  useEffect(() => {
    if (!enabled || !inspect || selection.length === 0) return;
    const observer = new MutationObserver(() => {
      setSelection((current) => {
        const connected = current.filter((target) => target.element.isConnected);
        return connected.length === current.length ? current : connected;
      });
    });
    observer.observe(document.body, { childList: true, subtree: true });
    return () => observer.disconnect();
  }, [enabled, inspect, selection.length]);

  useEffect(() => {
    measureSelection();
    window.addEventListener("resize", measureSelection);
    window.addEventListener("scroll", measureSelection, true);
    return () => {
      window.removeEventListener("resize", measureSelection);
      window.removeEventListener("scroll", measureSelection, true);
    };
  }, [measureSelection, dev.draft]);

  const restoreGesturePreview = useCallback((gesture: Gesture) => {
    for (const preview of gesture.previews) {
      for (const [property, value] of Object.entries(preview.original)) {
        if (value) preview.target.element.style.setProperty(property, value);
        else preview.target.element.style.removeProperty(property);
      }
    }
  }, []);

  const abandonGesture = useCallback(() => {
    const gesture = gestureRef.current;
    if (!gesture) return;
    gestureRef.current = null;
    restoreGesturePreview(gesture);
    try {
      if (gesture.captureTarget.hasPointerCapture?.(gesture.pointerId)) {
        gesture.captureTarget.releasePointerCapture(gesture.pointerId);
      }
    } catch {
      // A lost native capture already ended ownership; restoring the preview is still sufficient.
    }
    measureSelection();
  }, [measureSelection, restoreGesturePreview]);

  useEffect(() => {
    function onPointerMove(event: PointerEvent) {
      const gesture = gestureRef.current;
      if (!gesture || event.pointerId !== gesture.pointerId) return;
      const deltaX = (event.clientX - gesture.startX) / gesture.scale;
      const deltaY = (event.clientY - gesture.startY) / gesture.scale;
      const activeElements = draftRef.current.elements;
      const resizing = gesture.kind !== "move" && gesture.kind !== "rotate";
      const east = resizing && gesture.kind.includes("east");
      const west = resizing && gesture.kind.includes("west");
      const north = resizing && gesture.kind.includes("north");
      const south = resizing && gesture.kind.includes("south");
      const currentAngle = Math.atan2(event.clientY - gesture.centerY, event.clientX - gesture.centerX) * 180 / Math.PI;
      const angleDelta = currentAngle - gesture.startAngle;
      const changed = gesture.kind === "rotate"
        ? Math.abs(angleDelta) > 0.01
        : Math.abs(deltaX) > 0.01 || Math.abs(deltaY) > 0.01;
      if (!changed) return;
      gesture.changed = true;
      for (const preview of gesture.previews) {
        const { element, overrideId } = preview.target;
        const activeOverride = activeElements[overrideId];
        if (gesture.kind === "move") {
          element.style.position = activeOverride?.position === "absolute"
            ? "absolute"
            : "relative";
          element.style.left = `${snap(preview.baseLeft + deltaX, gesture.grid)}px`;
          element.style.top = `${snap(preview.baseTop + deltaY, gesture.grid)}px`;
          continue;
        }
        if (gesture.kind === "rotate") {
          element.style.transform = transformWithRotation(
            preview.baseTransform,
            snap(preview.baseRotation + angleDelta, rotationStepFor(element)),
          );
          continue;
        }
        if (east || west) {
          element.style.width = `${Math.max(1, snap(preview.baseWidth + (east ? deltaX : -deltaX), gesture.grid))}px`;
        }
        if (north || south) {
          element.style.height = `${Math.max(1, snap(preview.baseHeight + (south ? deltaY : -deltaY), gesture.grid))}px`;
        }

        // Width/height alone are not directional in flex/grid layouts: a centered or end-aligned
        // child can grow through the opposite edge. Measure the browser's actual result, then offset
        // only enough to keep the edge opposite the dragged handle fixed.
        const resized = element.getBoundingClientRect();
        if (east || west) {
          const desiredLeft = west ? preview.renderedRight - resized.width : preview.renderedLeft;
          const correction = (desiredLeft - resized.left) / gesture.scale;
          if (west || Math.abs(correction) > 0.01 || activeOverride?.left) {
            element.style.position = activeOverride?.position ?? "relative";
            element.style.left = roundedCssPixel(preview.baseLeft + correction);
          }
        }
        if (north || south) {
          const desiredTop = north ? preview.renderedBottom - resized.height : preview.renderedTop;
          const correction = (desiredTop - resized.top) / gesture.scale;
          if (north || Math.abs(correction) > 0.01 || activeOverride?.top) {
            element.style.position = activeOverride?.position ?? "relative";
            element.style.top = roundedCssPixel(preview.baseTop + correction);
          }
        }
      }
      measureSelection();
    }

    function finishGesture(event: PointerEvent) {
      const gesture = gestureRef.current;
      if (!gesture || event.pointerId !== gesture.pointerId) return;
      gestureRef.current = null;
      if (!gesture.changed) {
        measureSelection();
        return;
      }
      const changes = new Map<string, Record<string, string>>();
      for (const preview of gesture.previews) {
        const props: Record<string, string> = {};
        const properties = gesture.kind === "move"
          ? ["position", "left", "top"]
          : gesture.kind === "rotate"
            ? ["transform"]
            : ["position", "left", "top", "width", "height"];
        for (const property of properties) {
          const value = preview.target.element.style.getPropertyValue(property);
          if (value) props[property] = value;
        }
        changes.set(preview.target.overrideId, props);
      }
      restoreGesturePreview(gesture);
      commitChanges(changes);
    }

    function cancelByKey(event: KeyboardEvent) {
      if (event.key !== "Escape" || !gestureRef.current) return;
      event.preventDefault();
      abandonGesture();
    }
    function cancelByPointer(event: PointerEvent) {
      const gesture = gestureRef.current;
      if (!gesture || event.pointerId !== gesture.pointerId) return;
      abandonGesture();
    }
    function cancelStaleGesture() {
      // A new press cannot belong to an older still-active pointer sequence. If the native release
      // was lost, end the stale preview before the capture-phase inspector selects another target.
      abandonGesture();
    }

    window.addEventListener("pointermove", onPointerMove);
    window.addEventListener("pointerup", finishGesture);
    window.addEventListener("pointercancel", cancelByPointer);
    window.addEventListener("lostpointercapture", cancelByPointer);
    window.addEventListener("pointerdown", cancelStaleGesture, true);
    window.addEventListener("blur", abandonGesture);
    window.addEventListener("keydown", cancelByKey, true);
    return () => {
      window.removeEventListener("pointermove", onPointerMove);
      window.removeEventListener("pointerup", finishGesture);
      window.removeEventListener("pointercancel", cancelByPointer);
      window.removeEventListener("lostpointercapture", cancelByPointer);
      window.removeEventListener("pointerdown", cancelStaleGesture, true);
      window.removeEventListener("blur", abandonGesture);
      window.removeEventListener("keydown", cancelByKey, true);
      abandonGesture();
    };
  }, [abandonGesture, commitChanges, measureSelection, restoreGesturePreview]);

  useEffect(() => {
    function cycleTarget(event: KeyboardEvent) {
      if (!enabled || !inspect || event.key !== "Tab") return;
      const eventTarget = event.target;
      if (eventTarget instanceof Element && eventTarget.closest(
        "input, textarea, select, button, a[href], [contenteditable='true'], [role='button'], [tabindex]:not([tabindex='-1']), [data-design-studio-chrome]",
      )) return;
      const current = selection[selection.length - 1];
      if (!current) return;
      const next = event.shiftKey
        ? current.element.parentElement?.closest(DESIGN_TARGET_SELECTOR)
        : current.element.querySelector(DESIGN_TARGET_SELECTOR);
      if (!next || !("style" in next)) return;
      const id = designIdOf(next);
      if (!id) return;
      const target = selectedTargetFor(next as Element & ElementCSSInlineStyle);
      if (!target) return;
      event.preventDefault();
      setSelection([target]);
      selectTarget(next);
      selectVars(usedVarsForElement(next));
    }
    window.addEventListener("keydown", cycleTarget);
    return () => window.removeEventListener("keydown", cycleTarget);
  }, [enabled, inspect, selectTarget, selectVars, selection]);

  const beginGesture = useCallback((event: ReactPointerEvent<HTMLButtonElement>, kind: GestureKind) => {
    event.preventDefault();
    event.stopPropagation();
    const primary = selection[selection.length - 1];
    if (!primary) return;
    try {
      event.currentTarget.setPointerCapture?.(event.pointerId);
    } catch {
      // Global fenced listeners remain the compatibility path on older embedded browsers.
    }
    const grid = gridFor(primary.element);
    const rect = primary.element.getBoundingClientRect();
    const width = primary.element instanceof HTMLElement ? primary.element.offsetWidth : 0;
    const scale = width > 0 && rect.width > 0 ? rect.width / width : 1;
    gestureRef.current = {
      pointerId: event.pointerId,
      captureTarget: event.currentTarget,
      kind,
      startX: event.clientX,
      startY: event.clientY,
      scale,
      grid,
      centerX: rect.left + rect.width / 2,
      centerY: rect.top + rect.height / 2,
      startAngle: Math.atan2(event.clientY - (rect.top + rect.height / 2), event.clientX - (rect.left + rect.width / 2)) * 180 / Math.PI,
      changed: false,
      previews: selection.map((target) => {
        const overrides = draftRef.current.elements[target.overrideId] ?? {};
        const targetRect = target.element.getBoundingClientRect();
        const targetWidth = target.element instanceof HTMLElement && target.element.offsetWidth > 0
          ? target.element.offsetWidth
          : targetRect.width / scale;
        const targetHeight = target.element instanceof HTMLElement && target.element.offsetHeight > 0
          ? target.element.offsetHeight
          : targetRect.height / scale;
        const inlineTransform = target.element.style.transform;
        const computedTransform = getComputedStyle(target.element).transform;
        const baseTransform = overrides.transform
          ?? (inlineTransform && inlineTransform !== "none" ? inlineTransform : computedTransform);
        return {
          target,
          original: {
            position: target.element.style.position,
            left: target.element.style.left,
            top: target.element.style.top,
            width: target.element.style.width,
            height: target.element.style.height,
            transform: target.element.style.transform,
          },
          baseLeft: px(overrides.left),
          baseTop: px(overrides.top),
          baseWidth: px(overrides.width) || targetWidth,
          baseHeight: px(overrides.height) || targetHeight,
          baseRotation: rotationOf(baseTransform),
          baseTransform,
          renderedLeft: targetRect.left,
          renderedTop: targetRect.top,
          renderedRight: targetRect.right,
          renderedBottom: targetRect.bottom,
        };
      }),
    };
  }, [selection]);

  const moveByKeyboard = useCallback((event: ReactKeyboardEvent<HTMLButtonElement>) => {
    const vector: Record<string, [number, number]> = {
      ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1],
    };
    const direction = vector[event.key];
    if (!direction || selection.length === 0) return;
    event.preventDefault();
    const distance = gridFor(selection[selection.length - 1].element) * (event.shiftKey ? 10 : 1);
    const changes = new Map<string, Record<string, string>>();
    for (const target of selection) {
      const overrides = draftRef.current.elements[target.overrideId] ?? {};
      changes.set(target.overrideId, {
        position: overrides.position === "absolute" ? "absolute" : "relative",
        left: `${px(overrides.left) + direction[0] * distance}px`,
        top: `${px(overrides.top) + direction[1] * distance}px`,
      });
    }
    commitChanges(changes);
  }, [commitChanges, selection]);

  const resizeByKeyboard = useCallback((event: ReactKeyboardEvent<HTMLButtonElement>, direction: ResizeDirection) => {
    if (!event.key.startsWith("Arrow") || selection.length === 0) return;
    const horizontal = event.key === "ArrowLeft" || event.key === "ArrowRight";
    const vertical = event.key === "ArrowUp" || event.key === "ArrowDown";
    const west = direction.includes("west");
    const east = direction.includes("east");
    const north = direction.includes("north");
    const south = direction.includes("south");
    if ((horizontal && !west && !east) || (vertical && !north && !south)) return;
    event.preventDefault();
    const distance = gridFor(selection[selection.length - 1].element) * (event.shiftKey ? 10 : 1);
    const sign = event.key === "ArrowRight" || event.key === "ArrowDown" ? 1 : -1;
    const changes = new Map<string, Record<string, string>>();
    for (const target of selection) {
      const overrides = draftRef.current.elements[target.overrideId] ?? {};
      const element = target.element;
      const width = px(overrides.width) || (element instanceof HTMLElement ? element.offsetWidth : element.getBoundingClientRect().width);
      const height = px(overrides.height) || (element instanceof HTMLElement ? element.offsetHeight : element.getBoundingClientRect().height);
      const patch: Record<string, string> = {};
      if (horizontal) {
        const delta = (east ? sign : -sign) * distance;
        patch.width = `${Math.max(1, width + delta)}px`;
        if (west) {
          patch.position = overrides.position ?? "relative";
          patch.left = `${px(overrides.left) + sign * distance}px`;
        }
      }
      if (vertical) {
        const delta = (south ? sign : -sign) * distance;
        patch.height = `${Math.max(1, height + delta)}px`;
        if (north) {
          patch.position = overrides.position ?? "relative";
          patch.top = `${px(overrides.top) + sign * distance}px`;
        }
      }
      changes.set(target.overrideId, patch);
    }
    commitChanges(changes);
  }, [commitChanges, selection]);

  const rotateByKeyboard = useCallback((event: ReactKeyboardEvent<HTMLButtonElement>) => {
    if (selection.length === 0 || !["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown"].includes(event.key)) return;
    event.preventDefault();
    const direction = event.key === "ArrowRight" || event.key === "ArrowUp" ? 1 : -1;
    const step = rotationStepFor(selection[selection.length - 1].element) * (event.shiftKey ? 10 : 1);
    const changes = new Map<string, Record<string, string>>();
    for (const target of selection) {
      const inlineTransform = target.element.style.transform;
      const computedTransform = getComputedStyle(target.element).transform;
      const current = draftRef.current.elements[target.overrideId]?.transform
        ?? (inlineTransform && inlineTransform !== "none" ? inlineTransform : computedTransform);
      changes.set(target.overrideId, {
        transform: transformWithRotation(current, rotationOf(current) + direction * step),
      });
    }
    commitChanges(changes);
  }, [commitChanges, selection]);

  const removed = selection.length > 0 && selection.every(
    (target) => dev.draft.elements[target.overrideId]?.display === "none",
  );
  const primary = selection[selection.length - 1];
  const selectionName = selection.length > 1 ? `${selection.length} Selected` : primary?.label ?? "Selection";
  const geometryEditable = selection.length > 0 && selection.every(
    (target) => !isProtectedDesignRoot(target.element),
  );

  const toggleRemoval = useCallback(() => {
    const changes = new Map<string, Record<string, string | null>>();
    for (const target of selection) changes.set(target.overrideId, { display: removed ? null : "none" });
    commitChanges(changes);
  }, [commitChanges, removed, selection]);

  const resetSelection = useCallback(() => {
    commitChanges(new Map(selection.map((target) => [target.overrideId, null])));
  }, [commitChanges, selection]);

  const toggleDetached = useCallback(() => {
    const detached = selection.every((target) => dev.draft.elements[target.overrideId]?.position === "absolute");
    const changes = new Map<string, Record<string, string>>();
    for (const target of selection) {
      if (detached) {
        changes.set(target.overrideId, { position: "relative" });
        continue;
      }
      const parent = target.element.parentElement?.closest(DESIGN_TARGET_SELECTOR);
      const parentAuthority = parent ? exactDesignTargetAuthority(parent) : null;
      if (parentAuthority) changes.set(parentAuthority.overrideId, { position: "relative" });
      const element = target.element;
      changes.set(target.overrideId, {
        position: "absolute",
        left: `${element instanceof HTMLElement ? element.offsetLeft : 0}px`,
        top: `${element instanceof HTMLElement ? element.offsetTop : 0}px`,
        width: `${Math.max(1, element.getBoundingClientRect().width)}px`,
        height: `${Math.max(1, element.getBoundingClientRect().height)}px`,
      });
    }
    commitChanges(changes);
  }, [commitChanges, dev.draft.elements, selection]);

  const adjustLayer = useCallback((delta: -1 | 1) => {
    const changes = new Map<string, Record<string, string>>();
    const setLayer = (
      authority: ExactDesignTargetAuthority,
      index: number,
      computedPosition?: string,
    ) => {
      const existing = changes.get(authority.overrideId) ?? {};
      const patch: Record<string, string> = { ...existing, "z-index": String(index) };
      const position = draftRef.current.elements[authority.overrideId]?.position
        ?? computedPosition
        ?? getComputedStyle(authority.element).position;
      if ((position || "static") === "static") patch.position = "relative";
      changes.set(authority.overrideId, patch);
    };
    for (const target of selection) {
      const override = draftRef.current.elements[target.overrideId]?.["z-index"];
      const computedStyle = getComputedStyle(target.element);
      const current = Number.parseInt(override ?? computedStyle.zIndex, 10);
      const normalizedCurrent = Number.isFinite(current) ? current : 0;
      const siblings = effectiveSiblingPaintEntries(target.element);
      const siblingIndexes = siblings.map((sibling) => sibling.index);
      const requested = siblingIndexes.length === 0
        ? normalizedCurrent + delta
        : delta > 0
          ? Math.max(normalizedCurrent, ...siblingIndexes) + 1
          : Math.min(normalizedCurrent, ...siblingIndexes) - 1;

      if (requested > DESIGN_TARGET_Z_INDEX_MAX || requested < DESIGN_TARGET_Z_INDEX_MIN) {
        const boundary = delta > 0 ? DESIGN_TARGET_Z_INDEX_MAX : DESIGN_TARGET_Z_INDEX_MIN;
        const peerBoundary = boundary - delta;
        const parent = target.element.parentElement;
        if (parent) ensureDesignIdentities(parent);
        for (const sibling of siblings) {
          const saturated = delta > 0
            ? sibling.index >= DESIGN_TARGET_Z_INDEX_MAX
            : sibling.index <= DESIGN_TARGET_Z_INDEX_MIN;
          if (!saturated) continue;
          const authority = exactDesignTargetAuthority(sibling.element);
          if (authority) setLayer(authority, peerBoundary, sibling.position);
        }
        setLayer(target, boundary, computedStyle.position);
        continue;
      }
      setLayer(target, requested, computedStyle.position);
    }
    commitChanges(changes);
  }, [commitChanges, selection]);

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
      const nodes = Array.from(document.querySelectorAll(DESIGN_TARGET_SELECTOR))
        .filter((element) => !element.closest("[data-design-studio-chrome]"));
      setBadges(
        nodes.map((el) => {
          const id = designIdOf(el) ?? "";
          return { id, label: labelFor(id, el) || id, rect: rectOf(el) };
        }),
      );
    }
    enumerate();
    window.addEventListener("resize", enumerate);
    return () => window.removeEventListener("resize", enumerate);
  }, [enabled, showIds]);

  if (!enabled) return null;

  return createPortal(
    <div data-design-studio-chrome="true" className="pointer-events-none fixed inset-0 z-[190]">
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
            <span className="truncate text-xs font-semibold text-t1">{hover.label}</span>
          </div>
        </div>
      ) : null}

      {/* Show IDs overlay: one static badge over every [data-dev-id] node, in every window. */}
      {showIds
        ? badges.map((b, i) => (
            <span
              key={`${b.id}-${i}`}
              data-testid="dev-id-badge"
              className="absolute rounded-[3px] bg-acc px-1 py-0.5 font-mono text-2xs font-semibold text-acc-on shadow-card"
              style={{ left: b.rect.left, top: b.rect.top }}
            >
              {b.id}
            </span>
          ))
        : null}

      {inspect && primary && selectionRect ? (
        <div
          data-testid="dev-selection-overlay"
          className="absolute rounded-[4px] outline outline-2 outline-acc"
          style={{
            left: selectionRect.left,
            top: selectionRect.top,
            width: selectionRect.width,
            height: selectionRect.height,
          }}
        >
          <div className="pointer-events-auto absolute bottom-full left-0 mb-2 flex items-center gap-1 rounded-control border border-line2 bg-popover p-1 shadow-pop">
            <span className="max-w-40 truncate px-1 text-2xs font-semibold text-t1">{selectionName}</span>
            {geometryEditable ? <button type="button" aria-label={`Move ${selectionName}`} title={`Move ${selectionName}`} onPointerDown={(event) => beginGesture(event, "move")} onKeyDown={moveByKeyboard} className="rounded-control bg-acc px-2 py-1 text-xs font-semibold text-acc-on">Move</button> : null}
            {geometryEditable ? <button type="button" aria-label={`${removed ? "Restore" : "Remove"} ${selectionName}${removed ? "" : " From Arrangement"}`} onClick={toggleRemoval} className="rounded-control px-1.5 py-1 text-xs text-t1 hover:bg-control-hover">{removed ? "Restore" : "Remove"}</button> : null}
            <div className="relative">
              <button ref={selectionActionsButtonRef} type="button" aria-expanded={selectionActionsOpen} aria-label={`More actions for ${selectionName}`} onClick={() => selectionActionsOpen ? closeSelectionActions() : setSelectionActionsOpen(true)} className="rounded-control px-2 py-1 text-xs text-t1 hover:bg-control-hover">More</button>
              {selectionActionsOpen ? <div ref={selectionActionsMenuRef} className="absolute left-0 top-full mt-1 grid min-w-36 gap-0.5 rounded-control bg-popover p-1 shadow-pop">
                {geometryEditable ? <button type="button" aria-label={`Rotate ${selectionName}`} title={`Rotate ${selectionName}`} onPointerDown={(event) => beginGesture(event, "rotate")} onKeyDown={rotateByKeyboard} className="rounded-control px-2 py-1 text-left text-xs text-t1 hover:bg-control-hover">Rotate</button> : null}
                {geometryEditable ? <button type="button" aria-label={`${dev.draft.elements[primary.overrideId]?.position === "absolute" ? "Flow" : "Detach"} ${selectionName}`} onClick={toggleDetached} className="rounded-control px-2 py-1 text-left text-xs text-t1 hover:bg-control-hover">{dev.draft.elements[primary.overrideId]?.position === "absolute" ? "Return To Flow" : "Detach"}</button> : null}
                {geometryEditable ? <button type="button" aria-label={`Bring ${selectionName} Forward`} onClick={() => adjustLayer(1)} className="rounded-control px-2 py-1 text-left text-xs text-t1 hover:bg-control-hover">Bring Forward</button> : null}
                {geometryEditable ? <button type="button" aria-label={`Send ${selectionName} Backward`} onClick={() => adjustLayer(-1)} className="rounded-control px-2 py-1 text-left text-xs text-t1 hover:bg-control-hover">Send Backward</button> : null}
                <button type="button" aria-label={`Reset ${selectionName}`} onClick={resetSelection} className="rounded-control px-2 py-1 text-left text-xs text-t1 hover:bg-control-hover">Reset</button>
              </div> : null}
            </div>
          </div>
          {geometryEditable ? RESIZE_DIRECTIONS.map((direction) => (
            <button
              key={direction}
              type="button"
              aria-label={`Resize ${selectionName} ${direction[0].toUpperCase()}${direction.slice(1)}`}
              onPointerDown={(event) => beginGesture(event, direction)}
              onKeyDown={(event) => resizeByKeyboard(event, direction)}
              className="pointer-events-auto absolute size-2 -translate-x-1/2 -translate-y-1/2 rounded-full border border-acc bg-surface shadow-card"
              style={HANDLE_POSITION[direction]}
            />
          )) : null}
        </div>
      ) : null}
    </div>,
    document.body,
  );
}
