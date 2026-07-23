import { createElement, type ReactNode } from "react";
import { render, screen, fireEvent } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { api } from "../api/client";
import type { DiffAssets } from "../api/types";
import { ThemeProvider } from "../lib/theme";
import { DevModeProvider } from "../lib/devMode";
import { DiffModal } from "./DiffModal";

const bothChanged: DiffAssets = { symbol: true, footprint: true, model: false, datasheet: false };
const onlySymbol: DiffAssets = { symbol: true, footprint: false, model: false, datasheet: false };

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

// A pending fetch keeps the diff body in its loading state, so the "Loading diff..." <Text> renders
// without a network round-trip.
function renderDiff(assets: DiffAssets) {
  return render(
    <DiffModal
      open
      partId="p1"
      partName="ExamplePart"
      a="rev1"
      b="rev2"
      assets={assets}
      onClose={() => {}}
    />,
    { wrapper },
  );
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("DiffModal - copy adoption", () => {
  it("renders both kind tabs, the Close label and the loading line as default text with no copy wrappers outside dev mode", () => {
    vi.spyOn(api, "previewSvg").mockReturnValue(new Promise<Blob>(() => {}));
    const { container } = renderDiff(bothChanged);

    expect(screen.getByRole("tab", { name: "Symbol" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Footprint" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Close" })).toBeInTheDocument();
    expect(screen.getByText("Loading diff...")).toBeInTheDocument();

    expect(container.querySelector("[data-copy-id]")).toBeNull();
  });

  it("wraps the kind tabs, Close and loading line with their modals.json ids in dev mode", () => {
    vi.spyOn(api, "previewSvg").mockReturnValue(new Promise<Blob>(() => {}));
    const { container } = renderDiff(bothChanged);

    toggleDevMode();

    expect(container.querySelector('[data-copy-id="modal.diff.kind-symbol"]')).not.toBeNull();
    expect(container.querySelector('[data-copy-id="modal.diff.kind-footprint"]')).not.toBeNull();
    expect(container.querySelector('[data-copy-id="modal.diff.close-btn"]')).not.toBeNull();
    expect(container.querySelector('[data-copy-id="modal.diff.loading"]')).not.toBeNull();

    expect(screen.getByRole("button", { name: "Close" })).toBeInTheDocument();
  });

  it("resolves the single-kind label through the same id at the non-tab call site", () => {
    vi.spyOn(api, "previewSvg").mockReturnValue(new Promise<Blob>(() => {}));
    const { container } = renderDiff(onlySymbol);

    // With one changed kind there are no tabs: the kind renders in a plain span.
    expect(screen.queryByRole("tab")).toBeNull();
    expect(screen.getByText("Symbol")).toBeInTheDocument();

    toggleDevMode();
    expect(container.querySelector('[data-copy-id="modal.diff.kind-symbol"]')).not.toBeNull();
  });
});
