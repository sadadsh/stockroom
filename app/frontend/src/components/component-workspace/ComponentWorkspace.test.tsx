/**
 * The opened component, as a surface contract.
 *
 * Three columns that are always all present, an identity header whose subject is the part number
 * and nothing else, and no EDA application named anywhere in ordinary inspection. Each of those is
 * a decision that a well-meaning change can silently undo - a column dropped at a narrow width, a
 * generated name promoted back above the MPN, a tool label restored to an asset header - so each of
 * them is asserted here rather than left to a screenshot.
 *
 * The specification assertions all turn on ONE thing the dossier made possible: an expected field
 * nobody supplied is a `Missing` ROW, not an absence. That distinction cannot be recovered from an
 * empty string, so it is asserted on the rendered row rather than on a count.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { ApiError, api } from "../../api/client";
import { cadVariantApi } from "../../api/cadVariantClient";
import type { ComponentDossier, SpecificationGroup } from "../../api/dossierTypes";
import { componentRepresentationDevId, devIdSelector } from "../../lib/componentDevIds";
import { ThemeProvider } from "../../lib/theme";
import { ToastProvider } from "../../lib/toast";
import {
  defaultUiSession,
  openComponentInSession,
  resetUiSessionForTests,
} from "../../lib/uiSession";
import {
  WORKSPACE_COLUMNS_STORAGE_KEY,
  WORKSPACE_COLUMN_MIN,
  moveSplitter,
  readColumnFractions,
  resolveColumnWidths,
  writeColumnFractions,
} from "../../lib/workspaceColumns";
import {
  makeCandidate,
  makeDocument,
  makeDossier,
  makeDossierWith,
  makeOffer,
  makeRelatedPart,
  makeRepresentation,
  makeSourceLedgerEntry,
  makeSpecification,
  makeTool,
} from "../../test/dossierFixture";
import { ComponentWorkspace } from "./ComponentWorkspace";
import { cadAssetStatus } from "./workspaceStatus";
import { keyFacts, qualitySegments } from "./componentIdentity";
import { manageMenuItems } from "./ManageMenu";
import { filterGroups, countForFilter } from "./specificationRows";

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
      previewSvg: vi.fn(),
      modelGlb: vi.fn(),
      landPattern: vi.fn(),
      deletePart: vi.fn(),
      refreshSourcing: vi.fn(),
      setSpecificationOverride: vi.fn(),
      clearSpecificationOverride: vi.fn(),
      setSpecificationPreferredSource: vi.fn(),
      clearSpecificationPreferredSource: vi.fn(),
      documentFile: vi.fn(),
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

// three.js is verified in the Windows pixel gate; a column only needs the scene to mount.
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
  window.localStorage.clear();
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
async function open(
  dossier: ComponentDossier = makeDossier(),
  onDeleted?: (id: string) => void,
) {
  resetUiSessionForTests(openComponentInSession(defaultUiSession(), ID));
  mockApi.partDossier.mockResolvedValue(dossier);
  const view = provide(<ComponentWorkspace componentId={ID} onDeleted={onDeleted} />);
  // Wait on the identity element rather than its text: a fixture may deliberately carry an MPN
  // with the surrounding whitespace the copy action has to preserve, and a text query normalises it.
  await waitFor(() =>
    expect(document.querySelector(devIdSelector("component-browser.header-mpn"))).not.toBeNull(),
  );
  return view;
}

function node(devId: string): HTMLElement {
  return document.querySelector<HTMLElement>(devIdSelector(devId))!;
}

function columns(): HTMLElement[] {
  return Array.from(document.querySelectorAll<HTMLElement>("[data-workspace-column]"));
}

describe("the three-column workspace", () => {
  it("renders CAD Assets, Specifications and Sourcing and Resources side by side", async () => {
    await open();
    const present = columns().map((column) => column.dataset.workspaceColumn);
    expect(present).toEqual(["cad", "specifications", "sourcing"]);
    expect(node("component-browser.column-cad")).toHaveTextContent("CAD Assets");
    expect(node("component-browser.column-specifications")).toHaveTextContent("Specifications");
    expect(node("component-browser.column-sourcing")).toHaveTextContent("Sourcing and Resources");
  });

  it("gives every column its own scrollbar and never lets the workspace root scroll", async () => {
    await open();
    for (const column of columns()) {
      const scroller = column.querySelector<HTMLElement>("[data-workspace-scroll]")!;
      expect(scroller.className).toContain("overflow-y-auto");
      // The column FRAME is clipped; only the body inside it scrolls, so a long specification
      // list cannot push the column's own title strip off the top.
      expect(column.className).toContain("overflow-hidden");
    }
    expect(node("component-browser.root").className).toContain("overflow-hidden");
    expect(node("component-browser.columns").className).toContain("overflow-y-hidden");
  });

  it("has no per-component tab strip and no information tabs", async () => {
    await open();
    expect(document.querySelectorAll('[role="tab"]')).toHaveLength(0);
    expect(document.querySelectorAll('[role="tablist"]')).toHaveLength(0);
  });

  it("moves a splitter, persists the new proportions locally, and restores them", async () => {
    const user = userEvent.setup();
    const view = await open();
    const splitter = document.querySelector<HTMLElement>('[data-splitter="cad-specifications"]')!;
    const before = Number(splitter.getAttribute("aria-valuenow"));
    splitter.focus();
    await user.keyboard("{ArrowRight}");
    const after = Number(
      document
        .querySelector<HTMLElement>('[data-splitter="cad-specifications"]')!
        .getAttribute("aria-valuenow"),
    );
    expect(after).toBeGreaterThan(before);

    const stored = readColumnFractions();
    expect(stored).not.toBeNull();
    expect(stored!.cad).toBeGreaterThan(0.29);

    // A fresh mount reads the same machine-local preference back.
    view.unmount();
    await open();
    const restored = document.querySelector<HTMLElement>(
      '[data-splitter="cad-specifications"]',
    )!;
    expect(Number(restored.getAttribute("aria-valuenow"))).toBe(after);
  });

  it("keeps every column at or above its minimum, and never drops one", () => {
    const cramped = resolveColumnWidths(700);
    expect(cramped).toEqual(WORKSPACE_COLUMN_MIN);
    const roomy = resolveColumnWidths(1600);
    expect(roomy.cad).toBeGreaterThanOrEqual(WORKSPACE_COLUMN_MIN.cad);
    expect(roomy.specifications).toBeGreaterThanOrEqual(WORKSPACE_COLUMN_MIN.specifications);
    expect(roomy.sourcing).toBeGreaterThanOrEqual(WORKSPACE_COLUMN_MIN.sourcing);
    expect(Math.round(roomy.cad + roomy.specifications + roomy.sourcing)).toBe(1600);
  });

  it("moves a splitter as a zero-sum trade between its two neighbours only", () => {
    const start = resolveColumnWidths(1600);
    const moved = moveSplitter(start, "cad-specifications", 60);
    expect(moved.cad).toBe(start.cad + 60);
    expect(moved.specifications).toBe(start.specifications - 60);
    expect(moved.sourcing).toBe(start.sourcing);
    // A drag that would take a neighbour under its floor stops at the floor.
    const pinned = moveSplitter(start, "cad-specifications", 5000);
    expect(pinned.specifications).toBe(WORKSPACE_COLUMN_MIN.specifications);
  });

  it("stores proportions rather than pixels, so a different monitor keeps the same shape", () => {
    writeColumnFractions({ cad: 400, specifications: 800, sourcing: 400 });
    expect(window.localStorage.getItem(WORKSPACE_COLUMNS_STORAGE_KEY)).toContain("0.25");
    const wide = resolveColumnWidths(1920, readColumnFractions());
    expect(Math.round(wide.cad)).toBe(480);
    expect(Math.round(wide.specifications)).toBe(960);
  });
});

describe("the identity header", () => {
  it("makes the MPN the strongest text, and never puts a generated name before it", async () => {
    await open(
      makeDossier({
        identity: { mpn: "SN74LVC1G08DBVR", displayName: "Single 2-input AND gate" },
      }),
    );
    const mpn = node("component-browser.header-mpn");
    expect(mpn).toHaveTextContent("SN74LVC1G08DBVR");
    // The role class IS the hierarchy: 14px/600 primary, the only 14px in the workspace.
    expect(mpn.className).toContain("ui-component-mpn");

    const description = node("component-browser.header-description");
    expect(description.className).toContain("ui-component-description");
    expect(
      mpn.compareDocumentPosition(description) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    // Nothing else on the surface may claim the MPN role.
    expect(document.querySelectorAll(".ui-component-mpn")).toHaveLength(1);
  });

  it("aligns the lifecycle state separately instead of appending it to the part number", async () => {
    await open(makeDossier({ identity: { lifecycle: "Active" } }));
    expect(node("component-browser.header-mpn").textContent).toBe("LM358DR");
    expect(node("component-browser.header-lifecycle")).toHaveTextContent("Active");
  });

  it("takes its key facts from the category's own key specifications, not from the groups", async () => {
    await open(
      makeDossierWith({
        identity: { category: "Logic Gates", package: "SOT-23-5", pinCount: 5 },
        keySpecifications: [
          makeSpecification({
            key: "supply_voltage",
            label: "Supply Voltage",
            displayValue: "1.65–5.5",
            unit: "V",
            importance: "key",
          }),
          makeSpecification({
            key: "output_current",
            label: "Output Current",
            displayValue: "32",
            unit: "mA",
            importance: "key",
          }),
        ],
        groups: [
          {
            id: "package_mechanical",
            label: "Package and Mechanical",
            specifications: [
              makeSpecification({
                key: "package",
                label: "Package",
                displayValue: "SOT-23-5",
                unit: "",
              }),
            ],
          },
        ],
      }),
    );
    expect(node("component-browser.header-classification")).toHaveTextContent(
      "Logic Gates · SOT-23-5 · 5 pins",
    );
    // The two KEY specifications, in the schema's order - and not the package, which is a group
    // row the header would have picked up when it scanned the groups itself.
    const facts = node("component-browser.header-key-facts");
    expect(facts).toHaveTextContent("1.65–5.5 V · 32 mA");
    expect(facts).not.toHaveTextContent("SOT-23-5 ·");
  });

  it("never says the same fact on two of its four lines", async () => {
    // MEASURED on the seeded library's 100 nF 0402 capacitor. The header read
    //     CL05B104KO5NNNC / Samsung · 100 nF 16V X7R 0402 / Capacitors · 0402 / 100 nF · 0402
    // - `0402` three times and `100 nF` twice, on four consecutive lines. The four lines are four
    // different sentences about one part, and a distributor's description carrying the value and
    // the package in prose is ordinary, so the structured lines have to read line 2 before they
    // decide what to say.
    await open(
      makeDossierWith({
        identity: {
          mpn: "CL05B104KO5NNNC",
          manufacturer: "Samsung",
          category: "Capacitors",
          package: "0402",
          // A capacitor has no pin count, so line 3 is category and package alone.
          pinCount: null,
        },
        qualitySummary: { description: "100 nF 16V X7R 0402" },
        keySpecifications: [
          makeSpecification({
            key: "capacitance",
            label: "Capacitance",
            displayValue: "100",
            unit: "nF",
            importance: "key",
          }),
          makeSpecification({
            key: "package",
            label: "Package",
            displayValue: "0402",
            unit: "",
            importance: "key",
          }),
        ],
      }),
    );
    // The manufacturer's own words, untouched: normalising a description to fit is not this
    // header's business.
    expect(node("component-browser.header-description")).toHaveTextContent(
      "Samsung · 100 nF 16V X7R 0402",
    );
    // Line 3 keeps the classification and drops the package the description already stated.
    expect(node("component-browser.header-classification").textContent).toBe("Capacitors");
    // Line 4 had nothing left that adds anything, so it is omitted rather than padded.
    expect(document.querySelector('[data-dev-id="component-browser.header-key-facts"]')).toBeNull();
  });

  it("keeps a key fact the lines above it have not already said", async () => {
    // The rule is de-duplication, not suppression: a description that names the package does not
    // cost the reader the numbers, and line 4 still carries every fact that adds something.
    await open(
      makeDossierWith({
        identity: {
          mpn: "CL05B104KO5NNNC",
          manufacturer: "Samsung",
          category: "Capacitors",
          package: "0402",
          // A capacitor has no pin count, so line 3 is category and package alone.
          pinCount: null,
        },
        qualitySummary: { description: "MLCC 0402 X7R" },
        keySpecifications: [
          makeSpecification({
            key: "capacitance",
            label: "Capacitance",
            displayValue: "100",
            unit: "nF",
            importance: "key",
          }),
          makeSpecification({
            key: "voltage_rating",
            label: "Voltage Rating",
            displayValue: "16",
            unit: "V",
            importance: "key",
          }),
          makeSpecification({
            key: "package",
            label: "Package",
            displayValue: "0402",
            unit: "",
            importance: "key",
          }),
        ],
      }),
    );
    expect(node("component-browser.header-classification").textContent).toBe("Capacitors");
    const facts = node("component-browser.header-key-facts");
    expect(facts).toHaveTextContent("100 nF · 16 V");
    expect(facts.textContent).not.toContain("0402");
  });

  it("carries exactly the four header actions and none of the removed ones", async () => {
    await open(
      makeDossier({
        identity: {
          manufacturerPage: {
            url: "https://www.ti.com/product/LM358",
            host: "www.ti.com",
            sourceId: "manufacturer",
            sourceLabel: "Manufacturer",
            state: "verified",
            verified: true,
            reason: "the host is the manufacturer's own domain",
            checkedAt: "",
            rejectedCandidates: [],
          },
        },
        documents: {
          items: [makeDocument({ isPreferred: true })],
          count: 1,
          hasDatasheet: true,
          preferredDatasheet: makeDocument({ isPreferred: true }),
          preferredDatasheetReason: "official manufacturer PDF URL",
        },
      }),
    );
    const actions = within(node("component-browser.header-actions"))
      .getAllByRole("button")
      .map((button) => button.textContent?.trim());
    expect(actions).toEqual(["Datasheet", "Manufacturer Page", "Copy MPN", "Manage"]);

    for (const gone of [
      "Complete Component",
      "Edit Identity",
      "Resolve Source Conflict",
      "Delete Part",
      "KiCad Validated",
      "Altium Validated",
    ]) {
      expect(screen.queryByRole("button", { name: gone })).toBeNull();
    }
  });

  it("labels a missing datasheet as a state with a real action, never a dead button", async () => {
    await open(makeDossier());
    expect(node("component-browser.datasheet-missing")).toHaveTextContent("Datasheet Missing");
    expect(node("component-browser.datasheet-find")).toBeEnabled();
  });

  it("offers a Manufacturer Page only when the projection verified whose page it is", async () => {
    // An UNVERIFIED candidate is real data and is still not promoted into the action, because
    // pressing it is a promise about who published the page.
    await open(
      makeDossier({
        identity: {
          manufacturerPage: {
            url: "https://catalog.example.invalid/lm358",
            host: "catalog.example.invalid",
            sourceId: "",
            sourceLabel: "",
            state: "unverified",
            verified: false,
            reason: "nothing proves this host belongs to the manufacturer",
            checkedAt: "",
            rejectedCandidates: [
              {
                url: "https://www.mouser.com/lm358",
                sourceId: "mouser",
                sourceLabel: "Mouser",
                reason: "Mouser hosts its own listing, not the official page",
              },
            ],
          },
        },
      }),
    );
    expect(
      document.querySelector(devIdSelector("component-browser.header-manufacturer-page")),
    ).toBeNull();
  });
});

describe("Copy MPN", () => {
  it("copies the canonical part number exactly, and does not resize while confirming", async () => {
    const user = userEvent.setup();
    // AFTER setup(): user-event installs its own clipboard stub, and this test is about the exact
    // string the control hands to the platform, not about what user-event would store.
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", {
      value: { writeText },
      configurable: true,
    });
    await open(makeDossier({ identity: { mpn: "  SN74LVC1G08DBVR " } }));

    const button = node("component-browser.copy-mpn");
    const labelBefore = button.textContent;
    await user.click(button);
    // Byte for byte: no trim, no case change, no appended package.
    expect(writeText).toHaveBeenCalledWith("  SN74LVC1G08DBVR ");
    await waitFor(() => expect(button.querySelector('[data-copied="true"]')).not.toBeNull());
    // The label is unchanged and the glyph box is fixed, so nothing beside it moves.
    expect(button.textContent).toBe(labelBefore);
    expect(button.querySelector('[data-copied="true"]')!.className).toContain("h-3.5 w-3.5");
    expect(button).toHaveAccessibleName("Copied");
  });
});

describe("the Manage menu", () => {
  it("lists every management action, with Delete Component alone at the bottom", async () => {
    const user = userEvent.setup();
    await open();
    await user.click(node("component-browser.manage"));
    const entries = within(node("component-browser.manage-menu")).getAllByRole("menuitem");
    expect(entries.map((item) => item.textContent?.trim())).toEqual([
      "Edit Identity...",
      "Edit Category and Classification...",
      "Review Missing Specifications...",
      "Refresh Component Data",
      "Review CAD Sources...",
      "View Data Provenance...",
      "Delete Component...",
    ]);
    // Destructive last, and restrained red TEXT rather than a filled control.
    const last = entries[entries.length - 1];
    expect(last.className).toContain("text-err");
    expect(last.className).not.toContain("bg-err");
  });

  it("puts an ellipsis only where another surface follows", () => {
    const items = manageMenuItems({
      onEditIdentity: () => {},
      onEditClassification: () => {},
      onReviewMissing: () => {},
      onRefresh: () => {},
      refreshing: false,
      onReviewCadSources: () => {},
      onViewProvenance: () => {},
      onDelete: () => {},
    });
    expect(items.find((item) => item.id === "refresh")!.label).toBe("Refresh Component Data");
    expect(items.filter((item) => item.label.endsWith("...")).length).toBe(items.length - 1);
    expect(items[items.length - 1].id).toBe("delete");
    expect(items[items.length - 1].separated).toBe(true);
  });

  it("closes on Escape and hands focus back to the trigger", async () => {
    const user = userEvent.setup();
    await open();
    await user.click(node("component-browser.manage"));
    await user.keyboard("{Escape}");
    await waitFor(() =>
      expect(document.querySelector(devIdSelector("component-browser.manage-menu"))).toBeNull(),
    );
    expect(document.activeElement).toBe(node("component-browser.manage"));
  });

  it("names the component and what is removed before it deletes anything", async () => {
    const user = userEvent.setup();
    const onDeleted = vi.fn();
    mockApi.deletePart.mockResolvedValue(undefined);
    await open(makeDossier({ identity: { mpn: "LM358DR" } }), onDeleted);

    await user.click(node("component-browser.manage"));
    await user.click(screen.getByRole("menuitem", { name: "Delete Component..." }));

    const dialog = await screen.findByRole("dialog", { name: "Delete Component" });
    expect(dialog).toHaveTextContent("LM358DR");
    expect(dialog).toHaveTextContent(/symbol, footprint, 3D model, specifications/);
    // Only the final confirmation is solid red.
    const confirm = within(dialog).getByRole("button", { name: "Delete Component" });
    expect(confirm.className).toContain("bg-err");
    await user.click(confirm);
    await waitFor(() => expect(mockApi.deletePart).toHaveBeenCalledWith(ID));
    await waitFor(() => expect(onDeleted).toHaveBeenCalledWith(ID));
  });
});

describe("no EDA application is named in ordinary inspection", () => {
  const EDA = /kicad|altium|eagle|orcad|easyeda/i;

  it("names asset kinds, states and PROVIDERS, and never a design tool", async () => {
    const { container } = await open(
      makeDossier({
        cadAssets: {
          kinds: {
            symbol: makeRepresentation("symbol", "ready", [
              makeTool({ tool: "kicad", toolLabel: "KiCad", sourceLabel: "Ultra Librarian" }),
              makeTool({ tool: "altium", toolLabel: "Altium", sourceLabel: "Ultra Librarian" }),
            ]),
            footprint: makeRepresentation("footprint", "ready", [
              makeTool({ tool: "kicad", toolLabel: "KiCad", sourceLabel: "Ultra Librarian" }),
            ]),
            model: makeRepresentation("model", "ready", [
              makeTool({ tool: "kicad", toolLabel: "KiCad", sourceLabel: "Ultra Librarian" }),
            ]),
          },
          // The column-level decision names the PROVIDER, and the choice it offers is a
          // provider too. Neither is an EDA application, which is the whole distinction.
          preference: {
            provider: "ultralibrarian",
            label: "Ultra Librarian",
            pinned: true,
            assets: {
              symbol: { provider: "ultralibrarian", label: "Ultra Librarian", origin: "set_preference" },
              footprint: { provider: "ultralibrarian", label: "Ultra Librarian", origin: "set_preference" },
              model: { provider: "ultralibrarian", label: "Ultra Librarian", origin: "set_preference" },
            },
            options: [
              {
                provider: "ultralibrarian",
                label: "Ultra Librarian",
                coverage: { symbol: "validated", footprint: "validated", model: "validated" },
                set: { allowed: true, refusal: "", reason: "", changes: [], current: true },
                assets: {
                  symbol: { allowed: true, refusal: "", reason: "", changes: [], current: false },
                  footprint: { allowed: true, refusal: "", reason: "", changes: [], current: false },
                  model: { allowed: true, refusal: "", reason: "", changes: [], current: false },
                },
              },
            ],
          },
        },
        provenance: { sources: [makeSourceLedgerEntry({ id: "digikey", label: "DigiKey" })] },
        distributorOffers: [makeOffer()],
        supplySummary: { offerCount: 1, totalStock: 512 },
      }),
    );
    expect(container.textContent ?? "").not.toMatch(EDA);
    // The provider IS named, because a provider is source information.
    expect(node("component-browser.preferred-source")).toHaveTextContent("Ultra Librarian");
    expect(node("component-browser.column-cad")).toHaveTextContent("Symbol");
  });

  it("states an asset with a recorded check as Validated, never as the vague Ready", () => {
    const validated = makeRepresentation("symbol", "ready", [
      makeTool({
        checks: [
          {
            check: "pin_count",
            measured: 8,
            expected: 8,
            against: "datasheet",
            checkedAt: "2026-08-01T00:00:00Z",
            note: "",
          },
        ],
      }),
    ]);
    expect(cadAssetStatus(validated)).toBe("Validated");
    expect(cadAssetStatus(makeRepresentation("symbol", "ready"))).toBe("Available");
    expect(cadAssetStatus(makeRepresentation("footprint", "missing", []))).toBe("Missing");
    expect(cadAssetStatus(makeRepresentation("model", "failed"))).toBe("Failed");
  });

  it("keeps every asset module on screen when one is expanded", async () => {
    const user = userEvent.setup();
    await open();
    await user.click(screen.getByRole("button", { name: "Footprint", expanded: true }));
    for (const kind of ["symbol", "footprint", "model"] as const) {
      expect(
        document.querySelector(devIdSelector(componentRepresentationDevId(ID, kind))),
      ).not.toBeNull();
    }
  });
});

/**
 * One electrical group carrying the four situations that used to be indistinguishable: a verified
 * value, a field the category EXPECTS and nobody supplied, a field nobody supplied that the
 * category does not require, and two sources disagreeing.
 */
