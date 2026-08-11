/**
 * The dev mode override draft: the one working document Save writes back to source.
 *
 * tokens + copy + icons + elements + behaviors + layout are six slices of ONE document, not six
 * independent states - a history restore writes all six together, and Reset all clears all six
 * together. They therefore live behind a single reducer, so each of those transitions is one
 * dispatched action rather than a list of setter calls that could ever land apart.
 *
 * THE SIXTH SLICE IS THE ARRANGEMENT (Design Mode Phase 3). It is one whole layout document rather
 * than a map of keyed overrides, because an arrangement is a tree and half a tree is not an
 * arrangement. `null` means "no edit", and the renderer then falls through to the committed override
 * and the shipped default - see `layout/resolveWorkspaceLayout.ts` for that order.
 *
 * It joins the same history and the same Reset all as the other five (plan 1.5: "undo/redo spans
 * structure and style as one history"), and it is deliberately EXCLUDED from Save - see the comment
 * in `devModeSave.ts`.
 *
 * This module also owns the two effects that push the draft at the document (tokens as CSS
 * variables, elements as inline styles). Both run regardless of whether dev mode is `enabled`, so
 * the shipped design is always whatever was last saved. The layout slice needs no effect of its own:
 * the workspace reads it at render, which is what makes an arrangement edit a re-render rather than a
 * write to the DOM behind React's back.
 */
import { useCallback, useEffect, useLayoutEffect, useMemo, useReducer, useRef } from "react";
import type { LayoutDocument } from "../layout/document";
import type { Theme } from "./theme";
import { DEV_TOKENS, DEV_TOKEN_BY_VAR } from "./devTokens";
import { TOKEN_OVERRIDES } from "./token.overrides";
import { COPY_OVERRIDES } from "./copy.overrides";
import { ICON_OVERRIDES, type IconOverride } from "./icon.overrides";
import { ELEMENT_OVERRIDES } from "./element.overrides";
import { LAYOUT_OVERRIDES } from "./layout.overrides";
import {
  BEHAVIOR_OVERRIDES,
  type BehaviorOverride,
} from "./behavior.overrides";
import { applyElementOverrides, startElementOverrideObserver } from "./applyElementOverrides";

// The two override blocks: dark colours + shared radii on :root ("root"), light colours on
// :root[data-theme="light"] ("light"). Defined here (not in the regenerated overrides file) so the
// backend writer can rewrite token.overrides.ts as a bare const.
export interface TokenOverrides {
  root: Record<string, string>;
  light: Record<string, string>;
}

// Which override block a token edit lands in: dark colours + shared radii live on :root ("root"),
// light colours on :root[data-theme="light"] ("light").
export type TokenSelector = keyof TokenOverrides;

// The whole working document. Its key order is load-bearing: the history stack snapshots it with
// JSON.stringify, so every reducer branch must preserve this exact shape.
export interface DevModeDraft {
  tokens: TokenOverrides;
  copy: Record<string, string>;
  icons: Record<string, IconOverride>;
  elements: Record<string, Record<string, string>>;
  behaviors: Record<string, BehaviorOverride>;
  /** The working arrangement of the opened-component workspace, or `null` for "no edit". */
  layout: LayoutDocument | null;
}

function cloneTokens(src: TokenOverrides): TokenOverrides {
  return { root: { ...src.root }, light: { ...src.light } };
}

// A shallow clone of the committed icon overrides for the working-state (each entry copied so an
// edit never mutates the frozen imported module).
function cloneIcons(src: Record<string, IconOverride>): Record<string, IconOverride> {
  const out: Record<string, IconOverride> = {};
  for (const [id, ov] of Object.entries(src)) out[id] = { ...ov };
  return out;
}

// A shallow clone of the committed element overrides for the working-state (each per-id prop map
// copied so an edit never mutates the frozen imported module).
function cloneElements(
  src: Record<string, Record<string, string>>,
): Record<string, Record<string, string>> {
  const out: Record<string, Record<string, string>> = {};
  for (const [id, props] of Object.entries(src)) out[id] = { ...props };
  return out;
}

// A DEEP copy of the committed layout document, because an edit operation returns a new document but
// shares every untouched subtree with the one it was handed - so a working draft that started life as
// the imported module would share subtrees with it, and editing the draft would reach into the
// committed arrangement. `structuredClone` rather than a JSON round trip: a layout document is plain
// serialisable data (document.ts), so both produce the same tree, and this one does it without
// building the whole document as a string first.
function cloneLayout(src: LayoutDocument | null): LayoutDocument | null {
  return src ? structuredClone(src) : null;
}

