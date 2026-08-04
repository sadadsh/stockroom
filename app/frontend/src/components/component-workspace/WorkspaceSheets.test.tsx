/**
 * The exhaustive sheets, and the capabilities Slice 2 had left unreachable.
 *
 * Two contracts run through everything here. The compact tabs are SUMMARIES - they show counts and
 * a couple of representative rows and never grow into the sheet they hand off to, because the
 * workspace viewport does not scroll. And the sheets never overclaim: a distributor's suggested
 * substitution is labelled as unvalidated, a source that failed is not shown as one with no data,
 * and diagnostics stay collapsed instead of putting record hashes above the question a person came
 * with.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { ApiError, api } from "../../api/client";
import { cadVariantApi } from "../../api/cadVariantClient";
import type { ComponentWorkspaceResponse } from "../../api/workspaceTypes";
import { ThemeProvider } from "../../lib/theme";
import { ToastProvider } from "../../lib/toast";
import {
  defaultUiSession,
  openComponentInSession,
  resetUiSessionForTests,
} from "../../lib/uiSession";
import {
  makeFact,
  makeOffer,
  makeSourceRecord,
  makeWorkspace,
} from "../../test/workspaceFixture";
import { ComponentWorkspace } from "./ComponentWorkspace";
import { canApplyAlternate } from "./SourcesSheet";
import { factMatches, pinoutColumns, sheetGroups } from "./SpecificationsSheet";
import { representativeLine } from "./InfoTabPanels";

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
      refreshSourcing: vi.fn(),
      enrichPart: vi.fn(),
      openJobStream: vi.fn(),
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

async function open(workspace: ComponentWorkspaceResponse = makeWorkspace()) {
  resetUiSessionForTests(openComponentInSession(defaultUiSession(), ID));
  mockApi.partWorkspace.mockResolvedValue(workspace);
  const view = provide(<ComponentWorkspace componentId={ID} />);
  await screen.findByRole("heading", { name: workspace.identity.displayName });
  return view;
}

function streamOf(chunks: string[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder();
  return new ReadableStream<Uint8Array>({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(encoder.encode(chunk));
      controller.close();
    },
  });
}

/** Nine facts across two groups: enough that "renders them all" is a real distinction. */
function bigSpecs() {
  const electrical = ["Supply Voltage", "Quiescent Current", "Slew Rate", "Gain", "Noise"];
  const physical = ["Package", "Pitch", "Height", "Lead Count"];
  return {
    total: electrical.length + physical.length,
    pinCount: 2,
    pinout: [
      { pin: "1", name: "OUT1", type: "output" },
      { pin: "2", name: "IN1-", type: "input" },
    ],
    groups: [
      {
        id: "electrical",
        label: "Electrical",
        count: electrical.length,
        facts: electrical.map((label) =>
          makeFact({ id: label, label, rawValue: `${label} value` }),
        ),
      },
      {
        id: "physical",
        label: "Physical",
        count: physical.length,
        facts: physical.map((label) => makeFact({ id: label, label, rawValue: `${label} value` })),
      },
    ],
  };
}

/** Open the Specifications sheet the way a person does: the tab, then its View All. */
async function openSpecSheet(workspace: ComponentWorkspaceResponse) {
  await open(workspace);
  const user = userEvent.setup();
  const strip = document.querySelector<HTMLElement>('[data-dev-id="component-browser.info.tabs"]')!;
  await user.click(within(strip).getByRole("tab", { name: "Specifications" }));
  await user.click(
    within(await screen.findByLabelText("Specification Groups")).getByRole("button", {
      name: "View All Specifications",
    }),
  );
  return { user, dialog: await screen.findByRole("dialog", { name: "Specifications" }) };
}

async function openSheet(workspace: ComponentWorkspaceResponse, tab: string, title: string) {
  await open(workspace);
  const user = userEvent.setup();
  const strip = document.querySelector<HTMLElement>('[data-dev-id="component-browser.info.tabs"]')!;
  await user.click(within(strip).getByRole("tab", { name: tab }));
  const trigger = await screen.findByRole("button", { name: title });
  await user.click(trigger);
  return { user, trigger };
}

