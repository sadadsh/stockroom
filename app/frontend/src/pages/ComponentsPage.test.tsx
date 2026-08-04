import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { ApiError } from "../api/client";
import { api } from "../api/client";
import { cadVariantApi } from "../api/cadVariantClient";
import type { PartSummary } from "../api/types";
import { makePartDetail } from "../test/partFixture";
import { makeWorkspace } from "../test/workspaceFixture";
import { ToastProvider } from "../lib/toast";
import { ThemeProvider } from "../lib/theme";
import { RouterProvider } from "../lib/router";
import { AddPartProvider, useAddPart } from "../lib/addPart";
import { CaptureProvider } from "../lib/capture";
import {
  MAX_OPEN_COMPONENTS,
  defaultUiSession,
  openComponentInSession,
  readUiSession,
  resetUiSessionForTests,
} from "../lib/uiSession";
import { ComponentsPage } from "./ComponentsPage";

// Mock the typed client so the page renders against fixtures, not a live server.
// ApiError is preserved (the page branches on it for the error surface). The opened
// component reads the normalized workspace projection, and its representation dock
// pulls the symbol/footprint SVG and the model GLB, so those are mocked too.
vi.mock("../api/client", async (importActual) => {
  const actual = await importActual<typeof import("../api/client")>();
  return {
    ...actual,
    api: {
      listParts: vi.fn(),
      facets: vi.fn(),
      partWorkspace: vi.fn(),
      deletePart: vi.fn(),
      restoreDeletedPart: vi.fn(),
      getDuplicates: vi.fn(),
      previewSvg: vi.fn(),
      modelGlb: vi.fn(),
      landPattern: vi.fn(),
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

// three.js is verified in the Windows pixel gate; mock the scene so the dock's 3D module
// does not need a WebGL context here.
vi.mock("../lib/threeScene", () => ({
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

// Default: no duplicates. Individual tests override to exercise the badge + filter.
beforeEach(() => {
  mockApi.getDuplicates.mockResolvedValue({ by_mpn: [], by_footprint: [] });
  mockApi.previewSvg.mockResolvedValue(new Blob(["<svg/>"], { type: "image/svg+xml" }));
  mockApi.modelGlb.mockResolvedValue(new Uint8Array([0x67, 0x6c, 0x54, 0x46]).buffer);
  mockApi.landPattern.mockRejectedValue(new ApiError(404, "no footprint"));
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

/** The workspace for one id, named so a test can tell two open components apart. */
function workspaceFor(id: string, displayName: string, description: string) {
  return makeWorkspace({
    identity: { id, displayName, mpn: `${displayName}-MPN` },
    summary: { description: { rawValue: description, formattedValue: description } },
  });
}

const FACETS = {
  by_category: { ICs: 1 },
  by_manufacturer: { "Texas Instruments": 1 },
  complete: 1,
  incomplete: 0,
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
      <ThemeProvider>
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
      </ThemeProvider>
    </QueryClientProvider>,
  );
  return { ...utils, state };
}

/** The open-component strip, scoped so the four information tabs are never mistaken for it. */
function openTabs(): HTMLElement {
  return document.querySelector<HTMLElement>('[data-dev-id="component-browser.tabs"]')!;
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
    mockApi.facets.mockResolvedValue(FACETS);
    mockApi.partWorkspace.mockResolvedValue(
      workspaceFor("lm358", "LM358", "Dual Operational Amplifier"),
    );

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
    // was still the one-line loading placeholder. A browser clamps `scrollTop = N`
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
      mockApi.facets.mockResolvedValue(FACETS);
      mockApi.partWorkspace.mockResolvedValue(
        workspaceFor("lm358", "LM358", "Dual Operational Amplifier"),
      );

      const view = wrap(<ComponentsPage />);

      // The list is still in flight: nothing may be written into the placeholder.
      expect(await screen.findByText("Loading this library's components...")).toBeInTheDocument();
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
    mockApi.facets.mockResolvedValue(FACETS);
    mockApi.partWorkspace.mockResolvedValue(
      workspaceFor("lm358", "LM358", "Dual Operational Amplifier"),
    );

    const view = wrap(<ComponentsPage />);
    expect(await screen.findByText("Loading this library's components...")).toBeInTheDocument();
    view.unmount();

    expect(readUiSession().component_list_anchor).toEqual({
      part_id: "lm358",
      offset_px: 37,
    });
  });

  it("lists parts, shows the count, and auto-opens the first part's workspace", async () => {
    mockApi.listParts.mockResolvedValue({ parts: [SUMMARY], count: 1 });
    mockApi.facets.mockResolvedValue(FACETS);
    mockApi.partWorkspace.mockResolvedValue(
      workspaceFor("lm358", "LM358", "Dual Operational Amplifier"),
    );

    wrap(<ComponentsPage />);

    // The part appears in the list (the rail carries the library count now, not a header).
    expect((await screen.findAllByText("LM358")).length).toBeGreaterThan(0);
    // The opened component is the only surface that renders the description.
    expect(await screen.findByText("Dual Operational Amplifier")).toBeInTheDocument();
  });

  it("keeps the highlighted row and the opened workspace on the same selected part", async () => {
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
    mockApi.listParts.mockResolvedValue({ parts: [SUMMARY, secondSummary], count: 2 });
    mockApi.facets.mockResolvedValue(FACETS);
    mockApi.partWorkspace.mockImplementation(async (id) =>
      id === "tl072"
        ? workspaceFor("tl072", "TL072", "Low-noise dual JFET operational amplifier")
        : workspaceFor("lm358", "LM358", "Dual Operational Amplifier"),
    );

    wrap(<ComponentsPage />);
    const user = userEvent.setup();
    await screen.findByText("Dual Operational Amplifier");

    const secondRow = await screen.findByRole("button", { name: /TL072/ });
    await user.click(secondRow);

    expect(secondRow).toHaveAttribute("aria-current", "true");
    expect(
      await screen.findByText("Low-noise dual JFET operational amplifier"),
    ).toBeInTheDocument();
    expect(mockApi.partWorkspace).toHaveBeenLastCalledWith("tl072");
  });

  it("keeps 1,000 rows bounded and fetches one workspace per keyboard selection", async () => {
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
    mockApi.partWorkspace.mockImplementation(async (id) =>
      workspaceFor(id, `Part ${id.slice(-4)}`, `Detail ${id}`),
    );

    wrap(<ComponentsPage />);

    const first = await screen.findByRole("button", {
      name: /Part 0000/,
    });
    await screen.findByText("Detail part-0000");
    const list = document.querySelector('[data-dev-id="components.list"]');
    expect(list).toHaveAttribute("data-virtualized", "true");
    expect(
      list!.querySelectorAll('[data-dev-id="components.row"]').length,
    ).toBeLessThanOrEqual(40);
    expect(mockApi.listParts).toHaveBeenCalledTimes(1);
    expect(mockApi.partWorkspace).toHaveBeenCalledTimes(1);

    first.focus();
    await userEvent.keyboard("{ArrowDown}");
    const second = await screen.findByRole("button", {
      name: /Part 0001/,
    });
    await waitFor(() =>
      expect(second).toHaveAttribute("aria-current", "true"),
    );
    await screen.findByText("Detail part-0001");

    expect(mockApi.listParts).toHaveBeenCalledTimes(1);
    expect(mockApi.partWorkspace).toHaveBeenCalledTimes(2);
    expect(mockApi.partWorkspace).toHaveBeenLastCalledWith("part-0001");
  });

  it("badges MPN duplicates and the Duplicates filter narrows to just them (D2)", async () => {
    const dupA: PartSummary = { id: "a", display_name: "Cap A", category: "Passives", mpn: "C1", manufacturer: "X", is_complete: true, missing: [], eda_readiness: {} };
    const dupB: PartSummary = { id: "b", display_name: "Cap B", category: "Passives", mpn: "C1", manufacturer: "Y", is_complete: true, missing: [], eda_readiness: {} };
    const solo: PartSummary = { id: "s", display_name: "Solo Part", category: "Passives", mpn: "S1", manufacturer: "Z", is_complete: true, missing: [], eda_readiness: {} };
    mockApi.listParts.mockResolvedValue({ parts: [dupA, dupB, solo], count: 3 });
    mockApi.facets.mockResolvedValue({ by_category: { Passives: 3 }, by_manufacturer: {}, complete: 3, incomplete: 0 });
    mockApi.partWorkspace.mockImplementation(async (id) => workspaceFor(id, `Open ${id}`, "x"));
    // A real accidental duplicate: two parts under one MPN. Shared footprints are ignored.
    mockApi.getDuplicates.mockResolvedValue({ by_mpn: [{ key: "C1", parts: [dupA, dupB] }], by_footprint: [] });

    wrap(<ComponentsPage />);
    expect(await screen.findByText("Solo Part")).toBeInTheDocument();
    // Both duplicate members carry a badge; the solo part does not.
    await waitFor(() => expect(screen.getAllByText("Duplicate")).toHaveLength(2));

    // The Duplicates filter (behind the Filters popover) narrows to just the members. Scoped to
    // the picker: a component's name also reads on its open tab, which is not the list.
    const list = document.querySelector<HTMLElement>('[data-dev-id="components.list-scroll"]')!;
    await userEvent.click(screen.getByRole("button", { name: "Filters" }));
    await userEvent.click(screen.getByText(/Duplicates \(2\)/));
    expect(within(list).queryByText("Solo Part")).toBeNull();
    expect(within(list).getByText("Cap A")).toBeInTheDocument();
    expect(within(list).getByText("Cap B")).toBeInTheDocument();
  });

  it("opens the Add A Part modal from the Add Parts toolbar button", async () => {
    mockApi.listParts.mockResolvedValue({ parts: [SUMMARY], count: 1 });
    mockApi.facets.mockResolvedValue(FACETS);
    mockApi.partWorkspace.mockResolvedValue(workspaceFor("lm358", "LM358", "Dual op-amp"));

    const { state } = wrap(<ComponentsPage />);
    const user = userEvent.setup();

    expect(state.addPartOpen).toBe(false);
    await user.click(await screen.findByRole("button", { name: "Add Parts" }));
    expect(state.addPartOpen).toBe(true);
  });

  it("deletes a part only after an in-window confirm", async () => {
    mockApi.listParts.mockResolvedValue({ parts: [SUMMARY], count: 1 });
    mockApi.facets.mockResolvedValue(FACETS);
    mockApi.partWorkspace.mockResolvedValue(workspaceFor("lm358", "LM358", "Dual op-amp"));
    mockApi.deletePart.mockResolvedValue(undefined);

    wrap(<ComponentsPage />);
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: /Delete Part/ }));
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
    mockApi.facets.mockResolvedValue(FACETS);
    mockApi.partWorkspace.mockResolvedValue(workspaceFor("lm358", "LM358", "Dual op-amp"));
    mockApi.deletePart.mockResolvedValue(undefined);
    mockApi.restoreDeletedPart.mockResolvedValue(makePartDetail({ id: "lm358" }));

    wrap(<ComponentsPage />);
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: /Delete Part/ }));
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
    // deleted part must not be re-opened or re-fetched (it would 404).
    let resolveRefetch!: (v: { parts: PartSummary[]; count: number }) => void;
    mockApi.listParts
      .mockResolvedValueOnce({ parts: [SUMMARY], count: 1 })
      .mockImplementationOnce(
        () =>
          new Promise<{ parts: PartSummary[]; count: number }>((res) => {
            resolveRefetch = res;
          }),
      );
    mockApi.facets.mockResolvedValue(FACETS);
    mockApi.partWorkspace.mockResolvedValue(workspaceFor("lm358", "LM358", "Dual op-amp"));
    mockApi.deletePart.mockResolvedValue(undefined);

    wrap(<ComponentsPage />);
    const user = userEvent.setup();

    await screen.findByText("Dual op-amp");
    expect(mockApi.partWorkspace).toHaveBeenCalledTimes(1);

    await user.click(await screen.findByRole("button", { name: /Delete Part/ }));
    await user.click(
      within(await screen.findByRole("dialog")).getByRole("button", { name: "Delete" }),
    );

    // Delete succeeded; the refetch is in flight and the old list is retained.
    await screen.findByText("Part deleted");
    expect(mockApi.partWorkspace).toHaveBeenCalledTimes(1); // not re-fetched off the stale list

    // Resolve the refetch to an empty library: the honest empty state shows and
    // still nothing re-fetches the deleted part.
    await act(async () => {
      resolveRefetch({ parts: [], count: 0 });
    });
    expect(await screen.findByText("No Components Yet")).toBeInTheDocument();
    expect(mockApi.partWorkspace).toHaveBeenCalledTimes(1);
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
    expect(screen.queryByText("Select a component to open it.")).not.toBeInTheDocument();
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

    // The shared error state, not a hand-written centred div: it carries `data-product-state`,
    // it announces itself, and its message is a written sentence rather than `error.message`.
    const failure = await screen.findByText("Stockroom is not answering on this machine.");
    expect(failure.closest('[data-product-state="error"]')).not.toBeNull();
    expect(screen.getByRole("button", { name: "Try Again" })).toBeInTheDocument();
  });
});

