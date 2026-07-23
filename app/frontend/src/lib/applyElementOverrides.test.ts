import { afterEach, describe, expect, it } from "vitest";
import { applyElementOverrides, startElementOverrideObserver } from "./applyElementOverrides";

// Each test seeds real nodes under document.body; clear them so state never leaks between tests.
afterEach(() => {
  document.body.innerHTML = "";
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

describe("applyElementOverrides", () => {
  it("sets the mapped CSS property as an inline style on a matching node", () => {
    const el = nodeWithId("x.y");
    applyElementOverrides({ "x.y": { width: "240px" } });
    expect(el.style.getPropertyValue("width")).toBe("240px");
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
    expect(el.style.getPropertyValue("width")).toBe("300px");

    disconnect();
  });
});
