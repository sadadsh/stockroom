import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { useEffect, useState, type ReactNode } from "react";
import userEvent from "@testing-library/user-event";

import { api } from "../api/client";
import type { EnrichmentResult } from "../api/types";
import { AddPartProvider, useAddPart } from "../lib/addPart";
import { CaptureProvider, useCapture } from "../lib/capture";
import { ThemeProvider } from "../lib/theme";
import { ToastProvider } from "../lib/toast";
import { defaultUiSession, readUiSession, resetUiSessionForTests } from "../lib/uiSession";
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
  const { onReopen } = useCapture();
  const { isOpen } = useAddPart();
  const [opened, setOpened] = useState("");
  useEffect(() => onReopen(setOpened), [onReopen]);
  return <div data-testid="continuation" data-reopen={opened} data-add-open={String(isOpen)} />;
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
        <CaptureProvider>
          <AddPartProvider>
            <ToastProvider>
              {ui}
              <OpenAddPartOnMount />
              <ContinuationProbe />
            </ToastProvider>
          </AddPartProvider>
        </CaptureProvider>
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
  it("restores a server-staged network draft without putting raw fields in the session", async () => {
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
  });

  it("exposes one identity-to-coherent-network path and no local-file control", () => {
    wrapper(<IngestPage />);

    expect(screen.getByText("Resolve Identification + Data")).toBeInTheDocument();
    expect(screen.getByText("Add Once")).toBeInTheDocument();
    expect(screen.getByText("Collect One KiCad + Altium + STEP Package")).toBeInTheDocument();
    expect(screen.getByText(/available metadata, datasheet, provenance/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /browse/i })).not.toBeInTheDocument();
    expect(screen.queryByText(/vendor zip/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/drop.*zip/i)).not.toBeInTheDocument();
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

  it("stages a non-passive as metadata-only and hands off to network capture", async () => {
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
    expect(screen.getByText("Automatic Source Ladder")).toBeInTheDocument();
    expect(
      screen.getByText(/Identification-alone sources can contribute data but never active CAD/i),
    ).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Add to Components" }));
    await waitFor(() => expect(mockApi.ingestCommit).toHaveBeenCalledTimes(1));
    const candidate = mockApi.ingestCommit.mock.calls[0][0];
    expect(candidate.symbol_lib_path).toBeNull();
    expect(candidate.symbol_name).toBe("");
    expect(candidate.footprint_variants).toEqual([]);
    expect(candidate.model_path).toBeNull();
    expect(candidate.datasheet_path).toBeNull();
    expect(screen.getByTestId("continuation")).toHaveAttribute("data-reopen", "tpd6e05u06rvzr");
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
    expect(screen.queryByRole("button", { name: "Add to Components" })).not.toBeInTheDocument();
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
});
