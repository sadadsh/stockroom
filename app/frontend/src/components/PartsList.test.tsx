import { useState } from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { PartSummary } from "../api/types";
import { PartsList } from "./PartsList";
import { partAttention } from "./partAttention";

const FIXTURE_VIEWPORT_HEIGHT = 640;
// Count budget for a measured 640px list viewport: ~14 visible mixed-height items plus eight
// overscan items on either side and one retained sticky header. This is deliberately a DOM-count
// contract, not a jsdom timing claim.
const MAX_MOUNTED_ITEMS_AT_FIXTURE_VIEWPORT = 40;

function parts(count: number): PartSummary[] {
  return Array.from({ length: count }, (_, index) => ({
    id: `part-${String(index).padStart(4, "0")}`,
    display_name: `Part ${String(index).padStart(4, "0")}`,
    category: `Category ${String(Math.floor(index / 100)).padStart(2, "0")}`,
    mpn: `MPN-${index}`,
    manufacturer: "Fixture",
    is_complete: index !== 0,
    missing: index === 0 ? ["kicad_model"] : [],
    eda_readiness: {},
  }));
}

function Harness({
  fixture,
  selectedId,
  duplicateIds,
  onSelect,
}: {
  fixture: PartSummary[];
  selectedId: string | null;
  duplicateIds?: Set<string>;
  onSelect: (id: string) => void;
}) {
  const [scrollElement, setScrollElement] = useState<HTMLDivElement | null>(
    null,
  );
  return (
    <div
      ref={setScrollElement}
      data-testid="parts-scroll"
      style={{ height: FIXTURE_VIEWPORT_HEIGHT, overflowY: "auto" }}
    >
      <PartsList
        parts={fixture}
        selectedId={selectedId}
        duplicateIds={duplicateIds}
        onSelect={onSelect}
        scrollElement={scrollElement}
      />
    </div>
  );
}

function StatefulHarness({
  fixture,
  onSelect,
}: {
  fixture: PartSummary[];
  onSelect: (id: string) => void;
}) {
  const [selectedId, setSelectedId] = useState(fixture[0]?.id ?? null);
  return (
    <Harness
      fixture={fixture}
      selectedId={selectedId}
      onSelect={(id) => {
        setSelectedId(id);
        onSelect(id);
      }}
    />
  );
}

describe("no EDA application is named in the picker", () => {
  const EDA = /kicad|altium|eagle|orcad|easyeda/i;

  it("names the missing ASSET, never the design tool that could open it", () => {
    const fixture = parts(1);
    const { container } = render(
      <Harness
        fixture={[
          {
            ...fixture[0],
            missing: ["kicad_symbol", "altium_footprint", "kicad_model"],
          },
        ]}
        selectedId={null}
        onSelect={vi.fn()}
      />,
    );
    // The whole rendered picker, not just the opened component: a person browsing the library is
    // doing ordinary inspection, and the rule holds there too.
    expect(container.textContent ?? "").not.toMatch(EDA);
    const warning = container.querySelector('[data-dev-id="components.row-warn"]');
    expect(warning).toHaveTextContent("Missing Symbol + 2 More");
  });

  it("counts one artifact once, however many tools are missing it", () => {
    const fixture = parts(1);
    // Two tools, one gap in the PART: it needs a footprint. Listing it twice only ever read as
    // two problems because the tool names made the entries look different.
    const attention = partAttention({
      ...fixture[0],
      missing: ["kicad_footprint", "altium_footprint"],
    });
    expect(attention!.reason).toBe("Missing Footprint");
  });

  it("leaves an identity gap's own wording alone", () => {
    const attention = partAttention({
      ...parts(1)[0],
      missing: ["Manufacturer Part Number"],
    });
    expect(attention!.reason).toBe("Missing Manufacturer Part Number");
  });
});

