import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { api } from "../api/client";
import type { AltiumStatus } from "../api/types";
import { ToastProvider } from "../lib/toast";
import { AltiumDbLibSection } from "./AltiumDbLibSection";

vi.mock("../api/client", async (importActual) => {
  const actual = await importActual<typeof import("../api/client")>();
  return {
    ...actual,
    api: { altiumStatus: vi.fn(), altiumRegenerate: vi.fn(), altiumAttach: vi.fn() },
  };
});

const mockApi = vi.mocked(api);

const STATUS: AltiumStatus = {
  profile: "Main",
  dblib: "/home/x/git/stockroom/libraries/Main/altium/Stockroom.DbLib",
  dblib_dir: "/home/x/git/stockroom/libraries/Main/altium/",
  ready: 3,
  total: 88,
  rows: [
    { id: "a", display_name: "BQ24074 Charger", category: "ICs", mpn: "BQ24074RGTT", value: "BQ24074RGTT", symbol: "BQ24074RGTT", footprint: "VQFN-16", ready: true },
    { id: "b", display_name: "Mystery", category: "ICs", mpn: "", value: "", symbol: "", footprint: "", ready: false },
  ],
};

function renderSection() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={qc}>
      <ToastProvider>
        <AltiumDbLibSection />
      </ToastProvider>
    </QueryClientProvider>,
  );
}

describe("AltiumDbLibSection", () => {
  it("shows the place-ready ratio, active profile, and install path", async () => {
    mockApi.altiumStatus.mockResolvedValue(STATUS);
    renderSection();

    expect(await screen.findByText("3")).toBeInTheDocument();
    expect(screen.getByText("88")).toBeInTheDocument();
    expect(screen.getByText(/parts ready to place/)).toBeInTheDocument();
    expect(screen.getByText("Main")).toBeInTheDocument();
    expect(screen.getByTitle(STATUS.dblib)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Regenerate DbLib/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /View Library/ })).toBeInTheDocument();
  });

  it("regenerates and reports how many parts landed", async () => {
    mockApi.altiumStatus.mockResolvedValue(STATUS);
    mockApi.altiumRegenerate.mockResolvedValue({ emitted: 3, skipped: ["b"], dblib: STATUS.dblib });
    renderSection();

    await screen.findByText("3");
    await userEvent.click(screen.getByRole("button", { name: /Regenerate DbLib/ }));

    await waitFor(() => expect(mockApi.altiumRegenerate).toHaveBeenCalledTimes(1));
    expect(await screen.findByText(/Regenerated the DbLib with 3 parts\./)).toBeInTheDocument();
  });

  it("opens the library viewer modal", async () => {
    mockApi.altiumStatus.mockResolvedValue(STATUS);
    renderSection();

    await screen.findByText("3");
    await userEvent.click(screen.getByRole("button", { name: /View Library/ }));

    expect(await screen.findByRole("dialog", { name: "Altium Database Library" })).toBeInTheDocument();
  });
});