// --------------------------------------------------------------- compact vs sheet

describe("the compact specifications tab stays a summary", () => {
  it("stands for each group with two representative facts, never every row", async () => {
    await open(makeWorkspace({ specifications: bigSpecs() }));
    const user = userEvent.setup();
    const strip = document.querySelector<HTMLElement>('[data-dev-id="component-browser.info.tabs"]')!;
    await user.click(within(strip).getByRole("tab", { name: "Specifications" }));

    const region = await screen.findByLabelText("Specification Groups");
    // The counts are real and complete...
    expect(within(region).getByText("Electrical")).toBeInTheDocument();
    expect(within(region).getByText("5")).toBeInTheDocument();
    // ...but the facts themselves are a two-item stand-in, not the nine rows the record has.
    expect(within(region).queryByText("Slew Rate")).toBeNull();
    expect(within(region).queryByText("Lead Count")).toBeNull();
    expect(
      within(region).getByText("Supply Voltage Supply Voltage value · Quiescent Current Quiescent Current value"),
    ).toBeInTheDocument();
  });

  it("names two facts per group and no more", () => {
    const group = bigSpecs().groups[0];
    expect(representativeLine(group).split(" · ")).toHaveLength(2);
  });
});

describe("the full specification sheet", () => {
  it("renders every group and every fact, with the source for each value", async () => {
    const { dialog } = await openSpecSheet(makeWorkspace({ specifications: bigSpecs() }));
    expect(within(dialog).getByText("Electrical (5)")).toBeInTheDocument();
    expect(within(dialog).getByText("Physical (4)")).toBeInTheDocument();
    for (const label of ["Supply Voltage", "Slew Rate", "Noise", "Lead Count"]) {
      expect(within(dialog).getByText(label)).toBeInTheDocument();
    }
    // Every value says who supplied it. The fixture attributes each fact to DigiKey.
    expect(within(dialog).getAllByText("DigiKey").length).toBe(9);
  });

  it("shows every alternate value beside the value in force, with its source", async () => {
    const { dialog } = await openSpecSheet(
      makeWorkspace({
        specifications: {
          total: 1,
          groups: [
            {
              id: "electrical",
              label: "Electrical",
              count: 1,
              facts: [
                makeFact({
                  id: "Supply Voltage",
                  label: "Supply Voltage",
                  rawValue: "3 V",
                  state: "conflict",
                  alternates: [
                    {
                      rawValue: "3.3 V",
                      formattedValue: "3.3 V",
                      sourceId: "mouser",
                      sourceLabel: "Mouser",
                    },
                  ],
                }),
              ],
            },
          ],
        },
      }),
    );
    const alternate = within(dialog).getByText("3.3 V").closest("li")!;
    expect(within(alternate).getByText("Mouser")).toBeInTheDocument();
    expect(within(dialog).getByText("Sources Disagree")).toBeInTheDocument();
  });

  it("searches by label, value or source", async () => {
    const { user, dialog } = await openSpecSheet(makeWorkspace({ specifications: bigSpecs() }));
    await user.type(within(dialog).getByLabelText("Search specifications"), "slew");
    await waitFor(() => expect(within(dialog).queryByText("Lead Count")).toBeNull());
    expect(within(dialog).getByText("Slew Rate")).toBeInTheDocument();
    expect(within(dialog).queryByText("Physical (4)")).toBeNull();
  });

  it("dissolves the groups when sorted by name, so one ordered list answers the question", () => {
    const specifications = makeWorkspace({ specifications: bigSpecs() }).specifications;
    expect(sheetGroups(specifications, "", "group", "All").map((g) => g.id)).toEqual([
      "electrical",
      "physical",
    ]);
    const byName = sheetGroups(specifications, "", "name", "All");
    expect(byName).toHaveLength(1);
    expect(byName[0].facts.map((fact) => fact.label)).toEqual([
      "Gain",
      "Height",
      "Lead Count",
      "Noise",
      "Package",
      "Pitch",
      "Quiescent Current",
      "Slew Rate",
      "Supply Voltage",
    ]);
    expect(factMatches(byName[0].facts[0], "digikey")).toBe(true);
  });

  it("sorts the sheet through the control, not only through the helper", async () => {
    const { user, dialog } = await openSpecSheet(makeWorkspace({ specifications: bigSpecs() }));
    await user.selectOptions(within(dialog).getByLabelText("Sort specifications"), "name");
    await waitFor(() => expect(within(dialog).queryByText("Electrical (5)")).toBeNull());
    expect(within(dialog).getByText("All Specifications (9)")).toBeInTheDocument();
  });

  it("pins a specification from the sheet and pulls it to the top", async () => {
    const { user, dialog } = await openSpecSheet(makeWorkspace({ specifications: bigSpecs() }));
    const pin = within(dialog).getByRole("button", { name: "Pin Slew Rate" });
    expect(pin).toHaveAttribute("aria-pressed", "false");

    await user.click(pin);

    const pinnedSection = await within(dialog).findByLabelText("Pinned");
    expect(within(pinnedSection).getByText("Slew Rate")).toBeInTheDocument();
    expect(
      within(dialog).getAllByRole("button", { name: "Pinned Slew Rate" })[0],
    ).toHaveAttribute("aria-pressed", "true");
  });

  it("renders the complete pinout table and offers Apply Pinout beside it", async () => {
    const { dialog } = await openSpecSheet(makeWorkspace({ specifications: bigSpecs() }));
    const table = within(dialog).getByRole("table", { name: "Pinout" });
    expect(within(table).getByText("OUT1")).toBeInTheDocument();
    expect(within(table).getByText("IN1-")).toBeInTheDocument();
    // One row per pin, plus the header row.
    expect(within(table).getAllByRole("row")).toHaveLength(3);
    expect(within(dialog).getByRole("button", { name: "Look Up Pinout" })).toBeInTheDocument();
  });

  it("unions the pinout columns so a pin with an extra key is not silently truncated", () => {
    expect(pinoutColumns([{ pin: "1", name: "A" }, { pin: "2", type: "power" }])).toEqual([
      "pin",
      "name",
      "type",
    ]);
  });

  it("persists a looked-up pinout through the specs seam, with its source", async () => {
    mockApi.enrichPart.mockResolvedValue({ job_id: "e1" });
    mockApi.openJobStream.mockResolvedValue(
      streamOf([
        `event: result\ndata: ${JSON.stringify({
          result: {
            category: "ICs",
            specs: {
              pinout: {
                value: [{ pin: "1", name: "OUT1" }],
                source: "datasheet",
                confidence: "high",
              },
            },
            price_breaks: [],
            schema_version: 2,
          },
        })}\n\n`,
        "event: done\ndata: {}\n\n",
      ]),
    );
    mockApi.setSpecs.mockResolvedValue({} as never);
    const { user, dialog } = await openSpecSheet(makeWorkspace({ specifications: bigSpecs() }));

    await user.click(within(dialog).getByRole("button", { name: "Look Up Pinout" }));
    const apply = await within(dialog).findByRole("button", { name: "Apply Pinout" });
    await user.click(apply);

    await waitFor(() =>
      expect(mockApi.setSpecs).toHaveBeenCalledWith(
        ID,
        {
          pinout: {
            value: [{ pin: "1", name: "OUT1" }],
            source: "datasheet",
            confidence: "high",
          },
        },
        undefined,
      ),
    );
  });
});

