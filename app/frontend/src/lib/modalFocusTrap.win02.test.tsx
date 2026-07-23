/**
 * WIN-02 proof: the z-200 DevPanel edits an OPEN modal through its z-95 focus trap.
 *
 * The AltiumDbLibModal (a [role="dialog"] with a Tab focus-trap, see useModalDismiss) is mounted as a
 * SIBLING of the DevPanel, matching the real tree where the panel lives above every modal scrim. This
 * proves the two truths from CONTEXT locked decision 4: (A) a copy edit made in the panel reaches the
 * open modal's content, and (B) the panel stays interactive and sits OUTSIDE the modal's focus trap.
 */
import { createElement, type ReactNode } from "react";
import { render, screen, fireEvent } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { api } from "../api/client";
import type { AltiumStatus } from "../api/types";
import { ToastProvider } from "./toast";
import { ThemeProvider } from "./theme";
import { DevModeProvider } from "./devMode";
import { AltiumDbLibModal } from "../components/AltiumDbLibModal";
import { DevPanel } from "../components/DevPanel";

const STATUS: AltiumStatus = {
  profile: "default",
  dblib: "Stockroom.DbLib",
  dblib_dir: "/tmp",
  ready: 0,
  total: 0,
  rows: [],
};

function wrapper({ children }: { children: ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return createElement(
    QueryClientProvider,
    { client: qc },
    createElement(
      ThemeProvider,
      null,
      createElement(DevModeProvider, null, createElement(ToastProvider, null, children)),
    ),
  );
}

function toggleDevMode() {
  fireEvent.keyDown(window, { key: "D", ctrlKey: true, shiftKey: true });
}

afterEach(() => {
  vi.restoreAllMocks();
  // Token edits set inline CSS vars on <html>; clear them so the test does not leak.
  document.documentElement.removeAttribute("style");
  document.documentElement.removeAttribute("data-theme");
});

describe("WIN-02 - the DevPanel edits an open modal through its focus trap", () => {
  it("Proof A: a panel copy edit reaches the open modal's content", async () => {
    vi.spyOn(api, "altiumStatus").mockResolvedValue(STATUS);
    const { container } = render(
      <>
        <AltiumDbLibModal open onClose={() => {}} />
        <DevPanel />
      </>,
      { wrapper },
    );
    await screen.findByText("Altium Database Library");

    toggleDevMode();

    // Click the modal's title label: in dev mode the <Text> span is click-to-select (onClickCapture).
    const title = container.querySelector('[data-copy-id="modal.altium.title"]') as HTMLElement;
    expect(title).not.toBeNull();
    fireEvent.click(title);

    // The panel's Copy editor now targets that id; retype it to a new string.
    const editor = screen.getByLabelText("Edit copy text");
    expect(editor).toHaveValue("Altium Database Library");
    fireEvent.change(editor, { target: { value: "Reworded Library" } });

    // The z-200 panel edit reached the z-95 modal content: the live title span shows the new copy.
    const liveTitle = container.querySelector('[data-copy-id="modal.altium.title"]');
    expect(liveTitle).toHaveTextContent("Reworded Library");
    expect(liveTitle).not.toHaveTextContent("Altium Database Library");
  });

  it("Proof B: the panel is interactive and outside the modal's [role=dialog] focus trap", async () => {
    vi.spyOn(api, "altiumStatus").mockResolvedValue(STATUS);
    render(
      <>
        <AltiumDbLibModal open onClose={() => {}} />
        <DevPanel />
      </>,
      { wrapper },
    );
    await screen.findByText("Altium Database Library");

    toggleDevMode();

    // The panel is a sibling of, not a descendant of, the dialog: it is outside the focus trap.
    const dialog = screen.getByRole("dialog");
    const panel = screen.getByRole("complementary", { name: "Dev mode" });
    expect(dialog.contains(panel)).toBe(false);

    // A panel control still responds while the modal is open: nudging the accent writes its inline var.
    fireEvent.change(screen.getByLabelText("Accent value"), { target: { value: "#123456" } });
    expect(document.documentElement.style.getPropertyValue("--c-acc")).toBe("#123456");
  });
});
