import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { IconBrowser } from "./IconBrowser";

describe("IconBrowser", () => {
  it("searches the offline catalogue and returns a sanitized SVG body", async () => {
    const select = vi.fn();
    const user = userEvent.setup();
    render(<IconBrowser onSelect={select} targetViewBox="0 0 24 24" />);

    await user.type(screen.getByRole("searchbox", { name: "Search Icon Catalog" }), "github");
    await user.click(await screen.findByRole("button", { name: "Select github" }));

    expect(select).toHaveBeenCalledWith(expect.objectContaining({
      family: "brands",
      label: "github",
      body: expect.not.stringContaining("http"),
    }));
    expect(select.mock.calls[0]?.[0].body).toContain("transform=");
    expect(select.mock.calls[0]?.[0].body).toContain('stroke="none"');
  });
});
