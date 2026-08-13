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
      <button
        type="button"
        onClick={() => {
          if (!dev.enabled) dev.toggle();
          dev.selectDevId("auto.raw-svg.0abc123");
        }}
      >
        Select Raw Icon
      </button>
      <button
        type="button"
        onClick={() => {
          if (!dev.enabled) dev.toggle();
          dev.selectDevId("auto.copy.0fedcba");
        }}
      >
        Select Text Only
      </button>
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
        <svg data-design-id="auto.raw-svg.0abc123" viewBox="0 0 24 24"><path d="M3 12h18" /></svg>
        <span data-copy-id="component-browser.key-specs-title" data-design-id="auto.copy.0fedcba">Main Specifications</span>
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
  function openGroup(name: string) {
    const button = screen.getByRole("button", { name });
    if (button.getAttribute("aria-expanded") !== "true") fireEvent.click(button);
  }

  it("groups every editing capability into six plain-language sections", async () => {
    render(<Harness />);
    fireEvent.click(screen.getByRole("button", { name: "Select First" }));

    expect(screen.getAllByText("First Action")).toHaveLength(2);
    for (const facet of ["Quick", "Arrangement", "Appearance", "Content", "States", "Advanced"]) {
      expect(screen.getByRole("button", { name: facet })).toBeEnabled();
    }
    expect(screen.queryAllByRole("tab")).toHaveLength(0);
    openGroup("Content");
    fireEvent.change(screen.getByLabelText("Icon Stroke"), { target: { value: "2.4" } });
    await waitFor(() => {
      const draft = JSON.parse(screen.getByTestId("inspector-draft").textContent ?? "{}") as {
        icons: Record<string, { strokeWidth?: number }>;
      };
      expect(draft.icons["action.add"]?.strokeWidth).toBe(2.4);
      expect(draft.icons["action.edit"]).toBeUndefined();
    });
  });

  it("opens the complete offline icon library instead of hiding it behind quick picks", async () => {
    render(<Harness />);
    fireEvent.click(screen.getByRole("button", { name: "Select First" }));
    openGroup("Content");
    fireEvent.click(screen.getByRole("button", { name: "Choose Icon" }));

    expect(await screen.findByRole("searchbox", { name: "Search Icon Catalog" })).toBeVisible();
    expect(await screen.findByText(/offline icons/)).toBeVisible();
    expect(screen.getByRole("combobox", { name: "Icon Library" })).toContainHTML("Lucide");
  });

  it("offers the complete library for a raw automatically exposed interface SVG", async () => {
    render(<Harness />);
    fireEvent.click(screen.getByRole("button", { name: "Select Raw Icon" }));
    openGroup("Content");
    fireEvent.click(screen.getByRole("button", { name: "Choose Icon" }));

    expect(await screen.findByRole("searchbox", { name: "Search Icon Catalog" })).toBeVisible();
    expect(screen.queryByText("The icon is not registered.")).toBeNull();
  });

  it("adds an offline icon to a text-only element", async () => {
    render(<Harness />);
    fireEvent.click(screen.getByRole("button", { name: "Select Text Only" }));
    openGroup("Content");
    fireEvent.click(screen.getByRole("button", { name: "Choose Icon" }));

    const search = await screen.findByRole("searchbox", { name: "Search Icon Catalog" });
    fireEvent.change(search, { target: { value: "github" } });
    fireEvent.click(await screen.findByRole("button", { name: "Select github from Font Awesome brands" }));

    await waitFor(() => {
      const draft = JSON.parse(screen.getByTestId("inspector-draft").textContent ?? "{}") as {
        icons: Record<string, { insertInto?: string }>;
      };
      expect(Object.values(draft.icons)).toContainEqual(expect.objectContaining({
        insertInto: "auto.copy.0fedcba",
      }));
      expect(document.querySelector('[data-design-inserted-icon]')).not.toBeNull();
    });

  });

  it("applies Main Specifications text settings only to that selected text target", async () => {
    render(<Harness />);
    fireEvent.click(screen.getByRole("button", { name: "Select Text Only" }));
    openGroup("Content");
    fireEvent.change(screen.getByLabelText("Text font-size Value"), { target: { value: "22" } });

    await waitFor(() => {
      const heading = document.querySelector<HTMLElement>('[data-copy-id="component-browser.key-specs-title"]')!;
      const unrelated = document.querySelector<HTMLElement>('[data-copy-id="detail.action.copy"]')!;
      expect(heading.style.fontSize).toBe("22px");
      expect(unrelated.style.fontSize).toBe("");
    });
  });

  it("edits every global occurrence and removal is undoable", async () => {
    render(<Harness />);
    fireEvent.click(screen.getByRole("button", { name: "Select First" }));
    const first = document.querySelector<HTMLElement>('[data-dev-id="detail.action[first]"]')!;
    const second = document.querySelector<HTMLElement>('[data-dev-id="detail.action[second]"]')!;
    expect(first.style.display).toBe("");
    expect(second.style.display).toBe("");

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

  it(
    "keeps content edits on the exact selected copy and icon while styling semantic occurrences",
    async () => {
      const copyIds = ["detail.action.copy"];
      const iconIds = ["action.add"];
      render(<Harness />);
      fireEvent.click(screen.getByRole("button", { name: "Select First" }));

      openGroup("Advanced");
      expect(screen.getByLabelText("Text Domain Preview")).toHaveTextContent(copyIds.join(" "));
      expect(screen.getByLabelText("Icon Domain Preview")).toHaveTextContent(iconIds.join(" "));
      openGroup("Advanced");
      openGroup("Content");
      fireEvent.change(screen.getByLabelText("Text Content"), { target: { value: "Global Text" } });
      expect(screen.getByLabelText("Text font-size Value")).toHaveAttribute("type", "range");
      fireEvent.change(screen.getByLabelText("Text font-size Value"), { target: { value: "18" } });

      fireEvent.change(screen.getByLabelText("Icon Color"), { target: { value: "#123456" } });
      expect(screen.getByLabelText("Icon Color")).toHaveAttribute("type", "color");
      fireEvent.change(screen.getByLabelText("Icon Size"), { target: { value: "28" } });
      fireEvent.change(screen.getByLabelText("Treatment"), { target: { value: "solid" } });
      fireEvent.change(screen.getByLabelText("Alignment"), { target: { value: "text-top" } });
      fireEvent.change(screen.getByLabelText("Accessible Label"), { target: { value: "Add item" } });
      fireEvent.click(screen.getByRole("button", { name: "Choose Icon" }));
      fireEvent.change(await screen.findByRole("searchbox", { name: "Search Icon Catalog" }), { target: { value: "github" } });
      fireEvent.click(await screen.findByRole("button", { name: "Select github from Font Awesome brands" }));
      const body = screen.queryByLabelText("Edit Icon SVG Markup");
      if (body) fireEvent.change(body, { target: { value: '<path d="M2 2h20" />' } });

      await waitFor(() => {
        const draft = JSON.parse(screen.getByTestId("inspector-draft").textContent ?? "{}") as {
          copy: Record<string, string>;
          icons: Record<string, { swapToId?: string; body?: string; treatment?: string; alignment?: string; a11yLabel?: string }>;
          elements: Record<string, Record<string, string>>;
        };
        expect(Object.keys(draft.copy).sort()).toEqual([...copyIds].sort());
        expect(Object.keys(draft.icons).sort()).toEqual([...iconIds].sort());
        for (const id of copyIds) expect(draft.copy[id]).toBe("Global Text");
        expect(draft.copy["detail.action.second.copy"]).toBeUndefined();
        expect(draft.icons["action.edit"]).toBeUndefined();
        for (const id of iconIds) {
          expect(draft.icons[id]?.swapToId ?? draft.icons[id]?.body).toBeTruthy();
          expect(draft.icons[id]).toMatchObject({ treatment: "solid", alignment: "text-top", a11yLabel: "Add item" });
        }
      });

      const expectedRoots = ["detail.action[first]", "detail.action[second]"];
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
    openGroup("Advanced");

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
    openGroup("States");

    fireEvent.click(screen.getByRole("button", { name: "Disabled" }));
    expect(target).toBeDisabled();
    expect(target).toHaveAttribute("aria-disabled", "true");
    expect(target).toHaveAttribute("data-design-preview-state", "disabled");
    expect(target).toHaveClass("design-preview-disabled");
    fireEvent.click(target);
    expect(screen.getByTestId("activation-count")).toHaveTextContent("0");

    fireEvent.change(screen.getByLabelText("State Color"), { target: { value: "#123456" } });
    await waitFor(() => {
      const draft = JSON.parse(screen.getByTestId("inspector-draft").textContent ?? "{}") as {
        elements: Record<string, Record<string, string>>;
      };
      expect(draft.elements["detail.action[first]::state:disabled"]?.color).toBe("#123456");
      expect(draft.elements["detail.action[second]::state:disabled"]?.color).toBe("#123456");
    });

    for (const state of ["Hover", "Focus", "Active", "Selected"] as const) {
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

    openGroup("Arrangement");
    expect(screen.getByLabelText("Width Value")).toHaveAttribute("type", "range");
    expect(screen.getByLabelText("Display Value")).toHaveRole("combobox");
    fireEvent.change(screen.getByLabelText("Width Value"), { target: { value: "240" } });
    await waitFor(() => expect(first.style.width).toBe("240px"));
    fireEvent.click(screen.getByRole("button", { name: "Reset Width" }));
    await waitFor(() => expect(first.style.width).toBe(""));

    openGroup("Quick");
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
