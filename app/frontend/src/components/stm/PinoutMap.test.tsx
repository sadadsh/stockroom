import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { PinoutMap } from "./PinoutMap";
import type { PinDTO, PinoutDTO } from "../../api/types";

function pin(over: Partial<PinDTO>): PinDTO {
  return {
    position: "1",
    position_kind: "numeric",
    lqfp_side: null,
    bga_row: null,
    bga_col: null,
    canonical_pin_name: "PA0",
    raw_pin_name: "PA0",
    pin_type: "I/O",
    electrical_class: "io",
    category: "io",
    roles: [],
    functions: [],
    alternate_functions: [],
    five_v: null,
    supply: null,
    ...over,
  };
}

const LQFP: PinoutDTO = {
  part: "STM32F407V(E-G)Tx",
  mpn_example: "STM32F407VETx",
  package: "LQFP100",
  geometry: { body_shape: "qfp", pin_count: 4, rows: null, cols: null, pitch_mm: 0.5, has_center_pad: false },
  pins: [
    pin({ position: "1", lqfp_side: "left", category: "power" }),
    pin({ position: "2", lqfp_side: "bottom", category: "io", five_v: { tolerant: true, by_family: {}, caveat: "" } }),
    pin({ position: "3", lqfp_side: "right", category: "ground" }),
    pin({ position: "4", lqfp_side: "top", category: "reset" }),
  ],
};

const BGA: PinoutDTO = {
  part: "STM32H743_BGA",
  mpn_example: "STM32H743ZITx",
  package: "TFBGA240",
  geometry: { body_shape: "bga", pin_count: 4, rows: 2, cols: 2, pitch_mm: 0.8, has_center_pad: false },
  pins: [
    pin({ position: "A1", position_kind: "alnum", bga_row: "A", bga_col: 1, category: "power" }),
    pin({ position: "A2", position_kind: "alnum", bga_row: "A", bga_col: 2, category: "io" }),
    pin({ position: "B1", position_kind: "alnum", bga_row: "B", bga_col: 1, category: "ground" }),
    pin({ position: "B2", position_kind: "alnum", bga_row: "B", bga_col: 2, category: "io" }),
  ],
};

function pads(container: HTMLElement) {
  return container.querySelectorAll("[data-position]");
}

describe("PinoutMap", () => {
  it("renders one pad per pin for an LQFP part", () => {
    const { container } = render(
      <PinoutMap pinout={LQFP} selectedPosition={null} onSelectPosition={vi.fn()} />,
    );
    expect(pads(container)).toHaveLength(4);
  });

  it("renders a BGA part's full ball field, never zero pins", () => {
    const { container } = render(
      <PinoutMap pinout={BGA} selectedPosition={null} onSelectPosition={vi.fn()} />,
    );
    expect(pads(container).length).toBe(4);
    expect(pads(container).length).toBeGreaterThan(0);
  });

  it("clicking a pad calls onSelectPosition with its position", () => {
    const onSelectPosition = vi.fn();
    const { container } = render(
      <PinoutMap pinout={LQFP} selectedPosition={null} onSelectPosition={onSelectPosition} />,
    );
    const pad3 = container.querySelector('[data-position="3"]')!;
    fireEvent.click(pad3);
    expect(onSelectPosition).toHaveBeenCalledWith("3");
  });

  it("draws the selection ring on the selected pad only", () => {
    const { container } = render(
      <PinoutMap pinout={LQFP} selectedPosition={"2"} onSelectPosition={vi.fn()} />,
    );
    const selected = container.querySelector('[data-position="2"]')!;
    const other = container.querySelector('[data-position="1"]')!;
    // the selected pad has the extra ring rect (accent stroke); the other does not
    expect(selected.querySelector('rect[stroke="var(--c-acc-strong)"]')).not.toBeNull();
    expect(other.querySelector('rect[stroke="var(--c-acc-strong)"]')).toBeNull();
  });

  it("shows the layout-unavailable state when no pads can be laid out", () => {
    const noGeom: PinoutDTO = {
      ...LQFP,
      // perimeter pins with no lqfp_side cannot be placed -> an explicit unavailable state
      pins: [pin({ position: "1", lqfp_side: null }), pin({ position: "2", lqfp_side: null })],
    };
    render(<PinoutMap pinout={noGeom} selectedPosition={null} onSelectPosition={vi.fn()} />);
    expect(screen.getByText(/Layout unavailable/i)).toBeInTheDocument();
    expect(screen.queryByTestId("pinout-map-svg")).toBeNull();
  });
});