// --------------------------------------------------------------- sourcing

describe("the full sourcing sheet", () => {
  const workspace = makeWorkspace({
    sourcing: {
      offers: [
        makeOffer({
          sourceId: "mouser",
          sourceLabel: "Mouser",
          partNumber: "511-LM358",
          stock: 1240,
          currency: "USD",
          priceBreaks: [
            { qty: 1, price: 0.42 },
            { qty: 10, price: 0.31 },
            { qty: 100, price: 0.22 },
          ],
        }),
      ],
      shared: [makeFact({ id: "lifecycle", label: "Lifecycle", rawValue: "Active" })],
      relationships: [
        {
          id: "substitutions",
          label: "Potential Substitutions",
          count: 1,
          items: [
            {
              mpn: "LM2904DR",
              manufacturer: "TI",
              description: "Dual op-amp",
              url: "https://example.invalid/sub",
              sourceId: "digikey",
              sourceLabel: "DigiKey",
            },
          ],
        },
      ],
      resources: [
        {
          title: "3D Model",
          url: "https://example.invalid/model",
          sourceId: "digikey",
          sourceLabel: "DigiKey",
        },
      ],
    },
    sources: {
      records: [
        makeSourceRecord({ id: "mouser", label: "Mouser", state: "success", fieldCount: 3 }),
        makeSourceRecord({ id: "digikey", label: "DigiKey", state: "failed", fieldCount: 0 }),
        makeSourceRecord({ id: "lcsc", label: "LCSC", state: "not_configured", fieldCount: 0 }),
        makeSourceRecord({ id: "arrow", label: "Arrow", state: "unavailable", fieldCount: 0 }),
      ],
    },
  });

  it("lists every price break for every offer, with stock, currency and fetch time", async () => {
    await openSheet(workspace, "Sourcing", "View Full Sourcing");
    const dialog = await screen.findByRole("dialog", { name: "Sourcing" });
    const offer = within(dialog).getByLabelText("Mouser 511-LM358");
    expect(within(offer).getByText("511-LM358")).toBeInTheDocument();
    expect(within(offer).getByText("1,240")).toBeInTheDocument();
    expect(within(offer).getByText("USD")).toBeInTheDocument();
    expect(within(offer).getByText("2026-08-01T00:00:00Z")).toBeInTheDocument();
    const ladder = within(offer).getByRole("table", { name: "Price breaks Mouser" });
    // Three quoted breaks plus the header row: the ladder is complete, not a "from" price.
    expect(within(ladder).getAllByRole("row")).toHaveLength(4);
    expect(within(ladder).getByText("USD0.2200")).toBeInTheDocument();
  });

  it("labels distributor relationships as unvalidated suggestions, in prose", async () => {
    await openSheet(workspace, "Sourcing", "View Full Sourcing");
    const dialog = await screen.findByRole("dialog", { name: "Sourcing" });
    const related = within(dialog).getByLabelText("Related Parts");
    expect(
      within(related).getByText(/Stockroom has not checked that any of them is electrically/),
    ).toBeInTheDocument();
    expect(within(related).getByText("Potential Substitutions (1)")).toBeInTheDocument();
    expect(within(related).getByText("LM2904DR")).toBeInTheDocument();
  });

  it("distinguishes a source that failed from one that does not carry the part", async () => {
    await openSheet(workspace, "Sourcing", "View Full Sourcing");
    const dialog = await screen.findByRole("dialog", { name: "Sourcing" });
    const states = within(dialog).getByLabelText("Sources");
    expect(within(within(states).getByText("Mouser").closest("li")!).getByText("Answered"))
      .toBeInTheDocument();
    expect(within(within(states).getByText("DigiKey").closest("li")!).getByText("Failed"))
      .toBeInTheDocument();
    expect(
      within(within(states).getByText("LCSC").closest("li")!).getByText("Not Configured"),
    ).toBeInTheDocument();
    expect(
      within(within(states).getByText("Arrow").closest("li")!).getByText("Not Carried"),
    ).toBeInTheDocument();
  });

  it("carries the shared trade facts and the provider documents", async () => {
    await openSheet(workspace, "Sourcing", "View Full Sourcing");
    const dialog = await screen.findByRole("dialog", { name: "Sourcing" });
    expect(within(within(dialog).getByLabelText("Trade And Compliance")).getByText("Lifecycle"))
      .toBeInTheDocument();
    expect(within(within(dialog).getByLabelText("Documents")).getByText("3D Model"))
      .toBeInTheDocument();
  });

  it("surfaces the per-source outcome on the compact tab too", async () => {
    await open(workspace);
    const user = userEvent.setup();
    const strip = document.querySelector<HTMLElement>('[data-dev-id="component-browser.info.tabs"]')!;
    await user.click(within(strip).getByRole("tab", { name: "Sources & History" }));
    const region = await screen.findByLabelText("Source Records");
    expect(within(region).getByText("Failed")).toBeInTheDocument();
    expect(within(region).getByText("Not Configured")).toBeInTheDocument();
    expect(within(region).getByText("3 attributed")).toBeInTheDocument();
  });
});

