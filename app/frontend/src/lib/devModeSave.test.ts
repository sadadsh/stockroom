/**
 * THE COMMIT PIPELINE'S FRONT HALF (Design Mode Phase 4, plan 1.6 / decision 4).
 *
 * `useDevModeSave` is where a redesign stops being a local experiment: the layout slice joins the
 * five keyed ones in the save payload, the validator's reading of that document travels beside it,
 * and the copy the owner typed themselves is recorded as theirs. Three claims, and each one has a
 * failure mode that is silent rather than loud, which is why each is pinned here:
 *
 *   A DROPPED SLICE is invisible. A Save that quietly omits `layout` looks exactly like a Save that
 *   worked, and the owner discovers it when their laptop pulls main and the arrangement is the old
 *   one. So the payload is read back field by field.
 *
 *   A BASELINE THAT DOES NOT MOVE is invisible in the other direction: Save stays lit, the owner
 *   presses it again, and nothing they can see says whether the first one landed.
 *
 *   A RE-DERIVED DEVIATION LIST would drift. The committed issues have to be what `validateDocument`
 *   said about THIS document with THESE palettes, not an approximation computed elsewhere, so the
 *   test compares against the validator's own output rather than against a hand-written list.
 *
 * ---------------------------------------------------------------------------------------------
 * NON-VACUITY. Each case names the mutation that turns it red, and three were run for real:
 *
 *   1. `layout: { workspace: layout }` removed from the payload -> "carries the working arrangement"
 *      fails on `sent.layout` being undefined. The silent-drop failure above.
 *   2. The layout comparison removed from `dirty` -> "an arrangement edit is an unsaved change"
 *      fails: a redesigned workspace reports itself as saved.
 *   3. `committedIssuesFor` returning `[]` unconditionally -> "the deviation list ships with the
 *      commit" fails on an empty list where the validator reports an unknown piece.
 *
 * THE TWO KNOWN VACUOUS SHAPES, and why neither applies. Nothing here reads source text. And no case
 * asserts merely that something arrived: the arrangement case asserts the document's own id, the
 * issues case asserts a specific code against a specific subject, and the palette case asserts that
 * the SAME document produces DIFFERENT rows under a broken palette.
 */
import { renderHook, act } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../api/client";
import { DEFAULT_WORKSPACE_LAYOUT } from "../layout/defaultWorkspaceLayout";
import { LAYOUT_SCHEMA_VERSION, type LayoutDocument } from "../layout/document";
import { validateDocument } from "../layout/validateDocument";
import { draftThemeTokens } from "../layout/validateContrast";
import { WORKSPACE_PIECE_REGISTRY } from "../layout/workspacePieces";
import type { DevModeDraft, TokenOverrides } from "./devModeDraft";
import { committedIssuesFor, ownerAuthoredCopyIds, useDevModeSave } from "./devModeSave";
import type { LayoutOverrides } from "./layout.overrides";

vi.mock("../api/client", async (importActual) => {
  const actual = await importActual<typeof import("../api/client")>();
  return {
    ...actual,
    api: { ...actual.api, devSave: vi.fn().mockResolvedValue({ ok: true, written: [] }) },
  };
});

// Mutable stand-ins for the two committed modules this hook reads its BASELINE from. Both are empty
// on disk; a test seeds one to stand in for what a previous commit wrote, and the reset puts it back.
const MOCK_LAYOUT_OVERRIDES: LayoutOverrides = vi.hoisted(() => ({ workspace: null }));
vi.mock("./layout.overrides", () => ({ LAYOUT_OVERRIDES: MOCK_LAYOUT_OVERRIDES }));

const MOCK_COPY_OVERRIDES: Record<string, string> = vi.hoisted(() => ({}));
const MOCK_OWNER_AUTHORED: string[] = vi.hoisted(() => []);
vi.mock("./copy.overrides", () => ({
  COPY_OVERRIDES: MOCK_COPY_OVERRIDES,
  OWNER_AUTHORED_COPY_IDS: MOCK_OWNER_AUTHORED,
}));

const mockApi = vi.mocked(api);

beforeEach(() => {
  mockApi.devSave.mockClear();
});

afterEach(() => {
  MOCK_LAYOUT_OVERRIDES.workspace = null;
  for (const key of Object.keys(MOCK_COPY_OVERRIDES)) delete MOCK_COPY_OVERRIDES[key];
  MOCK_OWNER_AUTHORED.length = 0;
});

const NO_TOKENS: TokenOverrides = { root: {}, light: {} };

