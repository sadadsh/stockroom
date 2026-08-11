import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { useState } from "react";
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
      <output data-testid="inspector-draft">{JSON.stringify(dev.draft)}</output>
    </>
  );
}

function Harness() {
  const [activations, setActivations] = useState(0);
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
            onClick={() => setActivations((count) => count + 1)}
          >
            <span data-copy-id="detail.action.copy">First Action</span>
            <svg data-icon-id="action.add" viewBox="0 0 24 24"><path d="M4 12h16" /></svg>
          </button>
          <button
            type="button"
            data-dev-id="detail.action[second]"
            data-dev-role="detail.action"
          >
            <span data-copy-id="detail.action.second.copy">Second Action</span>
            <svg data-icon-id="action.edit" viewBox="0 0 24 24"><path d="M5 12h14" /></svg>
          </button>
        </section>
        <section data-dev-id="rail.root">
          <button type="button" data-dev-id="rail.action" data-dev-role="rail.action">
            <span data-copy-id="rail.action.copy">Rail Action</span>
            <svg data-icon-id="action.search" viewBox="0 0 24 24"><path d="M6 12h12" /></svg>
          </button>
        </section>
        <output data-testid="activation-count">{activations}</output>
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

  it.each([
    ["Role", ["detail.action.copy", "detail.action.second.copy"], ["action.add", "action.edit"]],
    ["Screen", ["detail.action.copy", "detail.action.second.copy"], ["action.add", "action.edit"]],
    ["Global", ["detail.action.copy", "detail.action.second.copy", "rail.action.copy"], ["action.add", "action.edit", "action.search"]],
  ] as const)(
    "applies scoped Text and Icon operations to every %s domain target shown in the preview",
    async (scope, copyIds, iconIds) => {
      render(<Harness />);
      fireEvent.click(screen.getByRole("button", { name: "Select First" }));
      fireEvent.click(screen.getByRole("button", { name: `${scope} Scope` }));

      fireEvent.click(screen.getByRole("tab", { name: "Text" }));
      expect(screen.getByLabelText("Text Domain Preview")).toHaveTextContent(copyIds.join(" "));
      fireEvent.change(screen.getByLabelText("Text Content"), { target: { value: `${scope} Text` } });
      fireEvent.change(screen.getByLabelText("Text font-size Value"), { target: { value: "18px" } });
      fireEvent.blur(screen.getByLabelText("Text font-size Value"));

      fireEvent.click(screen.getByRole("tab", { name: "Icon" }));
      expect(screen.getByLabelText("Icon Domain Preview")).toHaveTextContent(iconIds.join(" "));
      fireEvent.change(screen.getByLabelText("Icon Color"), { target: { value: "#123456" } });
      fireEvent.blur(screen.getByLabelText("Icon Color"));
      fireEvent.change(screen.getByLabelText("Icon Size"), { target: { value: "28px" } });
      fireEvent.blur(screen.getByLabelText("Icon Size"));
      const nextIcon = screen.getAllByRole("button", { name: /^Swap to / })[0]!;
      fireEvent.click(nextIcon);
      const body = screen.queryByLabelText("Edit Icon SVG Markup");
      if (body) fireEvent.change(body, { target: { value: '<path d="M2 2h20" />' } });

      await waitFor(() => {
        const draft = JSON.parse(screen.getByTestId("inspector-draft").textContent ?? "{}") as {
          copy: Record<string, string>;
          icons: Record<string, { swapToId?: string; body?: string }>;
          elements: Record<string, Record<string, string>>;
        };
        expect(Object.keys(draft.copy).sort()).toEqual([...copyIds].sort());
        expect(Object.keys(draft.icons).sort()).toEqual([...iconIds].sort());
        for (const id of copyIds) expect(draft.copy[id]).toBe(`${scope} Text`);
        for (const id of iconIds) expect(draft.icons[id]?.swapToId ?? draft.icons[id]?.body).toBeTruthy();
      });

      const expectedRoots = scope === "Global"
        ? ["detail.action[first]", "detail.action[second]", "rail.action"]
        : ["detail.action[first]", "detail.action[second]"];
      for (const id of expectedRoots) {
        const root = document.querySelector<HTMLElement>(`[data-dev-id="${id}"]`)!;
        const text = root.querySelector<HTMLElement>("[data-copy-id]")!;
        const icon = root.querySelector<SVGElement>("[data-icon-id]")!;
        expect(root.style.fontSize).toBe("");
        expect(root.style.color).toBe("");
        expect(root.style.width).toBe("");
        expect(text.style.fontSize).toBe("18px");
        expect(icon.style.width).toBe("28px");
        expect(icon.style.color).toBe("rgb(18, 52, 86)");
      }
    },
  );

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

  it("previews disabled controls visibly, suppresses activation, and restores every interactive state", async () => {
    render(<Harness />);
    fireEvent.click(screen.getByRole("button", { name: "Select First" }));
    const target = document.querySelector<HTMLButtonElement>('[data-dev-id="detail.action[first]"]')!;
    fireEvent.click(screen.getByRole("tab", { name: "States" }));

    fireEvent.click(screen.getByRole("button", { name: "Disabled" }));
    expect(target).toBeDisabled();
    expect(target).toHaveAttribute("aria-disabled", "true");
    expect(target).toHaveAttribute("data-design-preview-state", "disabled");
    expect(target).toHaveClass("design-preview-disabled");
    fireEvent.click(target);
    expect(screen.getByTestId("activation-count")).toHaveTextContent("0");

    for (const state of ["Hover", "Focus", "Active"] as const) {
      fireEvent.click(screen.getByRole("button", { name: state }));
      expect(target).not.toBeDisabled();
      expect(target).not.toHaveAttribute("aria-disabled");
      expect(target).toHaveAttribute("data-design-preview-state", state.toLowerCase());
    }
    fireEvent.click(target);
    expect(screen.getByTestId("activation-count")).toHaveTextContent("1");

    fireEvent.click(screen.getByRole("button", { name: "Default" }));
    expect(target).not.toHaveAttribute("data-design-preview-state");
    expect(target).not.toHaveClass("design-preview-disabled");
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
