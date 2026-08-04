/**
 * The modal STACK, proved on nested windows.
 *
 * This is a regression gate for a real bug, not a nicety. `DiffModal` and `WorkspaceModal` were
 * both `z-[110]` and BOTH attached their own `keydown` listener to `window`, so nesting them meant
 * one Escape ran two `onClose` handlers and closed both, and which one painted on top came down to
 * mount order. That is why the visual diff overlay in Sources & History could not be built: there
 * was nowhere safe to nest it.
 *
 * Four properties, and every one of them is what "safe to nest" actually means:
 *   - Escape closes the TOP window only.
 *   - z-index ascends with depth, so the inner window paints over the outer one.
 *   - the Tab trap follows the top window; focus cannot walk into the window underneath.
 *   - focus returns to the control that opened a window, so closing the inner one lands back
 *     INSIDE the outer one rather than on the page behind both.
 */
import { useState } from "react";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { ThemeProvider } from "./theme";
import { DevModeProvider } from "./devMode";
import { MODAL_BASE_Z, MODAL_Z_STEP, openModalCount } from "./useModalDismiss";
import { ModalShell } from "../components/primitives";

/**
 * An outer window with a control that opens an inner one: the exact shape of Sources & History
 * opening the visual diff.
 */
function Nested({
  onOuterClose = () => {},
}: {
  onOuterClose?: () => void;
}) {
  const [outer, setOuter] = useState(false);
  const [inner, setInner] = useState(false);
  return (
    <>
      <button type="button" onClick={() => setOuter(true)}>
        Open Sheet
      </button>
      <ModalShell
        open={outer}
        title="Sources & History"
        onClose={() => {
          setOuter(false);
          onOuterClose();
        }}
      >
        <button type="button" onClick={() => setInner(true)}>
          Visual Diff
        </button>
        <button type="button">Refresh Sourcing</button>
        <ModalShell
          open={inner}
          title="ExamplePart"
          size="stage"
          onClose={() => setInner(false)}
        >
          <button type="button">Symbol</button>
        </ModalShell>
      </ModalShell>
    </>
  );
}

function provide(ui: React.ReactNode) {
  return render(
    <ThemeProvider>
      <DevModeProvider>{ui}</DevModeProvider>
    </ThemeProvider>,
  );
}

/** The scrim a dialog sits in, which is where the stack's z-index lands. */
function scrimOf(dialog: HTMLElement): HTMLElement {
  return dialog.parentElement as HTMLElement;
}

async function openBoth(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByRole("button", { name: "Open Sheet" }));
  const outer = await screen.findByRole("dialog", { name: "Sources & History" });
  await user.click(within(outer).getByRole("button", { name: "Visual Diff" }));
  const inner = await screen.findByRole("dialog", { name: "ExamplePart" });
  return { outer, inner };
}

describe("nesting one modal inside another is safe", () => {
  it("closes only the TOP modal on Escape, and the outer one on the next press", async () => {
    const user = userEvent.setup();
    provide(<Nested />);
    const { outer, inner } = await openBoth(user);
    expect(openModalCount()).toBe(2);

    await user.keyboard("{Escape}");
    // The inner window goes. The sheet it was opened from is still there - which is the whole
    // bug: one press used to run both handlers.
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "ExamplePart" })).toBeNull());
    expect(outer).toBeInTheDocument();
    expect(openModalCount()).toBe(1);

    await user.keyboard("{Escape}");
    await waitFor(() =>
      expect(screen.queryByRole("dialog", { name: "Sources & History" })).toBeNull(),
    );
    expect(openModalCount()).toBe(0);
    expect(inner).not.toBeInTheDocument();
  });

  it("paints the inner modal above the outer one, by depth rather than by mount order", async () => {
    const user = userEvent.setup();
    provide(<Nested />);
    const { outer, inner } = await openBoth(user);

    const outerZ = Number(scrimOf(outer).style.zIndex);
    const innerZ = Number(scrimOf(inner).style.zIndex);
    expect(outerZ).toBe(MODAL_BASE_Z);
    expect(innerZ).toBe(MODAL_BASE_Z + MODAL_Z_STEP);
    expect(innerZ).toBeGreaterThan(outerZ);
  });

  it("moves the Tab trap to the top modal, so focus cannot walk into the one underneath", async () => {
    const user = userEvent.setup();
    provide(<Nested />);
    const { outer, inner } = await openBoth(user);

    await waitFor(() => expect(document.activeElement).toBe(inner));

    // Tab all the way round the inner window: focus stays inside it every time, and never lands
    // on the outer sheet's Refresh Sourcing control sitting behind the scrim.
    for (let i = 0; i < 6; i += 1) {
      await user.keyboard("{Tab}");
      expect(inner.contains(document.activeElement)).toBe(true);
    }
    expect(
      within(outer).getByRole("button", { name: "Refresh Sourcing" }),
    ).not.toBe(document.activeElement);
  });

  it("returns focus to the invoking control, so closing the inner modal lands back in the outer one", async () => {
    const user = userEvent.setup();
    provide(<Nested />);
    const { outer } = await openBoth(user);
    const invoker = within(outer).getByRole("button", { name: "Visual Diff" });

    await user.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "ExamplePart" })).toBeNull());

    // Back on the control that opened it, INSIDE the sheet - not on the page behind both.
    expect(document.activeElement).toBe(invoker);
    expect(outer.contains(document.activeElement)).toBe(true);
  });

  it("returns focus to the page control that opened the outer modal once both are closed", async () => {
    const user = userEvent.setup();
    provide(<Nested />);
    const opener = screen.getByRole("button", { name: "Open Sheet" });
    await openBoth(user);

    await user.keyboard("{Escape}");
    await user.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(document.activeElement).toBe(opener);
  });

  it("leaves the stack empty when a modal is unmounted while still open", async () => {
    const user = userEvent.setup();
    const { unmount } = provide(<Nested />);
    await openBoth(user);
    expect(openModalCount()).toBe(2);

    // Several windows here render only when open and never pass `open={false}`, so the stack has
    // to be left on UNMOUNT as well. A leaked layer would keep answering Escape forever.
    unmount();
    await waitFor(() => expect(openModalCount()).toBe(0));
  });
});
