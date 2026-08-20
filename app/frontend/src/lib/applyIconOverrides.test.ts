import { afterEach, describe, expect, it } from "vitest";
import {
  applyGeneratedIconOverrides,
  insertedIconOverrideId,
  startGeneratedIconOverrideObserver,
} from "./applyIconOverrides";

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

  it("settles after WebView normalizes an inserted SVG body", async () => {
    document.body.innerHTML = '<span data-design-id="auto.copy.0abc123">Specifications</span>';
    const id = insertedIconOverrideId("auto.copy.0abc123");
    const current = {
      [id]: {
        body: '<path d="M4 12h16" />',
        insertInto: "auto.copy.0abc123",
        placement: "before" as const,
      },
    };
    let childListMutations = 0;
    const counter = new MutationObserver((records) => {
      childListMutations += records.filter((record) => record.type === "childList").length;
    });
    counter.observe(document.body, { childList: true, subtree: true });
    const stop = startGeneratedIconOverrideObserver(() => current);

    try {
      applyGeneratedIconOverrides(current, {});
      await new Promise((resolve) => setTimeout(resolve, 0));
      const icon = document.querySelector<SVGElement>(`[data-design-inserted-icon="${id}"]`)!;
      const settledBody = icon.innerHTML;
      const settledMutations = childListMutations;

      applyGeneratedIconOverrides(current);
      await new Promise((resolve) => setTimeout(resolve, 0));

      expect(icon.innerHTML).toBe(settledBody);
      expect(childListMutations).toBe(settledMutations);
      expect(settledMutations).toBeLessThanOrEqual(3);
    } finally {
      stop();
      counter.disconnect();
    }
  });

  it("preserves raw outline geometry for a legacy solid treatment", () => {
    document.body.innerHTML = `
      <svg data-design-id="auto.svg.0abc123" viewBox="0 0 24 24" fill="none" stroke="currentColor">
        <path data-testid="open-path" d="M4 12h16" />
      </svg>
    `;

    applyGeneratedIconOverrides({ "auto.svg.0abc123": { treatment: "solid" } });

    const icon = document.querySelector("svg");
    expect(icon).toHaveAttribute("fill", "none");
    expect(icon).toHaveAttribute("stroke", "currentColor");
    expect(icon).toHaveAttribute("data-icon-treatment", "legacy-solid-fallback");
    expect(icon?.querySelector('[data-testid="open-path"]')).not.toBeNull();
  });
});