function draftWith(patch: Partial<DevModeDraft> = {}): DevModeDraft {
  return {
    tokens: { root: {}, light: {} },
    copy: {},
    icons: {},
    elements: {},
    behaviors: {},
    layout: null,
    ...patch,
  };
}

/** A redesign under its own id, so a payload assertion cannot pass on the shipped document. */
function redesign(): LayoutDocument {
  return { ...DEFAULT_WORKSPACE_LAYOUT, id: "workspace.component.redesigned" };
}

/** A document the validator has something to say about: a placement naming no registered piece. */
function documentWithDeviation(): LayoutDocument {
  return {
    schemaVersion: LAYOUT_SCHEMA_VERSION,
    id: "workspace.component.deviant",
    root: {
      kind: "region",
      id: "deviant.root",
      mode: "column",
      slots: [
        {
          kind: "slot",
          id: "deviant.slot",
          content: { kind: "placement", id: "deviant.place", piece: "nobody.registered.this" },
        },
      ],
    },
  };
}

describe("the layout slice in the save payload", () => {
  /**
   * FAILS IF: the layout block is dropped from the payload, or is sent as a bare document rather than
   * keyed by surface - the shell and the remaining routes become siblings of `workspace`, and a bare
   * document would have to be re-keyed by the writer guessing which surface it arranges.
   */
  it("carries the working arrangement, keyed by surface", async () => {
    const layout = redesign();
    const { result } = renderHook(() => useDevModeSave(draftWith({ layout })));

    await act(async () => {
      await result.current.save();
    });

    const sent = mockApi.devSave.mock.calls[0][0];
    expect(sent.layout).toEqual({ workspace: layout });
    expect(sent.layout?.workspace?.id).toBe("workspace.component.redesigned");
  });

  /**
   * NO WORKING EDIT COMMITS THE SHIPPED DEFAULT, deliberately. Reset all clears the arrangement the
   * same way it clears the token map, and saving after it commits that clear - which is the only
   * route back from a committed redesign, and is the same two steps every other slice uses.
   *
   * FAILS IF: a null layout is sent as an absent block (the writer would then leave the committed
   * document in place, and Reset all + Save would silently do nothing to the arrangement).
   */
  it("commits a null arrangement rather than omitting it", async () => {
    const { result } = renderHook(() => useDevModeSave(draftWith({ layout: null })));

    await act(async () => {
      await result.current.save();
    });

    const sent = mockApi.devSave.mock.calls[0][0];
    expect(sent.layout).toEqual({ workspace: null });
    expect(sent.committedIssues).toEqual({ workspace: [] });
  });
});

describe("dirty over the arrangement", () => {
  /** FAILS IF: the baseline ignores the committed module - Save would be lit on every boot. */
  it("is false on boot with a committed arrangement and nothing edited", () => {
    MOCK_LAYOUT_OVERRIDES.workspace = redesign();
    const { result } = renderHook(() =>
      useDevModeSave(draftWith({ layout: structuredClone(MOCK_LAYOUT_OVERRIDES.workspace) })),
    );
    expect(result.current.dirty).toBe(false);
  });

  /** FAILS IF: the layout comparison is missing from `dirty` - mutation 2 above. */
  it("an arrangement edit is an unsaved change", () => {
    const { result } = renderHook(() => useDevModeSave(draftWith({ layout: redesign() })));
    expect(result.current.dirty).toBe(true);
  });

  /**
   * THE BASELINE MOVES WITH THE WRITE, exactly as the five keyed slices' baselines do.
   *
   * FAILS IF: the saved baseline is not updated with the layout - Save stays lit after a successful
   * write, and nothing on screen distinguishes "saved" from "failed".
   */
  it("clears once the arrangement has been written", async () => {
    const layout = redesign();
    const { result, rerender } = renderHook((draft: DevModeDraft) => useDevModeSave(draft), {
      initialProps: draftWith({ layout }),
    });
    expect(result.current.dirty).toBe(true);

    await act(async () => {
      await result.current.save();
    });
    expect(result.current.dirty).toBe(false);

    // And a further edit lights it again - the baseline moved, it did not stop being compared.
    rerender(draftWith({ layout: { ...layout, id: "workspace.component.redesigned-again" } }));
    expect(result.current.dirty).toBe(true);
  });

  /** FAILS IF: a failed save moves the baseline anyway, telling the owner a lost redesign shipped. */
  it("survives a failed save", async () => {
    mockApi.devSave.mockRejectedValueOnce(new Error("no source tree"));
    const { result } = renderHook(() => useDevModeSave(draftWith({ layout: redesign() })));

    await act(async () => {
      await result.current.save();
    });
    expect(result.current.lastError).not.toBeNull();
    expect(result.current.dirty).toBe(true);
  });
});

