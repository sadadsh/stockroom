/**
 * Named local drafts: the round trip, the ordering, and every way storage can let the editor down.
 *
 * The interesting half of this file is the FAILURE half. `lib/workspaceColumns.ts` set the discipline
 * these helpers follow - a browser with storage disabled must render the workspace at its defaults
 * rather than fail to render it - and a helper that swallows failures can only be shown to swallow
 * them by making storage fail on purpose. So `localStorage` is made to throw, made to hold junk, and
 * made to hold a plausible-but-wrong file, and every case asserts what the caller is told.
 *
 * ---------------------------------------------------------------------------------------------
 * NON-VACUITY. Each test names the mutation to `layoutDrafts.ts` that turns it red. Two were run for
 * real and reverted:
 *
 *   1. THE TRY/CATCH AROUND THE READ WAS REMOVED. Deleting the `try` in `readFile`'s `getItem` failed
 *      "survives a browser that refuses storage entirely" with the thrown `SecurityError` rather than
 *      an empty list - which is the editor going down over a storage setting.
 *   2. THE SHAPE CHECK WAS WEAKENED. Changing `isLayoutDocument` to `typeof value === "object"` failed
 *      "drops an entry that is not a layout document" - the stored `{ root: "nope" }` loaded as a
 *      document and would have been handed to the renderer.
 *
 * THE TWO KNOWN VACUOUS SHAPES, and why neither applies. Nothing here reads source text. And no case
 * asserts only that a call "did not throw": every one asserts the VALUE returned and, where a write
 * was meant to land, reads it back through the public functions rather than out of the raw key.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { DEFAULT_WORKSPACE_LAYOUT } from "../layout/defaultWorkspaceLayout";
import { LAYOUT_SCHEMA_VERSION, type LayoutDocument } from "../layout/document";
import { setPlacementHidden } from "../layout/editOperations";
import {
  deleteLayoutDraft,
  LAYOUT_DRAFTS_STORAGE_KEY,
  LAYOUT_DRAFT_NAME_MAX,
  listLayoutDrafts,
  loadLayoutDraft,
  saveLayoutDraft,
} from "./layoutDrafts";

afterEach(() => {
  window.localStorage.clear();
  vi.restoreAllMocks();
});

function tiny(id = "fixture"): LayoutDocument {
  return {
    schemaVersion: LAYOUT_SCHEMA_VERSION,
    id,
    root: {
      kind: "region",
      id: "root",
      mode: "column",
      slots: [
        { kind: "slot", id: "slot.a", content: { kind: "placement", id: "place.a", piece: "piece.a" } },
      ],
    },
  };
}

/** What is actually in storage, for the cases that are about the stored file itself. */
function storedFile(): unknown {
  const raw = window.localStorage.getItem(LAYOUT_DRAFTS_STORAGE_KEY);
  return raw ? (JSON.parse(raw) as unknown) : null;
}

