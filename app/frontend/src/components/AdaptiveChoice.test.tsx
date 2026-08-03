import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ThemeProvider } from "../lib/theme";
import { DevModeProvider, useDevMode } from "../lib/devMode";
import { AdaptiveChoice } from "./AdaptiveChoice";

const handleChoiceChange = vi.fn();

function Harness() {
  const dev = useDevMode();
  return (
    <>
      <button onClick={() => dev.setBehaviorOverride("test.choice", { preset: "segmented" })}>
        Segment
      </button>
      <button onClick={() => dev.setBehaviorOverride("test.choice", { preset: "radio" })}>
        Radio
      </button>
      <button onClick={() => dev.setBehaviorOverride("test.choice", { preset: "searchable" })}>
        Search
      </button>
      <AdaptiveChoice
        devId="test.choice"
        label="Test Choice"
        value="b"
        onChange={handleChoiceChange}
        options={[{ value: "a", label: "Alpha" }, { value: "b", label: "Beta" }]}
      />
    </>
  );
}

describe("AdaptiveChoice", () => {
  it("swaps presentation without changing its semantic value", () => {
    render(<ThemeProvider><DevModeProvider><Harness /></DevModeProvider></ThemeProvider>);
    expect(screen.getByRole("combobox", { name: "Test Choice" })).toHaveValue("b");
    fireEvent.click(screen.getByRole("button", { name: "Segment" }));
    expect(screen.getByRole("radiogroup", { name: "Test Choice" })).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: "Beta" })).toHaveAttribute("aria-checked", "true");
    fireEvent.click(screen.getByRole("button", { name: "Radio" }));
    expect(screen.getByRole("radio", { name: "Beta" })).toBeChecked();
  });

  it("lets a searchable preset clear, choose, and restore the controlled label", () => {
    handleChoiceChange.mockClear();
    render(<ThemeProvider><DevModeProvider><Harness /></DevModeProvider></ThemeProvider>);
    fireEvent.click(screen.getByRole("button", { name: "Search" }));
    const search = screen.getByLabelText("Test Choice");
    expect(search).toHaveValue("Beta");
    fireEvent.focus(search);
    expect(search).toHaveValue("");
    fireEvent.change(search, { target: { value: "Alpha" } });
    expect(handleChoiceChange).toHaveBeenCalledWith("a");
    expect(search).toHaveValue("Beta");
  });
});
