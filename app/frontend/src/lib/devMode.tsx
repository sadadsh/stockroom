/**
 * Dev mode: a hidden, owner-only editor for the app's own design tokens and UI copy.
 *
 * It is invisible until toggled with Ctrl/Cmd+Shift+D. While on, the Design panel nudges colour
 * and radius tokens live (per theme), and any <Text> label becomes click-to-edit. Edits are NOT
 * a per-machine setting: Save writes them back to source (lib/token.overrides.ts +
 * lib/copy.overrides.ts) via POST /api/dev/save, so a committed change ships for everyone.
 *
 * The committed overrides load from those two modules and apply on boot for EVERYONE (dev mode
 * off or on) - the provider's token effect runs regardless of `enabled`, so the shipped design
 * is whatever was last saved. `enabled` only gates the editing surface. A default no-op context
 * lets <Text> resolve committed copy even with no provider mounted (so isolated tests still work).
 *
 * The provider is a composition of five focused hooks, one per concern: the override draft
 * (devModeDraft), undo/redo (devModeHistory), Save + dirty (devModeSave), the inspect-first
 * selection (devModeSelection) and the on/off switch (devModeToggle).
 */
import { createContext, useCallback, useContext, useMemo, type ReactNode } from "react";
import type { LayoutDocument } from "../layout/document";
import { useTheme, type Theme } from "./theme";
import { DEV_TOKEN_BY_VAR } from "./devTokens";
import { COPY_OVERRIDES } from "./copy.overrides";
import { ICON_OVERRIDES, type IconOverride } from "./icon.overrides";
import { ELEMENT_OVERRIDES } from "./element.overrides";
import {
  BEHAVIOR_OVERRIDES,
  type BehaviorOverride,
} from "./behavior.overrides";
import {
  useApplyDraftOverrides,
  useDevModeDraft,
  type TokenOverrides,
} from "./devModeDraft";
import { useDevModeHistory, useDevModeHistoryKeys } from "./devModeHistory";
import { useDevModeSave } from "./devModeSave";
import { useDevModeSelection } from "./devModeSelection";
import { useDevModeToggle } from "./devModeToggle";

