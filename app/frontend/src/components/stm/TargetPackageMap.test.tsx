/**
 * The universal-MCU package map's own contract. It shares the zoom chamber with PinoutMap and
 * CompatUnionMap, and like them it holds a d3 subscription for as long as it is mounted - so the
 * teardown is part of the contract, not an implementation detail.
 */
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { TargetDefinitionPosition } from "../../api/types";
import { TargetPackageMap } from "./TargetPackageMap";

function position(over: Partial<TargetDefinitionPosition>): TargetDefinitionPosition {
  return {
    position: "1",
    position_kind: "numeric",
    lqfp_side: "left",
    bga_row: null,
    bga_col: null,
    silicon_class: "stable_io",
    board_action: "direct",
    universal_primitive: "universal-breakout",
    identities: ["PA0"],
    access_tags: [],
    access_tags_union: [],
    present_on: 1,
    total_targets: 1,
    route_ids: [],
    hazard: "",
    per_target: [],
    ...over,
  };
}

const POSITIONS = [
  position({ position: "1", lqfp_side: "left" }),
  position({ position: "2", lqfp_side: "bottom" }),
  position({ position: "3", lqfp_side: "right" }),
  position({ position: "4", lqfp_side: "top" }),
];

function renderMap() {
  return render(
    <TargetPackageMap
      packageName="LQFP4"
      positions={POSITIONS}
      lens="compatibility"
      selectedPosition={null}
      onSelectPosition={vi.fn()}
    />,
  );
}

describe("TargetPackageMap", () => {
  it("lays one pad per position out on the shared pinout geometry", () => {
    const { container } = renderMap();
    expect(screen.getByTestId("target-package-map-svg")).toBeInTheDocument();
    expect(container.querySelectorAll("[data-position]")).toHaveLength(4);
  });

  // The zoom behavior is a subscription: `selection.call(behavior)` installs `.zoom` listeners on the
  // SVG node, and nothing removes them unless the effect's cleanup does. Asserting on the rendered
  // camera would prove nothing here - React 18 drops a state update on an unmounted tree silently, so
  // a leaked listener looks identical to a released one from the DOM side. d3 records every accepted
  // gesture on the node itself as `__zoom`, so that is the honest witness: it moves while the
  // listeners live and must not move once they are gone.
  it("retires its zoom listeners on unmount, so a gesture on the discarded node is not handled", () => {
    const { unmount } = renderMap();
    const svg = screen.getByTestId("target-package-map-svg") as unknown as SVGSVGElement & {
      __zoom?: unknown;
    };
    const cameraGroup = svg.querySelector("g")!;

    // mounted: the wheel gesture is handled - it moves d3's node transform AND the rendered camera
    fireEvent.wheel(svg, { deltaY: -400 });
    const handled = svg.__zoom;
    expect(handled).toBeDefined();
    expect(cameraGroup.getAttribute("transform")).not.toBe("translate(0,0) scale(1)");

    unmount();

    // unmounted: this test still holds the node, but no listener of ours may remain on it
    fireEvent.wheel(svg, { deltaY: -400 });
    expect(svg.__zoom).toBe(handled);
  });
});
