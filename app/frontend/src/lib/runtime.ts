/**
 * Runtime wiring for the API base URL and per-launch bearer token.
 *
 * On Windows the WebView2 host injects window.__API_BASE__ and
 * window.__STOCKROOM_TOKEN__ before the SPA loads (the token is minted fresh per
 * launch and never persisted, per the security model). For local browser dev we
 * fall back to VITE_API_BASE, then to the loopback default the standalone server
 * uses. The token may be empty in dev if the server was started without one.
 */

declare global {
  interface Window {
    __API_BASE__?: string;
    __STOCKROOM_TOKEN__?: string;
  }
}

const DEV_DEFAULT_BASE = "http://127.0.0.1:8765";

function trimTrailingSlash(url: string): string {
  return url.replace(/\/+$/, "");
}

export function apiBase(): string {
  const injected =
    typeof window !== "undefined" ? window.__API_BASE__ : undefined;
  if (injected && injected.trim()) return trimTrailingSlash(injected.trim());
  const fromEnv = import.meta.env.VITE_API_BASE as string | undefined;
  if (fromEnv && fromEnv.trim()) return trimTrailingSlash(fromEnv.trim());
  return DEV_DEFAULT_BASE;
}

export function apiToken(): string {
  const injected =
    typeof window !== "undefined" ? window.__STOCKROOM_TOKEN__ : undefined;
  if (injected && injected.trim()) return injected.trim();
  const fromEnv = import.meta.env.VITE_API_TOKEN as string | undefined;
  return fromEnv && fromEnv.trim() ? fromEnv.trim() : "";
}