// --------------------------------------------------------------- sources & history

const sourcesWorkspace = makeWorkspace({
  sources: {
    fields: [
      makeFact({
        id: "manufacturer",
        label: "Manufacturer",
        rawValue: "Texas Instruments",
        state: "conflict",
        alternates: [
          {
            rawValue: "TI",
            formattedValue: "TI",
            sourceId: "mouser",
            sourceLabel: "Mouser",
          },
        ],
      }),
      makeFact({
        id: "Supply Voltage",
        label: "Supply Voltage",
        rawValue: "3 V",
        alternates: [
          { rawValue: "3.3 V", formattedValue: "3.3 V", sourceId: "mouser", sourceLabel: "Mouser" },
        ],
      }),
    ],
    records: [makeSourceRecord({ id: "mouser", label: "Mouser", state: "failed", fieldCount: 1 })],
  },
});

describe("the sources and history sheet", () => {
  it("opens on Field Sources and offers the four questions it answers", async () => {
    await openSheet(sourcesWorkspace, "Sources & History", "View All");
    const dialog = await screen.findByRole("dialog", { name: "Sources & History" });
    expect(within(dialog).getAllByRole("tab").map((tab) => tab.textContent)).toEqual([
      "Field Sources",
      "Source Records",
      "Changes",
      "Diagnostics",
    ]);
    expect(within(dialog).getByText("Texas Instruments")).toBeInTheDocument();
    expect(within(dialog).getByText("conflict")).toBeInTheDocument();
  });

  it("applies an alternate onto a canonical field and refuses one it cannot write", async () => {
    mockApi.editField.mockResolvedValue({} as never);
    const { user } = await openSheet(sourcesWorkspace, "Sources & History", "View All");
    const dialog = await screen.findByRole("dialog", { name: "Sources & History" });

    // A record attribute can be put in force...
    await user.click(within(dialog).getByRole("button", { name: "Apply TI Manufacturer" }));
    await waitFor(() =>
      expect(mockApi.editField).toHaveBeenCalledWith(ID, "manufacturer", "TI"),
    );
    // ...a SPEC key cannot: `editField` writes record attributes, so no Apply is offered.
    expect(within(dialog).queryByRole("button", { name: /Apply 3\.3 V/ })).toBeNull();
  });

  it("knows which alternates are safe to apply", () => {
    const alternate = { rawValue: "TI", formattedValue: "TI", sourceId: "m", sourceLabel: "M" };
    expect(canApplyAlternate("manufacturer", alternate)).toBe(true);
    expect(canApplyAlternate("Supply Voltage", alternate)).toBe(false);
    expect(canApplyAlternate("mpn", { ...alternate, rawValue: { a: 1 } })).toBe(false);
  });

  it("lists the captured source records with their outcome and a refresh action", async () => {
    const { user } = await openSheet(sourcesWorkspace, "Sources & History", "View All");
    const dialog = await screen.findByRole("dialog", { name: "Sources & History" });
    await user.click(within(dialog).getByRole("tab", { name: "Source Records" }));

    const row = document.querySelector<HTMLElement>(
      '[data-dev-id="component-browser.source-record-row"]',
    )!;
    expect(within(row).getByText("Mouser")).toBeInTheDocument();
    expect(within(row).getByText("Failed")).toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: "Refresh Sourcing" })).toBeInTheDocument();
    // Enrichment keeps its home here rather than being rewritten.
    expect(
      within(dialog).getByRole("button", { name: "Enrich From Distributor" }),
    ).toBeInTheDocument();
  });

  it("reads the timeline from the existing history and diff endpoints", async () => {
    mockApi.partHistory.mockResolvedValue({
      commits: [
        {
          sha: "a".repeat(40),
          subject: "Edit lm358: manufacturer",
          author: "owner",
          iso_date: "2026-08-01T10:00:00Z",
        },
        {
          sha: "b".repeat(40),
          subject: "Add lm358",
          author: "owner",
          iso_date: "2026-07-01T10:00:00Z",
        },
      ],
      count: 2,
    });
    mockApi.partDiff.mockResolvedValue({
      a: "b".repeat(40),
      b: "a".repeat(40),
      fields: [
        { key: "manufacturer", before: "TI", after: "Texas Instruments", status: "changed" },
      ],
      assets: { symbol: false, footprint: false, model: false, datasheet: false },
    });
    const { user } = await openSheet(sourcesWorkspace, "Sources & History", "View All");
    const dialog = await screen.findByRole("dialog", { name: "Sources & History" });
    await user.click(within(dialog).getByRole("tab", { name: "Changes" }));

    expect(await within(dialog).findByText("Edit lm358: manufacturer")).toBeInTheDocument();
    await user.click(within(dialog).getByText("Edit lm358: manufacturer"));

    await waitFor(() =>
      expect(mockApi.partDiff).toHaveBeenCalledWith(ID, "b".repeat(40), "a".repeat(40)),
    );
    expect(await within(dialog).findByText("TI -> Texas Instruments")).toBeInTheDocument();
  });

  it("keeps diagnostics collapsed until they are asked for, and the raw record until then", async () => {
    mockApi.partDetail.mockResolvedValue({ id: ID, mpn: "LM358DR" } as never);
    const { user } = await openSheet(sourcesWorkspace, "Sources & History", "View All");
    const dialog = await screen.findByRole("dialog", { name: "Sources & History" });
    await user.click(within(dialog).getByRole("tab", { name: "Diagnostics" }));

    const toggle = within(dialog).getByRole("button", { name: "Show Diagnostics" });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(within(dialog).queryByText("rules@1")).toBeNull();

    await user.click(toggle);
    expect(within(dialog).getByText("rules@1")).toBeInTheDocument();
    // The canonical record is a SECOND disclosure: it is a network read, so it is not fetched
    // just because somebody opened diagnostics.
    expect(mockApi.partDetail).not.toHaveBeenCalled();

    await user.click(within(dialog).getByRole("button", { name: "Show Canonical Record" }));
    await waitFor(() => expect(mockApi.partDetail).toHaveBeenCalledWith(ID));
  });
});

