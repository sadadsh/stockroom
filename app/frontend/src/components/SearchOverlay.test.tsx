import { fireEvent, render, screen } from "@testing-library/react";
import type { SearchRow } from "../api/types";
import {
  defaultUiSession,
  readUiSession,
  resetUiSessionForTests,
} from "../lib/uiSession";
import { SearchOverlay } from "./SearchOverlay";
import { searchEvidenceColumns, searchMatchEvidence } from "./searchEvidence";

// A mutable result set, the same shape the mocked query returns. Empty by default, so every case
// that does not care about rows behaves exactly as it did before this holder existed.
const MOCK_SEARCH: { parts: SearchRow[] } = vi.hoisted(() => ({ parts: [] }));

vi.mock("../api/queries", () => ({
  useFacetsQuery: () => ({
    data: {
      by_category: {},
      by_manufacturer: {},
      complete: 0,
      incomplete: 0,
    },
  }),
  useParametricFacets: () => ({
    data: {
      category: null,
      total: 4,
      facets: [
        {
          key: "Resistance",
          label: "Resistance",
          kind: "range",
          count: 4,
          min: 10_000,
          max: 10_000,
          unit: "Ω",
        },
      ],
    },
  }),
  useSearchQuery: () => ({
    data: { parts: MOCK_SEARCH.parts, count: MOCK_SEARCH.parts.length },
    isLoading: false,
  }),
}));

afterEach(() => {
  MOCK_SEARCH.parts = [];
});

describe("SearchOverlay numeric facets", () => {
  it("renders a single numeric value once instead of fabricating a min-max control", () => {
    render(<SearchOverlay onClose={vi.fn()} onOpenPart={vi.fn()} />);

    expect(screen.getByText("Resistance")).toBeInTheDocument();
    expect(screen.getAllByText("10 kΩ")).toHaveLength(1);
    expect(screen.getByText("Sole value")).toBeInTheDocument();
    expect(screen.queryByRole("slider")).not.toBeInTheDocument();
    expect(
      document.querySelector('[data-dev-id="search.single-value-facet"] input'),
    ).toBeNull();
  });

  it("restores the exact server-owned query and parametric filter state", () => {
    const session = defaultUiSession();
    session.search_filters = {
      query: "precision resistor",
      category: null,
      in_stock: true,
      options: [{ key: "Tolerance", values: ["1%"] }],
      ranges: [{ key: "Resistance", min: 10_000, max: 10_000 }],
    };
    session.search_sort = { kind: "stock", direction: "desc" };
    session.open_surface = "search";
    resetUiSessionForTests(session);

    render(<SearchOverlay onClose={vi.fn()} onOpenPart={vi.fn()} />);

    expect(screen.getByRole("textbox", { name: "Search components" })).toHaveValue(
      "precision resistor",
    );
    expect(screen.getByRole("button", { name: "In Stock" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    fireEvent.click(screen.getByRole("button", { name: /^Sort/ }));
    const selectedSort = screen.getAllByRole("button", { name: /^In Stock/ })
      .find((button) => button.closest(".absolute"));
    expect(selectedSort?.querySelector("svg.ico")).not.toBeNull();
    expect(selectedSort?.textContent).not.toMatch(/[↑↓]/);
  });
});

describe("SearchOverlay title strip and sub-strip", () => {
  it("puts the caret in the query field on open, so typing goes to the search", () => {
    render(<SearchOverlay onClose={vi.fn()} onOpenPart={vi.fn()} />);

    // Read on the OPENING commit, not after a settle: the whole point is that the field is ready
    // for the first keystroke, and a focus that lands one interaction later has already lost it.
    expect(document.activeElement).toBe(
      screen.getByRole("textbox", { name: "Search components" }),
    );
  });

  it("dismisses exactly the chip that was pressed and leaves every other narrowing in force", async () => {
    const session = defaultUiSession();
    session.search_filters = {
      query: "",
      category: "Resistors",
      in_stock: false,
      options: [{ key: "Tolerance", values: ["1%"] }],
      ranges: [],
    };
    session.open_surface = "search";
    resetUiSessionForTests(session);

    render(<SearchOverlay onClose={vi.fn()} onOpenPart={vi.fn()} />);
    const chips = document.querySelector<HTMLElement>('[data-dev-id="search.chips"]')!;
    expect(chips.textContent).toContain("Resistors");
    expect(chips.textContent).toContain("1%");

    fireEvent.click(screen.getByRole("button", { name: "Remove Category filter" }));

    expect(chips.textContent).not.toContain("Resistors");
    // The other narrowing survives - a chip remover that reset the whole set would also pass an
    // assertion that only checked the chip it removed.
    expect(chips.textContent).toContain("1%");
    expect(screen.getByRole("button", { name: "Remove Tolerance filter" })).toBeInTheDocument();
  });
});

describe("SearchOverlay evidence-first result contract", () => {
  const complete: SearchRow = {
    id: "lm358",
    display_name: "Dual Operational Amplifier",
    category: "ICs",
    mpn: "LM358DR",
    manufacturer: "Texas Instruments",
    is_complete: true,
    missing: [],
    specs: { Package: "SOIC-8", Lifecycle: "Active" },
    stock: 100,
    unit_price: 0.42,
    currency: "USD",
  };

  it("collapses optional evidence columns when every result is empty", () => {
    expect(searchEvidenceColumns([complete])).toEqual({
      package: true,
      lifecycle: true,
    });
    expect(
      searchEvidenceColumns([{ ...complete, specs: {} }]),
    ).toEqual({ package: false, lifecycle: false });
  });

  it("names exact-MPN confidence and an actionable incomplete-evidence reason", () => {
    expect(searchMatchEvidence(complete, "lm358dr")).toEqual({
      match: "Exact MPN",
      evidence: "Record Evidence Complete",
    });
    expect(
      searchMatchEvidence(
        {
          ...complete,
          is_complete: false,
          missing: ["kicad_symbol", "altium_footprint"],
        },
        "op amp",
      ),
    ).toEqual({
      match: "Catalog Match",
      evidence: "Needs KiCad Symbol, Altium Footprint",
    });
  });
});

// The results anchor is written from a ref the component keeps in step with the active row, so the
// scroll checkpoint can persist an identity without re-subscribing every time the selection moves.
// The checkpoint also runs as the effect's teardown, which is the path this asserts: whatever row was
// active when the overlay went away is the row the next open scrolls back to.
describe("SearchOverlay result-anchor persistence", () => {
  const row = (id: string, mpn: string): SearchRow => ({
    id,
    display_name: mpn,
    category: "ICs",
    mpn,
    manufacturer: "Texas Instruments",
    is_complete: true,
    missing: [],
    specs: {},
    stock: 1,
    unit_price: 1,
    currency: "USD",
  });

  it("persists the row the selection MOVED to as the results anchor when the overlay goes away", () => {
    resetUiSessionForTests(defaultUiSession());
    MOCK_SEARCH.parts = [row("lm358", "LM358DR"), row("ne555", "NE555P")];

    const { unmount } = render(<SearchOverlay onClose={vi.fn()} onOpenPart={vi.fn()} />);
    expect(readUiSession().search_results.anchor_part_id).toBeNull();

    // move off the first result, so the anchor can only be right if the ref tracked the move
    fireEvent.keyDown(document, { key: "ArrowDown" });

    unmount();

    expect(readUiSession().search_results.anchor_part_id).toBe("ne555");
  });
});
