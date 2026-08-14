/**
 * The Sourcing and Resources column, as a surface contract.
 *
 * Three decisions here are the kind a well-meaning change silently undoes, so each of them is
 * asserted rather than left to a screenshot:
 *
 *   * THE ORDER. Six sections, with the source ledger last. It is the easiest thing in the world to
 *     move a provenance block up "so people can see where the data came from", and doing it puts an
 *     explanation above the thing it explains. Reframed for Phase 2: the order is stated by the LAYOUT
 *     DOCUMENT and pinned in `layout/defaultWorkspaceLayout.test.ts`, so what this file asserts is that
 *     the rendered column agrees with the document it was drawn from - including after a reveal.
 *   * THE REFRESH. A refresh that empties the offers table before repopulating it is
 *     indistinguishable, on screen, from a part no distributor carries. Stale numbers with their
 *     staleness stated are strictly better, and the rule has to hold even when the projection
 *     momentarily reports nothing.
 *   * THE TRANSLATION. `Answered`, `Schema version 4`, `derived_by_unknown` and their relatives
 *     are all true and all useless. The enumerated list in `provenanceText.tsx` is asserted
 *     against the whole rendered surface, so a raw key cannot come back through a new row.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { ApiError, api } from "../../api/client";
import { cadVariantApi } from "../../api/cadVariantClient";
import type { ComponentDossier, DistributorOffer } from "../../api/dossierTypes";
import { DevModeProvider } from "../../lib/devMode";
import { ThemeProvider } from "../../lib/theme";
import { ToastProvider } from "../../lib/toast";
import {
  defaultUiSession,
  openComponentInSession,
  resetUiSessionForTests,
} from "../../lib/uiSession";
import {
  makeDocument,
  makeDossier,
  makeFieldConflict,
  makeManualOverride,
  makeOffer,
  makeRelatedPart,
  makeRevisionEvent,
  makeSourceLedgerEntry,
} from "../../test/dossierFixture";
import { DEFAULT_WORKSPACE_LAYOUT } from "../../layout/defaultWorkspaceLayout";
import { findRegion } from "../../layout/document";
import { WORKSPACE_PIECE_REGISTRY, WORKSPACE_REGION } from "../../layout/workspacePieces";
import { ComponentWorkspace } from "./ComponentWorkspace";
import { OffersSection } from "./OffersSection";
import { volumeBreak } from "./offerFacts";
import { FORBIDDEN_IN_NORMAL_UI } from "./provenanceVocabulary";

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
  mockApi.partHistory.mockResolvedValue({ commits: [], count: 0 });
  mockApi.facets.mockResolvedValue({
    by_category: { ICs: 1 },
    by_manufacturer: {},
    complete: 1,
    incomplete: 0,
    category_catalog: ["ICs"],
  });
  mockCadVariantApi.inventory.mockResolvedValue({
    partId: ID,
    inventories: [],
    pairs: [],
    supplementary: [],
  });
});

/**
 * The provider frame, as an ELEMENT rather than a render call.
 *
 * A rerender has to hand back the same wrapped tree. Re-rendering a bare child would unmount the
 * providers and remount the component with fresh state, which would quietly turn the
 * "never empties" assertion into a test of a component that had just been created.
 */
function wrap(ui: ReactNode, qc: QueryClient) {
  return (
    <QueryClientProvider client={qc}>
      <ThemeProvider>
        <DevModeProvider>
          <ToastProvider>{ui}</ToastProvider>
        </DevModeProvider>
      </ThemeProvider>
    </QueryClientProvider>
  );
}

function provide(ui: ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const view = render(wrap(ui, qc));
  return { ...view, rerenderWrapped: (next: ReactNode) => view.rerender(wrap(next, qc)) };
}

async function open(dossier: ComponentDossier = makeDossier()) {
  resetUiSessionForTests(openComponentInSession(defaultUiSession(), ID));
  mockApi.partDossier.mockResolvedValue(dossier);
  const view = provide(<ComponentWorkspace componentId={ID} />);
  await screen.findByText(dossier.identity.mpn);
  return { ...view, user: userEvent.setup() };
}

