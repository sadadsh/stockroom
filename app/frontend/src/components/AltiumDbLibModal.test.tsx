import { createElement, type ReactNode } from "react";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { api } from "../api/client";
import type { AltiumStatus } from "../api/types";
import { ToastProvider } from "../lib/toast";
import { ThemeProvider } from "../lib/theme";
import { DevModeProvider } from "../lib/devMode";
import { AltiumDbLibModal } from "./AltiumDbLibModal";

// One ready row and one not-ready row: the not-ready row renders the Attach button (and its upload
// glyph), so both the Close and the Attach icons are on screen for the "an svg per icon" assertion.
const STATUS: AltiumStatus = {
  profile: "default",
  dblib: "Stockroom.DbLib",
  dblib_dir: "/tmp",
  ready: 1,
  total: 2,
  rows: [
    {
      id: "r1",
      display_name: "BQ24074",
      category: "IC",
      mpn: "BQ24074",
      value: "",
      symbol: "BQ24074",
      footprint: "SON-16",
      ready: true,
    },
    {
      id: "r2",
      display_name: "R_0603",
      category: "Resistor",
      mpn: "RC0603",
      value: "10k",
      symbol: "R",
      footprint: "R_0603",
      ready: false,
    },
  ],
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
  // Token edits set inline CSS vars on <html>; clear them so tests do not leak into each other.
  document.documentElement.removeAttribute("style");
  document.documentElement.removeAttribute("data-theme");
});

describe("AltiumDbLibModal - copy + icon adoption", () => {
  it("renders identical text and a glyph per icon, with no copy wrappers outside dev mode", async () => {
    vi.spyOn(api, "altiumStatus").mockResolvedValue(STATUS);
    const { container } = render(<AltiumDbLibModal open onClose={() => {}} />, { wrapper });

    // The title resolves to its default text (no override), and the not-ready row's Attach action
    // is present, so both the Close and Upload glyphs render.
    expect(await screen.findByText("Altium Database Library")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole("button", { name: "Attach Files" })).toBeInTheDocument());

    // Close glyph + Attach glyph both draw as <svg> (via <Icon>).
    expect(container.querySelectorAll("svg").length).toBeGreaterThanOrEqual(2);

    // Off dev mode a <Text> is a bare string with no wrapper: no editable copy targets exist.
    expect(container.querySelector("[data-copy-id]")).toBeNull();
  });

  it("wraps every label as an editable data-copy-id target in dev mode", async () => {
    vi.spyOn(api, "altiumStatus").mockResolvedValue(STATUS);
    const { container } = render(<AltiumDbLibModal open onClose={() => {}} />, { wrapper });
    await screen.findByText("Altium Database Library");

    toggleDevMode();

    // The visible <Text> labels carry their modals.json ids: the title, every table header, the
    // status cell, and the Attach label of the not-ready row.
    expect(container.querySelector('[data-copy-id="modal.altium.title"]')).not.toBeNull();
    expect(container.querySelector('[data-copy-id="modal.altium.th-part"]')).not.toBeNull();
    expect(container.querySelector('[data-copy-id="modal.altium.th-mpn"]')).not.toBeNull();
    expect(container.querySelector('[data-copy-id="modal.altium.th-status"]')).not.toBeNull();
    expect(container.querySelector('[data-copy-id="modal.altium.status-ready"]')).not.toBeNull();
    expect(container.querySelector('[data-copy-id="modal.altium.attach-files"]')).not.toBeNull();

    // The filter words go through useText (a SegmentedControl option label must be a string, so it
    // cannot host a <Text> node), so they resolve as text but carry no data-copy-id wrapper.
    expect(container.querySelector('[data-copy-id="modal.altium.filter-all"]')).toBeNull();
  });

  it("keeps the Close button's accessible name resolved through useText", async () => {
    vi.spyOn(api, "altiumStatus").mockResolvedValue(STATUS);
    render(<AltiumDbLibModal open onClose={() => {}} />, { wrapper });
    await screen.findByText("Altium Database Library");

    // useText(modal.altium.close, "Close") resolves the label whether or not dev mode is on.
    expect(screen.getByRole("button", { name: "Close" })).toBeInTheDocument();
    toggleDevMode();
    expect(screen.getByRole("button", { name: "Close" })).toBeInTheDocument();
  });
});
