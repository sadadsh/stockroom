// Vitest setup: jest-dom matchers plus deterministic runtime globals so the api
// client resolves a stable base + token in tests (runtime.ts reads these).
import "@testing-library/jest-dom/vitest";

declare global {
  interface Window {
    __API_BASE__?: string;
    __STOCKROOM_TOKEN__?: string;
  }
}

window.__API_BASE__ = "http://127.0.0.1:8765";
window.__STOCKROOM_TOKEN__ = "test-token";

// jsdom has no matchMedia; the theme layer (M6a-3) probes it.
if (!window.matchMedia) {
  window.matchMedia = ((query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addEventListener: () => {},
    removeEventListener: () => {},
    addListener: () => {},
    removeListener: () => {},
    dispatchEvent: () => false,
  })) as unknown as typeof window.matchMedia;
}
