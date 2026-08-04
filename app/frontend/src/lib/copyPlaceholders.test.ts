/**
 * The placeholder grammar and the three ways an override can be wrong.
 *
 * Every rule here has a matching backend rule in `dev.py`. The two halves are not redundant: the
 * backend stops a bad rewording being COMMITTED, and this stops a committed one - from a hand edit,
 * or from an older revision whose default said something else - from reaching a person.
 */
import { beforeEach, describe, expect, it } from "vitest";
import {
  copyDiagnosticFor,
  copyDiagnostics,
  copyOverrideProblem,
  copyPlaceholderDeclarations,
  copyPlaceholders,
  declareCopyPlaceholders,
  formatCopy,
  recordCopyDiagnostic,
  resetCopyDeclarations,
  resetCopyDiagnostics,
} from "./copyPlaceholders";

beforeEach(() => {
  resetCopyDiagnostics();
  resetCopyDeclarations();
});

describe("copyPlaceholders", () => {
  it("reads the names out of a well-formed template, sorted and de-duplicated", () => {
    expect(copyPlaceholders("Downloaded {count} of {total} files")).toEqual(["count", "total"]);
    expect(copyPlaceholders("{count} of {count}")).toEqual(["count"]);
    expect(copyPlaceholders("No placeholders here")).toEqual([]);
  });

  it("rejects every brace that is not part of a well-formed {name}", () => {
    expect(copyPlaceholders("Downloaded {coun")).toBeNull();
    expect(copyPlaceholders("Downloaded }count{")).toBeNull();
    expect(copyPlaceholders("Empty {}")).toBeNull();
    // A digit-led name is not a name; the `{2}` survives the token pass and trips the brace check.
    expect(copyPlaceholders("Index {2}")).toBeNull();
    // Doubling is not an escape in this grammar - the inner token matches and the outer braces stay.
    expect(copyPlaceholders("{{count}}")).toBeNull();
  });
});

describe("copyOverrideProblem", () => {
  const base = "Downloaded {count} of {total} files";

  it("accepts a rewording that keeps exactly the declared set", () => {
    expect(copyOverrideProblem(base, "{count} of {total} files are here")).toBeNull();
    expect(copyOverrideProblem("Add Part", "Add A Part")).toBeNull();
  });

  it("names a malformed override", () => {
    expect(copyOverrideProblem(base, "Downloaded {count} of {total files")).toBe("malformed");
  });

  it("names a dropped placeholder", () => {
    expect(copyOverrideProblem(base, "Downloaded {count} files")).toBe("missing-placeholder");
    expect(copyOverrideProblem(base, "Downloaded some files")).toBe("missing-placeholder");
  });

  it("names an invented placeholder", () => {
    expect(copyOverrideProblem(base, "Downloaded {count} of {total} on {pages}")).toBe(
      "unknown-placeholder",
    );
    // A sentence that never had a placeholder may not grow one: there is no value to put there.
    expect(copyOverrideProblem("Add Part", "Add {count} Parts")).toBe("unknown-placeholder");
  });

  it("holds an override to the empty set when the DEFAULT is itself malformed", () => {
    // A malformed default is a source bug (copy.coverage.test.ts fails on one). Until it is fixed
    // the stricter reading applies, rather than the override inheriting the mistake.
    expect(copyOverrideProblem("Broken {", "Broken {count}")).toBe("unknown-placeholder");
  });
});

describe("formatCopy", () => {
  it("substitutes every occurrence of a named value", () => {
    expect(formatCopy("Downloaded {count} of {total} files", { count: 3, total: 10 })).toBe(
      "Downloaded 3 of 10 files",
    );
    expect(formatCopy("{name} and {name}", { name: "A" })).toBe("A and A");
  });

  it("never renders template syntax when a value is missing", () => {
    const out = formatCopy("Downloaded {count} of {total} files", { count: 3 });
    expect(out).not.toContain("{");
    expect(out).not.toContain("}");
    expect(out).toBe("Downloaded 3 of  files");
  });

  it("leaves a placeholder-free string byte-identical", () => {
    expect(formatCopy("Add A Part")).toBe("Add A Part");
    expect(formatCopy("Add A Part", { count: 1 })).toBe("Add A Part");
  });
});

describe("diagnostics", () => {
  it("records one entry per id and reads back by id", () => {
    recordCopyDiagnostic("a.b", "malformed", ["count"]);
    recordCopyDiagnostic("a.b", "malformed", ["count"]);
    expect(copyDiagnostics()).toHaveLength(1);
    expect(copyDiagnosticFor("a.b")).toEqual({
      id: "a.b",
      problem: "malformed",
      required: ["count"],
    });
  });

  it("is bounded, so a pathological overrides file cannot grow it without limit", () => {
    for (let i = 0; i < 400; i++) recordCopyDiagnostic(`id.${i}`, "malformed", []);
    expect(copyDiagnostics().length).toBeLessThanOrEqual(200);
  });
});

describe("declarations", () => {
  it("records the required set for every id it has seen, including the empty one", () => {
    declareCopyPlaceholders("x.count", "Downloaded {count} of {total} files");
    declareCopyPlaceholders("x.plain", "Add A Part");
    expect(copyPlaceholderDeclarations()).toEqual({
      "x.count": ["count", "total"],
      "x.plain": [],
    });
  });
});
