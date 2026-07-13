import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { PinoutPin } from "../api/types";
import { PinoutViewer } from "./PinoutViewer";

const PINS: PinoutPin[] = [
  { pin: "2", name: "GND" },
  { pin: "10", name: "VCC" },
  { pin: "1", name: "VIN" },
];

function names(): (string | null)[] {
  // drop the header row, read each data row's Name cell (the 2nd cell)
  return screen
    .getAllByRole("row")
    .slice(1)
    .map((r) => within(r).getAllByRole("cell")[1].textContent);
}

describe("PinoutViewer", () => {
  it("renders every pin with a count", () => {
    render(<PinoutViewer pins={PINS} />);
    expect(screen.getByText("3 Pins")).toBeInTheDocument();
    expect(screen.getByText("VIN")).toBeInTheDocument();
    expect(screen.getByText("GND")).toBeInTheDocument();
    expect(screen.getByText("VCC")).toBeInTheDocument();
  });

  it("surfaces the source and confidence when provided", () => {
    render(<PinoutViewer pins={PINS} source="datasheet" confidence="high" />);
    expect(screen.getByText(/datasheet · high/i)).toBeInTheDocument();
  });

  it("filters by pin name", async () => {
    render(<PinoutViewer pins={PINS} />);
    await userEvent.type(screen.getByRole("textbox", { name: /filter pins/i }), "vcc");
    expect(screen.getByText("VCC")).toBeInTheDocument();
    expect(screen.queryByText("GND")).not.toBeInTheDocument();
    expect(screen.queryByText("VIN")).not.toBeInTheDocument();
  });

  it("filters by pin number too", async () => {
    render(<PinoutViewer pins={PINS} />);
    await userEvent.type(screen.getByRole("textbox", { name: /filter pins/i }), "10");
    // only pin 10 (VCC) survives; pin 1 (VIN) must not match "10"
    expect(screen.getByText("VCC")).toBeInTheDocument();
    expect(screen.queryByText("VIN")).not.toBeInTheDocument();
  });

  it("says so honestly when no pin matches the filter", async () => {
    render(<PinoutViewer pins={PINS} />);
    await userEvent.type(screen.getByRole("textbox", { name: /filter pins/i }), "zzz");
    expect(screen.getByText(/no pins match/i)).toBeInTheDocument();
  });

  it("sorts by pin number numerically, not lexicographically", async () => {
    render(<PinoutViewer pins={PINS} />);
    // default: source order
    expect(names()).toEqual(["GND", "VCC", "VIN"]);
    await userEvent.click(screen.getByRole("button", { name: /sort by pin/i }));
    // 1, 2, 10 -> VIN, GND, VCC (a lexicographic sort would give 1, 10, 2)
    expect(names()).toEqual(["VIN", "GND", "VCC"]);
  });

  it("renders column headers without letterspaced uppercase (design contract)", () => {
    render(<PinoutViewer pins={PINS} />);
    const pinHeader = screen.getByRole("button", { name: /sort by pin/i });
    // The contract retires letterspaced UPPERCASE micro-labels; headers stay Title case.
    expect(pinHeader.className).not.toMatch(/\buppercase\b/);
    expect(pinHeader.className).not.toMatch(/tracking-wide/);
  });

  it("sorts by name and toggles direction on a second click", async () => {
    render(<PinoutViewer pins={PINS} />);
    await userEvent.click(screen.getByRole("button", { name: /sort by name/i }));
    expect(names()).toEqual(["GND", "VCC", "VIN"]);
    await userEvent.click(screen.getByRole("button", { name: /sort by name/i }));
    expect(names()).toEqual(["VIN", "VCC", "GND"]);
  });
});
