import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { LandPattern, SymbolGeometry } from "../../../api/client";
import { inspectTarget } from "../../../design-studio/targetDomains";
import { FootprintPreview } from "../../component-workspace/FootprintPreview";
import { SymbolPreview } from "../../component-workspace/SymbolPreview";
import { CadPresentationInspector } from "./CadPresentationInspector";

const studio = vi.hoisted(() => ({
  resolvedCadPresentation: {} as Record<string, unknown>,
  setCadPresentation: vi.fn(),
  resetCadPresentation: vi.fn(),
}));

vi.mock("../../../design-studio/DesignStudioProvider", () => ({
  useOptionalDesignStudio: () => studio,
}));

const geometry: SymbolGeometry = {
  units: "mm",
  name: "U",
  namesHidden: false,
  numbersHidden: false,
  pins: [],
  graphics: [{ kind: "rectangle", points: [[0, 0], [4, 3]], center: [0, 0], radius: 0, width: 0.15, fill: "none", closed: true }],
  bounds: { x: 0, y: 0, width: 4, height: 3 },
};

const land: LandPattern = {
  units: "mm",
  pads: [{ number: "1", at: [0, 0], size: [1, 1], shape: "rect", rotation: 0, drill: 0, pad_type: "smd", side: "front", rratio: 0, layers: ["F.Cu"] }],
  graphics: [],
  model_placement: null,
};

beforeEach(() => {
  studio.resolvedCadPresentation = {};
  studio.setCadPresentation.mockReset();
  studio.resetCadPresentation.mockReset();
});

describe("CadPresentationInspector", () => {
  it("edits the typed presentation target exposed by the selected Stockroom container", () => {
    const host = document.createElement("section");
    host.dataset.devId = "component-browser.asset";
    host.dataset.designCadKind = "symbol";
    host.dataset.designCadTarget = "cad.symbol";
    document.body.append(host);
    const inspection = inspectTarget(document.body, "component-browser.asset");
    render(<CadPresentationInspector inspection={inspection} inspections={[inspection]} affectedTargetIds={[inspection.id]} setDomainProperty={vi.fn()} resetDomainProperty={vi.fn()} />);

    fireEvent.click(screen.getByRole("checkbox", { name: "Outline" }));
    expect(studio.setCadPresentation).toHaveBeenCalledWith("cad.symbol", "symbol", { body: false }, false);
    fireEvent.click(screen.getByRole("button", { name: "Reset CAD Presentation" }));
    expect(studio.resetCadPresentation).toHaveBeenCalledWith("cad.symbol");
    host.remove();
  });

  it("changes rendered symbol and footprint presentation without changing source geometry", () => {
    studio.resolvedCadPresentation = {
      "cad.symbol": { symbol: { body: false } },
      "cad.footprint": { footprint: { pads: false } },
    };
    const symbol = render(<SymbolPreview geometry={geometry} layers={{ pinName: true, pinNumber: true, electrical: true }} />);
    expect(symbol.container.querySelector("rect")).toBeNull();
    expect(geometry.graphics).toHaveLength(1);
    symbol.unmount();

    const footprint = render(<FootprintPreview land={land} layers={{ copper: true, mask: false, paste: false, silkscreen: true, fabrication: false, courtyard: true, numbers: true, origin: false, dimensions: false }} />);
    expect(footprint.container.querySelector("[data-pad]")).toBeNull();
    expect(land.pads).toHaveLength(1);
  });
});
