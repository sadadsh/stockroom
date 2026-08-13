import { afterEach, describe, expect, it } from "vitest";
import { applyGeneratedIconOverrides, insertedIconOverrideId } from "./applyIconOverrides";

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

  it("materializes and removes a safe icon attached to any design target", () => {
    document.body.innerHTML = '<span data-design-id="auto.copy.0abc123">Main Specifications</span>';
    const id = insertedIconOverrideId("auto.copy.0abc123");
    const current = {
      [id]: {
        body: '<path data-testid="added" d="M4 12h16" />',
        insertInto: "auto.copy.0abc123",
        placement: "before" as const,
      },
    };

    applyGeneratedIconOverrides(current, {});
    const added = document.querySelector<SVGElement>(`[data-design-inserted-icon="${id}"]`);
    expect(added).not.toBeNull();
    expect(added?.querySelector('[data-testid="added"]')).not.toBeNull();
    expect(added?.nextSibling?.textContent).toBe("Main Specifications");

    applyGeneratedIconOverrides({}, current);
    expect(document.querySelector(`[data-design-inserted-icon="${id}"]`)).toBeNull();
  });

  it("places an added icon beside a text input without throwing or replacing the input", () => {
    document.body.innerHTML = '<label><input data-design-id="auto.input.0abc123" value="MPN" /></label>';
    const id = insertedIconOverrideId("auto.input.0abc123");
    const current = {
      [id]: {
        body: '<path d="M4 12h16" />',
        insertInto: "auto.input.0abc123",
        placement: "before" as const,
      },
    };

    expect(() => applyGeneratedIconOverrides(current, {})).not.toThrow();
    const input = document.querySelector("input");
    expect(input?.previousElementSibling).toHaveAttribute("data-design-inserted-icon", id);
    expect(input).toHaveValue("MPN");
  });
});
