/**
 * Complete Component: the provider coverage matrix and the provider trip around it.
 *
 * The product rule under test is the one the owner stated: no cross-provider mixing. A person may
 * see every provider, see which ones can supply symbol + footprint + 3D model, reach any of them
 * in one click, and then use ONE provider's complete verified set. Nothing here may offer a
 * five-slot mix-and-match, and the last case in this file is the gate that keeps it that way.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { ApiError, api } from "../../api/client";
import { cadVariantApi } from "../../api/cadVariantClient";
import type {
  CadPreferenceScope,
  CadPreferenceView,
  ComponentDossier,
  ComponentProvidersView,
} from "../../api/dossierTypes";
import { WORKSPACE_PIECES, WORKSPACE_REGION } from "../../layout/workspacePieces";
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
  makeDossier,
  makeProviderRow,
} from "../../test/dossierFixture";
import { ComponentWorkspace } from "./ComponentWorkspace";

vi.mock("../../api/client", async (importActual) => {
  const actual = await importActual<typeof import("../../api/client")>();
  return {
    ...actual,
    api: {
      partDossier: vi.fn(),
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
      addPartFiles: vi.fn(),
      attachSelectedCaptureFiles: vi.fn(),
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

/**
 * What is in force, and what each choice would replace - as the backend already planned it.
 *
 * Ultra Librarian is the preferred set here, which is what makes the per-asset refusals real:
 * pinning SnapEDA to one artifact would leave two providers in force across the three, and the
 * backend says so with the reason the table has to show BEFORE the click.
 */
