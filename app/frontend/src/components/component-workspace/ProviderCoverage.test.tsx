/**
 * Complete Component: the provider coverage matrix and the provider trip around it.
 *
 * The product rule under test is the one the owner stated: no cross-provider mixing. A person may
 * see every provider, see which ones can supply symbol + footprint + 3D model, reach any of them
 * in one click, and then use ONE provider's complete verified set. Nothing here may offer a
 * five-slot mix-and-match, and the last case in this file is the gate that keeps it that way.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { ApiError, api } from "../../api/client";
import { cadVariantApi } from "../../api/cadVariantClient";
import type {
  ComponentProvidersView,
  ComponentWorkspaceResponse,
} from "../../api/workspaceTypes";
import { CaptureProvider } from "../../lib/capture";
import { componentProviderDevId, devIdSelector } from "../../lib/componentDevIds";
import { ThemeProvider } from "../../lib/theme";
import { ToastProvider } from "../../lib/toast";
import {
  defaultUiSession,
  openComponentInSession,
  resetUiSessionForTests,
} from "../../lib/uiSession";
import {
  makeCoverageCell,
  makeProviderRow,
  makeWorkspace,
} from "../../test/workspaceFixture";
import { ComponentWorkspace } from "./ComponentWorkspace";

vi.mock("../../api/client", async (importActual) => {
  const actual = await importActual<typeof import("../../api/client")>();
  return {
    ...actual,
    api: {
      partWorkspace: vi.fn(),
      partHistory: vi.fn(),
      partDetail: vi.fn(),
      partCadSource: vi.fn(),
      setPartProviderCoverage: vi.fn(),
      facets: vi.fn(),
      previewSvg: vi.fn(),
      modelGlb: vi.fn(),
      landPattern: vi.fn(),
      runCapture: vi.fn(),
      showCaptureProvider: vi.fn(),
      captureWorkflow: vi.fn(),
      workflowEvents: vi.fn(),
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

/**
 * The shape the backend sends, with the four rows every case below reads.
 *
 * Deliberately NOT in registry order: rows arrive ranked by evidence and the matrix must render
 * them exactly as given. Reordering them here is what proves the renderer never re-sorts.
 */
function coverage(): ComponentProvidersView {
  return {
    artifacts: ["symbol", "footprint", "model"],
    statuses: ["unknown", "available", "not_available", "downloaded", "validated"],
    tools: ["kicad", "altium"],
    completeProviders: ["ultralibrarian"],
    rows: [
      makeProviderRow({
        id: "ultralibrarian",
        label: "Ultra Librarian",
        order: 20,
        symbol: makeCoverageCell({ status: "validated", origin: "validator" }),
        footprint: makeCoverageCell({ status: "downloaded", origin: "native_download" }),
        model: makeCoverageCell({ status: "available", origin: "official_api" }),
      }),
      makeProviderRow({
        id: "snapeda",
        label: "SnapEDA",
        order: 10,
        symbol: makeCoverageCell({ status: "available", origin: "official_api" }),
        footprint: makeCoverageCell({ status: "not_available", origin: "official_api" }),
        model: makeCoverageCell({ status: "unknown" }),
      }),
      // No page is on record and the registry has no measured search surface for it, so there is
      // no honest link at all. The row must still exist.
      makeProviderRow({
        id: "traceparts",
        label: "TraceParts",
        order: 40,
        url: "",
        urlKind: "",
        needsLogin: false,
        aggregator: false,
      }),
      // A person said the model is not there; Stockroom holds the file, so its evidence stands.
      makeProviderRow({
        id: "digikey",
        label: "DigiKey",
        order: 30,
        distributor: true,
        aggregator: false,
        needsLogin: false,
        symbol: makeCoverageCell({ status: "unknown" }),
        footprint: makeCoverageCell({ status: "unknown" }),
        model: makeCoverageCell({
          status: "downloaded",
          origin: "native_download",
          userAssertion: {
            status: "not_available",
            origin: "user",
            notedAt: "2026-08-01T00:00:00Z",
            note: "",
            applied: false,
          },
        }),
      }),
    ],
  };
}

beforeEach(() => {
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
  mockApi.partCadSource.mockResolvedValue({
    mpn: "LM358DR",
    needs: ["kicad_symbol", "kicad_model"],
    completion_evidence: null,
    sources: [],
    url: null,
    vendor: "",
  });
  mockCadVariantApi.inventory.mockResolvedValue({
    partId: ID,
    inventories: [],
    pairs: [],
    supplementary: [],
  });
});

function provide(ui: ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <ThemeProvider>
        <ToastProvider>
          <CaptureProvider>{ui}</CaptureProvider>
        </ToastProvider>
      </ThemeProvider>
    </QueryClientProvider>,
  );
}