function region(devId: string): HTMLElement {
  return document.querySelector<HTMLElement>(`[data-dev-id="${devId}"]`)!;
}

/**
 * THE SECTIONS ON SCREEN, in the order the rendered column stacks them.
 *
 * Reframed for Phase 2: the expected order is no longer a list typed out here, it is READ OFF THE
 * LAYOUT DOCUMENT (see `documentSectionOrder`), because the order of the sections is the document's to
 * state and a committed redesign is allowed to change it. What the tests below still use this for is
 * WHICH sections drew at all, which is content-driven behaviour and is this file's business.
 */
function sectionOrder(): string[] {
  const known = new Set(documentSectionOrder());
  const column = region("component-browser.column-sourcing");
  return Array.from(column.querySelectorAll<HTMLElement>("[data-dev-id]"))
    .map((node) => node.dataset.devId!)
    .filter((id) => known.has(id));
}

/**
 * The six sections' dev ids, in the order the layout document places them.
 *
 * Resolved through the piece registry - each placement names a piece, each manifest names the dev ids
 * that piece renders, and the section's own id is the first of them - so this is the document's order
 * rather than a second copy of it. The reveal control at the bottom is not a section and is dropped.
 */
function documentSectionOrder(): string[] {
  const body = findRegion(DEFAULT_WORKSPACE_LAYOUT, WORKSPACE_REGION.sourcingBody);
  return (body?.slots ?? [])
    .map((slot) => (slot.content?.kind === "placement" ? slot.content.piece : ""))
    .filter((piece) => piece && piece !== "workspace.sourcing-empty-sections")
    .map((piece) => WORKSPACE_PIECE_REGISTRY.get(piece)?.devIds[0] ?? piece);
}

describe("the column's shape", () => {
  // Reframed for Phase 2, and moved: "asks the six questions in the order a person asks them, ledger
  // last" rendered a fully-sourced component and read the six section dev ids back out of the column.
  // That order is the layout document's, and it is now written out in full over
  // `DEFAULT_WORKSPACE_LAYOUT` in `layout/defaultWorkspaceLayout.test.ts` ("asks the six sourcing
  // questions in the order a person asks them, ledger last"), where a redesign is a different document
  // and a regression in the shipped one still fails. That the renderer draws a region's slots in the
  // document's order is `layout/engineInvariants.test.tsx`, held for arbitrary documents. Nothing was
  // dropped: the ORDER assertions the reveal test below makes are now made against the document's own
  // order, which is strictly more than this test asserted.

  it("keeps the manufacturer's own status apart from the library's lifecycle", async () => {
    await open(
      makeDossier({
        identity: { lifecycle: "Active" },
        supplySummary: {
          lifecycle: "Active",
          manufacturerStatus: "Not Recommended For New Designs",
        },
      }),
    );
    const lifecycle = region("component-browser.lifecycle");
    // Two rows, two claims, allowed to disagree: a distributor still listing a part as active
    // does not stop the manufacturer having marked it NRND.
    expect(within(lifecycle).getByText("Active")).toBeInTheDocument();
    expect(region("component-browser.manufacturer-status")).toHaveTextContent(
      "Not Recommended For New Designs",
    );
  });

  it("omits a manufacturer status nobody stated", async () => {
    await open(makeDossier({ supplySummary: { manufacturerStatus: "" } }));
    expect(document.querySelector('[data-dev-id="component-browser.manufacturer-status"]')).toBeNull();
  });

  it("renders a lifecycle state as text with no control affordance at all", async () => {
    await open(makeDossier({ supplySummary: { lifecycle: "Obsolete" } }));
    const status = within(region("component-browser.lifecycle")).getByText("Obsolete");
    // `ui-status-text` pins cursor:default and strips border, fill, hover and focus ring.
    expect(status).toHaveClass("ui-status-text");
    expect(status.closest("button")).toBeNull();
    expect(status.closest("a")).toBeNull();
    // Red, because obsolete means something. Colour is spent only where it does.
    expect(status).toHaveClass("text-err-text");
  });
});

