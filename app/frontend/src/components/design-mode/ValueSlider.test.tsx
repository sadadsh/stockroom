import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { ValueSlider } from "./ValueSlider";
import { ThemeProvider } from "../../lib/theme";
import { DevModeProvider, useDevMode } from "../../lib/devMode";
// @ts-expect-error Vitest executes this assertion in Node; browser bundles exclude Node types.
import { readFileSync } from "node:fs";

function HistoryHarness() {
  const dev = useDevMode();
  const value = Number.parseFloat(dev.draft.elements["slider.fixture"]?.width ?? "1");
  return (
    <>
      <button type="button" onClick={dev.toggle}>Enable</button>
      <button type="button" onClick={dev.undo}>Undo</button>
      <button type="button" onClick={() => dev.setElementProp("slider.fixture", "width", "48px")}>Set 48</button>
      <output data-testid="history-draft">{JSON.stringify(dev.draft.elements["slider.fixture"] ?? {})}</output>
      <ValueSlider
        ariaLabel="History Width"
        value={value}
        min={1}
        max={64}
        step={1}
        unit="px"
        onChange={(next) => dev.setElementProp("slider.fixture", "width", `${next}px`)}
      />
    </>
  );
}

function renderHistoryHarness() {
  render(
    <ThemeProvider>
      <DevModeProvider><HistoryHarness /></DevModeProvider>
    </ThemeProvider>,
  );
  fireEvent.click(screen.getByRole("button", { name: "Enable" }));
}

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

  it("records one undo entry for a complete pointer slide", () => {
    renderHistoryHarness();
    const slider = screen.getByRole("slider", { name: "History Width" });

    fireEvent.pointerDown(slider, { pointerId: 7 });
    for (const value of [12, 24, 36]) fireEvent.change(slider, { target: { value: String(value) } });
    fireEvent.pointerUp(slider, { pointerId: 7 });
    fireEvent.click(screen.getByRole("button", { name: "Undo" }));

    expect(screen.getByTestId("history-draft")).toHaveTextContent("{}");
  });

  it("ends a pointer transaction when release happens outside the slider", () => {
    renderHistoryHarness();
    const slider = screen.getByRole("slider", { name: "History Width" });

    fireEvent.pointerDown(slider, { pointerId: 11 });
    for (const value of [12, 24, 36]) fireEvent.change(slider, { target: { value: String(value) } });
    fireEvent.pointerUp(window, { pointerId: 11 });
    fireEvent.click(screen.getByRole("button", { name: "Set 48" }));
    fireEvent.click(screen.getByRole("button", { name: "Undo" }));

    expect(screen.getByTestId("history-draft")).toHaveTextContent('"width":"36px"');
    fireEvent.click(screen.getByRole("button", { name: "Undo" }));
    expect(screen.getByTestId("history-draft")).toHaveTextContent("{}");
  });

  it("records a held keyboard slider change as one undo entry", () => {
    renderHistoryHarness();
    const slider = screen.getByRole("slider", { name: "History Width" });

    fireEvent.keyDown(slider, { key: "ArrowRight" });
    for (const value of [2, 3, 4]) {
      fireEvent.keyDown(slider, { key: "ArrowRight", repeat: value > 2 });
      fireEvent.change(slider, { target: { value: String(value) } });
    }
    fireEvent.keyUp(slider, { key: "ArrowRight" });
    fireEvent.click(screen.getByRole("button", { name: "Undo" }));

    expect(screen.getByTestId("history-draft")).toHaveTextContent("{}");
  });

  it("records one exact-number typing session as one undo entry", () => {
    renderHistoryHarness();
    const exact = screen.getByRole("spinbutton", { name: "History Width Exact" });

    fireEvent.focus(exact);
    for (const value of ["12", "24", "36"]) fireEvent.change(exact, { target: { value } });
    fireEvent.blur(exact);
    fireEvent.click(screen.getByRole("button", { name: "Undo" }));

    expect(screen.getByTestId("history-draft")).toHaveTextContent("{}");
  });
});
