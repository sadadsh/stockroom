import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { api } from "../api/client";
import type { PartDetail } from "../api/types";
import { DEV_ID_BY_ID } from "../lib/devIds";
import { ThemeProvider } from "../lib/theme";
import { ToastProvider } from "../lib/toast";
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
      // the capture-needs query behind the Complete Part trigger (Altium gaps).
      partCadSource: vi.fn(),
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
  mockApi.partCadSource.mockResolvedValue({
    url: null,
    mpn: "",
    vendor: "DigiKey",
    needs: [],
  } as never);
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
      <ThemeProvider>
        <ToastProvider>{ui}</ToastProvider>
      </ThemeProvider>
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
    // the two real specs are listed (units prettified: kOhms -> kΩ for display)
    expect(screen.getByText("Resistance")).toBeInTheDocument();
    expect(screen.getByText("1.1 kΩ")).toBeInTheDocument();
    expect(screen.getByText("Tolerance")).toBeInTheDocument();
    // the count reflects only the real specs (asset keys + pinout excluded)
    expect(screen.getByText("2")).toBeInTheDocument();
    // asset references are shown as Files cards, never listed as specs
    expect(screen.queryByText("Device:R")).not.toBeInTheDocument();
  });

  it("renders every spec at once (no collapse) (B2)", () => {
    const many: Record<string, string> = {};
    for (let i = 0; i < 15; i++) many[`Spec ${i}`] = `value ${i}`;
    wrap(<DetailPanel detail={detail({ specs: many })} {...BASE} />);
    // the spec sheet is never collapsed: every spec shows at once, shallow AND deep (the
    // attributes band shows a capped highlight glance, but the spec sheet does not collapse).
    expect(screen.getByText("Spec 0")).toBeInTheDocument();
    expect(screen.getByText("Spec 7")).toBeInTheDocument();
    expect(screen.getByText("Spec 14")).toBeInTheDocument();
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
    // Pinout now lives in the workbench's Pinout tab; open it before filtering.
    await userEvent.click(screen.getByRole("tab", { name: "Pinout" }));
    await userEvent.type(screen.getByRole("textbox", { name: /filter pins/i }), "vcc");
    expect(screen.getByText("VCC")).toBeInTheDocument();

    rerender(view(B)); // switch parts: the filter must reset so B's pins show
    expect(screen.getByText("GND")).toBeInTheDocument();
    expect(screen.getByText("OUT")).toBeInTheDocument();
    expect(screen.queryByText(/no pins match/i)).not.toBeInTheDocument();
  });
});

