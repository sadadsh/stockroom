import { describe, expect, it } from "vitest";
import {
  DESIGN_OCCURRENCE_ATTRIBUTE,
  designIdOf,
  ensureDesignIdentities,
  exactDesignTargetAuthority,
  upgradeExactDesignTargetAuthority,
} from "./designIdentity";

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

  it("preserves valid generated caller identities when semantic metadata is present", () => {
    const root = document.createElement("section");
    root.dataset.devId = "fixture.root";
    root.innerHTML = `
      <span data-copy-id="brand.stockroom" data-design-id="auto.text.1234567">Stockroom</span>
      <span data-copy-id="component-browser.copy-mpn-object" data-design-id="auto.text.1234567">MPN</span>
    `;

    ensureDesignIdentities(root);
    const stockroom = designIdOf(root.children[0]!);
    const mpn = designIdOf(root.children[1]!);

    expect(stockroom).toBe("auto.text.1234567");
    expect(mpn).toBe("auto.text.1234567");
  });

  it("recreates a duplicate occurrence locator from stable semantic ancestors after restart", () => {
    const markup = `
      <main data-dev-id="shell.root">
        <section data-dev-id="rail.root"><button data-dev-id="rail.about">Rail About</button></section>
        <section data-dev-id="settings.root"><button data-dev-id="rail.about">Settings About</button></section>
      </main>
    `;
    const firstRoot = document.createElement("div");
    firstRoot.innerHTML = markup;
    document.body.append(firstRoot);
    ensureDesignIdentities(firstRoot);
    const firstButtons = firstRoot.querySelectorAll('[data-dev-id="rail.about"]');
    const firstAuthority = exactDesignTargetAuthority(firstButtons[1]!);
    const durableId = firstAuthority?.overrideId;

    firstRoot.remove();
    const restartedRoot = document.createElement("div");
    restartedRoot.innerHTML = markup;
    document.body.append(restartedRoot);
    ensureDesignIdentities(restartedRoot);
    const restartedButtons = restartedRoot.querySelectorAll('[data-dev-id="rail.about"]');

    expect(durableId).toMatch(/^auto\.occurrence\./);
    expect(restartedButtons[1]).toHaveAttribute(DESIGN_OCCURRENCE_ATTRIBUTE, durableId);
    expect(restartedButtons[0].getAttribute(DESIGN_OCCURRENCE_ATTRIBUTE)).not.toBe(durableId);
    restartedRoot.remove();
  });

  it("keeps stable occurrence locators attached to their semantic branch after reordering", () => {
    const root = document.createElement("div");
    root.innerHTML = `
      <main data-dev-id="shell.root">
        <section data-dev-id="rail.root"><button data-dev-id="rail.about">Rail About</button></section>
        <section data-dev-id="settings.root"><button data-dev-id="rail.about">Settings About</button></section>
      </main>
    `;
    document.body.append(root);
    ensureDesignIdentities(root);
    const settings = root.querySelector('[data-dev-id="settings.root"]')!;
    const settingsButton = settings.querySelector('[data-dev-id="rail.about"]')!;
    const before = settingsButton.getAttribute(DESIGN_OCCURRENCE_ATTRIBUTE);
    settings.parentElement?.prepend(settings);
    ensureDesignIdentities(root);

    expect(settingsButton).toHaveAttribute(DESIGN_OCCURRENCE_ATTRIBUTE, before);
    root.remove();
  });

  it("keeps occurrence locators on semantic branches after reordered remounts", () => {
    const firstRoot = document.createElement("div");
    firstRoot.innerHTML = `
      <main data-dev-id="shell.root">
        <div><section data-dev-id="rail.root"><button data-dev-id="rail.about">Rail About</button></section></div>
        <div><section data-dev-id="settings.root"><button data-dev-id="rail.about">Settings About</button></section></div>
      </main>
    `;
    document.body.append(firstRoot);
    ensureDesignIdentities(firstRoot);
    const firstRail = firstRoot.querySelector('[data-dev-id="rail.root"] [data-dev-id="rail.about"]')!;
    const firstSettings = firstRoot.querySelector('[data-dev-id="settings.root"] [data-dev-id="rail.about"]')!;
    const railOccurrence = firstRail.getAttribute(DESIGN_OCCURRENCE_ATTRIBUTE);
    const settingsOccurrence = firstSettings.getAttribute(DESIGN_OCCURRENCE_ATTRIBUTE);

    firstRoot.remove();
    const restartedRoot = document.createElement("div");
    restartedRoot.innerHTML = `
      <main data-dev-id="shell.root">
        <div><section data-dev-id="settings.root"><button data-dev-id="rail.about">Settings About</button></section></div>
        <div><section data-dev-id="rail.root"><button data-dev-id="rail.about">Rail About</button></section></div>
      </main>
    `;
    document.body.append(restartedRoot);
    ensureDesignIdentities(restartedRoot);

    expect(restartedRoot.querySelector('[data-dev-id="rail.root"] [data-dev-id="rail.about"]'))
      .toHaveAttribute(DESIGN_OCCURRENCE_ATTRIBUTE, railOccurrence);
    expect(restartedRoot.querySelector('[data-dev-id="settings.root"] [data-dev-id="rail.about"]'))
      .toHaveAttribute(DESIGN_OCCURRENCE_ATTRIBUTE, settingsOccurrence);
    restartedRoot.remove();
  });

  it("fails closed for indistinguishable duplicate siblings instead of binding by order", () => {
    const root = document.createElement("div");
    root.innerHTML = `
      <main data-dev-id="shell.root">
        <section data-dev-id="rail.root">
          <button data-dev-id="rail.about">Same</button>
          <button data-dev-id="rail.about">Same</button>
        </section>
      </main>
    `;
    document.body.append(root);
    ensureDesignIdentities(root);
    const buttons = root.querySelectorAll('[data-dev-id="rail.about"]');

    expect(buttons[0]).not.toHaveAttribute(DESIGN_OCCURRENCE_ATTRIBUTE);
    expect(buttons[1]).not.toHaveAttribute(DESIGN_OCCURRENCE_ATTRIBUTE);
    expect(exactDesignTargetAuthority(buttons[0])).toBeNull();
    expect(exactDesignTargetAuthority(buttons[1])).toBeNull();
    root.remove();
  });

  it("uses stable product data keys to address repeated interface rows", () => {
    const root = document.createElement("div");
    root.innerHTML = `
      <main data-dev-id="shell.root">
        <div data-spec-key="supplier-digikey"><span data-design-id="auto.source-label.1234567">DigiKey</span></div>
        <div data-spec-key="supplier-mouser"><span data-design-id="auto.source-label.1234567">Mouser</span></div>
      </main>
    `;
    document.body.append(root);
    ensureDesignIdentities(root);
    const labels = root.querySelectorAll('[data-design-id="auto.source-label.1234567"]');
    const authorities = Array.from(labels, exactDesignTargetAuthority);

    expect(authorities.every(Boolean)).toBe(true);
    expect(new Set(authorities.map((authority) => authority?.overrideId)).size).toBe(2);
    root.remove();
  });

  it("invalidates an exact occurrence when reparenting changes its durable locator", () => {
    const root = document.createElement("div");
    root.innerHTML = `
      <main data-dev-id="shell.root">
        <section data-dev-id="rail.root"><button data-dev-id="rail.about">Rail About</button></section>
        <section data-dev-id="settings.root"><button data-dev-id="rail.about">Settings About</button></section>
        <section data-dev-id="projects.root"></section>
      </main>
    `;
    document.body.append(root);
    ensureDesignIdentities(root);
    const selected = root.querySelector('[data-dev-id="settings.root"] [data-dev-id="rail.about"]')!;
    const authority = exactDesignTargetAuthority(selected)!;
    root.querySelector('[data-dev-id="projects.root"]')!.append(selected);

    expect(upgradeExactDesignTargetAuthority(authority)).toBeNull();
    root.remove();
  });
});
