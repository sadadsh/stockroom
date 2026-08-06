/**
 * The picker's search band.
 *
 * The search box was a BUTTON that opened the full-screen parametric search, which meant the
 * picker could not narrow itself: typing three characters of a part number - the commonest thing
 * anyone does in a library - took over the whole window. These tests hold the two apart, and hold
 * the filters to saying what they are hiding.
 */
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { Facets } from "../api/types";
import { ThemeProvider } from "../lib/theme";
import { Finder } from "./Finder";

const FACETS: Facets = {
  by_category: { "Logic Gates": 12, Resistors: 40 },
  by_manufacturer: {},
  complete: 50,
  incomplete: 2,
} as Facets;

function renderFinder(overrides: Partial<React.ComponentProps<typeof Finder>> = {}) {
  const props: React.ComponentProps<typeof Finder> = {
    search: "",
    onSearch: vi.fn(),
    facets: FACETS,
    category: null,
    onCategory: vi.fn(),
    completeOnly: false,
    onCompleteOnly: vi.fn(),
    duplicatesOnly: false,
    onDuplicatesOnly: vi.fn(),
    duplicateCount: 3,
    onOpenSearch: vi.fn(),
    ...overrides,
  };
  return { props, ...render(<ThemeProvider><Finder {...props} /></ThemeProvider>) };
}

describe("the picker's inline search", () => {
  it("is a real text input, not a trigger for another surface", async () => {
    const user = userEvent.setup();
    const onSearch = vi.fn();
    const onOpenSearch = vi.fn();
    renderFinder({ onSearch, onOpenSearch });

    const input = screen.getByRole("textbox", { name: "Search Components" });
    await user.type(input, "L");

    expect(onSearch).toHaveBeenCalledWith("L");
    // Typing in the picker never opens the parametric search over the top of it.
    expect(onOpenSearch).not.toHaveBeenCalled();
  });

  it("keeps the parametric search as its own separate control", async () => {
    const user = userEvent.setup();
    const onOpenSearch = vi.fn();
    renderFinder({ onOpenSearch });

    await user.click(screen.getByRole("button", { name: "Advanced Search" }));

    expect(onOpenSearch).toHaveBeenCalledTimes(1);
  });
});

describe("what the filters say about themselves", () => {
  it("says nothing while nothing is filtered", () => {
    renderFinder();

    expect(screen.queryByText(/^Showing:/)).toBeNull();
  });

  it("names every active filter in words rather than only counting them", () => {
    renderFinder({ category: "Logic Gates", completeOnly: true, duplicatesOnly: true });

    expect(
      screen.getByText("Showing: Logic Gates · Just Complete · Duplicates"),
    ).toBeInTheDocument();
  });

  it("clears every active filter from the summary itself", async () => {
    const user = userEvent.setup();
    const onCategory = vi.fn();
    const onCompleteOnly = vi.fn();
    const onDuplicatesOnly = vi.fn();
    renderFinder({
      category: "Resistors",
      completeOnly: true,
      duplicatesOnly: true,
      onCategory,
      onCompleteOnly,
      onDuplicatesOnly,
    });

    await user.click(screen.getByRole("button", { name: "Clear Filters" }));

    expect(onCategory).toHaveBeenCalledWith(null);
    expect(onCompleteOnly).toHaveBeenCalledWith(false);
    expect(onDuplicatesOnly).toHaveBeenCalledWith(false);
  });
});
