/**
 * Runtime wiring for the API base URL and per-launch bearer token.
 *
 * The production native WebView2 host keeps the API token outside JavaScript
 * and adds it to approved same-origin requests. A legacy development host may
 * still inject the base and token globals. Otherwise the SPA uses its served
 * HTTP origin, with VITE_API_BASE and the standalone loopback URL retained for
 * browser development. The token is deliberately optional.
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
  if (
    typeof window !== "undefined" &&
    (window.location.protocol === "http:" || window.location.protocol === "https:")
  ) {
    return trimTrailingSlash(window.location.origin);
  }
  return DEV_DEFAULT_BASE;
}

export function apiToken(): string {
  const injected =
    typeof window !== "undefined" ? window.__STOCKROOM_TOKEN__ : undefined;
  if (injected && injected.trim()) return injected.trim();
  const fromEnv = import.meta.env.VITE_API_TOKEN as string | undefined;
  return fromEnv && fromEnv.trim() ? fromEnv.trim() : "";
}
