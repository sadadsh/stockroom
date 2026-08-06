/**
 * Reachability, against the shipped arrangement and against documents broken in exactly one way.
 *
 * The anchor is the shipped pair: the default document over the workspace registry warns about
 * NOTHING, because every manifest is placed and nothing is hidden. Everything after it breaks that
 * document in one place and names the mutation to `validateReachability.ts` that would hide the
 * break.
 *
 * The documents are built by deep-cloning the shipped one and editing the clone, deliberately NOT by
 * calling `editOperations`: this suite has to fail when reachability is wrong, not when an edit
 * operation is, and the two would be indistinguishable if an edit produced the fixture.
 */
import { describe, expect, it } from "vitest";
import { DEFAULT_WORKSPACE_LAYOUT } from "./defaultWorkspaceLayout";
import { walkLayout, type LayoutDocument, type LayoutSlot } from "./document";
import { registerPieces, type PieceManifest } from "./registry";
import { validateReachability } from "./validateReachability";
import { WORKSPACE_PIECE_REGISTRY } from "./workspacePieces";

/** A structural copy. The document is serialisable by contract, so this is the whole of a clone. */
function clone(document: LayoutDocument): LayoutDocument {
  // `structuredClone` rather than a JSON round trip: the document is serialisable either way, and
  // the structured algorithm does not depend on that fact holding.
  return structuredClone(document);
}

/** Set `hidden` on one placement of the shipped document, by placement id. */
function withHidden(placementId: string): LayoutDocument {
  const copy = clone(DEFAULT_WORKSPACE_LAYOUT);
  for (const visit of walkLayout(copy)) {
    if (visit.node.kind === "placement" && visit.node.id === placementId) {
      (visit.node as { hidden?: boolean }).hidden = true;
      return copy;
    }
  }
  throw new Error(`No placement named ${placementId}`);
}

/** Empty the slot holding one placement, which is what deleting a piece from a design looks like. */
function withRemoved(placementId: string): LayoutDocument {
  const copy = clone(DEFAULT_WORKSPACE_LAYOUT);
  for (const visit of walkLayout(copy)) {
    if (visit.node.kind !== "slot") continue;
    const slot = visit.node as LayoutSlot & { content: LayoutSlot["content"] };
    if (slot.content?.kind === "placement" && slot.content.id === placementId) {
      slot.content = null;
      return copy;
    }
  }
  throw new Error(`No placement named ${placementId}`);
}

const actionsOf = (issues: ReturnType<typeof validateReachability>) =>
  issues.map((issue) => issue.subject.id);

describe("the shipped arrangement", () => {
  it("leaves no action out of reach", () => {
    // THE ANCHOR. Every manifest in `workspacePieces` is placed by the default document and nothing
    // is hidden, so the shipped design passes its own reachability gate. This test is what makes
    // every warning below meaningful: the validator is silent on a design that is right.
    expect(validateReachability(DEFAULT_WORKSPACE_LAYOUT, WORKSPACE_PIECE_REGISTRY)).toEqual([]);
  });

  it("is actually looking at a large set of actions", () => {
    // Guards the anchor against being vacuous. A registry whose manifests declared no actions would
    // pass the test above by having nothing to check.
    const declared = new Set(
      WORKSPACE_PIECE_REGISTRY.list().flatMap((manifest) => manifest.actions),
    );
    expect(declared.size).toBeGreaterThan(30);
    expect(declared.has("component-browser.delete")).toBe(true);
  });
});

describe("the canonical warning", () => {
  it("names Delete Component by its action id when the action group is hidden", () => {
    // Plan 1.4's own example: hide the identity header's action group and the Manage menu goes with
    // it, taking fourteen commands - Delete Component among them - out of reach.
    //
    // Killing mutation: read `hidden` as "skip this placement's PIECE entirely" rather than as "this
    // placement exposes nothing", or drop the `hidden` test altogether. Either makes this silent.
    const issues = validateReachability(withHidden("workspace.place.header-actions"), WORKSPACE_PIECE_REGISTRY);
    const deleted = issues.find((issue) => issue.subject.id === "component-browser.delete");
    expect(deleted).toBeDefined();
    expect(deleted?.severity).toBe("warning");
    expect(deleted?.subject.kind).toBe("action");
    expect(deleted?.copy.id).toBe("layout-issues.action-unreachable");
    // The row names the ID, never a sentence: the panel resolves the label.
    expect(deleted?.detail).toEqual({
      reason: "hidden",
      declaredBy: "workspace.header-actions",
    });
  });

  it("tells a hidden piece apart from a piece nobody placed", () => {
    // Killing mutation: report one reason for both. The fix differs - one is a setting to clear, the
    // other is a piece to drop back in - and a row that cannot say which is a row nobody can act on.
    const hidden = validateReachability(withHidden("workspace.place.header-actions"), WORKSPACE_PIECE_REGISTRY);
    const removed = validateReachability(withRemoved("workspace.place.header-actions"), WORKSPACE_PIECE_REGISTRY);
    expect(hidden.find((i) => i.subject.id === "component-browser.delete")?.detail?.reason).toBe("hidden");
    expect(removed.find((i) => i.subject.id === "component-browser.delete")?.detail?.reason).toBe("unplaced");
    // And the two agree on WHAT is unreachable; only the reason differs.
    expect(actionsOf(hidden)).toEqual(actionsOf(removed));
  });

  it("warns only about the actions that group alone declared", () => {
    // `component-browser.refresh` is declared by the header action group AND by the offers section,
    // so hiding the header does not put it out of reach. Killing mutation: warn per PIECE rather
    // than per ACTION, which would report every action the hidden piece declared.
    const issues = validateReachability(withHidden("workspace.place.header-actions"), WORKSPACE_PIECE_REGISTRY);
    expect(actionsOf(issues)).not.toContain("component-browser.refresh");
    expect(actionsOf(issues)).toContain("component-browser.delete");
    expect(actionsOf(issues)).toContain("component-browser.copy-mpn");
  });
});

