import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ThemeProvider } from "./theme";
import { DevModeProvider } from "./devMode";
import { Text } from "./copy";
import { DevPanel } from "../components/DevPanel";
import { api } from "../api/client";

vi.mock("../api/client", async (importActual) => {
  const actual = await importActual<typeof import("../api/client")>();
  return {
    ...actual,
    api: {
      ...actual.api,
      devSave: vi.fn().mockResolvedValue({ ok: true, written: [], tokens: 0, copy: 0 }),
    },
  };
});

const mockApi = vi.mocked(api);

afterEach(() => {
  // token edits set inline CSS vars on <html>; clear them so tests don't leak into each other
  document.documentElement.removeAttribute("style");
  document.documentElement.removeAttribute("data-theme");
});

function Harness() {
  return (
    <ThemeProvider>
      <DevModeProvider>
        <button type="button">
          Run <Text id="test.label">Original</Text>
        </button>
        <DevPanel />
      </DevModeProvider>
    </ThemeProvider>
  );
}

function toggleDevMode() {
  fireEvent.keyDown(window, { key: "D", ctrlKey: true, shiftKey: true });
}

describe("dev mode", () => {
  it("is hidden until Ctrl+Shift+D and a label renders plainly meanwhile", () => {
    render(<Harness />);
    expect(screen.queryByText("Save to source")).not.toBeInTheDocument();
    // off dev mode the label is a bare string inside the button, not an editable target
    expect(screen.getByRole("button", { name: /Run Original/ })).toBeInTheDocument();
    expect(document.querySelector("[data-copy-id]")).toBeNull();

    toggleDevMode();
    expect(screen.getByText("Save to source")).toBeInTheDocument();
    // now the label is wrapped as an editable target
    expect(document.querySelector('[data-copy-id="test.label"]')).not.toBeNull();

    // toggling again closes it
    toggleDevMode();
    expect(screen.queryByText("Save to source")).not.toBeInTheDocument();
  });

  it("nudges a colour token live and resets it to the shipped default", () => {
    render(<Harness />);
    toggleDevMode();

    const accValue = screen.getByLabelText("Accent value");
    fireEvent.change(accValue, { target: { value: "#123456" } });
    expect(document.documentElement.style.getPropertyValue("--c-acc")).toBe("#123456");

    // an override adds a reset control; resetting clears the inline var so it falls back to CSS
    fireEvent.click(screen.getByLabelText("Reset to default"));
    expect(document.documentElement.style.getPropertyValue("--c-acc")).toBe("");
  });

  it("edits a label's copy in place through the panel", () => {
    render(<Harness />);
    toggleDevMode();

    // clicking the label (without firing its button) selects it for editing
    fireEvent.click(screen.getByText("Original"));
    const editor = screen.getByLabelText("Edit copy text");
    expect(editor).toHaveValue("Original");

    fireEvent.change(editor, { target: { value: "Reworded" } });
    // the live label (the wrapped span) reflects the new copy immediately
    const label = document.querySelector('[data-copy-id="test.label"]');
    expect(label).toHaveTextContent("Reworded");
    expect(label).not.toHaveTextContent("Original");
  });

  it("saves the working overrides to source only when dirty", async () => {
    render(<Harness />);
    toggleDevMode();

    // nothing changed yet: Save is disabled
    expect(screen.getByRole("button", { name: "Save to source" })).toBeDisabled();

    fireEvent.change(screen.getByLabelText("Accent value"), { target: { value: "#abcdef" } });
    const save = screen.getByRole("button", { name: "Save to source" });
    expect(save).toBeEnabled();
    fireEvent.click(save);

    await waitFor(() => expect(mockApi.devSave).toHaveBeenCalledTimes(1));
    const arg = mockApi.devSave.mock.calls[0][0];
    expect(arg.tokens.root["--c-acc"]).toBe("#abcdef");
  });

  it("nudges a type-scale size live (px unit) and resets it to the shipped default", () => {
    render(<Harness />);
    toggleDevMode();

    const smValue = screen.getByLabelText("SM value");
    fireEvent.change(smValue, { target: { value: "20" } });
    expect(document.documentElement.style.getPropertyValue("--fs-sm")).toBe("20px");

    fireEvent.click(screen.getByLabelText("Reset to default"));
    expect(document.documentElement.style.getPropertyValue("--fs-sm")).toBe("");
  });

  it("nudges the unitless icon stroke live (no px unit appended)", () => {
    render(<Harness />);
    toggleDevMode();

    fireEvent.change(screen.getByLabelText("Icon stroke value"), { target: { value: "2.6" } });
    expect(document.documentElement.style.getPropertyValue("--icon-stroke")).toBe("2.6");
  });

  it("edits a shadow token as raw text and saves it under the active theme block", async () => {
    render(<Harness />);
    toggleDevMode();

    const shadow = screen.getByLabelText("Card shadow");
    fireEvent.change(shadow, { target: { value: "0 2px 4px rgba(0, 0, 0, 0.5)" } });
    expect(document.documentElement.style.getPropertyValue("--shadow-card")).toBe(
      "0 2px 4px rgba(0, 0, 0, 0.5)",
    );

    fireEvent.click(screen.getByRole("button", { name: "Save to source" }));
    await waitFor(() => expect(mockApi.devSave).toHaveBeenCalledTimes(1));
    const arg = mockApi.devSave.mock.calls[0][0];
    // dark is the default theme, so a themed shadow lands in the root (dark) block
    expect(arg.tokens.root["--shadow-card"]).toBe("0 2px 4px rgba(0, 0, 0, 0.5)");
  });
});
