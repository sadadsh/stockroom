import { render, screen, fireEvent } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ThemeProvider } from "../lib/theme";
import { DevModeProvider } from "../lib/devMode";
import { Text } from "../lib/copy";
import { DevPanel } from "./DevPanel";
import { DevInspector } from "./DevInspector";

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

  it("renders the Icon and Box facet tabs disabled", () => {
    render(<Harness />);
    toggleDevMode();
    expect(screen.getByRole("tab", { name: "Icon" })).toBeDisabled();
    expect(screen.getByRole("tab", { name: "Box" })).toBeDisabled();
  });

  it("Show IDs renders one badge per [data-dev-id] node in the panel's world", () => {
    render(<Harness />);
    toggleDevMode();
    clickButton("Show IDs");
    const count = document.querySelectorAll("[data-dev-id]").length;
    expect(screen.getAllByTestId("dev-id-badge")).toHaveLength(count);
  });
});
