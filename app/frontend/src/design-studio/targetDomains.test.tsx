import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { LandPattern, SymbolGeometry } from "../api/client";
import { Glb3DView } from "../components/Glb3DView";
import { FootprintPreview } from "../components/component-workspace/FootprintPreview";
import { SymbolPreview } from "../components/component-workspace/SymbolPreview";
import { applyElementOverrides } from "../lib/applyElementOverrides";
import {
  TECHNICAL_CONTENT_ATTRIBUTE,
  inspectTarget,
  previewTargetScope,
} from "./targetDomains";

vi.mock("../lib/threeScene", () => ({
  mountModelScene: () => ({
    dispose: vi.fn(),
    fit: vi.fn(),
    setView: vi.fn(),
    setSpin: vi.fn((wanted: boolean) => wanted),
    setLandPattern: vi.fn(),
    setRenderMode: vi.fn(),
    setLayers: vi.fn(),
    setPlacementMode: vi.fn(),
    modelInfo: vi.fn(() => null),
  }),
}));

type FixtureName = "currentColor SVG" | "fill SVG" | "nested text" | "mixed CAD header";

/** Builds the four mixed-markup forms without using the inspection helpers under test. */
function renderTargetFixture(name: FixtureName): HTMLElement {
  const target = document.createElement("section");
  target.dataset.devId = "detail.preview.3d.header";
  target.dataset.devRole = "detail.preview.header";
  target.className = "flex items-center";

  const textHost = name === "nested text" ? document.createElement("div") : target;
  for (let index = 1; index <= 8; index += 1) {
    const outer = document.createElement(index % 2 === 0 ? "span" : "strong");
    if (name === "nested text") {
      const inner = document.createElement("span");
      inner.dataset.copyId = `detail.preview.label-${index}`;
      inner.append(document.createTextNode(`Label ${index}`));
      outer.append(inner);
    } else {
      outer.dataset.copyId = `detail.preview.label-${index}`;
      outer.append(document.createTextNode(`Label ${index}`));
    }
    textHost.append(outer);
  }
  if (textHost !== target) target.append(textHost);

  const icon = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  icon.setAttribute("data-icon-id", "preview.expand");
  icon.setAttribute("viewBox", "0 0 24 24");
  const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
  path.setAttribute("d", "M4 12h16");
  path.setAttribute("fill", name === "fill SVG" ? "#ffffff" : "currentColor");
  icon.append(path);
  target.append(icon);

  if (name === "mixed CAD header") {
    const drawing = document.createElement("div");
    drawing.setAttribute(TECHNICAL_CONTENT_ATTRIBUTE, "true");
    drawing.innerHTML =
      '<svg><path d="M0 0h10"/><text>Engineering label</text></svg><svg data-icon-id="not-an-interface-icon"><path d="M1 1h2"/></svg>';
    target.append(drawing);
  }
  return target;
}

afterEach(() => {
  document.body.replaceChildren();
});

