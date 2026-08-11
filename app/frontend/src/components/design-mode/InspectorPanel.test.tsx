import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { DevModeProvider, useDevMode } from "../../lib/devMode";
import { ThemeProvider } from "../../lib/theme";
import { InspectorPanel } from "./InspectorPanel";

function Controls() {
  const dev = useDevMode();
  return (
    <>
      <button
        type="button"
        onClick={() => {
          if (!dev.enabled) dev.toggle();
          dev.selectDevId("detail.action[first]");
        }}
      >
        Select First
      </button>
      <button type="button" onClick={dev.undo}>Undo Inspector</button>
      <button type="button" onClick={() => dev.setToken("--c-acc", "#123456")}>Set Accent</button>
    </>
  );
}

function Harness() {
  return (
    <ThemeProvider>
      <DevModeProvider>
        <Controls />
        <section data-dev-id="detail.header">
          <button
            type="button"
            data-dev-id="detail.action[first]"
            data-dev-role="detail.action"
            data-dev-control="choice"
          >
            <span data-copy-id="detail.action.copy">First Action</span>
            <svg data-icon-id="action.add" viewBox="0 0 24 24"><path d="M4 12h16" /></svg>
          </button>
          <button
            type="button"
            data-dev-id="detail.action[second]"
            data-dev-role="detail.action"
          >
            Second Action
          </button>
        </section>
        <InspectorPanel />
      </DevModeProvider>
    </ThemeProvider>
  );
}

afterEach(() => {
  document.documentElement.removeAttribute("style");
  document.documentElement.removeAttribute("data-theme");
});

describe("InspectorPanel", () => {
  it("shows independent domains and every focused inspector", async () => {
    render(<Harness />);
    fireEvent.click(screen.getByRole("button", { name: "Select First" }));

    expect(screen.getByText("Box 1 · Text 1 · Icon 1")).toBeInTheDocument();
    for (const facet of ["Box", "Text", "Icon", "Arrangement", "Behavior", "States", "Advanced"]) {
      expect(screen.getByRole("tab", { name: facet })).toBeEnabled();
    }
    fireEvent.click(screen.getByRole("tab", { name: "Icon" }));
    fireEvent.change(screen.getByLabelText("Icon Stroke"), { target: { value: "2.4" } });
    await waitFor(() => expect(document.documentElement.style.getPropertyValue("--icon-stroke")).toBe("2.4"));
  });

  it("previews every affected role id before a broad edit and removal is undoable", async () => {
    render(<Harness />);
    fireEvent.click(screen.getByRole("button", { name: "Select First" }));
    fireEvent.click(screen.getByRole("button", { name: "Role Scope" }));

    expect(screen.getByText("Role · 2 Targets")).toBeInTheDocument();
    expect(screen.getByText("detail.action[first]")).toBeInTheDocument();
    expect(screen.getByText("detail.action[second]")).toBeInTheDocument();
    const first = document.querySelector<HTMLElement>('[data-dev-id="detail.action[first]"]')!;
    const second = document.querySelector<HTMLElement>('[data-dev-id="detail.action[second]"]')!;
    expect(first.style.display).toBe("");
    expect(second.style.display).toBe("");

    fireEvent.click(screen.getByRole("tab", { name: "Arrangement" }));
    fireEvent.click(screen.getByRole("button", { name: "Remove From Arrangement" }));
    await waitFor(() => {
      expect(first.style.display).toBe("none");
      expect(second.style.display).toBe("none");
    });

    fireEvent.click(screen.getByRole("button", { name: "Undo Inspector" }));
    await waitFor(() => {
      expect(first.style.display).toBe("");
      expect(second.style.display).toBe("");
    });
  });

  it("accepts only the validated property grammar in Advanced", async () => {
    render(<Harness />);
    fireEvent.click(screen.getByRole("button", { name: "Select First" }));
    fireEvent.click(screen.getByRole("tab", { name: "Advanced" }));

    expect(screen.getByText(/DOM structure cannot be edited/i)).toBeInTheDocument();
    expect(screen.queryByLabelText(/HTML|JavaScript/i)).not.toBeInTheDocument();
    const value = screen.getByLabelText("Advanced Value");
    fireEvent.change(value, { target: { value: "</style><script>alert(1)</script>" } });
    expect(screen.getByRole("button", { name: "Set Validated Value" })).toBeDisabled();

    fireEvent.change(value, { target: { value: "320px" } });
    fireEvent.click(screen.getByRole("button", { name: "Set Validated Value" }));
    await waitFor(() => {
      expect(
        document.querySelector<HTMLElement>('[data-dev-id="detail.action[first]"]')!.style.width,
      ).toBe("320px");
    });
  });

  it("resets property, target, screen, theme, and the full personal design without deleting markup", async () => {
    render(<Harness />);
    fireEvent.click(screen.getByRole("button", { name: "Select First" }));
    const first = document.querySelector<HTMLElement>('[data-dev-id="detail.action[first]"]')!;
    const second = document.querySelector<HTMLElement>('[data-dev-id="detail.action[second]"]')!;

    fireEvent.change(screen.getByLabelText("Width Value"), { target: { value: "240px" } });
    fireEvent.blur(screen.getByLabelText("Width Value"));
    await waitFor(() => expect(first.style.width).toBe("240px"));
    fireEvent.click(screen.getByRole("button", { name: "Reset Width" }));
    await waitFor(() => expect(first.style.width).toBe(""));

    fireEvent.click(screen.getByRole("button", { name: "Role Scope" }));
    fireEvent.click(screen.getByRole("tab", { name: "Arrangement" }));
    fireEvent.click(screen.getByRole("button", { name: "Remove From Arrangement" }));
    await waitFor(() => expect(second.style.display).toBe("none"));
    fireEvent.click(screen.getByRole("button", { name: "Target" }));
    await waitFor(() => {
      expect(first.style.display).toBe("");
      expect(second.style.display).toBe("none");
    });
    fireEvent.click(screen.getByRole("button", { name: "Screen" }));
    await waitFor(() => expect(second.style.display).toBe(""));

    fireEvent.click(screen.getByRole("button", { name: "Set Accent" }));
    await waitFor(() => expect(document.documentElement.style.getPropertyValue("--c-acc")).toBe("#123456"));
    fireEvent.click(screen.getByRole("button", { name: "Theme" }));
    await waitFor(() => expect(document.documentElement.style.getPropertyValue("--c-acc")).toBe(""));

    expect(screen.getByRole("button", { name: "Variation" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Full Personal Design" }));
    expect(document.querySelector('[data-dev-id="detail.action[first]"]')).toBeInTheDocument();
    expect(document.querySelector('[data-dev-id="detail.action[second]"]')).toBeInTheDocument();
  });
});
