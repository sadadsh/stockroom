import { render, screen } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it } from "vitest";
import { TabStrip } from "./primitives";

const TABS = [
  { id: "specs", label: "Specs" },
  { id: "sourcing", label: "Sourcing" },
] as const;

type TabId = (typeof TABS)[number]["id"];

// A tiny controlled host so the tablist is rendered exactly as real callers use it.
function Host({ devIdBase }: { devIdBase?: string }) {
  const [active, setActive] = useState<TabId>("specs");
  return (
    <TabStrip
      tabs={TABS}
      active={active}
      onSelect={setActive}
      idBase="workbench"
      devIdBase={devIdBase}
      aria-label="Part details"
    />
  );
}

describe("TabStrip devIdBase passthrough", () => {
  it("emits derived data-dev-ids on the tablist and each tab when devIdBase is set", () => {
    render(<Host devIdBase="detail" />);
    const tablist = screen.getByRole("tablist", { name: "Part details" });
    expect(tablist).toHaveAttribute("data-dev-id", "detail.tabs");
    expect(screen.getByRole("tab", { name: "Specs" })).toHaveAttribute(
      "data-dev-id",
      "detail.tab-specs",
    );
    expect(screen.getByRole("tab", { name: "Sourcing" })).toHaveAttribute(
      "data-dev-id",
      "detail.tab-sourcing",
    );
  });

  it("derives from a different base to match the catalog (projects)", () => {
    render(<Host devIdBase="projects" />);
    expect(screen.getByRole("tablist")).toHaveAttribute("data-dev-id", "projects.tabs");
    expect(screen.getByRole("tab", { name: "Specs" })).toHaveAttribute(
      "data-dev-id",
      "projects.tab-specs",
    );
  });

  it("emits no data-dev-id when devIdBase is omitted", () => {
    render(<Host />);
    expect(screen.getByRole("tablist")).not.toHaveAttribute("data-dev-id");
    for (const tab of screen.getAllByRole("tab")) {
      expect(tab).not.toHaveAttribute("data-dev-id");
    }
  });
});
