import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
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

  it("lists the record's parametric specs in a Specifications section, hiding asset keys (B1)", () => {
    wrap(
      <DetailPanel
        detail={detail({
          specs: {
            Resistance: "1.1 kOhms",
            Tolerance: "1%",
            Symbol: "Device:R",
            Footprint: "Resistor_SMD:R_0603_1608Metric",
            "3D Model": "Resistor_SMD.3dshapes/R_0603.wrl",
            pinout: [{ pin: "1", name: "A" }],
          },
        })}
        {...BASE}
      />,
    );
    // the two real specs are listed
    expect(screen.getByText("Resistance")).toBeInTheDocument();
    expect(screen.getByText("1.1 kOhms")).toBeInTheDocument();
    expect(screen.getByText("Tolerance")).toBeInTheDocument();
    // the count reflects only the real specs (asset keys + pinout excluded)
    expect(screen.getByText("(2)")).toBeInTheDocument();
    // asset references are shown as Files cards, never listed as specs
    expect(screen.queryByText("Device:R")).not.toBeInTheDocument();
  });

  it("collapses a deep spec list and expands it on Show all (B2)", async () => {
    const many: Record<string, string> = {};
    for (let i = 0; i < 15; i++) many[`Spec ${i}`] = `value ${i}`;
    wrap(<DetailPanel detail={detail({ specs: many })} {...BASE} />);
    // collapsed to the first 10; the deep ones are hidden behind Show all
    expect(screen.getByText("Spec 0")).toBeInTheDocument();
    expect(screen.queryByText("Spec 14")).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Show All 15" }));
    expect(screen.getByText("Spec 14")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Show Fewer" })).toBeInTheDocument();
  });

  it("shows a passive's 3D model as present via its footprint, not Not Linked (A8)", () => {
    // A passive owns no model.file but inherits the KiCad stock footprint's built-in 3D model,
    // which the model.glb endpoint resolves from the footprint; the card must read as present.
    wrap(
      <DetailPanel
        detail={detail({
          passive: true,
          model: null,
          footprint: { lib: "Resistor_SMD", name: "R_0603_1608Metric" },
        })}
        {...BASE}
      />,
    );
    expect(
      screen.getByRole("button", { name: "Open 3D Model Preview" }),
    ).toBeInTheDocument();
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

describe("DetailPanel asset tool pills", () => {
  it("renders a tool pill on each present asset, mapping the tool value to a nice label", () => {
    wrap(
      <DetailPanel
        detail={detail({
          symbol: { lib: "Device", name: "R", tool: "kicad" },
          footprint: { lib: "Resistor_SMD", name: "R_0603_1608Metric", tool: "altium" },
          model: { file: "models/r.step", tool: "kicad" },
        })}
        {...BASE}
      />,
    );
    // "altium" Title Cases to "Altium" (data-driven for future Altium support)
    expect(screen.getByText("Altium")).toBeInTheDocument();
    // "kicad" maps to the proper "KiCad" casing, on the symbol + 3D model cards
    expect(screen.getAllByText("KiCad").length).toBe(2);
  });

  it("defaults an absent tool field to KiCad on every present asset", () => {
    // the base fixture carries symbol/footprint/model with no tool field
    wrap(<DetailPanel detail={detail()} {...BASE} />);
    expect(screen.getAllByText("KiCad")).toHaveLength(3);
  });
});

describe("DetailPanel attach-after affordance", () => {
  it("opens the attach modal for a missing symbol and posts the entered lib + name", async () => {
    const onAttachSymbol = vi.fn();
    wrap(
      <DetailPanel
        detail={detail({ symbol: null })}
        {...BASE}
        onAttachSymbol={onAttachSymbol}
        onAttachFootprint={vi.fn()}
      />,
    );
    // the missing symbol card is now an Attach button (only one such button exists yet)
    await userEvent.click(screen.getByRole("button", { name: "Attach Symbol" }));

    const dialog = await screen.findByRole("dialog", { name: "Attach Symbol" });
    await userEvent.type(within(dialog).getByLabelText("Library"), "Device");
    await userEvent.type(within(dialog).getByLabelText("Name"), "R");
    await userEvent.click(within(dialog).getByRole("button", { name: "Attach Symbol" }));

    expect(onAttachSymbol).toHaveBeenCalledWith("Device", "R");
  });

  it("disables Attach until a name is entered (the backend gate requires it)", async () => {
    wrap(
      <DetailPanel
        detail={detail({ footprint: null })}
        {...BASE}
        onAttachSymbol={vi.fn()}
        onAttachFootprint={vi.fn()}
      />,
    );
    await userEvent.click(screen.getByRole("button", { name: "Attach Footprint" }));
    const dialog = await screen.findByRole("dialog", { name: "Attach Footprint" });
    // name empty -> submit disabled
    expect(within(dialog).getByRole("button", { name: "Attach Footprint" })).toBeDisabled();
    await userEvent.type(within(dialog).getByLabelText("Name"), "R_0603_1608Metric");
    expect(within(dialog).getByRole("button", { name: "Attach Footprint" })).toBeEnabled();
  });

  it("offers no Attach affordance in a read-only panel (no handler given)", () => {
    wrap(<DetailPanel detail={detail({ symbol: null })} {...BASE} />);
    expect(
      screen.queryByRole("button", { name: "Attach Symbol" }),
    ).not.toBeInTheDocument();
    // it degrades to the honest Not Linked state
    expect(screen.getByText("Not Linked")).toBeInTheDocument();
  });
});

describe("DetailPanel sourcing vendor label", () => {
  it("shows a human distributor name derived from the URL, not a lowercase 'manual'", () => {
    wrap(
      <DetailPanel
        detail={detail({
          purchase: [
            {
              vendor: "manual",
              url: "https://www.mouser.com/ProductDetail/Vishay/MCT06030D1101BP500",
              price_breaks: [],
              stock: null,
              currency: "",
              fetched_at: "",
            },
          ],
        })}
        {...BASE}
      />,
    );
    expect(screen.getByText("Mouser")).toBeInTheDocument();
    expect(screen.queryByText("manual")).toBeNull();
  });

  it("Title Cases an unknown stored vendor", () => {
    wrap(
      <DetailPanel
        detail={detail({
          purchase: [
            {
              vendor: "acme parts",
              url: "https://acme.example.com/p/1",
              price_breaks: [],
              stock: null,
              currency: "",
              fetched_at: "",
            },
          ],
        })}
        {...BASE}
      />,
    );
    // known-vendor map misses, so it Title Cases the stored name's first letter
    expect(screen.getByText("Acme parts")).toBeInTheDocument();
  });
});