describe("open component tabs", () => {
  const PARTS: PartSummary[] = Array.from({ length: 15 }, (_, index) => ({
    id: `p${index}`,
    display_name: `Part ${index}`,
    category: "ICs",
    mpn: `MPN-${index}`,
    manufacturer: "Fixture",
    is_complete: true,
    missing: [],
    eda_readiness: {},
  }));

  beforeEach(() => {
    mockApi.listParts.mockResolvedValue({ parts: PARTS, count: PARTS.length });
    mockApi.facets.mockResolvedValue({
      by_category: { ICs: PARTS.length },
      by_manufacturer: { Fixture: PARTS.length },
      complete: PARTS.length,
      incomplete: 0,
    });
    mockApi.partWorkspace.mockImplementation(async (id) =>
      workspaceFor(id, `Part ${id.slice(1)}`, `Description ${id}`),
    );
  });

  async function openRow(user: ReturnType<typeof userEvent.setup>, index: number) {
    await user.click(await screen.findByRole("button", { name: new RegExp(`Part ${index}\\b`) }));
  }

  it("opens a picker row into a tab, and re-selecting it activates rather than duplicates", async () => {
    wrap(<ComponentsPage />);
    const user = userEvent.setup();
    await screen.findByText("Description p0");

    await openRow(user, 1);
    await screen.findByText("Description p1");
    expect(readUiSession().open_components).toEqual(["p0", "p1"]);

    // Back to the first, then to the first again: still two tabs, never three.
    await openRow(user, 0);
    await openRow(user, 0);
    await waitFor(() => expect(readUiSession().active_component).toBe("p0"));
    expect(readUiSession().open_components).toEqual(["p0", "p1"]);
    expect(within(openTabs()).getAllByRole("tab")).toHaveLength(2);
  });

  it("activates an already-open component from its own tab", async () => {
    wrap(<ComponentsPage />);
    const user = userEvent.setup();
    await screen.findByText("Description p0");
    await openRow(user, 1);
    await screen.findByText("Description p1");

    await user.click(within(openTabs()).getByRole("tab", { name: "Part 0" }));

    await screen.findByText("Description p0");
    expect(readUiSession().active_component).toBe("p0");
    // The picker follows the tab, so the highlighted row and the open workspace never disagree.
    expect(document.querySelector('[data-part-id="p0"]')).toHaveAttribute("aria-current", "true");
    expect(mockApi.partWorkspace).toHaveBeenLastCalledWith("p0");
  });

  it("closing a tab leaves the component in the library and activates a neighbour", async () => {
    wrap(<ComponentsPage />);
    const user = userEvent.setup();
    await screen.findByText("Description p0");
    await openRow(user, 1);
    await screen.findByText("Description p1");

    await user.click(screen.getByRole("button", { name: "Close Tab" }));

    await waitFor(() => expect(readUiSession().open_components).toEqual(["p0"]));
    expect(readUiSession().active_component).toBe("p0");
    // The component is still listed: closing a VIEW of it deleted nothing.
    expect(await screen.findByRole("button", { name: /Part 1\b/ })).toBeInTheDocument();
    expect(mockApi.deletePart).not.toHaveBeenCalled();
  });

  it("restores the open strip and the active tab from the injected session", async () => {
    let session = defaultUiSession();
    session = openComponentInSession(session, "p3");
    session = openComponentInSession(session, "p5");
    session.selected_ids.component = "p5";
    resetUiSessionForTests(session);

    wrap(<ComponentsPage />);

    await screen.findByText("Description p5");
    const tabs = within(openTabs()).getAllByRole("tab");
    expect(tabs.map((tab) => tab.textContent)).toEqual(["Part 3", "Part 5"]);
    expect(within(openTabs()).getByRole("tab", { name: "Part 5" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
  });

  it("holds the tab bound at twelve, evicting the least recently used tab", async () => {
    wrap(<ComponentsPage />);
    const user = userEvent.setup();
    await screen.findByText("Description p0");

    for (let index = 1; index < MAX_OPEN_COMPONENTS + 2; index += 1) {
      await openRow(user, index);
      await screen.findByText(`Description p${index}`);
    }

    const open = readUiSession().open_components;
    expect(open).toHaveLength(MAX_OPEN_COMPONENTS);
    expect(within(openTabs()).getAllByRole("tab")).toHaveLength(MAX_OPEN_COMPONENTS);
    expect(open).toContain(`p${MAX_OPEN_COMPONENTS + 1}`);
    expect(open).not.toContain("p0");
  });

  it("drops a tab whose component is no longer in the library, without crashing", async () => {
    let session = defaultUiSession();
    session = openComponentInSession(session, "p2");
    session = openComponentInSession(session, "ghost-part");
    session.selected_ids.component = "p2";
    resetUiSessionForTests(session);

    wrap(<ComponentsPage />);

    await screen.findByText("Description p2");
    await waitFor(() => expect(readUiSession().open_components).toEqual(["p2"]));
    expect(within(openTabs()).queryByRole("tab", { name: "ghost-part" })).toBeNull();
  });

  it("keeps tabs open while a filter narrows the picker to one row", async () => {
    // Stale-tab removal must distinguish "this component left the library" from "this component
    // is not in the current search". A narrowed list is not evidence of a deletion, and closing
    // someone's open comparison as they type a filter would be the worse failure of the two.
    let session = defaultUiSession();
    session = openComponentInSession(session, "p0");
    session = openComponentInSession(session, "p1");
    session.selected_ids.component = "p1";
    session.component_filters.category = "ICs";
    resetUiSessionForTests(session);
    mockApi.listParts.mockResolvedValue({ parts: [PARTS[1]], count: 1 });

    wrap(<ComponentsPage />);

    await screen.findByText("Description p1");
    expect(readUiSession().open_components).toEqual(["p0", "p1"]);
    // The filtered-out tab keeps its place. Its label falls back to the component id, because a
    // list that no longer carries the row cannot supply the name.
    expect(within(openTabs()).getAllByRole("tab")).toHaveLength(2);
    expect(within(openTabs()).getByRole("tab", { name: "p0" })).toBeInTheDocument();
  });

  it("remembers each component's information tab and representation layout separately", async () => {
    wrap(<ComponentsPage />);
    const user = userEvent.setup();
    await screen.findByText("Description p0");

    await user.click(screen.getByRole("tab", { name: "Sourcing" }));
    await user.click(screen.getByRole("radio", { name: "Footprint" }));
    await waitFor(() =>
      expect(readUiSession().component_views.p0).toMatchObject({
        info_tab: "sourcing",
        representation_layout: "footprint",
      }),
    );

    await openRow(user, 1);
    await screen.findByText("Description p1");
    // A second component starts at its own defaults rather than inheriting the first's view.
    expect(screen.getByRole("tab", { name: "Overview" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    expect(screen.getByRole("radio", { name: "All" })).toHaveAttribute("aria-checked", "true");

    await user.click(within(openTabs()).getByRole("tab", { name: "Part 0" }));
    // Back on the first component, its own view state is in force: the Sourcing tab, not the
    // Overview the second component was left on.
    await waitFor(() =>
      expect(screen.getByRole("tab", { name: "Sourcing" })).toHaveAttribute(
        "aria-selected",
        "true",
      ),
    );
    expect(screen.getByRole("radio", { name: "Footprint" })).toHaveAttribute(
      "aria-checked",
      "true",
    );
  });

  it("keeps the opened component in a non-scrolling root", async () => {
    wrap(<ComponentsPage />);
    await screen.findByText("Description p0");
    const root = document.querySelector<HTMLElement>('[data-dev-id="component-browser.root"]')!;
    // The hard contract: height 100%, a zero min-height so flex children can shrink, and no
    // scrolling of its own. Everything longer than its band belongs in a modal.
    expect(root.className).toContain("h-full");
    expect(root.className).toContain("min-h-0");
    expect(root.className).toContain("overflow-hidden");
    // Nor may the column that holds it, nor the page itself, become a scroller.
    const pane = document.querySelector<HTMLElement>('[data-dev-id="components.detail-pane"]')!;
    expect(pane.className).toContain("overflow-hidden");
    // Nothing inside the workspace may scroll on its own. Modal subtrees are excluded because a
    // modal is the ONE surface the rule allows a scrollbar - and none is open here anyway.
    const scrollers = Array.from(
      root.querySelectorAll<HTMLElement>("[class*='overflow-y-auto'],[class*='overflow-auto']"),
    ).filter((node) => !node.closest('[role="dialog"]'));
    expect(scrollers).toEqual([]);
  });
});