/**
 * A section with nothing in it is not on screen, and one control puts every one of them back.
 *
 * The column used to render a full sentence per empty section, and there are eight of them across
 * five sections. On a part nobody has sourced that was most of the column - paragraphs of prose
 * where there is no information - and it is a large part of why the three columns read as uneven.
 * Four things have to hold, and each is a different way the fix could go wrong:
 *
 *   the empty section is genuinely ABSENT, not merely quiet;
 *   the reveal brings it back, so nothing is deleted;
 *   the ORDER survives the reveal, with provenance still last;
 *   the lifecycle rows never collapse, because "nobody has checked" is a fact about the part.
 */
describe("the empty sections", () => {
  /** A capacitor nobody has sourced: no offers, no documents, no relations, no ledger. */
  const bare = makeDossier();

  it("renders no empty section, and no sentence from one, until asked", async () => {
    await open(bare);
    const column = region("component-browser.column-sourcing");
    expect(sectionOrder()).toEqual(["component-browser.lifecycle"]);
    // The eight sentences, none of them on screen.
    for (const sentence of [
      /No distributor has quoted/,
      /No document has been recorded/,
      /No source has been consulted/,
      /No source disagrees/,
      /Nobody has overridden/,
      /Nothing is recorded about how/,
      /Nothing has changed since/,
      /No distributor has suggested/,
    ]) {
      expect(column.textContent ?? "").not.toMatch(sentence);
    }
  });

  it("says how many sections are silent, and reveals them in the column's own order", async () => {
    const { user } = await open(bare);
    // The count is the answer as well as the action: five conditional sections are silent.
    const toggle = screen.getByRole("button", { name: "Show 5 Blank Sections" });
    expect(toggle).toHaveAttribute("aria-expanded", "false");

    await user.click(toggle);
    // Every section is back, in the order the DOCUMENT places them - the reveal adds sections, it does
    // not rearrange the column. Compared against the document rather than against a list typed here,
    // so a committed redesign moves both sides at once and only a reveal that reordered things fails.
    expect(sectionOrder()).toEqual(documentSectionOrder());
    expect(documentSectionOrder()).toHaveLength(6);
    // Revealed, the sentences are back: the information was hidden, never removed.
    expect(screen.getByText(/No distributor has quoted/)).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Hide 5 Blank Sections" }),
    ).toHaveAttribute("aria-expanded", "true");
  });

  it("remembers the choice for this machine, in the storage the splitters already use", async () => {
    const { user } = await open(bare);
    await user.click(screen.getByRole("button", { name: "Show 5 Blank Sections" }));
    expect(
      window.localStorage.getItem("stockroom.component-workspace.sourcing-empty.v1"),
    ).toBe("true");
  });

  it("renders only product-status facts a source actually stated", async () => {
    await open(bare);
    const lifecycle = region("component-browser.lifecycle");
    expect(within(lifecycle).getByText("Product Status")).toBeInTheDocument();
    expect(within(lifecycle).getByText("Active")).toBeInTheDocument();
    expect(within(lifecycle).queryByText("Manufacturer Status")).toBeNull();
    expect(within(lifecycle).queryByText("Total Stock")).toBeNull();
    expect(within(lifecycle).queryByText("Lead Time")).toBeNull();
    expect(within(lifecycle).queryByText("Last Checked")).toBeNull();
    expect(within(lifecycle).queryByText("Unknown")).toBeNull();
  });

  it("offers no reveal at all when nothing is hidden", async () => {
    await open(
      makeDossier({
        distributorOffers: [makeOffer()],
        supplySummary: { offerCount: 1, totalStock: 512, factoryLeadTime: "12 weeks" },
        documents: { items: [makeDocument()], count: 1 },
        relatedParts: [makeRelatedPart()],
        provenance: { sources: [makeSourceLedgerEntry()] },
      }),
    );
    // A control that would reveal zero sections is a dead click path.
    expect(screen.queryByRole("button", { name: /Empty Sections/ })).toBeNull();
  });

  it("counts a named source failure as content, not as an empty offers section", async () => {
    await open(
      makeDossier({
        supplySummary: {
          failures: [{ provider: "lcsc", providerLabel: "LCSC", state: "not_configured" }],
        },
      }),
    );
    // "LCSC is not connected on this machine" is the difference between a part nobody sells and a
    // source nobody could reach, so the section that carries it stands on its own.
    expect(sectionOrder()).toContain("component-browser.offers");
    expect(region("component-browser.offer-failures")).toBeInTheDocument();
  });
});

