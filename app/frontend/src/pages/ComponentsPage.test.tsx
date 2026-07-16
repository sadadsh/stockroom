import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { ApiError } from "../api/client";
import { api } from "../api/client";
import type { PartDetail, PartSummary } from "../api/types";
import { ToastProvider } from "../lib/toast";
import { RouterProvider } from "../lib/router";
import { AddPartProvider, useAddPart } from "../lib/addPart";
import { requestPart } from "../lib/partSelection";
import { ComponentsPage } from "./ComponentsPage";

// Mock the typed client so the page renders against fixtures, not a live server.
// ApiError is preserved (the page branches on it for the error surface).
vi.mock("../api/client", async (importActual) => {
  const actual = await importActual<typeof import("../api/client")>();
  return {
    ...actual,
    api: {
      listParts: vi.fn(),
      facets: vi.fn(),
      partDetail: vi.fn(),
      editField: vi.fn(),
      moveCategory: vi.fn(),
      deletePart: vi.fn(),
      enrichPart: vi.fn(),
      setSpecs: vi.fn(),
      getDuplicates: vi.fn(),
    },
  };
});

const mockApi = vi.mocked(api);

// Default: no duplicates. Individual tests override to exercise the badge + filter.
beforeEach(() => {
  mockApi.getDuplicates.mockResolvedValue({ by_mpn: [], by_footprint: [] });
});

const SUMMARY: PartSummary = {
  id: "lm358",
  display_name: "LM358",
  category: "ICs",
  mpn: "LM358DR",
  manufacturer: "Texas Instruments",
  is_complete: true,
  missing: [],
};

const DETAIL: PartDetail = {
  id: "lm358",
  display_name: "LM358",
  category: "ICs",
  description: "Dual Operational Amplifier",
  tags: ["op-amp"],
  mpn: "LM358DR",
  manufacturer: "Texas Instruments",
  datasheet: null,
  purchase: [],
  symbol: null,
  footprint: null,
  model: null,
  provenance: null,
  hashes: null,
  enrichment: {},
  specs: {},
};

function wrap(ui: ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const state = { addPartOpen: false };
  function Probe() {
    state.addPartOpen = useAddPart().isOpen;
    return null;
  }
  const utils = render(
    <QueryClientProvider client={qc}>
      <ToastProvider>
        <RouterProvider initial="components">
          <AddPartProvider>
            <Probe />
            {ui}
          </AddPartProvider>
        </RouterProvider>
      </ToastProvider>
    </QueryClientProvider>,
  );
  return { ...utils, state };
}

