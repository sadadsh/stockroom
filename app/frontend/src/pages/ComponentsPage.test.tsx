import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { ApiError } from "../api/client";
import { api } from "../api/client";
import { cadVariantApi } from "../api/cadVariantClient";
import type { EnrichmentResult, PartDetail, PartSummary } from "../api/types";
import { makePartDetail } from "../test/partFixture";
import { ToastProvider } from "../lib/toast";
import { RouterProvider } from "../lib/router";
import { AddPartProvider, useAddPart } from "../lib/addPart";
import { CaptureProvider } from "../lib/capture";
import {
  defaultUiSession,
  readUiSession,
  resetUiSessionForTests,
} from "../lib/uiSession";
import { ComponentsPage } from "./ComponentsPage";

// Mock the typed client so the page renders against fixtures, not a live server.
// ApiError is preserved (the page branches on it for the error surface). The enrich
// lookup is a background job now: enrichPart submits it (-> {job_id}) and the sourced
// result arrives over the job's SSE stream (openJobStream); mock both.
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
      restoreDeletedPart: vi.fn(),
      enrichPart: vi.fn(),
      openJobStream: vi.fn(),
      setSpecs: vi.fn(),
      getDuplicates: vi.fn(),
    },
  };
});

vi.mock("../api/cadVariantClient", async (importActual) => {
  const actual = await importActual<typeof import("../api/cadVariantClient")>();
  return {
    ...actual,
    cadVariantApi: {
      inventory: vi.fn(),
      activatePair: vi.fn(),
    },
  };
});

const mockApi = vi.mocked(api);
const mockCadVariantApi = vi.mocked(cadVariantApi);

function streamOf(chunks: string[]): ReadableStream<Uint8Array> {
  const enc = new TextEncoder();
  return new ReadableStream<Uint8Array>({
    start(c) {
      for (const s of chunks) c.enqueue(enc.encode(s));
      c.close();
    },
  });
}

// A successful enrich lookup: the submit returns a job ref, the stream carries the
// sourced result on the terminal `result` event.
function mockEnrich(r: EnrichmentResult) {
  mockApi.enrichPart.mockResolvedValue({ job_id: "e1" });
  mockApi.openJobStream.mockResolvedValue(
    streamOf([
      `event: result\ndata: ${JSON.stringify({ result: r })}\n\n`,
      "event: done\ndata: {}\n\n",
    ]),
  );
}

// Default: no duplicates. Individual tests override to exercise the badge + filter.
beforeEach(() => {
  mockApi.getDuplicates.mockResolvedValue({ by_mpn: [], by_footprint: [] });
  mockCadVariantApi.inventory.mockResolvedValue({
    partId: "lm358",
    inventories: [],
    pairs: [],
    supplementary: [],
  });
  mockCadVariantApi.activatePair.mockResolvedValue({
    partId: "lm358",
    inventories: [],
    pairs: [],
    supplementary: [],
  });
});

const SUMMARY: PartSummary = {
  id: "lm358",
  display_name: "LM358",
  category: "ICs",
  mpn: "LM358DR",
  manufacturer: "Texas Instruments",
  is_complete: true,
  missing: [],
  eda_readiness: {},
};

const DETAIL: PartDetail = makePartDetail({
  id: "lm358",
  mpn: "LM358DR",
  manufacturer: "Texas Instruments",
  tags: ["op-amp"],
  derived: { display_name: "LM358", description: "Dual Operational Amplifier" },
});

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
          <CaptureProvider>
          <AddPartProvider>
            <Probe />
            {ui}
          </AddPartProvider>
          </CaptureProvider>
        </RouterProvider>
      </ToastProvider>
    </QueryClientProvider>,
  );
  return { ...utils, state };
}

