import { render, screen } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it } from "vitest";
import { Button, Card, Dot, Panel, RouteHeader, TabStrip } from "./primitives";

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

  it("derives ids from any supplied base", () => {
    render(<Host devIdBase="sample" />);
    expect(screen.getByRole("tablist")).toHaveAttribute("data-dev-id", "sample.tabs");
    expect(screen.getByRole("tab", { name: "Specs" })).toHaveAttribute(
      "data-dev-id",
      "sample.tab-specs",
    );
  });

  it("emits no data-dev-id when devIdBase is omitted", () => {
    render(<Host />);
    expect(screen.getByRole("tablist")).not.toHaveAttribute("data-dev-id");
    for (const tab of screen.getAllByRole("tab")) {
      expect(tab).not.toHaveAttribute("data-dev-id");
    }
  });

  it("supports the compact title-strip density without changing the default", () => {
    const { rerender } = render(
      <TabStrip
        tabs={TABS}
        active="specs"
        onSelect={() => {}}
        idBase="compact-workbench"
        density="compact"
        aria-label="Compact tabs"
      />,
    );
    expect(screen.getByRole("tab", { name: "Specs" })).toHaveClass("text-xs", "py-0.5");

    rerender(
      <TabStrip
        tabs={TABS}
        active="specs"
        onSelect={() => {}}
        idBase="default-workbench"
        aria-label="Default tabs"
      />,
    );
    expect(screen.getByRole("tab", { name: "Specs" })).toHaveClass("text-sm", "py-1");
  });
});

describe("RouteHeader's count", () => {
  it("sits NEXT TO the panel name, not flushed to the far edge", () => {
    // Same defect as the spec-group counts, in the twin nobody looked at. On the owner's real
    // window the Components panel is 320px wide and `justify-between` put its "1" about 290px
    // from the word it counts - while the "Diodes 1" group header 100px below it now reads
    // adjacent. One screen, two treatments, and the inconsistency was introduced by fixing only
    // one of them.
    //
    // Every call site passes a COUNT (a number, "N of M", "N active"), never a control, so there
    // is nothing here that wants to be flushed right.
    render(<RouteHeader right="1">Components</RouteHeader>);
    const title = screen.getByText("Components");
    const bar = title.parentElement!;
    expect(bar.className).not.toContain("justify-between");
    const spans = Array.from(bar.querySelectorAll("span"));
    expect(spans[spans.indexOf(title) + 1]?.textContent).toBe("1");
  });
});

describe("status marks", () => {
  it("distinguishes warning from neutral by shape, not color", () => {
    const { container } = render(
      <>
        <Dot tone="warn" />
        <Dot tone="neutral" />
      </>,
    );
    const [warning, neutral] = Array.from(container.children);
    expect(warning.querySelector("svg")).not.toBeNull();
    expect(neutral.querySelector("svg")).toBeNull();
    expect(neutral).toHaveClass("rounded-full");
  });
});

describe("quiet hierarchy", () => {
  it("leaves routine cards and secondary actions unboxed", () => {
    render(
      <>
        <Card data-testid="card">Routine content</Card>
        <Button>Secondary Action</Button>
        <Button variant="accent">Primary Action</Button>
        <Panel data-testid="panel">Major region</Panel>
      </>,
    );

    expect(screen.getByTestId("card")).not.toHaveClass("border");
    expect(screen.getByRole("button", { name: "Secondary Action" })).not.toHaveClass("border");
    expect(screen.getByRole("button", { name: "Primary Action" })).toHaveClass("bg-acc");
    expect(screen.getByTestId("panel")).toHaveClass("border");
  });
});
