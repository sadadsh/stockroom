import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createRef, useState } from "react";
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