describe("DetailPanel attach-after affordance", () => {
  it("adds a missing symbol by lib + name through the one Complete Part window", async () => {
    const onAttachSymbol = vi.fn();
    wrap(
      <DetailPanel
        detail={detail({ symbol: null })}
        {...BASE}
        onAttachSymbol={onAttachSymbol}
        onAttachFootprint={vi.fn()}
      />,
    );
    // the scattered per-tile attach buttons are gone; one Complete Part action opens the window
    await userEvent.click(screen.getByRole("button", { name: /Complete Part/ }));
    const dialog = await screen.findByRole("dialog", { name: /complete this part/i });
    await userEvent.click(within(dialog).getByRole("button", { name: "Add Symbol" }));
    // Library is pre-filled "Device" for a symbol; enter the device name and attach
    await userEvent.type(within(dialog).getByLabelText("Name"), "R");
    await userEvent.click(within(dialog).getByRole("button", { name: "Attach" }));

    expect(onAttachSymbol).toHaveBeenCalledWith("Device", "R");
  });

  it("disables the attach action until a footprint lib + name are entered", async () => {
    wrap(
      <DetailPanel
        detail={detail({ footprint: null })}
        {...BASE}
        onAttachSymbol={vi.fn()}
        onAttachFootprint={vi.fn()}
      />,
    );
    await userEvent.click(screen.getByRole("button", { name: /Complete Part/ }));
    const dialog = await screen.findByRole("dialog", { name: /complete this part/i });
    await userEvent.click(within(dialog).getByRole("button", { name: "Add Footprint" }));
    // both fields empty -> Attach disabled
    expect(within(dialog).getByRole("button", { name: "Attach" })).toBeDisabled();
    await userEvent.type(within(dialog).getByLabelText("Library"), "Resistor_SMD");
    await userEvent.type(within(dialog).getByLabelText("Name"), "R_0603_1608Metric");
    expect(within(dialog).getByRole("button", { name: "Attach" })).toBeEnabled();
  });

  it("offers no Complete Part affordance in a read-only panel (no handlers)", () => {
    wrap(<DetailPanel detail={detail({ symbol: null })} {...BASE} />);
    expect(
      screen.queryByRole("button", { name: /Complete Part/ }),
    ).not.toBeInTheDocument();
    // it degrades to the honest Not Linked state on the tile
    expect(screen.getByText("Not Linked")).toBeInTheDocument();
  });

  it("offers Complete Part for a KiCad-complete part that still needs Altium assets", async () => {
    mockApi.partCadSource.mockResolvedValue({
      url: "https://app.ultralibrarian.com/search?queryText=LM358DR",
      mpn: "LM358DR",
      vendor: "UltraLibrarian",
      needs: ["altium_symbol", "altium_footprint"],
    } as never);
    // detail() is fully KiCad-complete (symbol + footprint + model) and BASE.missing is [],
    // so without the Altium gap the trigger would not show.
    wrap(<DetailPanel detail={detail()} {...BASE} onAttachSymbol={vi.fn()} />);
    const trigger = await screen.findByRole("button", { name: /Complete Part/ });
    expect(trigger).toHaveTextContent("Altium symbol");
    expect(trigger).toHaveTextContent("Altium footprint");
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

describe("DetailPanel dev-mode ids (IDSYS-01)", () => {
  it("carries the panel + workbench data-dev-id anchors, each a known catalog id", () => {
    const { container } = wrap(<DetailPanel detail={detail()} {...BASE} />);
    for (const id of ["detail.root", "detail.workbench"]) {
      const el = container.querySelector(`[data-dev-id="${id}"]`);
      expect(el).not.toBeNull();
      expect(DEV_ID_BY_ID.has(id)).toBe(true);
    }
  });

  it("emits the derived tab-strip ids via TabStrip devIdBase, resolving via DEV_ID_BY_ID", () => {
    const { container } = wrap(<DetailPanel detail={detail()} {...BASE} />);
    // The tab strip carries its group id and the per-tab derived ids (locked decision 2):
    // detail.tabs on the tablist, detail.tab-specs on the first tab.
    const strip = container.querySelector('[data-dev-id="detail.tabs"]');
    expect(strip).not.toBeNull();
    const specsTab = container.querySelector('[data-dev-id="detail.tab-specs"]');
    expect(specsTab).not.toBeNull();
    // both derived ids are real catalog entries, not invented strings
    expect(DEV_ID_BY_ID.has("detail.tabs")).toBe(true);
    expect(DEV_ID_BY_ID.has("detail.tab-specs")).toBe(true);
  });
});

describe("DetailPanel spec sheet + identity", () => {
  it("drops catalog metadata from the spec sheet but keeps the real parametric specs", () => {
    wrap(
      <DetailPanel
        detail={detail({
          category: "Resistors",
          specs: {
            Resistance: "1.1 kOhms",
            Manufacturer: "Acme Corp",
            "Country of Origin": "Malaysia",
            Packaging: "Reel",
            "US Tariff %": "8",
          },
        })}
        {...BASE}
      />,
    );
    // the real spec shows (unit prettified for display)
    expect(screen.getByText("Resistance")).toBeInTheDocument();
    expect(screen.getByText("1.1 kΩ")).toBeInTheDocument();
    // the distributor-page metadata never reaches the physical spec sheet
    expect(screen.queryByText("Country of Origin")).not.toBeInTheDocument();
    expect(screen.queryByText("Malaysia")).not.toBeInTheDocument();
    expect(screen.queryByText("Reel")).not.toBeInTheDocument();
    expect(screen.queryByText("US Tariff %")).not.toBeInTheDocument();
  });

  it("headlines an opaque part (IC) by its display name, not its bare MPN, and reads the MPN once", () => {
    wrap(
      <DetailPanel
        detail={detail({
          category: "ICs",
          display_name: "Dual Op-Amp LM358",
          mpn: "LM358DR",
          specs: {},
        })}
        {...BASE}
      />,
    );
    // deriveTitle falls back to the MPN for a spec-less IC; the header prefers the human name
    expect(
      screen.getByRole("heading", { name: "Dual Op-Amp LM358" }),
    ).toBeInTheDocument();
    // the MPN still reads once, on the identity line below the headline
    expect(screen.getByText("LM358DR")).toBeInTheDocument();
    // and it is NOT the headline (no duplicate identity)
    expect(
      screen.queryByRole("heading", { name: "LM358DR" }),
    ).not.toBeInTheDocument();
  });

  it("headlines a passive by its derived title", () => {
    wrap(
      <DetailPanel
        detail={detail({
          category: "Resistors",
          display_name: "10k 1% 0603",
          mpn: "RC0603",
          specs: { Resistance: "10 kOhms", Tolerance: "1%" },
        })}
        {...BASE}
      />,
    );
    expect(
      screen.getByRole("heading", { name: "10 kΩ ±1% Resistor" }),
    ).toBeInTheDocument();
  });
});
