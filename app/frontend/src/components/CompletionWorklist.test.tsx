/**
 * The worklist, tested for the promises that make it worth showing at all: a row STARTS the real
 * person-driven capture for an exact part on an exact provider, it uses the reason the route itself
 * gave, it never invents work (or completeness) the run did not report, and it is honest about
 * there being exactly one capture slot.
 */
import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { CompletionWorklist } from "./CompletionWorklist";
import { CaptureProvider, useCapture } from "../lib/capture";
import { api } from "../api/client";
import { mockCapture } from "../test/captureMocks";
import { resetUiSessionForTests } from "../lib/uiSession";
import type { CadSourceResponse, CaptureBatchWorklist } from "../api/types";

function worklist(over: Partial<CaptureBatchWorklist> = {}): CaptureBatchWorklist {
  return {
    workflow_batch_id: "batch-1",
    total_items: 3,
    pending_items: 0,
    worklist: [
      {
        part_id: "lm317",
        mpn: "LM317",
        display_name: "LM317 Regulator",
        route_id: "ultralibrarian:ultralibrarian",
        provider_key: "ultralibrarian",
        label: "Ultra Librarian",
        status: "requires-human",
        reason: "no Ultra Librarian sign-in is saved on this PC",
        remaining: ["kicad_model", "altium_symbol"],
      },
    ],
    worklist_unit: "components",
    worklist_total: 1,
    unattended: [],
    unattended_total: 2,
    stalled: [],
    stalled_total: 0,
    unreadable: [],
    ...over,
  };
}

function cadSource(over: Partial<CadSourceResponse> = {}): CadSourceResponse {
  return {
    mpn: "LM317",
    needs: ["kicad_model"],
    sources: [
      {
        key: "digikey",
        label: "DigiKey",
        url: "https://www.digikey.com/en/models/1234",
        tools: ["kicad", "altium"],
        aggregator: true,
        instruction: "Open the models tab.",
        capture_available: true,
      },
      {
        key: "ultralibrarian",
        label: "Ultra Librarian",
        url: "https://app.ultralibrarian.com/search?queryText=LM317",
        tools: ["kicad", "altium"],
        aggregator: false,
        instruction: "Pick the part, choose KiCad and Altium, then Download.",
        capture_available: true,
      },
    ],
    url: "https://www.digikey.com/en/models/1234",
    vendor: "DigiKey",
    ...over,
  } as CadSourceResponse;
}

// Two rows, so a test can watch the one-click pass move from the first to the second.
function twoRows(): CaptureBatchWorklist {
  const first = worklist().worklist[0];
  return worklist({
    worklist: [
      first,
      { ...first, part_id: "ne555", mpn: "NE555", display_name: "NE555 Timer" },
    ],
    worklist_total: 2,
  });
}

const WORK_THROUGH_ALL = "Work through every listed component, one capture at a time";
const STOP_ADVANCING = "Stop working through the completion worklist";

// Another surface holding the SAME one capture slot, so a test can reproduce the displacement the
// Complete Part window causes when it starts a capture while a worklist row is still running.
function Displacer() {
  const capture = useCapture();
  return (
    <button
      type="button"
      onClick={() =>
        void capture
          .start("ne555", "NE555 Timer", [])
          .catch(() => undefined)
      }
    >
      Start Elsewhere
    </button>
  );
}

function CaptureBackgroundState() {
  const capture = useCapture();
  return (
    <output data-testid="capture-backgrounded">
      {capture.active.backgrounded ? "backgrounded" : "foreground"}
    </output>
  );
}

// CaptureProvider is the one global capture slot. A row starts a real capture through it, so this
// surface cannot be rendered without it - exactly as `main.tsx` mounts it above the whole app.
function renderWorklist(live = false, extra?: ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <CaptureProvider>
        <CompletionWorklist batchId="batch-1" live={live} />
        {extra}
      </CaptureProvider>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.restoreAllMocks();
  resetUiSessionForTests();
});

afterEach(() => {
  resetUiSessionForTests();
});

