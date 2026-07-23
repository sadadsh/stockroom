import { render, screen, fireEvent } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ThemeProvider } from "../lib/theme";
import { DevModeProvider } from "../lib/devMode";
import { Text } from "../lib/copy";
import { DevPanel } from "./DevPanel";
import { DevInspector } from "./DevInspector";
import { Icon } from "./Icon";

vi.mock("../api/client", async (importActual) => {
  const actual = await importActual<typeof import("../api/client")>();
  return {
    ...actual,
    api: {
      ...actual.api,
      devSave: vi.fn().mockResolvedValue({ ok: true, written: [], tokens: 0, copy: 0 }),
    },
  };
});

// jsdom does not implement scrollIntoView; install a mock so the locate/flash path is observable.
const scrollIntoViewMock = vi.fn();
beforeEach(() => {
  scrollIntoViewMock.mockClear();
  HTMLElement.prototype.scrollIntoView = scrollIntoViewMock;
});

afterEach(() => {
  document.documentElement.removeAttribute("style");
  document.documentElement.removeAttribute("data-theme");
});

// The app-side fixtures the inspector can point at: a bg-acc text-t1 element (two colour tokens) and
// an element carrying copy (its <Text> gives it a data-copy-id). Both are catalogue-addressable.
function Harness() {
  return (
    <ThemeProvider>
      <DevModeProvider>
        <button type="button" data-dev-id="detail.complete-part" className="bg-acc text-t1">
          Complete Part
        </button>
        <div data-dev-id="detail.title" className="text-t1">
          <Text id="detail.title.copy">Original Title</Text>
        </div>
        <button type="button" data-dev-id="rail.tab.components" aria-label="Components tab" className="text-t1">
          <Icon id="nav.components" />
        </button>
        <DevPanel />
        <DevInspector />
      </DevModeProvider>
    </ThemeProvider>
  );
}

function toggleDevMode() {
  fireEvent.keyDown(window, { key: "D", ctrlKey: true, shiftKey: true });
}

function clickButton(label: string) {
  fireEvent.click(screen.getByRole("button", { name: label }));
}

// Turn Inspect on, then inspect-click the given element (its closest [data-dev-id] is selected).
function inspectClick(el: Element) {
  clickButton("Inspect");
  fireEvent.click(el);
}

