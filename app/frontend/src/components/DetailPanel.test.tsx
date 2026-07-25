import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { api } from "../api/client";
import type { PartDetail } from "../api/types";
import { DEV_ID_BY_ID } from "../lib/devIds";
import { ThemeProvider } from "../lib/theme";
import { ToastProvider } from "../lib/toast";
import { CaptureProvider } from "../lib/capture";
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
      // the per-part sourcing refresh job (POST .../refresh + its SSE stream).
      refreshSourcing: vi.fn(),
      openJobStream: vi.fn(),
      // the Altium 3D embed: whether it can run here, and running it.
      altiumEmbedCapability: vi.fn(),
      altiumEmbedModel: vi.fn(),
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
  // Altium present and idle by default, so a case that cares about a BLOCKED state has to say so
  // rather than passing because the default happened to be unavailable.
  mockApi.altiumEmbedCapability.mockResolvedValue({
    installed: true,
    binary: "C:/Program Files/Altium/AD26/X2.EXE",
    requires_tool_installed: true,
    reason: "A 3D body is written into the footprint's .PcbLib by Altium itself, so embedding needs Altium installed on this machine.",
    busy: "",
    available: true,
  } as never);
  mockApi.altiumEmbedModel.mockResolvedValue({} as never);
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
    eda: { kicad: { symbol: SYM, footprint: FP, model: MODEL } },
    provenance: null,
    hashes: null,
    enrichment: {},
    specs: {},
    ...over,
  };
}

// The default KiCad asset set the fixture carries; cases override one slot at a time.
const SYM = { lib: "SR-ICs", name: "LM358", file: "" };
const FP = { lib: "SR-ICs", name: "SOIC-8", file: "" };
const MODEL = { lib: "", name: "", file: "models/lm358.step" };

function wrap(ui: ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <ThemeProvider>
        <CaptureProvider>
          <ToastProvider>{ui}</ToastProvider>
        </CaptureProvider>
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
    wrap(<DetailPanel detail={detail({ eda: { kicad: { symbol: SYM, footprint: FP, model: null } } })} {...BASE} />);
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
          eda: {
            kicad: { symbol: null, footprint: { lib: "Resistor_SMD", name: "R_0603_1608Metric", file: "" }, model: null },
          },
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
    expect(screen.getByText("Timeline")).toBeInTheDocument();
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
          <CaptureProvider>
            <ToastProvider>
              <DetailPanel detail={d} {...BASE} />
            </ToastProvider>
          </CaptureProvider>
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
        detail={detail({ eda: { kicad: { symbol: null, footprint: FP, model: MODEL } } })}
        {...BASE}
        onAttachSymbol={onAttachSymbol}
        onAttachFootprint={vi.fn()}
      />,
    );
    // readiness is tucked in a popover: open it, then the one Complete Part action opens the window
    await userEvent.click(screen.getByRole("button", { name: /CAD/ }));
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
        detail={detail({ eda: { kicad: { symbol: SYM, footprint: null, model: MODEL } } })}
        {...BASE}
        onAttachSymbol={vi.fn()}
        onAttachFootprint={vi.fn()}
      />,
    );
    await userEvent.click(screen.getByRole("button", { name: /CAD/ }));
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
    wrap(<DetailPanel detail={detail({ eda: { kicad: { symbol: null, footprint: FP, model: MODEL } } })} {...BASE} />);
    expect(
      screen.queryByRole("button", { name: /Complete Part/ }),
    ).not.toBeInTheDocument();
    // it degrades to the honest Not Linked state on the tile
    expect(screen.getByText("Not Linked")).toBeInTheDocument();
  });

  it("offers Complete Part for a KiCad-complete part that still needs Altium assets", async () => {
    // detail() is fully KiCad-complete (symbol + footprint + model) with NO altium_* refs, so the
    // Altium gap comes straight off the record (assetReadiness reads altium_symbol/altium_footprint,
    // not the cad-source query) and the trigger names it.
    wrap(<DetailPanel detail={detail()} {...BASE} onAttachSymbol={vi.fn()} />);
    await userEvent.click(screen.getByRole("button", { name: /CAD/ }));
    const trigger = await screen.findByRole("button", { name: /Complete Part/ });
    expect(trigger).toHaveTextContent("Altium Symbol");
    expect(trigger).toHaveTextContent("Altium Footprint");
  });

  it("shows CAD Complete once BOTH the KiCad and Altium assets are on the record", () => {
    // the regression the owner hit: a part with its Altium libraries attached stayed on
    // "CAD Incomplete" forever because readiness read the KiCad fields for Altium.
    const complete = detail({
      eda: {
        kicad: { symbol: SYM, footprint: FP, model: MODEL },
        altium: {
          symbol: { lib: "p.SchLib", name: "P", file: "" },
          footprint: { lib: "p.PcbLib", name: "P", file: "" },
          model: null,
        },
      },
    });
    wrap(<DetailPanel detail={complete} {...BASE} onAttachSymbol={vi.fn()} />);
    expect(screen.getByText("Complete")).toBeInTheDocument();
    expect(screen.queryByText("Incomplete")).not.toBeInTheDocument();
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
    // the vendor now shows in two legitimate places: the Links row (a quick product link) and
    // the Sourcing tab (the pricing detail), so assert it is present, not that it is unique.
    expect(screen.getAllByText("Mouser").length).toBeGreaterThan(0);
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
    // known-vendor map misses, so it Title Cases the stored name's first letter (present in both
    // the Links row and the Sourcing tab)
    expect(screen.getAllByText("Acme parts").length).toBeGreaterThan(0);
  });
});