async function open(
  providers: ComponentProvidersView = coverage(),
): Promise<HTMLElement> {
  const workspace: ComponentWorkspaceResponse = makeWorkspace({ providers });
  resetUiSessionForTests(openComponentInSession(defaultUiSession(), ID));
  mockApi.partWorkspace.mockResolvedValue(workspace);
  provide(<ComponentWorkspace componentId={ID} />);
  await screen.findByRole("heading", { name: workspace.identity.displayName });
  return document.querySelector<HTMLElement>('[data-dev-id="component-browser.header"]')!;
}

/** Open the component, then the Complete Component modal, and hand back the dialog. */
async function openSheet(
  providers: ComponentProvidersView = coverage(),
): Promise<{ dialog: HTMLElement; trigger: HTMLElement; user: ReturnType<typeof userEvent.setup> }> {
  const header = await open(providers);
  const user = userEvent.setup();
  const trigger = within(header).getByRole("button", { name: /Complete Component/ });
  await user.click(trigger);
  const dialog = await screen.findByRole("dialog", { name: "Complete Component" });
  return { dialog, trigger, user };
}

function row(dialog: HTMLElement, providerId: string): HTMLElement {
  return dialog.querySelector<HTMLElement>(devIdSelector(componentProviderDevId(ID, providerId)))!;
}

describe("provider coverage matrix", () => {
  it("renders every provider row in the order the backend ranked them", async () => {
    const { dialog } = await openSheet();
    const matrix = within(dialog).getByRole("table");
    const ids = Array.from(
      matrix.querySelectorAll<HTMLElement>("tbody tr[data-provider]"),
    ).map((element) => element.dataset.provider);
    // The fixture's `order` field ascends 20, 10, 40, 30: rendering it sorted would rearrange this.
    expect(ids).toEqual(["ultralibrarian", "snapeda", "traceparts", "digikey"]);
  });

  it("names the seven columns the person is choosing between", async () => {
    const { dialog } = await openSheet();
    const headers = within(dialog)
      .getByRole("table")
      .querySelectorAll("thead th");
    expect(Array.from(headers).map((cell) => cell.textContent)).toEqual([
      "Provider",
      "Symbol",
      "Footprint",
      "3D Model",
      "KiCad",
      "Altium",
      "Action",
    ]);
  });

  it("makes the provider that can supply everything obvious in words, not only in colour", async () => {
    const { dialog } = await openSheet();
    const complete = row(dialog, "ultralibrarian");
    expect(complete.dataset.complete).toBe("true");
    expect(within(complete).getByText("Complete Set")).toBeInTheDocument();
    // Nothing else claims it, and the claim is not a colour a person may not be able to see.
    expect(row(dialog, "snapeda").dataset.complete).toBe("false");
    expect(within(dialog).getAllByText("Complete Set")).toHaveLength(1);
  });

  it("renders each tool's own count out of three, from 0/3 to 3/3", async () => {
    const { dialog } = await openSheet();
    // Ultra Librarian supplies all three; SnapEDA one; TraceParts none.
    expect(within(row(dialog, "ultralibrarian")).getAllByText("3/3").length).toBeGreaterThan(0);
    expect(within(row(dialog, "snapeda")).getAllByText("1/3").length).toBeGreaterThan(0);
    expect(within(row(dialog, "traceparts")).getAllByText("0/3").length).toBeGreaterThan(0);
  });

  it("renders every one of the five statuses under its own label", async () => {
    const { dialog } = await openSheet();
    expect(within(row(dialog, "ultralibrarian")).getByText("Validated")).toBeInTheDocument();
    expect(within(row(dialog, "ultralibrarian")).getByText("Downloaded")).toBeInTheDocument();
    // "Available" also names an OPTION in the answer control, so scope it to the status span.
    expect(
      row(dialog, "ultralibrarian").querySelector('[data-status="available"]')?.textContent,
    ).toBe("Available");
    expect(
      row(dialog, "snapeda").querySelector('[data-status="not_available"]')?.textContent,
    ).toBe("Not Available");
    expect(
      row(dialog, "snapeda").querySelector('[data-status="unknown"]')?.textContent,
    ).toBe("Unknown");
  });

  it("says a provider has no page rather than inventing one", async () => {
    const { dialog } = await openSheet();
    const traceparts = row(dialog, "traceparts");
    const openProvider = within(traceparts).getByRole("button", {
      name: "Open Provider: TraceParts",
    });
    expect(openProvider).toBeDisabled();
    expect(
      within(traceparts).getAllByText(
        "No page is on record for this provider and this component.",
      ).length,
    ).toBeGreaterThan(0);
    // Nothing in the row is a link: a fabricated href is exactly the failure this guards.
    expect(traceparts.querySelectorAll("a")).toHaveLength(0);
  });

  it("opens a reachable provider through the one capture store", async () => {
    mockApi.runCapture.mockResolvedValue({
      workflow_batch_id: "batch-1",
      workflow_item_id: "item-1",
      event_cursor: 0,
    });
    mockApi.workflowEvents.mockResolvedValue({
      batch: { id: "batch-1", kind: "guided_capture", status: "running" },
      events: [],
      cursor: { next_sequence: 1, has_more: false },
    } as never);
    mockApi.captureWorkflow.mockResolvedValue({
      workflow_batch_id: "batch-1",
      workflow_item_id: "item-1",
      part_id: ID,
      initial_needs: ["kicad_symbol"],
      vendor: "ultralibrarian",
      active_route: null,
      report: null,
    } as never);
    const { dialog, user } = await openSheet();

    await user.click(
      within(row(dialog, "ultralibrarian")).getByRole("button", {
        name: "Open Provider: Ultra Librarian",
      }),
    );

    await waitFor(() =>
      expect(mockApi.runCapture).toHaveBeenCalledWith(
        expect.objectContaining({ partIds: [ID], vendor: "ultralibrarian" }),
      ),
    );
  });
});

