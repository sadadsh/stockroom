import { describe, expect, it } from "vitest";
import { DEV_IDS } from "../lib/devIds";
import { componentDevId } from "../lib/componentDevIds";
import { coverageIssuesFor, targetLayersFor } from "./targetCoverage";

function fixture(markup: string): HTMLElement {
  const root = document.createElement("div");
  root.innerHTML = markup;
  return root;
}

describe("target coverage", () => {
  it("fails when a meaningful interactive or visual boundary has no stable target", () => {
    const root = fixture("<section><button>Save</button></section>");
    expect(coverageIssuesFor(root, DEV_IDS)).toEqual(
      expect.arrayContaining([expect.objectContaining({ code: "missing-target" })]),
    );
    expect(coverageIssuesFor(root, DEV_IDS).some((issue) => issue.element.tagName === "BUTTON")).toBe(true);
  });

  it("lets one stable component target own its internal text and icon domains", () => {
    const root = fixture(`
      <button data-dev-id="rail.about"><span>About</span><svg viewBox="0 0 24 24"></svg></button>
    `);
    expect(coverageIssuesFor(root, DEV_IDS)).toEqual([]);
  });

  it("does not let a shell root hide an unaddressed nested control", () => {
    const root = fixture('<main data-dev-id="shell.root"><button>Save</button></main>');
    expect(coverageIssuesFor(root, DEV_IDS)).toEqual([
      expect.objectContaining({ code: "missing-target", element: root.querySelector("button") }),
    ]);
  });

  it("does not let any broad page identity hide an unaddressed nested control", () => {
    const root = fixture('<main data-dev-id="components.root"><div><button>Save</button></div></main>');
    expect(coverageIssuesFor(root, DEV_IDS)).toEqual([
      expect.objectContaining({ code: "missing-target", element: root.querySelector("button") }),
    ]);
  });

  it("does not let a broad page identity absorb nested text or icon boundaries", () => {
    const root = fixture('<main data-dev-id="components.root"><h2>Summary</h2><svg viewBox="0 0 24 24"></svg></main>');
    const missing = coverageIssuesFor(root, DEV_IDS).filter((issue) => issue.code === "missing-target");
    expect(missing.map((issue) => issue.element.tagName)).toEqual(expect.arrayContaining(["H2", "svg"]));
  });

  it("derives text, icon, layout, and interactive boundaries without opt-in markers", () => {
    const root = fixture(`
      <button data-dev-id="rail.about">About</button>
      <h2 data-copy-id="design-studio.title">Design Studio</h2>
      <svg data-icon-id="action.add"></svg>
      <section data-layout-piece="workspace.header-identity"></section>
    `);

    expect(coverageIssuesFor(root, DEV_IDS)).toEqual([]);
    expect(root.querySelector("[data-design-meaningful]")).toBeNull();
  });

  it("reports unaddressed text, icon, and semantic layout boundaries without annotations", () => {
    const root = fixture(`
      <main>
        <section aria-label="Summary">
          <h2>Component Summary</h2>
          <svg viewBox="0 0 24 24"></svg>
        </section>
      </main>
    `);

    const missingTags = coverageIssuesFor(root, DEV_IDS)
      .filter((issue) => issue.code === "missing-target")
      .map((issue) => issue.element.tagName.toLowerCase());
    expect(missingTags).toEqual(expect.arrayContaining(["main", "section", "h2", "svg"]));
  });

  it("accepts registered dev, copy, icon, layout-piece, and approved dynamic identities", () => {
    const dynamic = componentDevId("STM32 H7[owner]");
    const root = fixture(`
      <button data-design-meaningful data-dev-id="rail.about">About</button>
      <h2 data-design-meaningful data-copy-id="design-studio.title">Design Studio</h2>
      <svg data-design-meaningful data-icon-id="action.add"></svg>
      <section data-design-meaningful data-layout-piece="workspace.header-identity"></section>
      <article data-design-meaningful data-dev-id="${dynamic}"></article>
    `);
    expect(coverageIssuesFor(root, DEV_IDS)).toEqual([]);
  });

  it("reports unregistered identities without manufacturing a DOM-index target", () => {
    const root = fixture(
      '<section data-design-meaningful data-dev-id="component-browser.component-0"></section>',
    );
    expect(coverageIssuesFor(root, DEV_IDS)).toEqual([
      expect.objectContaining({
        code: "unregistered-target",
        targetId: "component-browser.component-0",
      }),
    ]);
    expect(JSON.stringify(coverageIssuesFor(root, DEV_IDS))).not.toContain("index");
  });

  it("builds a stable target hierarchy from identities rather than DOM indices", () => {
    const root = fixture(`
      <main data-dev-id="shell.root">
        <section data-dev-id="shell.content">
          <button data-dev-id="rail.about"><span data-copy-id="about.title">About</span></button>
          <button data-dev-id="rail.about">About Again</button>
        </section>
      </main>
    `);
    expect(targetLayersFor(root, DEV_IDS)).toEqual([
      expect.objectContaining({ key: "dev:shell.root", depth: 0, occurrences: 1 }),
      expect.objectContaining({ key: "dev:shell.content", parentKey: "dev:shell.root", depth: 1 }),
      expect.objectContaining({ key: "dev:rail.about", parentKey: "dev:shell.content", occurrences: 2 }),
      expect.objectContaining({ key: "copy:about.title", parentKey: "dev:rail.about", depth: 3 }),
    ]);
    expect(targetLayersFor(root, DEV_IDS).map((target) => target.key).join(" ")).not.toMatch(/index|:0|:1/);
  });
});