describe("inspectTarget", () => {
  it("inspects and edits a generated Stockroom target without an authored id", () => {
    const target = document.createElement("section");
    target.dataset.designId = "auto.generated-section.0abc123";
    target.innerHTML = '<span data-copy-id="generated.copy">Generated copy</span>';
    document.body.append(target);

    const inspection = inspectTarget(target, "auto.generated-section.0abc123");
    expect(inspection.id).toBe("auto.generated-section.0abc123");
    expect(inspection.summary.texts).toBe(1);

    applyElementOverrides({
      "auto.generated-section.0abc123": { width: "320px" },
    });
    expect(target.style.width).toBe("320px");
  });

  it.each<FixtureName>(["currentColor SVG", "fill SVG", "nested text", "mixed CAD header"])(
    "reports independent Box, Text, and Icon domains for %s",
    (fixture) => {
      const result = inspectTarget(renderTargetFixture(fixture), "detail.preview.3d.header");
      expect(result.summary).toEqual({
        boxes: 1,
        texts: 8,
        icons: 1,
        behaviors: 0,
        layout: 1,
        states: 0,
      });
      expect(result.editTargets.box).toMatchObject({
        domain: "box",
        overrideId: "detail.preview.3d.header",
        selector: ":scope",
      });
      expect(result.editTargets.text).toMatchObject({
        domain: "text",
        overrideId: "detail.preview.3d.header::text",
      });
      expect(result.editTargets.icon).toMatchObject({
        domain: "icon",
        overrideId: "detail.preview.3d.header::icon",
      });
      expect(result.editTargets.text.elements).toHaveLength(8);
      expect(result.editTargets.icon.elements).toHaveLength(1);
    },
  );

  it.each<FixtureName>(["currentColor SVG", "fill SVG", "nested text", "mixed CAD header"])(
    "applies Text and Icon writes only to their internal %s domain targets",
    (fixture) => {
      const target = renderTargetFixture(fixture);
      document.body.append(target);
      const inspection = inspectTarget(document.body, "detail.preview.3d.header");
      const textElements = [...new Set(inspection.texts.map((text) => text.element))] as HTMLElement[];
      const icon = inspection.icons[0]!.element as SVGElement;
      const technical = target.querySelector<HTMLElement>(`[${TECHNICAL_CONTENT_ATTRIBUTE}]`);

      applyElementOverrides({
        "detail.preview.3d.header::text": { "font-size": "20px" },
        "detail.preview.3d.header::icon": {
          color: "#123456",
          width: "32px",
          height: "32px",
        },
      });

      expect(target.style.fontSize).toBe("");
      expect(target.style.color).toBe("");
      expect(target.style.width).toBe("");
      expect(textElements.every((element) => element.style.fontSize === "20px")).toBe(true);
      expect(textElements.every((element) => element.style.color === "")).toBe(true);
      expect(icon.style.width).toBe("32px");
      expect(icon.style.height).toBe("32px");
      expect(icon.style.color).toBe("rgb(18, 52, 86)");
      if (fixture === "fill SVG") {
        expect(icon.querySelector<SVGElement>("path")?.style.fill).toBe("#123456");
      }
      expect(technical?.style.color ?? "").toBe("");
      expect(technical?.querySelector<SVGElement>("svg")?.style.color ?? "").toBe("");
    },
  );

  it("expands role, screen, and global scope to stable target ids before editing", () => {
    const root = document.createElement("main");
    root.innerHTML = `
      <button data-dev-id="detail.action[first]" data-dev-role="detail.action">First</button>
      <button data-dev-id="detail.action[second]" data-dev-role="detail.action">Second</button>
      <div data-dev-id="detail.summary">Summary</div>
      <div data-dev-id="rail.root">Rail</div>
    `;
    expect(previewTargetScope(root, "detail.action[first]", "role")).toEqual({
      scope: "role",
      affectedTargetIds: ["detail.action[first]", "detail.action[second]"],
    });
    expect(previewTargetScope(root, "detail.action[first]", "screen").affectedTargetIds).toEqual([
      "detail.action[first]",
      "detail.action[second]",
      "detail.summary",
    ]);
    expect(previewTargetScope(root, "detail.action[first]", "global").affectedTargetIds).toEqual([
      "detail.action[first]",
      "detail.action[second]",
      "detail.summary",
      "rail.root",
    ]);
  });
});

describe("production technical-content markers", () => {
  const geometry: SymbolGeometry = {
    units: "mm",
    name: "U",
    namesHidden: false,
    numbersHidden: false,
    pins: [],
    graphics: [
      {
        kind: "rectangle",
        points: [[0, 0], [4, 3]],
        center: [0, 0],
        radius: 0,
        width: 0.15,
        fill: "none",
        closed: true,
      },
    ],
    bounds: { x: 0, y: 0, width: 4, height: 3 },
  };
  const land: LandPattern = {
    units: "mm",
    pads: [
      {
        number: "1",
        at: [0, 0],
        size: [1, 1],
        shape: "rect",
        rotation: 0,
        drill: 0,
        pad_type: "smd",
        side: "front",
        rratio: 0,
        layers: ["F.Cu"],
      },
    ],
    graphics: [],
    model_placement: null,
  };

  it("marks the real symbol and footprint drawing roots", () => {
    const symbol = render(
      <SymbolPreview geometry={geometry} layers={{ pinName: true, pinNumber: true, electrical: true }} />,
    );
    expect(screen.getByRole("application", { name: /symbol drawing/i })).toHaveAttribute(
      TECHNICAL_CONTENT_ATTRIBUTE,
      "true",
    );
    symbol.unmount();

    render(<FootprintPreview land={land} layers={{
      copper: true,
      mask: false,
      paste: false,
      silkscreen: true,
      fabrication: false,
      courtyard: true,
      numbers: true,
      origin: false,
      dimensions: false,
    }} />);
    expect(screen.getByRole("application", { name: /land pattern drawing/i })).toHaveAttribute(
      TECHNICAL_CONTENT_ATTRIBUTE,
      "true",
    );
  });

  it("marks the real 3D model canvas", () => {
    render(
      <Glb3DView
        data={new Uint8Array([0x67, 0x6c, 0x54, 0x46]).buffer}
        isLoading={false}
        isError={false}
      />,
    );
    expect(screen.getByTestId("model-canvas")).toHaveAttribute(
      TECHNICAL_CONTENT_ATTRIBUTE,
      "true",
    );
  });
});
