import { createElement, type ReactNode } from "react";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { api } from "../api/client";
import type { PartDetail, StagingCandidate } from "../api/types";
import { ToastProvider } from "../lib/toast";
import { ThemeProvider } from "../lib/theme";
import { DevModeProvider } from "../lib/devMode";
import { CompletePartModal } from "./CompletePartModal";

function wrapper({ children }: { children: ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return createElement(
    QueryClientProvider,
    { client: qc },
    createElement(ToastProvider, null, children),
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
      createElement(DevModeProvider, null, createElement(ToastProvider, null, children)),
    ),
  );
}

function toggleDevMode() {
  fireEvent.keyDown(window, { key: "D", ctrlKey: true, shiftKey: true });
}

const DETAIL = {
  id: "part1",
  display_name: "BQ24074",
  category: "ICs",
  mpn: "BQ24074",
  manufacturer: "Texas Instruments",
  description: "Li-Ion charger",
  symbol: null,
  footprint: null,
  model: null,
  datasheet: null,
  passive: false,
} as unknown as PartDetail;

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

function mockCadSource(needs: string[]) {
  vi.spyOn(api, "partCadSource").mockResolvedValue({
    url: "https://app.ultralibrarian.com/search?queryText=BQ24074",
    mpn: "BQ24074",
    vendor: "UltraLibrarian",
    needs,
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

describe("CompletePartModal - guided capture", () => {
  it("renders the both-format checklist and the guided button", async () => {
    mockCadSource(["kicad_symbol", "kicad_footprint", "altium_symbol"]);
    render(<CompletePartModal detail={DETAIL} hasModel={true} onClose={() => {}} />, { wrapper });

    expect(await screen.findByText("CAD Files")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Get CAD Files (KiCad + Altium)" }),
    ).toBeInTheDocument();
    const kicadGroup = screen.getByText("KiCad").parentElement as HTMLElement;
    const altiumGroup = screen.getByText("Altium").parentElement as HTMLElement;
    // Each needed row renders under its tool group.
    expect(within(kicadGroup).getByText("Symbol")).toBeInTheDocument();
    expect(within(kicadGroup).getByText("Footprint")).toBeInTheDocument();
    expect(within(altiumGroup).getByText("Symbol")).toBeInTheDocument();
    // KiCad 3D Model was not needed here, so it is not listed.
    expect(within(kicadGroup).queryByText("3D Model")).toBeNull();
  });

  it("marks a requirement received when a capture lands", async () => {
    const user = userEvent.setup();
    mockCadSource(["kicad_symbol", "altium_symbol"]);
    const open = vi.fn().mockResolvedValue("tok");
    (window as unknown as { pywebview: { api: { open_cad_download: typeof open } } }).pywebview = {
      api: { open_cad_download: open },
    };
    vi.spyOn(api, "assetsInspect").mockResolvedValue({ job_id: "j1" });
    vi.spyOn(api, "openJobStream").mockResolvedValue(
      streamOf([
        `event: result\ndata: {"result":${JSON.stringify([CANDIDATE])}}\n\n`,
        "event: done\ndata: {}\n\n",
      ]),
    );
    vi.spyOn(api, "assetsCommit").mockResolvedValue({} as never);

    render(<CompletePartModal detail={DETAIL} hasModel={true} onClose={() => {}} />, { wrapper });
    await screen.findByText("CAD Files");
    await user.click(screen.getByRole("button", { name: "Get CAD Files (KiCad + Altium)" }));

    await act(async () => {
      window.__STOCKROOM_CAD_DOWNLOAD__!({
        path: "C:\\Downloads\\BQ24074.zip",
        token: "tok",
        requirements: ["kicad_symbol"],
      });
      await Promise.resolve();
    });

    // The KiCad Symbol row (the first "Symbol" row) flips to received.
    await waitFor(() => {
      const kicadGroup = screen.getByText("KiCad").parentElement as HTMLElement;
      expect(within(kicadGroup).getByText("Received")).toBeInTheDocument();
    });
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

    // Title + CAD section render their default text (no override).
    expect(await screen.findByText("Complete This Part")).toBeInTheDocument();
    expect(await screen.findByText("CAD Files")).toBeInTheDocument();
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
    await screen.findByText("CAD Files");

    toggleDevMode();

    // A cross-section of the wrapped surface: the title (inline), a row label sourced from an array
    // (row-symbol), an array/helper-fed CAD title, and the requirement Add button (req-add).
    expect(container.querySelector('[data-copy-id="modal.completePart.title"]')).not.toBeNull();
    expect(container.querySelector('[data-copy-id="modal.completePart.cad-title"]')).not.toBeNull();
    expect(container.querySelector('[data-copy-id="modal.completePart.row-symbol"]')).not.toBeNull();
    expect(container.querySelector('[data-copy-id="modal.completePart.req-add"]')).not.toBeNull();
  });

  it("keeps the dialog and Close accessible names resolved through useText", async () => {
    mockCadSource([]);
    render(<CompletePartModal detail={DETAIL} hasModel={true} onClose={() => {}} />, {
      wrapper: devWrapper,
    });
    await screen.findByText("Complete This Part");

    expect(screen.getByRole("dialog", { name: "Complete this part" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Close" })).toBeInTheDocument();
    toggleDevMode();
    expect(screen.getByRole("dialog", { name: "Complete this part" })).toBeInTheDocument();
  });
});