function cloneBehaviors(src: Record<string, BehaviorOverride>): Record<string, BehaviorOverride> {
  const out: Record<string, BehaviorOverride> = {};
  for (const [id, override] of Object.entries(src)) out[id] = { ...override };
  return out;
}

/** A fresh copy of the source-owned design that resolution can safely build on. */
export function committedDevModeDraft(): DevModeDraft {
  return {
    tokens: cloneTokens(TOKEN_OVERRIDES),
    copy: { ...COPY_OVERRIDES },
    icons: cloneIcons(ICON_OVERRIDES),
    elements: cloneElements(ELEMENT_OVERRIDES),
    behaviors: cloneBehaviors(BEHAVIOR_OVERRIDES),
    layout: cloneLayout(LAYOUT_OVERRIDES.workspace),
  };
}

// Reset all: every slice back to the shipped design, in one object so no slice can be forgotten.
// `layout: null` is the arrangement's version of an empty override map - the shipped default document.
export function emptyDevModeDraft(): DevModeDraft {
  return {
    tokens: { root: {}, light: {} },
    copy: {},
    icons: {},
    elements: {},
    behaviors: {},
    layout: null,
  };
}

export interface DraftTargetReset {
  targetIds: readonly string[];
  copyIds?: readonly string[];
  iconIds?: readonly string[];
}

/** Remove every persisted facet owned by concrete inspected targets in one immutable history step. */
export function resetDraftTargets(draft: DevModeDraft, reset: DraftTargetReset): DevModeDraft {
  const next: DevModeDraft = {
    tokens: cloneTokens(draft.tokens),
    copy: { ...draft.copy },
    icons: cloneIcons(draft.icons),
    elements: cloneElements(draft.elements),
    behaviors: cloneBehaviors(draft.behaviors),
    layout: cloneLayout(draft.layout),
  };
  for (const id of reset.targetIds) {
    delete next.elements[id];
    delete next.elements[`${id}::text`];
    delete next.elements[`${id}::icon`];
    delete next.behaviors[id];
  }
  for (const id of reset.copyIds ?? []) delete next.copy[id];
  for (const id of reset.iconIds ?? []) delete next.icons[id];
  return next;
}

/** Remove one CSS property from each resolved domain target in one immutable draft. */
export function resetDraftElementProperty(
  draft: DevModeDraft,
  targetIds: readonly string[],
  property: string,
): DevModeDraft {
  const next = resetDraftTargets(draft, { targetIds: [] });
  for (const id of targetIds) {
    if (!next.elements[id]) continue;
    delete next.elements[id][property];
    if (Object.keys(next.elements[id]).length === 0) delete next.elements[id];
  }
  return next;
}

/** Clear only the active theme's token overrides; all structural and opposite-theme edits survive. */
export function resetDraftTheme(draft: DevModeDraft, theme: Theme): DevModeDraft {
  const next = resetDraftTargets(draft, { targetIds: [] });
  if (theme === "light") next.tokens.light = {};
  else next.tokens.root = {};
  return next;
}

type DraftAction =
  | { type: "setToken"; selector: TokenSelector; cssVar: string; value: string }
  | { type: "resetToken"; selector: TokenSelector; cssVar: string }
  | { type: "setCopy"; id: string; text: string }
  | { type: "resetCopy"; id: string }
  | { type: "patchIcon"; id: string; patch: IconOverride }
  | { type: "resetIcon"; id: string }
  | { type: "setElementProp"; id: string; prop: string; value: string }
  | { type: "resetElementProp"; id: string; prop: string }
  | { type: "clearElement"; id: string }
  | { type: "setBehavior"; id: string; override: BehaviorOverride }
  | { type: "resetBehavior"; id: string }
  // The arrangement is written WHOLE (the edit operations in `layout/editOperations.ts` each return a
  // complete document), so there is one write action and one clear, not a set of field actions.
  | { type: "setLayout"; layout: LayoutDocument }
  | { type: "resetLayout" }
  // One action restores all six slices, so a history step can never half-apply.
  | { type: "restore"; draft: DevModeDraft }
  // One action replaces all six slices from a resolved personal document.
  | { type: "replace"; draft: DevModeDraft }
  // One action clears all six slices, for the same reason.
  | { type: "resetAll" };

