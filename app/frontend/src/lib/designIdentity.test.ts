import { describe, expect, it } from "vitest";
import { designIdOf, ensureDesignIdentities } from "./designIdentity";

describe("ensureDesignIdentities", () => {
  it("gives structurally identical runtime siblings distinct stable targets", () => {
    const root = document.createElement("section");
    root.dataset.devId = "fixture.root";
    root.innerHTML = "<span>First</span><span>Second</span><span>Third</span>";

    ensureDesignIdentities(root);
    const firstPass = Array.from(root.children, (element) => designIdOf(element));
    ensureDesignIdentities(root);

    expect(new Set(firstPass).size).toBe(3);
    expect(Array.from(root.children, (element) => designIdOf(element))).toEqual(firstPass);
  });

  it("uses the exact copy identity instead of one shared Text component identity", () => {
    const root = document.createElement("section");
    root.dataset.devId = "fixture.root";
    root.innerHTML = `
      <span data-copy-id="brand.stockroom" data-design-id="auto.text.1234567">Stockroom</span>
      <span data-copy-id="component-browser.copy-mpn-object" data-design-id="auto.text.1234567">MPN</span>
    `;

    ensureDesignIdentities(root);
    const stockroom = designIdOf(root.children[0]!);
    const mpn = designIdOf(root.children[1]!);

    expect(stockroom).toMatch(/^auto\.copy\./);
    expect(mpn).toMatch(/^auto\.copy\./);
    expect(mpn).not.toBe(stockroom);
  });
});