describe("the picker row's one primary item", () => {
  // The seeded library's first component, and the row the defect was measured on.
  const CAPACITOR: PartSummary = {
    ...parts(1)[0],
    id: "c100n",
    mpn: "CL05B104KO5NNNC",
    display_name: "100nF 0402",
    manufacturer: "Samsung",
    package: "C_0402_1005Metric",
    is_complete: false,
    missing: ["datasheet"],
  };

  /** The line `element` sits on: the ancestor whose own parent is the row's text column. */
  function lineOf(element: Element, column: Element): Element {
    let current: Element = element;
    while (current.parentElement && current.parentElement !== column) {
      current = current.parentElement;
    }
    return current;
  }

  it("gives the MPN a line of its own, so no secondary item can shrink it", () => {
    const { container } = render(
      <Harness fixture={[CAPACITOR]} selectedId={null} onSelect={vi.fn()} />,
    );
    const mpn = container.querySelector<HTMLElement>('[data-dev-id="components.row-mpn"]')!;
    const pkg = container.querySelector<HTMLElement>('[data-dev-id="components.row-package"]')!;
    const warn = container.querySelector<HTMLElement>('[data-dev-id="components.row-warn"]')!;
    const column = mpn.parentElement!;

    expect(mpn.textContent).toBe("CL05B104KO5NNNC");
    expect(mpn.className).toContain("ui-row-primary");
    // Ellipsis is allowed only when the identifier genuinely cannot fit, and the whole string is
    // on the tooltip when it happens.
    expect(mpn.title).toBe("CL05B104KO5NNNC");

    // MEASURED at 1366x768, picker row 290px wide: the MPN shared line one with a `flex-none`
    // package while a fixed 112px attention block sat beside them both, which left the identifier
    // about 8px and rendered it as `C...` - one letter and an ellipsis - with
    // `C_0402_1005Metric` and `Missing Datasheet...` keeping their space. That is the row's
    // hierarchy exactly inverted. The MPN IS its own line now, and both secondary items are on
    // lines below it, so neither can take a character off it at any width.
    expect(lineOf(mpn, column)).toBe(mpn);
    expect(lineOf(pkg, column)).not.toBe(mpn);
    expect(lineOf(warn, column)).not.toBe(mpn);
    const lines = [...column.children];
    expect(lines.indexOf(mpn)).toBe(0);
    expect(lines.indexOf(lineOf(pkg, column))).toBeGreaterThan(0);
    expect(lines.indexOf(lineOf(warn, column))).toBeGreaterThan(
      lines.indexOf(lineOf(pkg, column)),
    );
  });

  it("hands the attention state the description's width rather than the identifier's", () => {
    const { container } = render(
      <Harness fixture={[CAPACITOR]} selectedId={null} onSelect={vi.fn()} />,
    );
    const warn = container.querySelector<HTMLElement>('[data-dev-id="components.row-warn"]')!;
    const pkg = container.querySelector<HTMLElement>('[data-dev-id="components.row-package"]')!;
    const description = warn.previousElementSibling as HTMLElement;

    expect(description.textContent).toBe("100nF 0402");
    // `flex-1` is `flex: 1 1 0%`: the description asks for none of the line and takes what is
    // left, so it is the item that gives way. It is also the only text on the row whose loss
    // costs nothing, because the whole of it is on the opened component.
    expect(description.className).toContain("flex-1");
    expect(warn.className).toContain("min-w-0");
    expect(warn.className).not.toContain("flex-none");
    expect(warn).toHaveTextContent("Missing Datasheet");
    // The manufacturer yields to the package on its own line for the same reason.
    expect(pkg.previousElementSibling!.className).toContain("flex-1");
    expect(pkg.className).toContain("truncate");
  });
});

