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
});