describe("DetailPanel sourcing refresh", () => {
  // POST /api/library/parts/{id}/refresh existed since M6 with no way to reach it from the
  // UI (the 2026-07-23 wiring audit). The Sourcing section header now carries the trigger:
  // one click re-pulls price/stock/lifecycle from the distributor APIs as a write-lane job.
  it("offers Refresh Sourcing when the part has an MPN and starts the job on click", async () => {
    mockApi.refreshSourcing.mockResolvedValue({ job_id: "j1" });
    mockApi.openJobStream.mockResolvedValue(
      new ReadableStream<Uint8Array>({
        start(controller) {
          controller.enqueue(
            new TextEncoder().encode("event: done\ndata: {}\n\n"),
          );
          controller.close();
        },
      }),
    );
    const user = userEvent.setup();
    const { container } = wrap(<DetailPanel detail={detail()} {...BASE} />);

    const btn = container.querySelector('[data-dev-id="detail.sourcing-refresh"]');
    expect(btn).not.toBeNull();
    await user.click(btn as HTMLElement);

    expect(mockApi.refreshSourcing).toHaveBeenCalledWith("lm358");
  });

  it("offers no refresh without an MPN (nothing to look up by)", () => {
    const { container } = wrap(<DetailPanel detail={detail({ mpn: "" })} {...BASE} />);
    expect(container.querySelector('[data-dev-id="detail.sourcing-refresh"]')).toBeNull();
  });
});