/**
 * The provenance block used to render five counted sub-sections in a row - Data Sources 0, Field
 * Conflicts 0, Manual Overrides 0, Import and Enrichment Timeline 0, Revision Timeline 0 - each with
 * its own heading and its own sentence underneath. Five headings and five sentences to say nothing
 * happened. Now the silent ones are named once, on one line, and the full ledger is still one
 * button away.
 */
describe("the provenance block does not repeat itself", () => {
  it("names the silent questions on one line instead of five stacked sections", async () => {
    const { user } = await open(makeDossier());
    await user.click(screen.getByRole("button", { name: "Show 5 Blank Sections" }));

    const provenance = region("component-browser.provenance");
    // Not one of the five sub-sections is mounted...
    for (const devId of [
      "component-browser.provenance-sources",
      "component-browser.provenance-conflicts",
      "component-browser.provenance-overrides",
      "component-browser.provenance-intake",
      "component-browser.provenance-revisions",
    ]) {
      expect(provenance.querySelector(`[data-dev-id="${devId}"]`)).toBeNull();
    }
    // ...and all five are still ANSWERED, in one line, by the names their headings use.
    expect(region("component-browser.provenance-nothing")).toHaveTextContent(
      "Nothing recorded: Data Sources · Field Conflicts · Manual Overrides · " +
        "Import and Enrichment Timeline · Revision Timeline",
    );
    // The way to the complete ledger survives the collapse.
    expect(
      within(provenance).getByRole("button", { name: "View Data Provenance" }),
    ).toBeInTheDocument();
  });

  it("shows the questions that have answers and names only the rest", async () => {
    await open(
      makeDossier({
        provenance: { sources: [makeSourceLedgerEntry({ id: "mouser", label: "Mouser" })] },
      }),
    );
    expect(region("component-browser.provenance-sources")).toHaveTextContent("Mouser");
    // The four with nothing in them are one line, and Data Sources is not among them.
    const line = region("component-browser.provenance-nothing");
    expect(line).toHaveTextContent("Field Conflicts");
    expect(line).toHaveTextContent("Revision Timeline");
    expect(line.textContent ?? "").not.toContain("Data Sources");
  });
});

