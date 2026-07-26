import { createElement, type ReactNode } from "react";
import { render, screen, fireEvent } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { api } from "../api/client";
import { ThemeProvider } from "../lib/theme";
import { DevModeProvider } from "../lib/devMode";
import { PreviewModal, type PreviewKind } from "./PreviewModal";

const available: Record<PreviewKind, boolean> = { model: true, symbol: true, footprint: true };

function wrapper({ children }: { children: ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return createElement(
    QueryClientProvider,
    { client: qc },
    createElement(ThemeProvider, null, createElement(DevModeProvider, null, children)),
  );
}

function toggleDevMode() {
  fireEvent.keyDown(window, { key: "D", ctrlKey: true, shiftKey: true });
}

// initialKind=symbol renders the SvgPreview body; a pending fetch keeps it in its loading state so
// the "Loading preview..." <Text> is on screen without a network round-trip.
function renderPreview() {
  return render(
    <PreviewModal
      open
      partId="p1"
      partName="ExamplePart"
      available={available}
      initialKind="symbol"
      onClose={() => {}}
    />,
    { wrapper },
  );
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("PreviewModal - copy adoption", () => {
  it("renders its tab, close and loading strings as default text with no copy wrappers outside dev mode", () => {
    vi.spyOn(api, "previewSvg").mockReturnValue(new Promise<Blob>(() => {}));
    const { container } = renderPreview();

    expect(screen.getByRole("tab", { name: "3D Model" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Symbol" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Footprint" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Close" })).toBeInTheDocument();
    expect(screen.getByText("Loading preview...")).toBeInTheDocument();

    // Off dev mode a <Text> is a bare string: no editable copy targets exist.
    expect(container.querySelector("[data-copy-id]")).toBeNull();
  });

  it("wraps every tab label, the Close label and the loading line with their modals.json ids in dev mode", () => {
    vi.spyOn(api, "previewSvg").mockReturnValue(new Promise<Blob>(() => {}));
    const { container } = renderPreview();

    toggleDevMode();

    expect(container.querySelector('[data-copy-id="modal.preview.tab-model"]')).not.toBeNull();
    expect(container.querySelector('[data-copy-id="modal.preview.tab-symbol"]')).not.toBeNull();
    expect(container.querySelector('[data-copy-id="modal.preview.tab-footprint"]')).not.toBeNull();
    expect(container.querySelector('[data-copy-id="modal.preview.close-btn"]')).not.toBeNull();
    expect(container.querySelector('[data-copy-id="modal.preview.loading"]')).not.toBeNull();

    // The tablist + Close aria-labels resolve through useText (string form, no wrapper), so the
    // Close button keeps its accessible name.
    expect(screen.getByRole("button", { name: "Close" })).toBeInTheDocument();
  });
});
