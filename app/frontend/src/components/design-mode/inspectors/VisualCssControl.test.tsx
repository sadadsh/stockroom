import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { VisualCssControl } from "./VisualCssControl";

describe("VisualCssControl", () => {
  it("uses bounded visual controls instead of CSS text entry", () => {
    const width = vi.fn();
    const display = vi.fn();
    const color = vi.fn();
    const view = render(
      <>
        <VisualCssControl property="width" ariaLabel="Width Value" value="240px" onCommit={width} />
        <VisualCssControl property="display" ariaLabel="Display Value" value="flex" onCommit={display} />
        <VisualCssControl property="background-color" ariaLabel="Background Color Value" value="rgb(18, 52, 86)" onCommit={color} />
      </>,
    );

    const widthControl = screen.getByRole("slider", { name: "Width Value" });
    expect(widthControl).toHaveValue("240");
    fireEvent.change(widthControl, { target: { value: "320" } });
    expect(width).toHaveBeenLastCalledWith("320px");

    const displayControl = screen.getByRole("combobox", { name: "Display Value" });
    fireEvent.change(displayControl, { target: { value: "grid" } });
    expect(display).toHaveBeenLastCalledWith("grid");

    const colorControl = screen.getByLabelText("Background Color Value");
    expect(colorControl).toHaveAttribute("type", "color");
    expect(colorControl).toHaveValue("#123456");
    fireEvent.change(colorControl, { target: { value: "#abcdef" } });
    expect(color).toHaveBeenLastCalledWith("#abcdef");

    expect(view.container.querySelector('input[type="text"]')).toBeNull();
  });

  it("offers visual presets for effects and typography", () => {
    const onCommit = vi.fn();
    render(
      <>
        <VisualCssControl property="box-shadow" ariaLabel="Shadow Value" value="none" onCommit={onCommit} />
        <VisualCssControl property="font-family" ariaLabel="Font Family Value" value="system-ui" onCommit={onCommit} />
        <VisualCssControl property="opacity" ariaLabel="Opacity Value" value="0.5" onCommit={onCommit} />
      </>,
    );

    expect(screen.getByRole("combobox", { name: "Shadow Value" })).toBeVisible();
    expect(screen.getByRole("combobox", { name: "Font Family Value" })).toBeVisible();
    expect(screen.getByRole("slider", { name: "Opacity Value" })).toHaveValue("0.5");
  });
});
