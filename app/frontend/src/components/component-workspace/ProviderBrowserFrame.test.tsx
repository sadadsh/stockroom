import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ProviderBrowserFrame } from "./ProviderBrowserFrame";

afterEach(() => {
  Reflect.deleteProperty(window, "__STOCKROOM_HOST__");
  vi.restoreAllMocks();
});

function rect(x: number, y: number, width: number, height: number): DOMRect {
  return {
    x,
    y,
    width,
    height,
    top: y,
    right: x + width,
    bottom: y + height,
    left: x,
    toJSON: () => ({}),
  } as DOMRect;
}

describe("ProviderBrowserFrame", () => {
  it("keeps browser controls outside the native viewport and republishes position-only moves", () => {
    const setProviderViewport = vi.fn();
    Object.defineProperty(window, "__STOCKROOM_HOST__", {
      configurable: true,
      value: { setProviderViewport },
    });
    let viewportRect = rect(200, 160, 900, 560);
    vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockImplementation(function (
      this: HTMLElement,
    ) {
      return this.getAttribute("data-dev-id") === "component-browser.provider-viewport"
        ? viewportRect
        : rect(0, 0, 0, 0);
    });

    const view = (
      <ProviderBrowserFrame
        componentId="part-1"
        providerLabel="DigiKey"
        url="https://www.digikey.com/en/products/detail/example"
      />
    );
    const rendered = render(view);

    expect(screen.getByRole("button", { name: "Back" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Forward" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Reload" })).toBeVisible();
    expect(screen.getByRole("textbox", { name: "Provider Address" })).toBeVisible();
    expect(setProviderViewport).toHaveBeenLastCalledWith({
      componentId: "part-1",
      visible: true,
      x: 200,
      y: 160,
      width: 900,
      height: 560,
    });

    // Width and height are unchanged, so ResizeObserver cannot explain this publication. A parent
    // modal geometry commit must still move the native provider surface.
    viewportRect = rect(320, 240, 900, 560);
    rendered.rerender(
      <ProviderBrowserFrame
        componentId="part-1"
        providerLabel="DigiKey"
        url="https://www.digikey.com/en/products/detail/example"
      />,
    );
    expect(setProviderViewport).toHaveBeenLastCalledWith({
      componentId: "part-1",
      visible: true,
      x: 320,
      y: 240,
      width: 900,
      height: 560,
    });

    rendered.unmount();
    expect(setProviderViewport).toHaveBeenLastCalledWith({
      componentId: "part-1",
      visible: false,
      x: 0,
      y: 0,
      width: 0,
      height: 0,
    });
  });
});
