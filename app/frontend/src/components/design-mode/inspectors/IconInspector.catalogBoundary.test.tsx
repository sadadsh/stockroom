import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { inspectTarget } from "../../../design-studio/targetDomains";
import { DevModeProvider } from "../../../lib/devMode";
import { ThemeProvider } from "../../../lib/theme";
import { IconInspector } from "./IconInspector";

const boundary = vi.hoisted(() => ({ moduleLoads: 0, renders: 0 }));

vi.mock("../IconBrowser", () => {
  boundary.moduleLoads += 1;
  return {
    IconBrowser: () => {
      boundary.renders += 1;
      return <p>Loaded Icon Browser</p>;
    },
  };
});

afterEach(() => {
  document.querySelector('[data-dev-id="catalog.boundary"]')?.remove();
});

describe("IconInspector catalogue bundle boundary", () => {
  it("keeps the optional catalogue dormant until the picker opens", async () => {
    const target = document.createElement("button");
    target.setAttribute("data-dev-id", "catalog.boundary");
    const icon = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    icon.setAttribute("data-icon-id", "action.add");
    icon.setAttribute("viewBox", "0 0 24 24");
    target.append(icon);
    document.body.append(target);
    const inspection = inspectTarget(document.documentElement, "catalog.boundary");

    render(
      <ThemeProvider>
        <DevModeProvider>
          <IconInspector
            inspection={inspection}
            inspections={[inspection]}
            affectedTargetIds={[inspection.overrideId]}
            setDomainProperty={vi.fn()}
            resetDomainProperty={vi.fn()}
          />
        </DevModeProvider>
      </ThemeProvider>,
    );

    expect(boundary.moduleLoads).toBe(0);
    expect(boundary.renders).toBe(0);

    await userEvent.click(screen.getByRole("button", { name: "Choose Icon" }));

    expect(await screen.findByText("Loaded Icon Browser")).toBeVisible();
    expect(boundary.moduleLoads).toBe(1);
    expect(boundary.renders).toBe(1);
  });
});
