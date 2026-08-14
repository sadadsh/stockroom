import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createRef, useState } from "react";
import { installPreviewEffectGuard } from "../../design-studio/previewEffects";
import {
  ProviderBrowserModal,
  initialProviderModalGeometry,
  moveProviderModal,
  resizeProviderModal,
} from "./ProviderBrowserModal";

describe("ProviderBrowserModal", () => {
  it("keeps the browser inside a visible app margin while moving and resizing", () => {
    const initial = initialProviderModalGeometry({ width: 1280, height: 800 });
    expect(initial).toEqual({ x: 128, y: 80, width: 1024, height: 640 });

    expect(
      moveProviderModal(initial, -500, -500, { width: 1280, height: 800 }),
    ).toEqual({ x: 24, y: 24, width: 1024, height: 640 });
    expect(
      resizeProviderModal(initial, "south-east", 500, 500, {
        width: 1280,
        height: 800,
      }),
    ).toEqual({ x: 128, y: 80, width: 1128, height: 696 });
  });

  it("republishes native viewport coordinates throughout a titlebar drag", async () => {
    const setProviderViewport = vi.fn();
    Object.defineProperty(window, "__STOCKROOM_HOST__", {
      configurable: true,
      value: { setProviderViewport },
    });
    const bounds = vi
      .spyOn(HTMLElement.prototype, "getBoundingClientRect")
      .mockImplementation(function (this: HTMLElement) {
        if (this.getAttribute("data-dev-id") !== "component-browser.provider-viewport") {
          return { x: 0, y: 0, width: 0, height: 0 } as DOMRect;
        }
        const dialog = this.closest<HTMLElement>("[role=dialog]")!;
        const x = Number.parseFloat(dialog.style.left) + 4;
        const y = Number.parseFloat(dialog.style.top) + 70;
        const width = Number.parseFloat(dialog.style.width) - 8;
        const height = Number.parseFloat(dialog.style.height) - 74;
        return { x, y, width, height, top: y, left: x, right: x + width, bottom: y + height } as DOMRect;
      });

    try {
      render(
        <ProviderBrowserModal
          open
          componentId="part-1"
          providerLabel="DigiKey"
          url="https://www.digikey.com/en/products/detail/example"
          onClose={vi.fn()}
        />,
      );
      const first = setProviderViewport.mock.calls[setProviderViewport.mock.calls.length - 1]?.[0] as {
        x: number;
        y: number;
        width: number;
        height: number;
      };
      const titlebar = document.querySelector<HTMLElement>(
        '[data-dev-id="component-browser.provider-dialog-titlebar"]',
      )!;
      fireEvent(titlebar, new MouseEvent("pointerdown", {
        bubbles: true,
        clientX: 200,
        clientY: 120,
      }));
      fireEvent(titlebar, new MouseEvent("pointermove", {
        bubbles: true,
        clientX: 260,
        clientY: 165,
      }));
      fireEvent(titlebar, new MouseEvent("pointerup", {
        bubbles: true,
        clientX: 260,
        clientY: 165,
      }));

      await waitFor(() => {
        const last = setProviderViewport.mock.calls[
          setProviderViewport.mock.calls.length - 1
        ]?.[0];
        expect(last.x).toBe(first.x + 60);
        expect(last.y).toBe(first.y + 45);
        expect(last.width).toBe(first.width);
        expect(last.height).toBe(first.height);
      });
    } finally {
      bounds.mockRestore();
      Reflect.deleteProperty(window, "__STOCKROOM_HOST__");
    }
  });

  it("closes with its visible control and returns focus to the launcher", async () => {
    const user = userEvent.setup();
    const launcher = createRef<HTMLButtonElement>();
    const onClose = vi.fn();
    render(
      <>
        <button ref={launcher}>Open Provider</button>
        <ProviderBrowserModal
          open
          componentId="part-1"
          providerLabel="SnapEDA"
          url="https://snapeda.example/part-1"
          returnFocusRef={launcher}
          onClose={onClose}
        />
      </>,
    );

    expect(screen.getByRole("dialog", { name: "SnapEDA Provider" })).toHaveAttribute(
      "aria-modal",
      "true",
    );
    await user.click(screen.getByRole("button", { name: "Close Provider" }));

    expect(onClose).toHaveBeenCalledTimes(1);
    expect(launcher.current).toHaveFocus();
  });

  it("closes with Escape without activating content behind the modal", async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    const backgroundAction = vi.fn();
    render(
      <>
        <button onClick={backgroundAction}>Background Action</button>
        <ProviderBrowserModal
          open
          componentId="part-1"
          providerLabel="Ultra Librarian"
          url="https://ultralibrarian.example/part-1"
          onClose={onClose}
        />
      </>,
    );

    await user.keyboard("{Escape}");

    expect(onClose).toHaveBeenCalledTimes(1);
    expect(backgroundAction).not.toHaveBeenCalled();
  });

  it("remembers the opener when no explicit focus target is supplied", async () => {
    const user = userEvent.setup();
    function Harness() {
      const [open, setOpen] = useState(false);
      return (
        <>
          <button onClick={() => setOpen(true)}>Launch Provider</button>
          <ProviderBrowserModal
            open={open}
            componentId="part-1"
            providerLabel="SnapEDA"
            url="https://snapeda.example/part-1"
            onClose={() => setOpen(false)}
          />
        </>
      );
    }

    render(<Harness />);
    const launcher = screen.getByRole("button", { name: "Launch Provider" });
    await user.click(launcher);
    await user.click(screen.getByRole("button", { name: "Close Provider" }));

    expect(launcher).toHaveFocus();
  });

  it("always closes its local preview when the native provider command is refused", async () => {
    const user = userEvent.setup();
    const providerCommand = vi.fn();
    Object.defineProperty(window, "__STOCKROOM_HOST__", {
      configurable: true,
      value: { providerCommand },
    });
    const restoreGuard = installPreviewEffectGuard("components.manage-models-ready");

    function Harness() {
      const [open, setOpen] = useState(true);
      return (
        <ProviderBrowserModal
          open={open}
          componentId="part-1"
          providerLabel="Ultra Librarian"
          url="https://ultralibrarian.example/part-1"
          onClose={() => setOpen(false)}
        />
      );
    }

    try {
      render(<Harness />);
      await user.click(screen.getByRole("button", { name: "Close Provider" }));

      expect(screen.queryByRole("dialog", { name: "Ultra Librarian Provider" })).toBeNull();
      expect(providerCommand).not.toHaveBeenCalled();
    } finally {
      restoreGuard();
      Reflect.deleteProperty(window, "__STOCKROOM_HOST__");
    }
  });

  it("navigates to an entered HTTPS address like a normal browser", async () => {
    const user = userEvent.setup();
    const providerCommand = vi.fn();
    Object.defineProperty(window, "__STOCKROOM_HOST__", {
      configurable: true,
      value: { providerCommand },
    });

    render(
      <ProviderBrowserModal
        open
        componentId="part-1"
        providerLabel="Mouser"
        url="https://www.mouser.com/"
        onClose={vi.fn()}
      />,
    );

    const address = screen.getByRole("textbox", { name: "Provider Address" });
    await user.clear(address);
    await user.type(address, "https://www.digikey.com/en/products/result?keywords=LM358{Enter}");

    expect(providerCommand).toHaveBeenCalledWith({
      componentId: "part-1",
      command: "navigate",
      url: "https://www.digikey.com/en/products/result?keywords=LM358",
    });
  });
});
