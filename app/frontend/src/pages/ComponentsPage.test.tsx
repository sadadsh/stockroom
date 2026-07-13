import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { ApiError } from "../api/client";
import { api } from "../api/client";
import type { PartDetail, PartSummary } from "../api/types";
import { ComponentsPage } from "./ComponentsPage";

// Mock the typed client so the page renders against fixtures, not a live server.
// ApiError is preserved (the page branches on it for the error surface).
vi.mock("../api/client", async (importActual) => {
  const actual = await importActual<typeof import("../api/client")>();
  return {
    ...actual,
    api: {
      listParts: vi.fn(),
      facets: vi.fn(),
      partDetail: vi.fn(),
    },
  };
});

const mockApi = vi.mocked(api);

const SUMMARY: PartSummary = {
  id: "lm358",
  display_name: "LM358",
  category: "ICs",
  mpn: "LM358DR",
  manufacturer: "Texas Instruments",
  is_complete: true,
  missing: [],
};

const DETAIL: PartDetail = {
  id: "lm358",
  display_name: "LM358",
  category: "ICs",
  description: "Dual Operational Amplifier",
  tags: ["op-amp"],
  mpn: "LM358DR",
  manufacturer: "Texas Instruments",
  datasheet: null,
  purchase: [],
  symbol: null,
  footprint: null,
  model: null,
  provenance: null,
  hashes: null,
  enrichment: {},
};

function wrap(ui: ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>);
}

describe("ComponentsPage", () => {
  it("lists parts, shows the count, and auto-selects the first part's detail", async () => {
    mockApi.listParts.mockResolvedValue({ parts: [SUMMARY], count: 1 });
    mockApi.facets.mockResolvedValue({
      by_category: { ICs: 1 },
      by_manufacturer: { "Texas Instruments": 1 },
      complete: 1,
      incomplete: 0,
    });
    mockApi.partDetail.mockResolvedValue(DETAIL);

    wrap(<ComponentsPage />);

    expect(await screen.findByText("LM358")).toBeInTheDocument();
    expect(await screen.findByText("1 Parts")).toBeInTheDocument();
    // The detail panel is the only surface that renders the description.
    expect(await screen.findByText("Dual Operational Amplifier")).toBeInTheDocument();
  });

  it("shows the honest empty state when the library has no parts", async () => {
    mockApi.listParts.mockResolvedValue({ parts: [], count: 0 });
    mockApi.facets.mockResolvedValue({
      by_category: {},
      by_manufacturer: {},
      complete: 0,
      incomplete: 0,
    });

    wrap(<ComponentsPage />);

    expect(await screen.findByText("Your Library Is Empty")).toBeInTheDocument();
  });

  it("shows an honest retry surface when the server is unreachable", async () => {
    mockApi.listParts.mockRejectedValue(new ApiError(0, "connection refused"));
    mockApi.facets.mockResolvedValue({
      by_category: {},
      by_manufacturer: {},
      complete: 0,
      incomplete: 0,
    });

    wrap(<ComponentsPage />);

    expect(
      await screen.findByText("Cannot reach the Stockroom server."),
    ).toBeInTheDocument();
    expect(screen.getByText("Try Again")).toBeInTheDocument();
  });
});
