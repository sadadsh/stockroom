import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import {
  ElectricalSymbol,
  electricalSymbolForCategory,
} from "./electricalSymbolLibrary";
import { ICON_BY_ID } from "./iconRegistry";

describe("the electrical component symbol library", () => {
  it("renders category marks through the shared 24px interface grammar", () => {
    const { container } = render(<ElectricalSymbol kind="resistor" />);
    const symbol = container.querySelector('[data-electrical-symbol="resistor"]')!;
    const svg = symbol.querySelector("svg");
    expect(svg).not.toBeNull();
    expect(svg).toHaveClass("ico");
    expect(svg).toHaveAttribute("viewBox", "0 0 24 24");
    expect(svg).toHaveAttribute("stroke-width", "2");
    expect(svg).toHaveAttribute("fill", "none");
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
    ["ICs", "ic"],
    ["Switches", "switch"],
    ["ESD Protection", "generic"],
  ])("maps %s to its electrical identity", (category, expected) => {
    expect(electricalSymbolForCategory(category)).toBe(expected);
  });

  it.each([
    "Switching Voltage Regulators",
    "LED Drivers",
    "Motor Drivers",
    "Safety",
    "Hardware",
    "Modules",
    "Other",
    "",
  ])("uses a neutral generic mark for unsupported category %s", (category) => {
    expect(electricalSymbolForCategory(category)).toBe("generic");
  });

  it("does not let token substrings impersonate an electrical category", () => {
    expect(electricalSymbolForCategory("Safety Equipment")).toBe("generic");
    expect(electricalSymbolForCategory("Cellular Modules")).toBe("generic");
    expect(electricalSymbolForCategory("Switching Controllers")).toBe("generic");
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

  it("uses truthful circuit drawings when the upstream family has no matching component mark", () => {
    for (const id of [
      "category.crystal",
      "category.fuse",
      "category.led",
      "category.opamp",
      "category.transformer",
      "category.transistor",
    ]) {
      expect(ICON_BY_ID.get(id), id).toMatchObject({
        family: "stockroom-electrical",
        viewBox: "0 0 24 24",
        strokeWidth: 2,
      });
    }
    expect(ICON_BY_ID.get("category.generic")).toMatchObject({
      family: "tabler-outline",
      sourceIcon: "category",
      viewBox: "0 0 24 24",
      strokeWidth: 2,
    });
    expect(ICON_BY_ID.get("category.ic")?.sourceIcon).toBe("cpu");
    expect(ICON_BY_ID.get("layer.board")?.sourceIcon).toBe("layout-board");
  });
});
