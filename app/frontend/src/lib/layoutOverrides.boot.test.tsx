/**
 * THE ARRANGEMENT IN FORCE: the working draft, the committed override, the shipped default, in that
 * order - and the layout slice's membership of the one history and the one Reset all.
 *
 * WHY THIS FILE EXISTS. Phase 3A adds a sixth slice to a five-slice provider and a third source for
 * the document the workspace draws. Two things have to be true and neither is visible in a rendered
 * screenshot: with nothing committed and nothing edited the answer must be the SHIPPED OBJECT ITSELF
 * (which is why `ComponentWorkspace.domParity.test.tsx`'s digests do not move), and a committed
 * layout must apply on boot with Design Mode OFF (a redesign that shipped through source is the app,
 * plan decision 4). This file asserts both, plus the three-way order between them.
 *
 * The committed module is mocked the way `elementOverrides.boot.test.tsx` mocks
 * `lib/element.overrides.ts`: a mutable stand-in for a file that is empty on disk, seeded by a test to
 * stand in for what a Phase 4 commit would have written, emptied afterwards so nothing leaks.
 *
 * ---------------------------------------------------------------------------------------------
 * NON-VACUITY. Each test names the mutation that turns it red. Two were run for real and reverted:
 *
 *   1. THE ORDER WAS INVERTED. Making `resolveWorkspaceLayout` prefer the committed override over the
 *      draft failed "prefers a working draft over the committed override" - the failure that means an
 *      owner's edit does not appear on the screen they are editing.
 *   2. THE SLICE FELL OUT OF THE DRAFT. Removing `layout` from `emptyDraft()` in `devModeDraft.ts`
 *      failed "is cleared by Reset all alongside the other five slices" (the reducer's returned object
 *      no longer carries the key, so the working document survived a reset).
 *
 * THE TWO KNOWN VACUOUS SHAPES, and why neither applies. Nothing here reads source text. And no case
 * asserts merely that a document came back: the shipped case asserts REFERENCE identity with
 * `DEFAULT_WORKSPACE_LAYOUT`, and every draft case asserts a marker the other two documents do not
 * carry (the id, and the placement that was hidden).
 */
import { renderHook, act, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ReactNode } from "react";
import { DEFAULT_WORKSPACE_LAYOUT } from "../layout/defaultWorkspaceLayout";
import { findPlacement, type LayoutDocument } from "../layout/document";
import { setPlacementHidden } from "../layout/editOperations";
import { resolveWorkspaceLayout } from "../layout/resolveWorkspaceLayout";
import { ThemeProvider } from "./theme";
import { DevModeProvider, useDevMode } from "./devMode";
import type { LayoutOverrides } from "./layout.overrides";

// A mutable stand-in for the committed lib/layout.overrides.ts (null on disk). A test seeds it to
// stand in for what a Phase 4 commit wrote; afterEach puts it back so nothing leaks between tests.
const MOCK_LAYOUT_OVERRIDES: LayoutOverrides = vi.hoisted(() => ({ workspace: null }));
vi.mock("./layout.overrides", () => ({ LAYOUT_OVERRIDES: MOCK_LAYOUT_OVERRIDES }));

vi.mock("../api/client", async (importActual) => {
  const actual = await importActual<typeof import("../api/client")>();
  return {
    ...actual,
    api: { ...actual.api, devSave: vi.fn().mockResolvedValue({ ok: true, written: [] }) },
  };
});

afterEach(() => {
  MOCK_LAYOUT_OVERRIDES.workspace = null;
  document.documentElement.removeAttribute("style");
  document.documentElement.removeAttribute("data-theme");
});

function wrapper({ children }: { children: ReactNode }) {
  return (
    <ThemeProvider>
      <DevModeProvider>{children}</DevModeProvider>
    </ThemeProvider>
  );
}

/** A committed redesign: the shipped arrangement with the offers section hidden, under its own id. */
function committedRedesign(): LayoutDocument {
  const edited = setPlacementHidden(
    DEFAULT_WORKSPACE_LAYOUT,
    "workspace.place.sourcing-offers",
    true,
  );
  return { ...edited, id: "workspace.component.committed" };
}

/** What the owner is editing: the lifecycle section hidden instead, under a third id. */
function workingDraft(): LayoutDocument {
  const edited = setPlacementHidden(
    DEFAULT_WORKSPACE_LAYOUT,
    "workspace.place.sourcing-lifecycle",
    true,
  );
  return { ...edited, id: "workspace.component.draft" };
}