describe("the distributor offers ledger", () => {
  const offersDossier = makeDossier({
    distributorOffers: [
      makeOffer({
        provider: "mouser",
        providerLabel: "Mouser",
        sku: "511-LM358",
        stock: 1240,
        currency: "USD",
        unitPrice: 0.42,
        moq: 10,
        leadTime: "12 weeks",
        factoryLeadTime: "20 weeks",
        lifecycle: "NRND",
        staleness: "stale",
        priceBreaks: [
          { qty: 1, price: 0.42 },
          { qty: 100, price: 0.22 },
        ],
      }),
    ],
    supplySummary: {
      offerCount: 1,
      totalStock: 1240,
      bestUnitPrice: 0.42,
      bestUnitPriceCurrency: "USD",
      bestUnitPriceProvider: "mouser",
    },
  });

  it("shows one compact offer summary and reveals its complete ladder and metadata together", async () => {
    const { user } = await open(offersDossier);
    const ledger = screen.getByRole("list", { name: "Distributor offers" });
    const offer = region("component-browser.offer-row");

    expect(ledger).not.toHaveClass("overflow-x-auto");
    expect(ledger.querySelector("table")).toBeNull();
    expect(offer).not.toHaveAttribute("open");
    expect(within(offer).getByText("Stock")).toBeVisible();
    expect(within(offer).getByText("Unit Price")).toBeVisible();
    expect(within(offer).getByText("1,240")).toBeVisible();
    expect(within(offer).getByText("Price Breaks")).not.toBeVisible();
    expect(within(offer).getByText("20 weeks")).not.toBeVisible();

    await user.click(within(offer).getByTitle("511-LM358"));

    expect(offer).toHaveAttribute("open");
    expect(within(offer).getByText("Price Breaks")).toBeVisible();
    for (const label of [
      "Quote Code",
      "MOQ",
      "Lead Time",
      "Manufacturer Lead Time",
      "Product Status",
      "Last Checked",
    ]) {
      expect(within(offer).getByText(label)).toBeVisible();
    }
    expect(within(offer).getByText("20 weeks")).toBeVisible();
    expect(within(offer).getByText("NRND")).toBeVisible();
    expect(within(offer).getByText(/Stale$/)).toBeVisible();
    expect(within(offer).getAllByText("USD0.42")).toHaveLength(2);
    expect(within(offer).getByText("USD0.22")).toBeVisible();
  });

  it("renders the normalized provider priority without locally reordering package variants", () => {
    const normalized = [
      makeOffer({ provider: "mouser", sku: "MOUSER-1" }),
      makeOffer({ provider: "mouser", sku: "MOUSER-2" }),
      makeOffer({ provider: "digikey", sku: "DK-1" }),
      makeOffer({ provider: "digikey", sku: "DK-2" }),
    ];
    provide(
      <OffersSection
        offers={normalized}
        failures={[]}
        onRefresh={() => {}}
        onViewAll={() => {}}
        refreshing={false}
      />,
    );

    expect([...document.querySelectorAll<HTMLElement>("[data-offer-provider]")].map(
      (row) => within(row).getByTitle(/^(MOUSER|DK)-/).textContent,
    )).toEqual(["MOUSER-1", "MOUSER-2", "DK-1", "DK-2"]);
  });

  it("right-aligns the figures that are compared down a column", async () => {
    await open(offersDossier);
    const row = region("component-browser.offer-row");
    // Stock, price, break and MOQ all opt into `.ui-numeric`, which is tabular figures plus
    // right alignment. A provider name does not, because names are read, not compared.
    expect(within(row).getByText("1,240")).toHaveClass("ui-numeric");
    expect(within(row).getAllByText("USD0.42").every((value) => value.classList.contains("ui-numeric"))).toBe(true);
    expect(within(row).getByText("USD0.22")).toHaveClass("ui-numeric");
    const provider = document.querySelector<HTMLElement>('[data-sourcing-provider="mouser"]')!;
    expect(within(provider).getByText("Mouser")).not.toHaveClass("ui-numeric");
  });

  it("keeps the provider name quieter than the price it is quoting", async () => {
    await open(offersDossier);
    const row = region("component-browser.offer-row");
    // `ui-key-fact` is 11/600 primary; `ui-row-secondary` is 11/400 secondary. The engineering
    // datum outranks the brand, which is the whole point of a comparison table.
    expect(within(row).getAllByText("USD0.42").every((value) => value.classList.contains("ui-key-fact"))).toBe(true);
    const provider = document.querySelector<HTMLElement>('[data-sourcing-provider="mouser"]')!;
    expect(within(provider).getByText("Mouser")).toHaveClass("ui-row-secondary");
  });

  it("names the destination of a listing action rather than saying Product Page", async () => {
    await open(offersDossier);
    expect(screen.getByRole("link", { name: "Open Mouser Listing" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Product Page/ })).toBeNull();
  });

  it("reports the best volume break, and nothing when only one quantity was quoted", () => {
    expect(volumeBreak(makeOffer({ priceBreaks: [{ qty: 1, price: 0.42 }] }))).toBeNull();
    expect(
      volumeBreak(
        makeOffer({
          priceBreaks: [
            { qty: 1, price: 0.42 },
            { qty: 100, price: 0.22 },
            { qty: 10, price: 0.31 },
          ],
        }),
      ),
    ).toEqual({ qty: 100, price: 0.22 });
  });
});

