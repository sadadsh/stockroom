import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent, within } from "@testing-library/react";
import { PinoutLegend } from "./PinoutLegend";
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
  geometry: { body_shape: "qfp", pin_count: 5, rows: null, cols: null, pitch_mm: 0.5, has_center_pad: false },
  pins: [
    pin({ position: "1", category: "gpio" }),
    pin({ position: "2", category: "gpio", five_v: { tolerant: true, by_family: {}, caveat: "" } }),
    pin({ position: "3", category: "analog" }),
    pin({ position: "4", category: "boot", roles: [{ role_name: "boot0", role_class: "boot" }] }),
    pin({
      position: "5",
      category: "debug",
      roles: [{ role_name: "swdio", role_class: "debug" }],
    }),
    pin({ position: "6", category: "power", supply: "VDD" }),
  ],
};

describe("PinoutLegend", () => {
  it("shows live per-category counts, a click lens, and the key-pin facts for a loaded part", () => {
    const onToggle = vi.fn();
    render(<PinoutLegend pinout={PINOUT} highlight={new Set()} onToggleHighlight={onToggle} />);
    // live counts: 2 gpio, 1 analog
    const gpioRow = screen.getByRole("button", { name: /GPIO/ });
    expect(within(gpioRow).getByText("2")).toBeInTheDocument();
    // clicking a category row is the highlight lens
    fireEvent.click(gpioRow);
    expect(onToggle).toHaveBeenCalledWith("gpio");
    // the build-card key-pin facts with counts
    const keyPins = screen.getByTestId("legend-key-pins");
    expect(within(keyPins).getByText("Boot straps")).toBeInTheDocument();
    expect(within(keyPins).getByText("Debug access")).toBeInTheDocument();
    expect(within(keyPins).getByText("Oscillator")).toBeInTheDocument();
    expect(within(keyPins).getByText("VDD supply")).toBeInTheDocument();
  });

  it("teaches all four encoding channels", () => {
    render(<PinoutLegend />);
    // fill = category (the saturated channel)
    expect(screen.getByText("Category")).toBeInTheDocument();
    // the full ten-bucket category vocabulary, including the io split
    expect(screen.getByText("GPIO")).toBeInTheDocument();
    expect(screen.getByText("Analog")).toBeInTheDocument();
    expect(screen.getByText("Debug")).toBeInTheDocument();
    expect(screen.getByText("Oscillator")).toBeInTheDocument();
    expect(screen.getByText("Power")).toBeInTheDocument();
    expect(screen.getByText("Ground")).toBeInTheDocument();
    expect(screen.getByText("Not Connected")).toBeInTheDocument();
    // border = role
    expect(screen.getByText("Role")).toBeInTheDocument();
    // mark = 5V tolerant
    expect(screen.getByText("5V Tolerant")).toBeInTheDocument();
    // ring = selection
    expect(screen.getByText("Selected")).toBeInTheDocument();
  });
});
