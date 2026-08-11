import { describe, expect, it, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { SpecMatrixTable } from "./SpecMatrixTable";
import type { McuSpecRow } from "../../api/types";

function row(over: Partial<McuSpecRow>): McuSpecRow {
  return {
    part: "REFNAME",
    mpn_example: "STM32X",
    series: "STM32F4",
    line: "STM32F407",
    core: "Cortex-M4",
    package: "LQFP100",
    pin_count: 100,
    io_count: 82,
    flash_kb: 512,
    ram_kb: 192,
    max_freq_mhz: 168,
    vdd_min: 1.8,
    vdd_max: 3.6,
    temp_min_c: -40,
    temp_max_c: 85,
    peripherals: { USART: 4, SPI: 3 },
    ...over,
  };
}

const ROWS: McuSpecRow[] = [
  row({ part: "STM32F407V(E-G)Tx", mpn_example: "STM32F407VETx", core: "Cortex-M4", io_count: 82 }),
  row({
    part: "STM32H743Z(G-I)Tx",
    mpn_example: "STM32H743ZITx",
    series: "STM32H7",
    core: "Cortex-M7",
    io_count: 168,
    flash_kb: 2048,
  }),
];

describe("SpecMatrixTable", () => {
  it("renders the ST-MCU-FINDER columns", () => {
    render(<SpecMatrixTable rows={ROWS} activePart={null} onSelectPart={vi.fn()} />);
    for (const header of ["Part", "Core", "Series", "Package", "IOs", "Flash", "RAM", "Frequency", "USART", "SPI"]) {
      expect(screen.getByText(header)).toBeInTheDocument();
    }
  });

  it("keeps the first paint bounded instead of committing every row", () => {
    // A5. The virtualizer measures its scroll container, and a container that has not been
    // laid out yet (the first paint, and every jsdom render) measures 0 height - which yields
    // zero virtual items. The old fallback took that as "virtualization is unavailable" and
    // rendered modelRows in full: thousands of rows x 14 columns on the very first commit.
    // The initialRect guard PartsList and SearchOverlay already carry keeps the window bounded.
    const many = Array.from({ length: 2_000 }, (_, index) =>
      row({
        part: `STM32REF${index}`,
        mpn_example: `STM32MPN${index}`,
      }),
    );
    render(<SpecMatrixTable rows={many} activePart={null} onSelectPart={vi.fn()} />);

    const body = screen.getByTestId("spec-matrix-scroll");
    const rendered = Array.from(body.querySelectorAll("button")).filter((node) =>
      /STM32MPN\d+/.test(node.textContent ?? ""),
    );
    expect(rendered.length).toBeGreaterThan(0);
    expect(rendered.length).toBeLessThan(200);
    // The count line still reports the whole model, so nothing about the data is hidden.
    expect(screen.getByText("All 2,000 parts shown")).toBeInTheDocument();
  });

  it("strips the Arm Cortex- prefix from the Core cell so the tier is readable", () => {
    render(
      <SpecMatrixTable
        rows={[row({ part: "STM32F429ZITx", mpn_example: "STM32F429ZITx", core: "Arm Cortex-M4" })]}
        activePart={null}
        onSelectPart={vi.fn()}
      />,
    );
    expect(screen.getByText("M4")).toBeInTheDocument();
    expect(screen.queryByText("Arm Cortex-M4")).toBeNull();
  });

  it("the Columns popover hides and restores a column without squishing the rest", async () => {
    render(<SpecMatrixTable rows={ROWS} activePart={null} onSelectPart={vi.fn()} />);
    // the Series header (a sort button) is present, and its cells render
    expect(screen.getByRole("button", { name: /^Series/ })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Columns" }));
    const picker = screen.getByTestId("column-picker");
    // Part is the row identity and never hideable
    expect(within(picker).queryByLabelText("Part")).toBeNull();
    await userEvent.click(within(picker).getByLabelText("Series"));
    expect(screen.queryByRole("button", { name: /^Series/ })).toBeNull();
    await userEvent.click(within(picker).getByLabelText("Series"));
    expect(screen.getByRole("button", { name: /^Series/ })).toBeInTheDocument();
  });

  it("consumes Escape when closing the Columns popover", async () => {
    const escapedToParent = vi.fn();
    window.addEventListener("keydown", escapedToParent);
    try {
      render(<SpecMatrixTable rows={ROWS} activePart={null} onSelectPart={vi.fn()} />);
      await userEvent.click(screen.getByRole("button", { name: "Columns" }));
      expect(screen.getByTestId("column-picker")).toBeVisible();

      await userEvent.keyboard("{Escape}");

      expect(screen.queryByTestId("column-picker")).not.toBeInTheDocument();
      expect(escapedToParent).not.toHaveBeenCalled();
    } finally {
      window.removeEventListener("keydown", escapedToParent);
    }
  });

  it("shows mpn_example in the Part cell and never the raw ref_name", () => {
    render(<SpecMatrixTable rows={ROWS} activePart={null} onSelectPart={vi.fn()} />);
    expect(screen.getByText("STM32F407VETx")).toBeInTheDocument();
    expect(screen.getByText("STM32H743ZITx")).toBeInTheDocument();
    // the ref_name wildcard is never visible text (Pitfall 1)
    expect(screen.queryByText("STM32F407V(E-G)Tx")).toBeNull();
    expect(screen.queryByText("STM32H743Z(G-I)Tx")).toBeNull();
  });

  it("a column filter narrows the visible rows client-side (no api dependency)", async () => {
    render(<SpecMatrixTable rows={ROWS} activePart={null} onSelectPart={vi.fn()} />);
    // both rows visible to start
    expect(screen.getByText("STM32F407VETx")).toBeInTheDocument();
    expect(screen.getByText("STM32H743ZITx")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Filters" }));
    await userEvent.type(screen.getByLabelText("Filter Part"), "F407");

    expect(screen.getByText("STM32F407VETx")).toBeInTheDocument();
    expect(screen.queryByText("STM32H743ZITx")).toBeNull();
  });

  it("the free-text search box narrows rows client-side", async () => {
    render(<SpecMatrixTable rows={ROWS} activePart={null} onSelectPart={vi.fn()} />);
    await userEvent.type(screen.getByLabelText("Search Parts"), "H743");
    expect(screen.getByText("STM32H743ZITx")).toBeInTheDocument();
    expect(screen.queryByText("STM32F407VETx")).toBeNull();
  });

  it("clicking a row calls onSelectPart with the row's part (ref_name)", async () => {
    const onSelectPart = vi.fn();
    render(<SpecMatrixTable rows={ROWS} activePart={null} onSelectPart={onSelectPart} />);
    await userEvent.click(screen.getByText("STM32F407VETx"));
    expect(onSelectPart).toHaveBeenCalledWith("STM32F407V(E-G)Tx");
  });

  it("marks the active row", () => {
    render(
      <SpecMatrixTable rows={ROWS} activePart={"STM32H743Z(G-I)Tx"} onSelectPart={vi.fn()} />,
    );
    const activeRow = screen.getByText("STM32H743ZITx").closest("button")!;
    expect(activeRow).toHaveAttribute("aria-current", "true");
    // sanity: the other row is not marked
    const otherRow = screen.getByText("STM32F407VETx").closest("button")!;
    expect(within(otherRow).queryByText("STM32H743ZITx")).toBeNull();
    expect(otherRow).not.toHaveAttribute("aria-current");
  });

  // The column edge is a real separator control, so it has to be reachable and drivable without a
  // pointer: it takes focus, the arrows nudge the width, and Home puts it back.
  it("resizes a column from the keyboard and resets it with Home", async () => {
    render(<SpecMatrixTable rows={ROWS} activePart={null} onSelectPart={vi.fn()} />);
    const handle = screen.getByTestId("col-resize-flash_kb");
    expect(handle).toHaveAttribute("tabindex", "0");
    expect(handle).toHaveAttribute("aria-orientation", "vertical");

    const header = handle.parentElement!;
    const widthOf = () => header.parentElement!.style.gridTemplateColumns;
    const initial = widthOf();

    handle.focus();
    expect(handle).toHaveFocus();
    await userEvent.keyboard("{ArrowRight}");
    const widened = widthOf();
    expect(widened).not.toBe(initial);

    await userEvent.keyboard("{ArrowLeft}");
    expect(widthOf()).toBe(initial);

    await userEvent.keyboard("{ArrowRight}{ArrowRight}");
    expect(widthOf()).not.toBe(initial);
    await userEvent.keyboard("{Home}");
    expect(widthOf()).toBe(initial);
  });
});
