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

// jsdom has no URL.createObjectURL/revokeObjectURL; the preview viewer (M6d) turns a
// fetched SVG/GLB blob into an object URL for an <img> src. Provide a deterministic
// stub so the viewer components can be tested without a real object-URL store.
if (!URL.createObjectURL) {
  let n = 0;
  URL.createObjectURL = (() => `blob:mock/${++n}`) as typeof URL.createObjectURL;
  URL.revokeObjectURL = (() => {}) as typeof URL.revokeObjectURL;
}

// jsdom's Blob may lack arrayBuffer(); modelGlb() reads a fetched GLB blob as an
// ArrayBuffer for the three.js loader. Browsers have this natively.
if (typeof Blob !== "undefined" && !Blob.prototype.arrayBuffer) {
  Blob.prototype.arrayBuffer = function arrayBuffer(): Promise<ArrayBuffer> {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(reader.result as ArrayBuffer);
      reader.onerror = () => reject(reader.error);
      reader.readAsArrayBuffer(this);
    });
  };
}

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
