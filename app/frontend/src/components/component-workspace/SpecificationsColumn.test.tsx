/**
 * The Specifications column's two navigation surfaces: the search box and the section strip.
 *
 * Both are FILTERS AND JUMPS, never pages. Neither may navigate away, replace the column's
 * content, open a second surface, or add a second scrollbar - the workspace owns exactly three
 * scroll containers and a fourth would make "where am I" unanswerable. That is the property these
 * tests hold, because it is the one that quietly breaks when a filter is reimplemented as a view.
 *
 * The strip is built from what the dossier SENT for this category. A resistor has no Timing group
 * and a connector has no Memory group, so a fixed strip would offer links that scroll to nothing.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createRef } from "react";
import type { ComponentDossier } from "../../api/dossierTypes";
import { devIdSelector } from "../../lib/componentDevIds";
import { ThemeProvider } from "../../lib/theme";
import { makeCandidate, makeDossierWith, makeSpecification } from "../../test/dossierFixture";
import { SpecificationsColumn } from "./SpecificationsColumn";

const MOUSER = makeCandidate({
  sourceId: "mouser",
  sourceLabel: "Mouser",
  value: "3.0",
  displayValue: "3.0",
});

function dossier(): ComponentDossier {
  return makeDossierWith({
    keySpecifications: [
      makeSpecification({
        key: "supply_voltage",
        label: "Supply Voltage",
        group: "electrical",
        groupLabel: "Electrical",
        displayValue: "3.3",
        unit: "V",
        importance: "key",
      }),
    ],
    groups: [
      {
        id: "electrical",
        label: "Electrical",
        specifications: [
          makeSpecification({
            key: "supply_voltage",
            label: "Supply Voltage",
            group: "electrical",
            groupLabel: "Electrical",
            displayValue: "3.3",
            unit: "V",
            sourceCandidates: [MOUSER],
            preferredSource: MOUSER,
          }),
        ],
      },
      {
        id: "package_mechanical",
        label: "Package and Mechanical",
        specifications: [
          makeSpecification({
            key: "pin_count",
            label: "Pin Count",
            group: "package_mechanical",
            groupLabel: "Package and Mechanical",
            displayValue: "5",
            unit: "",
          }),
        ],
      },
      {
        id: "environmental_reliability",
        label: "Environmental and Reliability",
        specifications: [
          makeSpecification({
            key: "operating_temperature",
            label: "Operating Temperature",
            group: "environmental_reliability",
            groupLabel: "Environmental and Reliability",
            displayValue: "-40 to 125",
            unit: "°C",
          }),
        ],
      },
    ],
  });
}

function open(document_: ComponentDossier = dossier()) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const scrollRef = createRef<HTMLDivElement>() as { current: HTMLDivElement | null };
  const view = render(
    <QueryClientProvider client={qc}>
      <ThemeProvider>
        <SpecificationsColumn
          componentId="lm358"
          dossier={document_}
          filter="all"
          onFilter={() => {}}
          scrollRef={scrollRef}
          onViewPinout={() => {}}
        />
      </ThemeProvider>
    </QueryClientProvider>,
  );
  return { view, scrollRef };
}

function visibleRowKeys(): string[] {
  return [...document.querySelectorAll<HTMLElement>("[data-spec-key]")].map(
    (row) => row.dataset.specKey ?? "",
  );
}

function searchBox(): HTMLElement {
  return screen.getByRole("searchbox", { name: "Search specifications" });
}

describe("searching the specification sheet", () => {
  it("is a real inline input in the column's own toolbar, not a separate surface", () => {
    open();
    const input = searchBox();
    expect(input).toHaveAttribute("placeholder", "Search specifications…");
    // Above the scroller, inside the column, alongside the four filters.
    expect(
      input.closest(devIdSelector("component-browser.column-specifications")),
    ).not.toBeNull();
  });

  it("narrows by label", async () => {
    const user = userEvent.setup();
    open();
    await user.type(searchBox(), "pin count");
    expect(visibleRowKeys()).toEqual(["pin_count"]);
  });

  it("narrows by the UNIT a field is measured in", async () => {
    const user = userEvent.setup();
    open();
    await user.type(searchBox(), "°C");
    expect(visibleRowKeys()).toEqual(["operating_temperature"]);
  });

  it("narrows by the GROUP a field belongs to", async () => {
    const user = userEvent.setup();
    open();
    await user.type(searchBox(), "environmental");
    expect(visibleRowKeys()).toEqual(["operating_temperature"]);
  });

  it("narrows by a source that offered an answer, not only by the one in force", async () => {
    const user = userEvent.setup();
    open();
    await user.type(searchBox(), "mouser");
    expect(visibleRowKeys()).toEqual(["supply_voltage"]);
  });

  it("narrows by the value itself", async () => {
    const user = userEvent.setup();
    open();
    await user.type(searchBox(), "3.3");
    // The key block and the electrical group both carry it, which is the intended duplication.
    expect(visibleRowKeys()).toEqual(["supply_voltage", "supply_voltage"]);
  });

  it("keeps the rows where they are instead of replacing the column with a result list", async () => {
    const user = userEvent.setup();
    open();
    await user.type(searchBox(), "pin count");
    // The heading the surviving row belongs to is still its heading, the toolbar is still there,
    // and nothing navigated: a filter narrows a list, it does not become a page.
    expect(screen.getByText("Package and Mechanical")).toBeInTheDocument();
    expect(searchBox()).toHaveValue("pin count");
    expect(
      document.querySelectorAll(devIdSelector("component-browser.spec-filter")),
    ).toHaveLength(4);
  });

  it("says nothing matched rather than showing an empty sheet", async () => {
    const user = userEvent.setup();
    open();
    await user.type(searchBox(), "flux capacitance");
    expect(visibleRowKeys()).toEqual([]);
    expect(screen.getByText("No specification matches this filter.")).toBeInTheDocument();
  });
});

describe("the section anchor strip", () => {
  it("lists the headings this part actually has, key specifications first", () => {
    open();
    const strip = document.querySelector<HTMLElement>(
      devIdSelector("component-browser.spec-anchors"),
    )!;
    expect(
      within(strip)
        .getAllByRole("button")
        .map((button) => button.textContent),
    ).toEqual([
      "Main Specifications",
      "Electrical",
      "Package and Mechanical",
      "Environmental and Reliability",
    ]);
  });

  it("offers no heading this category never sent", () => {
    open();
    const strip = document.querySelector<HTMLElement>(
      devIdSelector("component-browser.spec-anchors"),
    )!;
    // A fixed strip would offer Timing and Memory here; this part has neither.
    expect(strip.textContent).not.toContain("Timing");
    expect(strip.textContent).not.toContain("Memory");
  });

  it("points every anchor at a section that is really on the screen", () => {
    open();
    for (const anchor of document.querySelectorAll<HTMLElement>("[data-spec-anchor]")) {
      const id = anchor.dataset.specAnchor!;
      expect(
        document.querySelector(`[data-spec-section="${id}"]`),
        `no section for anchor ${id}`,
      ).not.toBeNull();
    }
  });

  it("drops an anchor whose group the current search emptied", async () => {
    const user = userEvent.setup();
    open();
    await user.type(searchBox(), "pin count");
    const strip = document.querySelector<HTMLElement>(
      devIdSelector("component-browser.spec-anchors"),
    );
    // Only one heading survives, so there is nothing left to jump BETWEEN and the strip goes.
    expect(strip).toBeNull();
  });

  it("scrolls the column's own container and never replaces its content", async () => {
    const user = userEvent.setup();
    const { scrollRef } = open();
    const before = visibleRowKeys();
    const scroller = scrollRef.current!;
    const scrollTo = vi.fn();
    Object.defineProperty(scroller, "scrollTop", { set: scrollTo, get: () => 0 });

    await user.click(screen.getByTitle("Go to Environmental and Reliability"));

    // The column's scroller is the one that moved, and every row is still exactly where it was.
    expect(scrollTo).toHaveBeenCalled();
    expect(visibleRowKeys()).toEqual(before);
  });

  it("adds no second scrollbar of its own", () => {
    open();
    const strip = document.querySelector<HTMLElement>(
      devIdSelector("component-browser.spec-anchors"),
    )!;
    // It wraps. A horizontal scroller here would be a fourth scroll owner in a workspace that
    // has exactly three, and nobody can predict which one a wheel gesture moves.
    expect(strip.className).toContain("flex-wrap");
    expect(strip.className).not.toContain("overflow-x");
  });
});

describe("what the column shows before anybody filters anything", () => {
  it("opens with every group expanded, because the numbers are what a person came for", () => {
    open();
    for (const toggle of document.querySelectorAll(
      devIdSelector("component-browser.spec-group-toggle"),
    )) {
      expect(toggle).toHaveAttribute("aria-expanded", "true");
    }
  });

  it("lets a group be collapsed once somebody asks for that", async () => {
    const user = userEvent.setup();
    open();
    const toggle = [
      ...document.querySelectorAll<HTMLElement>(
        devIdSelector("component-browser.spec-group-toggle"),
      ),
    ].find((button) => button.textContent?.includes("Package and Mechanical"))!;
    await user.click(toggle);
    expect(visibleRowKeys()).not.toContain("pin_count");
  });

  it("keeps a key specification in its engineering group as well as the headline block", () => {
    open();
    // The dossier sends it in both places on purpose: the headline answers "what is this part",
    // the group answers "what does it do electrically", and one number answers both.
    expect(visibleRowKeys().filter((key) => key === "supply_voltage")).toHaveLength(2);
  });
});