describe("what counts as on screen", () => {
  const manifest = (id: string, actions: readonly string[]): PieceManifest => ({
    id,
    devIds: [],
    dataNeeds: [],
    actions,
    scroll: { owns: false },
    home: { regionId: "r", siblingGroup: "g" },
    source: "test",
  });

  const registry = registerPieces([manifest("piece.one", ["act.one"])]).registry;

  const documentWith = (slots: LayoutSlot[]): LayoutDocument => ({
    schemaVersion: 1,
    id: "test.document",
    root: { kind: "region", id: "r", mode: "column", slots },
  });

  it("counts a placement behind a runtime condition", () => {
    // Five sourcing sections draw only when they have content. A component with no offers is the
    // arrangement working, not a design defect, and warning on it would put a row on screen for
    // every sparse part.
    //
    // Killing mutation: skip placements carrying `visibility`. This document would then warn.
    const document = documentWith([
      {
        kind: "slot",
        id: "s",
        content: {
          kind: "placement",
          id: "p",
          piece: "piece.one",
          visibility: { anyOf: ["some.condition"] },
        },
      },
    ]);
    expect(validateReachability(document, registry)).toEqual([]);
  });

  it("counts a collapsed placement", () => {
    // Collapsing folds a body and leaves a heading: the action is one click further away, not gone.
    // Killing mutation: treat `collapsed` like `hidden`.
    const document = documentWith([
      { kind: "slot", id: "s", content: { kind: "placement", id: "p", piece: "piece.one", collapsed: true } },
    ]);
    expect(validateReachability(document, registry)).toEqual([]);
  });

  it("counts one visible placement of a piece that is also placed hidden", () => {
    // `hidden` is a per-PLACEMENT setting. Hiding the Symbol module does not hide the 3D one.
    // Killing mutation: collect hidden pieces into a set and subtract it from the exposed set.
    const document = documentWith([
      { kind: "slot", id: "s1", content: { kind: "placement", id: "p1", piece: "piece.one", hidden: true } },
      { kind: "slot", id: "s2", content: { kind: "placement", id: "p2", piece: "piece.one" } },
    ]);
    expect(validateReachability(document, registry)).toEqual([]);
  });

  it("warns when every placement of the piece is hidden", () => {
    const document = documentWith([
      { kind: "slot", id: "s1", content: { kind: "placement", id: "p1", piece: "piece.one", hidden: true } },
      { kind: "slot", id: "s2", content: { kind: "placement", id: "p2", piece: "piece.one", hidden: true } },
    ]);
    expect(actionsOf(validateReachability(document, registry))).toEqual(["act.one"]);
  });
});

describe("the list itself", () => {
  it("is ordered by action id, so two runs agree", () => {
    // Killing mutation: emit in registry order. The list would then reshuffle whenever a manifest
    // moved in `workspacePieces.ts`, and a committed layout's issues could not be diffed.
    const issues = validateReachability(withRemoved("workspace.place.header-actions"), WORKSPACE_PIECE_REGISTRY);
    const ids = actionsOf(issues);
    expect(ids.length).toBeGreaterThan(5);
    expect(ids).toEqual([...ids].sort());
  });

  it("reports every declaring piece when more than one declares a lost action", () => {
    const manifests: PieceManifest[] = ["piece.a", "piece.b"].map((id) => ({
      id,
      devIds: [],
      dataNeeds: [],
      actions: ["act.shared"],
      scroll: { owns: false },
      home: { regionId: "r", siblingGroup: "g" },
      source: "test",
    }));
    const registry = registerPieces(manifests).registry;
    const empty: LayoutDocument = {
      schemaVersion: 1,
      id: "test.document",
      root: { kind: "region", id: "r", mode: "column", slots: [] },
    };
    expect(validateReachability(empty, registry)[0]?.detail).toEqual({
      reason: "unplaced",
      declaredBy: "piece.a piece.b",
    });
  });
});
