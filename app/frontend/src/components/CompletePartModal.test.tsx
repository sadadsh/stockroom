import { createElement, useState, type ReactNode } from "react";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { api } from "../api/client";
import { mockCapture } from "../test/captureMocks";
import type { CompletionEvidence, PartDetail } from "../api/types";
import { makeAsset, makeEdaAssets, makePartDetail } from "../test/partFixture";
import { ToastProvider } from "../lib/toast";
import { ThemeProvider } from "../lib/theme";
import { DevModeProvider } from "../lib/devMode";
import { CaptureProvider } from "../lib/capture";
import { CompletePartModal } from "./CompletePartModal";

function wrapper({ children }: { children: ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return createElement(
    QueryClientProvider,
    { client: qc },
    createElement(CaptureProvider, null, createElement(ToastProvider, null, children)),
  );
}

// The copy/icon block needs the dev-mode surface, so it wraps the same query + toast harness in
// ThemeProvider + DevModeProvider (DevModeProvider reads useTheme).
function devWrapper({ children }: { children: ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return createElement(
    QueryClientProvider,
    { client: qc },
    createElement(
      ThemeProvider,
      null,
      createElement(
        DevModeProvider,
        null,
        createElement(CaptureProvider, null, createElement(ToastProvider, null, children)),
      ),
    ),
  );
}

function toggleDevMode() {
  fireEvent.keyDown(window, { key: "D", ctrlKey: true, shiftKey: true });
}

// Built through the shared wire-shaped factory rather than cast. The literal this replaces was
// stale all the way back to schema 1 - flat `symbol`/`footprint`/`model` and a `passive` boolean,
// none of which the record has carried for two schema versions - and `as unknown as PartDetail`
// is what let it keep compiling and keep asserting against a shape the server never sends.
const DETAIL: PartDetail = makePartDetail({
  id: "part1",
  mpn: "BQ24074",
  manufacturer: "Texas Instruments",
  part_class: "component",
  derived: { display_name: "BQ24074", category: "ICs", description: "Li-Ion charger" },
  assets: { kicad: makeEdaAssets() },
});

// The real DTO: every vendor in the owner's trust order, plus the flattened head.
const CAD_SOURCES = [
  {
    key: "digikey",
    label: "DigiKey",
    url: "https://www.digikey.com/en/products/result?keywords=BQ24074",
    tools: ["kicad", "altium"],
    aggregator: true,
    instruction: "Open the CAD Models section, then download for KiCad and for Altium.",
    capture_available: true,
  },
  {
    key: "ultralibrarian",
    label: "Ultra Librarian",
    url: "https://www.ultralibrarian.com/search?queryText=BQ24074",
    tools: ["kicad", "altium"],
    aggregator: false,
    instruction: "Pick the part, choose KiCad and Altium as the export formats, then Download.",
    capture_available: true,
    // The one provider reviewed for unattended capture; every other source is person-driven,
    // which is what decides whether Get Files runs a pass or opens the guided window.
    unattended_capture: true,
  },
  {
    key: "samacsys",
    label: "SamacSys",
    url: "https://componentsearchengine.com/search/BQ24074",
    tools: ["kicad", "altium"],
    aggregator: false,
    instruction: "Open the part, then download the KiCad and Altium models.",
    capture_available: true,
  },
  {
    key: "snapmagic",
    label: "SnapMagic",
    url: "https://www.snapeda.com/search/?q=BQ24074",
    tools: ["kicad", "altium"],
    aggregator: false,
    instruction: "Check the model is manufacturer-verified, then download for KiCad and Altium.",
    capture_available: true,
  },
];

function mockCadSource(
  needs: string[],
  completionEvidence?: CompletionEvidence,
) {
  vi.spyOn(api, "partCadSource").mockResolvedValue({
    url: CAD_SOURCES[0].url,
    mpn: "BQ24074",
    vendor: "DigiKey",
    needs,
    completion_evidence: completionEvidence,
    sources: CAD_SOURCES,
  } as never);
}

afterEach(() => {
  vi.restoreAllMocks();
  delete (window as { pywebview?: unknown }).pywebview;
  Reflect.deleteProperty(window, "__STOCKROOM_HOST__");
  // Token edits set inline CSS vars on <html>; clear them so tests do not leak into each other.
  document.documentElement.removeAttribute("style");
  document.documentElement.removeAttribute("data-theme");
});

const track = (tool: string) => document.querySelector(`[data-track='${tool}']`) as HTMLElement;

describe("CompletePartModal - automatic capture", () => {
  it("lays out the FILES and DETAILS regions with the both-format checklist", async () => {
    mockCadSource(["kicad_symbol", "kicad_footprint", "altium_symbol"]);
    render(<CompletePartModal detail={DETAIL} hasModel={true} onClose={() => {}} />, { wrapper });

    expect(await screen.findByText("Files")).toBeInTheDocument();
    expect(screen.getByText("Details")).toBeInTheDocument();
    expect(await screen.findByRole("button", { name: "Get Files" })).toBeInTheDocument();
    // Each needed row renders under its tool track.
    expect(within(track("KiCad")).getByText("Symbol")).toBeInTheDocument();
    expect(within(track("KiCad")).getByText("Footprint")).toBeInTheDocument();
    expect(within(track("Altium")).getByText("Symbol")).toBeInTheDocument();
    // KiCad 3D Model was not needed here, so it is not listed.
    expect(within(track("KiCad")).queryByText("3D Model")).toBeNull();
  });

  it("marks a requirement received when a capture lands", async () => {
    const user = userEvent.setup();
    mockCadSource(["kicad_symbol", "altium_symbol"]);
    const capture = mockCapture();

    render(<CompletePartModal detail={DETAIL} hasModel={true} onClose={() => {}} />, { wrapper });
    await user.click(await screen.findByRole("button", { name: "Get Files" }));

    // The host callback this used to push into is gone; capture runs in the backend now. So this
    // asserts the modal actually STARTS a capture for this part. What each requirement becomes is
    // decided by the RECORD and is asserted end to end in the backend tests, never by a forward
    // fabricated here.
    await waitFor(() => expect(capture.run).toHaveBeenCalled());
    expect(capture.run).toHaveBeenCalledWith(expect.objectContaining({ partIds: [DETAIL.id] }));
  });

  it("presents one source-agnostic automatic-completion workflow", async () => {
    mockCadSource(["kicad_symbol", "altium_symbol"]);
    render(<CompletePartModal detail={DETAIL} hasModel={true} onClose={() => {}} />, { wrapper });
    expect(
      await screen.findByText(
        "One automatic run reuses verified evidence and stops at the first complete validated KiCad + Altium + STEP package.",
      ),
    ).toBeInTheDocument();
    expect(screen.queryByText("Preferred Source")).toBeNull();
  });

  it("offers coherent network acquisition without a local-file fallback", async () => {
    mockCadSource(["kicad_symbol"]);
    render(<CompletePartModal detail={DETAIL} hasModel={true} onClose={() => {}} />, { wrapper });
    const getFiles = await screen.findByRole("button", { name: "Get Files" });
    expect(getFiles.className).toContain("bg-acc");
    expect(screen.queryByRole("button", { name: "Browse For Files" })).toBeNull();
  });

  it("keeps metadata editable without exposing manual CAD reference fields", async () => {
    const user = userEvent.setup();
    const onEditField = vi.fn();
    mockCadSource(["kicad_symbol", "kicad_footprint"]);
    render(
      <CompletePartModal
        detail={DETAIL}
        hasModel={true}
        onClose={() => {}}
        onEditField={onEditField}
      />,
      { wrapper },
    );
    const dialog = await screen.findByRole("dialog", { name: "Complete this part" });

    expect(within(dialog).queryByLabelText("Library")).toBeNull();
    expect(within(dialog).queryByLabelText("Name")).toBeNull();
    expect(within(dialog).queryByRole("button", { name: "Attach" })).toBeNull();

    await user.click(within(dialog).getByRole("button", { name: "Add Datasheet" }));
    await user.type(within(dialog).getByLabelText("URL"), "https://example.test/bq24074.pdf");
    await user.click(within(dialog).getByRole("button", { name: "Save" }));
    expect(onEditField).toHaveBeenCalledWith("datasheet", "https://example.test/bq24074.pdf");
  });

  it("can refresh with the first complete validated network set after files are complete", async () => {
    const user = userEvent.setup();
    mockCadSource([]);
    const capture = mockCapture([
      {
        event: "result",
        data: {
          result: {
            items: [
              {
                part_id: DETAIL.id,
                mpn: DETAIL.mpn,
                display_name: DETAIL.derived.display_name,
                category: "ICs",
                status: "already-complete",
                needed: [],
                satisfied: [],
                remaining: [],
                retained: 0,
                sources: [],
                notes: [],
                error: "",
                completion_evidence: {
                  state: "verified",
                  manifest_digest:
                    "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
                  reason: "The active pair was reverified from retained evidence.",
                },
                provider_outcomes: [
                  {
                    route_id: "verified-cache:verified-cache",
                    provider_key: "verified-cache",
                    author_key: "verified-cache",
                    label: "Verified Evidence",
                    status: "succeeded-retained",
                    attempted: false,
                    retained: 0,
                    activated: false,
                    reason: "The active pair remains verified.",
                  },
                ],
                collection_complete: true,
              },
            ],
            counts: { "already-complete": 1 },
            retained: 0,
            collection_complete: true,
            stopped: false,
            stop_reason: "",
          },
        },
      },
      { event: "done", data: {} },
    ]);

    render(<CompletePartModal detail={DETAIL} hasModel={true} onClose={() => {}} />, {
      wrapper,
    });

    expect(await screen.findByText("Automatic Completion")).toBeInTheDocument();
    expect(screen.queryByText("Files Reverified")).toBeNull();
    expect(screen.getByRole("button", { name: "Get Files" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Get Files" }));

    await waitFor(() => expect(capture.run).toHaveBeenCalled());
    expect(capture.run).toHaveBeenCalledWith(
      expect.objectContaining({
        partIds: [DETAIL.id],
        vendor: undefined,
        mode: "finish-first",
      }),
    );
    expect(await screen.findByText("Files Reverified")).toBeInTheDocument();
    expect(screen.getByText(/Reverified from sha256:bbbbbbbbbbbbb/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Get Files" })).toBeNull();
    expect(screen.getByRole("button", { name: "Refresh Sources" })).toBeInTheDocument();
    expect(
      await screen.findByText(
        "Collection Complete. Every route is settled. Unavailable means it was checked and had no exact deliverable.",
      ),
    ).toHaveClass("text-t2");
    expect(screen.getByText("Source Results")).toHaveClass("text-t2");
    expect(screen.getByText("Complete")).toHaveClass("text-[var(--c-ok-text)]");
  });

  it("shows each DigiKey author route independently and calls blocked work partial", async () => {
    const user = userEvent.setup();
    mockCadSource([]);
    mockCapture([
      {
        event: "result",
        data: {
          result: {
            items: [
              {
                part_id: DETAIL.id,
                mpn: DETAIL.mpn,
                display_name: DETAIL.derived.display_name,
                category: "ICs",
                status: "already-complete",
                needed: [],
                satisfied: [],
                remaining: [],
                retained: 0,
                sources: [],
                notes: [],
                error: "",
                completion_evidence: {
                  state: "verified",
                  manifest_digest:
                    "sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc",
                  reason: "The active pair was reverified from retained evidence.",
                },
                provider_outcomes: [
                  {
                    route_id: "digikey:digikey-ultralibrarian",
                    provider_key: "digikey",
                    author_key: "digikey-ultralibrarian",
                    label: "DigiKey / Ultra Librarian",
                    status: "unavailable",
                    attempted: true,
                    retained: 0,
                    activated: false,
                    reason: "No exact deliverable was offered.",
                  },
                  {
                    route_id: "digikey:digikey-snapmagic",
                    provider_key: "digikey",
                    author_key: "digikey-snapmagic",
                    label: "DigiKey / SnapMagic",
                    status: "requires-human",
                    attempted: true,
                    retained: 0,
                    activated: false,
                    reason: "DigiKey security verification is still open.",
                  },
                  {
                    route_id: "digikey:digikey-traceparts",
                    provider_key: "digikey",
                    author_key: "digikey-traceparts",
                    label: "DigiKey / TraceParts",
                    status: "not-attempted",
                    attempted: false,
                    retained: 0,
                    activated: false,
                    reason: "Not attempted after the prior route blocked.",
                  },
                ],
                collection_complete: false,
              },
            ],
            counts: { "already-complete": 1 },
            retained: 0,
            collection_complete: false,
            stopped: false,
            stop_reason: "",
          },
        },
      },
      { event: "done", data: {} },
    ]);

    render(<CompletePartModal detail={DETAIL} hasModel={true} onClose={() => {}} />, {
      wrapper,
    });
    await screen.findByText("Automatic Completion");
    await user.click(screen.getByRole("button", { name: "Get Files" }));

    expect(await screen.findByText("Files Reverified")).toBeInTheDocument();
    expect(
      await screen.findByText(
        "Collection Partial. A route requires human input, is blocked or failed, was cancelled, or was not attempted.",
      ),
    ).toHaveClass("text-[var(--c-warn-text)]");
    expect(screen.getByText("Partial")).toHaveClass("text-[var(--c-warn-text)]");
    expect(screen.getByText("DigiKey / Ultra Librarian")).toBeInTheDocument();
    expect(screen.getByText("DigiKey / SnapMagic")).toBeInTheDocument();
    expect(screen.getByText("DigiKey / TraceParts")).toBeInTheDocument();
    expect(screen.getByText("Unavailable")).toHaveClass("text-t2");
    expect(screen.getByText("Security Check Required")).toHaveClass(
      "text-[var(--c-warn-text)]",
    );
    expect(screen.getByText("Not Attempted")).toHaveClass("text-[var(--c-warn-text)]");
    expect(screen.getByText("No exact deliverable was offered.")).toHaveClass("text-t2");
  });

  it("never treats an empty needs projection as completion evidence", async () => {
    mockCadSource([]);

    render(<CompletePartModal detail={DETAIL} hasModel={true} onClose={() => {}} />, {
      wrapper,
    });

    expect(await screen.findByText("Automatic Completion")).toBeInTheDocument();
    expect(
      screen.getByText(
        "No completion evidence is recorded. Run verification before treating this part as complete.",
      ),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Get Files" })).toBeInTheDocument();
    expect(screen.queryByText("Files Reverified")).toBeNull();
    expect(screen.queryByText("CAD Files Not Required")).toBeNull();
  });

  it("renders persistent verified evidence without requiring another capture", async () => {
    mockCadSource([], {
      state: "verified",
      manifest_digest:
        "sha256:eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee",
      reason: "The active projections were re-resolved from retained evidence.",
    });

    render(<CompletePartModal detail={DETAIL} hasModel={true} onClose={() => {}} />, {
      wrapper,
    });

    expect(await screen.findByText("Files Reverified")).toBeInTheDocument();
    expect(screen.getByText(/Reverified from sha256:eeeeeeeeeeeee/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Get Files" })).toBeNull();
    expect(
      document.querySelector('[data-completion-evidence="verified"]'),
    ).not.toBeNull();
  });

  it("renders a not-required verdict distinctly without claiming files were verified", async () => {
    const user = userEvent.setup();
    mockCadSource([]);
    mockCapture([
      {
        event: "result",
        data: {
          result: {
            items: [
              {
                part_id: DETAIL.id,
                mpn: DETAIL.mpn,
                display_name: DETAIL.derived.display_name,
                category: "Mechanical",
                status: "already-complete",
                needed: [],
                satisfied: [],
                remaining: [],
                sources: [],
                notes: [],
                error: "",
                completion_evidence: {
                  state: "not-required",
                  manifest_digest: null,
                  reason: "This mechanical record has no EDA deliverables.",
                },
              },
            ],
            counts: { "already-complete": 1 },
            stopped: false,
            stop_reason: "",
          },
        },
      },
      { event: "done", data: {} },
    ]);

    render(<CompletePartModal detail={DETAIL} hasModel={true} onClose={() => {}} />, {
      wrapper,
    });
    await user.click(await screen.findByRole("button", { name: "Get Files" }));

    expect(await screen.findByText("CAD Files Not Required")).toBeInTheDocument();
    expect(screen.getByText("This mechanical record has no EDA deliverables.")).toBeInTheDocument();
    expect(screen.queryByText("Files Reverified")).toBeNull();
    expect(
      document.querySelector('[data-completion-evidence="not-required"]'),
    ).not.toBeNull();
  });

  it("never shows an asset word as both Added and Needed: DETAILS is metadata-only when FILES owns the assets", async () => {
    // A part that already HAS a KiCad symbol but needs the Altium symbol + footprint. Before the
    // fix, Symbol read "Added" in DETAILS and "Needed" in FILES at once.
    const withSymbol = makePartDetail({
      ...DETAIL,
      assets: { kicad: makeEdaAssets({ symbol: makeAsset({ name: "BQ24074" }) }) },
    });
    mockCadSource(["altium_symbol", "altium_footprint"]);
    render(<CompletePartModal detail={withSymbol} hasModel={true} onClose={() => {}} />, {
      wrapper,
    });
    await waitFor(() => expect(track("Altium")).not.toBeNull());

    // FILES owns the whole asset story: Symbol + Footprint live only under the Altium track, Needed.
    expect(within(track("Altium")).getByText("Symbol")).toBeInTheDocument();
    expect(within(track("Altium")).getByText("Footprint")).toBeInTheDocument();
    expect(within(track("Altium")).getAllByText("Needed")).toHaveLength(2);

    // DETAILS is metadata-only: no Symbol, Footprint, or 3D Model row survives when FILES owns them.
    const details = screen.getByText("Details").closest("section") as HTMLElement;
    expect(within(details).queryByText("Symbol")).toBeNull();
    expect(within(details).queryByText("Footprint")).toBeNull();
    expect(within(details).queryByText("3D Model")).toBeNull();

    // So no asset word carries two conflicting statuses: Symbol appears exactly once, and not "Added".
    expect(screen.getAllByText("Symbol")).toHaveLength(1);
    expect(screen.getAllByText("Footprint")).toHaveLength(1);
  });

  it("hands the capture to the background and closes on Keep Working", async () => {
    const user = userEvent.setup();
    mockCadSource(["kicad_symbol", "altium_symbol"]);
    // The run must still be IN FLIGHT for the hand-off control to exist: "Keep Working" is what
    // you press to leave a capture running and get on with something else. A mock that finished
    // instantly would take the modal straight to done and the button would never render - which
    // would make this test fail for a reason that has nothing to do with the behaviour it guards.
    vi.spyOn(api, "runCapture").mockResolvedValue({
      workflow_batch_id: "batch-background",
      workflow_item_id: "item-background",
      event_cursor: 0,
    });
    vi.spyOn(api, "workflowEvents").mockImplementation(
      () => new Promise(() => undefined),
    );
    const onClose = vi.fn();
    render(<CompletePartModal detail={DETAIL} hasModel={true} onClose={onClose} />, { wrapper });
    await user.click(await screen.findByRole("button", { name: "Get Files" }));
    // once capturing, Keep Working appears and hands off + closes
    const keep = await screen.findByRole("button", { name: "Keep Working" });
    await user.click(keep);
    expect(onClose).toHaveBeenCalled();
  });
});

describe("CompletePartModal - copy + icon adoption", () => {
  it("renders identical text and its three glyphs, with no copy wrappers outside dev mode", async () => {
    mockCadSource(["kicad_symbol", "kicad_footprint"]);
    const { container } = render(
      <CompletePartModal
        detail={DETAIL}
        hasModel={false}
        onClose={() => {}}
        onEditField={() => {}}
      />,
      { wrapper: devWrapper },
    );

    // Subtitle + CAD section render their default text (no override).
    expect(
      await screen.findByText(
        "Stockroom completes remaining data and one verified KiCad + Altium + STEP package.",
      ),
    ).toBeInTheDocument();
    expect(await screen.findByText("Automatic Completion")).toBeInTheDocument();
    // The three glyphs (modal.check on rows, action.download on the CAD button, modal.close on the
    // header button) all draw as <svg> via <Icon>.
    expect(container.querySelectorAll("svg").length).toBeGreaterThanOrEqual(3);
    // Off dev mode a <Text> is a bare string: no editable copy targets exist.
    expect(container.querySelector("[data-copy-id]")).toBeNull();
  });

  it("wraps a representative set of labels as data-copy-id targets in dev mode", async () => {
    mockCadSource(["kicad_symbol", "kicad_footprint"]);
    const { container } = render(
      <CompletePartModal
        detail={DETAIL}
        hasModel={false}
        onClose={() => {}}
        onEditField={() => {}}
      />,
      { wrapper: devWrapper },
    );
    // Wait for the CAD section (async cad-source query) so cad-title / row-symbol are mounted.
    await screen.findByText("Automatic Completion");

    toggleDevMode();

    // A cross-section of the wrapped surface: the subtitle (inline; the header title is the
    // part's own name, not copy), a row label sourced from an array (row-symbol), an
    // array/helper-fed CAD title, and the requirement Add button (req-add).
    expect(container.querySelector('[data-copy-id="modal.completePart.subtitle"]')).not.toBeNull();
    expect(container.querySelector('[data-copy-id="modal.completePart.cad-title"]')).not.toBeNull();
    expect(
      container.querySelector('[data-copy-id="modal.completePart.row-symbol"]'),
    ).not.toBeNull();
    expect(container.querySelector('[data-copy-id="modal.completePart.req-add"]')).not.toBeNull();
  });

  it("keeps the dialog and Close accessible names resolved through useText", async () => {
    mockCadSource([]);
    render(<CompletePartModal detail={DETAIL} hasModel={true} onClose={() => {}} />, {
      wrapper: devWrapper,
    });
    await screen.findByText(
      "Stockroom completes remaining data and one verified KiCad + Altium + STEP package.",
    );

    expect(screen.getByRole("dialog", { name: "Complete this part" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Close" })).toBeInTheDocument();
    toggleDevMode();
    expect(screen.getByRole("dialog", { name: "Complete this part" })).toBeInTheDocument();
  });
});

// ----------------------------------------------------------- one automatic acquisition workflow

const RENDER = () =>
  render(<CompletePartModal detail={DETAIL} hasModel={true} onClose={() => {}} />, { wrapper });

describe("CompletePartModal - one automatic acquisition workflow", () => {
  it("offers one Get Files action with no mode or provider choice", async () => {
    const user = userEvent.setup();
    mockCadSource(["kicad_symbol", "altium_symbol"]);
    const capture = mockCapture();
    RENDER();

    expect(await screen.findByText("Automatic Completion")).toBeInTheDocument();
    expect(screen.queryByText("Preferred Source")).toBeNull();
    expect(screen.queryByRole("button", { name: /Ultra Librarian/ })).toBeNull();
    expect(screen.queryByRole("button", { name: /SnapMagic/ })).toBeNull();

    await user.click(screen.getByRole("button", { name: "Get Files" }));
    await waitFor(() => expect(capture.run).toHaveBeenCalled());
    expect(capture.run).toHaveBeenCalledWith(
      expect.objectContaining({
        partIds: [DETAIL.id],
        vendor: undefined,
        mode: "finish-first",
      }),
    );
  });

  it("keeps provider work inside Stockroom without duplicating the embedded browser HUD", async () => {
    const user = userEvent.setup();
    mockCadSource(["kicad_symbol"]);
    vi.spyOn(api, "runCapture").mockImplementation(() => new Promise(() => {}));
    RENDER();
    await screen.findByText("Automatic Completion");

    await user.click(screen.getByRole("button", { name: "Get Files" }));

    expect(await screen.findByText("Provider Work Is Active")).toBeInTheDocument();
    expect(screen.getByText("Starting")).toBeInTheDocument();
    expect(
      screen.getByText(/provider needs your sign-in, security check, format choice/i),
    ).toBeInTheDocument();
    expect(screen.queryByText(/default browser/i)).toBeNull();
    expect(screen.queryByText(/separate window/i)).toBeNull();
    expect(screen.queryByRole("button", { name: "Finish Route" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Skip This Part" })).toBeNull();
  });

  it("queues selected downloads into the exact active durable provider task", async () => {
    const user = userEvent.setup();
    mockCadSource(["kicad_symbol", "altium_symbol"]);
    const pickFiles = vi.fn().mockResolvedValue(["D:\\Downloads\\BQ24074.zip"]);
    Object.defineProperty(window, "__STOCKROOM_HOST__", {
      configurable: true,
      value: { pickFiles },
    });
    vi.spyOn(api, "runCapture").mockResolvedValue({
      workflow_batch_id: "batch-selected-files",
      workflow_item_id: "item-selected-files",
      event_cursor: 0,
    });
    let eventCalls = 0;
    vi.spyOn(api, "workflowEvents").mockImplementation(async () => {
      eventCalls += 1;
      if (eventCalls > 1) return new Promise(() => undefined);
      return {
        schema_version: 1,
        batch: {
          id: "batch-selected-files",
          kind: "guided_capture",
          status: "running",
          created_at: 1,
          updated_at: 2,
          total_items: 1,
          item_counts: { running: 1 },
          cancellation: null,
          actions: {
            can_pause: false,
            can_resume: false,
            can_retry: false,
            can_cancel: true,
          },
        },
        events: [
          {
            sequence: 1,
            item_id: "item-selected-files",
            stage_id: null,
            kind: "stage_started",
            details: { stage: "cad_acquisition" },
            created_at: 2,
          },
        ],
        cursor: {
          after_sequence: 0,
          next_sequence: 1,
          limit: 200,
          has_more: false,
        },
      } as never;
    });
    const activeUrl = "https://www.digikey.com/en/products/detail/ti/BQ24074";
    vi.spyOn(api, "captureWorkflow").mockResolvedValue({
      workflow_batch_id: "batch-selected-files",
      workflow_item_id: "item-selected-files",
      part_id: DETAIL.id,
      mode: "finish-first",
      vendor: null,
      background: false,
      active_route: {
        vendor: "digikey",
        detail_url: activeUrl,
        route_token: "route-selected-files",
      },
      initial_needs: ["kicad_symbol", "altium_symbol"],
      report: null,
    });
    const attach = vi.spyOn(api, "attachSelectedCaptureFiles").mockResolvedValue({
      part_id: DETAIL.id,
      workflow_item_id: "item-selected-files",
      accepted: true,
      queued_files: 1,
    });
    RENDER();

    await user.click(await screen.findByRole("button", { name: "Get Files" }));
    // The button appears only after the durable batch and its exact provider route have both
    // propagated through the capture store. Full-suite Windows runners can be busy with other
    // WebView/Git fixtures, so use an explicit integration timeout instead of the DOM library's
    // one-second default. This still fails if any route field never arrives.
    await user.click(
      await screen.findByRole(
        "button",
        { name: "Use Downloaded Files" },
        { timeout: 5_000 },
      ),
    );

    expect(pickFiles).toHaveBeenCalledWith("cad-recovery");
    await waitFor(() =>
      expect(attach).toHaveBeenCalledWith({
        partId: DETAIL.id,
        workflowItemId: "item-selected-files",
        paths: ["D:\\Downloads\\BQ24074.zip"],
        vendor: "digikey",
        detailUrl: activeUrl,
        routeToken: "route-selected-files",
      }),
    );
    expect(
      await screen.findByText(/queued 1 selected file for validation in this completion task/i),
    ).toBeInTheDocument();
  }, 15_000);
});

// ------------------------------------------------------ the window contract every sibling has
//
// This window declared `role="dialog" aria-modal` while ignoring Escape, never trapping Tab,
// never returning focus, and closing on a backdrop `click` - so a text-selection drag that
// released on the scrim threw away whatever had been typed into it.

// The opener lives OUTSIDE the window and the provider tree outlives it, matching the real tree:
// DetailPanel mounts this window only while it is open, and the global capture store survives
// every open and close.
function OpenableWindow({ detail }: { detail: PartDetail }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button type="button" onClick={() => setOpen(true)}>
        Complete This Part
      </button>
      {open ? (
        <CompletePartModal detail={detail} hasModel={true} onClose={() => setOpen(false)} />
      ) : null}
    </>
  );
}

describe("CompletePartModal - dismiss, focus, and close paths", () => {
  it("moves focus into the dialog and keeps Tab inside it", async () => {
    mockCadSource(["kicad_symbol"]);
    render(<CompletePartModal detail={DETAIL} hasModel={true} onClose={() => {}} />, { wrapper });
    const dialog = await screen.findByRole("dialog", { name: "Complete this part" });

    expect(dialog).toHaveFocus();

    // Tab off the last control wraps to the first rather than escaping to inert background.
    const focusable = dialog.querySelectorAll<HTMLElement>(
      'button:not([disabled]), [href], input:not([disabled]), [tabindex]:not([tabindex="-1"])',
    );
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    last.focus();
    fireEvent.keyDown(window, { key: "Tab" });
    expect(first).toHaveFocus();

    first.focus();
    fireEvent.keyDown(window, { key: "Tab", shiftKey: true });
    expect(last).toHaveFocus();
  });

  it("closes on Escape and returns focus to the control that opened it", async () => {
    const user = userEvent.setup();
    mockCadSource(["kicad_symbol"]);
    render(<OpenableWindow detail={DETAIL} />, { wrapper });

    const opener = screen.getByRole("button", { name: "Complete This Part" });
    await user.click(opener);
    await screen.findByRole("dialog", { name: "Complete this part" });

    fireEvent.keyDown(window, { key: "Escape" });

    await waitFor(() =>
      expect(screen.queryByRole("dialog", { name: "Complete this part" })).toBeNull(),
    );
    expect(opener).toHaveFocus();
  });

  it("hands an in-flight capture to the background when Escape closes the window", async () => {
    const user = userEvent.setup();
    mockCadSource(["kicad_symbol"]);
    vi.spyOn(api, "runCapture").mockResolvedValue({
      workflow_batch_id: "batch-escape",
      workflow_item_id: "item-escape",
      event_cursor: 0,
    });
    vi.spyOn(api, "workflowEvents").mockImplementation(() => new Promise(() => undefined));
    const onClose = vi.fn();
    render(<CompletePartModal detail={DETAIL} hasModel={true} onClose={onClose} />, { wrapper });

    await user.click(await screen.findByRole("button", { name: "Get Files" }));
    await screen.findByText("Provider Work Is Active");
    fireEvent.keyDown(window, { key: "Escape" });

    // Escape is a close path like every other, so it must go through the same hand-off, not drop
    // a running capture on the floor.
    expect(onClose).toHaveBeenCalled();
  });

  it("keeps a selection drag that ends on the backdrop from discarding the window", async () => {
    mockCadSource(["kicad_symbol"]);
    const onClose = vi.fn();
    render(<CompletePartModal detail={DETAIL} hasModel={true} onClose={onClose} />, { wrapper });
    const dialog = await screen.findByRole("dialog", { name: "Complete this part" });
    const backdrop = dialog.parentElement as HTMLElement;

    // A drag that STARTS on the window's own text and releases on the scrim: the click event
    // lands on the backdrop, and the old `onClick` handler read that as "dismiss".
    fireEvent.mouseDown(within(dialog).getByText(DETAIL.derived.display_name));
    fireEvent.mouseUp(backdrop);
    fireEvent.click(backdrop);
    expect(onClose).not.toHaveBeenCalled();

    // A press that genuinely begins on the scrim still dismisses.
    fireEvent.mouseDown(backdrop);
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});

// The header counter is a completion claim, so VA-001 governs it: nothing in this window may read
// complete without digest-bound evidence.
const WITH_DATASHEET: PartDetail = makePartDetail({
  ...DETAIL,
  datasheet: { source_url: "https://example.test/bq24074.pdf" },
});

describe("CompletePartModal - the header counter", () => {
  it("still counts the CAD package when FILES shows no checklist", async () => {
    // An exact identity opens FILES, which takes Symbol, Footprint, and 3D Model out of DETAILS.
    // With an empty `needs` projection nothing replaced them in the checklist, so the counter fell
    // to the four metadata rows and read "4 / 4" - on the same card that says no evidence exists.
    mockCadSource([]);
    render(<CompletePartModal detail={WITH_DATASHEET} hasModel={true} onClose={() => {}} />, {
      wrapper,
    });

    expect(await screen.findByText("Automatic Completion")).toBeInTheDocument();
    expect(
      screen.getByText(
        "No completion evidence is recorded. Run verification before treating this part as complete.",
      ),
    ).toBeInTheDocument();
    expect(screen.getByText("4 / 5")).toBeInTheDocument();
    expect(screen.queryByText("4 / 4")).toBeNull();
  });

  it("counts the CAD package as done only once evidence proves it", async () => {
    mockCadSource([], {
      state: "verified",
      manifest_digest:
        "sha256:ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff",
      reason: "The active projections were re-resolved from retained evidence.",
    });
    render(<CompletePartModal detail={WITH_DATASHEET} hasModel={true} onClose={() => {}} />, {
      wrapper,
    });

    expect(await screen.findByText("Files Reverified")).toBeInTheDocument();
    expect(screen.getByText("5 / 5")).toBeInTheDocument();
  });

  it("counts every rendered checklist row alongside the package itself", async () => {
    mockCadSource(["kicad_symbol", "kicad_footprint", "altium_symbol"]);
    render(<CompletePartModal detail={WITH_DATASHEET} hasModel={true} onClose={() => {}} />, {
      wrapper,
    });
    await screen.findByText("Automatic Completion");

    // Four metadata rows, three waiting file rows, and the package the card is still proving.
    expect(await screen.findByText("4 / 8")).toBeInTheDocument();
  });
});

describe("CompletePartModal - per-file toasts", () => {
  it("toasts each received file once per capture, never once per reopen", async () => {
    const user = userEvent.setup();
    mockCadSource(["kicad_symbol"]);
    mockCapture();
    render(<OpenableWindow detail={DETAIL} />, { wrapper });

    await user.click(screen.getByRole("button", { name: "Complete This Part" }));
    await user.click(await screen.findByRole("button", { name: "Get Files" }));
    expect(await screen.findByText("KiCad symbol received")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Done" }));
    await user.click(screen.getByRole("button", { name: "Complete This Part" }));
    await screen.findByText("Files Reverified");

    // `received` belongs to the global capture store, not to this window. Reopening must not
    // replay a run that already reported - the toast still on screen is the original, not a
    // second copy of it.
    expect(screen.getAllByText("KiCad symbol received")).toHaveLength(1);
  });
});

describe("CompletePartModal - one capture slot", () => {
  it("disables another part instead of orphaning the active capture", async () => {
    const user = userEvent.setup();
    mockCadSource(["kicad_symbol"]);
    // No submission resolves, so the first part's capture is genuinely still in flight.
    const run = vi.spyOn(api, "runCapture").mockImplementation(() => new Promise(() => undefined));
    const other: PartDetail = makePartDetail({
      ...DETAIL,
      id: "part2",
      mpn: "LM317",
      derived: { display_name: "LM317" },
    });

    const { rerender } = render(
      <CompletePartModal detail={DETAIL} hasModel={true} onClose={() => {}} />,
      { wrapper },
    );
    await user.click(await screen.findByRole("button", { name: "Get Files" }));
    await screen.findByText("Provider Work Is Active");

    rerender(<CompletePartModal detail={other} hasModel={true} onClose={() => {}} />);
    expect(await screen.findByRole("button", { name: "Another Part Is Running" })).toBeDisabled();
    expect(screen.getByTitle(/Finish the active completion for BQ24074 first/)).toBeInTheDocument();
    expect(run).toHaveBeenCalledTimes(1);
  });
});