function draftReducer(state: DevModeDraft, action: DraftAction): DevModeDraft {
  switch (action.type) {
    case "setToken": {
      const block = { ...state.tokens[action.selector], [action.cssVar]: action.value };
      return { ...state, tokens: { ...state.tokens, [action.selector]: block } };
    }
    case "resetToken": {
      const block = { ...state.tokens[action.selector] };
      delete block[action.cssVar];
      return { ...state, tokens: { ...state.tokens, [action.selector]: block } };
    }
    case "setCopy":
      return { ...state, copy: { ...state.copy, [action.id]: action.text } };
    case "resetCopy": {
      const copy = { ...state.copy };
      delete copy[action.id];
      return { ...state, copy };
    }
    case "patchIcon":
      return {
        ...state,
        icons: { ...state.icons, [action.id]: { ...state.icons[action.id], ...action.patch } },
      };
    case "resetIcon": {
      const icons = { ...state.icons };
      delete icons[action.id];
      return { ...state, icons };
    }
    case "setElementProp":
      return {
        ...state,
        elements: {
          ...state.elements,
          [action.id]: { ...state.elements[action.id], [action.prop]: action.value },
        },
      };
    case "resetElementProp": {
      const props = { ...state.elements[action.id] };
      delete props[action.prop];
      const elements = { ...state.elements };
      // Drop the id entirely once its last property is gone, so the map never holds an empty entry.
      if (Object.keys(props).length === 0) delete elements[action.id];
      else elements[action.id] = props;
      return { ...state, elements };
    }
    case "clearElement": {
      const elements = { ...state.elements };
      delete elements[action.id];
      return { ...state, elements };
    }
    case "setBehavior":
      return {
        ...state,
        behaviors: {
          ...state.behaviors,
          [action.id]: { ...(state.behaviors[action.id] ?? {}), ...action.override },
        },
      };
    case "resetBehavior": {
      const behaviors = { ...state.behaviors };
      delete behaviors[action.id];
      return { ...state, behaviors };
    }
    case "setLayout":
      return { ...state, layout: action.layout };
    case "resetLayout":
      return state.layout === null ? state : { ...state, layout: null };
    case "restore": {
      const { tokens, copy, icons, elements, behaviors, layout } = action.draft;
      // Rebuilt field by field rather than spread, so the snapshot shape is stated in one place and a
      // stored snapshot that predates a slice restores as that slice's empty value.
      return { tokens, copy, icons, elements, behaviors, layout: layout ?? null };
    }
    case "replace":
      return {
        tokens: cloneTokens(action.draft.tokens),
        copy: { ...action.draft.copy },
        icons: cloneIcons(action.draft.icons),
        elements: cloneElements(action.draft.elements),
        behaviors: cloneBehaviors(action.draft.behaviors),
        layout: cloneLayout(action.draft.layout),
      };
    case "resetAll":
      return emptyDevModeDraft();
  }
}

/**
 * The override draft plus the panel-facing read/edit/reset callbacks over it. `theme` decides which
 * block a colour edit lands in, so the same token id can hold a different value per theme.
 */
