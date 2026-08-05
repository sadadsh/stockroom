import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { ApiError, api } from "../../api/client";
import { cadVariantApi } from "../../api/cadVariantClient";
import type { ComponentWorkspaceResponse } from "../../api/workspaceTypes";
import { componentRepresentationDevId, devIdSelector } from "../../lib/componentDevIds";
import { ThemeProvider } from "../../lib/theme";
import { ToastProvider } from "../../lib/toast";
import {
  defaultUiSession,
  openComponentInSession,
  readUiSession,
  resetUiSessionForTests,
} from "../../lib/uiSession";
import {
  makeFact,
  makeOffer,
  makeRepresentation,
  makeSourceRecord,
  makeTool,
  makeWorkspace,
} from "../../test/workspaceFixture";
import { ComponentWorkspace } from "./ComponentWorkspace";
import { dockTemplate } from "./RepresentationDock";
import { primaryActionLabel } from "./ComponentHeader";
import { toolStatus } from "./workspaceStatus";

vi.mock("../../api/client", async (importActual) => {
  const actual = await importActual<typeof import("../../api/client")>();
  return {
    ...actual,
    api: {
      partWorkspace: vi.fn(),
      partHistory: vi.fn(),
      partDiff: vi.fn(),
      partDetail: vi.fn(),
      facets: vi.fn(),
      editField: vi.fn(),
      moveCategory: vi.fn(),
      setSpecs: vi.fn(),
      previewSvg: vi.fn(),
      modelGlb: vi.fn(),
      landPattern: vi.fn(),
    },
  };
});

vi.mock("../../api/cadVariantClient", async (importActual) => {
  const actual = await importActual<typeof import("../../api/cadVariantClient")>();
  return {
    ...actual,
    cadVariantApi: { inventory: vi.fn(), activatePair: vi.fn() },
  };
});

// three.js is verified in the Windows pixel gate; the dock only needs the scene to mount.
vi.mock("../../lib/threeScene", () => ({
  mountModelScene: vi.fn(() => ({
    dispose: vi.fn(),
    fit: vi.fn(),
    setView: vi.fn(),
    setSpin: vi.fn((wanted: boolean) => wanted),
    setLandPattern: vi.fn(),
    setRenderMode: vi.fn(),
    setLayers: vi.fn(),
    setPlacementMode: vi.fn(),
    modelInfo: vi.fn(() => null),
  })),
}));

const mockApi = vi.mocked(api);
const mockCadVariantApi = vi.mocked(cadVariantApi);

const ID = "lm358";

beforeEach(() => {
  mockApi.previewSvg.mockResolvedValue(new Blob(["<svg/>"], { type: "image/svg+xml" }));
  mockApi.modelGlb.mockResolvedValue(new Uint8Array([0x67, 0x6c, 0x54, 0x46]).buffer);
  mockApi.landPattern.mockRejectedValue(new ApiError(404, "no footprint"));
  mockCadVariantApi.inventory.mockResolvedValue({
    partId: ID,
    inventories: [],
    pairs: [],
    supplementary: [],
  });
  mockApi.partHistory.mockResolvedValue({ commits: [], count: 0 });
  mockApi.facets.mockResolvedValue({
    by_category: { ICs: 1 },
    by_manufacturer: {},
    complete: 1,
    incomplete: 0,
    category_catalog: ["ICs", "Passives"],
  });
});

function provide(ui: ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <ThemeProvider>
        <ToastProvider>{ui}</ToastProvider>
      </ThemeProvider>
    </QueryClientProvider>,
  );
}

/** Open the component the way the page does, so its view state has somewhere to live. */
async function open(workspace: ComponentWorkspaceResponse = makeWorkspace()) {
  resetUiSessionForTests(openComponentInSession(defaultUiSession(), ID));
  mockApi.partWorkspace.mockResolvedValue(workspace);
  const view = provide(<ComponentWorkspace componentId={ID} />);
  await screen.findByRole("heading", { name: workspace.identity.displayName });
  return view;
}

function module(kind: "symbol" | "footprint" | "model"): HTMLElement {
  return document.querySelector<HTMLElement>(
    devIdSelector(componentRepresentationDevId(ID, kind)),
  )!;
}

