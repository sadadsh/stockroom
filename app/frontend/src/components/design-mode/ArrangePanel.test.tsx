/**
 * THE ARRANGE SECTION of the Design panel, over the real dev-mode draft and the real storage.
 *
 * Nothing here is stubbed: `lib/layoutDrafts.ts` writes to the jsdom `localStorage` and the panel
 * reads it back, and the draft slice is the one `DevModeProvider` really holds. A test that mocked
 * either would be asserting that this component calls functions, which is the half that is obvious;
 * what is worth proving is that the round trip lands - a draft saved is a draft that comes back as
 * the arrangement in force.
 *
 * NON-VACUITY. Each case names its killing mutation. The panel's floor in every case is that the
 * control it is about was really found and really pressed: `getByRole` throws on a missing control,
 * so a section that rendered nothing fails rather than passing over an empty scan.
 */
import { describe, it, expect, beforeEach } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { DevModeProvider, useDevMode } from "../../lib/devMode";
import { ThemeProvider } from "../../lib/theme";
import {
  LAYOUT_DRAFTS_STORAGE_KEY,
  listLayoutDrafts,
  saveLayoutDraft,
} from "../../lib/layoutDrafts";
import { DEFAULT_WORKSPACE_LAYOUT } from "../../layout/defaultWorkspaceLayout";
import { layoutPlacements, type LayoutDocument } from "../../layout/document";
import { setPlacementHidden, setPlacementCollapsed } from "../../layout/editOperations";
import { resolveWorkspaceLayout } from "../../layout/resolveWorkspaceLayout";
import { ArrangeSection } from "./ArrangePanel";

const HIDDEN_PLACEMENT = "workspace.place.sourcing-documents";
const COLLAPSED_PLACEMENT = "workspace.place.sourcing-official-api";

/** The shipped arrangement with one section off the screen each way. */
function editedDocument(): LayoutDocument {
  return setPlacementCollapsed(
    setPlacementHidden(DEFAULT_WORKSPACE_LAYOUT, { placement: HIDDEN_PLACEMENT }, true),
    { placement: COLLAPSED_PLACEMENT },
    true,
  );
}

/** A different arrangement, so "the draft that came back" is distinguishable from "the default". */
function otherDocument(): LayoutDocument {
  return setPlacementHidden(
    DEFAULT_WORKSPACE_LAYOUT,
    { placement: "workspace.place.sourcing-related" },
    true,
  );
}

function offScreenIds(document_: LayoutDocument): string[] {
  return layoutPlacements(document_)
    .filter((visit) => visit.node.hidden === true || visit.node.collapsed === true)
    .map((visit) => visit.node.id);
}

function Panel() {
  const dev = useDevMode();
  const [open, setOpen] = useState(true);
  return (
    <>
      <button data-testid="edit" onClick={() => dev.setLayoutDraft(editedDocument())} />
      <output data-testid="off-screen">
        {offScreenIds(resolveWorkspaceLayout(dev.layoutDraft)).join(" ")}
      </output>
      <output data-testid="draft">{dev.layoutDraft === null ? "none" : "held"}</output>
      <ArrangeSection open={open} setOpen={setOpen} />
    </>
  );
}

function mount() {
  return render(
    <ThemeProvider>
      <DevModeProvider>
        <Panel />
      </DevModeProvider>
    </ThemeProvider>,
  );
}

beforeEach(() => {
  window.localStorage.clear();
});

/* -------------------------------------------------------------------------- */

