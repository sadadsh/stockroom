import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { PinoutLegend } from "./PinoutLegend";

describe("PinoutLegend", () => {
  it("teaches all four encoding channels", () => {
    render(<PinoutLegend />);
    // fill = category (the saturated channel)
    expect(screen.getByText("Category")).toBeInTheDocument();
    expect(screen.getByText("I/O")).toBeInTheDocument();
    expect(screen.getByText("Power")).toBeInTheDocument();
    expect(screen.getByText("Ground")).toBeInTheDocument();
    // border = role
    expect(screen.getByText("Role")).toBeInTheDocument();
    // mark = 5V tolerant
    expect(screen.getByText("5V Tolerant")).toBeInTheDocument();
    // ring = selection
    expect(screen.getByText("Selected")).toBeInTheDocument();
  });
});
