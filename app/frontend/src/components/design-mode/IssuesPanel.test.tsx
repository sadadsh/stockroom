/**
 * THE ISSUES SECTION, over the real dev-mode draft and the real validator.
 *
 * Nothing is stubbed. The document is the shipped `DEFAULT_WORKSPACE_LAYOUT` resolved by
 * `resolveWorkspaceLayout`, the registry is `WORKSPACE_PIECE_REGISTRY`, the palettes are built from
 * `lib/devTokens.ts`, and the edits go through the same two paths the application uses: the layout
 * slice for an arrangement change and `setToken` for a colour. A test that handed the section a list
 * of issues would prove that a component renders an array; what is worth proving is that an EDIT
 * MADE IN THE EDITOR turns into a row and that undoing it takes the row away.
 *
 * --- THE ANCHOR -----------------------------------------------------------------------------------
 *
 * `validateDocument.test.ts` holds it at the validator: the shipped document over the shipped
 * registry with the shipped tokens produces NOTHING. This file holds the same claim at the surface,
 * which is what makes every case below a consequence of an edit rather than of a pre-existing warning
 * that happened to be there.
 *
 * --- HOW THE CHAIN IS COVERED, and where the seam is -----------------------------------------------
 *
 * The style-role case drives `setPlacementStyleRole` - the exact function the piece menu's control
 * calls - into the draft, and reads the exception back out of the rendered list. That the MENU calls
 * that function with the placement it was opened on is the neighbouring claim, asserted in
 * `ArrangeSurface.test.tsx` against the same operation. The two files share one pure function, which
 * is the seam and is stated rather than hidden.
 *
 * --- NON-VACUITY ----------------------------------------------------------------------------------
 *
 * Each case names its killing mutation, and every one of them starts from a list that is EMPTY, so a
 * section that rendered every issue it could imagine would fail the anchor before it reached them.
 */
import { describe, it, expect } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { DevModeProvider, useDevMode } from "../../lib/devMode";
import { ThemeProvider } from "../../lib/theme";
import { setPlacementHidden, setPlacementStyleRole } from "../../layout/editOperations";
import { resolveWorkspaceLayout } from "../../layout/resolveWorkspaceLayout";
import { devTokenValues } from "../../layout/validateContrast";
import { IssuesSection } from "./IssuesPanel";

/** A placement of a piece the registry knows, so a row can resolve to a dev id. */
const CAD_TITLE = "workspace.place.cad-title";
/** The first dev id `workspace.cad-title-strip` declares - what a row's click has to select. */
const CAD_TITLE_DEV_ID = "component-browser.column-cad";
/** Hiding this takes fourteen commands off the screen with it. */
const HEADER_ACTIONS = "workspace.place.header-actions";

/**
 * The label tier, set to the exact colour of the band it is drawn on: a ratio of 1.0 against a floor
 * of 4.5. Read out of the token defaults rather than written as a hex, so this stays a broken PAIRING
 * even if the palette moves.
 */
const BAND_DARK = devTokenValues("dark")["--c-band"];

function Harness() {
  const dev = useDevMode();
  const [open, setOpen] = useState(true);
  const layout = resolveWorkspaceLayout(dev.layoutDraft);
  return (
    <>
      <button
        data-testid="break-contrast"
        onClick={() => dev.setToken("--c-t3", BAND_DARK)}
      />
      <button data-testid="fix-contrast" onClick={() => dev.resetToken("--c-t3")} />
      <button
        data-testid="scope-role"
        onClick={() =>
          dev.setLayoutDraft(
            setPlacementStyleRole(layout, { placement: CAD_TITLE }, "sectionTitle", "sourceText"),
          )
        }
      />
      <button
        data-testid="clear-role"
        onClick={() =>
          dev.setLayoutDraft(
            setPlacementStyleRole(layout, { placement: CAD_TITLE }, "sectionTitle", null),
          )
        }
      />
      <button
        data-testid="hide-actions"
        onClick={() =>
          dev.setLayoutDraft(setPlacementHidden(layout, { placement: HEADER_ACTIONS }, true))
        }
      />
      <output data-testid="edit-mode">{dev.editMode ? "on" : "off"}</output>
      <output data-testid="selected">{dev.selectedDevId ?? "none"}</output>
      <IssuesSection open={open} setOpen={setOpen} />
    </>
  );
}

function mount() {
  return render(
    <ThemeProvider>
      <DevModeProvider>
        <Harness />
      </DevModeProvider>
    </ThemeProvider>,
  );
}

/** Every row currently in the list, as its issue code. */
function rowCodes(): string[] {
  return [...document.querySelectorAll<HTMLElement>('[data-dev-id="design.issue"]')].map(
    (node) => node.dataset.issueCode ?? "",
  );
}

/** The rows carrying one code, as elements, so a case can read a subject or press one. */
function rowsFor(code: string): HTMLElement[] {
  return [...document.querySelectorAll<HTMLElement>(`[data-issue-code="${code}"]`)];
}

/* -------------------------------------------------------------------------- */

describe("the issues list without an edit", () => {
  /**
   * THE ANCHOR AT THE SURFACE, and the plan-1.4 claim that the list "stays inspectable outside it":
   * arrange is OFF here and the section is still mounted and still reporting.
   *
   * FAILS IF: the section is gated on `editMode` (it renders nothing at all, and every case below
   * fails with it), or the list is seeded with anything the arrangement did not produce.
   */
  it("reports nothing, with arrange switched off", () => {
    mount();
    expect(screen.getByTestId("edit-mode").textContent).toBe("off");
    expect(screen.getByText("Nothing to report")).toBeTruthy();
    expect(rowCodes()).toEqual([]);
    // The count is drawn on the header, so a collapsed section still says whether it is worth
    // opening: warnings first, notes second.
    expect(screen.getByText("0 / 0")).toBeTruthy();
  });
});

