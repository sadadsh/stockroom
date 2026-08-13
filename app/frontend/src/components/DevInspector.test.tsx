import { render, screen, fireEvent } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { createPortal } from "react-dom";
import { ThemeProvider } from "../lib/theme";
import { DevModeProvider, useDevMode } from "../lib/devMode";
import { DevInspector } from "./DevInspector";
import { usedVarsForElement } from "../lib/inspectVars";
import { TECHNICAL_CONTENT_ATTRIBUTE } from "../design-studio/targetDomains";

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
      <output data-testid="element-overrides">{JSON.stringify(dev.draft.elements)}</output>
      <button type="button" onClick={dev.toggle}>
        toggle-dev
      </button>
      <button type="button" onClick={dev.toggleInspect}>
        toggle-inspect
      </button>
      <button type="button" onClick={dev.toggleShowIds}>
        toggle-showids
      </button>
      <button type="button" onClick={dev.undo}>undo</button>
    </div>
  );
}

function Harness({ onAppClick }: { onAppClick?: () => void }) {
  return (
    <ThemeProvider>
      <DevModeProvider>
        <Probe />
        <div data-design-product-root data-dev-id="components.stage" data-snap="on" data-grid-size="8">
          <button
            type="button"
            data-dev-id="detail.complete-part"
            className="bg-warn text-t1"
            onClick={onAppClick}
          >
            Complete Part
          </button>
          <span data-testid="stockroom-copy" data-copy-id="brand.stockroom" data-design-id="auto.text.1234567">Stockroom</span>
          <span data-testid="mpn-copy" data-copy-id="component-browser.copy-mpn-object" data-design-id="auto.text.1234567">MPN</span>
          <div data-dev-id="detail.readiness" className="bg-raise">
            <svg className="ico" viewBox="0 0 24 24" data-testid="ico">
              <path d="M4 12h16" />
            </svg>
          </div>
          <div data-dev-id="component-browser.symbol-canvas" {...{ [TECHNICAL_CONTENT_ATTRIBUTE]: "true" }}>
            <svg data-dev-id="detail.technical-shape" data-testid="technical-shape"><path d="M0 0h10" /></svg>
          </div>
        </div>
        {createPortal(
          <div data-dev-id="provider.backdrop">
            <button type="button" data-dev-id="provider.close">Close Provider</button>
          </div>,
          document.body,
        )}
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

  it("selects an automatically exposed icon as its own editable element", () => {
    render(<Harness />);
    on("toggle-dev");
    on("toggle-inspect");

    fireEvent.click(screen.getByTestId("ico"));
    expect(screen.getByTestId("selected").textContent).toMatch(/^auto\.dom-svg\./);
    expect(screen.getByTestId("vars")).toHaveTextContent("--icon-stroke");
  });

  it("selects a technical drawing's presentation root instead of an engineering descendant", () => {
    render(<Harness />);
    on("toggle-dev");
    on("toggle-inspect");
    fireEvent.click(screen.getByTestId("technical-shape"));
    expect(screen.getByTestId("selected")).toHaveTextContent("component-browser.symbol-canvas");
  });

  it("selects Stockroom-owned portal controls outside the product root", () => {
    render(<Harness />);
    on("toggle-dev");
    on("toggle-inspect");

    fireEvent.click(screen.getByRole("button", { name: "Close Provider" }));

    expect(screen.getByTestId("selected")).toHaveTextContent("provider.close");
  });

  it("selects the exact MPN copy target instead of the shared Text component", () => {
    render(<Harness />);
    on("toggle-dev");
    on("toggle-inspect");
    fireEvent.click(screen.getByTestId("stockroom-copy"));
    const stockroomId = screen.getByTestId("selected").textContent;

    fireEvent.click(screen.getByTestId("mpn-copy"));
    const mpnId = screen.getByTestId("selected").textContent;

    expect(mpnId).toMatch(/^auto\.copy\./);
    expect(mpnId).not.toBe(stockroomId);
  });

  it("inspect-off is zero behaviour change: the app click fires and nothing is selected", () => {
    const appClick = vi.fn();
    render(<Harness onAppClick={appClick} />);
    on("toggle-dev"); // dev on, inspect OFF (default)

    fireEvent.click(screen.getByRole("button", { name: "Complete Part" }));

    expect(appClick).toHaveBeenCalledTimes(1);
    expect(screen.getByTestId("selected")).toHaveTextContent("none");
  });

  it("Show IDs renders exactly one badge per authored or generated target", () => {
    render(<Harness />);
    on("toggle-dev");
    on("toggle-showids");

    const nodeCount = document.querySelectorAll("[data-dev-id],[data-design-id]").length;
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

  it("gives every selected Stockroom element move, rotate, hide, reset, and eight resize controls", () => {
    render(<Harness />);
    on("toggle-dev");
    on("toggle-inspect");
    fireEvent.click(screen.getByRole("button", { name: "Complete Part" }));

    expect(screen.getByRole("button", { name: "Move Complete Part" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Rotate Complete Part" })).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: /Resize Complete Part/ })).toHaveLength(8);
    expect(screen.getByRole("button", { name: "Hide Complete Part" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Detach Complete Part" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Reset Complete Part" })).toBeInTheDocument();
  });

  it("rotates from the keyboard as one undoable edit", () => {
    render(<Harness />);
    on("toggle-dev");
    on("toggle-inspect");
    const target = screen.getByRole("button", { name: "Complete Part" });
    fireEvent.click(target);

    const rotate = screen.getByRole("button", { name: "Rotate Complete Part" });
    fireEvent.keyDown(rotate, { key: "ArrowRight" });
    expect(target).toHaveStyle({ transform: "rotate(15deg)" });

    on("undo");
    expect(target.style.transform).toBe("");
  });

  it("rotates around the target center with a pointer gesture", () => {
    render(<Harness />);
    on("toggle-dev");
    on("toggle-inspect");
    const target = screen.getByRole("button", { name: "Complete Part" });
    Object.defineProperty(target, "offsetWidth", { configurable: true, value: 100 });
    vi.spyOn(target, "getBoundingClientRect").mockReturnValue({
      x: 20, y: 30, left: 20, top: 30, right: 120, bottom: 70, width: 100, height: 40,
      toJSON: () => ({}),
    });
    fireEvent.click(target);

    const rotate = screen.getByRole("button", { name: "Rotate Complete Part" });
    fireEvent(rotate, new MouseEvent("pointerdown", { bubbles: true, clientX: 70, clientY: 0 }));
    fireEvent(window, new MouseEvent("pointermove", { bubbles: true, clientX: 120, clientY: 50 }));
    fireEvent(window, new MouseEvent("pointerup", { bubbles: true, clientX: 120, clientY: 50 }));

    expect(target).toHaveStyle({ transform: "rotate(90deg)" });
  });

  it("hides globally and restores the selected element with one undo", () => {
    render(<Harness />);
    on("toggle-dev");
    on("toggle-inspect");
    const target = screen.getByRole("button", { name: "Complete Part" });
    fireEvent.click(target);

    fireEvent.click(screen.getByRole("button", { name: "Hide Complete Part" }));
    expect(target).toHaveStyle({ visibility: "hidden" });
    expect(screen.getByTestId("element-overrides")).toHaveTextContent('"visibility":"hidden"');

    on("undo");
    expect(target.style.visibility).toBe("");
  });

  it("snaps one move gesture and one resize gesture into atomic undo entries", () => {
    render(<Harness />);
    on("toggle-dev");
    on("toggle-inspect");
    const target = screen.getByRole("button", { name: "Complete Part" });
    Object.defineProperty(target, "offsetWidth", { configurable: true, value: 100 });
    Object.defineProperty(target, "offsetHeight", { configurable: true, value: 40 });
    vi.spyOn(target, "getBoundingClientRect").mockReturnValue({
      x: 20, y: 30, left: 20, top: 30, right: 120, bottom: 70, width: 100, height: 40,
      toJSON: () => ({}),
    });
    fireEvent.click(target);

    const move = screen.getByRole("button", { name: "Move Complete Part" });
    fireEvent(move, new MouseEvent("pointerdown", { bubbles: true, clientX: 0, clientY: 0 }));
    fireEvent(window, new MouseEvent("pointermove", { bubbles: true, clientX: 13, clientY: 11 }));
    fireEvent(window, new MouseEvent("pointerup", { bubbles: true, clientX: 13, clientY: 11 }));
    expect(target).toHaveStyle({ position: "relative", left: "16px", top: "8px" });
    on("undo");
    expect(target.style.left).toBe("");
    expect(target.style.top).toBe("");

    const resize = screen.getByRole("button", { name: "Resize Complete Part Southeast" });
    fireEvent(resize, new MouseEvent("pointerdown", { bubbles: true, clientX: 0, clientY: 0 }));
    fireEvent(window, new MouseEvent("pointermove", { bubbles: true, clientX: 13, clientY: 10 }));
    fireEvent(window, new MouseEvent("pointerup", { bubbles: true, clientX: 13, clientY: 10 }));
    expect(target).toHaveStyle({ width: "112px", height: "48px" });
    on("undo");
    expect(target.style.width).toBe("");
    expect(target.style.height).toBe("");
  });

  it("uses Shift-click for multi-selection and hides both global targets", () => {
    render(<Harness />);
    on("toggle-dev");
    on("toggle-inspect");
    const first = screen.getByRole("button", { name: "Complete Part" });
    const second = screen.getByTestId("ico");
    fireEvent.click(first);
    fireEvent.click(second, { shiftKey: true });

    expect(screen.getByText("2 Selected")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Hide 2 Selected" }));
    expect(first).toHaveStyle({ visibility: "hidden" });
    expect(second).toHaveStyle({ visibility: "hidden" });
  });

  it("detaches into the nearest identified container and undoes both changes together", () => {
    render(<Harness />);
    on("toggle-dev");
    on("toggle-inspect");
    const target = screen.getByRole("button", { name: "Complete Part" });
    const parent = target.parentElement as HTMLElement;
    vi.spyOn(target, "getBoundingClientRect").mockReturnValue({
      x: 20, y: 30, left: 20, top: 30, right: 120, bottom: 70, width: 100, height: 40,
      toJSON: () => ({}),
    });
    fireEvent.click(target);

    fireEvent.click(screen.getByRole("button", { name: "Detach Complete Part" }));
    expect(target).toHaveStyle({ position: "absolute", width: "100px", height: "40px" });
    expect(parent).toHaveStyle({ position: "relative" });

    on("undo");
    expect(target.style.position).toBe("");
    expect(parent.style.position).toBe("");
  });

  it("moves by the active grid from the keyboard and cancels an active gesture with Escape", () => {
    render(<Harness />);
    on("toggle-dev");
    on("toggle-inspect");
    const target = screen.getByRole("button", { name: "Complete Part" });
    Object.defineProperty(target, "offsetWidth", { configurable: true, value: 100 });
    Object.defineProperty(target, "offsetHeight", { configurable: true, value: 40 });
    fireEvent.click(target);
    const move = screen.getByRole("button", { name: "Move Complete Part" });

    fireEvent.keyDown(move, { key: "ArrowRight" });
    expect(target).toHaveStyle({ position: "relative", left: "8px", top: "0px" });

    fireEvent(move, new MouseEvent("pointerdown", { bubbles: true, clientX: 0, clientY: 0 }));
    fireEvent(window, new MouseEvent("pointermove", { bubbles: true, clientX: 40, clientY: 40 }));
    fireEvent.keyDown(window, { key: "Escape" });
    expect(target).toHaveStyle({ left: "8px", top: "0px" });
  });

  it("cycles between a selected target and its identified parent with Tab", () => {
    render(<Harness />);
    on("toggle-dev");
    on("toggle-inspect");
    fireEvent.click(screen.getByRole("button", { name: "Complete Part" }));

    fireEvent.keyDown(window, { key: "Tab", shiftKey: true });
    expect(screen.getByTestId("selected")).toHaveTextContent("components.stage");
    fireEvent.keyDown(window, { key: "Tab" });
    expect(screen.getByTestId("selected")).toHaveTextContent("detail.complete-part");
  });

  it("resizes from every handle with the keyboard grid", () => {
    render(<Harness />);
    on("toggle-dev");
    on("toggle-inspect");
    const target = screen.getByRole("button", { name: "Complete Part" });
    Object.defineProperty(target, "offsetWidth", { configurable: true, value: 100 });
    Object.defineProperty(target, "offsetHeight", { configurable: true, value: 40 });
    fireEvent.click(target);

    const east = screen.getByRole("button", { name: "Resize Complete Part East" });
    fireEvent.keyDown(east, { key: "ArrowRight" });
    expect(target).toHaveStyle({ width: "108px" });
    const north = screen.getByRole("button", { name: "Resize Complete Part North" });
    fireEvent.keyDown(north, { key: "ArrowUp" });
    expect(target).toHaveStyle({ height: "48px", top: "-8px" });
  });
});
