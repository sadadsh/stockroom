import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { api } from "../api/client";
import { ThemeProvider } from "../lib/theme";
import { PartTimeline } from "./PartTimeline";

vi.mock("../api/client", async (importActual) => {
  const actual = await importActual<typeof import("../api/client")>();
  return {
    ...actual,
    api: {
      ...actual.api,
      partHistory: vi.fn(),
      partDiff: vi.fn(),
      previewSvg: vi.fn(),
    },
  };
});

const mockApi = vi.mocked(api);

function sha(c: string) {
  return c.repeat(40);
}

const HISTORY = {
  commits: [
    { sha: sha("b"), subject: "Edit tps62130: manufacturer", author: "Sadad", iso_date: "2026-07-13T12:30:00-04:00" },
    { sha: sha("a"), subject: "Add tps62130", author: "Sadad", iso_date: "2026-07-13T12:00:00-04:00" },
  ],
  count: 2,
};

const NO_ASSETS = { symbol: false, footprint: false, model: false, datasheet: false };

function wrap(ui: ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <ThemeProvider>{ui}</ThemeProvider>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  mockApi.previewSvg.mockResolvedValue(new Blob(["<svg/>"], { type: "image/svg+xml" }));
});

describe("PartTimeline", () => {
  it("lists the commits newest first with author and short sha", async () => {
    mockApi.partHistory.mockResolvedValue(HISTORY);
    wrap(<PartTimeline partId="tps62130" />);

    const rows = await screen.findAllByRole("button", { expanded: false });
    expect(rows[0]).toHaveTextContent("Edit tps62130: manufacturer");
    expect(rows[1]).toHaveTextContent("Add tps62130");
    // the 7-char short sha of the newest commit
    expect(rows[0]).toHaveTextContent("bbbbbbb");
  });

  it("shows an honest empty state for a part with no commits", async () => {
    mockApi.partHistory.mockResolvedValue({ commits: [], count: 0 });
    wrap(<PartTimeline partId="ghost" />);
    expect(await screen.findByText(/No history yet/i)).toBeInTheDocument();
  });

  it("surfaces a history load error honestly", async () => {
    mockApi.partHistory.mockRejectedValue(new Error("boom"));
    wrap(<PartTimeline partId="tps62130" />);
    expect(await screen.findByText(/Could not load this part's history/i)).toBeInTheDocument();
  });

  it("selecting a commit shows its field diff against the previous part version", async () => {
    mockApi.partHistory.mockResolvedValue(HISTORY);
    mockApi.partDiff.mockResolvedValue({
      a: sha("a"),
      b: sha("b"),
      fields: [
        { key: "manufacturer", before: "TI", after: "NewCo", status: "changed" },
      ],
      assets: NO_ASSETS,
    });
    wrap(<PartTimeline partId="tps62130" />);

    await userEvent.click(await screen.findByText("Edit tps62130: manufacturer"));

    expect(await screen.findByText("Changed")).toBeInTheDocument();
    expect(screen.getByText("manufacturer")).toBeInTheDocument();
    expect(screen.getByText("TI")).toBeInTheDocument();
    expect(screen.getByText("NewCo")).toBeInTheDocument();
    // the newest commit diffs against the next-older commit in the part's history
    expect(mockApi.partDiff).toHaveBeenCalledWith("tps62130", sha("a"), sha("b"));
  });

  it("labels the earliest commit as a creation and diffs against an empty side", async () => {
    mockApi.partHistory.mockResolvedValue(HISTORY);
    mockApi.partDiff.mockResolvedValue({
      a: "",
      b: sha("a"),
      fields: [{ key: "mpn", before: null, after: "TPS62130", status: "added" }],
      assets: NO_ASSETS,
    });
    wrap(<PartTimeline partId="tps62130" />);

    await userEvent.click(await screen.findByText("Add tps62130"));

    expect(await screen.findByText(/Part created/i)).toBeInTheDocument();
    expect(mockApi.partDiff).toHaveBeenCalledWith("tps62130", "", sha("a"));
    // the earliest commit has nothing older to visually compare against
    expect(screen.queryByRole("button", { name: "View Visual Diff" })).toBeNull();
  });

  it("offers a visual diff when the commit moved the symbol, and opens the overlay", async () => {
    mockApi.partHistory.mockResolvedValue(HISTORY);
    mockApi.partDiff.mockResolvedValue({
      a: sha("a"),
      b: sha("b"),
      fields: [{ key: "manufacturer", before: "TI", after: "NewCo", status: "changed" }],
      assets: { ...NO_ASSETS, symbol: true },
    });
    wrap(<PartTimeline partId="tps62130" />);

    await userEvent.click(await screen.findByText("Edit tps62130: manufacturer"));
    const visual = await screen.findByRole("button", { name: "View Visual Diff" });
    await userEvent.click(visual);

    // the overlay renders both the old and the new symbol geometry
    expect(await screen.findByAltText("Symbol Before")).toBeInTheDocument();
    expect(screen.getByAltText("Symbol After")).toBeInTheDocument();
    // fetched at the two revisions (older = a, newer = b)
    await waitFor(() => {
      expect(mockApi.previewSvg).toHaveBeenCalledWith("symbol", "tps62130", sha("a"));
      expect(mockApi.previewSvg).toHaveBeenCalledWith("symbol", "tps62130", sha("b"));
    });
  });

  it("does not offer a visual diff when only metadata changed", async () => {
    mockApi.partHistory.mockResolvedValue(HISTORY);
    mockApi.partDiff.mockResolvedValue({
      a: sha("a"),
      b: sha("b"),
      fields: [{ key: "description", before: "old", after: "new", status: "changed" }],
      assets: NO_ASSETS,
    });
    wrap(<PartTimeline partId="tps62130" />);

    await userEvent.click(await screen.findByText("Edit tps62130: manufacturer"));
    await screen.findByText("Changed");
    expect(screen.queryByRole("button", { name: "View Visual Diff" })).toBeNull();
  });
});
