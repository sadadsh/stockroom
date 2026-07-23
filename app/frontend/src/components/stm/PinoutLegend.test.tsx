import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { PinoutLegend } from "./PinoutLegend";

describe("PinoutLegend", () => {
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