interface DevModeContextValue {
  enabled: boolean;
  toggle: () => void;
  // The active theme, so the panel can say which theme a colour edit targets.
  theme: Theme;
  // --- tokens ---
  // The two working override blocks themselves (dark + shared on `root`, light on `light`). The
  // panel's rows read `tokenValue` and want the active theme; the issues list has to resolve BOTH
  // palettes out of one draft, which no per-theme reader can answer.
  tokenOverrides: TokenOverrides;
  // The effective value of a token for the active theme (an override if set, else its shipped
  // default), so the panel shows what is live.
  tokenValue: (cssVar: string) => string;
  // True when a token carries an override for the active theme (drives the per-token Reset).
  isTokenOverridden: (cssVar: string) => boolean;
  setToken: (cssVar: string, value: string) => void;
  resetToken: (cssVar: string) => void;
  // --- copy ---
  resolveCopy: (id: string, fallback: string) => string;
  isCopyOverridden: (id: string) => boolean;
  setCopy: (id: string, text: string) => void;
  resetCopy: (id: string) => void;
  // --- icons (D-02 resolves overrides through the context / D-04 save writes them) ---
  // The working override held for an id (the panel-facing read), or undefined when none. Reads the
  // working-state under a provider; on the DEFAULT no-op context it reads the committed ICON_OVERRIDES.
  iconOverrideFor: (id: string) => IconOverride | undefined;
  // The override <Icon> resolves its swap-chain + body through: the working entry under a provider
  // (so an edit renders live, D-02), the committed ICON_OVERRIDES entry on the DEFAULT context (so an
  // unprovided <Icon> is byte-identical to today, D-03).
  resolveIconOverride: (id: string) => IconOverride | undefined;
  isIconOverridden: (id: string) => boolean;
  setIconBody: (id: string, body: string) => void;
  setIconSwap: (id: string, swapToId: string) => void;
  resetIcon: (id: string) => void;
  // --- per-element overrides (ELEM-01: a data-dev-id -> CSS-prop map applied as inline style) ---
  // The working prop map held for an id (the Box tab's read), or undefined when none. Reads the
  // working-state under a provider; on the DEFAULT no-op context it reads the committed ELEMENT_OVERRIDES.
  elementOverridesFor: (id: string) => Record<string, string> | undefined;
  // True when the working map holds a value for this id + prop (drives the per-property Reset).
  isElementPropOverridden: (id: string, prop: string) => boolean;
  setElementProp: (id: string, prop: string, value: string) => void;
  // Remove one property; when it was the id's last property the id drops from the working map.
  resetElementProp: (id: string, prop: string) => void;
  // Remove every property for an id (the Box tab's clear-all-for-this-element).
  clearElement: (id: string) => void;
  behaviorOverrideFor: (id: string) => BehaviorOverride | undefined;
  setBehaviorOverride: (id: string, override: BehaviorOverride) => void;
  resetBehaviorOverride: (id: string) => void;
  // --- the arrangement (Design Mode Phase 3) ---
  // The WORKING layout document for the opened-component workspace, or null when nothing is being
  // edited. Null does NOT mean "the shipped default": the committed override in lib/layout.overrides.ts
  // sits between the two, and `layout/resolveWorkspaceLayout.ts` is the one place that order is decided.
  layoutDraft: LayoutDocument | null;
  // True when a working arrangement is in force (an owner edit, or the committed override this session
  // started from). Drives the panel's revert affordance in 3C.
  isLayoutEdited: boolean;
  // Write the whole document. The EDITS are the pure functions in `layout/editOperations.ts`; nothing
  // in the provider knows what a move or a resize means.
  setLayoutDraft: (document: LayoutDocument) => void;
  // Back to no edit, so the committed override (or the shipped default) draws again.
  resetLayoutDraft: () => void;
  canUndo: boolean;
  canRedo: boolean;
  undo: () => void;
  redo: () => void;
  // The label the panel is currently editing (clicked in dev mode), with its default text so the
  // panel can show + reset to it, or null.
  selectedCopyId: string | null;
  selectedCopyDefault: string;
  selectCopy: (id: string, defaultText: string) => void;
  clearSelectedCopy: () => void;
  // --- inspect / selection (Dev Mode v2 inspect-first shell) ---
  // The one element selection that drives the Selection pane, the Tokens tab, and the Copy tab. Set
  // by an inspect-click, a catalogue click, or a Show IDs read; null means "no selection".
  selectedDevId: string | null;
  selectDevId: (id: string | null) => void;
  // Pointing mode: while on, the Inspector hover-highlights the closest [data-dev-id] and a click
  // selects it and is swallowed (never fires the app / copy layer). Off is zero behaviour change.
  inspect: boolean;
  toggleInspect: () => void;
  // The all-at-once overlay: one static id badge over every [data-dev-id] node, in every window.
  showIds: boolean;
  toggleShowIds: () => void;
  // ARRANGE (plan 1.5): the running application becomes the canvas - a handle over every placement,
  // draggable region boundaries, a settings menu per piece. Already ANDed with `enabled` by
  // `devModeToggle`, so a consumer never has to remember to. OFF is zero behaviour change, which is
  // what `ComponentWorkspace.domParity.test.tsx` holds this phase to.
  editMode: boolean;
  toggleEditMode: () => void;
  // The used design tokens of the current selection (cssVars), driving which Tokens rows show and a
  // scroll-into-view of the first. Set alongside the selection via selectVars.
  highlightedVars: string[];
  selectVars: (vars: string[]) => void;
  // --- persistence ---
  dirty: boolean;
  saving: boolean;
  lastError: string | null;
  save: () => Promise<void>;
  resetAll: () => void;
}

const noop = () => {};

