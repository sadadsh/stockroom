import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import {
  ElectricalSymbol,
  electricalSymbolForCategory,
} from "./electricalSymbolLibrary";

describe("the electrical component symbol library", () => {
  it("uses the IEC rectangular resistor rather than an ANSI zigzag or generic glyph", () => {
    const { container } = render(<ElectricalSymbol kind="resistor" />);
    const symbol = container.querySelector('[data-electrical-symbol="resistor"]')!;
    expect(symbol.querySelector("svg")).not.toBeNull();
    expect(symbol.querySelector("#rect2886-8")).not.toBeNull();
    expect(symbol.innerHTML).not.toContain("fa-");
  });

  it.each([
    ["Precision Resistors", "resistor"],
    ["Ceramic Capacitors", "capacitor"],
    ["Ferrite Beads", "inductor"],
    ["Light Emitting Diodes", "led"],
    ["MOSFETs", "transistor"],
    ["Analog Switches", "switch"],
    ["Headers and Connectors", "connector"],
    ["Crystal Oscillators", "crystal"],
    ["Transformers", "transformer"],
    ["Operational Amplifiers", "opamp"],
    ["Integrated Circuits", "ic"],
  ])("maps %s to its electrical identity", (category, expected) => {
    expect(electricalSymbolForCategory(category)).toBe(expected);
  });

  it("renders switch and IC identities from the installed symbol library", () => {
    const { container } = render(
      <>
        <ElectricalSymbol kind="switch" />
        <ElectricalSymbol kind="ic" />
      </>,
    );
    expect(container.querySelector('[data-electrical-symbol="switch"]')).not.toBeNull();
    expect(container.querySelector('[data-electrical-symbol="ic"]')).not.toBeNull();
  });
});
