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
    // the 7-char short sha, AND the full 40-char sha is NOT rendered (shortSha truncates)
    expect(rows[0]).toHaveTextContent("bbbbbbb");
    expect(rows[0]).not.toHaveTextContent(sha("b"));
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

  it("keeps the selection on the same commit when a newer commit lands (sha-keyed, not index)", async () => {
    const C1 = { sha: sha("a"), subject: "Add opamp", author: "Sadad", iso_date: "2026-07-13T12:00:00-04:00" };
    const C2 = { sha: sha("b"), subject: "Edit opamp: mfr", author: "Sadad", iso_date: "2026-07-13T12:30:00-04:00" };
    const C3 = { sha: sha("c"), subject: "Edit opamp: desc", author: "Sadad", iso_date: "2026-07-13T13:00:00-04:00" };
    mockApi.partHistory.mockResolvedValue({ commits: [C2, C1], count: 2 });
    // the diff shape depends on the args: only the earliest (a === "") reads as created
    mockApi.partDiff.mockImplementation((_id, a, b) =>
      Promise.resolve(
        a === ""
          ? { a, b, fields: [{ key: "mpn", before: null, after: "LM358", status: "added" }], assets: NO_ASSETS }
          : { a, b, fields: [{ key: "description", before: "o", after: "n", status: "changed" }], assets: NO_ASSETS },
      ),
    );
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={qc}>
        <ThemeProvider>
          <PartTimeline partId="opamp" />
        </ThemeProvider>
      </QueryClientProvider>,
    );

    // select the earliest commit (index 1 of the 2-commit list)
    await userEvent.click(await screen.findByText("Add opamp"));
    expect(await screen.findByText(/Part created/i)).toBeInTheDocument();

    // a newer commit lands at the top; the history refetches and everything shifts down
    mockApi.partHistory.mockResolvedValue({ commits: [C3, C2, C1], count: 3 });
    await qc.invalidateQueries({ queryKey: ["part-history", "opamp"] });
    expect(await screen.findByText("Edit opamp: desc")).toBeInTheDocument(); // refetched

    // the ORIGINALLY selected commit (C1) is still the one shown: it is still the
    // earliest, so "Part created" persists. An index-keyed selection would now point at
    // C2 (no longer the earliest) and this would flip to a "Changed" field diff.
    expect(screen.getByText(/Part created/i)).toBeInTheDocument();
    expect(screen.queryByText("Changed")).toBeNull();
  });

  it("labels the overlay images by the diffed kind (footprint, not a hardcoded 'Symbol')", async () => {
    mockApi.partHistory.mockResolvedValue(HISTORY);
    mockApi.partDiff.mockResolvedValue({
      a: sha("a"),
      b: sha("b"),
      fields: [{ key: "footprint.name", before: "SOIC-8", after: "SOIC-8-N", status: "changed" }],
      assets: { ...NO_ASSETS, footprint: true },
    });
    wrap(<PartTimeline partId="tps62130" />);

    await userEvent.click(await screen.findByText("Edit tps62130: manufacturer"));
    await userEvent.click(await screen.findByRole("button", { name: "View Visual Diff" }));

    // the overlay names the FOOTPRINT geometry, not "Symbol"
    expect(await screen.findByAltText("Footprint Before")).toBeInTheDocument();
    expect(screen.getByAltText("Footprint After")).toBeInTheDocument();
    expect(screen.queryByAltText("Symbol Before")).toBeNull();
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
