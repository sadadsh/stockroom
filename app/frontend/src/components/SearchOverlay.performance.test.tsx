import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { api } from "../api/client";
import type { SearchRow } from "../api/types";
import {
  readUiSession,
  resetUiSessionForTests,
} from "../lib/uiSession";
import { SearchOverlay } from "./SearchOverlay";

vi.mock("../api/client", async (importActual) => {
  const actual = await importActual<typeof import("../api/client")>();
  return {
    ...actual,
    api: {
      ...actual.api,
      facets: vi.fn(),
      parametricFacets: vi.fn(),
      searchParts: vi.fn(),
      putUiSession: vi.fn(),
    },
  };
});

const mockApi = vi.mocked(api);
const MAX_MOUNTED_SEARCH_ROWS = 40;
const originalScrollTo = Object.getOwnPropertyDescriptor(
  HTMLElement.prototype,
  "scrollTo",
);
const scrollTo = vi.fn();

beforeEach(() => {
  Object.defineProperty(HTMLElement.prototype, "scrollTo", {
    configurable: true,
    value: scrollTo,
  });
});

afterEach(() => {
  scrollTo.mockReset();
  if (originalScrollTo) {
    Object.defineProperty(
      HTMLElement.prototype,
      "scrollTo",
      originalScrollTo,
    );
  } else {
    Reflect.deleteProperty(HTMLElement.prototype, "scrollTo");
  }
});

function rows(count: number): SearchRow[] {
  return Array.from({ length: count }, (_, index) => ({
    id: `part-${String(index).padStart(4, "0")}`,
    display_name: `Part ${String(index).padStart(4, "0")}`,
    category: `Category ${String(Math.floor(index / 100)).padStart(2, "0")}`,
    mpn: `MPN-${index}`,
    manufacturer: "Fixture",
    is_complete: true,
    missing: [],
    specs: {
      Resistance: `${index + 1} kΩ`,
      Tolerance: index % 2 ? "1%" : "5%",
      Package: index % 2 ? "0603" : "0402",
      Voltage: `${10 + (index % 40)} V`,
    },
    stock: count - index,
    unit_price: 0.01 + index / 100_000,
    currency: "USD",
  }));
}

function renderOverlay(
  onOpenPart = vi.fn(),
): ReturnType<typeof render> & { onOpenPart: ReturnType<typeof vi.fn> } {
  const client = new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
        staleTime: Number.POSITIVE_INFINITY,
      },
    },
  });
  const view = render(
    <QueryClientProvider client={client}>
      <SearchOverlay onClose={vi.fn()} onOpenPart={onOpenPart} />
    </QueryClientProvider>,
  );
  return { ...view, onOpenPart };
}

