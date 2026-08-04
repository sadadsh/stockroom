import { createElement, type ReactNode } from "react";
import { render, screen, fireEvent } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { api } from "../api/client";
import { ThemeProvider } from "../lib/theme";
import { DevModeProvider } from "../lib/devMode";
import { PreviewModal } from "./PreviewModal";

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
  it("gives the inspection stage nearly the full application window", () => {
    vi.spyOn(api, "previewSvg").mockReturnValue(new Promise<Blob>(() => {}));
    const { container } = renderPreview();
    const dialog = container.querySelector('[data-dev-id="preview.root"]');

    expect(dialog).toHaveClass(
      "h-[calc(100vh-24px)]",
      "w-[calc(100vw-24px)]",
      "max-w-[1600px]",
      "max-h-[1100px]",
    );
    expect(container.querySelector('[data-dev-id="preview.stage"]')).toHaveClass("flex-1");
  });

  it("renders only the clicked viewer, close, and loading text outside dev mode", () => {
    vi.spyOn(api, "previewSvg").mockReturnValue(new Promise<Blob>(() => {}));
    const { container } = renderPreview();

    expect(screen.getByText("Symbol")).toBeInTheDocument();
    expect(screen.queryByRole("tab")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Close" })).toBeInTheDocument();
    expect(screen.getByText("Loading this preview...")).toBeInTheDocument();

    // Off dev mode a <Text> is a bare string: no editable copy targets exist.
    expect(container.querySelector("[data-copy-id]")).toBeNull();
  });

  it("wraps the loading line with its modals.json id in dev mode, and names the close control", () => {
    vi.spyOn(api, "previewSvg").mockReturnValue(new Promise<Blob>(() => {}));
    const { container } = renderPreview();

    toggleDevMode();

    expect(container.querySelector('[data-copy-id="modal.preview.loading"]')).not.toBeNull();

    // Close is the shared frame's icon control: its copy lives in the accessible name and
    // resolves through useText, which is the repo's rule for copy inside an attribute.
    expect(screen.getByRole("button", { name: "Close" })).toBeInTheDocument();
  });
});