const ELECTRICAL_ROWS = [
    makeSpecification({
      key: "supply_voltage",
      label: "Supply Voltage",
      displayValue: "3.3",
      unit: "V",
      verificationState: "verified",
    }),
    makeSpecification({
      key: "gain_bandwidth",
      label: "Gain Bandwidth",
      verificationState: "missing",
      applicability: "expected",
      expectedForCategory: true,
    }),
    makeSpecification({
      key: "slew_rate",
      label: "Slew Rate",
      verificationState: "not_reported",
      applicability: "applicable",
      expectedForCategory: false,
    }),
    makeSpecification({
      key: "operating_temperature",
      label: "Operating Temperature",
      displayValue: "−40–125",
      unit: "°C",
      verificationState: "conflicting",
      conflictState: "conflicting",
      sourceCandidates: [
        makeCandidate({
          sourceId: "digikey",
          sourceLabel: "DigiKey",
          value: "−40–125",
          displayValue: "−40–125",
        }),
        makeCandidate({
          sourceId: "mouser",
          sourceLabel: "Mouser",
          value: "0–70",
          displayValue: "0–70",
        }),
      ],
      preferredSource: makeCandidate({
        sourceId: "digikey",
        sourceLabel: "DigiKey",
        value: "−40–125",
        displayValue: "−40–125",
      }),
    }),
];