describe("the arrangement in force", () => {
  /**
   * THE PARITY GATE'S PRECONDITION. FAILS IF: the resolver stops falling through to the shipped
   * document, or returns a COPY of it - a copy would render the same DOM but would defeat the
   * reference-identity the renderer's keying and the engine-invariant mock both rely on.
   */
  it("is the shipped document itself when nothing is committed and nothing is edited", () => {
    expect(resolveWorkspaceLayout(null)).toBe(DEFAULT_WORKSPACE_LAYOUT);
    expect(resolveWorkspaceLayout(undefined)).toBe(DEFAULT_WORKSPACE_LAYOUT);

    const { result } = renderHook(() => useDevMode(), { wrapper });
    expect(result.current.enabled).toBe(false);
    expect(result.current.layoutDraft).toBeNull();
    expect(result.current.isLayoutEdited).toBe(false);
    expect(resolveWorkspaceLayout(result.current.layoutDraft)).toBe(DEFAULT_WORKSPACE_LAYOUT);
  });

  /**
   * THE BOOT APPLY, Design Mode OFF: a committed redesign is what everyone opens.
   *
   * FAILS IF: the resolver ignores the committed override, or the provider does not seed its working
   * state from it (the slice would start empty and the panel would show no arrangement at all).
   */
  it("applies a committed override on boot with Design Mode off", () => {
    MOCK_LAYOUT_OVERRIDES.workspace = committedRedesign();

    // Even with no provider mounted - an isolated test, a surface rendered on its own.
    expect(resolveWorkspaceLayout(null).id).toBe("workspace.component.committed");

    const { result } = renderHook(() => useDevMode(), { wrapper });
    expect(result.current.enabled).toBe(false);
    expect(result.current.layoutDraft?.id).toBe("workspace.component.committed");
    expect(result.current.isLayoutEdited).toBe(true);
    expect(
      findPlacement(result.current.layoutDraft as LayoutDocument, "workspace.place.sourcing-offers")
        ?.hidden,
    ).toBe(true);
    // A DEEP copy: an edit to the working document must not reach into the imported module.
    expect(result.current.layoutDraft).not.toBe(MOCK_LAYOUT_OVERRIDES.workspace);
    expect(result.current.layoutDraft?.root).not.toBe(MOCK_LAYOUT_OVERRIDES.workspace?.root);
  });

  /**
   * FAILS IF: the resolution order is inverted - the mutation proven above, and the one that would
   * make editing on the live app pointless.
   */
  it("prefers a working draft over the committed override, and the override over the default", () => {
    MOCK_LAYOUT_OVERRIDES.workspace = committedRedesign();
    expect(resolveWorkspaceLayout(workingDraft()).id).toBe("workspace.component.draft");
    expect(resolveWorkspaceLayout(null).id).toBe("workspace.component.committed");
    MOCK_LAYOUT_OVERRIDES.workspace = null;
    expect(resolveWorkspaceLayout(null)).toBe(DEFAULT_WORKSPACE_LAYOUT);
  });
});