describe("a live token edit", () => {
  /**
   * THE MANDATORY PROOF, and the one that says this list is LIVE rather than a picture of what
   * shipped: a colour nudged in the panel breaks a pairing, the warning appears, the colour is put
   * back, and the warning goes.
   *
   * FAILS IF: the section measures `shippedThemeTokens()` instead of `draftThemeTokens(...)` over
   * the token slice - the list then stays empty through both presses, which is the whole failure
   * mode this case exists for. PROVEN by swapping the call: both halves fail, the first on an empty
   * list and the second on the list never having filled.
   *
   * ALSO FAILS IF: the memo's dependency list drops `tokenOverrides`, in which case the first press
   * changes nothing on screen.
   */
  it("shows the contrast warning it caused, and clears it when the colour goes back", () => {
    mount();
    expect(rowCodes()).toEqual([]);

    fireEvent.click(screen.getByTestId("break-contrast"));
    const failing = rowsFor("contrast-below-text-floor");
    expect(failing.length).toBeGreaterThan(0);
    // The row is about the pairing that broke, in the theme it broke in.
    const subjects = failing.map((node) => node.textContent ?? "");
    expect(subjects.some((text) => text.includes("dark:--c-t3:--c-band"))).toBe(true);
    // And it carries the measurement, so the row is a finding rather than a label.
    expect(subjects.some((text) => text.includes("ratio=1"))).toBe(true);

    fireEvent.click(screen.getByTestId("fix-contrast"));
    expect(rowCodes()).toEqual([]);
    expect(screen.getByText("Nothing to report")).toBeTruthy();
  });

  /**
   * BOTH THEMES OUT OF ONE DRAFT. A colour is stored per theme, and the one being looked at is not
   * the one an edit can break - so the light palette has to be measured from its own defaults while
   * the dark block carries the edit.
   *
   * FAILS IF: `draftThemeTokens` applies the active theme's block to both palettes, which would
   * report the same pairing failing in light theme as well - a row for a colour nobody set.
   */
  it("leaves the other theme's palette at its defaults", () => {
    mount();
    fireEvent.click(screen.getByTestId("break-contrast"));
    const subjects = rowsFor("contrast-below-text-floor").map((node) => node.textContent ?? "");
    expect(subjects.some((text) => text.includes("dark:--c-t3:--c-band"))).toBe(true);
    expect(subjects.some((text) => text.includes("light:--c-t3:--c-band"))).toBe(false);
  });
});

describe("a style role scoped to one placement", () => {
  /**
   * THE TRACKED EXCEPTION, end to end through the surface. Plan 1.5 makes "only here" a RECORDED
   * exception, and the record is the document itself - so writing one has to make a row appear, and
   * dropping it has to take the row away, with nothing in between remembering anything.
   *
   * FAILS IF: the section resolves the shipped default instead of the working draft - the row never
   * appears at all. PROVEN by passing `null` to `resolveWorkspaceLayout`: this case, the one below it
   * and the reachability case all fail on an empty list.
   *
   * The neighbouring hazard - `setPlacementStyleRole` leaving `styleRoles: {}` behind on the clear -
   * is NOT caught here, and saying so is the point of naming mutations: `validateDocument` reads an
   * empty object as no exception, so the row would still go and only the DOCUMENT would be wrong.
   * That one is caught in `editOperations.test.ts`, where the placement's own keys are read.
   */
  it("appears as a note while it is in force, and goes when it is dropped", () => {
    mount();
    expect(rowCodes()).toEqual([]);

    fireEvent.click(screen.getByTestId("scope-role"));
    expect(rowCodes()).toEqual(["style-role-exception"]);
    const row = rowsFor("style-role-exception")[0];
    expect(row.textContent).toContain(CAD_TITLE);
    expect(row.textContent).toContain("roles=sectionTitle");
    // Informational, not a warning: the header counts it on the right of the slash.
    expect(screen.getByText("0 / 1")).toBeTruthy();

    fireEvent.click(screen.getByTestId("clear-role"));
    expect(rowCodes()).toEqual([]);
  });

  /**
   * FAILS IF: the row resolves the SUBJECT id straight into `selectDevId` - a placement id is not a
   * dev id and nothing in the panel would answer to it - or the manifest lookup takes any dev id
   * other than the piece's own first one.
   */
  it("points the inspector at the piece the exception is on", () => {
    mount();
    fireEvent.click(screen.getByTestId("scope-role"));
    expect(screen.getByTestId("selected").textContent).toBe("none");

    fireEvent.click(rowsFor("style-role-exception")[0]);
    expect(screen.getByTestId("selected").textContent).toBe(CAD_TITLE_DEV_ID);
  });
});

describe("an arrangement that takes commands off the screen", () => {
  /**
   * The plan's canonical warning, reached the way an owner reaches it. An action names nothing
   * placed, so its row has nothing to select and says so by being inert rather than by selecting
   * something adjacent.
   *
   * FAILS IF: every row is clickable regardless of subject kind, which would hand `selectDevId` an
   * action id and empty the Selection pane; or the reachability layer is dropped from the section's
   * call, in which case hiding the header actions reports nothing at all.
   */
  it("warns that the hidden commands are unreachable, and those rows select nothing", () => {
    mount();
    fireEvent.click(screen.getByTestId("hide-actions"));

    const unreachable = rowsFor("action-unreachable");
    expect(unreachable.length).toBeGreaterThan(5);
    for (const row of unreachable) expect(row).toBeDisabled();

    fireEvent.click(unreachable[0]);
    expect(screen.getByTestId("selected").textContent).toBe("none");
  });
});
