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
  it("automatically identities a meaningful interactive or visual boundary", () => {
    const root = fixture("<section><button>Save</button></section>");
    expect(coverageIssuesFor(root, DEV_IDS)).toEqual([]);
    expect(root.querySelector("button")?.getAttribute("data-design-id")).toMatch(/^auto\./);
  });

  it("requires generated identities on a control's internal text and icon nodes", () => {
    const root = fixture(`
      <button data-dev-id="rail.about"><span data-design-id="auto.fixture.0abc123">About</span><svg data-design-id="auto.fixture.0def456" viewBox="0 0 24 24"></svg></button>
    `);
    expect(coverageIssuesFor(root, DEV_IDS)).toEqual([]);
  });

  it("gives a nested control its own identity beneath the shell", () => {
    const root = fixture('<main data-dev-id="shell.root"><button>Save</button></main>');
    expect(coverageIssuesFor(root, DEV_IDS)).toEqual([]);
    expect(root.querySelector("button")).toHaveAttribute("data-design-id");
  });

  it("gives a nested control its own identity beneath a page", () => {
    const root = fixture('<main data-dev-id="components.root"><div><button>Save</button></div></main>');
    expect(coverageIssuesFor(root, DEV_IDS)).toEqual([]);
    expect(root.querySelector("button")).toHaveAttribute("data-design-id");
  });

  it("identities nested text and icon boundaries independently", () => {
    const root = fixture('<main data-dev-id="components.root"><h2>Summary</h2><svg viewBox="0 0 24 24"></svg></main>');
    expect(coverageIssuesFor(root, DEV_IDS)).toEqual([]);
    expect(root.querySelector("h2")).toHaveAttribute("data-design-id");
    expect(root.querySelector("svg")).toHaveAttribute("data-design-id");
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

  it("automatically covers text, icon, and semantic layout boundaries without annotations", () => {
    const root = fixture(`
      <main>
        <section aria-label="Summary">
          <h2>Component Summary</h2>
          <svg viewBox="0 0 24 24"></svg>
        </section>
      </main>
    `);

    expect(coverageIssuesFor(root, DEV_IDS)).toEqual([]);
    for (const tag of ["main", "section", "h2", "svg"]) {
      expect(root.querySelector(tag)).toHaveAttribute("data-design-id");
    }
  });

  it("supplies an identity to every Stockroom-owned rendered element", () => {
    const root = fixture(`
      <main data-dev-id="shell.root">
        <div></div>
        <span data-design-id="auto.fixture.0abc123">Ready</span>
      </main>
    `);

    expect(coverageIssuesFor(root, DEV_IDS)).toEqual([]);
    expect(root.querySelector("div")).toHaveAttribute("data-design-id");
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
    const layers = targetLayersFor(root, DEV_IDS);
    expect(layers).toEqual(expect.arrayContaining([
      expect.objectContaining({ key: "dev:shell.root", depth: 0, occurrences: 1 }),
      expect.objectContaining({ key: "dev:shell.content", parentKey: "dev:shell.root", depth: 1 }),
      expect.objectContaining({
        key: "dev:rail.about@ambiguous",
        parentKey: "dev:shell.content",
        occurrences: 2,
        overrideId: null,
      }),
      expect.objectContaining({ key: "copy:about.title" }),
    ]));
    expect(layers.map((target) => target.key).join(" ")).not.toMatch(/index|:0|:1/);
  });

  it("emits one exact selectable layer row for each durable duplicate occurrence", () => {
    const root = fixture(`
      <main data-dev-id="shell.root">
        <section data-dev-id="rail.root"><button data-dev-id="rail.about">Rail About</button></section>
        <section data-dev-id="settings.root"><button data-dev-id="rail.about">Settings About</button></section>
      </main>
    `);

    const duplicateRows = targetLayersFor(root, DEV_IDS).filter((target) => target.id === "rail.about");

    expect(duplicateRows).toHaveLength(2);
    expect(new Set(duplicateRows.map((target) => target.key)).size).toBe(2);
    expect(duplicateRows.every((target) => target.overrideId?.startsWith("auto.occurrence."))).toBe(true);
    expect(duplicateRows.map((target) => target.element.textContent)).toEqual(["Rail About", "Settings About"]);
  });

  it("includes generated identities in the complete layer tree", () => {
    const root = fixture(`
      <main data-dev-id="shell.root">
        <div data-design-id="auto.fixture.0abc123"><span data-design-id="auto.fixture.0def456">Ready</span></div>
      </main>
    `);

    expect(targetLayersFor(root, DEV_IDS)).toEqual([
      expect.objectContaining({ key: "dev:shell.root", depth: 0 }),
      expect.objectContaining({ key: "generated:auto.fixture.0abc123", depth: 1, ownerDevId: "auto.fixture.0abc123", meaningful: false }),
      expect.objectContaining({ key: "generated:auto.fixture.0def456", depth: 2, ownerDevId: "auto.fixture.0def456", meaningful: true }),
    ]);
  });

  it("marks only independently useful generated targets as meaningful", () => {
    const root = fixture(`
      <main data-dev-id="shell.root">
        <button data-design-id="auto.primitives-kit.0abc123">First</button>
        <button data-design-id="auto.primitives-kit.0abc123">Second</button>
        <svg data-design-id="auto.icon.0def456" data-icon-id="action.add"></svg>
        <span data-design-id="auto.fixture.0ghi789">Unique Text</span>
      </main>
    `);

    const targets = targetLayersFor(root, DEV_IDS);
    expect(targets).toEqual(expect.arrayContaining([
      expect.objectContaining({ id: "auto.primitives-kit.0abc123", occurrences: 2, meaningful: false, overrideId: null }),
      expect.objectContaining({ id: "auto.icon.0def456", occurrences: 1, meaningful: false }),
      expect.objectContaining({ id: "auto.fixture.0ghi789", occurrences: 1, meaningful: true }),
    ]));
  });
});
