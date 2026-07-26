import { describe, expect, it } from "vitest";
import {
  containerLayoutOf,
  gridColumnsOf,
  isValidGridSlot,
  isValidOrder,
  reorderSiblings,
  reorderSiblingsOf,
} from "./elementLayout";

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

  it("moves exactly one step across three-plus siblings, preserving the others' relative order", () => {
    // [a,b,c,d,e], move c down -> [a,b,d,c,e]: c and d swap, everyone else keeps their place.
    expect(reorderSiblings(["a", "b", "c", "d", "e"], "c", "down")).toEqual({
      a: "0",
      b: "1",
      d: "2",
      c: "3",
      e: "4",
    });
  });

  it("is stable when applied repeatedly: walking down halts at the last position", () => {
    // Simulate the panel re-deriving the visual sequence before each click (sort by order value).
    const seqFrom = (map: Record<string, string>) =>
      Object.entries(map)
        .sort((a, b) => Number(a[1]) - Number(b[1]))
        .map(([id]) => id);

    let seq = ["a", "b", "c"];
    seq = seqFrom(reorderSiblings(seq, "a", "down")); // -> [b,a,c]
    expect(seq).toEqual(["b", "a", "c"]);
    seq = seqFrom(reorderSiblings(seq, "a", "down")); // -> [b,c,a]
    expect(seq).toEqual(["b", "c", "a"]);
    seq = seqFrom(reorderSiblings(seq, "a", "down")); // at the end: no change
    expect(seq).toEqual(["b", "c", "a"]);
  });
});

describe("gridColumnsOf", () => {
  it("reads the column-track count from a grid-cols-N class", () => {
    expect(gridColumnsOf(makeContainer("grid grid-cols-2 gap-2", []))).toBe(2);
    expect(gridColumnsOf(makeContainer("grid grid-cols-12", []))).toBe(12);
    expect(gridColumnsOf(makeContainer("inline-grid grid-cols-3", []))).toBe(3);
  });

  it("returns 0 when no grid-cols-N class is present, and is null-safe", () => {
    expect(gridColumnsOf(makeContainer("grid gap-2", []))).toBe(0);
    expect(gridColumnsOf(makeContainer("flex flex-col", []))).toBe(0);
    // A partial token must not match (whole grid-cols-N only).
    expect(gridColumnsOf(makeContainer("grid-cols", []))).toBe(0);
    expect(gridColumnsOf(null)).toBe(0);
    expect(gridColumnsOf(undefined)).toBe(0);
  });
});

describe("isValidGridSlot", () => {
  it("accepts one or two safe line tokens (auto / small integer / span N)", () => {
    for (const v of ["1", "1 / 3", "span 2", "auto", "2", "-1", "1 / span 2", "auto / 3"]) {
      expect(isValidGridSlot(v)).toBe(true);
    }
  });

  it("rejects a three-part slot, empty, a stray identifier, and punctuation", () => {
    for (const v of ["1 / 2 / 3", "red", "", "1;2", "1 / red", "12345", "1 2"]) {
      expect(isValidGridSlot(v)).toBe(false);
    }
  });
});

describe("isValidOrder", () => {
  it("accepts a signed 1-3 digit integer (the backend `order` grammar)", () => {
    for (const v of ["0", "2", "-1", "120", "-120", "99"]) {
      expect(isValidOrder(v)).toBe(true);
    }
  });

  it("rejects empty, four-plus digits, slot syntax, and non-numeric text", () => {
    for (const v of ["", "1 / 2", "1200", "abc", "99999", "1.5", " 2", "12px"]) {
      expect(isValidOrder(v)).toBe(false);
    }
  });
});