describe("component identity header", () => {
  it("states identity, both design tools' compact status, and one primary action", async () => {
    await open(
      makeWorkspace({
        identity: { value: "10k", package: "0402", lifecycle: "Active" },
        representations: {
          symbol: makeRepresentation("symbol", "missing", [
            makeTool({ tool: "kicad", present: false, status: "missing" }),
          ]),
        },
      }),
    );

    const header = document.querySelector<HTMLElement>('[data-dev-id="component-browser.header"]')!;
    expect(within(header).getByRole("heading", { name: "LM358" })).toBeInTheDocument();
    expect(within(header).getByText("LM358DR")).toBeInTheDocument();
    expect(within(header).getByText("Texas Instruments")).toBeInTheDocument();
    expect(within(header).getByText("0402")).toBeInTheDocument();
    expect(within(header).getByText("ICs")).toBeInTheDocument();
    expect(within(header).getByText("Active")).toBeInTheDocument();
    // A value distinct from the part number earns its own place; one equal to it does not.
    expect(within(header).getByText("10k")).toBeInTheDocument();
    // The compact status uses the closed vocabulary, per tool.
    expect(within(header).getByText("KiCad Missing")).toBeInTheDocument();
    expect(within(header).getByText(/^Altium /)).toBeInTheDocument();
    expect(within(header).getByRole("button", { name: "Datasheet" })).toBeInTheDocument();
  });

  it("omits a value that only repeats the part number", async () => {
    await open(makeWorkspace({ identity: { value: "LM358DR" } }));
    const header = document.querySelector<HTMLElement>('[data-dev-id="component-browser.header"]')!;
    expect(within(header).getAllByText("LM358DR")).toHaveLength(1);
  });

  /**
   * The 960px supported minimum, asserted structurally.
   *
   * jsdom has no layout, so "is this readable" cannot be measured here. What CAN be pinned is the
   * rule that produced the defect: the fact row used to be a single line whose values were the only
   * shrinkable thing on it, so at 960 it rendered `Manufacturer Package Category` and no facts at
   * all. These assertions fail the moment the label stops being the part that yields.
   */
  it("keeps the identity values on screen at a narrow width and lets the labels yield instead", async () => {
    await open();
    const header = document.querySelector<HTMLElement>('[data-dev-id="component-browser.header"]')!;
    const facts = header.querySelector("dl")!;

    // A floor, not a leftover: the facts claim a basis, and the actions take their own line when
    // they cannot sit beside it. A value squeezed to an ellipsis is a value the person has lost.
    expect(facts.className).toContain("basis-40");
    expect(facts.className).toContain("flex-wrap");
    expect(facts.parentElement!.className).toContain("flex-wrap");

    for (const [label, value] of [
      ["Manufacturer", "Texas Instruments"],
      ["Package", "SOIC-8"],
      ["Category", "ICs"],
    ] as const) {
      const term = within(facts).getByText(label);
      const detail = term.parentElement!.querySelector("dd")!;
      expect(detail).toHaveTextContent(value);
      // The label is hidden VISUALLY below the threshold and is still in the tree, so a screen
      // reader keeps hearing which fact this is.
      expect(term.className).toContain("sr-only");
      expect(term.className).toContain("@[48rem]:not-sr-only");
      expect(detail.className).not.toContain("sr-only");
      // The hover title answers the same question a pointer user lost with the inline label.
      expect(term.parentElement).toHaveAttribute("title", `${label} ${value}`);
    }
  });

  it("names the primary action after the worst thing wrong with the component", () => {
    expect(primaryActionLabel(null)).toBe("Open Full Specifications");
    expect(primaryActionLabel("edit-identity")).toBe("Add Missing Identity");
    expect(primaryActionLabel("open-representation:model")).toBe("Fix 3D Model");
    expect(primaryActionLabel("open-representation:symbol")).toBe("Fix Symbol");
    expect(primaryActionLabel("open-field-source:package")).toBe("Resolve Source Conflict");
    expect(primaryActionLabel("open-requirements")).toBe("Review Requirements");
  });
});

