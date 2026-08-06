/**
 * The piece registry container.
 *
 * Small surface, three claims worth pinning: a manifest can be looked up by the id it registered
 * under, the list is registration order, and a duplicate is REPORTED without the first registration
 * being lost. The last of those is the one that matters - the whole point of reporting rather than
 * throwing or replacing is that the winner must not depend on which module imported first.
 */
import { describe, expect, it } from "vitest";
import { createPieceRegistry, registerPieces, type PieceManifest } from "./registry";

function manifest(id: string, source = `source/${id}.tsx`): PieceManifest {
  return {
    id,
    devIds: [],
    dataNeeds: [],
    actions: [],
    scroll: { owns: false },
    home: { regionId: "region.somewhere", siblingGroup: "group.somewhere" },
    source,
  };
}

describe("the piece registry", () => {
  it("registers, resolves and lists in registration order", () => {
    // Fails if `list` sorts, if `get` returns a copy that loses fields, or if `has` disagrees
    // with `get`.
    const registry = createPieceRegistry();
    expect(registry.register(manifest("piece.beta"))).toBeNull();
    expect(registry.register(manifest("piece.alpha"))).toBeNull();

    expect(registry.list().map((entry) => entry.id)).toEqual(["piece.beta", "piece.alpha"]);
    expect(registry.get("piece.alpha")?.source).toBe("source/piece.alpha.tsx");
    expect(registry.has("piece.beta")).toBe(true);
    expect(registry.has("piece.gamma")).toBe(false);
    expect(registry.get("piece.gamma")).toBeUndefined();
  });

  it("reports a duplicate registration and keeps the first", () => {
    // Fails if a second registration overwrites the first (the winner would then depend on import
    // order), or if a duplicate is swallowed and never reported.
    const registry = createPieceRegistry();
    registry.register(manifest("piece.alpha", "source/first.tsx"));
    const issue = registry.register(manifest("piece.alpha", "source/second.tsx"));

    expect(issue).toEqual({
      code: "duplicate-piece",
      pieceId: "piece.alpha",
      detail: { kept: "source/first.tsx", rejected: "source/second.tsx" },
    });
    expect(registry.get("piece.alpha")?.source).toBe("source/first.tsx");
    expect(registry.list()).toHaveLength(1);
  });

  it("does not throw on a duplicate", () => {
    // The warn-never-block contract at the registry level: a duplicated catalogue entry must not
    // take down every module that imports the registry.
    const registry = createPieceRegistry();
    registry.register(manifest("piece.alpha"));
    expect(() => registry.register(manifest("piece.alpha"))).not.toThrow();
  });

  it("collects every duplicate when a whole list is registered at once", () => {
    // Fails if `registerPieces` keeps only the last issue, or stops at the first duplicate.
    const { registry, issues } = registerPieces([
      manifest("piece.alpha"),
      manifest("piece.beta"),
      manifest("piece.alpha"),
      manifest("piece.beta"),
    ]);
    expect(issues.map((issue) => issue.pieceId)).toEqual(["piece.alpha", "piece.beta"]);
    expect(registry.list().map((entry) => entry.id)).toEqual(["piece.alpha", "piece.beta"]);
  });

  it("satisfies the validator's lookup without being handed to it as a special case", () => {
    // The registry is structurally a `PieceLookup`; if `has` were renamed the validator would stop
    // compiling against it, which is the coupling this asserts.
    const { registry } = registerPieces([manifest("piece.alpha")]);
    const lookup: { has(id: string): boolean } = registry;
    expect(lookup.has("piece.alpha")).toBe(true);
  });
});