describe("SearchOverlay 1,000-result performance contract", () => {
  it("bounds the DOM, keeps the active part through sort, and does not duplicate I/O", async () => {
    const fixture = rows(1_000);
    resetUiSessionForTests();
    mockApi.facets.mockResolvedValue({
      by_category: Object.fromEntries(
        Array.from({ length: 10 }, (_, index) => [
          `Category ${String(index).padStart(2, "0")}`,
          100,
        ]),
      ),
      by_manufacturer: { Fixture: 1_000 },
      complete: 1_000,
      incomplete: 0,
    });
    mockApi.parametricFacets.mockResolvedValue({
      category: null,
      total: 1_000,
      facets: [
        {
          key: "Resistance",
          label: "Resistance",
          kind: "range",
          count: 1_000,
          min: 1_000,
          max: 1_000_000,
          unit: "Ω",
        },
        {
          key: "Tolerance",
          label: "Tolerance",
          kind: "options",
          count: 1_000,
          options: [
            { value: "1%", count: 500 },
            { value: "5%", count: 500 },
          ],
        },
        {
          key: "Package",
          label: "Package",
          kind: "options",
          count: 1_000,
          options: [
            { value: "0402", count: 500 },
            { value: "0603", count: 500 },
          ],
        },
      ],
    });
    mockApi.searchParts.mockResolvedValue({
      parts: fixture,
      count: fixture.length,
    });
    mockApi.putUiSession.mockImplementation(async (snapshot) => snapshot);

    const { container, onOpenPart } = renderOverlay();
    const table = await waitFor(() => {
      const candidate = container.querySelector(
        '[data-dev-id="search.results-table"]',
      );
      expect(candidate).toHaveAttribute("data-virtualized", "true");
      return candidate as HTMLTableElement;
    });

    expect(table).toHaveAttribute("aria-rowcount", "1001");
    expect(
      within(table).getByRole("columnheader", { name: "Identity" }),
    ).toBeInTheDocument();
    expect(
      within(table).getByRole("columnheader", { name: "Match & Evidence" }),
    ).toBeInTheDocument();
    expect(
      within(table).getByRole("columnheader", { name: "Package" }),
    ).toBeInTheDocument();
    expect(
      within(table).getByRole("columnheader", { name: "Dual-EDA" }),
    ).toBeInTheDocument();
    expect(
      within(table).queryByRole("columnheader", { name: "Lifecycle" }),
    ).not.toBeInTheDocument();
    expect(
      within(table).queryByRole("columnheader", { name: "In Stock" }),
    ).not.toBeInTheDocument();
    expect(
      within(table).queryByRole("columnheader", { name: "Unit" }),
    ).not.toBeInTheDocument();
    const mountedRows = table.querySelectorAll(
      '[data-dev-id="search.results-row"]',
    );
    expect(mountedRows.length).toBeGreaterThan(0);
    expect(mountedRows.length).toBeLessThanOrEqual(
      MAX_MOUNTED_SEARCH_ROWS,
    );
    expect(mountedRows.length).toBeLessThan(fixture.length / 20);
    expect(mockApi.facets).toHaveBeenCalledTimes(1);
    expect(mockApi.parametricFacets).toHaveBeenCalledTimes(1);
    expect(mockApi.searchParts).toHaveBeenCalledTimes(1);

    const scroller = container.querySelector<HTMLElement>(
      '[data-dev-id="search.results"]',
    )!;
    scroller.scrollTop = 50_500;
    fireEvent.scroll(scroller);
    await waitFor(() =>
      expect(
        table.querySelector('[data-part-id="part-0999"]'),
      ).not.toBeNull(),
    );
    expect(
      table.querySelectorAll('[data-dev-id="search.results-row"]').length,
    ).toBeLessThanOrEqual(MAX_MOUNTED_SEARCH_ROWS);
    scroller.scrollTop = 0;
    fireEvent.scroll(scroller);

    await waitFor(() =>
      expect(
        table.querySelector('[data-part-id="part-0005"]'),
      ).not.toBeNull(),
    );
    const wanted = table.querySelector<HTMLTableRowElement>(
      '[data-part-id="part-0005"]',
    );
    expect(wanted).not.toBeNull();
    fireEvent.mouseEnter(wanted!);
    await waitFor(() =>
      expect(readUiSession().search_results.active_part_id).toBe(
        "part-0005",
      ),
    );

    const user = userEvent.setup();
    await user.click(
      screen.getByRole("button", { name: /^1%\s*500$/ }),
    );
    await waitFor(() => {
      expect(mockApi.parametricFacets).toHaveBeenCalledTimes(2);
      expect(mockApi.searchParts).toHaveBeenCalledTimes(2);
    });
    expect(readUiSession().search_results.active_part_id).toBe("part-0005");

    scrollTo.mockClear();
    const sortButton = screen.getByRole("button", { name: /^Sort Name/ });
    await user.click(sortButton);
    await user.click(
      within(sortButton.parentElement!).getByRole("button", {
        name: "In Stock",
      }),
    );
    expect(sortButton).toHaveAccessibleName(/^Sort In Stock/);

    // Stock ascending reverses the filtered fixture. The selected index moves
    // from 2 to 497, but its identity remains authoritative and no server key
    // changed.
    expect(readUiSession().search_results.active_part_id).toBe("part-0005");
    await waitFor(() => expect(scrollTo).toHaveBeenCalled());
    expect(mockApi.facets).toHaveBeenCalledTimes(1);
    expect(mockApi.parametricFacets).toHaveBeenCalledTimes(2);
    expect(mockApi.searchParts).toHaveBeenCalledTimes(2);
    expect(
      table.querySelectorAll('[data-dev-id="search.results-row"]').length,
    ).toBeLessThanOrEqual(MAX_MOUNTED_SEARCH_ROWS);

    const query = screen.getByRole("textbox", {
      name: "Search components",
    });
    await user.type(query, "abc");
    await waitFor(() => {
      expect(mockApi.parametricFacets).toHaveBeenCalledTimes(3);
      expect(mockApi.searchParts).toHaveBeenCalledTimes(3);
    });
    expect(mockApi.parametricFacets).toHaveBeenLastCalledWith(
      expect.objectContaining({ q: "abc" }),
    );
    expect(mockApi.searchParts).toHaveBeenLastCalledWith(
      expect.objectContaining({ q: "abc" }),
    );
    expect(readUiSession().search_results.active_part_id).toBe("part-0005");

    await user.keyboard("{Enter}");
    expect(onOpenPart).toHaveBeenCalledTimes(1);
    expect(onOpenPart).toHaveBeenCalledWith(
      "part-0005",
      "Category 00",
    );
  });

  it("does not scroll the virtualized list out from under the pointer", async () => {
    // P2: hovering a row selects it, and selection used to scroll the row into view
    // unconditionally. On a partly visible row that scroll moved the rows under the
    // cursor, firing another mouseenter, which scrolled again - moving the mouse dragged
    // the list along with it. Keyboard selection still scrolls: it is the only way the
    // active row can be off screen.
    resetUiSessionForTests();
    const fixture = rows(200);
    mockApi.facets.mockResolvedValue({
      by_category: { "Category 00": 100, "Category 01": 100 },
      by_manufacturer: { Fixture: 200 },
      complete: 200,
      incomplete: 0,
    });
    mockApi.parametricFacets.mockResolvedValue({
      category: null,
      total: 200,
      facets: [],
    });
    mockApi.searchParts.mockResolvedValue({
      parts: fixture,
      count: fixture.length,
    });
    mockApi.putUiSession.mockImplementation(async (snapshot) => snapshot);

    const { container } = renderOverlay();
    const table = await waitFor(() => {
      const candidate = container.querySelector(
        '[data-dev-id="search.results-table"]',
      );
      expect(candidate).toHaveAttribute("data-virtualized", "true");
      return candidate as HTMLTableElement;
    });

    scrollTo.mockClear();
    const hovered = table.querySelector<HTMLTableRowElement>(
      '[data-part-id="part-0004"]',
    );
    expect(hovered).not.toBeNull();
    fireEvent.mouseEnter(hovered!);
    await waitFor(() =>
      expect(readUiSession().search_results.active_part_id).toBe("part-0004"),
    );
    expect(scrollTo).not.toHaveBeenCalled();

    await userEvent.setup().keyboard("{End}");
    await waitFor(() =>
      expect(readUiSession().search_results.active_part_id).toBe("part-0199"),
    );
    expect(scrollTo).toHaveBeenCalled();
  });
});
