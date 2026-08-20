import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ProviderBrowserFrame } from "./ProviderBrowserFrame";

const identity = {
  componentId: "part-1",
  providerId: "digikey",
  routeId: "digikey-ultralibrarian",
  sessionId: "session-1",
};

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
        identity={identity}
        providerLabel="DigiKey"
        url="https://www.digikey.com/en/products/detail/example"
        canGoBack
        canGoForward={false}
      />
    );
    const rendered = render(view);

    expect(screen.getByRole("button", { name: "Back" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Forward" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Reload" })).toBeVisible();
    expect(screen.getByRole("textbox", { name: "Provider Address" })).toHaveValue(
      "https://www.digikey.com/en/products/detail/example",
    );
    expect(screen.getByRole("button", { name: "Go" })).toBeVisible();
    expect(screen.getByLabelText("Current provider address")).toHaveTextContent(
      "digikey.com/en/products/detail/example",
    );
    expect(setProviderViewport).toHaveBeenLastCalledWith({
      ...identity,
      visible: true,
      x: 200,
      y: 160,
      width: 900,
      height: 560,
    });
    const stableCallCount = setProviderViewport.mock.calls.length;
    rendered.rerender(
      <ProviderBrowserFrame
        identity={identity}
        providerLabel="DigiKey"
        url="https://www.digikey.com/en/products/detail/example"
        canGoBack
        canGoForward={false}
      />,
    );
    expect(setProviderViewport).toHaveBeenCalledTimes(stableCallCount);

    // Width and height are unchanged, so ResizeObserver cannot explain this publication. A parent
    // modal geometry commit must still move the native provider surface.
    viewportRect = rect(320, 240, 900, 560);
    rendered.rerender(
      <ProviderBrowserFrame
        identity={identity}
        providerLabel="DigiKey"
        url="https://www.digikey.com/en/products/detail/example"
      />,
    );
    expect(setProviderViewport).toHaveBeenLastCalledWith({
      ...identity,
      visible: true,
      x: 320,
      y: 240,
      width: 900,
      height: 560,
    });

    rendered.unmount();
    expect(setProviderViewport).toHaveBeenLastCalledWith({
      ...identity,
      visible: false,
      x: 0,
      y: 0,
      width: 0,
      height: 0,
    });
  });

  it("waits for acknowledged navigation and reports a refused command", async () => {
    const user = userEvent.setup();
    const providerCommand = vi.fn()
      .mockResolvedValueOnce(true)
      .mockResolvedValueOnce(false);
    Object.defineProperty(window, "__STOCKROOM_HOST__", {
      configurable: true,
      value: { providerCommand },
    });

    render(
      <ProviderBrowserFrame
        identity={{ ...identity, providerId: "mouser", routeId: "mouser" }}
        providerLabel="Mouser"
        url="https://www.mouser.com/c/?q=LM358"
      />,
    );

    const address = screen.getByRole("textbox", { name: "Provider Address" });
    await user.clear(address);
    await user.type(address, "https://www.digikey.com/en/products/result?keywords=LM358");
    await user.click(screen.getByRole("button", { name: "Go" }));
    await waitFor(() => expect(providerCommand).toHaveBeenCalledWith({
      ...identity,
      providerId: "mouser",
      routeId: "mouser",
      command: "navigate",
      url: "https://www.digikey.com/en/products/result?keywords=LM358",
    }));

    await user.click(screen.getByRole("button", { name: "Reload" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "The embedded provider browser refused Reload.",
    );
  });
});