describe("a sourcing refresh", () => {
  const withOffers = makeDossier({
    distributorOffers: [makeOffer({ providerLabel: "DigiKey", stock: 512 })],
    supplySummary: { offerCount: 1, totalStock: 512 },
  });

  /** Render the section directly, so a rerender can put the exact wire state under test. */
  function renderOffers(offers: readonly DistributorOffer[], refreshing: boolean) {
    return provide(
      <OffersSection
        offers={offers}
        failures={[]}
        onRefresh={() => {}}
        onViewAll={() => {}}
        refreshing={refreshing}
      />,
    );
  }

  it("never empties the offers table while a refresh is running", () => {
    const offers = [makeOffer({ providerLabel: "DigiKey", stock: 512 })];
    const { rerenderWrapped } = renderOffers(offers, false);
    expect(screen.getByText("512")).toBeInTheDocument();

    // The projection momentarily reports nothing - a job that has cleared the old rows and not
    // yet written the new ones. On screen that is indistinguishable from "no distributor carries
    // this part", so the last numbers stand.
    rerenderWrapped(
      <OffersSection offers={[]} failures={[]} onRefresh={() => {}} onViewAll={() => {}} refreshing />,
    );
    expect(screen.getByText("512")).toBeInTheDocument();
    expect(screen.getByText("DigiKey")).toBeInTheDocument();
    expect(screen.queryByText(/No distributor has quoted/)).toBeNull();
  });

  it("accepts an empty answer once the refresh has finished", () => {
    const offers = [makeOffer({ providerLabel: "DigiKey", stock: 512 })];
    const { rerenderWrapped } = renderOffers(offers, false);
    rerenderWrapped(
      <OffersSection offers={[]} failures={[]} onRefresh={() => {}} onViewAll={() => {}} refreshing={false} />,
    );
    // A distributor genuinely dropping the part is a real answer and is not hidden behind the
    // rule that protects a refresh in flight.
    expect(screen.getByText(/No distributor has quoted/)).toBeInTheDocument();
  });

  it("states that it is refreshing without letting go of the numbers", async () => {
    // A submit that never settles, so the control stays in its running state for the assertion.
    mockApi.refreshSourcing.mockReturnValue(new Promise(() => {}) as never);
    const { user } = await open(withOffers);
    await user.click(screen.getByRole("button", { name: "Refresh Offers" }));

    const control = await screen.findByRole("button", { name: /Refreshing/ });
    expect(control).toHaveAttribute("aria-busy", "true");
    expect(control).toBeDisabled();
    // The table is untouched behind it.
    expect(within(region("component-browser.offers")).getByText("512")).toBeInTheDocument();
  });

  it("attaches a failure to the section, named, above the numbers it could not update", async () => {
    await open(
      makeDossier({
        distributorOffers: [makeOffer({ stock: 512, failureState: "not_configured" })],
        supplySummary: {
          offerCount: 1,
          totalStock: 512,
          failures: [
            { provider: "lcsc", providerLabel: "LCSC", state: "not_configured" },
          ],
        },
      }),
    );
    // The state decides the sentence; the state itself is never pasted into one.
    expect(region("component-browser.offer-failures")).toHaveTextContent(
      "LCSC is not connected on this machine",
    );
    expect(region("component-browser.offer-failures")).not.toHaveTextContent("not_configured");
    expect(within(region("component-browser.offers")).getByText("512")).toBeInTheDocument();
  });
});