describe("DevPanel inspect-first shell", () => {
  it("with NO selection the Tokens tab shows the full grouped editable list", () => {
    render(<Harness />);
    toggleDevMode();
    // A representative row from each token group is present (nothing is scoped away).
    expect(screen.getByLabelText("Accent value")).toBeInTheDocument();
    expect(screen.getByLabelText("Card radius slider")).toBeInTheDocument();
    expect(screen.getByLabelText("Icon stroke value")).toBeInTheDocument();
    expect(screen.getByLabelText("Card shadow")).toBeInTheDocument();
  });

  it("selecting a bg-acc text-t1 element scopes the Tokens tab, and Show All restores the full list", () => {
    render(<Harness />);
    toggleDevMode();
    inspectClick(screen.getByRole("button", { name: "Complete Part" }));

    // Scoped: the element's used colour tokens are shown, unrelated tokens are hidden.
    expect(screen.getByLabelText("Accent value")).toBeInTheDocument();
    expect(screen.getByLabelText("Text value")).toBeInTheDocument();
    expect(screen.queryByLabelText("Card radius slider")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Icon stroke value")).not.toBeInTheDocument();

    // Show All falls back to the full grouped list.
    fireEvent.click(screen.getByRole("button", { name: "Show All" }));
    expect(screen.getByLabelText("Card radius slider")).toBeInTheDocument();
    expect(screen.getByLabelText("Icon stroke value")).toBeInTheDocument();
  });

  it("editing a scoped token still edits the GLOBAL token (no capability lost)", () => {
    render(<Harness />);
    toggleDevMode();
    inspectClick(screen.getByRole("button", { name: "Complete Part" }));

    fireEvent.change(screen.getByLabelText("Accent value"), { target: { value: "#0a0b0c" } });
    expect(document.documentElement.style.getPropertyValue("--c-acc")).toBe("#0a0b0c");
  });

  it("the Copy tab edits the selected element's copy id, updating the global copy", () => {
    render(<Harness />);
    toggleDevMode();
    inspectClick(screen.getByText("Original Title")); // closest [data-dev-id] is detail.title

    fireEvent.click(screen.getByRole("tab", { name: "Copy" }));
    const editor = screen.getByLabelText("Edit copy text");
    expect(editor).toHaveValue("Original Title");

    fireEvent.change(editor, { target: { value: "Reworded Title" } });
    const label = document.querySelector('[data-copy-id="detail.title.copy"]');
    expect(label).toHaveTextContent("Reworded Title");
  });

  it("a direct <Text> click still selects the copy and surfaces the Copy tab", () => {
    render(<Harness />);
    toggleDevMode();
    fireEvent.click(screen.getByText("Original Title")); // inspect OFF: the copy layer handles it
    // The Copy tab is now active with the clicked label loaded (the one-click shortcut is preserved).
    expect(screen.getByLabelText("Edit copy text")).toHaveValue("Original Title");
  });

  it("the catalogue filters by search and clicking an entry locates the element", () => {
    render(<Harness />);
    toggleDevMode();
    fireEvent.click(screen.getByRole("button", { name: /Catalogue/ }));

    fireEvent.change(screen.getByLabelText("Search ids"), { target: { value: "complete-part" } });
    const entry = screen.getByRole("button", { name: /detail\.complete-part/ });
    fireEvent.click(entry);
    expect(scrollIntoViewMock).toHaveBeenCalled();
  });

  it("enables the Icon facet tab and keeps the Box tab disabled", () => {
    render(<Harness />);
    toggleDevMode();
    expect(screen.getByRole("tab", { name: "Icon" })).toBeEnabled();
    expect(screen.getByRole("tab", { name: "Box" })).toBeDisabled();
  });

  it("the Icon tab shows an empty state when the selection has no icon", () => {
    render(<Harness />);
    toggleDevMode();
    inspectClick(screen.getByRole("button", { name: "Complete Part" }));
    fireEvent.click(screen.getByRole("tab", { name: "Icon" }));
    expect(
      screen.getByText(/select an element that is or contains an icon/i),
    ).toBeInTheDocument();
  });

  it("the Icon tab shows a same-category glyph picker + a raw-SVG editor for a selected icon", () => {
    render(<Harness />);
    toggleDevMode();
    inspectClick(screen.getByRole("button", { name: "Components tab" }));
    fireEvent.click(screen.getByRole("tab", { name: "Icon" }));

    // The raw-SVG editor is present (nav.components is a primary line icon, so raw editing is allowed).
    expect(screen.getByLabelText("Edit icon SVG body")).toBeInTheDocument();
    // The picker offers other primary glyphs (same category), and marks the current glyph active.
    expect(screen.getByRole("button", { name: "Swap to nav.projects" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Swap to nav.components" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
  });

  it("clicking a picker glyph swaps the icon (the panel preview follows the resolved target)", () => {
    render(<Harness />);
    toggleDevMode();
    inspectClick(screen.getByRole("button", { name: "Components tab" }));
    fireEvent.click(screen.getByRole("tab", { name: "Icon" }));

    fireEvent.click(screen.getByRole("button", { name: "Swap to nav.projects" }));
    // The resolved target moves to the picked glyph.
    expect(screen.getByRole("button", { name: "Swap to nav.projects" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(screen.getByRole("button", { name: "Swap to nav.components" })).toHaveAttribute(
      "aria-pressed",
      "false",
    );
  });

  it("editing the raw SVG drives a live, sanitised preview (no script survives)", () => {
    render(<Harness />);
    toggleDevMode();
    inspectClick(screen.getByRole("button", { name: "Components tab" }));
    fireEvent.click(screen.getByRole("tab", { name: "Icon" }));

    const editor = screen.getByLabelText("Edit icon SVG body");
    fireEvent.change(editor, {
      target: { value: '<path d="M2 2h9"/><script>alert(1)</script>' },
    });
    const preview = screen.getByTestId("icon-preview");
    expect(preview.innerHTML).toContain('d="M2 2h9"');
    expect(preview.innerHTML).not.toContain("script");
  });

  it("the per-icon Reset clears the override back to the registry default", () => {
    render(<Harness />);
    toggleDevMode();
    inspectClick(screen.getByRole("button", { name: "Components tab" }));
    fireEvent.click(screen.getByRole("tab", { name: "Icon" }));

    const editor = screen.getByLabelText("Edit icon SVG body");
    fireEvent.change(editor, { target: { value: '<path d="M0 0h4"/>' } });
    expect(editor).toHaveValue('<path d="M0 0h4"/>');

    fireEvent.click(screen.getByRole("button", { name: "Reset to default" }));
    expect(screen.getByLabelText("Edit icon SVG body")).not.toHaveValue('<path d="M0 0h4"/>');
  });

  it("art/brand icons are swap-only (no raw-SVG textarea)", () => {
    function ArtHarness() {
      return (
        <ThemeProvider>
          <DevModeProvider>
            <button type="button" data-dev-id="card.symbol" aria-label="Symbol art" className="text-t1">
              <Icon id="art.symbol" />
            </button>
            <DevPanel />
            <DevInspector />
          </DevModeProvider>
        </ThemeProvider>
      );
    }
    render(<ArtHarness />);
    toggleDevMode();
    inspectClick(screen.getByRole("button", { name: "Symbol art" }));
    fireEvent.click(screen.getByRole("tab", { name: "Icon" }));

    // Swap picker present, raw editor absent (D-03: art/brand markup is not hand-edited first).
    expect(screen.getByRole("button", { name: "Swap to art.footprint" })).toBeInTheDocument();
    expect(screen.queryByLabelText("Edit icon SVG body")).not.toBeInTheDocument();
  });

  it("a new icon selection surfaces the Icon tab automatically", () => {
    render(<Harness />);
    toggleDevMode();
    inspectClick(screen.getByRole("button", { name: "Components tab" }));
    // No manual tab click: the Icon editor is already showing.
    expect(screen.getByLabelText("Edit icon SVG body")).toBeInTheDocument();
  });

  it("DevPanel's own close glyph renders through <Icon> (itself inspectable)", () => {
    render(<Harness />);
    toggleDevMode();
    expect(document.querySelector('[data-icon-id="dev.close"]')).toBeInTheDocument();
  });

  it("DevPanel's reset dot renders through <Icon> once a token is overridden", () => {
    render(<Harness />);
    toggleDevMode();
    fireEvent.change(screen.getByLabelText("Accent value"), { target: { value: "#123456" } });
    expect(document.querySelector('[data-icon-id="dev.reset"]')).toBeInTheDocument();
  });

  it("Show IDs renders one badge per [data-dev-id] node in the panel's world", () => {
    render(<Harness />);
    toggleDevMode();
    clickButton("Show IDs");
    const count = document.querySelectorAll("[data-dev-id]").length;
    expect(screen.getAllByTestId("dev-id-badge")).toHaveLength(count);
  });
});
