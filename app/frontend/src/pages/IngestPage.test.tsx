import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { useEffect, type ReactNode } from "react";
import userEvent from "@testing-library/user-event";

import { ApiError, api } from "../api/client";
import type { EnrichmentResult } from "../api/types";
import { AddPartProvider, useAddPart } from "../lib/addPart";
import { RouterProvider, useRouter } from "../lib/router";
import { ThemeProvider } from "../lib/theme";
import { ToastProvider } from "../lib/toast";
import {
  componentView,
  defaultUiSession,
  readUiSession,
  resetUiSessionForTests,
  useUiSession,
} from "../lib/uiSession";
import { makePartDetail } from "../test/partFixture";
import { IngestPage } from "./IngestPage";

vi.mock("../api/client", async (importActual) => {
  const actual = await importActual<typeof import("../api/client")>();
  return {
    ...actual,
    api: {
      ...actual.api,
      enrichFromUrl: vi.fn(),
      enrichPart: vi.fn(),
      ingestCommit: vi.fn(),
      openJobStream: vi.fn(),
      getSettings: vi.fn(),
    },
  };
});

const mockApi = vi.mocked(api);

function sourced(value: unknown, source = "mouser") {
  return { value, source, confidence: "high" };
}

const EMPTY_RESULT: EnrichmentResult = {
  category: "",
  mpn: null,
  manufacturer: null,
  description: null,
  datasheet_url: null,
  stock: null,
  package: null,
  price_breaks: [],
  specs: {},
  add_plan: null,
  schema_version: 1,
};

function streamOf(result: EnrichmentResult): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder();
  return new ReadableStream<Uint8Array>({
    start(controller) {
      controller.enqueue(encoder.encode(`event: result\ndata: ${JSON.stringify({ result })}\n\n`));
      controller.enqueue(encoder.encode("event: done\ndata: {}\n\n"));
      controller.close();
    },
  });
}

