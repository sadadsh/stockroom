import { afterEach, describe, expect, it } from "vitest";

import { apiBase, apiToken } from "./runtime";

const injectedBase = window.__API_BASE__;
const injectedToken = window.__STOCKROOM_TOKEN__;

afterEach(() => {
  window.__API_BASE__ = injectedBase;
  window.__STOCKROOM_TOKEN__ = injectedToken;
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

  it("allows native request interception to own authentication", () => {
    delete window.__STOCKROOM_TOKEN__;
    expect(apiToken()).toBe("");
  });
});
