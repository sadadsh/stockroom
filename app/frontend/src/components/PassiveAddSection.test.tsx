import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { ApiError, api } from "../api/client";
import type { EnrichmentResult, PassiveAddPlan } from "../api/types";
import { ThemeProvider } from "../lib/theme";
import { makePartDetail } from "../test/partFixture";
import { PassiveAddSection } from "./PassiveAddSection";

const RESULT = {
  category: "Resistors",
  mpn: { value: "ABC.123", source: "mouser", confidence: "high" },
  manufacturer: { value: "Acme", source: "mouser", confidence: "high" },
  description: null,
  datasheet_url: { value: "https://example.com/abc.pdf", source: "mouser", confidence: "high" },
  stock: null,
  package: null,
  price_breaks: [],
  specs: {},
  add_plan: null,
  schema_version: 1,
} as EnrichmentResult;

const PLAN: PassiveAddPlan = {
  kind: "resistor",
  package: "0603",
  value: "10 kOhm",
  tolerance: "1%",
};

function refreshStream(): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder();
  return new ReadableStream({
    start(controller) {
      controller.enqueue(
        encoder.encode(
          `event: result\ndata: ${JSON.stringify({ result: makePartDetail({ id: "abc-123-a1b2" }) })}\n\n`,
        ),
      );
      controller.enqueue(encoder.encode("event: done\ndata: {}\n\n"));
      controller.close();
    },
  });
}

describe("PassiveAddSection duplicate recovery", () => {
  afterEach(() => vi.restoreAllMocks());

  it("offers deliberate open and evidence-refresh actions without mutating automatically", async () => {
    vi.spyOn(api, "facets").mockResolvedValue({
      by_category: {},
      by_manufacturer: {},
      complete: 0,
      incomplete: 0,
    });
    vi.spyOn(api, "passivePreview").mockResolvedValue({
      status: "ok",
      record: makePartDetail({
        id: "preview-only",
        mpn: "ABC.123",
        part_class: "passive",
        derived: { display_name: "10 kOhm 0603 Resistor", category: "Resistors" },
      }),
      gaps: [],
      stock_present: true,
    });
    vi.spyOn(api, "passiveAdd").mockRejectedValue(
      new ApiError(
        409,
        "MPN 'ABC.123' already exists as 'ABC-123'",
        undefined,
        "mpn_conflict",
        "abc-123-a1b2",
        "ABC-123",
      ),
    );
    const refresh = vi
      .spyOn(api, "refreshSourcing")
      .mockResolvedValue({ job_id: "refresh-existing" });
    vi.spyOn(api, "openJobStream").mockResolvedValue(refreshStream());
    const onAdded = vi.fn();
    const onOpenExisting = vi.fn();
    const qc = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    render(
      <QueryClientProvider client={qc}>
        <ThemeProvider>
          <PassiveAddSection
            result={RESULT}
            plan={PLAN}
            input="ABC.123"
            onAdded={onAdded}
            onOpenExisting={onOpenExisting}
            toast={() => undefined}
          />
        </ThemeProvider>
      </QueryClientProvider>,
    );

    const add = await screen.findByRole("button", { name: "Add And Continue" });
    await waitFor(() => expect(add).toBeEnabled());
    await userEvent.click(add);

    expect(await screen.findByText("ABC-123 exists in Components.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Open Component" })).toBeInTheDocument();
    const refreshButton = screen.getByRole("button", { name: "Refresh Evidence" });
    expect(onAdded).not.toHaveBeenCalled();
    expect(onOpenExisting).not.toHaveBeenCalled();
    expect(refresh).not.toHaveBeenCalled();

    await userEvent.click(refreshButton);
    await waitFor(() => expect(refresh).toHaveBeenCalledWith("abc-123-a1b2"));
    expect(onOpenExisting).not.toHaveBeenCalled();
  });
});
