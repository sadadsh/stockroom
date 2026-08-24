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
  useRef,
  useState,
  type ReactNode,
} from "react";
import { Theme as AstryxTheme } from "@astryxdesign/core/theme";
import { neutralTheme } from "../themes/neutral/neutral";
import { readPref, writePref } from "./uiPrefs";

export type Theme = "dark" | "light";
export type ColorScheme = "neutral" | "blue" | "green" | "violet";

const STORAGE_KEY = "sr-theme";
const COLOR_SCHEME_STORAGE_KEY = "sr-color-scheme";

interface ThemeContextValue {
  theme: Theme;
  colorScheme: ColorScheme;
  setTheme: (theme: Theme) => void;
  setColorScheme: (scheme: ColorScheme) => void;
  toggle: () => void;
}

function readStoredColorScheme(): ColorScheme {
  return readPref<ColorScheme>(
    "color_scheme",
    COLOR_SCHEME_STORAGE_KEY,
    (raw) => (["neutral", "blue", "green", "violet"].includes(raw) ? raw as ColorScheme : undefined),
    "neutral",
  );
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
  const [colorScheme, setColorSchemeState] = useState<ColorScheme>(readStoredColorScheme);
  const colorSchemeMounted = useRef(false);

  // Mirror the theme onto the root so the CSS variable set switches, and persist
  // it. The first paint is already correct (the inline script in index.html sets
  // data-theme before React boots); this keeps it in sync on every toggle.
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    writePref("theme", theme, STORAGE_KEY);
  }, [theme]);

  useEffect(() => {
    document.documentElement.dataset.colorScheme = colorScheme;
    if (colorSchemeMounted.current) writePref("color_scheme", colorScheme, COLOR_SCHEME_STORAGE_KEY);
    else colorSchemeMounted.current = true;
  }, [colorScheme]);

  const setTheme = useCallback((next: Theme) => setThemeState(next), []);
  const setColorScheme = useCallback((next: ColorScheme) => setColorSchemeState(next), []);
  const toggle = useCallback(
    () => setThemeState((t) => (t === "dark" ? "light" : "dark")),
    [],
  );

  // Held by identity rather than rebuilt inline. Both callbacks are already stable, so the only
  // thing that can change here is the theme itself - and a fresh object on every provider render
  // made every consumer of `useTheme` re-render whenever anything above this provider did, which
  // is most of the chrome. The dependency list is exactly what the value holds.
  const value = useMemo(
    () => ({ theme, colorScheme, setTheme, setColorScheme, toggle }),
    [theme, colorScheme, setTheme, setColorScheme, toggle],
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
