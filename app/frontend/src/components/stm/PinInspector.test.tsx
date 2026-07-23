import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { PinInspector } from "./PinInspector";
import type { PinDTO } from "../../api/types";

function pin(over: Partial<PinDTO>): PinDTO {
  return {
    position: "23",
    position_kind: "numeric",
    lqfp_side: "left",
    bga_row: null,
    bga_col: null,
    canonical_pin_name: "PA0",
    raw_pin_name: "PA0",
    pin_type: "I/O",
    electrical_class: "io",
    category: "io",
    roles: [{ role_name: "Wakeup", role_class: "wkup" }],
    functions: [{ signal: "ADC1_IN0", io_modes: "analog" }],
    alternate_functions: [
      { af_index: 1, signal: "TIM2_CH1", peripheral: "TIM2" },
      { af_index: 7, signal: "USART2_CTS", peripheral: "USART2" },
    ],
    five_v: { tolerant: true, by_family: { STM32F4: true }, caveat: "" },
    supply: null,
    ...over,
  };
}

describe("PinInspector", () => {
  it("renders every derived fact for the pin", () => {
    render(<PinInspector pin={pin({})} />);
    // names + position
    expect(screen.getByText("PA0")).toBeInTheDocument();
    expect(screen.getByText("Pin 23")).toBeInTheDocument();
    // roles
    expect(screen.getByText("Roles")).toBeInTheDocument();
    expect(screen.getByText("Wakeup")).toBeInTheDocument();
    // functions
    expect(screen.getByText("Functions")).toBeInTheDocument();
    expect(screen.getByText("ADC1_IN0")).toBeInTheDocument();
    // the full alternate-function set (read-only)
    expect(screen.getByText("Alternate Functions")).toBeInTheDocument();
    expect(screen.getByText("TIM2_CH1")).toBeInTheDocument();
    expect(screen.getByText("USART2_CTS")).toBeInTheDocument();
    expect(screen.getByText("USART2")).toBeInTheDocument();
    // 5V tolerance
    expect(screen.getByText("5V Tolerance")).toBeInTheDocument();
    expect(screen.getByText("Tolerant")).toBeInTheDocument();
  });

  it("shows the supply domain for a power pin", () => {
    render(
      <PinInspector
        pin={pin({ canonical_pin_name: "VDD", category: "power", electrical_class: "power", supply: "VDD", five_v: null })}
      />,
    );
    expect(screen.getByText("Supply")).toBeInTheDocument();
    // "VDD" is both the hero name and the supply value, so both instances render
    expect(screen.getAllByText("VDD")).toHaveLength(2);
  });

  it("shows Not applicable for a pin with no 5V fact (five_v null)", () => {
    render(<PinInspector pin={pin({ five_v: null })} />);
    expect(screen.getByText("5V Tolerance")).toBeInTheDocument();
    expect(screen.getByText("Not applicable")).toBeInTheDocument();
  });
});
