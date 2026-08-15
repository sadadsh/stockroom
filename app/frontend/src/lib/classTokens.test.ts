import { describe, expect, it } from "vitest";
import { CLASS_TO_VAR, TOKEN_COLOR_CLASSES, varsForClassName } from "./classTokens";
import { DEV_TOKEN_BY_VAR } from "./devTokens";

// The class map is what the inspect surface reads to name an element's tokens from its
// className, so these tests pin the entry count, the resolver's dedupe/ignore behaviour,
// and the invariant that every mapped cssVar is a real DEV_TOKEN.
describe("classTokens resolver", () => {
  it("maps every editable color through the complete utility-role vocabulary", () => {
    const nonColorEntries = 20;
    expect(Object.keys(CLASS_TO_VAR)).toHaveLength(
      Object.keys(TOKEN_COLOR_CLASSES).length * 6 + nonColorEntries,
    );
    for (const name of Object.keys(TOKEN_COLOR_CLASSES)) {
      for (const role of ["bg", "text", "border", "outline", "ring", "stroke"]) {
        expect(CLASS_TO_VAR[`${role}-${name}`]).toBe(TOKEN_COLOR_CLASSES[name]);
      }
    }
  });

  it("resolves known classes in order, deduped, ignoring unknowns", () => {
    // p-2 is a structural utility with no token; it is dropped.
    expect(varsForClassName("bg-acc text-t1 p-2")).toEqual(["--c-acc", "--c-t1"]);
    // First-seen order is preserved.
    expect(varsForClassName("text-t1 bg-acc")).toEqual(["--c-t1", "--c-acc"]);
    // Variants and opacity modifiers still resolve to the underlying editable token.
    expect(varsForClassName("focus-visible:outline-focus hover:bg-err/10")).toEqual([
      "--c-focus",
      "--c-err",
    ]);
    // A className with no token classes resolves to nothing.
    expect(varsForClassName("p-2 flex items-center")).toEqual([]);
  });

  it("collapses bg-/text-/border- of one colour to a single cssVar", () => {
    expect(varsForClassName("bg-acc border-acc")).toEqual(["--c-acc"]);
    expect(varsForClassName("bg-acc text-acc border-acc")).toEqual(["--c-acc"]);
    // A distinct colour still comes through as its own var, once.
    expect(varsForClassName("bg-acc text-acc bg-t2 border-t2")).toEqual([
      "--c-acc",
      "--c-t2",
    ]);
  });

  it("maps every cssVar to a real DEV_TOKEN", () => {
    for (const cssVar of Object.values(CLASS_TO_VAR)) {
      expect(DEV_TOKEN_BY_VAR.has(cssVar)).toBe(true);
    }
  });
});