describe("the Arrange section states what the arrangement is", () => {
  /**
   * FAILS IF: the state line reads the draft's CONTENT rather than whether there is one - a redesign
   * that happens to look like the shipped arrangement is still an edit, and one that has not been
   * made is not.
   */
  it("says whether an edit is in force, and reverts to what is committed", () => {
    mount();
    expect(screen.getByTestId("draft").textContent).toBe("none");
    expect(screen.getByRole("button", { name: /Reset To Applied/ })).toBeDisabled();

    fireEvent.click(screen.getByTestId("edit"));
    expect(screen.getByTestId("draft").textContent).toBe("held");
    const reset = screen.getByRole("button", { name: /Reset To Applied/ });
    expect(reset).not.toBeDisabled();

    fireEvent.click(reset);
    expect(screen.getByTestId("draft").textContent).toBe("none");
  });

  /**
   * THE ON SWITCH FOR AN OFF SWITCH. Hiding a piece removes the only surface its handle could hang
   * off, so without this list a hidden piece is unreachable from the canvas by construction.
   *
   * FAILS IF: the list reads only `hidden` and not `collapsed` (or the other way round), or Restore
   * clears one setting and leaves the other - a piece that is both is still not on the screen.
   */
  it("lists every piece that is off the screen, whichever setting put it there", () => {
    mount();
    expect(screen.getByText(/Nothing is off screen/)).toBeTruthy();

    fireEvent.click(screen.getByTestId("edit"));
    expect(screen.getByTestId("off-screen").textContent?.split(" ").sort()).toEqual(
      [COLLAPSED_PLACEMENT, HIDDEN_PLACEMENT].sort(),
    );
    const restores = screen.getAllByRole("button", { name: "Restore" });
    expect(restores).toHaveLength(2);

    fireEvent.click(restores[0]);
    fireEvent.click(screen.getAllByRole("button", { name: "Restore" })[0]);
    expect(screen.getByTestId("off-screen").textContent).toBe("");
  });
});

describe("named local drafts", () => {
  /**
   * FAILS IF: the panel saves the DRAFT SLICE rather than the arrangement in force - an owner who
   * has edited nothing and saves a draft means "the arrangement as it is", and a `null` slice is not
   * a document. PROVEN by saving `dev.layoutDraft`: the save silently stored nothing.
   */
  it("stores the arrangement in force, even before anything has been edited", () => {
    mount();
    fireEvent.change(screen.getByRole("textbox", { name: "Draft Name" }), {
      target: { value: "  wide sourcing  " },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save Draft" }));

    const stored = listLayoutDrafts();
    expect(stored.map((entry) => entry.name)).toEqual(["wide sourcing"]);
    expect(stored[0].documentId).toBe(DEFAULT_WORKSPACE_LAYOUT.id);
    // The field clears, so the next save is a decision rather than an accidental overwrite.
    expect(screen.getByRole("textbox", { name: "Draft Name" })).toHaveValue("");
  });

  /**
   * FAILS IF: Load writes the stored document somewhere other than the working draft, so the
   * workspace keeps drawing what it drew. The arrangement in force is read back, which is what the
   * renderer resolves.
   */
  it("loads a stored arrangement into the working draft", () => {
    saveLayoutDraft("sourcing left", otherDocument());
    mount();
    expect(screen.getByTestId("draft").textContent).toBe("none");

    fireEvent.click(screen.getByRole("button", { name: "Load" }));
    expect(screen.getByTestId("draft").textContent).toBe("held");
    expect(screen.getByTestId("off-screen").textContent).toBe("workspace.place.sourcing-related");
  });

  it("forgets a draft, and says so when a draft cannot be read", () => {
    saveLayoutDraft("one", otherDocument());
    saveLayoutDraft("two", otherDocument());
    mount();
    expect(screen.getAllByRole("button", { name: "Delete" })).toHaveLength(2);

    fireEvent.click(screen.getAllByRole("button", { name: "Delete" })[0]);
    expect(listLayoutDrafts().map((entry) => entry.name)).toHaveLength(1);
    expect(screen.getAllByRole("button", { name: "Delete" })).toHaveLength(1);

    // Storage overwritten by something else entirely: the list empties and the panel says the read
    // failed rather than pretending the draft is still there.
    window.localStorage.setItem(LAYOUT_DRAFTS_STORAGE_KEY, "not json");
    fireEvent.click(screen.getAllByRole("button", { name: "Delete" })[0]);
    expect(screen.getByRole("alert").textContent).toMatch(/did not store that draft/);
    expect(screen.getByText(/No drafts on this machine/)).toBeTruthy();
  });
});