function preference(): CadPreferenceView {
  const allowed = (current = false): CadPreferenceScope => ({
    allowed: true,
    refusal: "",
    reason: "",
    changes: [],
    current,
  });
  const mixed = (): CadPreferenceScope => ({
    allowed: false,
    refusal: "mixed",
    reason:
      "Preferring SnapEDA for this asset would leave Ultra Librarian in force for the other assets.",
    changes: [],
    current: false,
  });
  const unsupplied = (): CadPreferenceScope => ({
    allowed: false,
    refusal: "unsupplied",
    reason: "TraceParts does not supply the Symbol for this component.",
    changes: [],
    current: false,
  });
  const source = { provider: "ultralibrarian", label: "Ultra Librarian", origin: "set_preference" as const };
  return {
    provider: "ultralibrarian",
    label: "Ultra Librarian",
    mixed: false,
    pinned: true,
    reviewedAt: "2026-08-05T00:00:00Z",
    assets: { symbol: source, footprint: source, model: source },
    assetLabels: { symbol: "Symbol", footprint: "Footprint", model: "3D Model" },
    options: [
      {
        provider: "ultralibrarian",
        label: "Ultra Librarian",
        coverage: { symbol: "validated", footprint: "downloaded", model: "available" },
        set: allowed(true),
        assets: { symbol: allowed(), footprint: allowed(), model: allowed() },
      },
      {
        provider: "snapeda",
        label: "SnapEDA",
        coverage: { symbol: "available", footprint: "not_available", model: "unknown" },
        set: {
          allowed: false,
          refusal: "unsupplied",
          reason: "SnapEDA does not supply the Footprint, 3D Model for this component.",
          changes: [],
          current: false,
        },
        assets: { symbol: mixed(), footprint: mixed(), model: mixed() },
      },
      {
        provider: "traceparts",
        label: "TraceParts",
        coverage: { symbol: "unknown", footprint: "unknown", model: "unknown" },
        set: unsupplied(),
        assets: { symbol: unsupplied(), footprint: unsupplied(), model: unsupplied() },
      },
      {
        provider: "digikey",
        label: "DigiKey",
        coverage: { symbol: "unknown", footprint: "unknown", model: "downloaded" },
        set: unsupplied(),
        assets: { symbol: unsupplied(), footprint: unsupplied(), model: mixed() },
      },
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
  const dossier: ComponentDossier = makeDossier({
    cadSourceCoverage: providers,
    cadAssets: { preference: preference() },
  });
  resetUiSessionForTests(openComponentInSession(defaultUiSession(), ID));
  mockApi.partDossier.mockResolvedValue(dossier);
  provide(<ComponentWorkspace componentId={ID} />);
  await screen.findByText(dossier.identity.mpn);
  return document.querySelector<HTMLElement>('[data-dev-id="component-browser.column-cad"]')!;
}

/**
 * Open the component, then the provider comparison, and hand back the dialog.
 *
 * The trip is reached from the CAD column's own Compare Sources control (and from Manage > Review
 * CAD Sources...), not from a header button: comparing providers is a CAD question and belongs in
 * the CAD column, not beside the part number.
 */
async function openSheet(
  providers: ComponentProvidersView = coverage(),
): Promise<{ dialog: HTMLElement; trigger: HTMLElement; user: ReturnType<typeof userEvent.setup> }> {
  const column = await open(providers);
  const user = userEvent.setup();
  const trigger = within(column).getByRole("button", { name: "Compare Sources" });
  await user.click(trigger);
  const dialog = await screen.findByRole("dialog", { name: "Review CAD Sources" });
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

  it("names the columns the person is choosing between, and no design tool", async () => {
    const { dialog } = await openSheet();
    const headers = within(dialog)
      .getByRole("table")
      .querySelectorAll("thead th");
    // The two per-tool count columns this replaces put KiCad and Altium in the middle of an
    // ordinary comparison, which made a coverage table read as a compatibility report. What a
    // person compares is availability, validation and source.
    expect(Array.from(headers).map((cell) => cell.textContent)).toEqual([
      "Provider",
      // The three asset columns run in the order the CAD modules beside this table are stacked -
      // 3D Model, Footprint, Symbol - which the matrix applies itself (`CAD_ASSET_KINDS`) rather
      // than inheriting from the payload, whose tuple is a storage ordering.
      "3D Model",
      "Footprint",
      "Symbol",
      "Validation",
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

  it("counts what each provider supplies, and separately what was actually checked", async () => {
    const { dialog } = await openSheet();
    // Ultra Librarian supplies all three and says so in a word; SnapEDA supplies one of three.
    expect(within(row(dialog, "ultralibrarian")).getByText("Complete Set")).toBeInTheDocument();
    expect(within(row(dialog, "snapeda")).getAllByText("1/3").length).toBeGreaterThan(0);
    expect(within(row(dialog, "traceparts")).getAllByText("0/3").length).toBeGreaterThan(0);
    // Validated is a different claim from supplied: a downloaded file nobody inspected must
    // never be counted as one that passed.
    expect(
      row(dialog, "ultralibrarian").querySelector("[data-validated]")?.getAttribute("data-validated"),
    ).toBe("1");
    expect(
      row(dialog, "traceparts").querySelector("[data-validated]")?.getAttribute("data-validated"),
    ).toBe("0");
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

  it("stops a second import while the host chooser is still up, then allows a retry", async () => {
    // The chooser is a HOST window: it is up until the person picks or cancels, and while it is up
    // this control must not be pressable again. The gate for that is the band's own state, which
    // the sheet around it cannot see - so it is asserted here on the rendered control.
    let releaseChooser: (paths: string[]) => void = () => {};
    const host = window as unknown as {
      __STOCKROOM_HOST__?: { pickFiles: () => Promise<string[]> };
    };
    host.__STOCKROOM_HOST__ = {
      pickFiles: () =>
        new Promise<string[]>((resolve) => {
          releaseChooser = resolve;
        }),
    };
    try {
      const { dialog, user } = await openSheet();
      const importControl = () =>
        within(dialog).getByRole("button", { name: "Import Downloaded Files" });
      expect(importControl()).toBeEnabled();

      await user.click(importControl());
      expect(importControl()).toBeDisabled();

      // Cancelling the chooser is an empty selection: nothing is sent anywhere, and the control
      // comes back rather than staying dead until the window is reopened.
      await act(async () => {
        releaseChooser([]);
      });
      await waitFor(() => expect(importControl()).toBeEnabled());
      expect(mockApi.addPartFiles).not.toHaveBeenCalled();
      expect(mockApi.attachSelectedCaptureFiles).not.toHaveBeenCalled();
    } finally {
      delete host.__STOCKROOM_HOST__;
    }
  });

  it("says honestly that no run has reported so far", async () => {
    const { dialog } = await openSheet();
    const report = dialog.querySelector<HTMLElement>(
      '[data-dev-id="component-browser.provider-report"]',
    )!;
    expect(
      within(report).getByText("No provider run has reported for this component so far."),
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
    // The subject here is the MODAL, which is not a placement - the overlay surfaces join the layout
    // system in plan Phase 7. The workspace frame's own clipping is asserted below as the thing the
    // modal opens over; the general form of that claim - any document, any content, no page scroll -
    // is `layout/engineInvariants.test.tsx`.
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

  it("is reached from the assets it is about, not from a control beside the part number", async () => {
    const column = await open();
    // The header carries identity and four actions; which provider can supply a coherent CAD set
    // is a CAD question, so its way in sits with the assets it is about.
    expect(within(column).getByRole("button", { name: "Compare Sources" })).toBeInTheDocument();
    const header = document.querySelector<HTMLElement>(
      '[data-dev-id="component-browser.header-actions"]',
    )!;
    expect(within(header).queryByRole("button", { name: /Complete Component/ })).toBeNull();
    // Reframed for Phase 2: "in the CAD column" is a fact about the ARRANGEMENT, so it is asserted
    // where the arrangement is stated - the piece that owns this control and the region it homes in
    // are the registry's and the document's answer, and `layout/defaultWorkspaceLayout.test.ts` holds
    // the shipped document to it. A committed redesign that moves the CAD title strip moves this
    // claim with it, which is why the assertion above no longer names the column.
    const owner = WORKSPACE_PIECES.find((manifest) =>
      manifest.devIds.includes("component-browser.compare-sources"),
    );
    expect(owner?.id).toBe("workspace.cad-title-strip");
    expect(owner?.actions).toContain("component-browser.compare-cad-sources");
    expect(owner?.home.regionId).toBe(WORKSPACE_REGION.cadColumn);
  });
});

describe("no cross-provider mixing", () => {
  it("offers no chooser that lists providers under one artifact", async () => {
    const { dialog } = await openSheet();
    const providerLabels = coverage().rows.map((entry) => entry.label);

    // Every SELECT in the sheet is a per-artifact ANSWER control, and none of its options is a
    // provider: a select listing providers under Symbol is exactly the mix-and-match this forbids.
    // The per-asset preference is a button whose availability the backend already decided, not a
    // menu of every provider offered under each column.
    const choosers = within(dialog).getAllByRole("combobox");
    for (const chooser of choosers) {
      const options = within(chooser)
        .getAllByRole("option")
        .map((option) => option.textContent ?? "");
      expect(options).toEqual(["Use Stockroom's Answer", "Available", "Not Available"]);
      for (const label of providerLabels) expect(options).not.toContain(label);
    }

    // And the wording keeps the rule in the person's language, positively stated. It says it
    // WITHOUT naming a design tool: this is ordinary provider comparison, and an EDA application
    // named here would make a compatibility report out of a question about who supplies the files.
    expect(
      within(dialog).getByText(
        /Stockroom never combines files from two downloads and never activates part of a set on its own/,
      ),
    ).toBeInTheDocument();
    // The comparison itself names no design tool. It answers "who supplies the files", and the
    // two per-tool count columns this replaced turned that question into a compatibility report.
    // Scoped to the matrix on purpose: the same-download PAIR selector below it does name the two
    // library formats, because there the distinction is the subject rather than an intrusion.
    const matrix = within(dialog).getByRole("table");
    expect(matrix.textContent ?? "").not.toMatch(/KiCad|Altium|Eagle|OrCAD|EasyEDA/);
  });

  it("refuses a per-asset source the backend says would mix two providers, before the click", async () => {
    const { dialog } = await openSheet();
    const pin = within(row(dialog, "snapeda")).getAllByRole("button", {
      name: /Prefer This Source/,
    })[0];
    // Disabled, and carrying the reason - so the refusal is readable before the click rather
    // than arriving as an error after it.
    expect(pin).toBeDisabled();
    expect(pin.getAttribute("title")).toMatch(/Ultra Librarian/);
  });
});