describe("completion worklist", () => {
  it("names the part, the route's own reason, and the formats still outstanding", async () => {
    vi.spyOn(api, "captureWorklist").mockResolvedValue(worklist());
    vi.spyOn(api, "partCadSource").mockResolvedValue(cadSource());
    renderWorklist();

    expect(await screen.findByText("LM317 Regulator")).toBeInTheDocument();
    // The reason is the outcome's own sentence, not a status word this surface chose.
    expect(
      screen.getByText("no Ultra Librarian sign-in is saved on this PC"),
    ).toBeInTheDocument();
    expect(screen.getByText("3D Model")).toBeInTheDocument();
    expect(screen.getByText("Altium Symbol")).toBeInTheDocument();
  });

  it("starts the one automatic workflow for that component", async () => {
    // The defect this replaces: the row opened the provider URL directly, so no backend capture
    // session started, the person's Downloads were never snapshotted, and the file they collected
    // was never imported. The row routed them and dropped the result on the floor.
    vi.spyOn(api, "captureWorklist").mockResolvedValue(worklist());
    vi.spyOn(api, "partCadSource").mockResolvedValue(cadSource());
    const capture = mockCapture();
    renderWorklist(false, <CaptureBackgroundState />);

    await userEvent.click(
      await screen.findByRole("button", {
        name: "Get files for LM317 Regulator",
      }),
    );

    await waitFor(() => expect(capture.run).toHaveBeenCalled());
    expect(screen.getByTestId("capture-backgrounded")).toHaveTextContent("backgrounded");
    expect(capture.run).toHaveBeenCalledWith(
      expect.objectContaining({
        partIds: ["lm317"],
        vendor: undefined,
      }),
    );
  });

  it("runs one capture at a time and refuses to let another row displace it", async () => {
    vi.spyOn(api, "captureWorklist").mockResolvedValue(
      worklist({
        worklist: [
          worklist().worklist[0],
          {
            ...worklist().worklist[0],
            part_id: "ne555",
            mpn: "NE555",
            display_name: "NE555 Timer",
          },
        ],
        worklist_total: 2,
      }),
    );
    vi.spyOn(api, "partCadSource").mockResolvedValue(cadSource());
    // Never resolves: the capture stays in flight, which is the state the other rows must honour.
    const run = vi.spyOn(api, "runCapture").mockReturnValue(new Promise(() => {}));
    renderWorklist();

    await userEvent.click(
      await screen.findByRole("button", {
        name: "Get files for LM317 Regulator",
      }),
    );

    await waitFor(() => expect(run).toHaveBeenCalledTimes(1));
    await waitFor(() =>
      expect(
        screen.getByRole("button", {
          name: "Get files for NE555 Timer",
        }),
      ).toBeDisabled(),
    );
    expect(
      screen.getByRole("button", {
        name: "Get files for LM317 Regulator",
      }),
    ).toHaveTextContent("Getting Files");
  });

  it("refuses another surface instead of displacing the active worklist capture", async () => {
    vi.spyOn(api, "captureWorklist").mockResolvedValue(worklist());
    vi.spyOn(api, "partCadSource").mockResolvedValue(cadSource());
    vi.spyOn(api, "runCapture").mockReturnValue(new Promise(() => {}));
    renderWorklist(false, <Displacer />);

    await userEvent.click(
      await screen.findByRole("button", {
        name: "Get files for LM317 Regulator",
      }),
    );
    await expect(
      userEvent.click(screen.getByRole("button", { name: "Start Elsewhere" })),
    ).resolves.toBeUndefined();
    expect(api.runCapture).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("button", { name: "Get files for LM317 Regulator" })).toHaveTextContent(
      "Getting Files",
    );
  });

  it("does not show provider decisions before an embedded provider page asks for them", async () => {
    vi.spyOn(api, "captureWorklist").mockResolvedValue(worklist());
    vi.spyOn(api, "partCadSource").mockResolvedValue(cadSource());
    vi.spyOn(api, "runCapture").mockReturnValue(new Promise(() => {}));
    renderWorklist();

    await userEvent.click(
      await screen.findByRole("button", {
        name: "Get files for LM317 Regulator",
      }),
    );
    expect(screen.queryByRole("button", { name: "Finish Route" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Skip This Part" })).toBeNull();
  });

  it("does not expose a provider-only link beside Get Files", async () => {
    vi.spyOn(api, "captureWorklist").mockResolvedValue(worklist());
    const source = vi.spyOn(api, "partCadSource").mockResolvedValue(cadSource());
    renderWorklist();

    expect(await screen.findByRole("button", { name: "Get files for LM317 Regulator" })).toBeInTheDocument();
    expect(screen.queryByRole("link")).toBeNull();
    expect(source).not.toHaveBeenCalled();
  });

  it("counts what finished unattended apart from what needs a person", async () => {
    vi.spyOn(api, "captureWorklist").mockResolvedValue(worklist());
    vi.spyOn(api, "partCadSource").mockResolvedValue(cadSource());
    renderWorklist();

    expect(await screen.findByText("1 Needs You")).toBeInTheDocument();
    // Not "Done": that is one of the four synonyms the status vocabulary collapses into "Ready".
    expect(screen.getByText("2 No Person Needed")).toBeInTheDocument();
  });

  it("keeps a part no route can advance out of the worklist, and still reports it", async () => {
    // A stalled part sent to a provider that already said it has nothing is a wasted trip, so it
    // is counted separately rather than folded into the rows a person can act on.
    vi.spyOn(api, "captureWorklist").mockResolvedValue(
      worklist({
        worklist: [],
        worklist_total: 0,
        stalled: [
          {
            part_id: "mystery",
            mpn: "MYSTERY",
            display_name: "MYSTERY",
            status: "unchanged",
            reason: "no exact model exists for this package",
            remaining: ["kicad_model"],
          },
        ],
        stalled_total: 1,
      }),
    );
    renderWorklist();

    expect(await screen.findByText("Nothing on this run needs a person.")).toBeInTheDocument();
    expect(screen.getByText("1 No Route")).toBeInTheDocument();
    expect(
      screen.getByText(/no provider route a person could advance/i),
    ).toBeInTheDocument();
  });

  it("reports items still working rather than calling an unfinished run complete", async () => {
    vi.spyOn(api, "captureWorklist").mockResolvedValue(
      worklist({ worklist: [], worklist_total: 0, unattended_total: 0, pending_items: 4 }),
    );
    renderWorklist(true);

    expect(await screen.findByText("4 Still Working")).toBeInTheDocument();
    expect(
      screen.getByText("Nothing needs you yet. This fills in as each component settles."),
    ).toBeInTheDocument();
  });

  it("bounds the rendered rows and states how many are left", async () => {
    const rows = Array.from({ length: 30 }, (_, index) => ({
      ...worklist().worklist[0],
      part_id: `part-${index}`,
      mpn: `MPN-${index}`,
      display_name: `Part ${index}`,
    }));
    vi.spyOn(api, "captureWorklist").mockResolvedValue(
      worklist({ worklist: rows, worklist_total: 30 }),
    );
    vi.spyOn(api, "partCadSource").mockResolvedValue(cadSource());
    renderWorklist();

    expect(await screen.findByText("Part 0")).toBeInTheDocument();
    expect(screen.queryByText("Part 25")).toBeNull();
    expect(screen.getByText(/5 more components need a person/i)).toBeInTheDocument();
  });

  // --- one click for the whole list -----------------------------------------------------------
  //
  // Clearing the worklist used to cost one Start Capture per row on top of the provider clicks
  // nobody can remove. These prove the single control replaces every one of those, and that it
  // stops the moment continuing would be wrong.

  it("works the whole list from one click, starting each row as the last capture finishes", async () => {
    vi.spyOn(api, "captureWorklist").mockResolvedValue(twoRows());
    vi.spyOn(api, "partCadSource").mockResolvedValue(cadSource());
    const capture = mockCapture();
    renderWorklist();

    await userEvent.click(await screen.findByRole("button", { name: WORK_THROUGH_ALL }));

    await waitFor(() => expect(capture.run).toHaveBeenCalledTimes(2));
    // In list order, and never two at once: the second start only happened because the first
    // capture reached a terminal state, not because a timer went off.
    expect(capture.run).toHaveBeenNthCalledWith(
      1,
      expect.objectContaining({ partIds: ["lm317"], vendor: undefined }),
    );
    expect(capture.run).toHaveBeenNthCalledWith(
      2,
      expect.objectContaining({ partIds: ["ne555"], vendor: undefined }),
    );
    expect(await screen.findByTestId("completion-worklist-auto-ended")).toHaveTextContent(
      "Worked through all 2 components.",
    );
  });

  it("names the row that is open and how many are left while the pass runs", async () => {
    vi.spyOn(api, "captureWorklist").mockResolvedValue(twoRows());
    vi.spyOn(api, "partCadSource").mockResolvedValue(cadSource());
    vi.spyOn(api, "runCapture").mockReturnValue(new Promise(() => {}));
    renderWorklist();

    await userEvent.click(await screen.findByRole("button", { name: WORK_THROUGH_ALL }));

    expect(await screen.findByTestId("completion-worklist-auto")).toHaveTextContent(
      "Working through 1 of 2. LM317 Regulator is active in Stockroom",
    );
  });

  it("stops advancing when the person says so, and leaves the open capture alone", async () => {
    vi.spyOn(api, "captureWorklist").mockResolvedValue(twoRows());
    vi.spyOn(api, "partCadSource").mockResolvedValue(cadSource());
    const run = vi.spyOn(api, "runCapture").mockReturnValue(new Promise(() => {}));
    renderWorklist();

    await userEvent.click(await screen.findByRole("button", { name: WORK_THROUGH_ALL }));
    await waitFor(() => expect(run).toHaveBeenCalledTimes(1));
    await userEvent.click(await screen.findByRole("button", { name: STOP_ADVANCING }));

    expect(await screen.findByTestId("completion-worklist-auto-ended")).toHaveTextContent(
      "LM317 Regulator is still active in Stockroom",
    );
    // Stopping the pass is not cancelling the capture. Provider decisions remain inside the
    // embedded browser HUD instead of appearing early on every automatic stage.
    expect(screen.queryByRole("button", { name: "Finish Route" })).toBeNull();
    expect(run).toHaveBeenCalledTimes(1);
  });

  it("deduplicates several person-owned routes for the same component", async () => {
    vi.spyOn(api, "captureWorklist").mockResolvedValue(twoRows());
    vi.spyOn(api, "partCadSource").mockResolvedValue(cadSource());
    const samePart = worklist().worklist[0];
    vi.spyOn(api, "captureWorklist").mockResolvedValue({
      ...worklist(),
      worklist: [
        samePart,
        {
          ...samePart,
          route_id: "digikey:snapmagic",
          provider_key: "digikey",
          label: "DigiKey - SnapMagic",
        },
      ],
      worklist_unit: undefined,
      worklist_total: 2,
    });
    const capture = mockCapture();
    renderWorklist();

    expect(await screen.findAllByRole("button", { name: "Get files for LM317 Regulator" })).toHaveLength(1);
    expect(screen.getByText("2 Routes Need You")).toBeInTheDocument();
    expect(screen.getByText("Ultra Librarian + DigiKey - SnapMagic")).toBeInTheDocument();
    expect(screen.getByText(/DigiKey - SnapMagic: no Ultra Librarian sign-in/)).toBeInTheDocument();
    await userEvent.click(await screen.findByRole("button", { name: WORK_THROUGH_ALL }));
    expect(capture.run).toHaveBeenCalledTimes(1);
    expect(capture.run).toHaveBeenCalledWith(
      expect.objectContaining({ partIds: ["lm317"] }),
    );
  });

  it("stops instead of opening every remaining page when a start fails outright", async () => {
    // A capture that never opened a page failed for a reason that repeats identically on the next
    // row, so advancing would walk the whole list on one fault and open nothing.
    vi.spyOn(api, "captureWorklist").mockResolvedValue(twoRows());
    vi.spyOn(api, "partCadSource").mockResolvedValue(cadSource());
    const run = vi.spyOn(api, "runCapture").mockRejectedValue(new Error("no durable runtime"));
    renderWorklist();

    await userEvent.click(await screen.findByRole("button", { name: WORK_THROUGH_ALL }));

    expect(await screen.findByTestId("completion-worklist-auto-ended")).toHaveTextContent(
      "LM317 Regulator could not be started",
    );
    expect(run).toHaveBeenCalledTimes(1);
  });

  it("stops after a post-start failure when no provider handoff ever opened", async () => {
    // Creating a durable batch is not proof that a provider page opened. Repeating the same
    // backend failure across the whole list would produce no useful user trip.
    vi.spyOn(api, "captureWorklist").mockResolvedValue(twoRows());
    vi.spyOn(api, "partCadSource").mockResolvedValue(cadSource());
    const capture = mockCapture([{ event: "error", data: { message: "provider gave nothing" } }]);
    renderWorklist();

    await userEvent.click(await screen.findByRole("button", { name: WORK_THROUGH_ALL }));

    await waitFor(() => expect(capture.run).toHaveBeenCalledTimes(1));
    expect(await screen.findByTestId("completion-worklist-auto-ended")).toHaveTextContent(
      "LM317 Regulator could not be started",
    );
    expect(
      screen.getAllByText(/This capture ended without completing/),
    ).toHaveLength(1);
  });

  it("renders nothing at all when the batch has no worklist projection", async () => {
    vi.spyOn(api, "captureWorklist").mockRejectedValue(new Error("no guided capture"));
    const { container } = renderWorklist();

    expect(container.querySelector("[data-testid='completion-worklist']")).toBeNull();
  });
});