describe("what a person may correct", () => {
  it("offers only Available, Not Available, and withdrawing the answer", async () => {
    const { dialog } = await openSheet();
    const control = within(row(dialog, "snapeda")).getByRole("combobox", {
      name: "Your Answer: SnapEDA Symbol",
    });
    expect(
      within(control).getAllByRole("option").map((option) => option.textContent),
    ).toEqual(["Use Stockroom's Answer", "Available", "Not Available"]);
    // Downloaded and Validated are claims about bytes Stockroom holds; the backend answers 422,
    // so a control that could only produce one is never rendered.
    expect(within(control).queryByRole("option", { name: "Downloaded" })).toBeNull();
    expect(within(control).queryByRole("option", { name: "Validated" })).toBeNull();
  });

  it("posts the correction for exactly that provider and artifact", async () => {
    const next = coverage();
    mockApi.setPartProviderCoverage.mockResolvedValue(next);
    const { dialog, user } = await openSheet();

    await user.selectOptions(
      within(row(dialog, "snapeda")).getByRole("combobox", {
        name: "Your Answer: SnapEDA 3D Model",
      }),
      "not_available",
    );

    await waitFor(() =>
      expect(mockApi.setPartProviderCoverage).toHaveBeenCalledWith(ID, {
        provider: "snapeda",
        artifact: "model",
        status: "not_available",
      }),
    );
  });

  it("withdraws an answer with an empty status rather than a third opinion", async () => {
    mockApi.setPartProviderCoverage.mockResolvedValue(coverage());
    const { dialog, user } = await openSheet();

    await user.selectOptions(
      within(row(dialog, "digikey")).getByRole("combobox", {
        name: "Your Answer: DigiKey 3D Model",
      }),
      "",
    );

    await waitFor(() =>
      expect(mockApi.setPartProviderCoverage).toHaveBeenCalledWith(ID, {
        provider: "digikey",
        artifact: "model",
        status: "",
      }),
    );
  });

  it("shows Stockroom's own evidence winning, and why, when a correction was not applied", async () => {
    const { dialog } = await openSheet();
    const digikey = row(dialog, "digikey");
    const overruled = digikey.querySelector<HTMLElement>('[data-overruled="true"]')!;
    expect(overruled).toBeInTheDocument();
    expect(overruled.textContent).toContain("Stockroom holds a file for this artifact");
    // The reason is the status that outranked it, named rather than implied.
    expect(overruled.textContent).toContain("Downloaded");
    // The person's answer is still shown as theirs, not silently discarded.
    expect(
      within(digikey).getByRole("combobox", { name: "Your Answer: DigiKey 3D Model" }),
    ).toHaveValue("not_available");
    // A correction that WAS applied says nothing of the sort.
    expect(row(dialog, "snapeda").querySelector('[data-overruled="true"]')).toBeNull();
  });
});

