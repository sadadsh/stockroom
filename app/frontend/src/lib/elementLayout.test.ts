import { describe, expect, it } from "vitest";
import { containerLayoutOf, reorderSiblings, reorderSiblingsOf } from "./elementLayout";

// A tiny DOM builder: a container with the given class holding N buttons carrying data-dev-id=id.
function makeContainer(className: string, ids: string[]): HTMLElement {
  const container = document.createElement("div");
  container.setAttribute("class", className);
  for (const id of ids) {
    const child = document.createElement("button");
    child.setAttribute("data-dev-id", id);
    container.appendChild(child);
  }
  return container;
}

describe("containerLayoutOf", () => {
  it("reports flex for `flex` and `inline-flex`", () => {
    expect(containerLayoutOf(makeContainer("flex flex-col gap-2", []))).toBe("flex");
    expect(containerLayoutOf(makeContainer("inline-flex", []))).toBe("flex");
  });

  it("reports grid for `grid` and `inline-grid`", () => {
    expect(containerLayoutOf(makeContainer("grid grid-cols-3", []))).toBe("grid");
    expect(containerLayoutOf(makeContainer("inline-grid", []))).toBe("grid");
  });

  it("matches whole tokens only, so `flex-col` alone is not flex, and reports none otherwise", () => {
    expect(containerLayoutOf(makeContainer("flex-col gap-2", []))).toBe("none");
    expect(containerLayoutOf(makeContainer("block p-4", []))).toBe("none");
  });

  it("is null-safe", () => {
    expect(containerLayoutOf(null)).toBe("none");
    expect(containerLayoutOf(undefined)).toBe("none");
  });
});

describe("reorderSiblingsOf", () => {
  it("returns the parent's direct-child data-dev-id elements in DOM order (including the node)", () => {
    const container = makeContainer("flex", ["a", "b", "c"]);
    // A non-dev-id child and a nested dev-id must both be excluded (direct children only).
    const plain = document.createElement("span");
    container.appendChild(plain);
    const nested = document.createElement("div");
    nested.setAttribute("data-dev-id", "deep");
    container.children[0].appendChild(nested);

    const first = container.children[0];
    const ids = reorderSiblingsOf(first).map((el) => el.getAttribute("data-dev-id"));
    expect(ids).toEqual(["a", "b", "c"]);
  });

  it("returns [] when the element has no parent", () => {
    const orphan = document.createElement("div");
    orphan.setAttribute("data-dev-id", "x");
    expect(reorderSiblingsOf(orphan)).toEqual([]);
  });
});

describe("reorderSiblings", () => {
  it("moving down swaps the selected id one step later and normalizes 0-based", () => {
    // [a,b,c,d], move b down -> [a,c,b,d]
    expect(reorderSiblings(["a", "b", "c", "d"], "b", "down")).toEqual({
      a: "0",
      c: "1",
      b: "2",
      d: "3",
    });
  });

  it("moving up swaps the selected id one step earlier and normalizes 0-based", () => {
    // [a,b,c,d], move c up -> [a,c,b,d]
    expect(reorderSiblings(["a", "b", "c", "d"], "c", "up")).toEqual({
      a: "0",
      c: "1",
      b: "2",
      d: "3",
    });
  });

  it("is idempotent at the ends (first up / last down change nothing, no throw)", () => {
    expect(reorderSiblings(["a", "b", "c"], "a", "up")).toEqual({ a: "0", b: "1", c: "2" });
    expect(reorderSiblings(["a", "b", "c"], "c", "down")).toEqual({ a: "0", b: "1", c: "2" });
  });

  it("returns every sibling explicitly even for a two-element container", () => {
    expect(reorderSiblings(["one", "two"], "one", "down")).toEqual({ two: "0", one: "1" });
  });
});
