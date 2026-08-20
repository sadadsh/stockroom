import { render } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { Icon } from "./Icon";
import { ICON_OVERRIDES } from "../lib/icon.overrides";
import type { IconId } from "../lib/iconRegistry";

afterEach(() => {
  document.documentElement.removeAttribute("data-theme");
  for (const key of Object.keys(ICON_OVERRIDES)) delete ICON_OVERRIDES[key];
});

function rendered(node: React.ReactElement): SVGSVGElement {
  const { container } = render(node);
  const svg = container.querySelector("svg");
  if (!svg) throw new Error("expected an <svg>");
  return svg;
}

describe("chrome and navigation icon grammar", () => {
  it.each([
    "nav.theme",
    "brand.wordmark",
    "overlay.chevron",
    "nav.components",
    "nav.about",
    "nav.up-to-date",
  ])("renders %s on the shared Tabler Outline frame", (id) => {
    const svg = rendered(<Icon id={id as IconId} className="h-4 w-4" />);
    expect(svg).toHaveClass("ico", "h-4", "w-4");
    expect(svg).toHaveAttribute("viewBox", "0 0 24 24");
    expect(svg).toHaveAttribute("fill", "none");
    expect(svg).toHaveAttribute("stroke", "currentColor");
    expect(svg).toHaveAttribute("stroke-width", "2");
    expect(svg).toHaveAttribute("stroke-linecap", "round");
    expect(svg).toHaveAttribute("stroke-linejoin", "round");
  });

  it("keeps positive status color at the call site instead of baking it into geometry", () => {
    const { container } = render(
      <span className="text-ok">
        <Icon id="nav.up-to-date" className="h-4 w-4" />
      </span>,
    );
    expect(container.querySelector("span")).toHaveClass("text-ok");
    expect(container.querySelector("svg")).toHaveAttribute("stroke", "currentColor");
  });

  it.each(["default", "light", "dark", "disabled", "selected", "legacy-solid"])(
    "keeps visible geometry in the %s state",
    (state) => {
      if (state === "light" || state === "dark") document.documentElement.dataset.theme = state;
      if (state === "legacy-solid") ICON_OVERRIDES["action.search"] = { treatment: "solid" };
      const { container } = render(
        <button type="button" disabled={state === "disabled"} aria-pressed={state === "selected"}>
          <Icon id="action.search" className="h-4 w-4" />
        </button>,
      );
      const svg = container.querySelector("svg");
      expect(svg?.querySelectorAll("path, circle, rect, line, polyline, polygon, ellipse").length).toBeGreaterThan(0);
      expect(svg).toHaveAttribute("stroke", "currentColor");
      expect(svg).not.toHaveAttribute("stroke", "none");
    },
  );
});
