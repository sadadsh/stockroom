import { createElement, type ReactNode } from "react";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { api } from "../api/client";
import { mockCapture } from "../test/captureMocks";
import type { PartDetail, StagingCandidate } from "../api/types";
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

const CANDIDATE: StagingCandidate = {
  vendor: "ultralibrarian",
  symbol_lib_path: "/tmp/x.kicad_sym",
  symbol_name: "BQ24074",
  footprint_variants: [],
  chosen_footprint_index: 0,
  model_path: null,
  datasheet_path: null,
  display_name: "BQ24074",
  entry_name: "BQ24074",
  category: "IC",
  mpn: "BQ24074",
  manufacturer: "TI",
  description: "charger",
  tags: [],
  purchase: [],
  gaps: [],
};

function streamOf(chunks: string[]): ReadableStream<Uint8Array> {
  const enc = new TextEncoder();
  return new ReadableStream<Uint8Array>({
    start(controller) {
      for (const c of chunks) controller.enqueue(enc.encode(c));
      controller.close();
    },
  });
}

// The real DTO: every vendor in the owner's trust order, plus the flattened head.
const CAD_SOURCES = [
  {
    key: "digikey", label: "DigiKey",
    url: "https://www.digikey.com/en/products/result?keywords=BQ24074",
    tools: ["kicad", "altium"], aggregator: true,
    instruction: "Open the CAD Models section, then download for KiCad and for Altium.",
  },
  {
    key: "ultralibrarian", label: "Ultra Librarian",
    url: "https://www.ultralibrarian.com/search?queryText=BQ24074",
    tools: ["kicad", "altium"], aggregator: false,
    instruction: "Pick the part, choose KiCad and Altium as the export formats, then Download.",
  },
  {
    key: "samacsys", label: "SamacSys",
    url: "https://componentsearchengine.com/search/BQ24074",
    tools: ["kicad", "altium"], aggregator: false,
    instruction: "Open the part, then download the KiCad and Altium models.",
  },
  {
    key: "snapmagic", label: "SnapMagic",
    url: "https://www.snapeda.com/search/?q=BQ24074",
    tools: ["kicad", "altium"], aggregator: false,
    instruction: "Check the model is manufacturer-verified, then download for KiCad and Altium.",
  },
];

function mockCadSource(needs: string[]) {
  vi.spyOn(api, "partCadSource").mockResolvedValue({
    url: CAD_SOURCES[0].url,
    mpn: "BQ24074",
    vendor: "DigiKey",
    needs,
    sources: CAD_SOURCES,
  } as never);
}

afterEach(() => {
  vi.restoreAllMocks();
  delete (window as { pywebview?: unknown }).pywebview;
  delete window.__STOCKROOM_CAD_DOWNLOAD__;
  // Token edits set inline CSS vars on <html>; clear them so tests do not leak into each other.
  document.documentElement.removeAttribute("style");
  document.documentElement.removeAttribute("data-theme");
});

const track = (tool: string) => document.querySelector(`[data-track='${tool}']`) as HTMLElement;