describe("the layout slice of the dev mode draft", () => {
  /** FAILS IF: the slice does not hold what it was handed, or `isLayoutEdited` does not follow it. */
  it("holds the document it is given and drops it on reset", () => {
    const { result } = renderHook(() => useDevMode(), { wrapper });
    act(() => result.current.setLayoutDraft(workingDraft()));
    expect(result.current.layoutDraft?.id).toBe("workspace.component.draft");
    expect(result.current.isLayoutEdited).toBe(true);
    expect(resolveWorkspaceLayout(result.current.layoutDraft).id).toBe("workspace.component.draft");

    act(() => result.current.resetLayoutDraft());
    expect(result.current.layoutDraft).toBeNull();
    expect(result.current.isLayoutEdited).toBe(false);
    expect(resolveWorkspaceLayout(result.current.layoutDraft)).toBe(DEFAULT_WORKSPACE_LAYOUT);
  });

  /**
   * ONE HISTORY OVER STRUCTURE AND STYLE (plan 1.5). FAILS IF: the layout slice is left out of the
   * snapshotted draft, or gets a history of its own - either way an undo after a token edit would not
   * walk back through the arrangement edit that preceded it.
   */
  it("undoes and redoes an arrangement edit in the same history as a token edit", async () => {
    const { result } = renderHook(() => useDevMode(), { wrapper });
    expect(result.current.canUndo).toBe(false);

    act(() => result.current.setLayoutDraft(workingDraft()));
    await waitFor(() => expect(result.current.canUndo).toBe(true));
    act(() => result.current.setToken("--c-surface", "#101010"));
    await waitFor(() => expect(result.current.tokenValue("--c-surface")).toBe("#101010"));

    // One step back is the token edit; the arrangement is still the drafted one.
    act(() => result.current.undo());
    await waitFor(() => expect(result.current.tokenValue("--c-surface")).not.toBe("#101010"));
    expect(result.current.layoutDraft?.id).toBe("workspace.component.draft");

    // Two steps back is the arrangement edit.
    act(() => result.current.undo());
    await waitFor(() => expect(result.current.layoutDraft).toBeNull());

    act(() => result.current.redo());
    await waitFor(() => expect(result.current.layoutDraft?.id).toBe("workspace.component.draft"));
  });

  /**
   * FAILS IF: `emptyDraft()` stops carrying the layout slice - the mutation proven above. Reset all is
   * one action for exactly this reason: a slice that is not in that object is a slice a reset forgets.
   *
   * WHAT RESET ALL MEANS FOR AN ARRANGEMENT, stated here because it is the one place the layout slice
   * differs from the five keyed ones. Clearing the token slice means "no token overrides", so the
   * shipped stylesheet applies and a Save would commit that clear. Clearing the layout slice means
   * "NO WORKING EDIT" - and with a redesign already committed to source, no working edit is the
   * COMMITTED arrangement, not the shipped default. That is not an inconsistency to be fixed by
   * inventing a third state: undoing a committed redesign is a change to source, and since Phase 4
   * that is exactly what Reset all FOLLOWED BY SAVE does - the same two steps that revert any of the
   * five keyed slices to the shipped design. Reset alone still changes nothing on disk.
   */
  it("is cleared by Reset all alongside the other five slices", () => {
    MOCK_LAYOUT_OVERRIDES.workspace = committedRedesign();
    const { result } = renderHook(() => useDevMode(), { wrapper });
    expect(result.current.layoutDraft?.id).toBe("workspace.component.committed");

    act(() => result.current.setLayoutDraft(workingDraft()));
    act(() => result.current.setCopy("test.label", "Reworded"));
    expect(result.current.layoutDraft?.id).toBe("workspace.component.draft");

    act(() => result.current.resetAll());
    expect(result.current.layoutDraft).toBeNull();
    expect(result.current.isCopyOverridden("test.label")).toBe(false);
    // No working edit: the committed arrangement draws again, and the owner's own draft is gone.
    expect(resolveWorkspaceLayout(result.current.layoutDraft).id).toBe(
      "workspace.component.committed",
    );

    // With nothing committed, the same reset lands on the shipped default - by reference.
    MOCK_LAYOUT_OVERRIDES.workspace = null;
    const fresh = renderHook(() => useDevMode(), { wrapper });
    act(() => fresh.result.current.setLayoutDraft(workingDraft()));
    act(() => fresh.result.current.resetAll());
    expect(resolveWorkspaceLayout(fresh.result.current.layoutDraft)).toBe(DEFAULT_WORKSPACE_LAYOUT);
  });

  /**
   * SAVE CARRIES THE ARRANGEMENT (Phase 4, plan 1.6 / decision 4: a committed redesign becomes the
   * app). This test asserted the opposite through Phase 3, when the arrangement deliberately had no
   * write path and a half-wired one would have silently dropped an owner's redesign. The write path
   * now exists - `lib/devModeSave.ts` sends the layout slice and the backend writes this module - so
   * the claim inverts with it.
   *
   * FAILS IF: the layout slice falls out of the save payload, or an arrangement edit stops flipping
   * `dirty` - which would leave the owner looking at a disabled Save with a redesign in front of them.
   */
  it("is carried by Save and flips dirty", async () => {
    const { api } = await import("../api/client");
    const { result } = renderHook(() => useDevMode(), { wrapper });
    expect(result.current.dirty).toBe(false);

    act(() => result.current.setLayoutDraft(workingDraft()));
    expect(result.current.dirty).toBe(true);

    await act(async () => {
      await result.current.save();
    });
    const sent = vi.mocked(api.devSave).mock.calls[0][0];
    expect(sent.layout?.workspace?.id).toBe("workspace.component.draft");
    // The baseline moved with the write: the same document is no longer an unsaved edit.
    expect(result.current.dirty).toBe(false);
    expect(result.current.layoutDraft?.id).toBe("workspace.component.draft");
  });

  /**
   * The setters are inert with no provider, exactly as the other five slices' are.
   *
   * FAILS IF: the DEFAULT context exposes the committed override as a working draft (the resolver would
   * then apply it twice, and `isLayoutEdited` would be true with nothing edited) or throws.
   */
  it("is inert on the DEFAULT no-op context", () => {
    MOCK_LAYOUT_OVERRIDES.workspace = committedRedesign();
    const { result } = renderHook(() => useDevMode());
    expect(result.current.layoutDraft).toBeNull();
    expect(result.current.isLayoutEdited).toBe(false);
    expect(() => {
      result.current.setLayoutDraft(workingDraft());
      result.current.resetLayoutDraft();
    }).not.toThrow();
    expect(result.current.layoutDraft).toBeNull();
    // The committed arrangement still applies, because the RESOLVER reads it rather than the context.
    expect(resolveWorkspaceLayout(result.current.layoutDraft).id).toBe(
      "workspace.component.committed",
    );
  });
});