describe("the documents section", () => {
  it("leads with the title and discloses tertiary file metadata", async () => {
    const { user } = await open(
      makeDossier({
        documents: {
          items: [
            makeDocument({
              title: "LM358 Dual Operational Amplifier",
              revision: "Rev H",
              localPath: "datasheets/lm358.pdf",
              sourceLabel: "Texas Instruments",
            }),
          ],
          count: 1,
        },
      }),
    );
    const row = region("component-browser.document-row");
    const title = within(row).getByText("LM358 Dual Operational Amplifier");
    expect(title).toHaveClass("ui-row-secondary");
    // The filename is a fact about our disk, not about the part. It stays, one tier down.
    expect(within(row).getByText(/lm358\.pdf/)).not.toBeVisible();
    await user.click(within(row).getByText("Document Details"));
    expect(within(row).getByText(/lm358\.pdf/)).toBeVisible();
    expect(within(row).getByText(/lm358\.pdf/)).toHaveClass("ui-component-metadata");
    expect(within(row).getByText(/Rev H/)).toBeVisible();
  });

  it("never uses a raw URL as a document's name", async () => {
    await open(
      makeDossier({
        documents: {
          items: [
            makeDocument({
              documentType: "package_drawing",
              documentTypeLabel: "Package Drawing",
              title: "SOIC-8 Package Drawing",
              localPath: "",
              remoteUrl: "https://ti.example.invalid/lit/ml/mpso002a/mpso002a.pdf",
            }),
          ],
          count: 1,
        },
      }),
    );
    const row = region("component-browser.document-row");
    expect(within(row).getByText("SOIC-8 Package Drawing")).toBeInTheDocument();
    expect(row.textContent).not.toContain("https://");
  });
});

describe("the related parts section", () => {
  it("states the reason and warning immediately, then discloses comparison evidence", async () => {
    const { user } = await open(
      makeDossier({
        relatedParts: [
          makeRelatedPart({
            mpn: "SN74AHC1G08DBVR",
            reason: "same_function_different_package",
            reasonLabel: "Same function, different package",
            evidence: [{ field: "package", ours: "sot23", theirs: "sc70" }],
          }),
        ],
      }),
    );
    const row = region("component-browser.related-row");
    expect(row.dataset.relatedValidated).toBe("false");
    expect(row).toHaveTextContent("Same function, different package");
    const evidence = region("component-browser.related-evidence");
    expect(evidence).toHaveTextContent("package: sot23 → sc70");
    expect(within(evidence).getByText("package: sot23 → sc70")).not.toBeVisible();
    expect(region("component-browser.related-not-validated")).toHaveTextContent(
      "Stockroom has not checked this for equivalence",
    );
    await user.click(within(row).getByText("Comparison Details"));
    expect(within(evidence).getByText("package: sot23 → sc70")).toBeVisible();
  });
});

describe("data provenance and timeline", () => {
  const historyDossier = makeDossier({
    provenance: {
      sources: [makeSourceLedgerEntry({ id: "mouser", label: "Mouser", fieldCount: 4 })],
      conflicts: [makeFieldConflict()],
      manualOverrides: [makeManualOverride()],
    },
    revisions: [
      makeRevisionEvent({
        kind: "imported",
        kindLabel: "Imported",
        summary: "Imported from Ultra Librarian",
      }),
      makeRevisionEvent({
        kind: "manual_override",
        kindLabel: "Field Overridden",
        summary: "tolerance set by owner",
      }),
    ],
  });

  it("reports a disagreement as a field with named answers, not as a state on a key", async () => {
    await open(historyDossier);
    const conflicts = region("component-browser.provenance-conflicts");
    expect(within(conflicts).getByText("Tolerance")).toBeInTheDocument();
    expect(within(conflicts).getByText("1 %")).toBeInTheDocument();
    expect(within(conflicts).getByText("0.5 %")).toBeInTheDocument();
    // Which one is actually deciding the value, so the reader is not left to guess.
    expect(within(conflicts).getByText("In force")).toBeInTheDocument();
    expect(conflicts.textContent).not.toContain("conflicting");
  });

  it("says what a reviewed decision displaced and who made it", async () => {
    await open(historyDossier);
    const overrides = region("component-browser.provenance-overrides");
    expect(within(overrides).getByText("0.5 %")).toBeInTheDocument();
    expect(overrides).toHaveTextContent("Replaced 1 % from Mouser");
    expect(overrides).toHaveTextContent("Reviewer owner");
  });

  it("separates how the data arrived from what has changed since", async () => {
    await open(historyDossier);
    expect(region("component-browser.provenance-intake")).toHaveTextContent(
      "Imported from Ultra Librarian",
    );
    expect(region("component-browser.provenance-revisions")).toHaveTextContent(
      "tolerance set by owner",
    );
    // Each event belongs to exactly one history: the projection decided which.
    expect(region("component-browser.provenance-intake")).not.toHaveTextContent(
      "tolerance set by owner",
    );
  });

  it("hides technical diagnostics until developer mode asks for them", async () => {
    const { user } = await open(historyDossier);
    expect(document.querySelector('[data-dev-id="component-browser.provenance-diagnostics"]'))
      .toBeNull();

    await user.keyboard("{Control>}{Shift>}D{/Shift}{/Control}");
    await waitFor(() =>
      expect(region("component-browser.provenance-diagnostics")).toBeInTheDocument(),
    );
  });
});