// --------------------------------------------------------------- restored capabilities

describe("identity editing, restored", () => {
  it("edits a canonical identity field from the header", async () => {
    mockApi.editField.mockResolvedValue({} as never);
    await open();
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: "Edit Identity" }));
    const dialog = await screen.findByRole("dialog", { name: "Edit Identity" });
    await user.click(within(dialog).getByRole("button", { name: "Edit Manufacturer" }));
    const input = within(dialog).getByRole("textbox", { name: "Manufacturer" });
    await user.clear(input);
    await user.type(input, "TI{Enter}");

    await waitFor(() => expect(mockApi.editField).toHaveBeenCalledWith(ID, "manufacturer", "TI"));
  });

  it("moves the component to another category through the move seam, not a field edit", async () => {
    mockApi.moveCategory.mockResolvedValue({} as never);
    await open();
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: "Edit Identity" }));
    const dialog = await screen.findByRole("dialog", { name: "Edit Identity" });
    await user.selectOptions(within(dialog).getByLabelText("Category"), "Passives");

    await waitFor(() => expect(mockApi.moveCategory).toHaveBeenCalledWith(ID, "Passives"));
    expect(mockApi.editField).not.toHaveBeenCalled();
  });

  it("opens identity editing from the attention item that names the missing field", async () => {
    await open(
      makeWorkspace({
        attention: [
          {
            id: "identity.manufacturer",
            severity: "blocking",
            title: "Manufacturer Is Missing",
            detail: "This component cannot be completed without it.",
            action: "edit-identity",
          },
        ],
      }),
    );
    const user = userEvent.setup();
    await user.click(
      screen.getByRole("button", { name: "Manufacturer Is Missing: edit-identity" }),
    );
    expect(await screen.findByRole("dialog", { name: "Edit Identity" })).toBeInTheDocument();
  });
});