describe("the provider trip", () => {
  it("states the component, the provider, and what the provider page is doing", async () => {
    const { dialog } = await openSheet();
    const trip = dialog.querySelector<HTMLElement>(
      '[data-dev-id="component-browser.provider-browser"]',
    )!;
    expect(within(trip).getByText("LM358")).toBeInTheDocument();
    expect(within(trip).getByText("LM358DR")).toBeInTheDocument();
    expect(within(trip).getByText("None open")).toBeInTheDocument();
    expect(within(trip).getByText("Not open")).toBeInTheDocument();
    // Nothing is running, so neither the page control nor the way back is offered.
    expect(within(trip).getByRole("button", { name: "Show Provider Page" })).toBeDisabled();
    expect(within(trip).getByRole("button", { name: "Return To Stockroom" })).toBeDisabled();
  });

  it("lists what is still needed for this component", async () => {
    const { dialog } = await openSheet();
    const progress = dialog.querySelector<HTMLElement>(
      '[data-dev-id="component-browser.provider-progress"]',
    )!;
    expect(within(progress).getByText("KiCad Symbol")).toBeInTheDocument();
    expect(within(progress).getByText("3D Model")).toBeInTheDocument();
    expect(within(progress).getByText("0/2")).toBeInTheDocument();
    expect(within(progress).getAllByText("Needed")).toHaveLength(2);
  });

  it("says honestly that no run has reported yet", async () => {
    const { dialog } = await openSheet();
    const report = dialog.querySelector<HTMLElement>(
      '[data-dev-id="component-browser.provider-report"]',
    )!;
    expect(
      within(report).getByText("No provider run has reported for this component yet."),
    ).toBeInTheDocument();
  });

  it("reaches the retained-set chooser, which is the one place a set is put in force", async () => {
    const { dialog } = await openSheet();
    const sets = dialog.querySelector<HTMLElement>(
      '[data-dev-id="component-browser.provider-sets"]',
    )!;
    expect(sets).toBeInTheDocument();
    await waitFor(() => expect(mockCadVariantApi.inventory).toHaveBeenCalledWith(ID));
    expect(
      within(sets).getByText(/One verified set per provider/),
    ).toBeInTheDocument();
  });
});

describe("the modal contract", () => {
  it("opens from the header, traps Tab, closes on Escape, and gives focus back", async () => {
    const { dialog, trigger, user } = await openSheet();
    // Focus moved into the dialog on open.
    expect(dialog.contains(document.activeElement)).toBe(true);

    const focusable = Array.from(
      dialog.querySelectorAll<HTMLElement>(
        'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])',
      ),
    );
    expect(focusable.length).toBeGreaterThan(1);
    focusable[focusable.length - 1].focus();
    await user.tab();
    // Tab off the last control wraps to the first: focus never escapes onto inert background.
    expect(dialog.contains(document.activeElement)).toBe(true);

    await user.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(document.activeElement).toBe(trigger);
  });

  it("keeps the workspace itself unscrollable: only the modal and the wide table scroll", async () => {
    const { dialog } = await openSheet();
    const root = document.querySelector<HTMLElement>('[data-dev-id="component-browser.root"]')!;
    expect(root.className).toContain("h-full");
    expect(root.className).toContain("min-h-0");
    expect(root.className).toContain("overflow-hidden");
    // The modal body is the one surface allowed a vertical scrollbar...
    const scroller = dialog.querySelector<HTMLElement>(".overflow-y-auto")!;
    expect(scroller).toBeInTheDocument();
    // ...and the seven-column table scrolls sideways inside its own box rather than widening it.
    const matrix = dialog.querySelector<HTMLElement>(
      '[data-dev-id="component-browser.provider-matrix"]',
    )!;
    expect(matrix.className).toContain("overflow-x-auto");
    // No scrollable card inside a scrollable card.
    expect(matrix.closest(".overflow-y-auto")).toBe(scroller);
    expect(matrix.querySelectorAll(".overflow-y-auto")).toHaveLength(0);
  });

  it("summarises coverage on the header control that opens it", async () => {
    const header = await open();
    const trigger = within(header).getByRole("button", { name: /Complete Component/ });
    // One of four providers can supply the whole set. Two numbers, because "1" alone would not
    // say whether there is anywhere else to look.
    expect(trigger.textContent).toContain("1/4");
  });
});

describe("no cross-provider mixing", () => {
  it("offers no control that assembles one component from several providers", async () => {
    const { dialog } = await openSheet();
    const providerLabels = coverage().rows.map((entry) => entry.label);

    // Every chooser in the sheet is a per-artifact ANSWER control, and none of its options is a
    // provider: a select listing providers under Symbol is exactly the mix-and-match this forbids.
    const choosers = within(dialog).getAllByRole("combobox");
    for (const chooser of choosers) {
      const options = within(chooser)
        .getAllByRole("option")
        .map((option) => option.textContent ?? "");
      expect(options).toEqual(["Use Stockroom's Answer", "Available", "Not Available"]);
      for (const label of providerLabels) expect(options).not.toContain(label);
    }

    // And the wording keeps the rule in the person's language, positively stated.
    expect(
      within(dialog).getByText(
        /Stockroom never combines files from two downloads and never activates one design tool alone/,
      ),
    ).toBeInTheDocument();
  });
});
