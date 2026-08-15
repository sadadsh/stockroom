/**
 * Theme is a real toggle backed by a `data-theme` attribute on the document root
 * plus a token set (see styles/index.css, where every color token resolves to a
 * CSS variable that flips on `[data-theme="light"]`). The choice persists to
 * localStorage so the window opens in the last-used theme. Dark is the default
 * (the mockups are dark); the toggle is fully wired, not cosmetic.
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
import { Theme as AstryxTheme } from "@astryxdesign/core/theme";
import { neutralTheme } from "../themes/neutral/neutral";
import { readPref, writePref } from "./uiPrefs";

export type Theme = "dark" | "light";

const STORAGE_KEY = "sr-theme";

interface ThemeContextValue {
  theme: Theme;
  setTheme: (theme: Theme) => void;
  toggle: () => void;
}

const ThemeContext = createContext<ThemeContextValue | null>(null);

function readStored(): Theme {
  // Host-injected preference first, localStorage only as the dev-server fallback: the host binds an
  // ephemeral port, so localStorage is a fresh empty store on every launch and the saved theme was
  // silently lost every time. See lib/uiPrefs.ts.
  return readPref<Theme>(
    "theme",
    STORAGE_KEY,
    (raw) => (raw === "light" || raw === "dark" ? raw : undefined),
    "dark",
  );
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [theme, setThemeState] = useState<Theme>(readStored);

  // Mirror the theme onto the root so the CSS variable set switches, and persist
  // it. The first paint is already correct (the inline script in index.html sets
  // data-theme before React boots); this keeps it in sync on every toggle.
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    writePref("theme", theme, STORAGE_KEY);
  }, [theme]);

  const setTheme = useCallback((next: Theme) => setThemeState(next), []);
  const toggle = useCallback(
    () => setThemeState((t) => (t === "dark" ? "light" : "dark")),
    [],
  );

  // Held by identity rather than rebuilt inline. Both callbacks are already stable, so the only
  // thing that can change here is the theme itself - and a fresh object on every provider render
  // made every consumer of `useTheme` re-render whenever anything above this provider did, which
  // is most of the chrome. The dependency list is exactly what the value holds.
  const value = useMemo(
    () => ({ theme, setTheme, toggle }),
    [theme, setTheme, toggle],
  );

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

/** Mount ASTRYX at the real application boundary without changing every component test root. */
export function AstryxThemeBridge({ children }: { children: ReactNode }) {
  const { theme } = useTheme();
  return (
    // ASTRYX uses display: contents here, preserving Stockroom's existing shell geometry.
    <AstryxTheme theme={neutralTheme} mode={theme}>
      {children}
    </AstryxTheme>
  );
}

export function useTheme(): ThemeContextValue {
  const ctx = useContext(ThemeContext);
  if (!ctx) throw new Error("useTheme must be used within a ThemeProvider");
  return ctx;
}