// Without a provider (isolated tests, Storybook), dev mode is inert but committed copy still
// resolves, so a <Text> renders the shipped override or its default either way.
const DEFAULT: DevModeContextValue = {
  enabled: false,
  toggle: noop,
  theme: "dark",
  // No provider: nothing is being edited, so both blocks are empty and a reader of them measures the
  // shipped defaults - which is exactly what `tokenValue` below answers with on this same context.
  tokenOverrides: { root: {}, light: {} },
  tokenValue: (cssVar) => {
    const t = DEV_TOKEN_BY_VAR.get(cssVar);
    return t?.default.dark ?? "";
  },
  isTokenOverridden: () => false,
  setToken: noop,
  resetToken: noop,
  resolveCopy: (id, fallback) => COPY_OVERRIDES[id] ?? fallback,
  isCopyOverridden: () => false,
  setCopy: noop,
  resetCopy: noop,
  // No provider: committed icon overrides still resolve, so an unprovided <Icon> draws the shipped
  // override or its registry default exactly as today (mirror resolveCopy -> COPY_OVERRIDES[id]).
  iconOverrideFor: (id) => ICON_OVERRIDES[id],
  resolveIconOverride: (id) => ICON_OVERRIDES[id],
  isIconOverridden: () => false,
  setIconBody: noop,
  setIconSwap: noop,
  resetIcon: noop,
  // No provider: committed element overrides still resolve (so the Box tab reads what shipped), and
  // the setters are inert - mirrors iconOverrideFor -> ICON_OVERRIDES[id].
  elementOverridesFor: (id) => ELEMENT_OVERRIDES[id],
  isElementPropOverridden: () => false,
  setElementProp: noop,
  resetElementProp: noop,
  clearElement: noop,
  behaviorOverrideFor: (id) => BEHAVIOR_OVERRIDES[id],
  setBehaviorOverride: noop,
  resetBehaviorOverride: noop,
  // No provider: there is no working arrangement, and that is not the same as there being no
  // committed one. Unlike the five keyed slices, the committed layout is NOT exposed here - the
  // resolver reads `LAYOUT_OVERRIDES` directly, so a workspace mounted with no provider (an isolated
  // test) draws the committed arrangement exactly as the application does.
  layoutDraft: null,
  isLayoutEdited: false,
  setLayoutDraft: noop,
  resetLayoutDraft: noop,
  canUndo: false,
  canRedo: false,
  undo: noop,
  redo: noop,
  selectedCopyId: null,
  selectedCopyDefault: "",
  selectCopy: noop,
  clearSelectedCopy: noop,
  selectedDevId: null,
  selectDevId: noop,
  inspect: false,
  toggleInspect: noop,
  showIds: false,
  toggleShowIds: noop,
  editMode: false,
  toggleEditMode: noop,
  highlightedVars: [],
  selectVars: noop,
  dirty: false,
  saving: false,
  lastError: null,
  save: async () => {},
  resetAll: noop,
};

const DevModeContext = createContext<DevModeContextValue>(DEFAULT);

export function DevModeProvider({ children }: { children: ReactNode }) {
  const { theme } = useTheme();
  // The hook call order below is the effect order: snapshot, the Ctrl/Cmd+Shift+D toggle, the
  // Ctrl/Cmd+Z history keys, then the two document applies (tokens, elements).
  const { draft, restore, resetDraft, api: draftApi } = useDevModeDraft(theme);
  const { api: historyApi, historyRevision, undo, redo } = useDevModeHistory(draft, restore);
  const { api: toggleApi, enabled, clearSelectedCopy } = useDevModeToggle();
  useDevModeHistoryKeys(enabled, undo, redo);
  useApplyDraftOverrides(draft.tokens, draft.elements, theme);
  const selectionApi = useDevModeSelection();
  const saveApi = useDevModeSave(draft);

  // Reset all is one draft action - all six slices clear together, the arrangement included - plus
  // dropping the label the copy editor was pointed at, which is not part of the saved document.
  const resetAll = useCallback(() => {
    resetDraft();
    clearSelectedCopy();
  }, [resetDraft, clearSelectedCopy]);

  const value = useMemo<DevModeContextValue>(
    () => ({
      ...toggleApi,
      theme,
      ...draftApi,
      ...historyApi,
      ...selectionApi,
      ...saveApi,
      resetAll,
    }),
    [
      toggleApi,
      theme,
      draftApi,
      historyApi,
      // The undo/redo stacks are refs, so a push or pop alone does not re-render. This counter is
      // what makes Undo/Redo enable immediately after a ref-only stack mutation.
      historyRevision,
      selectionApi,
      saveApi,
      resetAll,
    ],
  );

  return <DevModeContext.Provider value={value}>{children}</DevModeContext.Provider>;
}

export function useDevMode(): DevModeContextValue {
  return useContext(DevModeContext);
}
