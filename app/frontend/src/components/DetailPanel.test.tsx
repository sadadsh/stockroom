import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { api } from "../api/client";
import type { PartDetail } from "../api/types";
import { ThemeProvider } from "../lib/theme";
import { DetailPanel } from "./DetailPanel";

// The Files cards fetch live SVG thumbnails; mock the previews so nothing hits network.
vi.mock("../api/client", async (importActual) => {
  const actual = await importActual<typeof import("../api/client")>();
  return {
    ...actual,
    api: {
      ...actual.api,
      previewSvg: vi.fn(),
      modelGlb: vi.fn(),
      // the History section (M6k) fetches the part's timeline; mock it so nothing
      // hits network and it renders its honest empty state by default.
      partHistory: vi.fn(),
      partDiff: vi.fn(),
    },
  };
});

// three.js is verified in the Windows pixel gate; mock the scene so opening the 3D
// tab does not need a WebGL context here.
vi.mock("../lib/threeScene", () => ({ mountModelScene: vi.fn(() => vi.fn()) }));

const mockApi = vi.mocked(api);

beforeEach(() => {
  mockApi.previewSvg.mockResolvedValue(new Blob(["<svg/>"], { type: "image/svg+xml" }));
  mockApi.modelGlb.mockResolvedValue(new Uint8Array([0x67, 0x6c, 0x54, 0x46]).buffer);
  mockApi.partHistory.mockResolvedValue({ commits: [], count: 0 });
});

function detail(over: Partial<PartDetail> = {}): PartDetail {
  return {
    id: "lm358",
    display_name: "LM358",
    category: "ICs",
    description: "Dual op-amp",
    tags: [],
    mpn: "LM358DR",
    manufacturer: "TI",
    datasheet: null,
    purchase: [],
    symbol: { lib: "SR-ICs", name: "LM358" },
    footprint: { lib: "SR-ICs", name: "SOIC-8" },
    model: { file: "models/lm358.step" },
    provenance: null,
    hashes: null,
    enrichment: {},
    specs: {},
    ...over,
  };
}

function wrap(ui: ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <ThemeProvider>{ui}</ThemeProvider>
    </QueryClientProvider>,
  );
}

const BASE = {
  isLoading: false,
  error: null as Error | null,
  missing: [] as string[],
  isComplete: true,
};

describe("DetailPanel files previews (M6d)", () => {
  it("opens the preview modal on the clicked kind when a Files card is clicked", async () => {
    mockApi.previewSvg.mockResolvedValue(new Blob(["<svg/>"], { type: "image/svg+xml" }));
    wrap(<DetailPanel detail={detail()} {...BASE} />);

    // no modal until a card is clicked
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Open Symbol Preview" }));

    const dialog = await screen.findByRole("dialog", { name: "Previews for LM358" });
    expect(dialog).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Symbol" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
  });

  it("opens directly on the 3D tab from the 3D Model card", async () => {
    mockApi.modelGlb.mockResolvedValue(new Uint8Array([0x67, 0x6c, 0x54, 0x46]).buffer);
    wrap(<DetailPanel detail={detail()} {...BASE} />);

    await userEvent.click(screen.getByRole("button", { name: "Open 3D Model Preview" }));

    expect(await screen.findByRole("dialog")).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "3D Model" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
  });

  it("does not make a missing file's card clickable", () => {
    wrap(<DetailPanel detail={detail({ model: null })} {...BASE} />);
    expect(
      screen.queryByRole("button", { name: "Open 3D Model Preview" }),
    ).not.toBeInTheDocument();
  });
});

describe("DetailPanel git timeline (M6k)", () => {
  it("renders the History section and mounts the part timeline", async () => {
    mockApi.partHistory.mockResolvedValue({
      commits: [
        { sha: "c".repeat(40), subject: "Add lm358", author: "Sadad", iso_date: "2026-07-13T12:00:00-04:00" },
      ],
      count: 1,
    });
    wrap(<DetailPanel detail={detail()} {...BASE} />);
    expect(screen.getByText("History")).toBeInTheDocument();
    // the timeline is wired to this part id, so its commit renders
    expect(await screen.findByText("Add lm358")).toBeInTheDocument();
    expect(mockApi.partHistory).toHaveBeenCalledWith("lm358");
  });
});

describe("DetailPanel pinout (M6i)", () => {
  it("renders the pinout table when the record has a persisted pinout", () => {
    wrap(
      <DetailPanel
        detail={detail({
          specs: {
            pinout: [
              { pin: "1", name: "OUT1" },
              { pin: "2", name: "IN1-" },
            ],
          },
          enrichment: { pinout: { source: "datasheet", confidence: "high" } },
        })}
        {...BASE}
      />,
    );
    expect(screen.getByText("Pinout")).toBeInTheDocument();
    expect(screen.getByText("2 Pins")).toBeInTheDocument();
    expect(screen.getByText("OUT1")).toBeInTheDocument();
    expect(screen.getByText(/datasheet · high/i)).toBeInTheDocument();
  });

  it("shows no Pinout section when the record has no pinout", () => {
    wrap(<DetailPanel detail={detail({ specs: {} })} {...BASE} />);
    expect(screen.queryByText("Pinout")).not.toBeInTheDocument();
  });

  it("resets the pinout filter when switching to a different part (keyed per part)", async () => {
    // Without a per-part key the single PinoutViewer instance carries its filter
    // across a part switch (the same leak the sibling EnrichPanel is keyed to avoid).
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const view = (d: PartDetail) => (
      <QueryClientProvider client={qc}>
        <ThemeProvider>
          <DetailPanel detail={d} {...BASE} />
        </ThemeProvider>
      </QueryClientProvider>
    );
    const A = detail({ id: "a", specs: { pinout: [{ pin: "1", name: "VCC" }] } });
    const B = detail({
      id: "b",
      specs: { pinout: [{ pin: "1", name: "GND" }, { pin: "2", name: "OUT" }] },
    });
    const { rerender } = render(view(A));
    await userEvent.type(screen.getByRole("textbox", { name: /filter pins/i }), "vcc");
    expect(screen.getByText("VCC")).toBeInTheDocument();

    rerender(view(B)); // switch parts: the filter must reset so B's pins show
    expect(screen.getByText("GND")).toBeInTheDocument();
    expect(screen.getByText("OUT")).toBeInTheDocument();
    expect(screen.queryByText(/no pins match/i)).not.toBeInTheDocument();
  });
});
