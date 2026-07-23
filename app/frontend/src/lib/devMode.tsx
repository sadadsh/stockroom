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
 */
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { api } from "../api/client";
import { ApiError } from "../api/client";
import { useTheme, type Theme } from "./theme";
import { DEV_TOKENS, DEV_TOKEN_BY_VAR } from "./devTokens";
import { TOKEN_OVERRIDES } from "./token.overrides";
import { COPY_OVERRIDES } from "./copy.overrides";

// The two override blocks: dark colours + shared radii on :root ("root"), light colours on
// :root[data-theme="light"] ("light"). Defined here (not in the regenerated overrides file) so the
// backend writer can rewrite token.overrides.ts as a bare const.
interface TokenOverrides {
  root: Record<string, string>;
  light: Record<string, string>;
}

// Which override block a token edit lands in: dark colours + shared radii live on :root ("root"),
// light colours on :root[data-theme="light"] ("light").
type TokenSelector = keyof TokenOverrides;

interface DevModeContextValue {
  enabled: boolean;
  toggle: () => void;
  // The active theme, so the panel can say which theme a colour edit targets.
  theme: Theme;
  // --- tokens ---
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
  // The label the panel is currently editing (clicked in dev mode), with its default text so the
  // panel can show + reset to it, or null.
  selectedCopyId: string | null;
  selectedCopyDefault: string;
  selectCopy: (id: string, defaultText: string) => void;
  clearSelectedCopy: () => void;
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
  selectedCopyId: null,
  selectedCopyDefault: "",
  selectCopy: noop,
  clearSelectedCopy: noop,
  dirty: false,
  saving: false,
  lastError: null,
  save: async () => {},
  resetAll: noop,
};

const DevModeContext = createContext<DevModeContextValue>(DEFAULT);

function cloneTokens(src: TokenOverrides): TokenOverrides {
  return { root: { ...src.root }, light: { ...src.light } };
}

export function DevModeProvider({ children }: { children: ReactNode }) {
  const { theme } = useTheme();
  const [enabled, setEnabled] = useState(false);
  const [tokens, setTokens] = useState<TokenOverrides>(() => cloneTokens(TOKEN_OVERRIDES));
  const [copy, setCopyState] = useState<Record<string, string>>(() => ({ ...COPY_OVERRIDES }));
  const [selectedCopy, setSelectedCopy] = useState<{ id: string; def: string } | null>(null);
  const [saving, setSaving] = useState(false);
  const [lastError, setLastError] = useState<string | null>(null);
  // The last-saved baseline, so `dirty` reflects unsaved edits (the imported modules are frozen).
  const [savedTokens, setSavedTokens] = useState(() => JSON.stringify(TOKEN_OVERRIDES));
  const [savedCopy, setSavedCopy] = useState(() => JSON.stringify(COPY_OVERRIDES));

  // Ctrl/Cmd+Shift+D toggles the whole surface. It is the only way in, so dev mode is hidden.
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if ((e.ctrlKey || e.metaKey) && e.shiftKey && (e.key === "D" || e.key === "d")) {
        e.preventDefault();
        setEnabled((v) => !v);
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

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
      setTokens((prev) => ({ ...prev, [selector]: { ...prev[selector], [cssVar]: value } }));
    },
    [activeSelector],
  );

  const resetToken = useCallback(
    (cssVar: string) => {
      const token = DEV_TOKEN_BY_VAR.get(cssVar);
      if (!token) return;
      const selector: TokenSelector = token.themed ? activeSelector : "root";
      setTokens((prev) => {
        const next = { ...prev[selector] };
        delete next[cssVar];
        return { ...prev, [selector]: next };
      });
    },
    [activeSelector],
  );

  const resolveCopy = useCallback(
    (id: string, fallback: string): string => copy[id] ?? fallback,
    [copy],
  );
  const isCopyOverridden = useCallback((id: string): boolean => id in copy, [copy]);
  const setCopy = useCallback((id: string, text: string) => {
    setCopyState((prev) => ({ ...prev, [id]: text }));
  }, []);
  const resetCopy = useCallback((id: string) => {
    setCopyState((prev) => {
      const next = { ...prev };
      delete next[id];
      return next;
    });
  }, []);

  const resetAll = useCallback(() => {
    setTokens({ root: {}, light: {} });
    setCopyState({});
    setSelectedCopy(null);
  }, []);

  const selectCopy = useCallback((id: string, defaultText: string) => {
    setSelectedCopy({ id, def: defaultText });
  }, []);
  const clearSelectedCopy = useCallback(() => setSelectedCopy(null), []);

  const dirty =
    JSON.stringify(tokens) !== savedTokens || JSON.stringify(copy) !== savedCopy;

  const save = useCallback(async () => {
    setSaving(true);
    setLastError(null);
    try {
      await api.devSave({ tokens, copy });
      setSavedTokens(JSON.stringify(tokens));
      setSavedCopy(JSON.stringify(copy));
    } catch (err) {
      setLastError(err instanceof ApiError ? err.message : "Could not save to source");
    } finally {
      setSaving(false);
    }
  }, [tokens, copy]);

  const value = useMemo<DevModeContextValue>(
    () => ({
      enabled,
      toggle: () => setEnabled((v) => !v),
      theme,
      tokenValue,
      isTokenOverridden,
      setToken,
      resetToken,
      resolveCopy,
      isCopyOverridden,
      setCopy,
      resetCopy,
      selectedCopyId: selectedCopy?.id ?? null,
      selectedCopyDefault: selectedCopy?.def ?? "",
      selectCopy,
      clearSelectedCopy,
      dirty,
      saving,
      lastError,
      save,
      resetAll,
    }),
    [
      enabled,
      theme,
      tokenValue,
      isTokenOverridden,
      setToken,
      resetToken,
      resolveCopy,
      isCopyOverridden,
      setCopy,
      resetCopy,
      selectedCopy,
      selectCopy,
      clearSelectedCopy,
      dirty,
      saving,
      lastError,
      save,
      resetAll,
    ],
  );

  return <DevModeContext.Provider value={value}>{children}</DevModeContext.Provider>;
}

export function useDevMode(): DevModeContextValue {
  return useContext(DevModeContext);
}