export function useDevModeDraft(theme: Theme) {
  const [draft, dispatch] = useReducer(draftReducer, undefined, committedDevModeDraft);
  const { tokens, copy, icons, elements, behaviors, layout } = draft;

  const activeSelector: TokenSelector = theme === "light" ? "light" : "root";

  const tokenValue = useCallback(
    (cssVar: string): string => {
      const token = DEV_TOKEN_BY_VAR.get(cssVar);
      if (!token) return "";
      const selector: TokenSelector = token.themed ? activeSelector : "root";
      const override = tokens[selector][cssVar];
      if (override != null) return override;
      return token.themed
        ? (theme === "light" ? token.default.light : token.default.dark) ?? token.default.dark
        : token.default.dark;
    },
    [tokens, activeSelector, theme],
  );

  const isTokenOverridden = useCallback(
    (cssVar: string): boolean => {
      const token = DEV_TOKEN_BY_VAR.get(cssVar);
      if (!token) return false;
      const selector: TokenSelector = token.themed ? activeSelector : "root";
      return tokens[selector][cssVar] != null;
    },
    [tokens, activeSelector],
  );

  const setToken = useCallback(
    (cssVar: string, value: string) => {
      const token = DEV_TOKEN_BY_VAR.get(cssVar);
      if (!token) return;
      const selector: TokenSelector = token.themed ? activeSelector : "root";
      dispatch({ type: "setToken", selector, cssVar, value });
    },
    [activeSelector],
  );

  const resetToken = useCallback(
    (cssVar: string) => {
      const token = DEV_TOKEN_BY_VAR.get(cssVar);
      if (!token) return;
      const selector: TokenSelector = token.themed ? activeSelector : "root";
      dispatch({ type: "resetToken", selector, cssVar });
    },
    [activeSelector],
  );

  const resolveCopy = useCallback(
    (id: string, fallback: string): string => copy[id] ?? fallback,
    [copy],
  );
  const isCopyOverridden = useCallback((id: string): boolean => id in copy, [copy]);
  const setCopy = useCallback((id: string, text: string) => {
    dispatch({ type: "setCopy", id, text });
  }, []);
  const resetCopy = useCallback((id: string) => {
    dispatch({ type: "resetCopy", id });
  }, []);

  // --- icons (D-02 / D-04) --- the working override map mirrors the copy slice one-for-one:
  // read (iconOverrideFor / resolveIconOverride), edit (setIconBody / setIconSwap), clear (resetIcon).
  const iconOverrideFor = useCallback(
    (id: string): IconOverride | undefined => icons[id],
    [icons],
  );
  // Under a provider <Icon> resolves through the working-state, so a working edit renders live.
  const resolveIconOverride = useCallback(
    (id: string): IconOverride | undefined => icons[id],
    [icons],
  );
  const isIconOverridden = useCallback(
    (id: string): boolean => {
      const ov = icons[id];
      return ov != null && (ov.body != null || ov.swapToId != null);
    },
    [icons],
  );
  const setIconBody = useCallback((id: string, body: string) => {
    dispatch({ type: "patchIcon", id, patch: { body } });
  }, []);
  const setIconSwap = useCallback((id: string, swapToId: string) => {
    dispatch({ type: "patchIcon", id, patch: { swapToId } });
  }, []);
  const resetIcon = useCallback((id: string) => {
    dispatch({ type: "resetIcon", id });
  }, []);

  // --- per-element overrides (ELEM-01) --- the working map mirrors the icon slice one-for-one:
  // read (elementOverridesFor), edit (setElementProp), clear (resetElementProp / clearElement).
  const elementOverridesFor = useCallback(
    (id: string): Record<string, string> | undefined => elements[id],
    [elements],
  );
  const isElementPropOverridden = useCallback(
    (id: string, prop: string): boolean => elements[id] != null && prop in elements[id],
    [elements],
  );
  const setElementProp = useCallback((id: string, prop: string, value: string) => {
    dispatch({ type: "setElementProp", id, prop, value });
  }, []);
  const resetElementProp = useCallback((id: string, prop: string) => {
    dispatch({ type: "resetElementProp", id, prop });
  }, []);
  const clearElement = useCallback((id: string) => {
    dispatch({ type: "clearElement", id });
  }, []);

  const behaviorOverrideFor = useCallback((id: string) => behaviors[id], [behaviors]);
  const setBehaviorOverride = useCallback((id: string, override: BehaviorOverride) => {
    dispatch({ type: "setBehavior", id, override });
  }, []);
  const resetBehaviorOverride = useCallback((id: string) => {
    dispatch({ type: "resetBehavior", id });
  }, []);

  // --- the arrangement (Design Mode Phase 3) --- one whole document in, one whole document out. The
  // EDITS live in `layout/editOperations.ts` as pure functions from document to document; this slice
  // only holds the result, which is what keeps arrangement logic out of the provider.
  const setLayoutDraft = useCallback((next: LayoutDocument) => {
    dispatch({ type: "setLayout", layout: next });
  }, []);
  const resetLayoutDraft = useCallback(() => {
    dispatch({ type: "resetLayout" });
  }, []);

  // Write all six slices at once (an undo/redo step), so the draft can never half-restore.
  const restore = useCallback((next: DevModeDraft) => {
    dispatch({ type: "restore", draft: next });
  }, []);
  // Hydration is one complete document transition, so history records it as one step.
  const replaceDraft = useCallback((next: DevModeDraft) => {
    dispatch({ type: "replace", draft: next });
  }, []);
  // Clear all six slices at once (Reset all), for the same reason.
  const resetDraft = useCallback(() => {
    dispatch({ type: "resetAll" });
  }, []);

  const api = useMemo(
    () => ({
      // The two override BLOCKS, not a reader. `tokenValue` answers for the theme being looked at,
      // which is what a panel row needs and what a validator cannot use: a colour nudged in dark
      // theme leaves the light palette alone, and the issues list has to measure both (see
      // `layout/validateContrast.ts`'s `draftThemeTokens`).
      tokenOverrides: tokens,
      tokenValue,
      isTokenOverridden,
      setToken,
      resetToken,
      resolveCopy,
      isCopyOverridden,
      setCopy,
      resetCopy,
      iconOverrideFor,
      resolveIconOverride,
      isIconOverridden,
      setIconBody,
      setIconSwap,
      resetIcon,
      elementOverridesFor,
      isElementPropOverridden,
      setElementProp,
      resetElementProp,
      clearElement,
      behaviorOverrideFor,
      setBehaviorOverride,
      resetBehaviorOverride,
      // The VALUE, not a reader: whoever draws a surface needs the document itself, and the resolution
      // order that decides whether it is the one drawn lives in `layout/resolveWorkspaceLayout.ts`.
      layoutDraft: layout,
      isLayoutEdited: layout !== null,
      setLayoutDraft,
      resetLayoutDraft,
    }),
    [
      tokens,
      tokenValue,
      isTokenOverridden,
      setToken,
      resetToken,
      resolveCopy,
      isCopyOverridden,
      setCopy,
      resetCopy,
      iconOverrideFor,
      resolveIconOverride,
      isIconOverridden,
      setIconBody,
      setIconSwap,
      resetIcon,
      elementOverridesFor,
      isElementPropOverridden,
      setElementProp,
      resetElementProp,
      clearElement,
      behaviorOverrideFor,
      setBehaviorOverride,
      resetBehaviorOverride,
      layout,
      setLayoutDraft,
      resetLayoutDraft,
    ],
  );

  return { draft, restore, replaceDraft, resetDraft, api };
}

