import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Icon } from "./Icon";
import type { IconId } from "../lib/iconRegistry";

function rendered(node: React.ReactElement): SVGSVGElement {
  const { container } = render(node);
  const svg = container.querySelector("svg");
  if (!svg) throw new Error("expected an <svg>");
  return svg;
}

describe("detail icon grammar", () => {
  it.each([
    "detail.chevron-right",
    "detail.ready-check",
    "detail.select-chevron",
    "finder.filter",
  ])("renders %s on the shared 24px, 2px outline frame", (id) => {
    const svg = rendered(<Icon id={id as IconId} className="h-3.5 w-3.5" />);
    expect(svg).toHaveClass("ico", "h-3.5", "w-3.5");
    expect(svg).toHaveAttribute("viewBox", "0 0 24 24");
    expect(svg).toHaveAttribute("fill", "none");
    expect(svg).toHaveAttribute("stroke", "currentColor");
    expect(svg).toHaveAttribute("stroke-width", "2");
  });

  it("keeps an untitled selector decorative", () => {
    const svg = rendered(<Icon id="detail.select-chevron" className="h-3 w-3" />);
    expect(svg).toHaveAttribute("aria-hidden", "true");
  });
});
