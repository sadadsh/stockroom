import { render, screen, fireEvent } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ThemeProvider } from "../lib/theme";
import { DevModeProvider, useDevMode } from "../lib/devMode";
import { DevInspector } from "./DevInspector";
import { usedVarsForElement } from "../lib/inspectVars";

afterEach(() => {
  document.documentElement.removeAttribute("style");
  document.documentElement.removeAttribute("data-theme");
});

// A probe that surfaces the selection state as text and exposes buttons to flip the toggles, so a
// test can drive dev mode without the full panel.
function Probe() {
  const dev = useDevMode();
  return (
    <div>
      <div data-testid="selected">{dev.selectedDevId ?? "none"}</div>
      <div data-testid="vars">{dev.highlightedVars.join(",")}</div>
      <button type="button" onClick={dev.toggle}>
        toggle-dev
      </button>
      <button type="button" onClick={dev.toggleInspect}>
        toggle-inspect
      </button>
      <button type="button" onClick={dev.toggleShowIds}>
        toggle-showids
      </button>
    </div>
  );
}

function Harness({ onAppClick }: { onAppClick?: () => void }) {
  return (
    <ThemeProvider>
      <DevModeProvider>
        <Probe />
        <button
          type="button"
          data-dev-id="detail.complete-part"
          className="bg-warn text-t1"
          onClick={onAppClick}
        >
          Complete Part
        </button>
        <div data-dev-id="detail.readiness" className="bg-raise">
          <svg className="ico" viewBox="0 0 24 24" data-testid="ico">
            <path d="M4 12h16" />
          </svg>
        </div>
        <DevInspector />
      </DevModeProvider>
    </ThemeProvider>
  );
}

function on(label: string) {
  fireEvent.click(screen.getByText(label));
}

describe("usedVarsForElement", () => {
  it("resolves className tokens and adds --icon-stroke by element type", () => {
    const btn = document.createElement("button");
    btn.setAttribute("class", "bg-warn text-t1 p-2");
    expect(usedVarsForElement(btn)).toEqual(["--c-warn", "--c-t1"]);

    const wrap = document.createElement("div");
    wrap.setAttribute("class", "bg-raise");
    wrap.innerHTML = '<svg class="ico"></svg>';
    expect(usedVarsForElement(wrap)).toEqual(["--c-raise", "--icon-stroke"]);

    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("class", "ico");
    expect(usedVarsForElement(svg)).toEqual(["--icon-stroke"]);
  });
});

describe("DevInspector", () => {
  it("inspect-on click swallows the app click and selects the element + its used vars", () => {
    const appClick = vi.fn();
    render(<Harness onAppClick={appClick} />);
    on("toggle-dev");
    on("toggle-inspect");

    fireEvent.click(screen.getByRole("button", { name: "Complete Part" }));

    expect(appClick).not.toHaveBeenCalled(); // the click is swallowed in inspect mode
    expect(screen.getByTestId("selected")).toHaveTextContent("detail.complete-part");
    expect(screen.getByTestId("vars")).toHaveTextContent("--c-warn,--c-t1");
  });

  it("adds --icon-stroke when the inspected element contains an svg.ico", () => {
    render(<Harness />);
    on("toggle-dev");
    on("toggle-inspect");

    fireEvent.click(screen.getByTestId("ico"));
    expect(screen.getByTestId("selected")).toHaveTextContent("detail.readiness");
    expect(screen.getByTestId("vars")).toHaveTextContent("--c-raise,--icon-stroke");
  });

  it("inspect-off is zero behaviour change: the app click fires and nothing is selected", () => {
    const appClick = vi.fn();
    render(<Harness onAppClick={appClick} />);
    on("toggle-dev"); // dev on, inspect OFF (default)

    fireEvent.click(screen.getByRole("button", { name: "Complete Part" }));

    expect(appClick).toHaveBeenCalledTimes(1);
    expect(screen.getByTestId("selected")).toHaveTextContent("none");
  });

  it("Show IDs renders exactly one badge per [data-dev-id] node", () => {
    render(<Harness />);
    on("toggle-dev");
    on("toggle-showids");

    const nodeCount = document.querySelectorAll("[data-dev-id]").length;
    expect(nodeCount).toBe(2);
    expect(screen.getAllByTestId("dev-id-badge")).toHaveLength(nodeCount);
  });

  it("detaches its listeners when dev mode turns off (no swallow after disable)", () => {
    const appClick = vi.fn();
    render(<Harness onAppClick={appClick} />);
    on("toggle-dev");
    on("toggle-inspect");
    on("toggle-dev"); // disable dev mode again

    fireEvent.click(screen.getByRole("button", { name: "Complete Part" }));
    expect(appClick).toHaveBeenCalledTimes(1); // listener removed, so the click passes through
    expect(screen.getByTestId("selected")).toHaveTextContent("none");
  });
});