function OpenAddPartOnMount() {
  const { open } = useAddPart();
  useEffect(() => {
    open();
    // This is a one-time test harness action. Re-running after close would reopen
    // the dialog and mask the continuation contract under test.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  return null;
}

/**
 * Stands in for the Library page, which owns opening a part. The reopen seam is a SUBSCRIPTION, so
 * the probe registers for it exactly as that page does and records what it was handed - which is
 * also what proves the request survives the gap in between: the intake flow requests the open from
 * inside its own commit, and nothing else here reads it.
 */
function ContinuationProbe() {
  const { isOpen } = useAddPart();
  const { route } = useRouter();
  const session = useUiSession();
  const active = session.active_component ?? "";
  return (
    <div
      data-testid="continuation"
      data-active={active}
      data-cad-view={active ? componentView(session, active).cad_view : ""}
      data-route={route}
      data-add-open={String(isOpen)}
    />
  );
}

function wrapper(ui: ReactNode) {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <ThemeProvider>
        <RouterProvider>
          <AddPartProvider>
            <ToastProvider>
              {ui}
              <OpenAddPartOnMount />
              <ContinuationProbe />
            </ToastProvider>
          </AddPartProvider>
        </RouterProvider>
      </ThemeProvider>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  mockApi.getSettings.mockResolvedValue({
    mouser_api_key_set: false,
    digikey_client_secret_set: false,
  } as never);
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("IngestPage network-only Add A Part", () => {
  it("permits an exact usable result when the other configured official source failed", async () => {
    mockApi.enrichPart.mockResolvedValue({ job_id: "partial-official" });
    mockApi.openJobStream.mockResolvedValue(
      streamOf({
        ...EMPTY_RESULT,
        category: "ICs",
        mpn: sourced("TPS62130RGTR", "mouser"),
        manufacturer: sourced("Texas Instruments", "mouser"),
        description: sourced("3 A buck converter", "mouser"),
        datasheet_url: sourced("https://ti.com/tps62130.pdf", "mouser"),
        source_states: { mouser: "success", digikey: "failed" },
      }),
    );
    wrapper(<IngestPage />);
    const user = userEvent.setup();

    await user.type(screen.getByLabelText("Product link or part number"), "TPS62130RGTR");
    await user.click(screen.getByRole("button", { name: "Look Up" }));

    expect(await screen.findByRole("button", { name: "Add And Continue" })).toBeEnabled();
    expect(screen.getByText(/Mouser succeeded/i)).toBeInTheDocument();
    expect(screen.getByText(/DigiKey failed/i)).toBeInTheDocument();
    expect(screen.queryByText(/will not add this component/i)).not.toBeInTheDocument();
  });

  it("blocks LCSC identity when both official APIs failed", async () => {
    mockApi.enrichPart.mockResolvedValue({ job_id: "both-official-failed" });
    mockApi.openJobStream.mockResolvedValue(
      streamOf({
        ...EMPTY_RESULT,
        category: "ICs",
        mpn: sourced("LCSC-ONLY-1", "lcsc"),
        manufacturer: sourced("Untrusted Maker", "lcsc"),
        description: sourced("LCSC-only result", "lcsc"),
        datasheet_url: sourced("https://example.com/lcsc-only.pdf", "lcsc"),
        source_states: { mouser: "failed", digikey: "failed", lcsc: "success" },
      }),
    );
    wrapper(<IngestPage />);
    const user = userEvent.setup();

    await user.type(screen.getByLabelText("Product link or part number"), "LCSC-ONLY-1");
    await user.click(screen.getByRole("button", { name: "Look Up" }));

    expect(await screen.findByText(/Mouser and DigiKey failed/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Add And Continue" })).not.toBeInTheDocument();
    expect(screen.queryByText("Review and Add")).not.toBeInTheDocument();
  });

  it("records a lookup exception as a visible Failed row with Retry", async () => {
    mockApi.enrichPart.mockRejectedValue(new Error("official lookup unavailable"));
    wrapper(<IngestPage />);
    const user = userEvent.setup();

    await user.type(screen.getByLabelText("Product link or part number"), "FAILED-LOOKUP-1");
    await user.click(screen.getByRole("button", { name: "Look Up" }));

    expect(await screen.findByText("Failed")).toBeInTheDocument();
    expect(screen.getByText("FAILED-LOOKUP-1")).toBeInTheDocument();
    expect(screen.getAllByText(/official lookup unavailable/i).length).toBeGreaterThan(0);
    await user.click(screen.getByRole("button", { name: "Retry" }));
    await waitFor(() => expect(mockApi.enrichPart).toHaveBeenCalledTimes(2));
  });

  it("keeps a bounded 25-part session open with durable outcomes and no CAD launch", async () => {
    let current = 0;
    mockApi.enrichPart.mockImplementation(async () => ({ job_id: `part-${current}` }));
    mockApi.openJobStream.mockImplementation(async () => {
      const mpn = `ACTIVE-${String(current).padStart(2, "0")}`;
      current += 1;
      return streamOf({
        ...EMPTY_RESULT,
        category: "ICs",
        mpn: sourced(mpn),
        manufacturer: sourced("Acme"),
        description: sourced(`Active component ${mpn}`),
        datasheet_url: sourced(`https://example.com/${mpn}.pdf`),
        source_states: { mouser: "success", digikey: "not_configured" },
      });
    });
    mockApi.ingestCommit.mockImplementation(async (candidate) =>
      makePartDetail({
        id: candidate.mpn.toLowerCase(),
        mpn: candidate.mpn,
        derived: { display_name: candidate.mpn },
      }),
    );
    const runCapture = vi.spyOn(mockApi, "runCapture");
    const showProvider = vi.spyOn(mockApi, "showCaptureProvider");
    wrapper(<IngestPage />);
    const user = userEvent.setup();
    const input = screen.getByLabelText("Product link or part number");

    for (let index = 0; index < 25; index += 1) {
      const mpn = `ACTIVE-${String(index).padStart(2, "0")}`;
      await user.type(input, mpn);
      await user.click(screen.getByRole("button", { name: "Look Up" }));
      await user.click(await screen.findByRole("button", { name: "Add And Continue" }));
      await waitFor(() => expect(input).toHaveValue(""));
    }

    expect(screen.getByTestId("continuation")).toHaveAttribute("data-add-open", "true");
    expect(screen.getByTestId("continuation")).toHaveAttribute("data-active", "");
    expect(screen.getAllByText("CAD Needed")).toHaveLength(25);
    expect(screen.getByText("ACTIVE-00")).toBeInTheDocument();
    expect(screen.getByText("ACTIVE-24")).toBeInTheDocument();
    expect(mockApi.ingestCommit).toHaveBeenCalledTimes(25);
    expect(runCapture).not.toHaveBeenCalled();
    expect(showProvider).not.toHaveBeenCalled();
  }, 30_000);

  it("opens Manage Models only from the explicit Add and Manage Models action", async () => {
    mockApi.enrichPart.mockResolvedValue({ job_id: "open-after-add" });
    mockApi.openJobStream.mockResolvedValue(
      streamOf({
        ...EMPTY_RESULT,
        category: "ICs",
        mpn: sourced("OPEN-ME-1"),
        manufacturer: sourced("Acme"),
        description: sourced("Explicit-open component"),
        datasheet_url: sourced("https://example.com/open-me-1.pdf"),
      }),
    );
    mockApi.ingestCommit.mockResolvedValue(
      makePartDetail({ id: "open-me-1", mpn: "OPEN-ME-1" }),
    );
    wrapper(<IngestPage />);
    const user = userEvent.setup();

    await user.type(screen.getByLabelText("Product link or part number"), "OPEN-ME-1");
    await user.click(screen.getByRole("button", { name: "Look Up" }));
    await user.click(await screen.findByRole("button", { name: "Add and Manage Models" }));

    expect(screen.getByTestId("continuation")).toHaveAttribute("data-active", "open-me-1");
    expect(screen.getByTestId("continuation")).toHaveAttribute("data-cad-view", "manage-models");
    expect(screen.getByTestId("continuation")).toHaveAttribute("data-route", "assets");
    expect(screen.getByTestId("continuation")).toHaveAttribute("data-add-open", "false");
  });

  it("restores raw official evidence from a server-staged draft after restart", async () => {
    const session = defaultUiSession();
    session.open_surface = "add_part";
    session.intake_draft_ref = {
      draft_id: "4f204a7e-e610-4a75-b575-569bca2b3470",
      revision: 2,
    };
    resetUiSessionForTests(session);
    const storedDraft = {
      schema: "stockroom.intake-draft",
      version: 1,
      draft_id: session.intake_draft_ref.draft_id,
      revision: 2,
      network_input: { kind: "mpn", value: "TPD6E05U06RVZR" },
      review: {
        lookup_input: { kind: "mpn", value: "TPD6E05U06RVZR" },
        enrichment_result: {
          ...EMPTY_RESULT,
          category: "ESD Protection",
          mpn: sourced("TPD6E05U06RVZR", "digikey"),
          manufacturer: sourced("Texas Instruments", "digikey"),
          description: sourced("Six-channel ESD protection array", "digikey"),
          datasheet_url: sourced(
            "https://www.ti.com/lit/ds/symlink/tpd6e05u06.pdf",
            "digikey",
          ),
          source_states: { mouser: "not_configured", digikey: "success" },
          official_payloads: {
            digikey: {
              Products: [{ ManufacturerProductNumber: "TPD6E05U06RVZR" }],
            },
          },
          official_evidence: {
            digikey: {
              provider: "digikey",
              queried_mpn: "TPD6E05U06RVZR",
              canonical_mpn: "TPD6E05U06RVZR",
              selected_values: { mpn: "TPD6E05U06RVZR" },
            },
          },
        },
        candidates: [
          {
            client_id: "candidate-7",
            vendor: "digikey",
            display_name: "TPD6E05U06RVZR",
            entry_name: "TPD6E05U06RVZR",
            category: "ESD Protection",
            mpn: "TPD6E05U06RVZR",
            manufacturer: "Texas Instruments",
            description: "Six-channel ESD protection array",
            tags: ["esd"],
            purchase: [],
            gaps: [],
            specs: [],
            alternates: [],
            enrichment: [],
            official_payloads: {
              digikey: {
                Products: [{ ManufacturerProductNumber: "TPD6E05U06RVZR" }],
              },
            },
            official_evidence: {
              digikey: {
                provider: "digikey",
                queried_mpn: "TPD6E05U06RVZR",
                canonical_mpn: "TPD6E05U06RVZR",
                selected_values: { mpn: "TPD6E05U06RVZR" },
              },
            },
            datasheet_url: "https://www.ti.com/lit/ds/symlink/tpd6e05u06.pdf",
            conflicts: [],
          },
        ],
      },
    };
    const fetchDraft = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify(storedDraft), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );

    expect(readUiSession().intake_draft_ref).toEqual(session.intake_draft_ref);
    wrapper(<IngestPage />);
    expect(readUiSession().intake_draft_ref).toEqual(session.intake_draft_ref);

    await waitFor(() =>
      expect(fetchDraft).toHaveBeenCalledWith(
        expect.stringContaining(
          "/api/intake-drafts/4f204a7e-e610-4a75-b575-569bca2b3470?revision=2",
        ),
        expect.objectContaining({ method: "GET" }),
      ),
    );
    await waitFor(() =>
      expect(screen.getByRole("textbox", { name: /product link or part number/i }))
        .toHaveValue("TPD6E05U06RVZR"),
    );
    expect(await screen.findByText("Texas Instruments")).toBeInTheDocument();
    mockApi.ingestCommit.mockResolvedValue(
      makePartDetail({ id: "tpd6e05u06rvzr", mpn: "TPD6E05U06RVZR" }),
    );
    await userEvent.click(screen.getByRole("button", { name: "Add And Continue" }));
    await waitFor(() => expect(mockApi.ingestCommit).toHaveBeenCalledTimes(1));
    expect(mockApi.ingestCommit.mock.calls[0][0].official_payloads).toEqual(
      storedDraft.review.candidates[0].official_payloads,
    );
    expect(mockApi.ingestCommit.mock.calls[0][0].official_evidence).toEqual(
      storedDraft.review.candidates[0].official_evidence,
    );
  });

  it("exposes one identity-to-coherent-network path and no local-file control", () => {
    wrapper(<IngestPage />);

    expect(screen.getByText("Resolve Identification + Data")).toBeInTheDocument();
    expect(screen.getByText("Add Once")).toBeInTheDocument();
    expect(screen.getByText("Choose CAD In Manage Models")).toBeInTheDocument();
    expect(screen.getByText(/available metadata, datasheet, provenance/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /browse/i })).not.toBeInTheDocument();
    expect(screen.queryByText(/vendor zip/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/drop.*zip/i)).not.toBeInTheDocument();
    expect(screen.queryByText("Import A List")).not.toBeInTheDocument();
  });

  it("routes a bare part number through exact MPN lookup", async () => {
    mockApi.enrichPart.mockResolvedValue({ job_id: "mpn-1" });
    mockApi.openJobStream.mockResolvedValue(
      streamOf({
        ...EMPTY_RESULT,
        mpn: sourced("ERJ-P03F1101V"),
        manufacturer: sourced("Panasonic"),
      }),
    );
    wrapper(<IngestPage />);
    const user = userEvent.setup();

    await user.type(screen.getByLabelText("Product link or part number"), "ERJ-P03F1101V");
    await user.click(screen.getByRole("button", { name: "Look Up" }));

    expect(mockApi.enrichPart).toHaveBeenCalledWith("ERJ-P03F1101V", undefined, undefined);
    expect(mockApi.enrichFromUrl).not.toHaveBeenCalled();
    expect(await screen.findByText("Review and Add")).toBeInTheDocument();
  });

  it("stages a non-passive and records CAD Needed without launching capture", async () => {
    mockApi.enrichFromUrl.mockResolvedValue({ job_id: "url-1" });
    mockApi.openJobStream.mockResolvedValue(
      streamOf({
        ...EMPTY_RESULT,
        category: "ICs",
        mpn: sourced("TPD6E05U06RVZR"),
        manufacturer: sourced("Texas Instruments"),
        description: sourced("6-channel ESD array"),
        datasheet_url: sourced("https://ti.com/tpd.pdf"),
      } as EnrichmentResult),
    );
    mockApi.ingestCommit.mockResolvedValue(
      makePartDetail({
        id: "tpd6e05u06rvzr",
        derived: { display_name: "TPD6E05U06RVZR" },
      }),
    );
    wrapper(<IngestPage />);
    const user = userEvent.setup();

    await user.type(
      screen.getByLabelText("Product link or part number"),
      "https://www.mouser.com/ProductDetail/Texas-Instruments/TPD6E05U06RVZR",
    );
    await user.click(screen.getByRole("button", { name: "Look Up" }));
    await screen.findByText("Review and Add");

    expect(screen.getByLabelText("Part Number")).toHaveValue("TPD6E05U06RVZR");
    expect(screen.getByText("CAD Added When You Choose")).toBeInTheDocument();
    expect(
      screen.getByText(/Stockroom never opens a provider or starts a CAD download unattended/i),
    ).toBeInTheDocument();
    expect(screen.queryByText("Automatic Source Ladder")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Add And Continue" }));
    await waitFor(() => expect(mockApi.ingestCommit).toHaveBeenCalledTimes(1));
    const candidate = mockApi.ingestCommit.mock.calls[0][0];
    expect(candidate.symbol_lib_path).toBeNull();
    expect(candidate.symbol_name).toBe("");
    expect(candidate.footprint_variants).toEqual([]);
    expect(candidate.model_path).toBeNull();
    expect(candidate.datasheet_path).toBeNull();
    expect(screen.getByText("CAD Needed")).toBeInTheDocument();
    expect(screen.getByTestId("continuation")).toHaveAttribute("data-active", "");
    expect(screen.getByTestId("continuation")).toHaveAttribute("data-add-open", "true");
  });

  it("opens an existing normalized-MPN match only after the explicit recovery action", async () => {
    mockApi.enrichPart.mockResolvedValue({ job_id: "existing-1" });
    mockApi.openJobStream.mockResolvedValue(
      streamOf({
        ...EMPTY_RESULT,
        category: "ICs",
        mpn: sourced("ABC.123"),
        manufacturer: sourced("Acme"),
        description: sourced("Interface controller"),
        datasheet_url: sourced("https://example.com/abc.pdf"),
      }),
    );
    mockApi.ingestCommit.mockRejectedValue(
      new ApiError(
        409,
        "MPN 'ABC.123' already exists as 'ABC-123'",
        undefined,
        "mpn_conflict",
        "abc-123-a1b2",
        "ABC-123",
      ),
    );
    wrapper(<IngestPage />);
    const user = userEvent.setup();

    await user.type(screen.getByLabelText("Product link or part number"), "ABC.123");
    await user.click(screen.getByRole("button", { name: "Look Up" }));
    await user.click(await screen.findByRole("button", { name: "Add And Continue" }));

    expect(await screen.findByText("ABC-123 exists in Components.")).toBeInTheDocument();
    expect(screen.getByTestId("continuation")).toHaveAttribute("data-active", "");
    expect(screen.getByTestId("continuation")).toHaveAttribute("data-add-open", "true");

    await user.click(screen.getAllByRole("button", { name: "Open Component" })[0]);
    expect(screen.getByTestId("continuation")).toHaveAttribute("data-active", "abc-123-a1b2");
    expect(screen.getByTestId("continuation")).toHaveAttribute("data-route", "components");
    expect(screen.getByTestId("continuation")).toHaveAttribute("data-add-open", "false");
  });

  it("accepts exact LCSC catalogue metadata without creating an LCSC CAD path", async () => {
    mockApi.enrichPart.mockResolvedValue({ job_id: "lcsc-1" });
    mockApi.openJobStream.mockResolvedValue(
      streamOf({
        ...EMPTY_RESULT,
        category: "ICs",
        mpn: sourced("S1M", "lcsc"),
        manufacturer: sourced("onsemi", "lcsc"),
        description: sourced("Rectifier diode", "lcsc"),
        specs: {
          product_url: sourced("https://www.lcsc.com/product-detail/C7420317.html", "lcsc"),
        },
        source_states: { mouser: "success", digikey: "not_configured", lcsc: "success" },
      } as EnrichmentResult),
    );
    wrapper(<IngestPage />);
    const user = userEvent.setup();

    await user.type(screen.getByLabelText("Product link or part number"), "S1M");
    await user.click(screen.getByRole("button", { name: "Look Up" }));

    expect(await screen.findByText("Review and Add")).toBeInTheDocument();
    expect(screen.getByLabelText("Part Number")).toHaveValue("S1M");
    expect(screen.queryByText(/EasyEDA/i)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /browse/i })).not.toBeInTheDocument();
  });

  it("rejects an LCSC near match instead of staging substitute geometry", async () => {
    mockApi.enrichPart.mockResolvedValue({ job_id: "near-1" });
    mockApi.openJobStream.mockResolvedValue(
      streamOf({
        ...EMPTY_RESULT,
        mpn: sourced("US1M", "lcsc"),
        manufacturer: sourced("R+O", "lcsc"),
      }),
    );
    wrapper(<IngestPage />);
    const user = userEvent.setup();

    await user.type(screen.getByLabelText("Product link or part number"), "S1M");
    await user.click(screen.getByRole("button", { name: "Look Up" }));

    expect(
      await screen.findByText(/No exact manufacturer and part-number match was proven/i),
    ).toBeInTheDocument();
    expect(screen.queryByText("Review and Add")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Add And Continue" })).not.toBeInTheDocument();
  });

  it("shows an official near MPN as an explicit correction and re-runs exact lookup", async () => {
    mockApi.enrichPart
      .mockResolvedValueOnce({ job_id: "typo-1" })
      .mockResolvedValueOnce({ job_id: "corrected-1" });
    mockApi.openJobStream
      .mockResolvedValueOnce(streamOf({
        ...EMPTY_RESULT,
        source_states: { digikey: "unavailable" },
        identity_suggestions: { digikey: ["ADG714BRUZ-REEL", "ADG714BRUZ-REEL7"] },
      } as EnrichmentResult))
      .mockResolvedValueOnce(streamOf({
        ...EMPTY_RESULT,
        mpn: sourced("ADG714BRUZ-REEL", "digikey"),
        manufacturer: sourced("Analog Devices", "digikey"),
      }));
    wrapper(<IngestPage />);
    const user = userEvent.setup();

    await user.type(screen.getByLabelText("Product link or part number"), "DG714BRUZ-REEL");
    await user.click(screen.getByRole("button", { name: "Look Up" }));
    await user.click(await screen.findByRole("button", { name: "Use ADG714BRUZ-REEL" }));

    expect(mockApi.enrichPart).toHaveBeenNthCalledWith(2, "ADG714BRUZ-REEL", undefined, undefined);
    expect(await screen.findByText("Review and Add")).toBeInTheDocument();
    expect(screen.getByLabelText("Part Number")).toHaveValue("ADG714BRUZ-REEL");
  });

  it("shows every pulled spec disagreement while keeping local CAD absent", async () => {
    mockApi.enrichFromUrl.mockResolvedValue({ job_id: "spec-1" });
    mockApi.openJobStream.mockResolvedValue(
      streamOf({
        ...EMPTY_RESULT,
        category: "ICs",
        mpn: sourced("TPD6E05U06RVZR"),
        specs: {
          "Working Voltage": sourced("5.5 V"),
          product_url: sourced("https://mouser.com/x"),
        },
        spec_conflicts: {
          "Working Voltage": [sourced("5.5 V"), sourced("6 V", "digikey")],
        },
      } as EnrichmentResult),
    );
    wrapper(<IngestPage />);
    const user = userEvent.setup();

    await user.type(
      screen.getByLabelText("Product link or part number"),
      "https://www.mouser.com/ProductDetail/Texas-Instruments/TPD6E05U06RVZR",
    );
    await user.click(screen.getByRole("button", { name: "Look Up" }));

    const table = await screen.findByRole("region", { name: "Pulled Specs" });
    expect(table).toHaveTextContent("5.5 V");
    expect(table).toHaveTextContent("6 V");
    expect(table).toHaveTextContent("DigiKey");
    expect(table).not.toHaveTextContent("mouser.com/x");
    expect(screen.queryByRole("button", { name: /browse/i })).not.toBeInTheDocument();
  });

  it("shows only the server-selected Mouser-first specification projection", async () => {
    mockApi.enrichPart.mockResolvedValue({ job_id: "authority-1" });
    mockApi.openJobStream.mockResolvedValue(
      streamOf({
        ...EMPTY_RESULT,
        category: "Switches",
        mpn: sourced("ADG714BRUZ-REEL"),
        manufacturer: sourced("Analog Devices"),
        specs: {
          "Supply Voltage": sourced("3.3 V", "lcsc"),
          "LCSC Internal Category": sourced("123", "lcsc"),
        },
        selected_specs: {
          "Supply Voltage": sourced("5 V", "mouser"),
          "Current Rating": sourced("30 mA", "digikey"),
        },
        selected_spec_conflicts: {
          "Supply Voltage": [sourced("5 V", "mouser"), sourced("4.8 V", "digikey")],
        },
      } as EnrichmentResult),
    );
    wrapper(<IngestPage />);
    const user = userEvent.setup();

    await user.type(screen.getByLabelText("Product link or part number"), "ADG714BRUZ-REEL");
    await user.click(screen.getByRole("button", { name: "Look Up" }));

    const table = await screen.findByRole("region", { name: "Pulled Specs" });
    expect(table).toHaveTextContent("5 V");
    expect(table).toHaveTextContent("4.8 V");
    expect(table).toHaveTextContent("30 mA");
    expect(table).not.toHaveTextContent("3.3 V");
    expect(table).not.toHaveTextContent("LCSC Internal Category");
  });
});
