import { afterEach, describe, expect, it, vi } from "vitest";

import { apiBase, apiToken } from "./runtime";

const injectedBase = window.__API_BASE__;
const injectedToken = window.__STOCKROOM_TOKEN__;

afterEach(() => {
  window.__API_BASE__ = injectedBase;
  window.__STOCKROOM_TOKEN__ = injectedToken;
  vi.unstubAllEnvs();
});

describe("native host runtime boundary", () => {
  it("uses an explicit development base when the host supplies one", () => {
    window.__API_BASE__ = "http://127.0.0.1:9012/";
    expect(apiBase()).toBe("http://127.0.0.1:9012");
  });

  it("uses the served origin when the native host keeps credentials out of JavaScript", () => {
    delete window.__API_BASE__;
    expect(apiBase()).toBe(window.location.origin);
  });

  it("reads the development .env base only while developing in a browser", () => {
    delete window.__API_BASE__;
    vi.stubEnv("DEV", true);
    vi.stubEnv("VITE_API_BASE", "http://127.0.0.1:9013/");
    expect(apiBase()).toBe("http://127.0.0.1:9013");
  });

  it("keeps a build-time API base out of the shipped bundle", () => {
    delete window.__API_BASE__;
    vi.stubEnv("DEV", false);
    vi.stubEnv("VITE_API_BASE", "https://machine-specific.invalid");
    expect(apiBase()).toBe(window.location.origin);
  });

  it("allows native request interception to own authentication", () => {
    delete window.__STOCKROOM_TOKEN__;
    expect(apiToken()).toBe("");
  });

  it("reads the development .env token only while developing in a browser", () => {
    delete window.__STOCKROOM_TOKEN__;
    vi.stubEnv("DEV", true);
    vi.stubEnv("VITE_API_TOKEN", "dev-only-bearer");
    expect(apiToken()).toBe("dev-only-bearer");
  });

  it("keeps a build-time bearer token out of the shipped bundle", () => {
    // A `VITE_` value is SUBSTITUTED at build time, and the built SPA is committed. Were the read
    // ungated, a `vite build` on a machine holding a `.env` would bake that machine's token into a
    // distributed artifact. In a production build `import.meta.env.DEV` is a static false, so the
    // read is eliminated; this is that elimination observed from the one side a test can stand on.
    delete window.__STOCKROOM_TOKEN__;
    vi.stubEnv("DEV", false);
    vi.stubEnv("VITE_API_TOKEN", "leaked-bearer");
    expect(apiToken()).toBe("");
  });
});