describe("DetailPanel dev-mode ids (IDSYS-01)", () => {
  it("carries the panel + workbench data-dev-id anchors, each a known catalog id", () => {
    const { container } = wrap(<DetailPanel detail={detail()} {...BASE} />);
    for (const id of ["detail.root", "detail.identity"]) {
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
    // The distributor-page metadata never reaches the PHYSICAL spec sheet. Scoped to the sheet
    // rather than the whole document since Batch 3: the procurement facts (origin, tariff,
    // packaging) are real vendor data the owner asked to stop discarding, so they now render in the
    // commercial column's Trade And Compliance block instead of being dropped on the floor. The
    // rule this test protects is "the spec sheet is physical parameters", and that still holds.
    const sheet = document.querySelector('[data-dev-id="detail.specs"]')!;
    for (const label of ["Country of Origin", "Malaysia", "Reel", "US Tariff %"]) {
      expect(sheet.textContent).not.toContain(label);
    }
    // ...and they are NOT lost: the same values are in the trade block
    const trade = document.querySelector('[data-dev-id="detail.trade"]')!;
    expect(trade.textContent).toContain("Country of Origin");
    expect(trade.textContent).toContain("Malaysia");
    expect(trade.textContent).toContain("US Tariff %");
    expect(trade.textContent).toContain("Reel");
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

describe("DetailPanel element removal", () => {
  it("offers per-element Remove chips in the CAD popover and confirms before detaching", async () => {
    mockApi.detachAsset = vi.fn().mockResolvedValue({} as never);
    const user = userEvent.setup();
    const { container } = wrap(
      <DetailPanel
        detail={detail({ datasheet: { file: "x.pdf", source_url: "", fetched_at: "" } })}
        {...BASE}
        onEditField={() => {}}
      />,
    );
    await user.click(screen.getByRole("button", { name: /cad/i }));
    const chips = container.querySelectorAll('[data-dev-id="detail.remove-asset"]');
    expect(chips.length).toBeGreaterThan(0);
    await user.click(
      // the chip appends a close glyph, and the label names WHOSE 3D model it is
      [...chips].find((c) => c.textContent?.startsWith("KiCad 3D Model")) as HTMLElement,
    );
    // in-window confirm, then the detach fires. The kind is the `<tool>_<asset kind>`
    // vocabulary from the EDA registry, so the 3D model chip names WHOSE model it is.
    await user.click(await screen.findByRole("button", { name: /^remove$/i }));
    await waitFor(() =>
      expect(mockApi.detachAsset).toHaveBeenCalledWith("lm358", "kicad_model"),
    );
  });
});


describe("Altium 3D embed (punch 16)", () => {
  // A part with the full Altium pair and a KiCad 3D model file: the exact state where the .PcbLib
  // exists to write into and a model exists to write.
  const ALTIUM_READY = {
    kicad: { symbol: SYM, footprint: FP, model: MODEL },
    altium: {
      symbol: { lib: "lm358.SchLib", name: "LM358", file: "" },
      footprint: { lib: "lm358.PcbLib", name: "SOIC-8", file: "" },
      model: null,
    },
  };

  async function openReadiness(over: Partial<PartDetail> = {}) {
    wrap(<DetailPanel detail={detail(over)} {...BASE} />);
    await userEvent.click(screen.getByRole("button", { name: /CAD/ }));
  }

  function byDevId(id: string) {
    return document.querySelector(`[data-dev-id="${id}"]`);
  }

  it("offers the embed action when there is a footprint to write into and a model to write", async () => {
    await openReadiness({ eda: ALTIUM_READY });
    const action = await waitFor(() => {
      const el = byDevId("detail.embed3d");
      expect(el).not.toBeNull();
      expect(el).not.toBeDisabled();
      return el as HTMLButtonElement;
    });
    expect(action).toHaveTextContent("Embed 3D Model");
    expect(byDevId("detail.embed3d-blocked")).toBeNull();
  });

  it("runs the embed for this part when the action is clicked", async () => {
    // Drive the actual control, not the handler: a wired-looking button that calls nothing is the
    // failure mode this catches.
    await openReadiness({ eda: ALTIUM_READY });
    const action = await waitFor(() => {
      const el = byDevId("detail.embed3d") as HTMLButtonElement;
      expect(el).not.toBeDisabled();
      return el;
    });
    await userEvent.click(action);
    expect(mockApi.altiumEmbedModel).toHaveBeenCalledWith("lm358", false);
  });

  it("explains that the Altium library must be attached first, rather than sitting inert", async () => {
    await openReadiness({ eda: { kicad: { symbol: SYM, footprint: FP, model: MODEL } } });
    expect(byDevId("detail.embed3d")).toBeDisabled();
    expect(byDevId("detail.embed3d-blocked")).toHaveTextContent(/Attach the Altium library first/);
  });

  it("explains that a 3D model file is needed first", async () => {
    await openReadiness({
      eda: { ...ALTIUM_READY, kicad: { symbol: SYM, footprint: FP, model: null } },
    });
    expect(byDevId("detail.embed3d")).toBeDisabled();
    expect(byDevId("detail.embed3d-blocked")).toHaveTextContent(/Add a 3D model file first/);
  });

  it("gives a KiCad-only peer the registry's reason instead of a control that does nothing", async () => {
    mockApi.altiumEmbedCapability.mockResolvedValue({
      installed: false,
      binary: "",
      requires_tool_installed: true,
      reason: "A 3D body is written into the footprint's .PcbLib by Altium itself, so embedding needs Altium installed on this machine.",
      busy: "",
      available: false,
    } as never);
    await openReadiness({ eda: ALTIUM_READY });
    await waitFor(() =>
      expect(byDevId("detail.embed3d-blocked")).toHaveTextContent(/needs Altium installed/),
    );
    expect(byDevId("detail.embed3d")).toBeDisabled();
  });

  it("says a windowed Altium is holding the license seat", async () => {
    mockApi.altiumEmbedCapability.mockResolvedValue({
      installed: true,
      binary: "C:/x/X2.EXE",
      requires_tool_installed: true,
      reason: "",
      busy: "Altium Designer",
      available: false,
    } as never);
    await openReadiness({ eda: ALTIUM_READY });
    await waitFor(() =>
      expect(byDevId("detail.embed3d-blocked")).toHaveTextContent(/Close Altium first/),
    );
  });

  it("shows the embedded confirmation, and no action, once the container really carries it", async () => {
    await openReadiness({
      eda: {
        ...ALTIUM_READY,
        altium: {
          ...ALTIUM_READY.altium,
          model: { lib: "lm358.PcbLib", name: "SOIC-8", file: "models/lm358.step" },
        },
      },
    });
    expect(byDevId("detail.embed3d-done")).toHaveTextContent(/3D Model embedded/);
    expect(byDevId("detail.embed3d")).toBeNull();
  });

  it("shows the 3D gap as an ACTION, and never as a blocker on Altium readiness", async () => {
    // How the re-baselined rule surfaces at the layer the user sees, stated deliberately because
    // the two obvious alternatives are both wrong:
    //  - the gap must NOT join the Altium "needs" list, because a missing 3D body does not stop a
    //    footprint from placing, and listing it would turn every Altium part red;
    //  - it must NOT join the Complete Part needs either, because that window opens a CAPTURE
    //    session and an Altium 3D body cannot be fetched from a vendor. It is embedded from the
    //    file the part already holds, which is a different action entirely.
    // So the gap is communicated by the presence of the embed action next to a READY Altium row.
    await openReadiness({ eda: ALTIUM_READY });
    await waitFor(() => expect(byDevId("detail.embed3d")).not.toBeNull());
    const readiness = byDevId("detail.readiness") as HTMLElement;
    // BOTH tool rows read Ready: the 3D gap is real and actionable without making Altium unready.
    expect(within(readiness).getAllByText("Ready")).toHaveLength(2);
    expect(within(readiness).queryByText(/Complete Part/)).toBeNull();
  });

  it("offers nothing for a passive, which inherits the stock footprint's own 3D body", async () => {
    await openReadiness({ passive: true, eda: ALTIUM_READY });
    expect(byDevId("detail.embed3d")).toBeNull();
    expect(byDevId("detail.embed3d-done")).toBeNull();
  });
});

// -- Alternates (punch 9 + punch 2): every value a source offered and lost with is on the record
// now, so the panel has to SHOW it and let the user swap which one is in force. Before this the
// loser was never persisted at all, so there was nothing to show.
describe("DetailPanel alternates", () => {
  const withTwoDescriptions = () =>
    detail({
      description: "3A buck",
      alternates: {
        description: [
          { value: "3A buck", source: "mouser", confidence: "high" },
          { value: "Step-Down Regulator, 3 A", source: "digikey", confidence: "high" },
        ],
      },
    });

  it("says how many answers a field has, without spending space until asked", async () => {
    wrap(<DetailPanel detail={withTwoDescriptions()} {...BASE} />);
    expect(screen.getByRole("button", { name: /2 Sources/i })).toBeTruthy();
    // the other distributor's wording stays out of the way until the disclosure is opened
    expect(screen.queryByText("Step-Down Regulator, 3 A")).toBeNull();
  });

  it("shows each answer with the distributor that gave it once opened", async () => {
    const user = userEvent.setup();
    wrap(<DetailPanel detail={withTwoDescriptions()} {...BASE} />);
    await user.click(screen.getByRole("button", { name: /2 Sources/i }));
    expect(screen.getByText("Step-Down Regulator, 3 A")).toBeTruthy();
    expect(screen.getByText("DigiKey")).toBeTruthy();
    expect(screen.getAllByText("Mouser").length).toBeGreaterThan(0);
  });

  it("swaps the stored description to the answer the user picks", async () => {
    const user = userEvent.setup();
    const onEditField = vi.fn();
    wrap(
      <DetailPanel detail={withTwoDescriptions()} {...BASE} onEditField={onEditField} />,
    );
    await user.click(screen.getByRole("button", { name: /2 Sources/i }));
    await user.click(screen.getByRole("button", { name: /Use DigiKey/i }));
    expect(onEditField).toHaveBeenCalledWith("description", "Step-Down Regulator, 3 A");
  });

  it("offers no swap for the answer already in force", async () => {
    const user = userEvent.setup();
    wrap(
      <DetailPanel detail={withTwoDescriptions()} {...BASE} onEditField={vi.fn()} />,
    );
    await user.click(screen.getByRole("button", { name: /2 Sources/i }));
    expect(screen.queryByRole("button", { name: /Use Mouser/i })).toBeNull();
  });

  it("shows nothing at all for a part whose sources agreed", () => {
    wrap(<DetailPanel detail={detail({ description: "3A buck" })} {...BASE} />);
    expect(screen.queryByRole("button", { name: /Sources/i })).toBeNull();
  });

  it("swaps a SPEC value through the specs seam, not the field seam", async () => {
    const user = userEvent.setup();
    const onUseSpecValue = vi.fn();
    wrap(
      <DetailPanel
        detail={detail({
          specs: { Tolerance: "1%" },
          alternates: {
            Tolerance: [
              { value: "1%", source: "mouser", confidence: "high" },
              { value: "5%", source: "digikey", confidence: "high" },
            ],
          },
        })}
        {...BASE}
        onUseSpecValue={onUseSpecValue}
      />,
    );
    await user.click(screen.getByRole("button", { name: /2 Sources/i }));
    await user.click(screen.getByRole("button", { name: /Use DigiKey/i }));
    expect(onUseSpecValue).toHaveBeenCalledWith("Tolerance", "5%", "digikey");
  });
});

describe("DetailPanel alternates comparison", () => {
  it("does not offer to use the value it is already using, even when presentation rewrote it", async () => {
    // Tolerance "1%" RENDERS as "±1%" (applySign). Comparing the alternate against the presented
    // string made the in-force value look like a different answer, so the panel offered "Use
    // Mouser" for the value Mouser had already won with. Caught in a real screenshot, not by a
    // passing test - the description case that the other tests cover is never prettified.
    const user = userEvent.setup();
    wrap(
      <DetailPanel
        detail={detail({
          specs: { Tolerance: "1%" },
          alternates: {
            Tolerance: [
              { value: "1%", source: "mouser", confidence: "high" },
              { value: "2%", source: "digikey", confidence: "high" },
            ],
          },
        })}
        {...BASE}
        onUseSpecValue={vi.fn()}
      />,
    );
    expect(screen.getByText("±1%")).toBeTruthy();  // the prettifier really did run
    await user.click(screen.getByRole("button", { name: /2 Sources/i }));
    expect(screen.queryByRole("button", { name: /Use Mouser/i })).toBeNull();
    expect(screen.getByRole("button", { name: /Use DigiKey/i })).toBeTruthy();
  });
});
