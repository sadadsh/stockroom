import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { ApiError, api } from "../api/client";
import type { PartDetail, StagingCandidate } from "../api/types";
import { ToastProvider } from "../lib/toast";
import { IngestPage } from "./IngestPage";

vi.mock("../api/client", async (im) => {
  const actual = await im<typeof import("../api/client")>();
  return {
    ...actual,
    api: {
      ...actual.api,
      ingestInspect: vi.fn(),
      openJobStream: vi.fn(),
      ingestCommit: vi.fn(),
    },
  };
});
const mockApi = vi.mocked(api);

function streamOf(chunks: string[]): ReadableStream<Uint8Array> {
  const enc = new TextEncoder();
  return new ReadableStream<Uint8Array>({
    start(c) {
      for (const s of chunks) c.enqueue(enc.encode(s));
      c.close();
    },
  });
}

const CANDIDATE: StagingCandidate = {
  vendor: "lcsc",
  symbol_lib_path: "/tmp/SR-ICs.kicad_sym",
  symbol_name: "NE555P",
  footprint_variants: ["/tmp/DIP-8.kicad_mod", "/tmp/SOIC-8.kicad_mod"],
  chosen_footprint_index: 0,
  model_path: null,
  datasheet_path: "/tmp/ne555.pdf",
  display_name: "NE555P",
  entry_name: "NE555P",
  category: "ICs",
  mpn: "NE555P",
  manufacturer: "Texas Instruments",
  description: "Single timer",
  tags: ["timer"],
  purchase: [],
  gaps: ["no 3D model in this package"],
};

const PART_DETAIL = { id: "ne555", display_name: "NE555P" } as PartDetail;

function resultStream(candidates: StagingCandidate[]): ReadableStream<Uint8Array> {
  return streamOf([
    'event: progress\ndata: {"pct":50,"message":"fetching"}\n\n',
    `event: result\ndata: ${JSON.stringify({ result: candidates })}\n\n`,
    "event: done\ndata: {}\n\n",
  ]);
}

function wrap(ui: ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <ToastProvider>{ui}</ToastProvider>
    </QueryClientProvider>,
  );
}

async function inspectOnce(candidates: StagingCandidate[]) {
  mockApi.ingestInspect.mockResolvedValue({ job_id: "j1" });
  mockApi.openJobStream.mockResolvedValue(resultStream(candidates));
  wrap(<IngestPage />);
  const user = userEvent.setup();
  await user.type(screen.getByLabelText("LCSC Part IDs"), "C123");
  await user.click(screen.getByRole("button", { name: "Inspect" }));
  return user;
}

describe("IngestPage", () => {
  it("inspects an LCSC id and renders the returned staging candidate", async () => {
    const user = await inspectOnce([CANDIDATE]);
    expect(mockApi.ingestInspect).toHaveBeenCalledWith([], ["C123"]);
    // The candidate's proposed name lands in an editable field.
    expect(await screen.findByLabelText("Name")).toHaveValue("NE555P");
    // Its gap is surfaced honestly.
    expect(screen.getByText(/no 3D model/i)).toBeInTheDocument();
    void user;
  });

  it("commits a candidate and reports success", async () => {
    const user = await inspectOnce([CANDIDATE]);
    await screen.findByLabelText("Name");
    mockApi.ingestCommit.mockResolvedValue(PART_DETAIL);

    await user.click(screen.getByRole("button", { name: "Add To Library" }));

    expect(mockApi.ingestCommit).toHaveBeenCalledTimes(1);
    expect(await screen.findByText(/Added NE555P/i)).toBeInTheDocument();
  });

  it("surfaces the complete-to-add gate missing fields on a 422", async () => {
    const user = await inspectOnce([CANDIDATE]);
    await screen.findByLabelText("Name");
    mockApi.ingestCommit.mockRejectedValue(
      new ApiError(422, "IncompleteError", ["3D model", "purchase link"]),
    );

    await user.click(screen.getByRole("button", { name: "Add To Library" }));

    const card = (await screen.findByText("3D model")).closest("[data-candidate]")!;
    expect(within(card as HTMLElement).getByText("3D model")).toBeInTheDocument();
    expect(within(card as HTMLElement).getByText("purchase link")).toBeInTheDocument();
  });

  it("shows an honest empty state when inspection finds nothing", async () => {
    const user = await inspectOnce([]);
    expect(await screen.findByText(/No parts found/i)).toBeInTheDocument();
    void user;
  });
});