describe("CompletePartModal - guided capture", () => {
  it("lays out the FILES and DETAILS regions with the both-format checklist", async () => {
    mockCadSource(["kicad_symbol", "kicad_footprint", "altium_symbol"]);
    render(<CompletePartModal detail={DETAIL} hasModel={true} onClose={() => {}} />, { wrapper });

    expect(await screen.findByText("Files")).toBeInTheDocument();
    expect(screen.getByText("Details")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Get Files" })).toBeInTheDocument();
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
    vi.spyOn(api, "assetsInspect").mockResolvedValue({ job_id: "j1" });
    vi.spyOn(api, "openJobStream").mockResolvedValue(
      streamOf([
        `event: result\ndata: {"result":${JSON.stringify([CANDIDATE])}}\n\n`,
        "event: done\ndata: {}\n\n",
      ]),
    );
    vi.spyOn(api, "assetsCommit").mockResolvedValue({} as never);

    render(<CompletePartModal detail={DETAIL} hasModel={true} onClose={() => {}} />, { wrapper });
    await screen.findByText("Files");
    await user.click(screen.getByRole("button", { name: "Get Files" }));

    // The host callback this used to push into is gone; capture runs in the backend now. So this
    // asserts the modal actually STARTS a capture for this part. What each requirement becomes is
    // decided by the RECORD and is asserted end to end in the backend tests, never by a forward
    // fabricated here.
    await waitFor(() => expect(capture.run).toHaveBeenCalled());
    expect(capture.run).toHaveBeenCalledWith(
      expect.objectContaining({ partIds: [DETAIL.id] }),
    );
  });

  it("names DigiKey in the guided-capture subline, never a placeholder vendor", async () => {
    mockCadSource(["kicad_symbol", "altium_symbol"]);
    render(<CompletePartModal detail={DETAIL} hasModel={true} onClose={() => {}} />, { wrapper });
    await screen.findByText("Files");
    expect(screen.getByText(/from DigiKey\.?$/)).toBeInTheDocument();
    expect(screen.queryByText(/the vendor/)).toBeNull();
  });

  it("makes Get Files the accent primary and Browse For Files the quiet secondary", async () => {
    mockCadSource(["kicad_symbol"]);
    render(<CompletePartModal detail={DETAIL} hasModel={true} onClose={() => {}} />, { wrapper });
    const getFiles = await screen.findByRole("button", { name: "Get Files" });
    const browse = screen.getByRole("button", { name: "Browse For Files" });
    // the accent variant carries the solid accent background; the quiet fallback does not
    expect(getFiles.className).toContain("bg-acc");
    expect(browse.className).not.toContain("bg-acc");
  });

  it("never shows an asset word as both Added and Needed: DETAILS is metadata-only when FILES owns the assets", async () => {
    // A part that already HAS a KiCad symbol but needs the Altium symbol + footprint. Before the
    // fix, Symbol read "Added" in DETAILS and "Needed" in FILES at once.
    const withSymbol = makePartDetail({
      ...DETAIL,
      assets: { kicad: makeEdaAssets({ symbol: makeAsset({ name: "BQ24074" }) }) },
    });
    mockCadSource(["altium_symbol", "altium_footprint"]);
    render(<CompletePartModal detail={withSymbol} hasModel={true} onClose={() => {}} />, { wrapper });
    await screen.findByText("Files");

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
    vi.spyOn(api, "runCapture").mockResolvedValue({ job_id: "job-1" });
    vi.spyOn(api, "openJobStream").mockImplementation(() => new Promise(() => {}) as never);
    const onClose = vi.fn();
    render(<CompletePartModal detail={DETAIL} hasModel={true} onClose={onClose} />, { wrapper });
    await screen.findByText("Files");
    await user.click(screen.getByRole("button", { name: "Get Files" }));
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
        onAttachSymbol={() => {}}
        onAttachFootprint={() => {}}
      />,
      { wrapper: devWrapper },
    );

    // Subtitle + CAD section render their default text (no override).
    expect(
      await screen.findByText("Add the files and data this part still needs."),
    ).toBeInTheDocument();
    expect(await screen.findByText("Guided Capture")).toBeInTheDocument();
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
        onAttachSymbol={() => {}}
        onAttachFootprint={() => {}}
      />,
      { wrapper: devWrapper },
    );
    // Wait for the CAD section (async cad-source query) so cad-title / row-symbol are mounted.
    await screen.findByText("Guided Capture");

    toggleDevMode();

    // A cross-section of the wrapped surface: the subtitle (inline; the header title is the
    // part's own name, not copy), a row label sourced from an array (row-symbol), an
    // array/helper-fed CAD title, and the requirement Add button (req-add).
    expect(container.querySelector('[data-copy-id="modal.completePart.subtitle"]')).not.toBeNull();
    expect(container.querySelector('[data-copy-id="modal.completePart.cad-title"]')).not.toBeNull();
    expect(container.querySelector('[data-copy-id="modal.completePart.row-symbol"]')).not.toBeNull();
    expect(container.querySelector('[data-copy-id="modal.completePart.req-add"]')).not.toBeNull();
  });

  it("keeps the dialog and Close accessible names resolved through useText", async () => {
    mockCadSource([]);
    render(<CompletePartModal detail={DETAIL} hasModel={true} onClose={() => {}} />, {
      wrapper: devWrapper,
    });
    await screen.findByText("Add the files and data this part still needs.");

    expect(screen.getByRole("dialog", { name: "Complete this part" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Close" })).toBeInTheDocument();
    toggleDevMode();
    expect(screen.getByRole("dialog", { name: "Complete this part" })).toBeInTheDocument();
  });
});

// ------------------------------------------------------- choosing WHERE the files come from
//
// The control the four-vendor module existed for and nothing rendered. Before this the route
// resolved a single DigiKey link, so a person who wanted Ultra Librarian's manufacturer-verified
// model had no way to say so.

const RENDER = () =>
  render(<CompletePartModal detail={DETAIL} hasModel={true} onClose={() => {}} />, { wrapper });

// The picker's own buttons, found through the group's heading rather than a testid: this repo
// carries `data-dev-id`, not `data-testid`, and querying the wrong attribute is a test that fails
// for a reason unrelated to the thing it is about.
const vendorGroup = () =>
  screen.getByText("Download From").parentElement!.querySelector("div")!.parentElement!;
const vendorButton = (name: RegExp) =>
  within(vendorGroup()).getByRole("button", { name });

describe("CompletePartModal - vendor choice", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  it("offers every vendor, in the owner's trust order", async () => {
    mockCadSource(["kicad_symbol", "altium_symbol"]);
    RENDER();
    await screen.findByText("Download From");

    const names = within(vendorGroup())
      .getAllByRole("button")
      .map((b) => b.textContent!.replace("hosts all three", "").trim());
    expect(names).toEqual(["DigiKey", "Ultra Librarian", "SamacSys", "SnapMagic"]);
  });

  it("says DigiKey HOSTS the others rather than implying a fourth library", async () => {
    mockCadSource(["kicad_symbol"]);
    RENDER();
    await screen.findByText("Download From");

    expect(vendorButton(/DigiKey/)).toHaveTextContent("hosts all three");
    expect(vendorButton(/SamacSys/)).not.toHaveTextContent("hosts all three");
  });

  it("opens the vendor that was CHOSEN, not the default", async () => {
    mockCadSource(["kicad_symbol"]);
    const capture = mockCapture();
    RENDER();
    await screen.findByText("Download From");

    await userEvent.click(vendorButton(/Ultra Librarian/));
    await userEvent.click(screen.getByRole("button", { name: "Get Files" }));

    await waitFor(() => expect(capture.run).toHaveBeenCalled());
    expect(capture.run).toHaveBeenCalledWith(
      expect.objectContaining({ vendor: "ultralibrarian" }),
    );
  });

  it("remembers the choice, because over 90 parts one decision beats ninety", async () => {
    mockCadSource(["kicad_symbol"]);
    const { unmount } = RENDER();
    await screen.findByText("Download From");
    await userEvent.click(vendorButton(/SamacSys/));
    unmount();

    mockCadSource(["kicad_symbol"]);
    RENDER();
    await screen.findByText("Download From");

    expect(vendorButton(/SamacSys/)).toHaveAttribute("aria-pressed", "true");
  });

  it("falls back to the trust order's head when the remembered vendor is not offered", async () => {
    // A stored key from a build that knew a vendor this one does not must not open nowhere.
    window.localStorage.setItem("stockroom.capture.vendor", "a-vendor-that-retired");
    mockCadSource(["kicad_symbol"]);
    RENDER();
    await screen.findByText("Download From");

    expect(vendorButton(/DigiKey/)).toHaveAttribute("aria-pressed", "true");
  });

  it("names the CHOSEN vendor in the subline, so the sentence matches the button", async () => {
    mockCadSource(["kicad_symbol"]);
    RENDER();
    await screen.findByText("Download From");

    await userEvent.click(vendorButton(/SnapMagic/));

    expect(await screen.findByText(/from SnapMagic\.?$/)).toBeInTheDocument();
  });
});