// --------------------------------------------------------------- the surface contract

// The opened component's own source, as raw strings. Same technique as devIds.parity.test.ts:
// no node:fs, which breaks `tsc -b` and is environment-fragile.
const WORKSPACE_SOURCE = Object.entries(
  import.meta.glob("/src/components/component-workspace/*.tsx", {
    query: "?raw",
    eager: true,
    import: "default",
  }) as Record<string, string>,
).filter(([path]) => !/\.test\.tsx$/.test(path));

/** Source with its comments removed: a rule about CODE must not convict its own documentation. */
function withoutComments(text: string): string {
  return text.replace(/\/\*[\s\S]*?\*\//g, "").replace(/(^|\s)\/\/.*$/gm, "");
}

describe("the opened component is provider-neutral", () => {
  it("names no distributor and reads no provider payload key", () => {
    // The projection turned provider payloads into offers, resources and relationships precisely
    // so no presentation component has to know which vendor filled them in. A vendor name or a
    // `catalog.<vendor>` read here is the leak coming back, and a fifth distributor would then
    // need an edit in this directory rather than none.
    const offenders: string[] = [];
    for (const [path, raw] of WORKSPACE_SOURCE) {
      const text = withoutComments(raw);
      for (const needle of ["digikey", "digi-key", "mouser", "lcsc", "snapeda", "ultralibrarian"]) {
        if (text.toLowerCase().includes(needle)) offenders.push(`${path}: ${needle}`);
      }
      // `\b` matters: `category_catalog` is the facet field, not a provider payload read.
      if (/\bcatalog\s*[?.[]/.test(text)) offenders.push(`${path}: catalog`);
    }
    expect(offenders).toEqual([]);
    expect(WORKSPACE_SOURCE.length).toBeGreaterThan(10);
  });
});

describe("the workspace surface contract", () => {
  it("gives only the modal a scrollbar: the workspace root and its regions never scroll", async () => {
    await open(makeWorkspace({ specifications: bigSpecs() }));
    const root = document.querySelector<HTMLElement>('[data-dev-id="component-browser.root"]')!;
    expect(root.className).toContain("h-full");
    expect(root.className).toContain("min-h-0");
    expect(root.className).toContain("overflow-hidden");
    for (const region of document.querySelectorAll<HTMLElement>(
      '[data-dev-id="component-browser.specifications"], [data-dev-id="component-browser.pinout"]',
    )) {
      expect(region.className).toContain("overflow-hidden");
      expect(region.className).not.toContain("overflow-y-auto");
    }
  });

  it("traps focus, closes on Escape, and hands focus back to the control that opened it", async () => {
    const { user, trigger } = await openSheet(
      makeWorkspace({ specifications: bigSpecs() }),
      "Specifications",
      "View All Specifications",
    );
    const dialog = await screen.findByRole("dialog", { name: "Specifications" });
    expect(dialog).toHaveAttribute("aria-modal", "true");
    await waitFor(() => expect(document.activeElement).toBe(dialog));

    // Tab from the last focusable element wraps back into the dialog rather than escaping it.
    const focusable = dialog.querySelectorAll<HTMLElement>(
      'button:not([disabled]), [href], input:not([disabled]), [tabindex]:not([tabindex="-1"])',
    );
    focusable[focusable.length - 1].focus();
    await user.keyboard("{Tab}");
    expect(dialog.contains(document.activeElement)).toBe(true);

    await user.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(document.activeElement).toBe(trigger);
  });
});
