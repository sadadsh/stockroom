import { cleanup, render, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { ELEMENT_OVERRIDES } from "../lib/element.overrides";
import { DesignIdentityRuntime } from "./DesignIdentityRuntime";
import { Icon } from "./Icon";
import { Text } from "../lib/copy";

afterEach(() => {
  cleanup();
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
});