describe("named layout drafts", () => {
  /** FAILS IF: the document is stored by reference, or the round trip loses a field. */
  it("saves and loads a document, by value", () => {
    const document = tiny();
    expect(saveLayoutDraft("sourcing left", document)).toBe(true);

    const loaded = loadLayoutDraft("sourcing left");
    expect(loaded).toEqual(document);
    // A fresh object: mutating what came back cannot reach into storage or into the caller's document.
    expect(loaded).not.toBe(document);
    expect(loadLayoutDraft("sourcing left")).not.toBe(loaded);
  });

  /** FAILS IF: the shipped document does not survive the round trip - the case that matters most. */
  it("round-trips the shipped workspace document and an edit of it", () => {
    expect(saveLayoutDraft("as shipped", DEFAULT_WORKSPACE_LAYOUT)).toBe(true);
    expect(loadLayoutDraft("as shipped")).toEqual(structuredClone(DEFAULT_WORKSPACE_LAYOUT));

    const edited = setPlacementHidden(
      DEFAULT_WORKSPACE_LAYOUT,
      "workspace.place.sourcing-offers",
      true,
    );
    expect(saveLayoutDraft("no offers", edited)).toBe(true);
    expect(loadLayoutDraft("no offers")).toEqual(edited);
    // Two drafts, not one overwritten by the other.
    expect(listLayoutDrafts().map((entry) => entry.name).sort()).toEqual(["as shipped", "no offers"]);
  });

  /** FAILS IF: a name is not trimmed, so one draft is stored under two keys. */
  it("treats a name and its padded form as one draft", () => {
    expect(saveLayoutDraft("  spec first  ", tiny("first"))).toBe(true);
    expect(saveLayoutDraft("spec first", tiny("second"))).toBe(true);
    expect(listLayoutDrafts()).toHaveLength(1);
    expect(listLayoutDrafts()[0].name).toBe("spec first");
    expect(loadLayoutDraft(" spec first ")?.id).toBe("second");
  });

  /** FAILS IF: a save under an existing name versions instead of replacing. */
  it("replaces a draft of the same name and keeps the newer save time", () => {
    expect(saveLayoutDraft("one", tiny("old"), 1_000)).toBe(true);
    expect(saveLayoutDraft("one", tiny("new"), 2_000)).toBe(true);
    expect(listLayoutDrafts()).toEqual([{ name: "one", savedAt: 2_000, documentId: "new" }]);
    expect(loadLayoutDraft("one")?.id).toBe("new");
  });

  /** FAILS IF: the list is not newest-first, or the tie-break is unstable. */
  it("lists drafts newest first, with names breaking a tie", () => {
    saveLayoutDraft("older", tiny(), 1_000);
    saveLayoutDraft("newest", tiny(), 3_000);
    saveLayoutDraft("beta", tiny(), 2_000);
    saveLayoutDraft("alpha", tiny(), 2_000);
    expect(listLayoutDrafts().map((entry) => entry.name)).toEqual([
      "newest",
      "alpha",
      "beta",
      "older",
    ]);
  });

  /** FAILS IF: a delete reports success for a name nobody saved, or takes a sibling with it. */
  it("deletes by name and reports whether there was anything to delete", () => {
    saveLayoutDraft("keep", tiny());
    saveLayoutDraft("drop", tiny());
    expect(deleteLayoutDraft("drop")).toBe(true);
    expect(deleteLayoutDraft("drop")).toBe(false);
    expect(deleteLayoutDraft("never existed")).toBe(false);
    expect(listLayoutDrafts().map((entry) => entry.name)).toEqual(["keep"]);
    expect(loadLayoutDraft("keep")).not.toBeNull();
  });

  /** FAILS IF: an unusable name is stored anyway - an unnamed draft nobody can find again. */
  it("refuses a name that cannot be found again", () => {
    for (const name of ["", "   ", "\n\t", "x".repeat(LAYOUT_DRAFT_NAME_MAX + 1)]) {
      expect(saveLayoutDraft(name, tiny())).toBe(false);
    }
    expect(storedFile()).toBeNull();
    expect(listLayoutDrafts()).toEqual([]);
    expect(loadLayoutDraft("")).toBeNull();
    // The bound itself is allowed - it is a limit, not an off-by-one.
    expect(saveLayoutDraft("x".repeat(LAYOUT_DRAFT_NAME_MAX), tiny())).toBe(true);
  });

  /** FAILS IF: something that is not a document is accepted, and later handed to the renderer. */
  it("refuses a document that is not one", () => {
    const notDocuments: unknown[] = [
      null,
      undefined,
      42,
      "a document",
      {},
      { schemaVersion: 1, id: "x" },
      { schemaVersion: 1, id: "x", root: { kind: "slot", slots: [] } },
      { schemaVersion: 1, id: "x", root: { kind: "region", slots: "nope" } },
      { schemaVersion: "1", id: "x", root: { kind: "region", slots: [] } },
    ];
    for (const value of notDocuments) {
      expect(saveLayoutDraft("bad", value as LayoutDocument)).toBe(false);
    }
    expect(listLayoutDrafts()).toEqual([]);
  });

  /** FAILS IF: a document with a cycle throws out of `saveLayoutDraft` instead of being refused. */
  it("refuses a document that will not serialise", () => {
    const document = tiny();
    (document.root as { self?: unknown }).self = document.root;
    expect(saveLayoutDraft("cyclic", document)).toBe(false);
    expect(listLayoutDrafts()).toEqual([]);
  });
});