describe("the deviation list that ships with the commit", () => {
  /**
   * FAILS IF: the issues are re-derived, approximated, or emptied - mutation 3 above. Compared
   * against `validateDocument`'s own output so the two can never disagree about what was committed.
   */
  it("is exactly what the validator says about the document being written", async () => {
    const layout = documentWithDeviation();
    const { result } = renderHook(() => useDevModeSave(draftWith({ layout })));

    await act(async () => {
      await result.current.save();
    });

    const sent = mockApi.devSave.mock.calls[0][0];
    const expected = validateDocument(
      layout,
      WORKSPACE_PIECE_REGISTRY,
      draftThemeTokens(NO_TOKENS),
    );
    expect(sent.committedIssues?.workspace).toEqual(expected);

    // Non-vacuous in its own right: the list actually says something, and says it about this node.
    const unknown = sent.committedIssues?.workspace.filter((i) => i.code === "unknown-piece") ?? [];
    expect(unknown).toHaveLength(1);
    expect(unknown[0].subject.id).toBe("deviant.place");
    expect(unknown[0].severity).toBe("warning");
  });

  /**
   * MEASURED AGAINST THE PALETTE BEING COMMITTED, not the shipped one.
   *
   * FAILS IF: the contrast layer is handed `shippedThemeTokens()` - the committed rows would then
   * describe colours the commit replaces, which is the drift the record exists to avoid.
   */
  it("measures contrast against the token overrides in the same save", () => {
    const layout = DEFAULT_WORKSPACE_LAYOUT;
    const shipped = committedIssuesFor(layout, NO_TOKENS);
    // The primary word tier, drawn the colour of the canvas it sits on: unreadable by construction.
    const blinded: TokenOverrides = {
      root: { "--c-t1": "#101014", "--c-canvas": "#101014" },
      light: {},
    };
    const measured = committedIssuesFor(layout, blinded);

    const failing = measured.filter(
      (issue) => issue.code === "contrast-below-text-floor" && issue.subject.id.includes("--c-t1"),
    );
    expect(failing.length).toBeGreaterThan(0);
    expect(measured).not.toEqual(shipped);
  });

  /** FAILS IF: a null arrangement invents issues about a document that is not being committed. */
  it("is empty when no arrangement is committed", () => {
    expect(committedIssuesFor(null, NO_TOKENS)).toEqual([]);
  });
});

describe("owner-authored copy provenance", () => {
  /**
   * THE MINIMAL HONEST FORM (plan 1.5). An entry whose text is not what is committed was typed in
   * this editor by the owner; an entry that matches the committed text was not touched here and keeps
   * whatever provenance the committed record gave it - which for a hand-edited rewording is none.
   *
   * FAILS IF: every override is marked owner-authored (the lint would stop binding ordinary
   * text committed through any route), or none is (the exemption could never be earned).
   */
  it("records what the editor changed, and leaves untouched entries alone", () => {
    MOCK_COPY_OVERRIDES["detail.hand-edited"] = "Verify";
    MOCK_COPY_OVERRIDES["detail.reworded"] = "Check";

    const recorded = ownerAuthoredCopyIds({
      "detail.hand-edited": "Verify", // unchanged here: not this editor's doing
      "detail.reworded": "Confirm", // retyped in the editor now
      "detail.new": "Open the sheet", // added in the editor now
    });
    expect(recorded).toEqual(["detail.new", "detail.reworded"]);
  });

  /** FAILS IF: a previously-recorded id loses its mark on a save that did not touch it. */
  it("keeps an already-recorded id while it still carries an override", () => {
    MOCK_COPY_OVERRIDES["detail.owner-typed"] = "Check the part";
    MOCK_OWNER_AUTHORED.push("detail.owner-typed");

    expect(ownerAuthoredCopyIds({ "detail.owner-typed": "Check the part" })).toEqual([
      "detail.owner-typed",
    ]);
    // Dropped from the overrides entirely: there is nothing left to exempt, so the mark goes too.
    expect(ownerAuthoredCopyIds({})).toEqual([]);
  });

  /** FAILS IF: the block stops being sent - the writer would clear the record on the next save. */
  it("travels with the save payload", async () => {
    const { result } = renderHook(() =>
      useDevModeSave(draftWith({ copy: { "detail.reworded": "Confirm" } })),
    );

    await act(async () => {
      await result.current.save();
    });

    expect(mockApi.devSave.mock.calls[0][0].ownerAuthoredCopy).toEqual(["detail.reworded"]);
  });
});
