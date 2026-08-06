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
import type { ComponentDossier } from "../../api/dossierTypes";
import { DevModeProvider } from "../../lib/devMode";
import { ThemeProvider } from "../../lib/theme";
import { ToastProvider } from "../../lib/toast";
import {
  defaultUiSession,
  openComponentInSession,
  resetUiSessionForTests,
} from "../../lib/uiSession";
import {
  makeCandidate,
  makeDocument,
  makeDossier,
  makeOffer,
  makeRelatedPart,
  makeSourceLedgerEntry,
  makeSpecification,
} from "../../test/dossierFixture";
import { makePartDetail } from "../../test/partFixture";
import { ComponentWorkspace } from "./ComponentWorkspace";
import { canApplyAlternate } from "./sourceCandidates";
import { pinoutColumns } from "./pinoutRows";

vi.mock("../../api/client", async (importActual) => {
  const actual = await importActual<typeof import("../../api/client")>();
  return {
    ...actual,
    api: {
      partDossier: vi.fn(),
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
        <DevModeProvider>
          <ToastProvider>{ui}</ToastProvider>
        </DevModeProvider>
      </ThemeProvider>
    </QueryClientProvider>,
  );
}

/**
 * Turn developer mode on the way a person does: Ctrl+Shift+D, which is the only way in.
 *
 * It matters that this is the real path. Technical diagnostics are gated on the same flag the
 * design panel is, and a test that reached past the gate would prove the panel renders rather
 * than that the gate holds.
 */
async function enableDeveloperMode(user: ReturnType<typeof userEvent.setup>) {
  await user.keyboard("{Control>}{Shift>}D{/Shift}{/Control}");
}

async function open(dossier: ComponentDossier = makeDossier()) {
  resetUiSessionForTests(openComponentInSession(defaultUiSession(), ID));
  mockApi.partDossier.mockResolvedValue(dossier);
  const view = provide(<ComponentWorkspace componentId={ID} />);
  await screen.findByText(dossier.identity.mpn);
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
  const row = (label: string) =>
    makeSpecification({ key: label, label, displayValue: `${label} value`, unit: "" });
  return makeDossier({
    specificationGroups: [
      {
        id: "electrical",
        label: "Electrical",
        count: electrical.length,
        specifications: electrical.map(row),
      },
      {
        id: "package_mechanical",
        label: "Package and Mechanical",
        count: physical.length,
        specifications: physical.map(row),
      },
    ],
    diagnostics: {
      pinCount: 2,
      pinout: [
        { pin: "1", name: "OUT1", type: "output" },
        { pin: "2", name: "IN1-", type: "input" },
      ],
    },
  });
}

/**
 * Open a secondary surface by pressing the control that leads to it.
 *
 * Every one of these now hangs off a COLUMN or off the Manage menu rather than off an information
 * tab, because there are no information tabs: the columns are all on screen at once, so a sheet is
 * reached from the section it belongs to.
 */
async function openSheet(dossier: ComponentDossier, control: string, dialogName: string) {
  await open(dossier);
  const user = userEvent.setup();
  const trigger = await screen.findByRole("button", { name: control });
  await user.click(trigger);
  const dialog = await screen.findByRole("dialog", { name: dialogName });
  return { user, trigger, dialog };
}

/** Open the Manage menu and run one of its items. */
async function manage(item: string) {
  const user = userEvent.setup();
  await user.click(screen.getByRole("button", { name: "Manage" }));
  await user.click(await screen.findByRole("menuitem", { name: item }));
  return user;
}

// --------------------------------------------------------------- compact vs sheet

describe("the pinout sheet", () => {
  it("renders the complete pinout table and offers Commit Pinout beside it", async () => {
    const { dialog } = await openSheet(
      bigSpecs(),
      "View Pinout",
      "Pinout",
    );
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

  /**
   * A filtered row keeps the row it already had, instead of inheriting another pin's.
   *
   * The filter is the whole reason this table exists on a hundred-pin package, and it is also the
   * one thing that makes a row's POSITION meaningless: narrow the search and the pin that was
   * seventh is suddenly first. A row identified by where it currently sits therefore names a
   * different pin on every keystroke, and the element that was drawn for one pin gets repainted
   * with another's - which is how a row a person had selected, scrolled to or was reading ends up
   * being a different pin than the one they were looking at.
   *
   * Identity here is the pin's ORDINAL IN THE RECORD, which the filter cannot move. Proved on the
   * DOM node rather than on a key, because the node is what a person's selection and the browser's
   * scroll position are attached to.
   */
  it("keeps a pin on its own row when the filter narrows around it", async () => {
    const { dialog, user } = await openSheet(
      makeDossier({
        diagnostics: {
          pinCount: 4,
          pinout: [
            { pin: "1", name: "VCC" },
            { pin: "2", name: "GND" },
            { pin: "3", name: "SDA" },
            { pin: "4", name: "SCL" },
          ],
        },
      }),
      "View Pinout",
      "Pinout",
    );
    const table = within(dialog).getByRole("table", { name: "Pinout" });
    const before = within(table).getByText("SDA").closest("tr");
    expect(before).not.toBeNull();

    await user.type(within(dialog).getByRole("searchbox", { name: "Filter pins" }), "SDA");
    await waitFor(() => expect(within(table).getAllByRole("row")).toHaveLength(2));

    expect(within(table).getByText("SDA").closest("tr")).toBe(before);
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
    const { user, dialog } = await openSheet(
      bigSpecs(),
      "View Pinout",
      "Pinout",
    );

    await user.click(within(dialog).getByRole("button", { name: "Look Up Pinout" }));
    const apply = await within(dialog).findByRole("button", { name: "Commit Pinout" });
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
  const dossier = makeDossier({
    distributorOffers: [
      makeOffer({
        provider: "mouser",
        providerLabel: "Mouser",
        sku: "511-LM358",
        stock: 1240,
        currency: "USD",
        unitPrice: 0.42,
        moq: 1,
        priceBreaks: [
          { qty: 1, price: 0.42 },
          { qty: 10, price: 0.31 },
          { qty: 100, price: 0.22 },
        ],
      }),
    ],
    supplySummary: { offerCount: 1, totalStock: 1240, lifecycle: "Active" },
    relatedParts: [
      makeRelatedPart({
        mpn: "LM2904DR",
        manufacturer: "TI",
        description: "Dual op-amp",
        url: "https://example.invalid/sub",
      }),
    ],
    documents: {
      items: [
        makeDocument({
          documentType: "other",
          documentTypeLabel: "Reference",
          title: "3D Model",
          localPath: "",
          remoteUrl: "https://example.invalid/model",
          sourceLabel: "DigiKey",
        }),
      ],
      count: 1,
      hasDatasheet: false,
    },
    provenance: {
      sources: [
        makeSourceLedgerEntry({ id: "mouser", label: "Mouser", state: "success", fieldCount: 3 }),
        makeSourceLedgerEntry({ id: "digikey", label: "DigiKey", state: "failed", fieldCount: 0 }),
        makeSourceLedgerEntry({
          id: "lcsc",
          label: "LCSC",
          state: "not_configured",
          fieldCount: 0,
        }),
        makeSourceLedgerEntry({
          id: "arrow",
          label: "Arrow",
          state: "unavailable",
          fieldCount: 0,
        }),
      ],
    },
  });

  it("lists every price break for every offer, with stock, currency and fetch time", async () => {
    const { dialog } = await openSheet(dossier, "View Price Breaks", "Price Breaks");
    const offer = within(dialog).getByLabelText("Mouser 511-LM358");
    expect(within(offer).getByText("511-LM358")).toBeInTheDocument();
    expect(within(offer).getByText("1,240")).toBeInTheDocument();
    expect(within(offer).getByText("MOQ 1")).toBeInTheDocument();
    const ladder = within(offer).getByRole("table", { name: "Price breaks Mouser" });
    // Three quoted breaks plus the header row: the ladder is complete, not a "from" price.
    expect(within(ladder).getAllByRole("row")).toHaveLength(4);
    expect(within(ladder).getByText("USD0.22")).toBeInTheDocument();
  });

  it("labels distributor relationships as unvalidated suggestions, in prose", async () => {
    const { dialog } = await openSheet(dossier, "View Price Breaks", "Price Breaks");
    const related = within(dialog).getByLabelText("Related Parts");
    expect(
      within(related).getByText(/Stockroom has not checked whether these parts are interchangeable/),
    ).toBeInTheDocument();
    // And on the ROW itself, with the reason it is here at all.
    expect(within(related).getByText(/Offered as a substitution/)).toBeInTheDocument();
    expect(within(related).getByText("LM2904DR")).toBeInTheDocument();
  });

  it("distinguishes a source that failed from one that does not carry the part", async () => {
    const { dialog } = await openSheet(dossier, "View Price Breaks", "Price Breaks");
    const states = within(dialog).getByLabelText("Sources");
    expect(within(within(states).getByText("Mouser").closest("li")!).getByText("Supplied"))
      .toBeInTheDocument();
    expect(within(within(states).getByText("DigiKey").closest("li")!).getByText("Failed"))
      .toBeInTheDocument();
    expect(
      within(within(states).getByText("LCSC").closest("li")!).getByText("Not Connected"),
    ).toBeInTheDocument();
    expect(
      within(within(states).getByText("Arrow").closest("li")!).getByText("Not Carried"),
    ).toBeInTheDocument();
  });

  it("carries the typed documents, each labelled with what kind of document it is", async () => {
    const { dialog } = await openSheet(dossier, "View Price Breaks", "Price Breaks");
    const documents = within(dialog).getByLabelText("Documents");
    expect(within(documents).getByText("3D Model")).toBeInTheDocument();
    expect(within(documents).getByText("Reference")).toBeInTheDocument();
  });

  it("gives the sourcing column a Source, Fields Used, Retrieved and State table", async () => {
    await open(dossier);
    const table = screen.getByRole("table", { name: "Data sources" });
    expect(
      within(table)
        .getAllByRole("columnheader")
        .map((cell) => cell.textContent),
    ).toEqual(["Source", "Fields Used", "Retrieved", "State"]);
    const mouser = within(table).getByText("Mouser").closest("tr")!;
    expect(within(mouser).getByText("3")).toBeInTheDocument();
    expect(within(mouser).getByText("Supplied")).toBeInTheDocument();
    // The three degraded outcomes stay apart: a broken fetch, a distributor that does not
    // carry the part, and a machine that was never given credentials.
    expect(
      within(within(table).getByText("DigiKey").closest("tr")!).getByText("Failed"),
    ).toBeInTheDocument();
    expect(
      within(within(table).getByText("LCSC").closest("tr")!).getByText("Not Connected"),
    ).toBeInTheDocument();
    expect(
      within(within(table).getByText("Arrow").closest("tr")!).getByText("Not Carried"),
    ).toBeInTheDocument();
  });
});

// --------------------------------------------------------------- sources & history

const sourcesDossier = makeDossier({
  provenance: {
    recordFields: [
      {
        key: "manufacturer",
        label: "Manufacturer",
        preferredValue: "Texas Instruments",
        displayValue: "Texas Instruments",
        sourceCandidates: [
          makeCandidate({ value: "Texas Instruments", displayValue: "Texas Instruments" }),
          makeCandidate({
            sourceId: "mouser",
            sourceLabel: "Mouser",
            value: "TI",
            displayValue: "TI",
          }),
        ],
        preferredSource: makeCandidate({
          value: "Texas Instruments",
          displayValue: "Texas Instruments",
        }),
        conflictState: "conflicting",
        verificationState: "conflicting",
        mapped: false,
      },
      {
        key: "Supply Voltage",
        label: "Supply Voltage",
        preferredValue: "3 V",
        displayValue: "3 V",
        sourceCandidates: [
          makeCandidate({ value: "3 V", displayValue: "3 V" }),
          makeCandidate({
            sourceId: "mouser",
            sourceLabel: "Mouser",
            value: "3.3 V",
            displayValue: "3.3 V",
          }),
        ],
        preferredSource: makeCandidate({ value: "3 V", displayValue: "3 V" }),
        conflictState: "conflicting",
        verificationState: "conflicting",
        mapped: false,
      },
    ],
    sources: [
      makeSourceLedgerEntry({ id: "mouser", label: "Mouser", state: "failed", fieldCount: 1 }),
    ],
  },
});

describe("the sources and history sheet", () => {
  it("opens on Field Sources and offers the four questions it answers", async () => {
    const { dialog } = await openSheet(
      sourcesDossier,
      "View Data Provenance",
      "Data Provenance",
    );
    expect(within(dialog).getAllByRole("tab").map((tab) => tab.textContent)).toEqual([
      "Field Sources",
      "Source Records",
      "Changes",
      "Technical Diagnostics",
    ]);
    expect(within(dialog).getByText("Texas Instruments")).toBeInTheDocument();
    // The quality vocabulary, not the storage token: `conflicting` is what the record calls it.
    expect(within(dialog).queryAllByText("conflicting")).toEqual([]);
    expect(within(dialog).getAllByText("Conflicting").length).toBeGreaterThan(0);
  });

  it("applies an alternate onto a canonical field and refuses one it cannot write", async () => {
    mockApi.editField.mockResolvedValue({} as never);
    const { user, dialog } = await openSheet(
      sourcesDossier,
      "View Data Provenance",
      "Data Provenance",
    );

    // A record attribute can be put in force...
    await user.click(within(dialog).getByRole("button", { name: "Commit TI Manufacturer" }));
    await waitFor(() =>
      expect(mockApi.editField).toHaveBeenCalledWith(ID, "manufacturer", "TI"),
    );
    // ...a SPEC key cannot: `editField` writes record attributes, so no Commit is offered.
    expect(within(dialog).queryByRole("button", { name: /Commit 3\.3 V/ })).toBeNull();
  });

  it("knows which alternates are safe to apply", () => {
    const alternate = makeCandidate({ value: "TI", displayValue: "TI" });
    expect(canApplyAlternate("manufacturer", alternate)).toBe(true);
    expect(canApplyAlternate("Supply Voltage", alternate)).toBe(false);
    expect(canApplyAlternate("mpn", { ...alternate, value: { a: 1 } })).toBe(false);
  });

  it("lists the captured source records with their outcome and a refresh action", async () => {
    const { user, dialog } = await openSheet(
      sourcesDossier,
      "View Data Provenance",
      "Data Provenance",
    );
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
    const { user, dialog } = await openSheet(
      sourcesDossier,
      "View Data Provenance",
      "Data Provenance",
    );
    await user.click(within(dialog).getByRole("tab", { name: "Changes" }));

    expect(await within(dialog).findByText("Edit lm358: manufacturer")).toBeInTheDocument();
    await user.click(within(dialog).getByText("Edit lm358: manufacturer"));

    await waitFor(() =>
      expect(mockApi.partDiff).toHaveBeenCalledWith(ID, "b".repeat(40), "a".repeat(40)),
    );
    expect(await within(dialog).findByText("TI -> Texas Instruments")).toBeInTheDocument();
  });

  it("offers the visual diff only for a commit that actually moved a drawing", async () => {
    mockApi.partHistory.mockResolvedValue({
      commits: [
        {
          sha: "a".repeat(40),
          subject: "Edit lm358: manufacturer",
          author: "owner",
          iso_date: "2026-08-01T10:00:00Z",
        },
      ],
      count: 1,
    });
    // A text-only commit. "symbol_content_hash changed" is a true field row and tells a person
    // nothing about geometry, but there is no geometry here to look at, so no overlay is offered.
    mockApi.partDiff.mockResolvedValue({
      a: "",
      b: "a".repeat(40),
      fields: [
        { key: "manufacturer", before: "TI", after: "Texas Instruments", status: "changed" },
      ],
      assets: { symbol: false, footprint: false, model: false, datasheet: false },
    });
    const { user, dialog } = await openSheet(
      sourcesDossier,
      "View Data Provenance",
      "Data Provenance",
    );
    await user.click(within(dialog).getByRole("tab", { name: "Changes" }));
    await user.click(await within(dialog).findByText("Edit lm358: manufacturer"));

    expect(await within(dialog).findByText("TI -> Texas Instruments")).toBeInTheDocument();
    expect(within(dialog).queryByRole("button", { name: "Visual Diff" })).toBeNull();
  });

  it("opens the visual diff NESTED in the sheet, and closes it without closing the sheet", async () => {
    // The deferred overlay, finally reachable. It could not be built while this sheet and the diff
    // window shared a z-index and a window-level Escape listener; the modal stack settles both.
    mockApi.partHistory.mockResolvedValue({
      commits: [
        {
          sha: "a".repeat(40),
          subject: "Redraw lm358 symbol",
          author: "owner",
          iso_date: "2026-08-01T10:00:00Z",
        },
      ],
      count: 1,
    });
    mockApi.partDiff.mockResolvedValue({
      a: "",
      b: "a".repeat(40),
      fields: [{ key: "symbol_content_hash", before: "aaa", after: "bbb", status: "changed" }],
      assets: { symbol: true, footprint: false, model: false, datasheet: false },
    });
    const { user, dialog: sheet } = await openSheet(
      sourcesDossier,
      "View Data Provenance",
      "Data Provenance",
    );
    await user.click(within(sheet).getByRole("tab", { name: "Changes" }));
    await user.click(await within(sheet).findByText("Redraw lm358 symbol"));

    const trigger = await within(sheet).findByRole("button", { name: "Visual Diff" });
    await user.click(trigger);

    const overlay = await screen.findByRole("dialog", {
      name: `Visual Diff for ${sourcesDossier.identity.mpn}`,
    });
    // Both windows are open at once, and the overlay paints above the sheet it came from.
    expect(sheet).toBeInTheDocument();
    expect(Number((overlay.parentElement as HTMLElement).style.zIndex)).toBeGreaterThan(
      Number((sheet.parentElement as HTMLElement).style.zIndex),
    );

    await user.keyboard("{Escape}");
    await waitFor(() =>
      expect(
        screen.queryByRole("dialog", {
          name: `Visual Diff for ${sourcesDossier.identity.mpn}`,
        }),
      ).toBeNull(),
    );
    // The sheet survives, and focus is back on the control inside it that opened the overlay.
    expect(screen.getByRole("dialog", { name: "Data Provenance" })).toBeInTheDocument();
    expect(document.activeElement).toBe(trigger);
  });

  it("keeps the schema version and the storage keys off the normal path entirely", async () => {
    const { user, dialog } = await openSheet(
      sourcesDossier,
      "View Data Provenance",
      "Data Provenance",
    );
    await user.click(within(dialog).getByRole("tab", { name: "Technical Diagnostics" }));

    // Not collapsed - absent. A derivation identifier is machine text, and a person who is not
    // debugging Stockroom has no use for it however few clicks away it is.
    expect(within(dialog).queryByRole("button", { name: "Show Diagnostics" })).toBeNull();
    expect(within(dialog).queryByText("rules@1")).toBeNull();
    expect(within(dialog).getByText(/Turn on developer mode/)).toBeInTheDocument();
  });

  it("gives developer mode the schema, the derivation and the canonical record", async () => {
    mockApi.partDetail.mockResolvedValue({ id: ID, mpn: "LM358DR" } as never);
    const { user, dialog } = await openSheet(
      sourcesDossier,
      "View Data Provenance",
      "Data Provenance",
    );
    await user.click(within(dialog).getByRole("tab", { name: "Technical Diagnostics" }));
    await enableDeveloperMode(user);

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
  // The identity sheet's handoff half renders the CANONICAL RECORD (the EDA registry names record
  // attributes), so these tests have to supply one. It is fetched only while the sheet is open.
  beforeEach(() => {
    mockApi.partDetail.mockResolvedValue(
      makePartDetail({
        id: ID,
        mpn: "LM358DR",
        manufacturer: "Texas Instruments",
        derived: { display_name: "LM358DR", category: "ICs", description: "Dual op-amp" },
      }) as never,
    );
  });

  it("edits a canonical identity field from the Manage menu", async () => {
    mockApi.editField.mockResolvedValue({} as never);
    await open();
    const user = await manage("Edit Identification...");
    const dialog = await screen.findByRole("dialog", { name: "Edit Identification" });
    await user.click(within(dialog).getByRole("button", { name: "Edit Manufacturer" }));
    const input = within(dialog).getByRole("textbox", { name: "Manufacturer" });
    await user.clear(input);
    await user.type(input, "TI{Enter}");

    await waitFor(() => expect(mockApi.editField).toHaveBeenCalledWith(ID, "manufacturer", "TI"));
  });

  it("moves the component to another category through the move seam, not a field edit", async () => {
    mockApi.moveCategory.mockResolvedValue({} as never);
    await open();
    const user = await manage("Edit Class and Classification...");
    const dialog = await screen.findByRole("dialog", {
      name: "Edit Class and Classification",
    });
    await user.selectOptions(within(dialog).getByLabelText("Category"), "Passives");

    await waitFor(() => expect(mockApi.moveCategory).toHaveBeenCalledWith(ID, "Passives"));
    expect(mockApi.editField).not.toHaveBeenCalled();
  });

  it("renders the EDA handoff band from the registry, so its fields have exactly one editor", async () => {
    // The orphan decision, made visible. `HandoffBand` lost its only importer when DetailPanel was
    // deleted while this sheet hand-wrote mpn/manufacturer/description a second time. The band is
    // the one that survived: it is generated from the EDA registry, so a third tool joins by
    // declaring `data_fields`, and it carries the symbol and footprint references and the datasheet
    // that the hand-written list had no way to show.
    await open();
    await manage("Edit Identification...");
    const dialog = await screen.findByRole("dialog", { name: "Edit Identification" });

    const band = await within(dialog).findByRole("region", { name: "EDA Handoff" });
    // The two fields the registry does NOT own stay in the sheet's own Identity section...
    expect(within(dialog).getByRole("button", { name: "Edit Listed Name" })).toBeInTheDocument();
    // ...and the registry-owned ones appear once, in the band.
    expect(within(band).getByText("Symbol")).toBeInTheDocument();
    expect(within(band).getByText("Footprint")).toBeInTheDocument();
    expect(within(dialog).getAllByText("Manufacturer")).toHaveLength(1);
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
  // Reframed for Phase 2, and moved out of this file: "scrolls in the three columns and nowhere else"
  // opened a component with an enormous specification sheet and read the overflow classes off the
  // root, counted the three `[data-workspace-scroll]` elements, and checked that no section had grown
  // one of its own. Every one of those claims is now an ENGINE INVARIANT in
  // `layout/engineInvariants.test.tsx`, held for arbitrary layout documents rather than for the one
  // that ships: the frame clips both axes and nothing scrolls outside it, each scroller owns exactly
  // one axis, no region scroller nests inside another on the same axis, and pathological content adds
  // no scroll container at all - which is this test's `bigSpecs()` case, generalised (forty groups,
  // thirty offers) and asserted as a difference against the ordinary render rather than as a count of
  // three. The three-per-column half is the document's, and is asserted over
  // `DEFAULT_WORKSPACE_LAYOUT` in `layout/defaultWorkspaceLayout.test.ts`.

  it("traps focus, closes on Escape, and hands focus back to the control that opened it", async () => {
    const { user, trigger, dialog } = await openSheet(
      bigSpecs(),
      "View Pinout",
      "Pinout",
    );
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