describe("compact tool status", () => {
  const base = makeWorkspace().representations;

  it("is worst-first, and only says how ready once nothing is wrong", () => {
    const withStatus = (...tools: Parameters<typeof makeTool>[0][]) => ({
      ...base,
      symbol: makeRepresentation("symbol", "ready", [makeTool(tools[0])]),
      footprint: makeRepresentation("footprint", "ready", [makeTool(tools[1] ?? tools[0])]),
      model: makeRepresentation("model", "ready", [makeTool(tools[2] ?? tools[0])]),
    });
    expect(toolStatus(withStatus({ status: "failed" }), "kicad")).toBe("Failed");
    expect(toolStatus(withStatus({ status: "missing", present: false }), "kicad")).toBe("Missing");
    expect(toolStatus(withStatus({ status: "review" }), "kicad")).toBe("Needs Review");
    expect(toolStatus(withStatus({ status: "not_required", present: false }), "kicad")).toBe(
      "Not Required",
    );
    // Downloaded from a named provider, but nothing has checked it.
    expect(toolStatus(withStatus({ sourceId: "snapeda", checks: [] }), "kicad")).toBe("Downloaded");
    // A recorded check that passed is a stronger claim than a download.
    expect(
      toolStatus(
        withStatus({
          checks: [
            { check: "pins", measured: 8, expected: 8, against: "datasheet", checkedAt: "", note: "" },
          ],
        }),
        "kicad",
      ),
    ).toBe("Validated");
    // Present, unchecked, and nobody says where it came from.
    expect(toolStatus(withStatus({ sourceId: "", checks: [] }), "kicad")).toBe("Available");
    expect(toolStatus(base, "nonexistent-tool")).toBe("Unknown");
  });
});

describe("representation dock", () => {
  it("shows all three representations side by side by default", async () => {
    await open();
    expect(module("symbol")).toBeInTheDocument();
    expect(module("footprint")).toBeInTheDocument();
    expect(module("model")).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: "All" })).toHaveAttribute("aria-checked", "true");
    // Three equal tracks: nothing is a rail, nothing is stacked into a scrolling column.
    expect(dockTemplate("all")).toBe("minmax(0,1fr) minmax(0,1fr) minmax(0,1fr)");
  });

  it("expands one representation and keeps the other two reachable as rails", async () => {
    await open();
    const user = userEvent.setup();

    for (const kind of ["symbol", "footprint", "model"] as const) {
      const label = kind === "model" ? "3D Model" : kind === "symbol" ? "Symbol" : "Footprint";
      await user.click(screen.getByRole("radio", { name: label }));
      await waitFor(() =>
        expect(readUiSession().component_views[ID]?.representation_layout).toBe(kind),
      );
      // All three modules are still in the DOM: expanding never removes a representation.
      expect(module("symbol")).toBeInTheDocument();
      expect(module("footprint")).toBeInTheDocument();
      expect(module("model")).toBeInTheDocument();
      // The other two are rails, and each rail is the control that switches back to it.
      const rails = document.querySelectorAll('[data-dev-id="component-browser.representation-rail"]');
      expect(rails).toHaveLength(2);
      expect(dockTemplate(kind).split(" ").filter((track) => track === "40px")).toHaveLength(2);
    }
  });

  it("switches layout when a collapsed rail is clicked", async () => {
    await open();
    const user = userEvent.setup();
    await user.click(screen.getByRole("radio", { name: "Symbol" }));
    await waitFor(() =>
      expect(readUiSession().component_views[ID]?.representation_layout).toBe("symbol"),
    );

    await user.click(within(module("model")).getByRole("button", { name: "Show 3D Model" }));

    await waitFor(() =>
      expect(readUiSession().component_views[ID]?.representation_layout).toBe("model"),
    );
    expect(within(module("symbol")).getByRole("button", { name: "Show Symbol" })).toBeInTheDocument();
  });

  it("walks the three modules with the arrow keys", async () => {
    await open();
    const controls = () =>
      Array.from(
        document.querySelectorAll<HTMLElement>("[data-representation-control]"),
      );
    controls()[0].focus();
    expect(document.activeElement).toBe(controls()[0]);

    await userEvent.keyboard("{ArrowRight}");
    expect(document.activeElement).toBe(controls()[1]);
    await userEvent.keyboard("{ArrowRight}");
    expect(document.activeElement).toBe(controls()[2]);
    // Wraps, so the strip has no dead end.
    await userEvent.keyboard("{ArrowRight}");
    expect(document.activeElement).toBe(controls()[0]);
    await userEvent.keyboard("{ArrowLeft}");
    expect(document.activeElement).toBe(controls()[2]);
    await userEvent.keyboard("{Home}");
    expect(document.activeElement).toBe(controls()[0]);
    // Focus moved without collapsing anything: arrowing past a module must not re-lay-out the dock.
    expect(readUiSession().component_views[ID]?.representation_layout).toBe("all");
  });

  it("states one concise issue and reaches the retained-variant chooser from Details", async () => {
    await open(
      makeWorkspace({
        representations: {
          footprint: makeRepresentation("footprint", "failed", [makeTool({ status: "failed" })]),
        },
      }),
    );
    const user = userEvent.setup();
    expect(
      within(module("footprint")).getByText("A recorded check did not pass."),
    ).toBeInTheDocument();

    await user.click(within(module("footprint")).getByRole("button", { name: "Details" }));

    const dialog = await screen.findByRole("dialog", { name: "Footprint Details" });
    expect(within(dialog).getAllByText("KiCad").length).toBeGreaterThan(0);
    await waitFor(() => expect(mockCadVariantApi.inventory).toHaveBeenCalledWith(ID));
  });

  /**
   * The other half of the 960px minimum. A native `<select>` sizes itself to its widest option and
   * carries a platform arrow, so it held 111px of a 176px module column and the title truncated to
   * `S` and `F`. A single letter is not a label, so the name and the status are now the fixed part
   * of that row and the tool chooser is what gives way.
   */
  it("keeps every module's title and status whole, and lets the tool chooser narrow instead", async () => {
    await open(
      makeWorkspace({
        representations: {
          symbol: makeRepresentation("symbol", "ready", [
            makeTool({ tool: "kicad", toolLabel: "KiCad" }),
            makeTool({ tool: "altium", toolLabel: "Altium" }),
          ]),
        },
      }),
    );

    for (const [kind, label] of [
      ["symbol", "Symbol"],
      ["footprint", "Footprint"],
      ["model", "3D Model"],
    ] as const) {
      const title = within(module(kind)).getByRole("button", { name: label });
      expect(title).toHaveTextContent(label);
      // Never a shrink candidate, so the whole word survives however narrow the column gets.
      expect(title.className).toContain("flex-none");
      expect(title.className).not.toContain("truncate");
      // The status has to survive the same squeeze: a module with no readable status states nothing.
      expect(within(module(kind)).getByText(/^(Ready|Not Required)$/)).toBeInTheDocument();
    }

    const chooser = within(module("symbol")).getByRole("combobox", { name: "Symbol tool" });
    expect(chooser.className).toContain("max-w-full");
  });

  it("persists the selected tool per representation kind", async () => {
    await open(
      makeWorkspace({
        representations: {
          symbol: makeRepresentation("symbol", "ready", [
            makeTool({ tool: "kicad", toolLabel: "KiCad" }),
            makeTool({ tool: "altium", toolLabel: "Altium" }),
          ]),
        },
      }),
    );
    const user = userEvent.setup();

    await user.selectOptions(
      within(module("symbol")).getByRole("combobox", { name: "Symbol tool" }),
      "altium",
    );

    await waitFor(() =>
      expect(readUiSession().component_views[ID]?.representation_tool.symbol).toBe("altium"),
    );
    expect(readUiSession().component_views[ID]?.representation_tool.footprint).toBe("");
  });
});

