import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { ValueSlider } from "./ValueSlider";
// @ts-expect-error Vitest executes this assertion in Node; browser bundles exclude Node types.
import { readFileSync } from "node:fs";

describe("ValueSlider", () => {
  it("always shows the exact current value and unit", () => {
    render(
      <ValueSlider
        ariaLabel="Grid Size"
        value={8}
        min={1}
        max={64}
        step={1}
        unit="px"
        onChange={() => {}}
      />,
    );

    expect(screen.getByRole("slider", { name: "Grid Size" })).toHaveValue("8");
    expect(screen.getByRole("spinbutton", { name: "Grid Size Exact" })).toHaveValue(8);
    expect(screen.getByText("px")).toBeVisible();
  });

  it("updates from the slider and clamps exact entry to the accepted range", async () => {
    const onChange = vi.fn();
    render(
      <ValueSlider
        ariaLabel="Grid Size"
        value={8}
        min={1}
        max={64}
        step={1}
        unit="px"
        onChange={onChange}
      />,
    );

    fireEvent.change(screen.getByRole("slider", { name: "Grid Size" }), {
      target: { value: "12" },
    });
    expect(onChange).toHaveBeenLastCalledWith(12);

    const exact = screen.getByRole("spinbutton", { name: "Grid Size Exact" });
    await userEvent.setup().clear(exact);
    await userEvent.setup().type(exact, "99");
    fireEvent.blur(exact);
    expect(onChange).toHaveBeenLastCalledWith(64);
  });

  it("owns every Design Studio range so no slider can hide its value", () => {
    const sources = [
      "src/components/DevPanel.tsx",
      "src/components/design-mode/DesignStudioToolbar.tsx",
      "src/components/design-mode/ArrangeSurface.tsx",
      "src/components/design-mode/inspectors/VisualCssControl.tsx",
      "src/components/design-mode/inspectors/IconInspector.tsx",
      "src/components/design-mode/inspectors/CadPresentationInspector.tsx",
    ];
    for (const source of sources) {
      expect(readFileSync(source, "utf8"), source).not.toContain('type="range"');
    }
  });
});