const ELECTRICAL: SpecificationGroup = {
  id: "electrical",
  label: "Electrical",
  specifications: ELECTRICAL_ROWS,
  count: ELECTRICAL_ROWS.length,
};

describe("the specification column", () => {
  it("shows the specifications immediately, not behind a tab or a View All", async () => {
    await open(makeDossierWith({ groups: [ELECTRICAL] }));
    const column = node("component-browser.column-specifications");
    expect(column).toHaveTextContent("Supply Voltage");
    expect(column).toHaveTextContent("3.3 V");
  });

  it("renders an expected field nobody supplied as a real Missing row", async () => {
    await open(makeDossierWith({ groups: [ELECTRICAL] }));
    const row = document.querySelector<HTMLElement>('[data-spec-key="gain_bandwidth"]')!;
    expect(row).not.toBeNull();
    expect(row.dataset.specState).toBe("missing");
    expect(row).toHaveTextContent("Gain Bandwidth");
    expect(row).toHaveTextContent("Missing");
  });

  it("keeps Not Reported apart from Missing, because only one of them is a gap", async () => {
    await open(makeDossierWith({ groups: [ELECTRICAL] }));
    const notReported = document.querySelector<HTMLElement>('[data-spec-key="slew_rate"]')!;
    expect(notReported.dataset.specState).toBe("not_reported");
    expect(notReported).toHaveTextContent("Not Reported");
    // The header counts the GAP only. A field the category never asked for is not one.
    expect(node("component-browser.quality-summary").dataset.missing).toBe("1");
  });

  it("attaches a conflicting value's alternative to the row it disagrees with", async () => {
    const user = userEvent.setup();
    await open(makeDossierWith({ groups: [ELECTRICAL] }));
    const row = document.querySelector<HTMLElement>(
      '[data-spec-key="operating_temperature"]',
    )!;
    expect(row.dataset.specState).toBe("conflicting");
    await user.click(
      within(row).getByRole("button", { name: /Source evidence for Operating Temperature/ }),
    );
    // The losing answer is listed ON the row it disagrees with, carrying the source that offered
    // it and the trust tier that lost it the field.
    const alternate = within(row).getByRole("listitem");
    expect(alternate).toHaveTextContent("0–70");
    expect(alternate).toHaveTextContent("Mouser");
    expect(
      within(alternate).getByRole("button", { name: "Use Mouser Value" }),
    ).toBeInTheDocument();
  });

  it("filters rather than paginates, and the header's quality summary drives the filter", async () => {
    const user = userEvent.setup();
    await open(makeDossierWith({ groups: [ELECTRICAL] }));
    const missing = document.querySelector<HTMLElement>('[data-quality-segment="missing"]')!;
    expect(missing).toHaveTextContent("1 Required Values Missing");
    await user.click(missing);
    await waitFor(() =>
      expect(
        document.querySelectorAll('[data-dev-id="component-browser.spec-row"]'),
      ).toHaveLength(1),
    );
    expect(document.querySelector('[data-spec-state="missing"]')).toHaveTextContent(
      "Gain Bandwidth",
    );
  });

  it("counts each filter over the six-state vocabulary rather than over empty strings", () => {
    expect(countForFilter([ELECTRICAL], [], "missing")).toBe(1);
    expect(countForFilter([ELECTRICAL], [], "conflicts")).toBe(1);
    expect(countForFilter([ELECTRICAL], [], "unverified")).toBe(0);
    // A group that loses every row is dropped rather than rendered as an empty heading.
    expect(filterGroups([ELECTRICAL], "conflicts", "")).toHaveLength(1);
    expect(filterGroups([ELECTRICAL], "conflicts", "supply")).toHaveLength(0);
  });

  it("takes key facts from keySpecifications and never invents one", () => {
    const dossier = makeDossierWith({
      keySpecifications: [
        makeSpecification({ key: "a", displayValue: "3.3", unit: "V", importance: "key" }),
        makeSpecification({ key: "b", displayValue: "", verificationState: "missing" }),
      ],
    });
    // The one with a value. A key specification with no answer keeps its ROW below and stays out
    // of a header line that would otherwise be a row of blanks.
    expect(keyFacts(dossier).map((fact) => fact.key)).toEqual(["a"]);
    expect(keyFacts(makeDossier())).toEqual([]);
  });
});