describe("the translation rule", () => {
  /**
   * A dossier carrying every shape that used to leak a storage word onto the screen: a source
   * that succeeded, a record a newer build wrote, keys this build does not model, and an empty
   * derivation identifier - which is what produced "Derived by unknown".
   */
  const leaky = makeDossier({
    distributorOffers: [makeOffer({ failureState: "failed" })],
    supplySummary: {
      offerCount: 1,
      totalStock: 512,
      failures: [{ provider: "digikey", providerLabel: "DigiKey", state: "failed" }],
    },
    documents: { items: [makeDocument()], count: 1 },
    relatedParts: [makeRelatedPart()],
    provenance: {
      sources: [
        makeSourceLedgerEntry({ id: "mouser", label: "Mouser", state: "success" }),
        makeSourceLedgerEntry({ id: "lcsc", label: "LCSC", state: "not_configured" }),
      ],
      conflicts: [makeFieldConflict()],
      manualOverrides: [makeManualOverride()],
      compatibility: {
        isFutureRecord: true,
        readOnlyFieldCount: 1,
        fields: [
          { key: "manufacturer_part_number_raw", label: "Manufacturer part number raw", origin: "record" },
        ],
        hasNotice: true,
      },
    },
    revisions: [makeRevisionEvent()],
    diagnostics: {
      recordSchemaVersion: 4,
      isFutureRecord: true,
      derivedBy: "",
      unknownKeys: ["projection_v4", "source_record_2"],
    },
  });

  it("lets none of the enumerated backend strings reach the normal reading path", async () => {
    await open(leaky);
    const text = region("component-browser.column-sourcing").textContent ?? "";
    const leaked = FORBIDDEN_IN_NORMAL_UI.filter((phrase) => text.includes(phrase));
    expect(leaked).toEqual([]);
  });

  it("translates a newer build's data into a warning that names the fields it is about", async () => {
    const { user } = await open(leaky);
    const notice = region("component-browser.compatibility-notice");
    expect(notice).toHaveTextContent(
      "1 of this component's fields came from a newer version of Stockroom and cannot be edited here",
    );
    // The count is what makes it actionable; the names are what make it checkable.
    expect(document.querySelector('[data-dev-id="component-browser.compatibility-field"]'))
      .toBeNull();
    await user.click(screen.getByRole("button", { name: "View Affected Fields" }));
    expect(region("component-browser.compatibility-field")).toHaveTextContent(
      "Manufacturer part number raw",
    );
  });

  it("names what happened to each source in words about the source", async () => {
    await open(leaky);
    const table = screen.getByRole("table", { name: "Data sources" });
    expect(
      within(within(table).getByText("Mouser").closest("tr")!).getByText("Supplied"),
    ).toBeInTheDocument();
    expect(
      within(within(table).getByText("LCSC").closest("tr")!).getByText("Not Connected"),
    ).toBeInTheDocument();
  });
});
