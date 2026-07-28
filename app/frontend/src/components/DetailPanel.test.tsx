import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { api } from "../api/client";
import type { PartDetail } from "../api/types";
import { DEV_ID_BY_ID } from "../lib/devIds";
import { ThemeProvider } from "../lib/theme";
import { ToastProvider } from "../lib/toast";
import { CaptureProvider } from "../lib/capture";
import type { DeepPartial } from "fishery";
import { makeAsset, makePartDetail } from "../test/partFixture";
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
// the scene returns a handle ({dispose, setView}); see PartPreview.test.tsx
vi.mock("../lib/threeScene", () => ({
  mountModelScene: vi.fn(() => ({
    dispose: vi.fn(),
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

// Delegates to the ONE shared wire-shaped factory (src/test/partFixture.ts); only the default
// asset set is local to this file, because most cases here are about a complete KiCad part.
function detail(over: DeepPartial<PartDetail> = {}): PartDetail {
  return makePartDetail({
    id: "lm358",
    assets: { kicad: { symbol: SYM, footprint: FP, model: MODEL } },
    ...over,
  });
}

// The default KiCad asset set the fixture carries; cases override one slot at a time.
const SYM = makeAsset({ lib: "SR-ICs", name: "LM358", file: "" });
const FP = makeAsset({ lib: "SR-ICs", name: "SOIC-8", file: "" });
const MODEL = makeAsset({ lib: "", name: "", file: "models/lm358.step" });

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

    const dialog = await screen.findByRole("dialog", { name: "Inspect LM358" });
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
    wrap(<DetailPanel detail={detail({ assets: { kicad: { symbol: SYM, footprint: FP, model: null } } })} {...BASE} />);
    expect(
      screen.queryByRole("button", { name: "Open 3D Model Preview" }),
    ).not.toBeInTheDocument();
  });

  it("lists the record's parametric specs in a Specifications section, hiding asset keys (B1)", () => {
    wrap(
      <DetailPanel
        detail={detail({
          derived: {
            specs: {
            Resistance: "1.1 kOhms",
            Tolerance: "1%",
            Symbol: "Device:R",
            Footprint: "Resistor_SMD:R_0603_1608Metric",
            "3D Model": "Resistor_SMD.3dshapes/R_0603.wrl",
            pinout: [{ pin: "1", name: "A" }],
          },
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

  it("never truncates or caps the rows inside a spec group (B2)", () => {
    const many: Record<string, string> = {};
    for (let i = 0; i < 15; i++) many[`Spec ${i}`] = `value ${i}`;
    wrap(<DetailPanel detail={detail({ derived: { specs: many } })} {...BASE} />);
    // B2 originally read "renders every spec at once (no collapse)". NARROWED 2026-07-25 when the
    // owner asked for the opposite of "no collapse" - *"doesnt have things hidden behind buttons.
    // its so much thrown in your face"* - so groups past the first closed by default.
    //
    // THAT IS NO LONGER TRUE and this comment asserted it long after it stopped being: on
    // 2026-07-26 the owner overruled it with *"the specifications should all be expanded by
    // default"*, and `defaultOpen` has returned true for every group since. A stale comment that
    // reads as a reason is exactly what lets a wrong belief survive, so it is corrected rather
    // than left describing a behaviour the app does not have.
    //
    // What B2 was really protecting still holds and is what this asserts: an OPEN group shows ALL
    // of its rows, however many there are. No "+12 more", no cap, no scroll-to-reveal. A part with
    // fifteen specs in one group shows fifteen.
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
          part_class: "passive",
          assets: {
            kicad: { symbol: null, footprint: makeAsset({ lib: "Resistor_SMD", name: "R_0603_1608Metric", file: "" }), model: null },
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
    expect(screen.getByText("Activity")).toBeInTheDocument();
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
          enrichment: { pinout: { source: "datasheet", confidence: "high" } },
          derived: {
            specs: {
            pinout: [
              { pin: "1", name: "OUT1" },
              { pin: "2", name: "IN1-" },
            ],
          },
          },
        })}
        {...BASE}
      />,
    );
    const heading = screen.getByRole("heading", { name: "Datasheet Pinout" });
    const cad = screen.getByRole("button", { name: /CAD/ });
    expect(heading).toBeInTheDocument();
    expect(screen.getByText("2 Pins")).toBeInTheDocument();
    expect(screen.getByText("OUT1")).toBeInTheDocument();
    expect(screen.getByText(/datasheet · high/i)).toBeInTheDocument();
    expect(
      cad.compareDocumentPosition(heading) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    expect(screen.queryByRole("tab", { name: "Pinout" })).not.toBeInTheDocument();
  });

  it("shows no Pinout section when the record has no pinout", () => {
    wrap(<DetailPanel detail={detail({ derived: { specs: {} } })} {...BASE} />);
    expect(
      screen.queryByRole("heading", { name: "Datasheet Pinout" }),
    ).not.toBeInTheDocument();
  });

  it("resets the pinout filter when switching to a different part (keyed per part)", async () => {
    // Without a per-part key the single compact pinout card carries its filter
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
    const A = detail({ id: "a", derived: { specs: { pinout: [{ pin: "1", name: "VCC" }] } } });
    const B = detail({
      id: "b",
      derived: {
        specs: { pinout: [{ pin: "1", name: "GND" }, { pin: "2", name: "OUT" }] },
      },
    });
    const { rerender } = render(view(A));
    await userEvent.type(
      screen.getByRole("searchbox", { name: /filter datasheet pins/i }),
      "vcc",
    );
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
        detail={detail({ assets: { kicad: { symbol: null, footprint: FP, model: MODEL } } })}
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
        detail={detail({ assets: { kicad: { symbol: SYM, footprint: null, model: MODEL } } })}
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
    wrap(<DetailPanel detail={detail({ assets: { kicad: { symbol: null, footprint: FP, model: MODEL } } })} {...BASE} />);
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
      assets: {
        kicad: { symbol: SYM, footprint: FP, model: MODEL },
        altium: {
          symbol: makeAsset({ lib: "p.SchLib", name: "P", file: "" }),
          footprint: makeAsset({ lib: "p.PcbLib", name: "P", file: "" }),
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

  it("removes inactive workbench panels from layout even when their class sets display", async () => {
    const user = userEvent.setup();
    const { container } = wrap(<DetailPanel detail={detail()} {...BASE} />);
    const overview = container.querySelector("#workbench-panel-specs") as HTMLElement;
    const representations = container.querySelector("#workbench-panel-handoff") as HTMLElement;

    expect(overview.style.display).toBe("");
    expect(representations.style.display).toBe("none");
    await user.click(screen.getByRole("tab", { name: "Representations" }));
    expect(overview.style.display).toBe("none");
    expect(representations.style.display).toBe("");
    expect(representations).toHaveClass("overflow-hidden");
    expect(
      container
        .querySelector('[data-dev-id="detail.representations"]')
        ?.querySelector(".overflow-auto"),
    ).not.toBeNull();
    const representation = container.querySelector(
      '[data-dev-id="detail.representations"]',
    ) as HTMLElement;
    expect(within(representation).getByText("Design Tool")).toBeInTheDocument();
    expect(within(representation).getAllByText("Symbol").length).toBeGreaterThan(0);
    expect(within(representation).getAllByText("Footprint").length).toBeGreaterThan(0);
    expect(within(representation).getAllByText("3D Model").length).toBeGreaterThan(0);
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
          derived: {
            category: "Resistors",
            specs: {
            Resistance: "1.1 kOhms",
            Manufacturer: "Acme Corp",
            "Country of Origin": "Malaysia",
            Packaging: "Reel",
            "US Tariff %": "8",
          },
          },
        })}
        {...BASE}
      />,
    );
    // the real spec shows (unit prettified for display). getAllBy, because Key Specifications now
    // surfaces the leading parametric spec at the head of this column as well as the full list
    // below it - a hero summary, so the label legitimately appears twice.
    expect(screen.getAllByText("Resistance").length).toBeGreaterThan(0);
    expect(screen.getAllByText("1.1 kΩ").length).toBeGreaterThan(0);
    // The distributor-page metadata never reaches the PHYSICAL spec sheet. Scoped to the sheet
    // rather than the whole document since Batch 3: the procurement facts (origin, tariff,
    // packaging) are real vendor data the owner asked to stop discarding, so they now render in the
    // commercial column's Trade And Compliance block instead of being dropped on the floor. The
    // rule this test protects is "the spec sheet is physical parameters", and that still holds.
    const sheet = document.querySelector('[data-dev-id="detail.specs"]')!;
    for (const label of ["Country of Origin", "Malaysia", "Reel", "US Tariff"]) {
      expect(sheet.textContent).not.toContain(label);
    }
    // ...and they are NOT lost: the same values are in the trade block, one click away. The block
    // is CLOSED by default (2026-07-25, the owner's "data vomit" pass), so opening it is part of
    // the assertion now - which also proves the disclosure actually reveals what its count claims.
    const trade = document.querySelector('[data-dev-id="detail.trade"]')!;
    expect(trade.textContent).toContain("3"); // the header states how much it is holding
    fireEvent.click(trade.querySelector("button")!);
    expect(trade.textContent).toContain("Country of Origin");
    expect(trade.textContent).toContain("Malaysia");
    expect(trade.textContent).toContain("US Tariff");
    expect(trade.textContent).toContain("Reel");
  });

  it("headlines an opaque part (IC) by its display name, not its bare MPN, and reads the MPN once", () => {
    wrap(
      <DetailPanel
        detail={detail({
          mpn: "LM358DR",
          derived: {
            category: "ICs",
            display_name: "Dual Op-Amp LM358",
            specs: {},
          },
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
          mpn: "RC0603",
          derived: {
            category: "Resistors",
            display_name: "10k 1% 0603",
            specs: { Resistance: "10 kOhms", Tolerance: "1%" },
          },
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
      symbol: makeAsset({ lib: "lm358.SchLib", name: "LM358", file: "" }),
      footprint: makeAsset({ lib: "lm358.PcbLib", name: "SOIC-8", file: "" }),
      model: null,
    },
  };

  async function openReadiness(over: DeepPartial<PartDetail> = {}) {
    wrap(<DetailPanel detail={detail(over)} {...BASE} />);
    await userEvent.click(screen.getByRole("button", { name: /CAD/ }));
  }

  function byDevId(id: string) {
    return document.querySelector(`[data-dev-id="${id}"]`);
  }

  it("offers the embed action when there is a footprint to write into and a model to write", async () => {
    await openReadiness({ assets: ALTIUM_READY });
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
    await openReadiness({ assets: ALTIUM_READY });
    const action = await waitFor(() => {
      const el = byDevId("detail.embed3d") as HTMLButtonElement;
      expect(el).not.toBeDisabled();
      return el;
    });
    await userEvent.click(action);
    expect(mockApi.altiumEmbedModel).toHaveBeenCalledWith("lm358", false);
  });

  it("explains that the Altium library must be attached first, rather than sitting inert", async () => {
    await openReadiness({ assets: { kicad: { symbol: SYM, footprint: FP, model: MODEL } } });
    expect(byDevId("detail.embed3d")).toBeDisabled();
    expect(byDevId("detail.embed3d-blocked")).toHaveTextContent(/Attach the Altium library first/);
  });

  it("explains that a 3D model file is needed first", async () => {
    await openReadiness({
      assets: { ...ALTIUM_READY, kicad: { symbol: SYM, footprint: FP, model: null } },
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
    await openReadiness({ assets: ALTIUM_READY });
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
    await openReadiness({ assets: ALTIUM_READY });
    await waitFor(() =>
      expect(byDevId("detail.embed3d-blocked")).toHaveTextContent(/Close Altium first/),
    );
  });

  it("shows the embedded confirmation, and no action, once the container really carries it", async () => {
    await openReadiness({
      assets: {
        ...ALTIUM_READY,
        altium: {
          ...ALTIUM_READY.altium,
          model: makeAsset({ lib: "lm358.PcbLib", name: "SOIC-8", file: "models/lm358.step" }),
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
    await openReadiness({ assets: ALTIUM_READY });
    await waitFor(() => expect(byDevId("detail.embed3d")).not.toBeNull());
    const readiness = byDevId("detail.readiness") as HTMLElement;
    // BOTH tool rows read Ready: the 3D gap is real and actionable without making Altium unready.
    expect(within(readiness).getAllByText("Ready")).toHaveLength(2);
    expect(within(readiness).queryByText(/Complete Part/)).toBeNull();
  });

  it("offers nothing for a passive, which inherits the stock footprint's own 3D body", async () => {
    await openReadiness({ part_class: "passive", assets: ALTIUM_READY });
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
      alternates: {
        description: [
          { value: "3A buck", source: "mouser", confidence: "high" },
          { value: "Step-Down Regulator, 3 A", source: "digikey", confidence: "high" },
        ],
      },
      derived: {
        description: "3A buck",
      },
    });

  it("says how many answers a field has, without spending space until asked", async () => {
    wrap(<DetailPanel detail={withTwoDescriptions()} {...BASE} />);
    // description + datasheet now live on the Handoff TAB (owner's choice 2026-07-26)
    await userEvent.click(screen.getByRole("tab", { name: "Representations" }));
    expect(screen.getByRole("button", { name: /2 Sources/i })).toBeTruthy();
    // the other distributor's wording stays out of the way until the disclosure is opened
    expect(screen.queryByText("Step-Down Regulator, 3 A")).toBeNull();
  });

  it("shows each answer with the distributor that gave it once opened", async () => {
    const user = userEvent.setup();
    wrap(<DetailPanel detail={withTwoDescriptions()} {...BASE} />);
    await user.click(screen.getByRole("tab", { name: "Representations" }));
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
    // The description + datasheet fields moved to the Handoff TAB (owner's choice, 2026-07-26);
    // open it before asserting on them. The assertions themselves are unchanged.
    await userEvent.click(screen.getByRole("tab", { name: "Representations" }));
    // The description + datasheet fields moved to the Handoff TAB (owner's choice, 2026-07-26);
    // open it before asserting on them. The assertions themselves are unchanged.
    await userEvent.click(screen.getByRole("tab", { name: "Representations" }));
    // The description + datasheet fields moved to the Handoff TAB (owner's choice, 2026-07-26);
    // open it before asserting on them. The assertions themselves are unchanged.
    await userEvent.click(screen.getByRole("tab", { name: "Representations" }));
    await user.click(screen.getByRole("button", { name: /2 Sources/i }));
    await user.click(screen.getByRole("button", { name: /Use DigiKey/i }));
    expect(onEditField).toHaveBeenCalledWith("description", "Step-Down Regulator, 3 A");
  });

  it("offers no swap for the answer already in force", async () => {
    const user = userEvent.setup();
    wrap(
      <DetailPanel detail={withTwoDescriptions()} {...BASE} onEditField={vi.fn()} />,
    );
    // The description + datasheet fields moved to the Handoff TAB (owner's choice, 2026-07-26);
    // open it before asserting on them. The assertions themselves are unchanged.
    await userEvent.click(screen.getByRole("tab", { name: "Representations" }));
    await user.click(screen.getByRole("button", { name: /2 Sources/i }));
    expect(screen.queryByRole("button", { name: /Use Mouser/i })).toBeNull();
  });

  it("shows nothing at all for a part whose sources agreed", () => {
    wrap(<DetailPanel detail={detail({ derived: { description: "3A buck" } })} {...BASE} />);
    expect(screen.queryByRole("button", { name: /Sources/i })).toBeNull();
  });

  it("swaps a SPEC value through the specs seam, not the field seam", async () => {
    const user = userEvent.setup();
    const onUseSpecValue = vi.fn();
    wrap(
      <DetailPanel
        detail={detail({
          alternates: {
            Tolerance: [
              { value: "1%", source: "mouser", confidence: "high" },
              { value: "5%", source: "digikey", confidence: "high" },
            ],
          },
          derived: {
            specs: { Tolerance: "1%" },
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
          alternates: {
            Tolerance: [
              { value: "1%", source: "mouser", confidence: "high" },
              { value: "2%", source: "digikey", confidence: "high" },
            ],
          },
          derived: {
            specs: { Tolerance: "1%" },
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

// -- punch 15: the destructive action's interaction language. It was dim text in a corner reading
// "Delete Part"; the owner asked for a red X that expands to "Delete Part?" on hover with a loading
// state, and generalised the philosophy to the whole app - so it is the shared IconButton primitive
// (which already had the reveal behaviour, zero tests and zero callers) rather than a one-off.
describe("DetailPanel delete action", () => {
  it("reads as a destructive action that names its consequence as a question", () => {
    wrap(<DetailPanel detail={detail()} {...BASE} onDelete={vi.fn()} />);
    const del = screen.getByRole("button", { name: "Delete Part?" });
    // Reads as destructive at rest via the err token, but MUTED - no border, no fill. The full
    // ghost-danger treatment arrives with the label when the control is approached, because a
    // permanently bordered red box in the corner shouts louder than the text it replaced.
    expect(del.className).toContain("--c-err");
    expect(del.className).toContain("border-transparent");
    expect(del.getAttribute("data-revealed")).toBe("false");
  });

  it("shows the running state ON the control, not only in a toast", () => {
    wrap(<DetailPanel detail={detail()} {...BASE} onDelete={vi.fn()} deleting />);
    const del = screen.getByRole("button", { name: "Deleting" });
    expect(del).toBeDisabled();
    expect(del).toHaveAttribute("aria-busy", "true");
  });

  it("spins for a DELETE, not for any other write in flight", () => {
    // `busy` is the panel's aggregate write flag, so using it would make the delete control spin
    // while a symbol was attaching - claiming an action the user never started.
    wrap(<DetailPanel detail={detail()} {...BASE} onDelete={vi.fn()} busy />);
    expect(screen.queryByRole("button", { name: "Deleting" })).toBeNull();
  });

  it("still asks for confirmation, because the explanation is worth more than a slick two-click", async () => {
    const user = userEvent.setup();
    const onDelete = vi.fn();
    wrap(<DetailPanel detail={detail()} {...BASE} onDelete={onDelete} />);
    await user.click(screen.getByRole("button", { name: "Delete Part?" }));
    // the dialog that says it commits and can be restored from git history
    expect(await screen.findByRole("dialog")).toBeTruthy();
    expect(onDelete).not.toHaveBeenCalled();
  });
});

// -- The spec row's label/value pairing (found in the owner's own shot critique): the label was
// left-aligned and the value right-aligned, so on a wide column the eye had to cross a long empty
// gap to pair "Applications" with "HDMI".
describe("DetailPanel spec row pairing", () => {
  it("puts the value in its own column next to the label, not flung to the far edge", () => {
    wrap(
      <DetailPanel
        // Slew Rate deliberately: it is NOT in the curated ICs key set, so "promote not copy" leaves
        // it in the Specifications list, which is the list whose row anatomy this test is about.
        detail={detail({ derived: { category: "ICs", specs: { "Slew Rate": "13 V/us" } } })}
        {...BASE}
      />,
    );
    // Scoped to the full Specifications list: Key Specifications now renders the same spec at the
    // head of this column (a hero summary above the full table), so an unscoped query matches twice.
    const list = document.querySelector('[data-dev-id="detail.specs-list"]') as HTMLElement;
    const row = within(list).getByText("Slew Rate").closest("div")!;
    // a grid with a bounded label track, so every value in the group starts at the same x and sits
    // adjacent to its label - not `justify-between`, which pushes them to opposite edges
    expect(row.className).toContain("grid");
    expect(row.className).not.toContain("justify-between");
  });
});

describe("DetailPanel key specifications", () => {
  it("promotes key rows once instead of duplicating them in the full specification list", () => {
    wrap(
      <DetailPanel
        detail={detail({
          derived: {
            category: "Resistors",
            specs: {
              Resistance: "10 kOhm",
              Tolerance: "1%",
              Package: "0603",
              "Pulse Duration": "1 ms",
            },
          },
        })}
        {...BASE}
      />,
    );
    const key = screen.getByRole("region", { name: "Key Specifications" });
    const full = document.querySelector('[data-dev-id="detail.specs-list"]') as HTMLElement;
    expect(within(key).getByText("Resistance")).toBeInTheDocument();
    expect(within(full).queryByText("Resistance")).not.toBeInTheDocument();
    expect(within(full).getByText("Pulse Duration")).toBeInTheDocument();
  });

  it("moves a custom pin into Key Specifications and returns it when unpinned", async () => {
    const user = userEvent.setup();
    wrap(
      <DetailPanel
        detail={detail({
          derived: {
            category: "ICs",
            specs: {
              "Supply Voltage": "3.3 V",
              Package: "QFN-16",
              "Slew Rate": "13 V/us",
            },
          },
        })}
        {...BASE}
      />,
    );
    await user.click(screen.getByRole("button", { name: "Pin Slew Rate" }));
    const key = screen.getByRole("region", { name: "Key Specifications" });
    const full = document.querySelector('[data-dev-id="detail.specs-list"]') as HTMLElement;
    expect(within(key).getByText("Slew Rate")).toBeInTheDocument();
    expect(within(full).queryByText("Slew Rate")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Unpin Slew Rate" }));
    expect(within(full).getByText("Slew Rate")).toBeInTheDocument();
  });
});

describe("DetailPanel alternates alignment", () => {
  it("lines an alternate's value up with the row it belongs to", async () => {
    // The alternates were justify-between while their PARENT row had just been changed to a grid,
    // so a child's value flew to the far edge while the parent's sat beside its label. On the very
    // rows whose job is to be compared, that is the original complaint made worse. Both use the
    // same track definition, so they cannot drift apart again.
    const user = userEvent.setup();
    wrap(
      <DetailPanel
        detail={detail({
          alternates: {
            Tolerance: [
              { value: "1%", source: "mouser", confidence: "high" },
              { value: "2%", source: "digikey", confidence: "high" },
            ],
          },
          derived: {
            specs: { Tolerance: "1%" },
          },
        })}
        {...BASE}
      />,
    );
    await user.click(screen.getByRole("button", { name: /2 Sources/i }));
    // the label is uppercased by CSS, so the DOM text is still "DigiKey"; the vendor also appears
    // in the Sourcing column, so pick the occurrence inside the alternates list
    const entry = screen
      .getAllByText("DigiKey")
      .map((el) => el.closest("li"))
      .find((li): li is HTMLLIElement => li !== null)!;
    expect(entry.className).toContain("grid");
    expect(entry.className).not.toContain("justify-between");
    // the same label-track width the parent row uses, so the value columns coincide
    expect(entry.className).toContain("10.5rem");
  });
});

// -- punch 8 + 11: the Links row read as a bordered pill beside a bare pencil (two shapes, two
// heights, reading as unrelated things), and the asset tiles spelled out the word "View" where a
// glyph says it in less space.
describe("DetailPanel links row anatomy", () => {
  const withDatasheet = () =>
    detail({
      datasheet: { file: "", source_url: "https://ti.com/ds.pdf", fetched_at: "" },
    });

  // RE-BASELINED 2026-07-25, deliberately. Punch 8's complaint was that the datasheet was a
  // bordered pill NEXT TO a bare pencil - "two shapes at two heights with a gap" - and the fix was
  // one flat 34px row matching Filing's anatomy. The datasheet is an EDA handoff field, so at the
  // owner's request it moved into the handoff block above Specifications and wears the same cell
  // anatomy as every other field there; Filing itself is gone, its Category now a cell in the same
  // block. The ORIGINAL requirement is unchanged and still asserted: one consistent shape, the
  // link still opens, the link is still editable, an absent datasheet still says so plainly.
  it("presents the datasheet with the same cell anatomy as the other handoff fields", () => {
    wrap(<DetailPanel detail={withDatasheet()} {...BASE} onEditField={vi.fn()} />);
    const cell = document.querySelector('[data-dev-id="detail.handoff-datasheet"]');
    expect(cell, "the datasheet should be a cell in the EDA handoff block").toBeTruthy();
    const peer = document.querySelector('[data-dev-id="detail.handoff-mpn"]')!;
    expect(cell!.className).toBe(peer.className);
  });

  it("still opens the datasheet and still allows editing the link", async () => {
    const user = userEvent.setup();
    const onEditField = vi.fn();
    wrap(<DetailPanel detail={withDatasheet()} {...BASE} onEditField={onEditField} />);
    // The datasheet field moved to the Handoff TAB (owner's choice, 2026-07-26); open it before
    // asserting on it. The assertions themselves are unchanged.
    await user.click(screen.getByRole("tab", { name: "Representations" }));
    // OPENS: a real anchor at the FULL url, never the shortened display label.
    expect(screen.getByRole("link", { name: /Open Datasheet/i })).toHaveAttribute(
      "href",
      "https://ti.com/ds.pdf",
    );
    // EDITS: click-to-edit, the same interaction every other editable handoff field uses.
    await user.click(screen.getByRole("button", { name: /Datasheet/i }));
    const input = screen.getByLabelText("Datasheet");
    await user.clear(input);
    await user.type(input, "https://x/y.pdf{Enter}");
    expect(onEditField).toHaveBeenCalledWith("datasheet", "https://x/y.pdf");
  });

  it("says a missing datasheet plainly rather than showing an empty control", () => {
    wrap(<DetailPanel detail={detail({ datasheet: null })} {...BASE} />);
    const cell = document.querySelector('[data-dev-id="detail.handoff-datasheet"]')!;
    // an unset handoff field reads as a GAP, in the warn tone: an empty one here means the part
    // lands in the EDA tool incomplete
    expect(cell.textContent).toMatch(/Not Set|Add Datasheet/);
  });

  it("moves the eye into a labelled Expand action over the asset stage", () => {
    wrap(<DetailPanel detail={detail()} {...BASE} />);
    // The footer is identity/status only; expansion is one large, consistent stage affordance.
    expect(screen.queryByText("View")).toBeNull();
    const tile = document.querySelector('[data-dev-id="detail.asset-symbol"]')!;
    const footer = tile.lastElementChild as HTMLElement;
    expect(within(footer).queryByRole("button")).toBeNull();
    expect(screen.getByRole("button", { name: "Open Symbol Preview" })).toHaveTextContent(
      "Expand",
    );
  });
});

// --- The description leads the Specifications column (owner, 2026-07-26). -----------------------

describe("the description lede", () => {
  it("shows the description at the head of the column, above Top Specifications", () => {
    // Real specs, so Top Specifications actually renders and the ordering assertion below is not
    // vacuously true against a block that is not there.
    wrap(
      <DetailPanel
        detail={detail({
          derived: {
            description: "Dual op-amp, 3 MHz",
            specs: { "Supply Voltage": "3 V", "Package / Case": "SOIC-8" },
          },
        })}
        {...BASE}
      />,
    );
    // Scoped to the lede block on purpose: the Handoff TAB also carries the description, and a
    // bare getByText finds both. That is not duplication on screen - the tabs are alternatives -
    // but it does mean this assertion has to name which one it means.
    const block = document.querySelector('[data-dev-id="detail.description-lede"]');
    expect(block).not.toBeNull();
    expect(block).toHaveTextContent("Dual op-amp, 3 MHz");
    // ABOVE, not merely present: the whole ask was about where it sits.
    const top = document.querySelector('[data-dev-id="detail.key-specs"]');
    expect(top).not.toBeNull();
    expect(block!.compareDocumentPosition(top!) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("renders NOTHING when the part has no description", () => {
    // An emphasized empty lede would be the loudest element on the sheet saying nothing.
    wrap(<DetailPanel detail={detail({ derived: { description: "" } })} {...BASE} />);
    expect(document.querySelector('[data-dev-id="detail.description-lede"]')).toBeNull();
  });

  it("keeps the N Sources swap with the text it is about", () => {
    wrap(
      <DetailPanel
        detail={detail({
          alternates: {
            description: [
              { value: "Dual op-amp", source: "mouser", confidence: "high" },
              { value: "Op Amp, 2 channel", source: "digikey", confidence: "high" },
            ],
          },
          derived: {
            description: "Dual op-amp",
          },
        })}
        {...BASE}
      />,
    );
    const block = document.querySelector('[data-dev-id="detail.description-lede"]');
    expect(block?.textContent).toMatch(/2 Sources/);
  });
});

// --- Compact assets use one stage-centred inspection affordance (owner, 2026-07-28). --------------
// The mini renderer is now a passive auto-rotating specimen. Hover/focus reveals one labelled eye
// over every present representation; detached footer glyphs and whole-card click contracts are gone.

describe("the 3D tile's click target", () => {
  it("does NOT open the modal when the stage shell outside Inspect is clicked", async () => {
    wrap(<DetailPanel detail={detail()} {...BASE} />);
    const tile = document.querySelector('[data-dev-id="detail.asset-hero"]');
    expect(tile).not.toBeNull();
    // Expansion has one explicit command, not a surprising click-anywhere contract.
    const stage = tile!.firstElementChild as HTMLElement;
    fireEvent.click(stage);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("keeps every present representation shell out of the button role", () => {
    wrap(<DetailPanel detail={detail()} {...BASE} />);
    for (const id of ["detail.asset-hero", "detail.asset-symbol", "detail.asset-footprint"]) {
      expect(document.querySelector(`[data-dev-id="${id}"]`)!.tagName).toBe("DIV");
    }
  });

  it("opens the modal from the labelled Expand overlay", async () => {
    wrap(<DetailPanel detail={detail()} {...BASE} />);
    await userEvent.click(screen.getByRole("button", { name: "Open 3D Model Preview" }));
    expect(await screen.findByRole("dialog")).toBeInTheDocument();
  });

  it("gives all three present representations the same Expand contract", () => {
    wrap(<DetailPanel detail={detail()} {...BASE} />);
    expect(screen.getByRole("button", { name: "Open 3D Model Preview" })).toHaveTextContent(
      "Expand",
    );
    expect(screen.getByRole("button", { name: "Open Symbol Preview" })).toHaveTextContent(
      "Expand",
    );
    expect(screen.getByRole("button", { name: "Open Footprint Preview" })).toHaveTextContent(
      "Expand",
    );
  });
});

describe("a spec value never breaks INSIDE one of its tokens", () => {
  // Measured on the owner's real window: "Peak Pulse Current (10/1000us)" rendered as
  // "2.5A / (8/20us / )" with an orphaned ")" on its own line, and elsewhere split the unit itself
  // into "8/20u" + "s". A reader cannot tell "8/20us" from "8/20u s", so this is correctness.
  //
  // jsdom does NO layout, so the width at which it breaks was measured separately in real Chromium
  // (see the comment on SpecValue): a 60px value track is fine, 48px and below breaks inside, and
  // `word-break: keep-all` changes nothing. What is asserted HERE is the DOM contract that fix
  // rests on, which is the part jsdom can actually see.
  it("holds a token containing a slash together", () => {
    wrap(
      <DetailPanel detail={detail({ derived: { specs: { "Peak Pulse": "2.5A (8/20us)" } } })} {...BASE} />,
    );
    // Asserted through the CLASS rather than the exact string: the spec pipeline prettifies a
    // value on its way to the row, so pinning the rendered text here would be testing the
    // prettifier. What matters is that the bracketed token arrives as ONE unbreakable unit.
    const held = Array.from(document.querySelectorAll("span.whitespace-nowrap")).map(
      (el) => el.textContent ?? "",
    );
    const token = held.find((s) => s.includes("8/20"));
    expect(token, `no unbreakable token held 8/20; got ${JSON.stringify(held)}`).toBeTruthy();
    // Both brackets in the SAME token, so the closing one can never be orphaned onto its own line.
    expect(token).toContain("(");
    expect(token).toContain(")");
  });

  it("leaves an ordinary value as a PLAIN text node", () => {
    // The regression that killed the first attempt: wrapping every token in a span fragments the
    // text node, and `getByText` matches an element by its DIRECT text children, so a blanket
    // split silently broke every existing query for a spec value. A value with no break-risk must
    // stay exactly as it was.
    wrap(<DetailPanel detail={detail({ derived: { specs: { Resistance: "1.1 kΩ" } } })} {...BASE} />);
    const el = screen.getByText("1.1 kΩ");
    expect(el.tagName).toBe("DD");
    expect(el.querySelector("span.whitespace-nowrap")).toBeNull();
  });

  it("still lets a token too long for any track break rather than overflowing", () => {
    const long = `${"A".repeat(30)}/${"B".repeat(30)}`;
    wrap(<DetailPanel detail={detail({ derived: { specs: { Weird: long } } })} {...BASE} />);
    expect(screen.getByText(long).querySelector("span.whitespace-nowrap")).toBeNull();
  });
});

describe("a spec group's count", () => {
  it("sits NEXT TO the label it counts, not flushed to the far edge", async () => {
    // Measured on a 1600px window: `detail.specs` is 530px wide and the count was `ml-auto`, so
    // "5" rendered ~500px from the word "Electrical". Four of those hung in a right-hand column
    // with nothing tying each number to its noun. jsdom has no layout, so this asserts the
    // STRUCTURE that produces the adjacency: the count is the title's immediate next sibling,
    // and nothing in the header pushes it away with an auto margin.
    wrap(<DetailPanel detail={detail({ derived: { specs: { "Breakdown Voltage": "6.5 V" } } })} {...BASE} />);
    const header = await screen.findByText("Electrical");
    const button = header.closest("button");
    expect(button).not.toBeNull();
    const spans = Array.from(button!.querySelectorAll("span"));
    const titleIndex = spans.findIndex((s) => s.textContent === "Electrical");
    expect(titleIndex).toBeGreaterThanOrEqual(0);
    const count = spans[titleIndex + 1];
    expect(count?.textContent).toMatch(/^\d+$/);
    expect(count?.className ?? "").not.toContain("ml-auto");
  });
});

// The regression pin for cold-eyes finding 3 (2026-07-27): `missingAssets`/`needsList` were a
// hardcoded symbol/footprint/3D-model list evaluated regardless of the part's CLASS, recreating
// the exact "CAD Incomplete forever" shape one layer up from the fix in edaTarget.ts. A mechanical
// part was told to add a symbol it can never have; a fiducial was told to add all three while the
// CAD chip simultaneously read Complete. All four rows are the reviewer's own reproduction table.
describe("the Complete-Part needs line respects the part's class (cold-eyes finding 3)", () => {
  async function needsText(over: Partial<PartDetail> = {}) {
    // `canComplete` gates the whole "Add X to make this part usable" sentence
    // (`!!(onEditField || onAttachSymbol || onAttachFootprint)`), so at least one write callback
    // must be present or the sentence never renders and every assertion below passes vacuously
    // regardless of what missingAssets/needsList computed - which is exactly what happened on
    // the first version of this test, caught before it was trusted.
    wrap(<DetailPanel detail={detail(over)} {...BASE} onAttachSymbol={vi.fn()} />);
    await userEvent.click(await screen.findByRole("button", { name: /CAD/ }));
    return document.body.textContent ?? "";
  }

  it("a mechanical part with its footprint attached is never told to add a symbol", async () => {
    const text = await needsText({
      part_class: "mechanical",
      assets: { kicad: { symbol: null, footprint: FP, model: null } },
    });
    expect(text).not.toMatch(/Add[^.]*\bsymbol\b/i);
  });

  it("a virtual part is never told to add all three while the chip reads Complete", async () => {
    const text = await needsText({
      part_class: "virtual",
      assets: { kicad: { symbol: null, footprint: null, model: null } },
    });
    expect(text).not.toMatch(/Add symbol, footprint, 3D model/i);
  });

  it("a passive with a stock footprint and no symbol is never told to add a symbol", async () => {
    const text = await needsText({
      part_class: "passive",
      assets: {
        kicad: {
          symbol: null,
          footprint: makeAsset({ lib: "Resistor_SMD", name: "R_0603_1608Metric" }),
          model: null,
        },
      },
    });
    expect(text).not.toMatch(/Add[^.]*\bsymbol\b/i);
  });

  it("control: a component with nothing attached is still told to add everything", async () => {
    const text = await needsText({
      part_class: "component",
      assets: { kicad: { symbol: null, footprint: null, model: null } },
    });
    expect(text).toMatch(/symbol/i);
    expect(text).toMatch(/footprint/i);
  });
});
