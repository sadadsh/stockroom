import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ELEMENT_OVERRIDES } from "../lib/element.overrides";
import { DesignIdentityRuntime } from "./DesignIdentityRuntime";
import { Icon } from "./Icon";
import { Text } from "../lib/copy";
import { DevModeProvider, useDevMode } from "../lib/devMode";
import { directTextCopyId } from "../design-studio/targetDomains";
import { ThemeProvider } from "../lib/theme";

function DirectCopyControl() {
  const dev = useDevMode();
  return <button type="button" onClick={() => dev.setCopy(directTextCopyId("perf.direct"), "Changed")}>Change Copy</button>;
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  delete ELEMENT_OVERRIDES["auto.caller-copy.1234567"];
  delete ELEMENT_OVERRIDES["auto.caller-copy.7654321"];
  delete ELEMENT_OVERRIDES["authored.copy"];
});

describe("DesignIdentityRuntime", () => {
  it("keeps production caller identities authoritative over copy, icon, and layout metadata", async () => {
    render(
      <>
        <section data-design-product-root="true">
          <span data-testid="copy-host" data-design-id="auto.caller-copy.1234567" data-copy-id="copy.fixture">Copy</span>
          <svg data-testid="icon-host" data-design-id="auto.caller-icon.1234567" data-icon-id="icon.fixture" />
          <div data-testid="layout-host" data-design-id="auto.caller-layout.1234567" data-layout-piece="layout.fixture" />
        </section>
        <DesignIdentityRuntime />
      </>,
    );

    await waitFor(() => {
      expect(document.querySelector('[data-testid="copy-host"]')).toHaveAttribute("data-design-id", "auto.caller-copy.1234567");
      expect(document.querySelector('[data-testid="icon-host"]')).toHaveAttribute("data-design-id", "auto.caller-icon.1234567");
      expect(document.querySelector('[data-testid="layout-host"]')).toHaveAttribute("data-design-id", "auto.caller-layout.1234567");
    });
  });

  it("preserves build-generated caller identities through the real Text and Icon primitives", async () => {
    const copyIdentity = { "data-design-id": "auto.caller-copy.1234567" };
    const secondCopyIdentity = { "data-design-id": "auto.caller-copy.7654321" };
    const iconIdentity = { "data-design-id": "auto.caller-icon.1234567" };
    const secondIconIdentity = { "data-design-id": "auto.caller-icon.7654321" };
    ELEMENT_OVERRIDES[copyIdentity["data-design-id"]] = { color: "rgb(1, 2, 3)" };
    ELEMENT_OVERRIDES[secondCopyIdentity["data-design-id"]] = { color: "rgb(3, 2, 1)" };

    render(
      <section data-design-product-root="true">
        <Text id="copy.fixture" {...copyIdentity}>Copy</Text>
        <Text id="copy.fixture.second" {...secondCopyIdentity}>Second Copy</Text>
        <Icon id="action.add" {...iconIdentity} />
        <Icon id="action.edit" {...secondIconIdentity} />
        <DesignIdentityRuntime />
      </section>,
    );

    await waitFor(() => {
      expect(document.querySelector('[data-design-id="auto.caller-copy.1234567"]'))
        .toHaveAttribute("data-design-id", "auto.caller-copy.1234567");
      expect(document.querySelector("svg"))
        .toHaveAttribute("data-design-id", "auto.caller-icon.1234567");
      expect(document.querySelector('[data-design-id="auto.caller-copy.7654321"]'))
        .toHaveTextContent("Second Copy");
      expect(document.querySelectorAll("svg")[1])
        .toHaveAttribute("data-design-id", "auto.caller-icon.7654321");
    });
  });

  it("preserves authored caller identities through the real Text and Icon primitives", () => {
    const authoredCopy = { "data-dev-id": "authored.copy" };
    const authoredIcon = { "data-dev-id": "authored.icon" };
    ELEMENT_OVERRIDES[authoredCopy["data-dev-id"]] = { color: "rgb(1, 2, 3)" };

    render(
      <>
        <Text id="copy.authored" {...authoredCopy}>Authored Copy</Text>
        <Icon id="action.add" {...authoredIcon} />
      </>,
    );

    expect(document.querySelector('[data-dev-id="authored.copy"]')).toHaveTextContent("Authored Copy");
    expect(document.querySelector("svg")).toHaveAttribute("data-dev-id", "authored.icon");
  });

  it("coalesces a burst of DOM mutations into one identity pass", async () => {
    const queued: FrameRequestCallback[] = [];
    const request = vi.spyOn(window, "requestAnimationFrame").mockImplementation((callback) => {
      queued.push(callback);
      return 1;
    });
    vi.spyOn(window, "cancelAnimationFrame").mockImplementation(() => undefined);
    render(<><section data-testid="root" data-design-product-root="true" /><DesignIdentityRuntime /></>);
    const root = document.querySelector('[data-testid="root"]')!;

    root.append(document.createElement("span"), document.createElement("span"));
    await waitFor(() => expect(request).toHaveBeenCalledTimes(1));
    queued[0]?.(0);
    expect(request).toHaveBeenCalledTimes(1);
  });

  it("does not rescan the product tree for text-only mutations", async () => {
    const queued: FrameRequestCallback[] = [];
    const request = vi.spyOn(window, "requestAnimationFrame").mockImplementation((callback) => {
      queued.push(callback);
      return 1;
    });
    vi.spyOn(window, "cancelAnimationFrame").mockImplementation(() => undefined);
    render(<><section data-testid="root" data-design-product-root="true"><span>Before</span></section><DesignIdentityRuntime /></>);

    queued.splice(0).forEach((callback) => callback(0));
    request.mockClear();

    (document.querySelector('[data-testid="root"] span')!.firstChild as Text).data = "After";
    await Promise.resolve();

    expect(request).not.toHaveBeenCalled();
    expect(queued).toHaveLength(0);
  });

  it("reuses resolved targets while direct copy is edited", async () => {
    render(
      <ThemeProvider>
        <DevModeProvider>
          <section data-testid="root" data-design-product-root="true">
            <span data-dev-id="perf.direct">Before</span>
          </section>
          <DirectCopyControl />
          <DesignIdentityRuntime />
        </DevModeProvider>
      </ThemeProvider>,
    );
    const root = document.querySelector<HTMLElement>('[data-testid="root"]')!;
    const scan = vi.spyOn(root, "querySelectorAll");

    fireEvent.click(screen.getByRole("button", { name: "Change Copy" }));
    await waitFor(() => expect(root).toHaveTextContent("Changed"));

    expect(scan).not.toHaveBeenCalled();
  });
});
