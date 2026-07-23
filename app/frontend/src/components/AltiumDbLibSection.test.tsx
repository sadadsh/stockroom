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
    api: {
      altiumStatus: vi.fn(),
      altiumRegenerate: vi.fn(),
      altiumAttach: vi.fn(),
      altiumOdbcStatus: vi.fn(),
    },
  };
});

const mockApi = vi.mocked(api);

const ODBC_URL = "http://www.ch-werner.de/sqliteodbc/sqliteodbc_w64.exe";
const odbc = (installed: boolean | null) => ({
  installed,
  driver: "SQLite3 ODBC Driver",
  download_url: ODBC_URL,
});

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
  beforeEach(() => {
    // default the machine-level ODBC probe so the existing status tests don't have to; each ODBC
    // test overrides it. null = the honest off-Windows answer.
    mockApi.altiumOdbcStatus.mockResolvedValue(odbc(null));
  });

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

  it("reports the ODBC driver as Not Installed and offers the official installer when it is absent", async () => {
    mockApi.altiumStatus.mockResolvedValue(STATUS);
    mockApi.altiumOdbcStatus.mockResolvedValue(odbc(false));
    renderSection();

    expect(await screen.findByText("Not Installed")).toBeInTheDocument();
    const link = screen.getByRole("link", { name: /Download Driver/ });
    expect(link).toHaveAttribute("href", ODBC_URL);
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("rel", expect.stringContaining("noreferrer"));
  });

  it("reports the ODBC driver as Installed and hides the download when it is present", async () => {
    mockApi.altiumStatus.mockResolvedValue(STATUS);
    mockApi.altiumOdbcStatus.mockResolvedValue(odbc(true));
    renderSection();

    expect(await screen.findByText("Installed")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Download Driver/ })).toBeNull();
  });

  it("stays honest off Windows, where the driver cannot be verified, and offers no download", async () => {
    mockApi.altiumStatus.mockResolvedValue(STATUS);
    mockApi.altiumOdbcStatus.mockResolvedValue(odbc(null));
    renderSection();

    expect(await screen.findByText(/cannot be verified/i)).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Download Driver/ })).toBeNull();
  });
});
