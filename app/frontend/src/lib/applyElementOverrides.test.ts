import { afterEach, describe, expect, it, vi } from "vitest";
import { applyElementOverrides, startElementOverrideObserver } from "./applyElementOverrides";
import { ELEMENT_OVERRIDES } from "./element.overrides";
import {
  DESIGN_TARGET_SELECTOR,
  exactDesignTargetAuthority,
  releaseExactDesignTargetAuthority,
} from "./designIdentity";

// Each test seeds real nodes under document.body; clear them so state never leaks between tests.
afterEach(() => {
  document.body.innerHTML = "";
  vi.unstubAllGlobals();
});

function nodeWithId(id: string): HTMLElement {
  const el = document.createElement("div");
  el.setAttribute("data-dev-id", id);
  document.body.appendChild(el);
  return el;
}

// Resolve after the MutationObserver has had a chance to flush (it delivers on a microtask).
function nextTick(): Promise<void> {
  return new Promise((resolve) => queueMicrotask(resolve));
}

function nextFrame(): Promise<void> {
  return new Promise((resolve) => requestAnimationFrame(() => resolve()));
}

describe("applyElementOverrides", () => {
  it("sets the mapped CSS property as an inline style on a matching node", () => {
    const el = nodeWithId("x.y");
    applyElementOverrides({ "x.y": { width: "240px" } });
    expect(el.style.getPropertyValue("width")).toBe("240px");
  });

  it("removes every repeated specification source with one saved semantic override", () => {
    document.body.innerHTML = `
      <span data-dev-id="component-browser.spec-source">DigiKey</span>
      <span data-dev-id="component-browser.spec-source">Mouser</span>
    `;
    applyElementOverrides(ELEMENT_OVERRIDES);
    const sources = document.querySelectorAll<HTMLElement>(
      '[data-dev-id="component-browser.spec-source"]',
    );
    expect(sources).toHaveLength(2);
    expect(Array.from(sources).map((source) => source.style.display)).toEqual(["none", "none"]);
  });

  it("reapplies a persisted occurrence override to the same semantic branch after restart", () => {
    const markup = `
      <main data-dev-id="shell.root">
        <section data-dev-id="rail.root"><button data-dev-id="rail.about">Rail About</button></section>
        <section data-dev-id="settings.root"><button data-dev-id="rail.about">Settings About</button></section>
      </main>
    `;
    document.body.innerHTML = markup;
    const firstButtons = document.querySelectorAll<HTMLElement>('[data-dev-id="rail.about"]');
    const overrideId = exactDesignTargetAuthority(firstButtons[1])?.overrideId;
    expect(overrideId).toMatch(/^auto\.occurrence\./);

    document.body.innerHTML = markup;
    const restartedButtons = document.querySelectorAll<HTMLElement>('[data-dev-id="rail.about"]');
    applyElementOverrides({ [overrideId!]: { width: "222px" } });

    expect(restartedButtons[0].style.width).toBe("");
    expect(restartedButtons[1].style.width).toBe("222px");
  });

  it("rebinds a unique semantic override only to the same deterministic remount", () => {
    const firstRoot = document.createElement("section");
    firstRoot.innerHTML = '<button data-design-id="auto.fixture.0abc123">Original</button>';
    document.body.append(firstRoot);
    const first = firstRoot.firstElementChild!;
    expect(exactDesignTargetAuthority(first)?.overrideId).toBe("auto.fixture.0abc123");
    applyElementOverrides({ "auto.fixture.0abc123": { width: "211px" } });
    expect(first).toHaveStyle({ width: "211px" });

    firstRoot.remove();
    const restartedRoot = document.createElement("section");
    restartedRoot.innerHTML = '<button data-design-id="auto.fixture.0abc123">Restarted</button>';
    document.body.append(restartedRoot);
    const restarted = restartedRoot.firstElementChild!;
    applyElementOverrides({ "auto.fixture.0abc123": { width: "211px" } });

    expect(restarted).toHaveStyle({ width: "211px" });
    restartedRoot.remove();
  });

  it("does not let a retired binding from an earlier product root poison a later mount", () => {
    const firstRoot = document.createElement("main");
    firstRoot.dataset.designProductRoot = "true";
    firstRoot.innerHTML = '<button data-design-id="auto.fixture.0abc123">First Mount</button>';
    document.body.append(firstRoot);
    const authority = exactDesignTargetAuthority(firstRoot.firstElementChild!)!;
    releaseExactDesignTargetAuthority(authority);
    firstRoot.remove();

    const nextRoot = document.createElement("main");
    nextRoot.dataset.designProductRoot = "true";
    nextRoot.innerHTML = '<button data-design-id="auto.fixture.0abc123">Later Mount</button>';
    document.body.append(nextRoot);
    const later = nextRoot.firstElementChild!;
    applyElementOverrides({ "auto.fixture.0abc123": { width: "211px" } });

    expect(later).toHaveStyle({ width: "211px" });
  });

  it("does not migrate an unselected semantic override to a peer after ambiguity", () => {
    const root = document.createElement("main");
    root.dataset.designProductRoot = "true";
    root.innerHTML = '<button data-design-id="auto.fixture.0abc123" data-testid="original">Original</button>';
    document.body.append(root);
    const original = root.firstElementChild!;
    expect(exactDesignTargetAuthority(original)?.overrideId).toBe("auto.fixture.0abc123");
    const override = { "auto.fixture.0abc123": { width: "211px" } };
    applyElementOverrides(override);

    const peer = document.createElement("button");
    peer.dataset.designId = "auto.fixture.0abc123";
    peer.dataset.testid = "peer";
    root.append(peer);
    applyElementOverrides(override);
    expect(original).toHaveStyle({ width: "211px" });
    expect(peer).not.toHaveStyle({ width: "211px" });

    original.remove();
    applyElementOverrides(override);
    expect(peer).not.toHaveStyle({ width: "211px" });
  });

  it("clears exactly the dropped property when it is absent from current but was in previous", () => {
    const el = nodeWithId("x.y");
    const first = { "x.y": { width: "240px", height: "80px" } };
    applyElementOverrides(first);
    expect(el.style.getPropertyValue("width")).toBe("240px");
    expect(el.style.getPropertyValue("height")).toBe("80px");

    // Second apply drops `width` but keeps `height`; only `width` should be removed.
    applyElementOverrides({ "x.y": { height: "80px" } }, first);
    expect(el.style.getPropertyValue("width")).toBe("");
    expect(el.style.getPropertyValue("height")).toBe("80px");
  });

  it("clears every property of an id that disappears entirely from current", () => {
    const el = nodeWithId("x.y");
    const first = { "x.y": { width: "240px" } };
    applyElementOverrides(first);
    applyElementOverrides({}, first);
    expect(el.style.getPropertyValue("width")).toBe("");
  });

  it("applies to a node mounted AFTER the first apply once the observer fires", async () => {
    const overrides = { "late.node": { width: "300px" } };
    applyElementOverrides(overrides);
    const disconnect = startElementOverrideObserver(() => overrides);

    const el = nodeWithId("late.node");
    // Not applied synchronously on insert; the observer re-applies on its microtask flush.
    expect(el.style.getPropertyValue("width")).toBe("");
    await nextTick();
    await nextFrame();
    expect(el.style.getPropertyValue("width")).toBe("300px");

    disconnect();
  });

  it("coalesces repeated catalog growth into one override pass per frame", async () => {
    let scheduled: FrameRequestCallback | undefined;
    const request = vi.fn((callback: FrameRequestCallback) => {
      scheduled = callback;
      return 1;
    });
    vi.stubGlobal("requestAnimationFrame", request);
    vi.stubGlobal("cancelAnimationFrame", vi.fn());
    const overrides = { "late.node::matching": { width: "300px" } };
    const disconnect = startElementOverrideObserver(() => overrides);

    const first = nodeWithId("late.node");
    await nextTick();
    const second = nodeWithId("late.node");
    await nextTick();

    expect(request).toHaveBeenCalledTimes(1);
    scheduled?.(0);
    expect(first.style.width).toBe("300px");
    expect(second.style.width).toBe("300px");
    disconnect();
  });

  it("resolves occurrence identities once for a large applied design", () => {
    document.body.innerHTML = `
      <main data-design-product-root="true">
        <section data-testid="left"><button data-dev-id="shared.action">Left</button></section>
        <section data-testid="right"><button data-dev-id="shared.action">Right</button></section>
      </main>
    `;
    const buttons = document.querySelectorAll<HTMLElement>('[data-dev-id="shared.action"]');
    const left = exactDesignTargetAuthority(buttons[0])?.overrideId;
    const right = exactDesignTargetAuthority(buttons[1])?.overrideId;
    expect(left).toMatch(/^auto\.occurrence\./);
    expect(right).toMatch(/^auto\.occurrence\./);

    const query = vi.spyOn(document, "querySelectorAll");
    const largeAppliedDesign = Object.fromEntries(
      Array.from({ length: 80 }, (_, index) => [
        `auto.occurrence.${index.toString(36).padStart(7, "0")}`,
        { display: "none" },
      ]),
    );
    applyElementOverrides({
      ...largeAppliedDesign,
      [left!]: { display: "none" },
      [right!]: { display: "none" },
    });

    expect(query.mock.calls.filter(([selector]) => selector === DESIGN_TARGET_SELECTOR)).toHaveLength(1);
    query.mockRestore();
  });

  it("writes safe global state rules and removes them with the draft", () => {
    nodeWithId("x.y");
    const state = { "x.y::state:hover": { color: "#123456" } };
    applyElementOverrides(state);
    const sheet = document.querySelector<HTMLStyleElement>("#stockroom-design-state-overrides");
    expect(sheet?.textContent).toContain("data-dev-id");
    expect(sheet?.textContent).not.toContain("data-dev-role");
    expect(sheet?.textContent).toContain(":hover");
    expect(sheet?.textContent).toContain('[data-design-preview-state="hover"]');
    expect(sheet?.textContent).toContain("color:#123456");

    applyElementOverrides({}, state);
    expect(document.querySelector("#stockroom-design-state-overrides")).toBeNull();
  });

  it("contains one failing DOM write instead of blanking the remaining preview", () => {
    const broken = nodeWithId("broken.node");
    const healthy = nodeWithId("healthy.node");
    vi.spyOn(console, "error").mockImplementation(() => undefined);
    vi.spyOn(broken.style, "setProperty").mockImplementation(() => {
      throw new Error("simulated DOM write failure");
    });

    expect(() => applyElementOverrides({
      "broken.node": { width: "100px" },
      "healthy.node": { width: "200px" },
    })).not.toThrow();
    expect(healthy.style.width).toBe("200px");
  });

  it("never applies visibility or destructive geometry to the product preview root", () => {
    const root = nodeWithId("preview.root");
    root.setAttribute("data-design-product-root", "true");

    applyElementOverrides({
      "preview.root": {
        display: "none",
        visibility: "hidden",
        position: "absolute",
        width: "1px",
        height: "1px",
        transform: "rotate(90deg)",
        opacity: "0",
        overflow: "hidden",
        padding: "0",
        gap: "0",
        "z-index": "-999",
        filter: "brightness(0)",
        "background-color": "#123456",
      },
    });

    expect(root.style.display).toBe("");
    expect(root.style.visibility).toBe("");
    expect(root.style.position).toBe("");
    expect(root.style.width).toBe("");
    expect(root.style.height).toBe("");
    expect(root.style.transform).toBe("");
    expect(root.style.opacity).toBe("");
    expect(root.style.overflow).toBe("");
    expect(root.style.padding).toBe("");
    expect(root.style.gap).toBe("");
    expect(root.style.zIndex).toBe("");
    expect(root.style.filter).toBe("");
    expect(root.style.backgroundColor).toBe("rgb(18, 52, 86)");

    applyElementOverrides({
      "preview.root::state:hover": { transform: "rotate(90deg)", opacity: "0" },
    });
    expect(document.querySelector("#stockroom-design-state-overrides")?.textContent ?? "")
      .not.toContain("transform");
    expect(document.querySelector("#stockroom-design-state-overrides")?.textContent ?? "")
      .not.toContain("opacity");
  });
});
