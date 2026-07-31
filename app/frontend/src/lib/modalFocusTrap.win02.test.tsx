/**
 * WIN-02 proof: the z-200 DevPanel edits an OPEN modal through its z-95 focus trap.
 *
 * The AltiumDbLibModal (a [role="dialog"] with a Tab focus-trap, see useModalDismiss) is mounted as a
 * SIBLING of the DevPanel, matching the real tree where the panel lives above every modal scrim. This
 * proves the two truths from CONTEXT locked decision 4: (A) a copy edit made in the panel reaches the
 * open modal's content, and (B) the panel stays interactive and sits OUTSIDE the modal's focus trap.
 *
 * The CompletePartModal is proved here too. It is the window this contract most needed and least
 * had: it declared `role="dialog" aria-modal` while importing `useModalDismiss` zero times, so it
 * shipped with no Escape, no Tab trap, and no focus restore while seven siblings had all three.
 * Testing only the Altium viewer is what let that pass unnoticed, so both windows run the same two
 * proofs, and the Complete Part window additionally proves the dismissal contract itself.
 */
import { createElement, type ReactNode } from "react";
import { render, screen, fireEvent } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { api } from "../api/client";
import type { AltiumStatus, PartDetail } from "../api/types";
import { makeEdaAssets, makePartDetail } from "../test/partFixture";
import { ToastProvider } from "./toast";
import { ThemeProvider } from "./theme";
import { DevModeProvider } from "./devMode";
import { CaptureProvider } from "./capture";
import { AltiumDbLibModal } from "../components/AltiumDbLibModal";
import { CompletePartModal } from "../components/CompletePartModal";
import { DevPanel } from "../components/DevPanel";

const STATUS: AltiumStatus = {
  profile: "default",
  dblib: "Stockroom.DbLib",
  dblib_dir: "/tmp",
  datasource_present: true,
  ready: 0,
  total: 0,
  rows: [],
};

const PART: PartDetail = makePartDetail({
  id: "part1",
  mpn: "BQ24074",
  manufacturer: "Texas Instruments",
  derived: { display_name: "BQ24074", category: "ICs", description: "Li-Ion charger" },
  assets: { kicad: makeEdaAssets() },
});

// The Complete Part window drives the global capture store, so CaptureProvider joins the harness.
// It is inert for the Altium viewer and keeps both windows on one wrapper.
function wrapper({ children }: { children: ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return createElement(
    QueryClientProvider,
    { client: qc },
    createElement(
      ThemeProvider,
      null,
      createElement(
        DevModeProvider,
        null,
        createElement(CaptureProvider, null, createElement(ToastProvider, null, children)),
      ),
    ),
  );
}

function mockCadSource() {
  vi.spyOn(api, "partCadSource").mockResolvedValue({
    url: "https://www.digikey.com/en/products/result?keywords=BQ24074",
    mpn: "BQ24074",
    vendor: "DigiKey",
    needs: ["kicad_symbol"],
    sources: [],
  } as never);
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

describe("WIN-02 - the DevPanel edits the open Complete Part window through its focus trap", () => {
  it("Proof A: a panel copy edit reaches the open window's content", async () => {
    mockCadSource();
    const { container } = render(
      <>
        <CompletePartModal detail={PART} hasModel={true} onClose={() => {}} />
        <DevPanel />
      </>,
      { wrapper },
    );
    await screen.findByText("Automatic Completion");

    toggleDevMode();

    // Click the window's subtitle: in dev mode the <Text> span is click-to-select (onClickCapture).
    const subtitle = container.querySelector(
      '[data-copy-id="modal.completePart.subtitle"]',
    ) as HTMLElement;
    expect(subtitle).not.toBeNull();
    fireEvent.click(subtitle);

    const editor = screen.getByLabelText("Edit copy text");
    expect(editor).toHaveValue(
      "Stockroom completes remaining data and one verified KiCad + Altium + STEP package.",
    );
    fireEvent.change(editor, { target: { value: "Reworded Completion Subtitle" } });

    const liveSubtitle = container.querySelector('[data-copy-id="modal.completePart.subtitle"]');
    expect(liveSubtitle).toHaveTextContent("Reworded Completion Subtitle");
  });

  it("Proof B: the panel is interactive and outside the window's [role=dialog] focus trap", async () => {
    mockCadSource();
    render(
      <>
        <CompletePartModal detail={PART} hasModel={true} onClose={() => {}} />
        <DevPanel />
      </>,
      { wrapper },
    );
    await screen.findByText("Automatic Completion");

    toggleDevMode();

    const dialog = screen.getByRole("dialog", { name: "Complete this part" });
    const panel = screen.getByRole("complementary", { name: "Dev mode" });
    expect(dialog.contains(panel)).toBe(false);

    fireEvent.change(screen.getByLabelText("Accent value"), { target: { value: "#654321" } });
    expect(document.documentElement.style.getPropertyValue("--c-acc")).toBe("#654321");
  });

  it("Proof C: the window that had no dismissal contract now honours Escape and traps Tab", async () => {
    mockCadSource();
    const onClose = vi.fn();
    render(<CompletePartModal detail={PART} hasModel={true} onClose={onClose} />, { wrapper });
    const dialog = await screen.findByRole("dialog", { name: "Complete this part" });

    // The hook moves focus into the dialog, keeps Tab inside it, and answers Escape - the exact
    // three the Altium viewer above has had all along.
    expect(dialog).toHaveFocus();
    const focusable = dialog.querySelectorAll<HTMLElement>(
      'button:not([disabled]), [href], input:not([disabled]), [tabindex]:not([tabindex="-1"])',
    );
    focusable[focusable.length - 1].focus();
    fireEvent.keyDown(window, { key: "Tab" });
    expect(focusable[0]).toHaveFocus();

    fireEvent.keyDown(window, { key: "Escape" });
    expect(onClose).toHaveBeenCalled();
  });
});