/**
 * Push the draft at the document: tokens as CSS variables on <html>, per-element overrides as
 * inline styles on every matching [data-dev-id] node.
 */
export function useApplyDraftOverrides(
  tokens: TokenOverrides,
  elements: Record<string, Record<string, string>>,
  theme: Theme,
) {
  // Two refs drive the element-override apply: prevElementsRef holds the previously-applied map so a
  // re-apply can compute exactly which props to clear; elementsRef always holds the latest map so the
  // observer's getter re-applies the current overrides to late-mounted nodes.
  const prevElementsRef = useRef<Record<string, Record<string, string>>>(elements);
  const elementsRef = useRef(elements);
  // Synced in a layout effect, not during render: render can be replayed or thrown away, and the
  // observer getter would then re-apply overrides from a tree that never committed. Layout effects
  // land before this commit's passive effects, so the apply/observe effect below installs its
  // getter over this render's map.
  useLayoutEffect(() => {
    elementsRef.current = elements;
  });

  // Apply the committed + edited tokens to the document for the ACTIVE theme (colours are
  // theme-specific, radii shared). Runs regardless of `enabled` so the shipped design is whatever
  // was last saved; a token with no override is cleared so it falls back to the index.css default.
  useEffect(() => {
    const root = document.documentElement;
    for (const token of DEV_TOKENS) {
      const selector: TokenSelector = token.themed && theme === "light" ? "light" : "root";
      const value = tokens[selector][token.cssVar];
      if (value != null && value !== "") root.style.setProperty(token.cssVar, value);
      else root.style.removeProperty(token.cssVar);
    }
  }, [tokens, theme]);

  // Apply the committed + edited per-element overrides as inline styles on every matching
  // [data-dev-id] node. Runs regardless of `enabled` (like the token effect) so a saved tweak ships
  // for everyone. Diffs against the previously-applied map to clear exactly the props that were
  // removed, then starts an observer so a node that mounts later still receives its override.
  useEffect(() => {
    applyElementOverrides(elements, prevElementsRef.current);
    prevElementsRef.current = elements;
    return startElementOverrideObserver(() => elementsRef.current);
  }, [elements]);
}
