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
  // The `.env` fallback is a BROWSER-DEV convenience and is gated to the dev build for one reason:
  // a `VITE_` value is not read at runtime, it is substituted into the JavaScript at build time. The
  // built SPA is committed to this repository (app/frontend-dist), so a `vite build` run on a machine
  // that happens to hold a `.env` would bake that machine's bearer token into a distributed artifact
  // and commit it. `import.meta.env.DEV` is a static `false` in a production build, so the read below
  // is eliminated outright rather than merely skipped, and no token can reach the bundle. The
  // production host never used this path anyway - it injects the per-launch token at window level,
  // outside JavaScript source, which is what `injected` above reads.
  const fromEnv = import.meta.env.DEV
    ? (import.meta.env.VITE_API_TOKEN as string | undefined)
    : undefined;
  return fromEnv && fromEnv.trim() ? fromEnv.trim() : "";
}