describe("storage that lets the editor down", () => {
  /**
   * FAILS IF: the `try` around `getItem` is removed - the mutation proven above. Every reader has to
   * answer, because the alternative is a Design Mode panel that cannot mount in a locked-down browser.
   */
  it("survives a browser that refuses storage entirely", () => {
    const boom = () => {
      throw new DOMException("denied", "SecurityError");
    };
    // Spied on the PROTOTYPE, following ComponentWorkspace.test.tsx: jsdom's `localStorage` is a proxy
    // and an own-property spy on the instance is not what the call reaches.
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(boom);
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(boom);

    expect(listLayoutDrafts()).toEqual([]);
    expect(loadLayoutDraft("anything")).toBeNull();
    expect(deleteLayoutDraft("anything")).toBe(false);
    expect(saveLayoutDraft("anything", tiny())).toBe(false);
  });

  /** FAILS IF: a quota failure is reported as a successful save, so the owner trusts a lost draft. */
  it("reports false when a write cannot land", () => {
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new DOMException("full", "QuotaExceededError");
    });
    expect(saveLayoutDraft("too big", tiny())).toBe(false);
  });

  /** FAILS IF: a corrupt file throws on read rather than reading as no drafts at all. */
  it("reads junk as no drafts", () => {
    for (const raw of ["", "not json", "[]", "null", '"a string"', "{}", '{"version":1}']) {
      window.localStorage.setItem(LAYOUT_DRAFTS_STORAGE_KEY, raw);
      expect(listLayoutDrafts(), raw).toEqual([]);
      expect(loadLayoutDraft("one"), raw).toBeNull();
    }
  });

  /** FAILS IF: a file from another schema version is read as if it were this one. */
  it("ignores a file written by another version", () => {
    window.localStorage.setItem(
      LAYOUT_DRAFTS_STORAGE_KEY,
      JSON.stringify({
        version: 99,
        drafts: { one: { name: "one", savedAt: 1, documentId: "x", document: tiny() } },
      }),
    );
    expect(listLayoutDrafts()).toEqual([]);
  });

  /**
   * FAILS IF: the per-entry shape check is weakened - the mutation proven above. The good entry beside
   * the bad ones is the point: one unreadable draft must not cost the owner the others.
   */
  it("drops an entry that is not a layout document, and keeps the ones that are", () => {
    window.localStorage.setItem(
      LAYOUT_DRAFTS_STORAGE_KEY,
      JSON.stringify({
        version: 1,
        drafts: {
          good: { name: "good", savedAt: 2, documentId: "fixture", document: tiny() },
          "no document": { name: "no document", savedAt: 3 },
          "bad root": {
            name: "bad root",
            savedAt: 4,
            documentId: "x",
            document: { schemaVersion: 1, id: "x", root: "nope" },
          },
          "wrong name": { name: "other", savedAt: 5, documentId: "x", document: tiny() },
          "no time": { name: "no time", savedAt: "yesterday", documentId: "x", document: tiny() },
          "": { name: "", savedAt: 6, documentId: "x", document: tiny() },
        },
      }),
    );
    expect(listLayoutDrafts()).toEqual([{ name: "good", savedAt: 2, documentId: "fixture" }]);
    expect(loadLayoutDraft("good")).toEqual(tiny());
    expect(loadLayoutDraft("bad root")).toBeNull();
    expect(loadLayoutDraft("wrong name")).toBeNull();
  });

  /** FAILS IF: a save rewrites the file from scratch and loses the drafts it could not parse... */
  it("keeps the readable drafts when a new one is saved beside a corrupt neighbour", () => {
    window.localStorage.setItem(
      LAYOUT_DRAFTS_STORAGE_KEY,
      JSON.stringify({
        version: 1,
        drafts: {
          good: { name: "good", savedAt: 2, documentId: "fixture", document: tiny() },
          broken: { name: "broken", savedAt: 3 },
        },
      }),
    );
    expect(saveLayoutDraft("fresh", tiny("fresh"), 4)).toBe(true);
    expect(listLayoutDrafts().map((entry) => entry.name)).toEqual(["fresh", "good"]);
  });
});
