import { render, screen, fireEvent } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ThemeProvider } from "../lib/theme";
import { DevModeProvider } from "../lib/devMode";
import { api } from "../api/client";
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
        {/* A real flex container with dev-id children, so the Layout reorder path has genuine siblings. */}
        <div data-dev-id="rail.nav" className="flex flex-col">
          <button type="button" data-dev-id="rail.nav-components" className="text-t1">
            Nav Components
          </button>
          <button type="button" data-dev-id="rail.nav-projects" className="text-t1">
            Nav Projects
          </button>
          <button type="button" data-dev-id="rail.nav-settings" className="text-t1">
            Nav Settings
          </button>
        </div>
        {/* A real grid container (grid-cols-2) with dev-id children, so the grid slot picker path has a
            genuine grid child under jsdom. */}
        <div data-dev-id="detail.actions" className="grid grid-cols-2 gap-2">
          <button type="button" data-dev-id="detail.action-a" className="text-t1">
            Action A
          </button>
          <button type="button" data-dev-id="detail.action-b" className="text-t1">
            Action B
          </button>
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

  it("enables the Icon and Box facet tabs", () => {
    render(<Harness />);
    toggleDevMode();
    expect(screen.getByRole("tab", { name: "Icon" })).toBeEnabled();
    expect(screen.getByRole("tab", { name: "Box" })).toBeEnabled();
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

  // --- the [Box] tab (ELEM-02): per-element resize + spacing overrides on the selected element ---

  // Select the bg-acc button and open the Box tab; returns the live [data-dev-id] node under edit.
  function selectAndOpenBox(): HTMLElement {
    const target = screen.getByRole("button", { name: "Complete Part" });
    inspectClick(target);
    fireEvent.click(screen.getByRole("tab", { name: "Box" }));
    return document.querySelector('[data-dev-id="detail.complete-part"]') as HTMLElement;
  }

  it("editing a Box field updates the live element AND the save payload's elements block", () => {
    render(<Harness />);
    toggleDevMode();
    const node = selectAndOpenBox();

    // Each field carries the element's computed value as its placeholder (jsdom yields limited values,
    // so assert the attribute is PRESENT rather than a specific px).
    const width = screen.getByLabelText("Width value");
    expect(width).toHaveAttribute("placeholder");

    // Typing writes the override live: the Plan 01 apply effect sets the inline style on the node.
    fireEvent.change(width, { target: { value: "300px" } });
    expect(node.style.width).toBe("300px");

    // Save carries the working override as an `elements` block for the backend writer.
    const devSave = vi.mocked(api.devSave);
    devSave.mockClear();
    fireEvent.click(screen.getByRole("button", { name: /Save to source/ }));
    expect(devSave).toHaveBeenCalledWith(
      expect.objectContaining({
        elements: { "detail.complete-part": { width: "300px" } },
      }),
    );
  });

  it("a Box field's per-property reset clears its inline style and empties the field", () => {
    render(<Harness />);
    toggleDevMode();
    const node = selectAndOpenBox();

    const width = screen.getByLabelText("Width value");
    fireEvent.change(width, { target: { value: "300px" } });
    expect(node.style.width).toBe("300px");

    // With the override set, the row shows a ResetDot; clicking it removes just that property.
    fireEvent.click(screen.getByRole("button", { name: "Reset to default" }));
    expect(node.style.width).toBe("");
    expect(screen.getByLabelText("Width value")).toHaveValue("");
  });

  it("Clear All wipes every override on the selected element", () => {
    render(<Harness />);
    toggleDevMode();
    const node = selectAndOpenBox();

    // Use two longhand properties (one resize, one spacing): jsdom's removeProperty does not reliably
    // clear a CSS shorthand like `padding`, so assert on longhands the environment handles cleanly.
    fireEvent.change(screen.getByLabelText("Width value"), { target: { value: "300px" } });
    fireEvent.change(screen.getByLabelText("Margin Top value"), { target: { value: "8px" } });
    expect(node.style.width).toBe("300px");
    expect(node.style.marginTop).toBe("8px");

    fireEvent.click(screen.getByRole("button", { name: "Clear All" }));
    expect(node.style.width).toBe("");
    expect(node.style.marginTop).toBe("");
  });

  it("the Box tab shows an empty state with no selection and renders no fields", () => {
    render(<Harness />);
    toggleDevMode();
    fireEvent.click(screen.getByRole("tab", { name: "Box" }));
    expect(screen.getByText(/select an element to override its box/i)).toBeInTheDocument();
    expect(screen.queryByLabelText("Width value")).not.toBeInTheDocument();
  });

  // --- the Layout section (Phase F / LAYOUT-01): reorder within a flex/grid container via `order` ---

  // Select the given nav child and open the Box tab; returns its live [data-dev-id] node.
  function selectNavAndOpenBox(devId: string, label: string): HTMLElement {
    inspectClick(screen.getByRole("button", { name: label }));
    fireEvent.click(screen.getByRole("tab", { name: "Box" }));
    return document.querySelector(`[data-dev-id="${devId}"]`) as HTMLElement;
  }

  it("shows Move Up / Move Down only for an element inside a flex/grid container with siblings", () => {
    render(<Harness />);
    toggleDevMode();
    // A flex-container child: the Layout controls appear.
    selectNavAndOpenBox("rail.nav-components", "Nav Components");
    expect(screen.getByRole("button", { name: "Move Up" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Move Down" })).toBeInTheDocument();

    // A non-container element (its parent has no flex/grid class): no Layout controls. Inspect is
    // already on from the call above, so a bare click reselects (a second inspectClick would toggle off).
    fireEvent.click(screen.getByRole("button", { name: "Complete Part" }));
    fireEvent.click(screen.getByRole("tab", { name: "Box" }));
    expect(screen.queryByRole("button", { name: "Move Up" })).not.toBeInTheDocument();
  });

  it("Move Down writes the recomputed `order` live and carries it in the save `elements` block", () => {
    render(<Harness />);
    toggleDevMode();
    const node = selectNavAndOpenBox("rail.nav-components", "Nav Components");

    // Move the first child down one step: it swaps with its next sibling, landing at visual index 1.
    fireEvent.click(screen.getByRole("button", { name: "Move Down" }));
    // The Phase E apply effect sets the inline style live from the `order` override.
    expect(node.style.order).toBe("1");

    // Save carries the reorder purely as an `order` entry in the `elements` block for the backend writer.
    const devSave = vi.mocked(api.devSave);
    devSave.mockClear();
    fireEvent.click(screen.getByRole("button", { name: /Save to source/ }));
    expect(devSave).toHaveBeenCalledWith(
      expect.objectContaining({
        elements: expect.objectContaining({ "rail.nav-components": { order: "1" } }),
      }),
    );
  });

  it("Move Up / Move Down walk one step across three siblings without jumping to an end", () => {
    render(<Harness />);
    toggleDevMode();
    const first = selectNavAndOpenBox("rail.nav-components", "Nav Components");
    const last = document.querySelector('[data-dev-id="rail.nav-settings"]') as HTMLElement;

    // From visual index 0, one Move Down lands at 1 (swaps with projects), not at the back.
    fireEvent.click(screen.getByRole("button", { name: "Move Down" }));
    expect(first.style.order).toBe("1");
    // A second Move Down lands at 2 (swaps with settings), and settings falls back to 1.
    fireEvent.click(screen.getByRole("button", { name: "Move Down" }));
    expect(first.style.order).toBe("2");
    expect(last.style.order).toBe("1");
  });

  // --- the grid slot picker (Phase F / LAYOUT-01, decision 1b): grid-column / grid-row on a grid child ---

  it("shows a grid slot picker only for a grid child, not for a flex child", () => {
    render(<Harness />);
    toggleDevMode();
    // A grid-container child: the slot picker (column + row controls) appears.
    selectNavAndOpenBox("detail.action-a", "Action A");
    expect(screen.getByLabelText("Grid Column")).toBeInTheDocument();
    expect(screen.getByLabelText("Grid Row")).toBeInTheDocument();

    // A flex-container child still gets the reorder controls but NO grid slot picker.
    fireEvent.click(screen.getByRole("button", { name: "Nav Components" }));
    fireEvent.click(screen.getByRole("tab", { name: "Box" }));
    expect(screen.getByRole("button", { name: "Move Up" })).toBeInTheDocument();
    expect(screen.queryByLabelText("Grid Column")).not.toBeInTheDocument();
  });

  it("choosing a column slot writes a validated grid-column live and into the save `elements` block", () => {
    render(<Harness />);
    toggleDevMode();
    const node = selectNavAndOpenBox("detail.action-a", "Action A");

    // The options are derived from the container's grid-cols-2: auto, 1, 2, span 2.
    fireEvent.change(screen.getByLabelText("Grid Column"), { target: { value: "2" } });
    expect(node.style.getPropertyValue("grid-column")).toBe("2");

    // Save carries the slot purely as a grid-column entry in the `elements` block for the backend writer.
    const devSave = vi.mocked(api.devSave);
    devSave.mockClear();
    fireEvent.click(screen.getByRole("button", { name: /Save to source/ }));
    expect(devSave).toHaveBeenCalledWith(
      expect.objectContaining({
        elements: expect.objectContaining({ "detail.action-a": { "grid-column": "2" } }),
      }),
    );
  });

  it("Reset Slot clears only grid-column / grid-row, leaving the element's order untouched", () => {
    render(<Harness />);
    toggleDevMode();
    const node = selectNavAndOpenBox("detail.action-a", "Action A");

    fireEvent.change(screen.getByLabelText("Grid Column"), { target: { value: "2" } });
    fireEvent.change(screen.getByLabelText("Grid Row"), { target: { value: "span 2" } });
    // Also reorder within the grid, so we can prove Reset Slot leaves `order` alone.
    fireEvent.click(screen.getByRole("button", { name: "Move Down" }));
    expect(node.style.getPropertyValue("grid-column")).toBe("2");
    expect(node.style.getPropertyValue("grid-row")).toBe("span 2");
    expect(node.style.order).toBe("1");

    fireEvent.click(screen.getByRole("button", { name: "Reset Slot" }));
    expect(node.style.getPropertyValue("grid-column")).toBe("");
    expect(node.style.getPropertyValue("grid-row")).toBe("");
    // The order override survives: Reset Slot touches only the grid slot properties.
    expect(node.style.order).toBe("1");
    expect(screen.queryByRole("button", { name: "Reset Slot" })).not.toBeInTheDocument();
  });

  it("choosing auto clears the grid-column override (the grid's own flow returns)", () => {
    render(<Harness />);
    toggleDevMode();
    const node = selectNavAndOpenBox("detail.action-a", "Action A");

    fireEvent.change(screen.getByLabelText("Grid Column"), { target: { value: "2" } });
    expect(node.style.getPropertyValue("grid-column")).toBe("2");
    fireEvent.change(screen.getByLabelText("Grid Column"), { target: { value: "auto" } });
    expect(node.style.getPropertyValue("grid-column")).toBe("");
  });

  it("Reset Order clears every sibling's order and drops it from the save `elements` block", async () => {
    render(<Harness />);
    toggleDevMode();
    const node = selectNavAndOpenBox("rail.nav-components", "Nav Components");
    const projects = document.querySelector('[data-dev-id="rail.nav-projects"]') as HTMLElement;

    fireEvent.click(screen.getByRole("button", { name: "Move Down" }));
    expect(node.style.order).toBe("1");
    expect(projects.style.order).toBe("0");

    // Commit the reorder so the saved baseline carries the order values.
    const devSave = vi.mocked(api.devSave);
    fireEvent.click(screen.getByRole("button", { name: /Save to source/ }));
    expect(devSave).toHaveBeenCalledWith(
      expect.objectContaining({
        elements: expect.objectContaining({ "rail.nav-components": { order: "1" } }),
      }),
    );
    // Let the async save settle so the footer button returns from "Saving..." to "Save to source".
    await screen.findByRole("button", { name: /Save to source/ });

    // Reset Order strips `order` from every sibling, restoring the original DOM order.
    fireEvent.click(screen.getByRole("button", { name: "Reset Order" }));
    expect(node.style.order).toBe("");
    expect(projects.style.order).toBe("");
    expect(screen.queryByRole("button", { name: "Reset Order" })).not.toBeInTheDocument();

    // Saving again carries an empty `elements` block - the reorder reverted with no leftover overrides.
    devSave.mockClear();
    fireEvent.click(screen.getByRole("button", { name: /Save to source/ }));
    expect(devSave).toHaveBeenCalledWith(expect.objectContaining({ elements: {} }));
  });
});
