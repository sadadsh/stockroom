import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { api } from "../api/client";
import type { BulkReport } from "../api/types";
import { ToastProvider } from "../lib/toast";
import { BomPage } from "./BomPage";

vi.mock("../api/client", async (im) => {
  const actual = await im<typeof import("../api/client")>();
  return {
    ...actual,
    api: {
      ...actual.api,
      bomMatch: vi.fn(),
      enrichBulk: vi.fn(),
      openJobStream: vi.fn(),
    },
  };
});
const mockApi = vi.mocked(api);

function wrap(ui: ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <ToastProvider>{ui}</ToastProvider>
    </QueryClientProvider>,
  );
}

function streamOf(chunks: string[]): ReadableStream<Uint8Array> {
  const enc = new TextEncoder();
  return new ReadableStream<Uint8Array>({
    start(c) {
      for (const s of chunks) c.enqueue(enc.encode(s));
      c.close();
    },
  });
}

const MATCH = {
  items: [
    {
      mpn: "TPS62130RGTR",
      part_id: "tps62130",
      display_name: "TPS62130",
      is_complete: true,
      missing: [],
      matches: 1,
    },
    {
      mpn: "WIDGET99",
      part_id: null,
      display_name: "",
      is_complete: false,
      missing: [],
      matches: 0,
    },
  ],
  in_library: 1,
  total: 2,
};

describe("BomPage", () => {
  it("checks a pasted BOM against the library and reports per line", async () => {
    mockApi.bomMatch.mockResolvedValue(MATCH);
    wrap(<BomPage />);
    const user = userEvent.setup();
    await user.type(screen.getByTestId("bom-input"), "TPS62130RGTR\nWIDGET99");
    await user.click(screen.getByRole("button", { name: "Check Against Components" }));

    expect(mockApi.bomMatch).toHaveBeenCalledWith({ text: "TPS62130RGTR\nWIDGET99" });
    expect(await screen.findByTestId("bom-row-TPS62130RGTR")).toHaveTextContent(
      "In Components",
    );
    expect(screen.getByTestId("bom-row-WIDGET99")).toHaveTextContent("Not In Components");
    // the focal count reads coverage at a glance
    expect(screen.getByTestId("bom-coverage")).toHaveTextContent("1/2");
  });

  it("routes a comma-bearing paste to the CSV parser", async () => {
    mockApi.bomMatch.mockResolvedValue(MATCH);
    wrap(<BomPage />);
    const user = userEvent.setup();
    await user.type(screen.getByTestId("bom-input"), "Ref,MPN,Qty{enter}U1,TPS62130RGTR,1");
    await user.click(screen.getByRole("button", { name: "Check Against Components" }));
    const arg = mockApi.bomMatch.mock.calls[0][0];
    expect("csv" in arg).toBe(true);
  });

  it("looks up only the missing lines through enrichment and merges the report", async () => {
    mockApi.bomMatch.mockResolvedValue(MATCH);
    mockApi.enrichBulk.mockResolvedValue({ job_id: "j9" });
    const report: BulkReport = {
      items: [
        { mpn: "WIDGET99", complete: false, missing: ["manufacturer"], error: "" },
      ],
      total: 1,
    } as unknown as BulkReport;
    mockApi.openJobStream.mockResolvedValue(
      streamOf([
        `event: result\ndata: ${JSON.stringify({ result: report })}\n\n`,
        "event: done\ndata: {}\n\n",
      ]),
    );

    wrap(<BomPage />);
    const user = userEvent.setup();
    await user.type(screen.getByTestId("bom-input"), "TPS62130RGTR\nWIDGET99");
    await user.click(screen.getByRole("button", { name: "Check Against Components" }));
    await screen.findByTestId("bom-row-WIDGET99");

    await user.click(screen.getByRole("button", { name: "Look Up Missing" }));
    expect(mockApi.enrichBulk).toHaveBeenCalledWith({ text: "WIDGET99" });
    await waitFor(() =>
      expect(screen.getByTestId("bom-row-WIDGET99")).toHaveTextContent(
        /missing manufacturer/i,
      ),
    );
  });
});
