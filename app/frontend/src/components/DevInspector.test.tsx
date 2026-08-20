import { act, render, screen, fireEvent, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { createPortal } from "react-dom";
import { ThemeProvider } from "../lib/theme";
import { DevModeProvider, useDevMode } from "../lib/devMode";
import { DevInspector } from "./DevInspector";
import { Button } from "./primitives";
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
      <div data-testid="selected-override">{dev.selectedTarget?.overrideId ?? "none"}</div>
      <div data-testid="selected-version">{dev.selectedTarget?.element.getAttribute("data-occurrence-version") ?? "none"}</div>
      <div data-testid="selected-copy">{dev.selectedCopyId ?? "none"}</div>
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
      <button type="button" onClick={() => {
        if (dev.selectedTarget) dev.setElementProp(dev.selectedTarget.overrideId, "width", "120px");
      }}>set-selected-width-120</button>
      <button type="button" onClick={() => {
        if (dev.selectedTarget) dev.setElementProp(dev.selectedTarget.overrideId, "width", "240px");
      }}>set-selected-width-240</button>
      <button type="button" onClick={() => {
        dev.setElementProp("detail.readiness", "width", "320px");
      }}>set-unrelated-width</button>
    </div>
  );
}

function Harness({
  onAppClick,
  onChromePointerDown,
  occurrenceVersion = "initial",
  readinessTransform,
  readinessClassTransform = false,
  insertEarlierPeer = false,
  hideRepeatedSecond = false,
  uniqueVersion = "initial",
  insertUniquePeer = false,
  hideUniqueTarget = false,
}: {
  onAppClick?: () => void;
  onChromePointerDown?: () => void;
  occurrenceVersion?: string;
  readinessTransform?: string;
  readinessClassTransform?: boolean;
  insertEarlierPeer?: boolean;
  hideRepeatedSecond?: boolean;
  uniqueVersion?: string;
  insertUniquePeer?: boolean;
  hideUniqueTarget?: boolean;
}) {
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
          <span data-testid="mpn-copy" data-copy-id="component-browser.copy-mpn-object" data-design-id="auto.text.1234567"><strong data-testid="mpn-copy-child">MPN</strong></span>
          {readinessClassTransform ? <style>{`.authored-transform { transform: translateX(10px) scale(2); }`}</style> : null}
          {insertEarlierPeer ? <button key="inserted" type="button" data-testid="repeated-inserted" data-design-id="auto.repeated-action.1234567">Repeated Inserted</button> : null}
          <Button key={`first-${occurrenceVersion}`} type="button" data-testid="repeated-first" data-design-id="auto.repeated-action.1234567">Repeated First</Button>
          {!hideRepeatedSecond ? <Button key={`second-${occurrenceVersion}`} type="button" data-testid="repeated-second" data-design-id="auto.repeated-action.1234567">Repeated Second</Button> : null}
          {!hideUniqueTarget ? <Button
            key={`unique-${uniqueVersion}`}
            type="button"
            data-testid={`unique-target-${uniqueVersion}`}
            data-occurrence-version={uniqueVersion}
            data-design-id="auto.unique-action.1234567"
          >Unique Target</Button> : null}
          {insertUniquePeer ? <Button type="button" data-testid="unique-target-peer" data-design-id="auto.unique-action.1234567">Unique Peer</Button> : null}
          <div data-dev-id="detail.readiness" className={`bg-raise${readinessClassTransform ? " authored-transform" : ""}`} style={{ transform: readinessTransform }}>
            <svg className="ico" viewBox="0 0 24 24" data-testid="ico">
              <path d="M4 12h16" />
            </svg>
          </div>
          <div data-dev-id="component-browser.symbol-canvas" {...{ [TECHNICAL_CONTENT_ATTRIBUTE]: "true" }}>
            <svg data-dev-id="detail.technical-shape" data-testid="technical-shape"><path d="M0 0h10" /></svg>
          </div>
        </div>
        {createPortal(
          <>
            <div data-dev-id="provider.backdrop">
              <button type="button" data-dev-id="provider.close">Close Provider</button>
            </div>
            {onChromePointerDown ? (
              <div data-design-studio-chrome="true">
                <button type="button" data-dev-id="design.placement-handle" onPointerDown={onChromePointerDown}>Move Piece</button>
              </div>
            ) : null}
          </>,
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

  it("leaves Design Studio chrome pointer controls interactive without selecting them", () => {
    const pointerDown = vi.fn();
    render(<Harness onChromePointerDown={pointerDown} />);
    on("toggle-dev");
    on("toggle-inspect");

    fireEvent.pointerDown(screen.getByRole("button", { name: "Move Piece" }), { button: 0 });

    expect(pointerDown).toHaveBeenCalledOnce();
    expect(screen.getByTestId("selected")).toHaveTextContent("none");
  });

  it("makes the highlighted element the editing selection on pointer press", () => {
    render(<Harness />);
    on("toggle-dev");
    on("toggle-inspect");
    fireEvent.click(screen.getByRole("button", { name: "Complete Part" }));
    expect(screen.getByTestId("selected")).toHaveTextContent("detail.complete-part");

    const next = screen.getByTestId("ico");
    fireEvent.pointerMove(next);
    expect(screen.getByTestId("dev-hover")).toBeInTheDocument();
    fireEvent(next, new MouseEvent("pointerdown", { bubbles: true, button: 0 }));

    expect(screen.getByTestId("selected").textContent).toMatch(/^auto\.dom-svg\./);
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

  it("gives repeated caller identities separate exact occurrence addresses", () => {
    render(<Harness />);
    on("toggle-dev");
    on("toggle-inspect");
    fireEvent.click(screen.getByTestId("stockroom-copy"));
    const stockroomId = screen.getByTestId("selected-override").textContent;

    fireEvent.click(screen.getByTestId("mpn-copy"));
    const mpnId = screen.getByTestId("selected-override").textContent;

    expect(screen.getByTestId("selected")).toHaveTextContent("auto.text.1234567");
    expect(mpnId).toMatch(/^auto\.occurrence\./);
    expect(mpnId).not.toBe(stockroomId);
  });

  it("keeps the clicked occurrence authoritative when two targets share one semantic id", () => {
    render(<Harness />);
    on("toggle-dev");
    on("toggle-inspect");
    const first = screen.getByTestId("repeated-first");
    const second = screen.getByTestId("repeated-second");
    first.getBoundingClientRect = vi.fn(() => ({
      x: 10, y: 20, left: 10, top: 20, right: 110, bottom: 50, width: 100, height: 30,
      toJSON: () => ({}),
    }));
    second.getBoundingClientRect = vi.fn(() => ({
      x: 210, y: 220, left: 210, top: 220, right: 310, bottom: 250, width: 100, height: 30,
      toJSON: () => ({}),
    }));

    fireEvent(second, new MouseEvent("pointerdown", { bubbles: true, button: 0 }));

    expect(screen.getByTestId("dev-selection-overlay")).toHaveStyle({ left: "210px", top: "220px" });
  });

  it("upgrades a selected unique target before later duplicate growth can broaden its override", async () => {
    const view = render(<Harness />);
    on("toggle-dev");
    on("toggle-inspect");
    const selected = screen.getByTestId("unique-target-initial") as HTMLElement;
    fireEvent.click(selected);
    expect(screen.getByTestId("selected-override")).toHaveTextContent("auto.unique-action.1234567");

    on("set-selected-width-120");
    expect(selected.style.width).toBe("120px");

    view.rerender(<Harness insertUniquePeer />);

    await waitFor(() => expect(screen.getByTestId("selected-override").textContent).toMatch(/^auto\.occurrence\./));
    const peer = screen.getByTestId("unique-target-peer") as HTMLElement;
    expect(selected.style.width).toBe("120px");
    expect(peer.style.width).toBe("");

    on("set-selected-width-240");
    expect(selected.style.width).toBe("240px");
    expect(peer.style.width).toBe("");
  });

  it("keeps a retired unique override inert when only its later peer survives", async () => {
    const view = render(<Harness />);
    on("toggle-dev");
    on("toggle-inspect");
    fireEvent.click(screen.getByTestId("unique-target-initial"));
    on("set-selected-width-120");

    view.rerender(<Harness insertUniquePeer />);
    await waitFor(() => expect(screen.getByTestId("selected-override").textContent).toMatch(/^auto\.occurrence\./));
    const peer = screen.getByTestId("unique-target-peer") as HTMLElement;
    expect(peer.style.width).toBe("");

    view.rerender(<Harness insertUniquePeer hideUniqueTarget />);
    await waitFor(() => expect(screen.getByTestId("selected")).toHaveTextContent("none"));
    on("set-unrelated-width");

    expect(peer.style.width).toBe("");
  });

  it("rebinds a disconnected selection only when one replacement is uniquely provable", async () => {
    const view = render(<Harness uniqueVersion="first-mount" />);
    on("toggle-dev");
    on("toggle-inspect");
    fireEvent.click(screen.getByTestId("unique-target-first-mount"));
    expect(screen.getByTestId("selected-version")).toHaveTextContent("first-mount");
    on("set-selected-width-120");
    expect((screen.getByTestId("unique-target-first-mount") as HTMLElement).style.width).toBe("120px");

    view.rerender(<Harness uniqueVersion="second-mount" />);

    await waitFor(() => expect(screen.getByTestId("selected-version")).toHaveTextContent("second-mount"));
    expect(screen.getByTestId("selected")).toHaveTextContent("auto.unique-action.1234567");
    expect(screen.getByTestId("selected-override")).toHaveTextContent("auto.unique-action.1234567");
    expect((screen.getByTestId("unique-target-second-mount") as HTMLElement).style.width).toBe("120px");
  });

  it("retains a connected target across earlier insertion and clears safely on unprovable remount", async () => {
    const view = render(<Harness occurrenceVersion="first-mount" />);
    on("toggle-dev");
    on("toggle-inspect");
    const selected = screen.getByTestId("repeated-second");
    selected.getBoundingClientRect = vi.fn(() => ({
      x: 210, y: 220, left: 210, top: 220, right: 310, bottom: 250, width: 100, height: 30,
      toJSON: () => ({}),
    }));
    Object.defineProperty(selected, "offsetWidth", { configurable: true, value: 100 });
    Object.defineProperty(selected, "offsetHeight", { configurable: true, value: 30 });
    fireEvent(selected, new MouseEvent("pointerdown", { bubbles: true, button: 0 }));

    const move = screen.getByRole("button", { name: "Move Repeated Second" });
    fireEvent(move, new MouseEvent("pointerdown", { bubbles: true, clientX: 0, clientY: 0 }));
    fireEvent(window, new MouseEvent("pointermove", { bubbles: true, clientX: 16, clientY: 8 }));
    fireEvent(window, new MouseEvent("pointerup", { bubbles: true, clientX: 16, clientY: 8 }));
    expect((selected as HTMLElement).style.left).toBe("16px");

    view.rerender(<Harness occurrenceVersion="first-mount" insertEarlierPeer />);
    const retained = screen.getByTestId("repeated-second");
    expect((retained as HTMLElement).style.left).toBe("16px");
    retained.getBoundingClientRect = vi.fn(() => ({
      x: 410, y: 420, left: 410, top: 420, right: 510, bottom: 450, width: 100, height: 30,
      toJSON: () => ({}),
    }));
    fireEvent(window, new Event("resize"));
    expect(await screen.findByTestId("dev-selection-overlay")).toHaveStyle({ left: "410px", top: "420px" });
    on("undo");
    expect((retained as HTMLElement).style.left).toBe("");

    view.rerender(<Harness occurrenceVersion="second-mount" insertEarlierPeer />);

    await waitFor(() => expect(screen.getByTestId("selected")).toHaveTextContent("none"));
    expect(screen.queryByTestId("dev-selection-overlay")).toBeNull();
  });

  it("clears a removed duplicate instead of silently rebinding to its surviving peer", async () => {
    const view = render(<Harness />);
    on("toggle-dev");
    on("toggle-inspect");
    fireEvent.click(screen.getByTestId("repeated-second"));
    expect(screen.getByTestId("selected-override").textContent).toMatch(/^auto\.occurrence\./);

    view.rerender(<Harness hideRepeatedSecond />);

    await waitFor(() => expect(screen.getByTestId("selected")).toHaveTextContent("none"));
    expect(screen.getByTestId("repeated-first")).not.toHaveAttribute("data-design-occurrence-id");
  });

  it("synchronizes copy and element selection on the pointer press", () => {
    render(<Harness />);
    on("toggle-dev");
    on("toggle-inspect");

    fireEvent(screen.getByTestId("mpn-copy"), new MouseEvent("pointerdown", { bubbles: true, button: 0 }));

    expect(screen.getByTestId("selected")).toHaveTextContent("auto.text.1234567");
    expect(screen.getByTestId("selected-override").textContent).toMatch(/^auto\.occurrence\./);
    expect(screen.getByTestId("selected-copy")).toHaveTextContent("component-browser.copy-mpn-object");
  });

  it("keeps the owning copy selected when an exact nested text child is pressed", () => {
    render(<Harness />);
    on("toggle-dev");
    on("toggle-inspect");

    fireEvent(screen.getByTestId("mpn-copy-child"), new MouseEvent("pointerdown", { bubbles: true, button: 0 }));

    expect(screen.getByTestId("selected").textContent).toMatch(/^auto\.dom-strong\./);
    expect(screen.getByTestId("selected-copy")).toHaveTextContent("component-browser.copy-mpn-object");
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
    expect(screen.getAllByRole("button", { name: /Resize Complete Part/ })).toHaveLength(8);
    expect(screen.getByRole("button", { name: "Hide Complete Part" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "More actions for Complete Part" }));
    expect(screen.getByRole("button", { name: "Rotate Complete Part" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Detach Complete Part" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Bring Complete Part Forward" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Send Complete Part Backward" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Reset Complete Part" })).toBeInTheDocument();
  });

  it("focuses More actions and closes one layer with Escape", async () => {
    render(<Harness />);
    on("toggle-dev");
    on("toggle-inspect");
    fireEvent.click(screen.getByRole("button", { name: "Complete Part" }));

    const opener = screen.getByRole("button", { name: "More actions for Complete Part" });
    opener.focus();
    fireEvent.click(opener);
    await waitFor(() => expect(screen.getByRole("button", { name: "Rotate Complete Part" })).toHaveFocus());

    fireEvent.keyDown(window, { key: "Escape" });
    expect(screen.queryByRole("button", { name: "Rotate Complete Part" })).not.toBeInTheDocument();
    await waitFor(() => expect(opener).toHaveFocus());
  });

  it("moves the selected element forward and backward as undoable layer edits", () => {
    render(<Harness />);
    on("toggle-dev");
    on("toggle-inspect");
    const target = screen.getByRole("button", { name: "Complete Part" });
    fireEvent.click(target);
    fireEvent.click(screen.getByRole("button", { name: "More actions for Complete Part" }));

    fireEvent.click(screen.getByRole("button", { name: "Bring Complete Part Forward" }));
    expect(target).toHaveStyle({ zIndex: "1" });
    fireEvent.click(screen.getByRole("button", { name: "Send Complete Part Backward" }));
    expect(target).toHaveStyle({ zIndex: "0" });

    on("undo");
    expect(target).toHaveStyle({ zIndex: "1" });
  });

  it("makes z-order effective on a statically positioned target", () => {
    render(<Harness />);
    on("toggle-dev");
    on("toggle-inspect");
    fireEvent.click(document.querySelector('[data-dev-id="detail.readiness"]')!);
    fireEvent.click(screen.getByRole("button", { name: /more actions/i }));

    fireEvent.click(screen.getByRole("button", { name: /bring .* forward/i }));

    expect(JSON.parse(screen.getByTestId("element-overrides").textContent ?? "{}")).toMatchObject({
      "detail.readiness": { position: "relative", "z-index": "1" },
    });
  });

  it("moves across sibling paint order instead of incrementing an ineffective local number", () => {
    render(<Harness />);
    on("toggle-dev");
    on("toggle-inspect");
    const target = document.querySelector<HTMLElement>('[data-dev-id="detail.readiness"]')!;
    const paintedPeer = document.createElement("div");
    paintedPeer.style.position = "relative";
    paintedPeer.style.zIndex = "7";
    act(() => target.parentElement!.appendChild(paintedPeer));
    fireEvent.click(target);
    fireEvent.click(screen.getByRole("button", { name: /more actions/i }));

    fireEvent.click(screen.getByRole("button", { name: /bring .* forward/i }));

    expect(target).toHaveStyle({ position: "relative", zIndex: "8" });
  });

  it("rebalances a saturated top sibling so Bring Forward stays effective and grammar-safe", () => {
    render(<Harness />);
    on("toggle-dev");
    on("toggle-inspect");
    const target = document.querySelector<HTMLElement>('[data-dev-id="detail.readiness"]')!;
    const paintedPeer = document.createElement("div");
    paintedPeer.setAttribute("data-design-id", "auto.layer-peer.1234567");
    paintedPeer.style.position = "relative";
    paintedPeer.style.zIndex = "9999";
    target.style.position = "relative";
    target.style.zIndex = "9999";
    target.parentElement!.appendChild(paintedPeer);
    fireEvent.click(target);
    fireEvent.click(screen.getByRole("button", { name: /more actions/i }));

    fireEvent.click(screen.getByRole("button", { name: /bring .* forward/i }));

    const overrides = JSON.parse(screen.getByTestId("element-overrides").textContent ?? "{}");
    expect(overrides["detail.readiness"]["z-index"]).toBe("9999");
    expect(overrides["auto.layer-peer.1234567"]["z-index"]).toBe("9998");
    expect(target).toHaveStyle({ zIndex: "9999" });
    expect(paintedPeer).toHaveStyle({ zIndex: "9998" });

    on("undo");
    expect(JSON.parse(screen.getByTestId("element-overrides").textContent ?? "{}")).toEqual({});
  });

  it("rebalances a saturated bottom sibling so Send Backward stays effective and grammar-safe", () => {
    render(<Harness />);
    on("toggle-dev");
    on("toggle-inspect");
    const target = document.querySelector<HTMLElement>('[data-dev-id="detail.readiness"]')!;
    const paintedPeer = document.createElement("div");
    paintedPeer.setAttribute("data-design-id", "auto.layer-peer.1234567");
    paintedPeer.style.position = "relative";
    paintedPeer.style.zIndex = "-9999";
    target.style.position = "relative";
    target.style.zIndex = "-9999";
    act(() => target.parentElement!.appendChild(paintedPeer));
    fireEvent.click(target);
    fireEvent.click(screen.getByRole("button", { name: /more actions/i }));

    fireEvent.click(screen.getByRole("button", { name: /send .* backward/i }));

    const overrides = JSON.parse(screen.getByTestId("element-overrides").textContent ?? "{}");
    expect(overrides["detail.readiness"]["z-index"]).toBe("-9999");
    expect(overrides["auto.layer-peer.1234567"]["z-index"]).toBe("-9998");
    expect(target).toHaveStyle({ zIndex: "-9999" });
    expect(paintedPeer).toHaveStyle({ zIndex: "-9998" });
  });

  it("rotates from the keyboard as one undoable edit", () => {
    render(<Harness />);
    on("toggle-dev");
    on("toggle-inspect");
    const target = screen.getByRole("button", { name: "Complete Part" });
    fireEvent.click(target);
    fireEvent.click(screen.getByRole("button", { name: "More actions for Complete Part" }));

    const rotate = screen.getByRole("button", { name: "Rotate Complete Part" });
    fireEvent.keyDown(rotate, { key: "ArrowRight" });
    expect(target).toHaveStyle({ transform: "rotate(15deg)" });

    on("undo");
    expect(target.style.transform).toBe("");
  });

  it("preserves existing transform components while rotating", () => {
    render(<Harness readinessTransform="translateX(10px) scale(2)" />);
    on("toggle-dev");
    on("toggle-inspect");
    fireEvent.click(document.querySelector('[data-dev-id="detail.readiness"]')!);
    fireEvent.click(screen.getByRole("button", { name: /more actions/i }));

    fireEvent.keyDown(screen.getByRole("button", { name: /rotate/i }), { key: "ArrowRight" });

    expect(JSON.parse(screen.getByTestId("element-overrides").textContent ?? "{}")).toMatchObject({
      "detail.readiness": { transform: "translateX(10px) scale(2) rotate(15deg)" },
    });
  });

  it("composes rotation with a transform authored by a stylesheet class", () => {
    render(<Harness readinessClassTransform />);
    on("toggle-dev");
    on("toggle-inspect");
    fireEvent.click(document.querySelector('[data-dev-id="detail.readiness"]')!);
    fireEvent.click(screen.getByRole("button", { name: /more actions/i }));

    fireEvent.keyDown(screen.getByRole("button", { name: /rotate/i }), { key: "ArrowRight" });

    expect(JSON.parse(screen.getByTestId("element-overrides").textContent ?? "{}")).toMatchObject({
      "detail.readiness": { transform: "translateX(10px) scale(2) rotate(15deg)" },
    });
  });

  it("preserves the browser-computed matrix form while adding rotation", () => {
    render(<Harness />);
    on("toggle-dev");
    on("toggle-inspect");
    const target = document.querySelector<HTMLElement>('[data-dev-id="detail.readiness"]')!;
    const nativeGetComputedStyle = window.getComputedStyle;
    vi.spyOn(window, "getComputedStyle").mockImplementation((element, pseudo) => {
      const computed = nativeGetComputedStyle(element, pseudo);
      if (element === target) {
        Object.defineProperty(computed, "transform", {
          configurable: true,
          value: "matrix(1, 0, 0, 1, 10, 20)",
        });
      }
      return computed;
    });
    fireEvent.click(target);
    fireEvent.click(screen.getByRole("button", { name: /more actions/i }));

    fireEvent.keyDown(screen.getByRole("button", { name: /rotate/i }), { key: "ArrowRight" });

    expect(target.style.transform).toBe("matrix(1, 0, 0, 1, 10, 20) rotate(15deg)");
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
    fireEvent.click(screen.getByRole("button", { name: "More actions for Complete Part" }));

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

  it("moves only the clicked second duplicate and undoes the gesture once", () => {
    render(<Harness />);
    on("toggle-dev");
    on("toggle-inspect");
    const first = screen.getByTestId("repeated-first") as HTMLElement;
    const second = screen.getByTestId("repeated-second") as HTMLElement;
    Object.defineProperty(second, "offsetWidth", { configurable: true, value: 100 });
    Object.defineProperty(second, "offsetHeight", { configurable: true, value: 40 });
    fireEvent.click(second);

    const move = screen.getByRole("button", { name: "Move Repeated Second" });
    fireEvent(move, new MouseEvent("pointerdown", { bubbles: true, clientX: 0, clientY: 0 }));
    fireEvent(window, new MouseEvent("pointermove", { bubbles: true, clientX: 16, clientY: 8 }));
    fireEvent(window, new MouseEvent("pointerup", { bubbles: true, clientX: 16, clientY: 8 }));

    expect(first.style.left).toBe("");
    expect(second.style.left).toBe("16px");
    on("undo");
    expect(first.style.left).toBe("");
    expect(second.style.left).toBe("");
  });

  it("abandons a lost resize before selecting another element", () => {
    render(<Harness />);
    on("toggle-dev");
    on("toggle-inspect");
    const target = screen.getByRole("button", { name: "Complete Part" });
    Object.defineProperty(target, "offsetWidth", { configurable: true, value: 100 });
    Object.defineProperty(target, "offsetHeight", { configurable: true, value: 40 });
    fireEvent.click(target);

    const resize = screen.getByRole("button", { name: "Resize Complete Part East" });
    fireEvent(resize, new MouseEvent("pointerdown", { bubbles: true, clientX: 100, clientY: 20 }));
    fireEvent(window, new MouseEvent("pointermove", { bubbles: true, clientX: 116, clientY: 20 }));
    expect(target).toHaveStyle({ width: "120px" });

    // The native release is deliberately absent. A new press must restore the old preview before
    // capture-phase selection moves to a different target, and later pointer motion owns nothing.
    fireEvent(screen.getByTestId("ico"), new MouseEvent("pointerdown", { bubbles: true, button: 0 }));
    fireEvent(window, new MouseEvent("pointermove", { bubbles: true, clientX: 240, clientY: 20 }));

    expect(screen.getByTestId("selected").textContent).toMatch(/^auto\.dom-svg\./);
    expect(target.style.width).toBe("");
    expect(screen.getByTestId("element-overrides")).toHaveTextContent("{}");
  });

  it("cancels a captured resize on pointer cancellation", () => {
    render(<Harness />);
    on("toggle-dev");
    on("toggle-inspect");
    const target = screen.getByRole("button", { name: "Complete Part" });
    Object.defineProperty(target, "offsetWidth", { configurable: true, value: 100 });
    Object.defineProperty(target, "offsetHeight", { configurable: true, value: 40 });
    fireEvent.click(target);

    const resize = screen.getByRole("button", { name: "Resize Complete Part Southeast" });
    fireEvent(resize, new MouseEvent("pointerdown", { bubbles: true, clientX: 100, clientY: 40 }));
    fireEvent(window, new MouseEvent("pointermove", { bubbles: true, clientX: 116, clientY: 56 }));
    fireEvent(window, new MouseEvent("pointercancel", { bubbles: true, clientX: 116, clientY: 56 }));

    expect(target.style.width).toBe("");
    expect(target.style.height).toBe("");
    expect(screen.getByTestId("element-overrides")).toHaveTextContent("{}");
  });

  it("keeps the left edge fixed when an end-aligned target is resized east", () => {
    render(<Harness />);
    on("toggle-dev");
    on("toggle-inspect");
    const target = screen.getByRole("button", { name: "Complete Part" });
    Object.defineProperty(target, "offsetWidth", { configurable: true, value: 100 });
    Object.defineProperty(target, "offsetHeight", { configurable: true, value: 40 });
    vi.spyOn(target, "getBoundingClientRect").mockImplementation(() => {
      const width = Number.parseFloat(target.style.width) || 100;
      const leftOffset = Number.parseFloat(target.style.left) || 0;
      const left = 300 - width + leftOffset;
      return {
        x: left, y: 30, left, top: 30, right: left + width, bottom: 70, width, height: 40,
        toJSON: () => ({}),
      };
    });
    fireEvent.click(target);

    const resize = screen.getByRole("button", { name: "Resize Complete Part East" });
    fireEvent(resize, new MouseEvent("pointerdown", { bubbles: true, clientX: 300, clientY: 50 }));
    fireEvent(window, new MouseEvent("pointermove", { bubbles: true, clientX: 316, clientY: 50 }));
    fireEvent(window, new MouseEvent("pointerup", { bubbles: true, clientX: 316, clientY: 50 }));

    expect(target).toHaveStyle({ position: "relative", left: "20px", width: "120px" });
    expect(target.getBoundingClientRect().left).toBe(200);
    expect(target.getBoundingClientRect().right).toBe(320);
  });

  it("does not write or move anything when the Move grip is only clicked", () => {
    render(<Harness />);
    on("toggle-dev");
    on("toggle-inspect");
    const target = screen.getByRole("button", { name: "Complete Part" });
    fireEvent.click(target);

    const move = screen.getByRole("button", { name: "Move Complete Part" });
    fireEvent.pointerDown(move, { pointerId: 7, clientX: 40, clientY: 20 });
    fireEvent.pointerUp(window, { pointerId: 7, clientX: 40, clientY: 20 });

    expect(target.style.position).toBe("");
    expect(target.style.left).toBe("");
    expect(target.style.top).toBe("");
    expect(screen.getByTestId("element-overrides")).toHaveTextContent("{}");
  });

  it("keeps the preview frame out of accidental geometry and hide gestures", () => {
    render(<Harness />);
    on("toggle-dev");
    on("toggle-inspect");
    const frame = document.querySelector<HTMLElement>("[data-design-product-root]")!;

    fireEvent.click(frame);

    expect(screen.getByTestId("selected")).toHaveTextContent("components.stage");
    expect(screen.queryByRole("button", { name: /^Move / })).toBeNull();
    expect(screen.queryByRole("button", { name: /^Rotate / })).toBeNull();
    expect(screen.queryByRole("button", { name: /^Detach / })).toBeNull();
    expect(screen.queryAllByRole("button", { name: /^Resize / })).toHaveLength(0);
    expect(screen.queryByRole("button", { name: /^Hide / })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: /more actions/i }));
    expect(screen.queryByRole("button", { name: /^Bring / })).toBeNull();
    expect(screen.queryByRole("button", { name: /^Send / })).toBeNull();
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

  it("detaches without writing destructive geometry to the protected preview root", () => {
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
    fireEvent.click(screen.getByRole("button", { name: "More actions for Complete Part" }));

    fireEvent.click(screen.getByRole("button", { name: "Detach Complete Part" }));
    expect(target).toHaveStyle({ position: "absolute", width: "100px", height: "40px" });
    expect(parent.style.position).toBe("");

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

  it("leaves Tab navigation alone while editor chrome owns focus", () => {
    render(<Harness />);
    on("toggle-dev");
    on("toggle-inspect");
    fireEvent.click(screen.getByRole("button", { name: "Complete Part" }));
    const move = screen.getByRole("button", { name: "Move Complete Part" });
    move.focus();

    const event = new KeyboardEvent("keydown", { key: "Tab", bubbles: true, cancelable: true });
    move.dispatchEvent(event);

    expect(event.defaultPrevented).toBe(false);
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