describe("information tabs", () => {
  it("offers exactly the four questions, and persists the active one", async () => {
    await open();
    const user = userEvent.setup();
    const strip = document.querySelector<HTMLElement>('[data-dev-id="component-browser.info.tabs"]')!;
    expect(within(strip).getAllByRole("tab").map((tab) => tab.textContent)).toEqual([
      "Overview",
      "Specifications",
      "Sourcing",
      "Sources & History",
    ]);

    await user.click(within(strip).getByRole("tab", { name: "Sources & History" }));

    await waitFor(() => expect(readUiSession().component_views[ID]?.info_tab).toBe("sources"));
    expect(screen.getByLabelText("Source Records")).toBeInTheDocument();
  });

  it("renders real data in every tab rather than an empty placeholder", async () => {
    await open(
      makeWorkspace({
        specifications: {
          total: 2,
          pinCount: 8,
          groups: [
            {
              id: "electrical",
              label: "Electrical",
              count: 2,
              facts: [
                makeFact({ id: "Supply Voltage", label: "Supply Voltage", rawValue: "3 V" }),
                makeFact({ id: "Package", label: "Package", rawValue: "SOIC-8" }),
              ],
            },
          ],
        },
        sourcing: { offers: [makeOffer({ partNumber: "296-1234" })] },
        sources: {
          records: [makeSourceRecord({ fetchedAt: "2026-08-01" })],
        },
      }),
    );
    const user = userEvent.setup();
    const strip = document.querySelector<HTMLElement>('[data-dev-id="component-browser.info.tabs"]')!;

    // Overview: the curated key specs and the sourcing snapshot both read the projection.
    expect(screen.getByText("Supply Voltage")).toBeInTheDocument();
    expect(within(screen.getByLabelText("Sourcing Snapshot")).getByText("DigiKey")).toBeInTheDocument();

    await user.click(within(strip).getByRole("tab", { name: "Specifications" }));
    const groups = await screen.findByLabelText("Specification Groups");
    const electrical = within(groups).getByText("Electrical").closest("li")!;
    expect(within(electrical).getByText("2")).toBeInTheDocument();

    await user.click(within(strip).getByRole("tab", { name: "Sourcing" }));
    const distributors = await screen.findByLabelText("Distributors");
    expect(within(distributors).getByText("DigiKey")).toBeInTheDocument();

    await user.click(within(strip).getByRole("tab", { name: "Sources & History" }));
    const records = await screen.findByLabelText("Source Records");
    expect(within(records).getByText("DigiKey")).toBeInTheDocument();
  });

  it("opens the full sheet in a modal, which is the only surface allowed to scroll", async () => {
    await open(
      makeWorkspace({
        specifications: {
          total: 1,
          groups: [
            {
              id: "electrical",
              label: "Electrical",
              count: 1,
              facts: [makeFact({ id: "Supply Voltage", label: "Supply Voltage", rawValue: "3 V" })],
            },
          ],
        },
      }),
    );
    const user = userEvent.setup();

    // Overview's View All hands off to the Specifications TAB; that tab's own View All opens the
    // exhaustive sheet, which is the only surface here allowed to scroll.
    await user.click(
      within(screen.getByLabelText("Key Specifications")).getByRole("button", { name: "View All" }),
    );
    await user.click(
      within(await screen.findByLabelText("Specification Groups")).getByRole("button", {
        name: "View All Specifications",
      }),
    );

    const dialog = await screen.findByRole("dialog", { name: "Specifications" });
    expect(within(dialog).getByText("Electrical (1)")).toBeInTheDocument();
    await user.click(within(dialog).getByRole("button", { name: "Close" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });
});

describe("overview", () => {
  it("marks a description its sources disagree about", async () => {
    await open(
      makeWorkspace({
        summary: {
          description: makeFact({
            id: "description",
            label: "Description",
            rawValue: "Dual op-amp",
            state: "conflict",
          }),
        },
      }),
    );
    const region = document.querySelector<HTMLElement>(
      '[data-dev-id="component-browser.description"]',
    )!;
    expect(within(region).getByText("Sources Disagree")).toBeInTheDocument();
  });

  it("renders every attention item with the action it names", async () => {
    await open(
      makeWorkspace({
        attention: [
          {
            id: "representation.symbol",
            severity: "blocking",
            title: "Symbol Missing",
            detail: "No file is attached yet.",
            action: "open-representation:symbol",
          },
          {
            id: "conflict.package",
            severity: "warning",
            title: "Sources Disagree On Package",
            detail: "2 values were offered.",
            action: "open-field-source:package",
          },
        ],
      }),
    );
    const user = userEvent.setup();
    const region = screen.getByLabelText("Needs Attention");
    const items = within(region).getAllByRole("listitem");
    expect(items).toHaveLength(2);
    expect(within(region).getByText("Symbol Missing")).toBeInTheDocument();
    expect(within(region).getByText("2 values were offered.")).toBeInTheDocument();

    // The action is the point of an attention item: acting on a representation problem takes you
    // to that representation.
    await user.click(
      // The action name is "Resolve: <what is wrong>". It used to be "<title>: <raw action token>",
      // which read out "open-representation:symbol" to a screen reader - an internal routing key,
      // not a sentence a person can act on.
      within(items[0]).getByRole("button", { name: "Resolve: Symbol Missing" }),
    );
    await waitFor(() =>
      expect(readUiSession().component_views[ID]?.representation_layout).toBe("symbol"),
    );

    // A source disagreement is answered where attribution lives.
    await user.click(
      within(items[1]).getByRole("button", {
        name: "Resolve: Sources Disagree On Package",
      }),
    );
    await waitFor(() => expect(readUiSession().component_views[ID]?.info_tab).toBe("sources"));
  });

  it("says so honestly when nothing needs attention", async () => {
    await open();
    expect(
      within(screen.getByLabelText("Needs Attention")).getByText("Nothing needs attention."),
    ).toBeInTheDocument();
  });
});