describe("the sourcing column", () => {
  it("answers lifecycle, stock and price before it explains where they came from", async () => {
    await open(
      makeDossier({
        identity: { lifecycle: "Active" },
        distributorOffers: [makeOffer({ stock: 512, unitPrice: 0.42 })],
        supplySummary: {
          offerCount: 1,
          totalStock: 512,
          bestUnitPrice: 0.42,
          bestUnitPriceCurrency: "$",
          lifecycle: "Active",
        },
        provenance: { sources: [makeSourceLedgerEntry()] },
      }),
    );
    const column = node("component-browser.column-sourcing");
    expect(column).toHaveTextContent("512");
    expect(column).toHaveTextContent("$0.42");
    const lifecycle = node("component-browser.lifecycle");
    const provenance = node("component-browser.provenance");
    expect(
      lifecycle.compareDocumentPosition(provenance) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
  });

  it("says Unknown when no distributor reported a count, and never renders it as zero", async () => {
    await open(
      makeDossier({
        distributorOffers: [makeOffer({ stock: null })],
        supplySummary: { offerCount: 1, totalStock: null },
      }),
    );
    const stock = node("component-browser.total-stock");
    expect(stock.dataset.stockKnown).toBe("false");
    expect(stock).toHaveTextContent("Unknown");
    expect(stock).not.toHaveTextContent("0");
  });

  it("distinguishes a real zero from an unknown count", async () => {
    await open(
      makeDossier({
        distributorOffers: [makeOffer({ stock: 0 })],
        supplySummary: { offerCount: 1, totalStock: 0 },
      }),
    );
    const stock = node("component-browser.total-stock");
    expect(stock.dataset.stockKnown).toBe("true");
    expect(stock).toHaveTextContent("0");
  });

  it("names the destination of a distributor link rather than saying Product Page", async () => {
    await open(
      makeDossier({
        distributorOffers: [makeOffer({ provider: "mouser", providerLabel: "Mouser" })],
        supplySummary: { offerCount: 1 },
      }),
    );
    expect(screen.getByRole("link", { name: "Open Mouser Listing" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Product Page" })).toBeNull();
  });

  it("attaches a source failure to the sourcing section without blanking the old numbers", async () => {
    await open(
      makeDossier({
        distributorOffers: [makeOffer({ failureState: "failed" })],
        supplySummary: {
          offerCount: 1,
          totalStock: 512,
          failures: [
            { provider: "digikey", providerLabel: "DigiKey", state: "failed" },
          ],
        },
      }),
    );
    // Named, and a sentence rather than a state token pasted into one.
    expect(node("component-browser.offer-failures")).toHaveTextContent(
      "DigiKey could not be read",
    );
    // The offer it failed to refresh is still on screen, with its last known numbers.
    expect(node("component-browser.offers")).toHaveTextContent("512");
  });

  it("states why a related part is related, and that Stockroom has validated nothing", async () => {
    await open(
      makeDossier({
        relatedParts: [
          makeRelatedPart({
            mpn: "SN74AHC1G08DBVR",
            reason: "same_function_different_logic_family",
            reasonLabel: "Same function, different logic family",
            evidence: [{ field: "logic_family", ours: "LVC", theirs: "AHC" }],
          }),
        ],
      }),
    );
    const row = document.querySelector<HTMLElement>('[data-dev-id="component-browser.related-row"]')!;
    expect(row.dataset.relatedReason).toBe("same_function_different_logic_family");
    expect(row).toHaveTextContent("Same function, different logic family");
    expect(node("component-browser.related-evidence")).toHaveTextContent(
      "logic_family: LVC → AHC",
    );
    expect(node("component-browser.related-not-validated")).toHaveTextContent(
      "Not checked for equivalence by Stockroom",
    );
  });

  it("shows the preferred datasheet's reason instead of re-deriving which copy wins", async () => {
    await open(
      makeDossierWith({
        documents: [
          makeDocument({
            title: "LM358 Datasheet",
            isPreferred: true,
            sourceType: "distributor",
            sourceLabel: "DigiKey",
          }),
        ],
      }),
    );
    expect(node("component-browser.preferred-datasheet-reason")).toHaveTextContent(
      "official manufacturer PDF URL",
    );
  });
});

describe("the workspace status bar", () => {
  it("states the component's own condition without repeating the library counts", async () => {
    await open(makeDossierWith({ groups: [ELECTRICAL] }));
    const bar = node("component-browser.status-bar");
    expect(bar).toHaveTextContent("Ready");
    expect(bar).toHaveTextContent("1 missing");
    expect(bar).toHaveTextContent("1 conflicting");
  });

  it("summarises quality as named conditions, never as an opaque fraction", () => {
    const dossier = makeDossier({
      cadAssets: { kinds: { footprint: makeRepresentation("footprint", "missing", []) } },
    });
    const segments = qualitySegments(dossier);
    expect(segments.map((segment) => segment.kind)).toEqual(["cad"]);
    expect(segments[0].tone).toBe("warn");
    expect(segments[0].count).toBe(1);
  });
});
