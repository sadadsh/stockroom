import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ApiError, api } from "../api/client";
import type { StagingCandidate } from "../api/types";
import { makePartDetail } from "../test/partFixture";
import { CandidateCard } from "./CandidateCard";

function candidate(): StagingCandidate {
  return {
    vendor: "Mouser",
    symbol_lib_path: null,
    symbol_name: "",
    footprint_variants: [],
    chosen_footprint_index: 0,
    model_path: null,
    datasheet_path: null,
    entry_name: "",
    display_name: "LM358",
    category: "ICs",
    mpn: "LM358DR",
    manufacturer: "TI",
    description: "Dual op amp",
    tags: [],
    gaps: [],
    specs: {},
    enrichment: {},
    alternates: {},
    catalog: {},
    provenance: {
      source: "mouser",
      source_url: "https://example.com/lm358.pdf",
      original_zip_sha256: "",
      ingested_at: "",
    },
    purchase: [
      {
        vendor: "Mouser",
        url: "https://mouser.example/old",
        part_number: "595-LM358DR",
        price_breaks: [{ qty: 1, price: 1.25, currency: "USD" }],
        stock: 250,
        currency: "USD",
        fetched_at: "2026-08-19T12:00:00Z",
      },
      {
        vendor: "DigiKey",
        url: "https://digikey.example/unchanged",
        part_number: "296-LM358DR-ND",
        price_breaks: [{ qty: 10, price: 0.95, currency: "USD" }],
        stock: 900,
        currency: "USD",
        fetched_at: "2026-08-19T12:01:00Z",
      },
    ],
  };
}

describe("CandidateCard purchase editing", () => {
  afterEach(() => vi.restoreAllMocks());

  it("edits only the primary URL and preserves every offer and its evidence", async () => {
    const commit = vi
      .spyOn(api, "ingestCommit")
      .mockResolvedValue(makePartDetail({ id: "lm358", mpn: "LM358DR" }));
    const qc = new QueryClient();
    render(
      <QueryClientProvider client={qc}>
        <CandidateCard
          stagedId="candidate-1"
          candidate={candidate()}
          onCommitted={() => undefined}
          onOpenExisting={() => undefined}
          toast={() => undefined}
        />
      </QueryClientProvider>,
    );

    const url = screen.getByRole("textbox", { name: "Purchase URL" });
    await userEvent.clear(url);
    await userEvent.type(url, "https://mouser.example/new");
    await userEvent.click(screen.getByRole("button", { name: "Add And Continue" }));
    await waitFor(() => expect(commit).toHaveBeenCalled());

    expect(commit.mock.calls[0][0].purchase).toEqual([
      {
        vendor: "Mouser",
        url: "https://mouser.example/new",
        part_number: "595-LM358DR",
        price_breaks: [{ qty: 1, price: 1.25, currency: "USD" }],
        stock: 250,
        currency: "USD",
        fetched_at: "2026-08-19T12:00:00Z",
      },
      {
        vendor: "DigiKey",
        url: "https://digikey.example/unchanged",
        part_number: "296-LM358DR-ND",
        price_breaks: [{ qty: 10, price: 0.95, currency: "USD" }],
        stock: 900,
        currency: "USD",
        fetched_at: "2026-08-19T12:01:00Z",
      },
    ]);
  });

  it("turns a typed MPN conflict into explicit existing-component recovery", async () => {
    vi.spyOn(api, "ingestCommit").mockRejectedValue(
      new ApiError(
        409,
        "MPN 'ABC.123' already exists as 'ABC-123'",
        undefined,
        "mpn_conflict",
        "abc-123-a1b2",
        "ABC-123",
      ),
    );
    const refresh = vi.spyOn(api, "refreshSourcing");
    const onCommitted = vi.fn();
    const onOpenExisting = vi.fn();
    const qc = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
    render(
      <QueryClientProvider client={qc}>
        <CandidateCard
          stagedId="candidate-1"
          candidate={{ ...candidate(), mpn: "ABC.123" }}
          onCommitted={onCommitted}
          onOpenExisting={onOpenExisting}
          toast={() => undefined}
        />
      </QueryClientProvider>,
    );

    await userEvent.click(screen.getByRole("button", { name: "Add And Continue" }));

    expect(await screen.findByText("ABC-123 exists in Components.")).toBeInTheDocument();
    const open = screen.getByRole("button", { name: "Open Component" });
    expect(screen.getByRole("button", { name: "Refresh Evidence" })).toBeInTheDocument();
    expect(onCommitted).not.toHaveBeenCalled();
    expect(onOpenExisting).not.toHaveBeenCalled();
    expect(refresh).not.toHaveBeenCalled();

    await userEvent.click(open);
    expect(onOpenExisting).toHaveBeenCalledWith("abc-123-a1b2");
  });

  it("rejects an MPN correction that would attach part-A official evidence to part B", async () => {
    const commit = vi.spyOn(api, "ingestCommit").mockResolvedValue(
      makePartDetail({ id: "part-b", mpn: "PART-B" }),
    );
    const onFailed = vi.fn();
    const qc = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
    render(
      <QueryClientProvider client={qc}>
        <CandidateCard
          stagedId="candidate-evidence"
          candidate={{
            ...candidate(),
            mpn: "PART-A",
            official_payloads: {
              mouser: {
                SearchResults: { Parts: [{ ManufacturerPartNumber: "PART-A" }] },
              },
            },
            official_evidence: {
              mouser: {
                provider: "mouser",
                queried_mpn: "PART-A",
                canonical_mpn: "PART-A",
                selected_values: { mpn: "PART-A" },
              },
            },
          }}
          onCommitted={() => undefined}
          onFailed={onFailed}
          onOpenExisting={() => undefined}
          toast={() => undefined}
        />
      </QueryClientProvider>,
    );

    const mpn = screen.getByRole("textbox", { name: "Part Number" });
    await userEvent.clear(mpn);
    await userEvent.type(mpn, "PART-B");
    await userEvent.click(screen.getByRole("button", { name: "Add And Continue" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(/evidence belongs to PART-A/i);
    expect(screen.getByRole("alert")).toHaveTextContent(/run lookup again/i);
    expect(commit).not.toHaveBeenCalled();
    expect(onFailed).toHaveBeenCalledWith("PART-B", expect.stringMatching(/PART-A/i));
  });
});