describe("ComponentsPage", () => {
  it("restores the injected filters, stable selection, and picker scroll", async () => {
    const session = defaultUiSession();
    session.component_filters = {
      query: "LM",
      category: "ICs",
      complete_only: true,
      duplicates_only: false,
    };
    session.selected_ids.component = "lm358";
    session.component_list_anchor = { part_id: "lm358", offset_px: 37 };
    resetUiSessionForTests(session);
    mockApi.listParts.mockResolvedValue({ parts: [SUMMARY], count: 1 });
    mockApi.facets.mockResolvedValue({
      by_category: { ICs: 1 },
      by_manufacturer: { "Texas Instruments": 1 },
      complete: 1,
      incomplete: 0,
    });
    mockApi.partDetail.mockResolvedValue(DETAIL);

    wrap(<ComponentsPage />);

    await screen.findByRole("heading", { name: "LM358" });
    expect(mockApi.listParts).toHaveBeenCalledWith({
      q: "LM",
      category: "ICs",
      completeOnly: true,
    });
    const row = document.querySelector('[data-part-id="lm358"]');
    expect(row).toHaveAttribute("aria-current", "true");
    const scroller = document.querySelector<HTMLElement>(
      '[data-dev-id="components.list-scroll"]',
    );
    await waitFor(() => expect(scroller?.scrollTop).toBe(37));
  });

  it("restores the picker scroll only once the real rows exist, and never checkpoints the clamped 0", async () => {
    // A3. The restore used to run the instant the scroll node mounted - while the picker body
    // was still the one-line "Loading parts..." placeholder. A browser clamps `scrollTop = N`
    // against that tiny scroll height, so the anchor became 0 and the unmount checkpoint then
    // persisted that 0 over the saved offset. jsdom has no layout and stores scrollTop
    // verbatim, so the stub below MODELS the browser clamp and records every write: what is
    // asserted is the ORDER of the writes, not any arithmetic jsdom would have done anyway.
    const session = defaultUiSession();
    session.component_list_anchor = { part_id: "lm358", offset_px: 37 };
    resetUiSessionForTests(session);
    const descriptor = Object.getOwnPropertyDescriptor(
      Element.prototype,
      "scrollTop",
    )!;
    const writes: number[] = [];
    // No room to scroll while the placeholder is on screen; the settled list has room.
    let scrollCeiling = 0;
    Object.defineProperty(Element.prototype, "scrollTop", {
      configurable: true,
      get: descriptor.get,
      set(value: number) {
        if (
          this instanceof HTMLElement &&
          this.dataset.devId === "components.list-scroll"
        ) {
          writes.push(value);
          descriptor.set!.call(this, Math.min(value, scrollCeiling));
          return;
        }
        descriptor.set!.call(this, value);
      },
    });

    try {
      let resolveList!: (value: { parts: PartSummary[]; count: number }) => void;
      mockApi.listParts.mockImplementation(
        () =>
          new Promise<{ parts: PartSummary[]; count: number }>((resolve) => {
            resolveList = resolve;
          }),
      );
      mockApi.facets.mockResolvedValue({
        by_category: { ICs: 1 },
        by_manufacturer: {},
        complete: 1,
        incomplete: 0,
      });
      mockApi.partDetail.mockResolvedValue(DETAIL);

      const view = wrap(<ComponentsPage />);

      // The list is still in flight: nothing may be written into the placeholder.
      expect(await screen.findByText("Loading parts...")).toBeInTheDocument();
      expect(writes).toEqual([]);

      scrollCeiling = 400;
      await act(async () => {
        resolveList({ parts: [SUMMARY], count: 1 });
      });

      // Only now, against the real list, is the anchor restored.
      await waitFor(() => expect(writes).toEqual([37]));
      view.unmount();
      expect(readUiSession().component_list_anchor).toEqual({
        part_id: "lm358",
        offset_px: 37,
      });
    } finally {
      Object.defineProperty(Element.prototype, "scrollTop", descriptor);
    }
  });

  it("keeps the saved picker anchor when the page unmounts before the rows arrive", async () => {
    // A3, the other half: a checkpoint is only honest once a restore has landed. Leaving the
    // page mid-load must not overwrite the saved offset with wherever the placeholder sat.
    const session = defaultUiSession();
    session.component_list_anchor = { part_id: "lm358", offset_px: 37 };
    resetUiSessionForTests(session);
    mockApi.listParts.mockImplementation(
      () => new Promise<{ parts: PartSummary[]; count: number }>(() => {}),
    );
    mockApi.facets.mockResolvedValue({
      by_category: { ICs: 1 },
      by_manufacturer: {},
      complete: 1,
      incomplete: 0,
    });
    mockApi.partDetail.mockResolvedValue(DETAIL);

    const view = wrap(<ComponentsPage />);
    expect(await screen.findByText("Loading parts...")).toBeInTheDocument();
    view.unmount();

    expect(readUiSession().component_list_anchor).toEqual({
      part_id: "lm358",
      offset_px: 37,
    });
  });

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

    // The part appears in the list (the rail carries the library count now, not a header).
    expect(await screen.findByText("LM358")).toBeInTheDocument();
    // The detail panel is the only surface that renders the description.
    // findAllByText, not findByText: the description now appears BOTH as the lede at the head
    // of the Specifications column and as the editable field in the Handoff tab. Only one is
    // visible at a time (they are alternative tabs), but both are in the DOM.
    expect((await screen.findAllByText("Dual Operational Amplifier")).length).toBeGreaterThan(0);
  });

  it("keeps the highlighted row and detail panel on the same selected part", async () => {
    const secondSummary: PartSummary = {
      id: "tl072",
      display_name: "TL072",
      category: "ICs",
      mpn: "TL072ID",
      manufacturer: "Texas Instruments",
      is_complete: true,
      missing: [],
      eda_readiness: {},
    };
    const secondDetail = makePartDetail({
      id: "tl072",
      mpn: "TL072ID",
      manufacturer: "Texas Instruments",
      derived: {
        display_name: "TL072",
        description: "Low-noise dual JFET operational amplifier",
      },
    });
    mockApi.listParts.mockResolvedValue({ parts: [SUMMARY, secondSummary], count: 2 });
    mockApi.facets.mockResolvedValue({
      by_category: { ICs: 2 },
      by_manufacturer: { "Texas Instruments": 2 },
      complete: 2,
      incomplete: 0,
    });
    mockApi.partDetail.mockImplementation(async (id) => (id === "tl072" ? secondDetail : DETAIL));

    wrap(<ComponentsPage />);
    const user = userEvent.setup();
    await screen.findAllByText("Dual Operational Amplifier");

    const secondRow = await screen.findByRole("button", { name: /TL072/ });
    await user.click(secondRow);

    expect(secondRow).toHaveAttribute("aria-current", "true");
    expect(
      (await screen.findAllByText("Low-noise dual JFET operational amplifier")).length,
    ).toBeGreaterThan(0);
    expect(mockApi.partDetail).toHaveBeenLastCalledWith("tl072");
  });

  it("keeps 1,000 rows bounded and fetches one detail per keyboard selection", async () => {
    const fixture: PartSummary[] = Array.from(
      { length: 1_000 },
      (_, index) => ({
        id: `part-${String(index).padStart(4, "0")}`,
        display_name: `Part ${String(index).padStart(4, "0")}`,
        category: `Category ${String(Math.floor(index / 100)).padStart(2, "0")}`,
        mpn: `MPN-${index}`,
        manufacturer: "Fixture",
        is_complete: true,
        missing: [],
        eda_readiness: {},
      }),
    );
    mockApi.listParts.mockResolvedValue({
      parts: fixture,
      count: fixture.length,
    });
    mockApi.facets.mockResolvedValue({
      by_category: Object.fromEntries(
        Array.from({ length: 10 }, (_, index) => [
          `Category ${String(index).padStart(2, "0")}`,
          100,
        ]),
      ),
      by_manufacturer: { Fixture: fixture.length },
      complete: fixture.length,
      incomplete: 0,
    });
    mockApi.partDetail.mockImplementation(async (id) =>
      makePartDetail({
        id,
        mpn: `MPN-${Number(id.slice(-4))}`,
        manufacturer: "Fixture",
        derived: {
          display_name: `Part ${id.slice(-4)}`,
          description: `Detail ${id}`,
        },
      }),
    );

    wrap(<ComponentsPage />);

    const first = await screen.findByRole("button", {
      name: /Part 0000/,
    });
    await screen.findAllByText("Detail part-0000");
    const list = document.querySelector('[data-dev-id="components.list"]');
    expect(list).toHaveAttribute("data-virtualized", "true");
    expect(
      list!.querySelectorAll('[data-dev-id="components.row"]').length,
    ).toBeLessThanOrEqual(40);
    expect(mockApi.listParts).toHaveBeenCalledTimes(1);
    expect(mockApi.partDetail).toHaveBeenCalledTimes(1);

    first.focus();
    await userEvent.keyboard("{ArrowDown}");
    const second = await screen.findByRole("button", {
      name: /Part 0001/,
    });
    await waitFor(() =>
      expect(second).toHaveAttribute("aria-current", "true"),
    );
    await screen.findAllByText("Detail part-0001");

    expect(mockApi.listParts).toHaveBeenCalledTimes(1);
    expect(mockApi.partDetail).toHaveBeenCalledTimes(2);
    expect(mockApi.partDetail).toHaveBeenLastCalledWith("part-0001");
  });

  it("badges MPN duplicates and the Duplicates filter narrows to just them (D2)", async () => {
    const dupA: PartSummary = { id: "a", display_name: "Cap A", category: "Passives", mpn: "C1", manufacturer: "X", is_complete: true, missing: [], eda_readiness: {} };
    const dupB: PartSummary = { id: "b", display_name: "Cap B", category: "Passives", mpn: "C1", manufacturer: "Y", is_complete: true, missing: [], eda_readiness: {} };
    const solo: PartSummary = { id: "s", display_name: "Solo Part", category: "Passives", mpn: "S1", manufacturer: "Z", is_complete: true, missing: [], eda_readiness: {} };
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

    // Manufacturer is an EDA handoff field, and the handoff moved to its own tab (owner's choice,
    // 2026-07-26). Open it first; the edit-and-toast behaviour under test is unchanged.
    await user.click(await screen.findByRole("tab", { name: "Readiness" }));
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
    mockApi.moveCategory.mockResolvedValue(
      makePartDetail({ ...DETAIL, derived: { ...DETAIL.derived, category: "Passives" } }),
    );

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

    await user.click(await screen.findByRole("button", { name: "More Actions" }));
    await user.click(screen.getByRole("button", { name: "Delete Part" }));
    const dialog = await screen.findByRole("dialog");
    // Nothing deleted until the dialog's own confirm is clicked.
    expect(mockApi.deletePart).not.toHaveBeenCalled();
    await user.click(within(dialog).getByRole("button", { name: "Delete" }));

    expect(mockApi.deletePart).toHaveBeenCalledWith("lm358");
    expect(await screen.findByText("Part deleted")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Undo Delete" })).toBeInTheDocument();
  });

  it("restores the exact deleted part from the toast action", async () => {
    mockApi.listParts.mockResolvedValue({ parts: [SUMMARY], count: 1 });
    mockApi.facets.mockResolvedValue({
      by_category: { ICs: 1 },
      by_manufacturer: {},
      complete: 1,
      incomplete: 0,
    });
    mockApi.partDetail.mockResolvedValue(DETAIL);
    mockApi.deletePart.mockResolvedValue(undefined);
    mockApi.restoreDeletedPart.mockResolvedValue(DETAIL);

    wrap(<ComponentsPage />);
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: "More Actions" }));
    await user.click(screen.getByRole("button", { name: "Delete Part" }));
    await user.click(
      within(await screen.findByRole("dialog")).getByRole("button", { name: "Delete" }),
    );
    await user.click(await screen.findByRole("button", { name: "Undo Delete" }));

    await waitFor(() => expect(mockApi.restoreDeletedPart).toHaveBeenCalledWith("lm358"));
    expect(await screen.findByText("Part restored")).toBeInTheDocument();
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

    await screen.findAllByText("Dual Operational Amplifier");
    expect(mockApi.partDetail).toHaveBeenCalledTimes(1);

    await user.click(await screen.findByRole("button", { name: "More Actions" }));
    await user.click(screen.getByRole("button", { name: "Delete Part" }));
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
    mockEnrich({
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

    // Enrich now lives in the part workbench's Enrich tab, so open it first.
    await user.click(await screen.findByRole("tab", { name: "Evidence" }));
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
    mockEnrich({
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

    // Enrich now lives in the part workbench's Enrich tab, so open it first.
    await user.click(await screen.findByRole("tab", { name: "Evidence" }));
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
    mockEnrich({
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
    mockApi.setSpecs.mockResolvedValue(
      makePartDetail({ ...DETAIL, derived: { ...DETAIL.derived, specs: { pinout: pins } } }),
    );

    wrap(<ComponentsPage />);
    const user = userEvent.setup();

    // Enrich now lives in the part workbench's Enrich tab, so open it first.
    await user.click(await screen.findByRole("tab", { name: "Evidence" }));
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

  it("shows the honest empty state when the library has no parts", async () => {
    mockApi.listParts.mockResolvedValue({ parts: [], count: 0 });
    mockApi.facets.mockResolvedValue({
      by_category: {},
      by_manufacturer: {},
      complete: 0,
      incomplete: 0,
    });

    const view = wrap(<ComponentsPage />);

    expect(await screen.findByText("No Components Yet")).toBeInTheDocument();
    expect(screen.getAllByText("No Components Yet")).toHaveLength(1);
    expect(screen.queryByText("Select a part to see its details.")).not.toBeInTheDocument();
    const action = screen.getByRole("button", { name: "Add Parts" });
    await userEvent.click(action);
    expect(view.state.addPartOpen).toBe(true);
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