describe("ComponentsPage", () => {
  it("lists parts, shows the count, and auto-selects the first part's detail", async () => {
    mockApi.listParts.mockResolvedValue({ parts: [SUMMARY], count: 1 });
    mockApi.facets.mockResolvedValue({
      by_category: { ICs: 1 },
      by_manufacturer: { "Texas Instruments": 1 },
      complete: 1,
      incomplete: 0,
    });
    mockApi.partDetail.mockResolvedValue(DETAIL);

    wrap(<ComponentsPage />);

    expect(await screen.findByText("LM358")).toBeInTheDocument();
    expect(await screen.findByText("1 Parts")).toBeInTheDocument();
    // The detail panel is the only surface that renders the description.
    expect(await screen.findByText("Dual Operational Amplifier")).toBeInTheDocument();
  });

  it("badges MPN duplicates and the Duplicates filter narrows to just them (D2)", async () => {
    const dupA: PartSummary = { id: "a", display_name: "Cap A", category: "Passives", mpn: "C1", manufacturer: "X", is_complete: true, missing: [] };
    const dupB: PartSummary = { id: "b", display_name: "Cap B", category: "Passives", mpn: "C1", manufacturer: "Y", is_complete: true, missing: [] };
    const solo: PartSummary = { id: "s", display_name: "Solo Part", category: "Passives", mpn: "S1", manufacturer: "Z", is_complete: true, missing: [] };
    mockApi.listParts.mockResolvedValue({ parts: [dupA, dupB, solo], count: 3 });
    mockApi.facets.mockResolvedValue({ by_category: { Passives: 3 }, by_manufacturer: {}, complete: 3, incomplete: 0 });
    mockApi.partDetail.mockResolvedValue(DETAIL);
    // A real accidental duplicate: two parts under one MPN. Shared footprints are ignored.
    mockApi.getDuplicates.mockResolvedValue({ by_mpn: [{ key: "C1", parts: [dupA, dupB] }], by_footprint: [] });

    wrap(<ComponentsPage />);
    expect(await screen.findByText("Solo Part")).toBeInTheDocument();
    // Both duplicate members carry a badge; the solo part does not.
    await waitFor(() => expect(screen.getAllByText("Duplicate")).toHaveLength(2));

    // The Duplicates filter (behind the Filters popover) narrows to just the members.
    await userEvent.click(screen.getByRole("button", { name: "Filters" }));
    await userEvent.click(screen.getByText(/Duplicates \(2\)/));
    expect(screen.queryByText("Solo Part")).toBeNull();
    expect(screen.getByText("Cap A")).toBeInTheDocument();
    expect(screen.getByText("Cap B")).toBeInTheDocument();
  });

  it("opens the Add A Part modal from the Add Parts toolbar button", async () => {
    mockApi.listParts.mockResolvedValue({ parts: [SUMMARY], count: 1 });
    mockApi.facets.mockResolvedValue({
      by_category: { ICs: 1 },
      by_manufacturer: {},
      complete: 1,
      incomplete: 0,
    });
    mockApi.partDetail.mockResolvedValue(DETAIL);

    const { state } = wrap(<ComponentsPage />);
    const user = userEvent.setup();

    expect(state.addPartOpen).toBe(false);
    await user.click(await screen.findByRole("button", { name: "Add Parts" }));
    expect(state.addPartOpen).toBe(true);
  });

  it("edits an identity field inline and reports a toast", async () => {
    mockApi.listParts.mockResolvedValue({ parts: [SUMMARY], count: 1 });
    mockApi.facets.mockResolvedValue({
      by_category: { ICs: 1 },
      by_manufacturer: {},
      complete: 1,
      incomplete: 0,
    });
    mockApi.partDetail.mockResolvedValue(DETAIL);
    mockApi.editField.mockResolvedValue({ ...DETAIL, manufacturer: "TI Inc" });

    wrap(<ComponentsPage />);
    const user = userEvent.setup();

    const field = await screen.findByRole("button", { name: "Edit Manufacturer" });
    await user.click(field);
    const input = screen.getByLabelText("Manufacturer");
    await user.clear(input);
    await user.type(input, "TI Inc");
    await user.keyboard("{Enter}");

    expect(mockApi.editField).toHaveBeenCalledWith("lm358", "manufacturer", "TI Inc");
    expect(await screen.findByText("Saved")).toBeInTheDocument();
  });

  it("moves a part to another category through the select", async () => {
    mockApi.listParts.mockResolvedValue({ parts: [SUMMARY], count: 1 });
    mockApi.facets.mockResolvedValue({
      by_category: { ICs: 1, Passives: 3 },
      by_manufacturer: {},
      complete: 1,
      incomplete: 0,
    });
    mockApi.partDetail.mockResolvedValue(DETAIL);
    mockApi.moveCategory.mockResolvedValue({ ...DETAIL, category: "Passives" });

    wrap(<ComponentsPage />);
    const user = userEvent.setup();

    const select = await screen.findByLabelText("Category");
    await user.selectOptions(select, "Passives");

    expect(mockApi.moveCategory).toHaveBeenCalledWith("lm358", "Passives");
    expect(await screen.findByText("Moved to Passives")).toBeInTheDocument();
  });

  it("deletes a part only after an in-window confirm", async () => {
    mockApi.listParts.mockResolvedValue({ parts: [SUMMARY], count: 1 });
    mockApi.facets.mockResolvedValue({
      by_category: { ICs: 1 },
      by_manufacturer: {},
      complete: 1,
      incomplete: 0,
    });
    mockApi.partDetail.mockResolvedValue(DETAIL);
    mockApi.deletePart.mockResolvedValue(undefined);

    wrap(<ComponentsPage />);
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: "Delete Part" }));
    const dialog = await screen.findByRole("dialog");
    // Nothing deleted until the dialog's own confirm is clicked.
    expect(mockApi.deletePart).not.toHaveBeenCalled();
    await user.click(within(dialog).getByRole("button", { name: "Delete" }));

    expect(mockApi.deletePart).toHaveBeenCalledWith("lm358");
    expect(await screen.findByText("Part deleted")).toBeInTheDocument();
  });

  it("does not re-fetch the just-deleted part off the retained list mid-refetch", async () => {
    // Hold the post-delete list refetch open so the window where TanStack still
    // serves the previous (retained) list is observable. During that window the
    // deleted part must not be re-selected or re-fetched (it would 404).
    let resolveRefetch!: (v: { parts: PartSummary[]; count: number }) => void;
    mockApi.listParts
      .mockResolvedValueOnce({ parts: [SUMMARY], count: 1 })
      .mockImplementationOnce(
        () =>
          new Promise<{ parts: PartSummary[]; count: number }>((res) => {
            resolveRefetch = res;
          }),
      );
    mockApi.facets.mockResolvedValue({
      by_category: { ICs: 1 },
      by_manufacturer: {},
      complete: 1,
      incomplete: 0,
    });
    mockApi.partDetail.mockResolvedValue(DETAIL);
    mockApi.deletePart.mockResolvedValue(undefined);

    wrap(<ComponentsPage />);
    const user = userEvent.setup();

    await screen.findByText("Dual Operational Amplifier");
    expect(mockApi.partDetail).toHaveBeenCalledTimes(1);

    await user.click(await screen.findByRole("button", { name: "Delete Part" }));
    await user.click(
      within(await screen.findByRole("dialog")).getByRole("button", { name: "Delete" }),
    );

    // Delete succeeded; the refetch is in flight and the old list is retained.
    await screen.findByText("Part deleted");
    expect(mockApi.partDetail).toHaveBeenCalledTimes(1); // not re-fetched off the stale list

    // Resolve the refetch to an empty library: the honest empty state shows and
    // still nothing re-fetches the deleted part.
    await act(async () => {
      resolveRefetch({ parts: [], count: 0 });
    });
    expect(await screen.findByText("No Components Yet")).toBeInTheDocument();
    expect(mockApi.partDetail).toHaveBeenCalledTimes(1);
  });

  it("enriches a part from its MPN and applies a sourced field through editField", async () => {
    mockApi.listParts.mockResolvedValue({ parts: [SUMMARY], count: 1 });
    mockApi.facets.mockResolvedValue({
      by_category: { ICs: 1 },
      by_manufacturer: {},
      complete: 1,
      incomplete: 0,
    });
    // The record has no manufacturer, so the sourced value is applyable.
    mockApi.partDetail.mockResolvedValue({ ...DETAIL, manufacturer: "" });
    mockApi.enrichPart.mockResolvedValue({
      category: "ICs",
      mpn: null,
      manufacturer: { value: "Analog Devices", source: "jsonld", confidence: "high" },
      description: null,
      datasheet_url: null,
      stock: null,
      package: null,
      price_breaks: [],
      specs: {},
      schema_version: 1,
    });
    mockApi.editField.mockResolvedValue(DETAIL);

    wrap(<ComponentsPage />);
    const user = userEvent.setup();

    await user.click(
      await screen.findByRole("button", { name: "Enrich From Distributor" }),
    );
    expect(mockApi.enrichPart).toHaveBeenCalledWith("LM358DR", "ICs", undefined);

    const row = (await screen.findByText("Analog Devices")).closest("div")!;
    await user.click(within(row).getByRole("button", { name: "Apply" }));

    expect(mockApi.editField).toHaveBeenCalledWith("lm358", "manufacturer", "Analog Devices");
    expect(await screen.findByText("Saved")).toBeInTheDocument();
  });

  it("shows Already Set (no Apply) when the record already holds the enriched value", async () => {
    // Drives the real DetailPanel -> EnrichPanel `current` wire end to end: if that
    // wire stops feeding the record's own manufacturer/description into the gate,
    // Apply is wrongly offered for a value already on the record. The record here
    // already holds the manufacturer the lookup returns, so the row must read
    // "Already Set" and offer no Apply.
    mockApi.listParts.mockResolvedValue({ parts: [SUMMARY], count: 1 });
    mockApi.facets.mockResolvedValue({
      by_category: { ICs: 1 },
      by_manufacturer: {},
      complete: 1,
      incomplete: 0,
    });
    mockApi.partDetail.mockResolvedValue({ ...DETAIL, manufacturer: "Analog Devices" });
    mockApi.enrichPart.mockResolvedValue({
      category: "ICs",
      mpn: null,
      manufacturer: { value: "Analog Devices", source: "jsonld", confidence: "high" },
      description: null,
      datasheet_url: null,
      stock: null,
      package: null,
      price_breaks: [],
      specs: {},
      schema_version: 1,
    });

    wrap(<ComponentsPage />);
    const user = userEvent.setup();

    await user.click(
      await screen.findByRole("button", { name: "Enrich From Distributor" }),
    );

    expect(await screen.findByText("Already Set")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Apply" })).not.toBeInTheDocument();
  });

  it("applies an enriched pinout through the specs seam and reports a toast", async () => {
    // Drives the whole ComponentsPage -> DetailPanel -> EnrichPanel -> handleApplyPinout
    // -> setSpecs wire. If any link breaks (a dropped onApplyPinout prop), the Apply
    // Pinout button never reaches setSpecs and this goes RED. The record has no pinout
    // yet, so Apply Pinout is offered (not "Already Set").
    const pins = [
      { pin: "1", name: "OUT1" },
      { pin: "2", name: "IN1-" },
    ];
    mockApi.listParts.mockResolvedValue({ parts: [SUMMARY], count: 1 });
    mockApi.facets.mockResolvedValue({
      by_category: { ICs: 1 },
      by_manufacturer: {},
      complete: 1,
      incomplete: 0,
    });
    mockApi.partDetail.mockResolvedValue(DETAIL);
    mockApi.enrichPart.mockResolvedValue({
      category: "ICs",
      mpn: null,
      manufacturer: null,
      description: null,
      datasheet_url: null,
      stock: null,
      package: null,
      price_breaks: [],
      specs: { pinout: { value: pins, source: "datasheet", confidence: "high" } },
      schema_version: 1,
    });
    mockApi.setSpecs.mockResolvedValue({ ...DETAIL, specs: { pinout: pins } });

    wrap(<ComponentsPage />);
    const user = userEvent.setup();

    await user.click(
      await screen.findByRole("button", { name: "Enrich From Distributor" }),
    );
    await user.click(await screen.findByRole("button", { name: "Apply Pinout" }));

    expect(mockApi.setSpecs).toHaveBeenCalledWith(
      "lm358",
      { pinout: { value: pins, source: "datasheet", confidence: "high" } },
      undefined,
    );
    expect(await screen.findByText("Pinout saved")).toBeInTheDocument();
  });

  it("consumes a palette part request: clears filters and selects that part even when a search hid it", async () => {
    const R10K: PartSummary = {
      id: "r10k",
      display_name: "R 10k",
      category: "Passives",
      mpn: "RC0402-10K",
      manufacturer: "Yageo",
      is_complete: true,
      missing: [],
    };
    // listParts honors the q filter so a search can hide the requested part; the
    // request must clear that filter so the part comes back and gets selected.
    mockApi.listParts.mockImplementation(async (args) => {
      const all = [SUMMARY, R10K];
      const q = (args.q ?? "").toLowerCase();
      const parts = q
        ? all.filter(
            (p) =>
              p.display_name.toLowerCase().includes(q) ||
              p.mpn.toLowerCase().includes(q),
          )
        : all;
      return { parts, count: parts.length };
    });
    mockApi.facets.mockResolvedValue({
      by_category: { ICs: 1, Passives: 1 },
      by_manufacturer: {},
      complete: 2,
      incomplete: 0,
    });
    mockApi.partDetail.mockImplementation(async (id) =>
      id === "r10k"
        ? { ...DETAIL, id: "r10k", display_name: "R 10k", description: "Thick Film Resistor" }
        : DETAIL,
    );

    wrap(<ComponentsPage />);
    const user = userEvent.setup();

    // Filter the list down to just LM358; R 10k is now hidden.
    await screen.findByText("Dual Operational Amplifier");
    const search = screen.getByLabelText("Search Parts");
    await user.type(search, "LM358");
    await waitFor(() => expect(screen.queryByText("R 10k")).toBeNull());

    // A palette request for the hidden part clears the filter and selects it.
    act(() => requestPart("r10k"));

    expect(await screen.findByText("Thick Film Resistor")).toBeInTheDocument();
    expect(mockApi.partDetail).toHaveBeenCalledWith("r10k");
    expect(screen.getByLabelText("Search Parts")).toHaveValue("");
  });

  it("honors a palette part request on a FRESH mount with a warm parts cache (no auto-select clobber)", async () => {
    // The palette pre-warms the shared parts cache via its enabled:open query, so a
    // fresh ComponentsPage can mount with the list already settled (isFetching
    // false) on its very first render. In that same commit the request-drain effect
    // and the auto-select-first effect both run; the requested part (which is NOT
    // first in the list) must still win. This is the warm-cache cross-page race the
    // same-page test above cannot see (there a search filter forces isFetching true,
    // which gates auto-select). Regression lock.
    const R10K: PartSummary = {
      id: "r10k",
      display_name: "R 10k",
      category: "Passives",
      mpn: "RC0402-10K",
      manufacturer: "Yageo",
      is_complete: true,
      missing: [],
    };
    mockApi.listParts.mockResolvedValue({ parts: [SUMMARY, R10K], count: 2 });
    mockApi.facets.mockResolvedValue({
      by_category: { ICs: 1, Passives: 1 },
      by_manufacturer: {},
      complete: 2,
      incomplete: 0,
    });
    mockApi.partDetail.mockImplementation(async (id) =>
      id === "r10k"
        ? { ...DETAIL, id: "r10k", display_name: "R 10k", description: "Thick Film Resistor" }
        : DETAIL,
    );

    // staleTime mirrors production (main.tsx uses 15s) so the warm cache is FRESH
    // and does NOT refetch on mount -> isFetching is false on the first render,
    // which is exactly the condition that makes the auto-select/drain race fire.
    const qc = new QueryClient({
      defaultOptions: { queries: { retry: false, staleTime: Infinity } },
    });
    // Warm the exact shared key the palette's enabled:open query populates.
    qc.setQueryData(["parts", "", "", false], { parts: [SUMMARY, R10K], count: 2 });
    // The request was fired from another route, before this page mounted.
    requestPart("r10k");

    render(
      <QueryClientProvider client={qc}>
        <ToastProvider>
          <RouterProvider initial="components">
            <AddPartProvider>
              <ComponentsPage />
            </AddPartProvider>
          </RouterProvider>
        </ToastProvider>
      </QueryClientProvider>,
    );

    // The requested (second) part is selected, not the first part in the list.
    expect(await screen.findByText("Thick Film Resistor")).toBeInTheDocument();
    expect(mockApi.partDetail).toHaveBeenCalledWith("r10k");
    expect(screen.queryByText("Dual Operational Amplifier")).toBeNull();
  });

  it("shows the honest empty state when the library has no parts", async () => {
    mockApi.listParts.mockResolvedValue({ parts: [], count: 0 });
    mockApi.facets.mockResolvedValue({
      by_category: {},
      by_manufacturer: {},
      complete: 0,
      incomplete: 0,
    });

    wrap(<ComponentsPage />);

    expect(await screen.findByText("No Components Yet")).toBeInTheDocument();
  });

  it("shows an honest retry surface when the server is unreachable", async () => {
    mockApi.listParts.mockRejectedValue(new ApiError(0, "connection refused"));
    mockApi.facets.mockResolvedValue({
      by_category: {},
      by_manufacturer: {},
      complete: 0,
      incomplete: 0,
    });

    wrap(<ComponentsPage />);

    expect(
      await screen.findByText("Cannot reach the Stockroom server."),
    ).toBeInTheDocument();
    expect(screen.getByText("Try Again")).toBeInTheDocument();
  });
});
