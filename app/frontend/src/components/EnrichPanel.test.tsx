import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { ApiError, api } from "../api/client";
import type { EnrichmentResult } from "../api/types";
import { EnrichPanel } from "./EnrichPanel";

// The enrich lookup is the only api call this panel makes; mock it directly.
vi.mock("../api/client", async (importActual) => {
  const actual = await importActual<typeof import("../api/client")>();
  return { ...actual, api: { ...actual.api, enrichPart: vi.fn() } };
});

const mockApi = vi.mocked(api);

function result(over: Partial<EnrichmentResult> = {}): EnrichmentResult {
  return {
    category: "ICs",
    mpn: null,
    manufacturer: null,
    description: null,
    datasheet_url: null,
    stock: null,
    package: null,
    price_breaks: [],
    specs: {},
    schema_version: 1,
    ...over,
  };
}

function wrap(ui: ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>);
}

const EMPTY_CURRENT = { manufacturer: "", description: "" };

describe("EnrichPanel", () => {
  it("looks the part up by MPN and renders each sourced field with its source", async () => {
    mockApi.enrichPart.mockResolvedValue(
      result({
        manufacturer: { value: "Texas Instruments", source: "jsonld", confidence: "high" },
        description: { value: "Dual Op-Amp", source: "datasheet", confidence: "medium" },
      }),
    );
    wrap(
      <EnrichPanel
        mpn="LM358DR"
        category="ICs"
        current={EMPTY_CURRENT}
        onApply={vi.fn()}
      />,
    );
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: "Enrich From Distributor" }));

    expect(mockApi.enrichPart).toHaveBeenCalledWith("LM358DR", "ICs", undefined);
    expect(await screen.findByText("Texas Instruments")).toBeInTheDocument();
    expect(screen.getByText("Dual Op-Amp")).toBeInTheDocument();
    // The source and confidence are surfaced so the user can judge the value.
    expect(screen.getByText(/jsonld/)).toBeInTheDocument();
  });

  it("applies a sourced field into the record through onApply", async () => {
    mockApi.enrichPart.mockResolvedValue(
      result({
        manufacturer: { value: "Texas Instruments", source: "jsonld", confidence: "high" },
      }),
    );
    const onApply = vi.fn();
    wrap(
      <EnrichPanel mpn="LM358DR" category="ICs" current={EMPTY_CURRENT} onApply={onApply} />,
    );
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: "Enrich From Distributor" }));
    const row = (await screen.findByText("Texas Instruments")).closest("div")!;
    await user.click(within(row).getByRole("button", { name: "Apply" }));

    expect(onApply).toHaveBeenCalledWith("manufacturer", "Texas Instruments");
  });

  it("does not offer Apply when the record already holds the sourced value", async () => {
    mockApi.enrichPart.mockResolvedValue(
      result({
        manufacturer: { value: "Texas Instruments", source: "jsonld", confidence: "high" },
      }),
    );
    wrap(
      <EnrichPanel
        mpn="LM358DR"
        category="ICs"
        current={{ manufacturer: "Texas Instruments", description: "" }}
        onApply={vi.fn()}
      />,
    );
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: "Enrich From Distributor" }));

    expect(await screen.findByText("Already Set")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Apply" })).not.toBeInTheDocument();
  });

  it("offers Apply Pinout when the lookup surfaces a pinout and applies it", async () => {
    const pins = [
      { pin: "1", name: "OUT1" },
      { pin: "2", name: "IN1-" },
    ];
    mockApi.enrichPart.mockResolvedValue(
      result({
        specs: { pinout: { value: pins, source: "datasheet", confidence: "high" } },
      }),
    );
    const onApplyPinout = vi.fn();
    wrap(
      <EnrichPanel
        mpn="LM358DR"
        category="ICs"
        current={EMPTY_CURRENT}
        onApply={vi.fn()}
        onApplyPinout={onApplyPinout}
      />,
    );
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: "Enrich From Distributor" }));
    // it reports how many pins it found
    expect(await screen.findByText(/2 pins/i)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Apply Pinout" }));

    expect(onApplyPinout).toHaveBeenCalledWith({
      value: pins,
      source: "datasheet",
      confidence: "high",
    });
  });

  it("shows Already Set for the pinout when the record already has one", async () => {
    mockApi.enrichPart.mockResolvedValue(
      result({
        specs: {
          pinout: { value: [{ pin: "1", name: "OUT1" }], source: "datasheet", confidence: "high" },
        },
      }),
    );
    wrap(
      <EnrichPanel
        mpn="LM358DR"
        category="ICs"
        current={EMPTY_CURRENT}
        onApply={vi.fn()}
        onApplyPinout={vi.fn()}
        hasPinout
      />,
    );
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: "Enrich From Distributor" }));

    expect(await screen.findByText(/1 pin/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Apply Pinout" })).not.toBeInTheDocument();
  });

  it("says so honestly when the lookup finds nothing new", async () => {
    mockApi.enrichPart.mockResolvedValue(result());
    wrap(
      <EnrichPanel mpn="MYSTERY-PART" category="Other" current={EMPTY_CURRENT} onApply={vi.fn()} />,
    );
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: "Enrich From Distributor" }));

    expect(
      await screen.findByText(/No new data found/i),
    ).toBeInTheDocument();
  });

  it("surfaces a lookup failure honestly instead of a silent no-op", async () => {
    mockApi.enrichPart.mockRejectedValue(new ApiError(500, "scraper crashed"));
    wrap(
      <EnrichPanel mpn="LM358DR" category="ICs" current={EMPTY_CURRENT} onApply={vi.fn()} />,
    );
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: "Enrich From Distributor" }));

    expect(await screen.findByText(/scraper crashed/)).toBeInTheDocument();
  });
});
