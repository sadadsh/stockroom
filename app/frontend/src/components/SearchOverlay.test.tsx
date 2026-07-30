import { render, screen } from "@testing-library/react";
import type { SearchRow } from "../api/types";
import { defaultUiSession, resetUiSessionForTests } from "../lib/uiSession";
import {
  SearchOverlay,
  searchEvidenceColumns,
  searchMatchEvidence,
} from "./SearchOverlay";

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
    data: { parts: [], count: 0 },
    isLoading: false,
  }),
}));

describe("SearchOverlay numeric facets", () => {
  it("renders a single numeric value once instead of fabricating a min-max control", () => {
    render(<SearchOverlay onClose={vi.fn()} onOpenPart={vi.fn()} />);

    expect(screen.getByText("Resistance")).toBeInTheDocument();
    expect(screen.getAllByText("10 kΩ")).toHaveLength(1);
    expect(screen.getByText("Only value")).toBeInTheDocument();
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
