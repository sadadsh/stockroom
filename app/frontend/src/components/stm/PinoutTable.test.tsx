import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { PinoutTable } from "./PinoutTable";
import type { PinDTO, PinoutDTO } from "../../api/types";

function pin(over: Partial<PinDTO>): PinDTO {
  return {
    position: "1",
    position_kind: "numeric",
    lqfp_side: "left",
    bga_row: null,
    bga_col: null,
    canonical_pin_name: "PA0",
    raw_pin_name: "PA0",
    pin_type: "I/O",
    electrical_class: "io",
    category: "gpio",
    roles: [],
    functions: [],
    alternate_functions: [],
    five_v: null,
    supply: null,
    ...over,
  };
}

const PINOUT: PinoutDTO = {
  part: "STM32F407V(E-G)Tx",
  mpn_example: "STM32F407VET6",
  package: "LQFP100",
  geometry: { body_shape: "qfp", pin_count: 3, rows: null, cols: null, pitch_mm: 0.5, has_center_pad: false },
  pins: [
    pin({ position: "10", canonical_pin_name: "PA2" }),
    pin({
      position: "2",
      canonical_pin_name: "PA9",
      five_v: { tolerant: true, by_family: {}, caveat: "" },
      alternate_functions: [{ af_index: 7, signal: "USART1_TX", peripheral: "USART1" }],
    }),
    pin({ position: "1", canonical_pin_name: "VDD", category: "power" }),
  ],
};

describe("PinoutTable", () => {
  it("lists every pin numeric-aware (1, 2, 10 - never lexicographic)", () => {
    render(<PinoutTable pinout={PINOUT} selectedPosition={null} onSelectPosition={vi.fn()} />);
    const cells = screen
      .getAllByRole("row")
      .slice(1)
      .map((r) => r.querySelector("td")?.textContent);
    expect(cells).toEqual(["1", "2", "10"]);
  });

  it("carries the AF set with indices and marks 5V tolerance", () => {
    render(<PinoutTable pinout={PINOUT} selectedPosition={null} onSelectPosition={vi.fn()} />);
    expect(screen.getByText(/AF7 USART1_TX/)).toBeInTheDocument();
    expect(screen.getByText("FT")).toBeInTheDocument();
  });

  it("clicking a row selects that pin (the same selection model as the map)", () => {
    const onSelect = vi.fn();
    render(<PinoutTable pinout={PINOUT} selectedPosition={null} onSelectPosition={onSelect} />);
    fireEvent.click(screen.getByText("PA9"));
    expect(onSelect).toHaveBeenCalledWith("2");
  });

  it("marks the selected row", () => {
    render(<PinoutTable pinout={PINOUT} selectedPosition="2" onSelectPosition={vi.fn()} />);
    const row = screen.getByText("PA9").closest("tr")!;
    expect(row.getAttribute("aria-selected")).toBe("true");
  });
});
