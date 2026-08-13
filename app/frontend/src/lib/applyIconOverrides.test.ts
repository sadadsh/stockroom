import { afterEach, describe, expect, it } from "vitest";
import { applyGeneratedIconOverrides } from "./applyIconOverrides";

afterEach(() => document.body.replaceChildren());

describe("applyGeneratedIconOverrides", () => {
  it("applies and restores a sanitized library body on an automatically exposed SVG", () => {
    document.body.innerHTML = `
      <svg data-design-id="auto.svg.0abc123" viewBox="0 0 24 24">
        <path data-testid="original" d="M1 1h2" />
      </svg>
    `;
    const previous = {};
    const current = { "auto.svg.0abc123": { body: '<circle data-testid="replacement" cx="12" cy="12" r="6" />' } };

    applyGeneratedIconOverrides(current, previous);
    expect(document.querySelector('[data-testid="replacement"]')).not.toBeNull();

    applyGeneratedIconOverrides({}, current);
    expect(document.querySelector('[data-testid="original"]')).not.toBeNull();
  });
});
