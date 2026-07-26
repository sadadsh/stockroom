import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { api } from "../api/client";
import type { RescanStateResponse } from "../api/types";
import { ToastProvider } from "../lib/toast";
import { RescanSection } from "./RescanSection";

vi.mock("../api/client", async (importActual) => {
  const actual = await importActual<typeof import("../api/client")>();
  return {
    ...actual,
    api: { rescanLibrary: vi.fn(), getRescanState: vi.fn(), openJobStream: vi.fn() },
  };
});

const mockApi = vi.mocked(api);

const NEVER_RUN: RescanStateResponse = { parts: {}, counts: {} };

const LAST_RUN: RescanStateResponse = {
  parts: {
    lm358: { checked_at: "2026-07-10T12:00:00+00:00", outcome: "updated" },
    tps1: { checked_at: "2026-07-11T09:30:00+00:00", outcome: "failed" },
  },
  counts: { updated: 1, failed: 1 },
};

function streamOf(chunks: string[]): ReadableStream<Uint8Array> {
  const enc = new TextEncoder();
  return new ReadableStream<Uint8Array>({
    start(controller) {
      for (const c of chunks) controller.enqueue(enc.encode(c));
      controller.close();
    },
  });
}

function renderSection() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={qc}>
      <ToastProvider>
        <RescanSection />
      </ToastProvider>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  mockApi.getRescanState.mockResolvedValue(NEVER_RUN);
});

describe("RescanSection", () => {
  it("shows an honest never-run state with no last-refreshed line", async () => {
    renderSection();
    expect(await screen.findByTestId("rescan-never-run")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Refresh Prices & Stock/ })).toBeInTheDocument();
  });

  it("shows the last-known rescan summary with an honest failed count", async () => {
    mockApi.getRescanState.mockResolvedValue(LAST_RUN);
    renderSection();

    const summary = await screen.findByTestId("rescan-last-summary");
    expect(summary).toHaveTextContent("Last refreshed");
    expect(summary).toHaveTextContent("2");
    const tally = screen.getByTestId("rescan-tally");
    expect(tally).toHaveTextContent("1 Updated");
    expect(tally).toHaveTextContent("1 Failed");
  });

  it("runs a rescan end to end and shows the terminal summary including paused providers", async () => {
    mockApi.rescanLibrary.mockResolvedValue({ job_id: "j1" });
    mockApi.openJobStream.mockResolvedValue(
      streamOf([
        'event: progress\ndata: {"pct":0,"done":0,"total":2,"message":"2 parts to refresh"}\n\n',
        'event: progress\ndata: {"pct":50,"done":1,"total":2,"part_id":"lm358","outcome":"updated"}\n\n',
        'event: progress\ndata: {"pct":100,"done":2,"total":2,"part_id":"tps1","outcome":"failed"}\n\n',
        'event: result\ndata: {"result":{"total":2,"updated":1,"unchanged":0,"no_data":0,"failed":1,"paused_providers":["Mouser"],"message":"Refreshed 1 of 2 (0 unchanged, 0 no data, 1 failed) (paused: Mouser)"}}\n\n',
        "event: done\ndata: {}\n\n",
      ]),
    );
    renderSection();
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: /Refresh Prices & Stock/ }));

    expect(await screen.findByTestId("rescan-done")).toBeInTheDocument();
    expect(mockApi.rescanLibrary).toHaveBeenCalledWith(false);
    const tally = screen.getByTestId("rescan-tally");
    expect(tally).toHaveTextContent("1 Updated");
    expect(tally).toHaveTextContent("1 Failed");
    const paused = screen.getByTestId("rescan-paused");
    expect(paused).toHaveTextContent("Mouser");
    expect(screen.getByText(/Refreshed 1 of 2/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Refresh Again/ })).toBeInTheDocument();
  });

  it("checking Force Full Rescan sends force=true to the API", async () => {
    mockApi.rescanLibrary.mockResolvedValue({ job_id: "j2" });
    mockApi.openJobStream.mockResolvedValue(streamOf(["event: done\ndata: {}\n\n"]));
    renderSection();
    const user = userEvent.setup();

    await user.click(screen.getByText("Force Full Rescan"));
    await user.click(await screen.findByRole("button", { name: /Refresh Prices & Stock/ }));

    await waitFor(() => expect(mockApi.rescanLibrary).toHaveBeenCalledWith(true));
  });

  it("attaches to an already-running rescan and toasts instead of starting a second one", async () => {
    mockApi.rescanLibrary.mockResolvedValue({ job_id: "shared", already_running: true });
    mockApi.openJobStream.mockResolvedValue(
      streamOf([
        'event: progress\ndata: {"pct":80,"done":8,"total":10,"part_id":"midway","outcome":"updated"}\n\n',
        "event: done\ndata: {}\n\n",
      ]),
    );
    renderSection();
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: /Refresh Prices & Stock/ }));

    expect(
      await screen.findByText(/already running\. Showing its live progress\./),
    ).toBeInTheDocument();
  });

  it("surfaces a stream-open failure as an inline error", async () => {
    mockApi.rescanLibrary.mockResolvedValue({ job_id: "j3" });
    mockApi.openJobStream.mockRejectedValue(new Error("connection refused"));
    renderSection();
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: /Refresh Prices & Stock/ }));

    expect(await screen.findByTestId("rescan-error")).toHaveTextContent("connection refused");
  });
});
