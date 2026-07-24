import { describe, expect, it } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { CompatUnionMap } from "./CompatUnionMap";
import type { UnionDTO, UnionPositionDTO } from "../../api/types";

function pos(over: Partial<UnionPositionDTO>): UnionPositionDTO {
  return {
    position: "1",
    position_kind: "numeric",
    lqfp_side: "left",
    bga_row: null,
    bga_col: null,
    classification: "shared",
    present_on: 2,
    total: 2,
    per_part: [],
    reconcile: null,
    ...over,
  };
}

function union(positions: UnionPositionDTO[]): UnionDTO {
  return {
    parts: ["STM32F407VETx", "STM32F407VGTx"],
    resolved: [
      { ref: "A", mpn: "STM32F407VETx" },
      { ref: "B", mpn: "STM32F407VGTx" },
    ],
    package: "LQFP100",
    family: "STM32F4",
    grain: "per-part",
    positions,
    verdict: { interchangeable: true, swaps_required: 0, blocking: [] },
  };
}

// The dedicated classification token set (unionClassificationHue), the CSS-var fills the SVG
// classification dot paints with. A distinct family from the electrical-class pin hues.
const TONE_FILL = {
  shared: "var(--stm-classify-shared)",
  divergent: "var(--stm-classify-divergent)",
  partial: "var(--stm-classify-partial)",
};

function padFill(container: HTMLElement, position: string): string | null {
  return container.querySelector(`[data-position="${position}"] rect.pad`)?.getAttribute("fill") ?? null;
}

describe("CompatUnionMap", () => {
  it("fills each pad with its own --stm-classify token (shared/divergent/partial)", () => {
    const { container } = render(
      <CompatUnionMap
        union={union([
          pos({ position: "1", lqfp_side: "left", classification: "shared" }),
          pos({ position: "2", lqfp_side: "bottom", classification: "divergent" }),
          pos({ position: "3", lqfp_side: "right", classification: "partial" }),
        ])}
      />,
    );
    expect(padFill(container, "1")).toBe(TONE_FILL.shared);
    expect(padFill(container, "2")).toBe(TONE_FILL.divergent);
    expect(padFill(container, "3")).toBe(TONE_FILL.partial);
  });

  it("lays the union out on the reused pinout geometry as an SVG map, one pad per position, never a flat table", () => {
    const { container } = render(
      <CompatUnionMap
        union={union([
          pos({ position: "1", lqfp_side: "left" }),
          pos({ position: "2", lqfp_side: "bottom" }),
          pos({ position: "3", lqfp_side: "right" }),
          pos({ position: "4", lqfp_side: "top" }),
        ])}
      />,
    );
    expect(screen.getByTestId("compat-union-map-svg")).toBeInTheDocument();
    expect(container.querySelectorAll("[data-position]")).toHaveLength(4);
    // it is a geometry map, not the flat pin-list fallback
    expect(screen.queryByTestId("compat-union-list")).toBeNull();
  });

  it("lays a BGA union out on the same ball-grid geometry, never zero pads", () => {
    const { container } = render(
      <CompatUnionMap
        union={union([
          pos({ position: "A1", position_kind: "alnum", lqfp_side: null, bga_row: "A", bga_col: 1 }),
          pos({ position: "A2", position_kind: "alnum", lqfp_side: null, bga_row: "A", bga_col: 2, classification: "divergent" }),
          pos({ position: "B1", position_kind: "alnum", lqfp_side: null, bga_row: "B", bga_col: 1 }),
        ])}
      />,
    );
    expect(screen.getByTestId("compat-union-map-svg")).toBeInTheDocument();
    expect(container.querySelectorAll("[data-position]").length).toBe(3);
  });

  it("falls back to a clickable classification list when no layout can be drawn", () => {
    render(
      <CompatUnionMap
        union={union([
          pos({ position: "1", lqfp_side: null, classification: "shared" }),
          pos({ position: "2", lqfp_side: null, classification: "divergent" }),
        ])}
      />,
    );
    expect(screen.getByTestId("compat-union-list")).toBeInTheDocument();
    expect(screen.queryByTestId("compat-union-map-svg")).toBeNull();
  });

  it("teaches the shared / divergent / partial legend and does not paint per-part facts on the pads", () => {
    const { container } = render(
      <CompatUnionMap
        union={union([
          pos({
            position: "1",
            lqfp_side: "left",
            classification: "divergent",
            per_part: [{ ref: "A", canonical_pin_name: "PA0", roles: ["gpio"], functions: ["USART2_TX"] }],
          }),
        ])}
      />,
    );
    // the legend teaches all three classifications
    expect(screen.getAllByText("Shared").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Divergent").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Partial").length).toBeGreaterThan(0);
    // the per-part signal is NOT painted onto the map (it is click detail only)
    expect(container.textContent).not.toContain("USART2_TX");
  });

  it("reveals the per-part audit trail only AFTER a divergent pad is clicked, never in the initial render", () => {
    const { container } = render(
      <CompatUnionMap
        union={union([
          pos({
            position: "23",
            lqfp_side: "left",
            classification: "divergent",
            per_part: [
              { ref: "STM32F407VE", canonical_pin_name: "PA0", roles: ["gpio"], functions: ["USART2_CTS"] },
            ],
            reconcile: {
              swappable: true,
              swaps: [{ ref: "STM32F407VE", target_signal: "USART2_TX", via_af_index: 7 }],
              reason: null,
            },
          }),
        ])}
      />,
    );
    // initial render: no reconcile detail, no per-part trail
    expect(screen.queryByTestId("compat-reconcile-detail")).toBeNull();
    expect(screen.queryByTestId("compat-per-part")).toBeNull();

    fireEvent.click(container.querySelector('[data-position="23"]')!);

    // after the click: the detail + per-part trail + reconciling swap appear
    expect(screen.getByTestId("compat-reconcile-detail")).toBeInTheDocument();
    expect(screen.getByTestId("compat-per-part")).toBeInTheDocument();
    expect(screen.getByText("USART2_TX")).toBeInTheDocument();
  });
});
