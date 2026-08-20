import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { neutralIconRegistry } from "./icons";
import type { IconId } from "../../lib/iconRegistry";

const THEME_CONTRACT_IDS = ["status.error", "status.success", "status.info"] as const satisfies readonly IconId[];

describe("neutral theme icon adapter", () => {
  it("keeps status semantics distinct and typed", () => {
    expect(THEME_CONTRACT_IDS).toEqual(["status.error", "status.success", "status.info"]);
    const { container } = render(neutralIconRegistry.error);
    expect(container.querySelector("svg")).toHaveAttribute("data-icon-id", "status.error");
    const success = render(neutralIconRegistry.success);
    expect(success.container.querySelector("svg")).toHaveAttribute("data-icon-id", "status.success");
    const info = render(neutralIconRegistry.info);
    expect(info.container.querySelector("svg")).toHaveAttribute("data-icon-id", "status.info");
  });

  it("renders every Astryx glyph from the central Tabler Outline authority", () => {
    for (const [name, icon] of Object.entries(neutralIconRegistry)) {
      const { container, unmount } = render(icon);
      const svg = container.querySelector("svg");
      expect(svg, name).not.toBeNull();
      expect(svg, name).toHaveAttribute("data-icon-family", "tabler-outline");
      expect(svg?.getAttribute("data-icon-id"), name).toMatch(/^[a-z]+\.[a-z0-9-]+$/);
      expect(svg, name).toHaveAttribute("viewBox", "0 0 24 24");
      expect(svg, name).toHaveAttribute("fill", "none");
      expect(svg, name).toHaveAttribute("stroke", "currentColor");
      expect(svg, name).toHaveAttribute("stroke-width", "2");
      unmount();
    }
  });
});
