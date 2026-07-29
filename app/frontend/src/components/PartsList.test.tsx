import { useState } from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { PartSummary } from "../api/types";
import { PartsList } from "./PartsList";

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

describe("PartsList virtualization", () => {
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
});