describe("PartsList virtualization", () => {
  it("turns every incomplete-row warning into a reason and automatic next step", () => {
    const fixture = parts(1);
    const attention = partAttention({
      ...fixture[0],
      missing: ["kicad_model", "altium_footprint"],
    });

    // The ASSET is what the row names. A design tool's name never appears during ordinary
    // component inspection, and browsing the library is the most ordinary inspection there is.
    //
    // The next step is on the DESCRIPTION and no longer takes a line of its own. Measured at a
    // 290px picker, that line rendered as `Next: Collecting Ev...` - a hint cut mid-word, which
    // names nothing and promises nothing - while the MPN above it was down to one character.
    expect(attention).toEqual({
      reason: "Missing 3D Model + Footprint",
      description:
        "Needs Attention. Missing 3D Model, Footprint. Next: Stockroom will continue source collection and verification.",
    });

    render(
      <Harness
        fixture={[{ ...fixture[0], missing: ["kicad_model", "altium_footprint"] }]}
        selectedId={fixture[0].id}
        onSelect={vi.fn()}
      />,
    );

    const row = screen.getByRole("button", { name: /Part 0000/ });
    const warning = row.querySelector(
      '[data-dev-id="components.row-warn"]',
    );
    expect(warning).toHaveTextContent("Missing 3D Model + Footprint");
    expect(warning).not.toHaveTextContent("Next: Collecting Evidence");
    expect(row).toHaveAccessibleDescription(
      /Stockroom will continue source collection and verification/,
    );
  });

  it("keeps a 1,000-part library's mounted DOM bounded while preserving row contracts", async () => {
    const fixture = parts(1_000);
    const onSelect = vi.fn();
    const { container, rerender } = render(
      <Harness
        fixture={fixture}
        selectedId={fixture[0].id}
        duplicateIds={new Set([fixture[0].id])}
        onSelect={onSelect}
      />,
    );

    const list = container.querySelector('[data-dev-id="components.list"]');
    expect(list).toHaveAttribute("data-virtualized", "true");

    const mountedItems = list!.querySelectorAll(":scope > [data-index]");
    const mountedRows = list!.querySelectorAll(
      '[data-dev-id="components.row"]',
    );
    expect(mountedItems.length).toBeGreaterThan(0);
    expect(mountedItems.length).toBeLessThanOrEqual(
      MAX_MOUNTED_ITEMS_AT_FIXTURE_VIEWPORT,
    );
    expect(mountedRows.length).toBeLessThan(fixture.length / 20);

    const first = screen.getByRole("button", { name: /Part 0000/ });
    expect(first).toHaveAttribute("data-dev-id", "components.row");
    expect(first).toHaveAttribute("aria-current", "true");
    expect(
      first.querySelector('[data-dev-id="components.row-thumbnail"]'),
    ).not.toBeNull();
    expect(
      first.querySelector('[data-dev-id="components.row-duplicate"]'),
    ).not.toBeNull();
    expect(
      first.querySelector('[data-dev-id="components.row-warn"]'),
    ).not.toBeNull();

    first.focus();
    await userEvent.keyboard("{Enter}");
    expect(onSelect).toHaveBeenCalledWith(fixture[0].id);

    // Scroll-driven range changes must expose the tail without mounting the 978 rows in between.
    const scroll = screen.getByTestId("parts-scroll");
    scroll.scrollTop = 47_740;
    fireEvent.scroll(scroll);
    const last = await screen.findByRole("button", { name: /Part 0999/ });
    expect(screen.getByText("Category 09")).toBeInTheDocument();
    expect(screen.queryByText("Category 00")).toBeNull();
    expect(
      list!.querySelectorAll(":scope > [data-index]").length,
    ).toBeLessThanOrEqual(MAX_MOUNTED_ITEMS_AT_FIXTURE_VIEWPORT);
    await userEvent.click(last);
    expect(onSelect).toHaveBeenLastCalledWith(fixture[999].id);

    rerender(
      <Harness
        fixture={fixture}
        selectedId={fixture[999].id}
        duplicateIds={new Set([fixture[0].id])}
        onSelect={onSelect}
      />,
    );
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: /Part 0999/ }),
      ).toHaveAttribute("aria-current", "true"),
    );
  });

  it("keeps the one-item path in normal document flow", () => {
    const fixture = parts(1);
    const { container } = render(
      <Harness
        fixture={fixture}
        selectedId={fixture[0].id}
        onSelect={vi.fn()}
      />,
    );

    const list = container.querySelector('[data-dev-id="components.list"]');
    expect(list).toHaveAttribute("data-virtualized", "false");
    expect(
      list!.querySelectorAll('[data-dev-id="components.row"]'),
    ).toHaveLength(1);
    expect(
      list!.querySelector('[data-dev-id="components.category-header"]'),
    ).not.toBeNull();
  });

  it("drops the old virtual window when search or filtering narrows to one part", () => {
    const fixture = parts(1_000);
    const onSelect = vi.fn();
    const { container, rerender } = render(
      <Harness
        fixture={fixture}
        selectedId={fixture[0].id}
        onSelect={onSelect}
      />,
    );
    expect(
      container.querySelector('[data-dev-id="components.list"]'),
    ).toHaveAttribute("data-virtualized", "true");

    const match = fixture[999];
    rerender(
      <Harness fixture={[match]} selectedId={match.id} onSelect={onSelect} />,
    );

    const list = container.querySelector('[data-dev-id="components.list"]');
    expect(list).toHaveAttribute("data-virtualized", "false");
    expect(
      list!.querySelectorAll('[data-dev-id="components.row"]'),
    ).toHaveLength(1);
    expect(screen.getByRole("button", { name: /Part 0999/ })).toHaveAttribute(
      "aria-current",
      "true",
    );
    expect(screen.queryByRole("button", { name: /Part 0000/ })).toBeNull();
  });

  it("uses stable-id keyboard navigation without duplicate selection", async () => {
    const fixture = parts(1_000);
    const onSelect = vi.fn();
    render(<StatefulHarness fixture={fixture} onSelect={onSelect} />);

    const first = screen.getByRole("button", { name: /Part 0000/ });
    // Deliberately NOT aria-setsize / aria-posinset: `role="button"` ignores both, so asserting
    // them asserted a promise the accessibility tree never saw. Conveying "row N of M" for the
    // virtualized list needs real listbox semantics on the picker, tracked separately.
    expect(first).not.toHaveAttribute("aria-setsize");
    expect(first).not.toHaveAttribute("aria-posinset");
    first.focus();

    await userEvent.keyboard("{ArrowDown}");
    const second = await screen.findByRole("button", { name: /Part 0001/ });
    expect(second).toHaveAttribute("aria-current", "true");
    expect(second).toHaveFocus();
    expect(onSelect).toHaveBeenCalledTimes(1);
    expect(onSelect).toHaveBeenLastCalledWith("part-0001");

    const scroll = screen.getByTestId("parts-scroll");
    await userEvent.keyboard("{End}");
    expect(onSelect).toHaveBeenCalledTimes(2);
    expect(onSelect).toHaveBeenLastCalledWith("part-0999");

    // jsdom has no layout-backed scrollTo. Drive the same settled range event
    // that the browser emits after the navigation helper scrolls to the tail.
    scroll.scrollTop = 47_740;
    fireEvent.scroll(scroll);

    const last = await screen.findByRole("button", { name: /Part 0999/ });
    expect(last).toHaveAttribute("aria-current", "true");
    await waitFor(() => expect(last).toHaveFocus());

    await userEvent.keyboard("{End}");
    expect(onSelect).toHaveBeenCalledTimes(2);
  });
});
