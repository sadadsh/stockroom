import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
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
      altiumSetup: vi.fn(),
      altiumOdbcStatus: vi.fn(),
      altiumModelsPending: vi.fn(),
      altiumEmbedCapability: vi.fn(),
      altiumEmbedModels: vi.fn(),
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
  datasource_present: true,
  rows: [
    {
      id: "a",
      display_name: "BQ24074 Charger",
      category: "ICs",
      mpn: "BQ24074RGTT",
      value: "BQ24074RGTT",
      symbol: "BQ24074RGTT",
      footprint: "VQFN-16",
      ready: true,
    },
    {
      id: "b",
      display_name: "Mystery",
      category: "ICs",
      mpn: "",
      value: "",
      symbol: "",
      footprint: "",
      ready: false,
    },
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
    // Default the bulk-embed probes so the existing tests do not have to: nothing pending, which
    // is the state where the action is deliberately absent.
    mockApi.altiumModelsPending.mockResolvedValue({ pending: [], count: 0 });
    mockApi.altiumEmbedCapability.mockResolvedValue({
      installed: true,
      binary: "C:/Altium/X2.EXE",
      requires_tool_installed: true,
      reason: "",
      busy: "",
      available: true,
    });
  });

  it("shows the place-ready ratio, active library, and install path", async () => {
    mockApi.altiumStatus.mockResolvedValue(STATUS);
    renderSection();

    expect(await screen.findByText("3")).toBeInTheDocument();
    expect(screen.getByText("88")).toBeInTheDocument();
    expect(screen.getByText(/parts prepared to place/)).toBeInTheDocument();
    expect(screen.getByText("Main")).toBeInTheDocument();
    expect(screen.getByTitle(STATUS.dblib)).toBeInTheDocument();
    expect(
      screen.getByText(/opening Stockroom never launches Altium/i),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Rebuild DbLib/ })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Set Up In Altium/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /View Catalog/ })).toBeInTheDocument();
  });

  it("keeps Catalog Build and 3D embedding out of Settings", async () => {
    mockApi.altiumStatus.mockResolvedValue({ ...STATUS, datasource_present: false });
    mockApi.altiumModelsPending.mockResolvedValue({ pending: ["a"], count: 1 });
    renderSection();

    await screen.findByText(/parts prepared to place/);
    expect(screen.queryByRole("button", { name: /Rebuild DbLib/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Embed 3D Models/ })).not.toBeInTheDocument();
    expect(screen.getByText(/Assets.*Build Now/i)).toBeInTheDocument();
  });

  it("opens the library viewer modal", async () => {
    mockApi.altiumStatus.mockResolvedValue(STATUS);
    renderSection();

    await screen.findByText("3");
    await userEvent.click(screen.getByRole("button", { name: /View Catalog/ }));

    expect(
      await screen.findByRole("dialog", { name: "Altium Database Catalog" }),
    ).toBeInTheDocument();
  });

  it("makes native Altium setup an explicit action", async () => {
    mockApi.altiumStatus.mockResolvedValue(STATUS);
    renderSection();

    await screen.findByText("3");
    await userEvent.click(screen.getByRole("button", { name: /Setup Guide/ }));

    expect(
      await screen.findByText(/without opening Altium until the setup action is chosen/i),
    ).toBeInTheDocument();
    expect(screen.getByText("Explicit Install And Verification")).toBeInTheDocument();
    expect(screen.getByText(/Opening Stockroom, switching catalogs, and rebuilding the DbLib never launch Altium/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Set Up In Altium/ })).toBeInTheDocument();
    expect(screen.queryByText(/right-click the library/i)).not.toBeInTheDocument();
  });

  it("launches setup only after the explicit button is pressed", async () => {
    mockApi.altiumStatus.mockResolvedValue(STATUS);
    mockApi.altiumSetup.mockResolvedValue({
      status: "verified",
      detail: "Installed and verified from the explicit action.",
      dblib: STATUS.dblib,
      component_key: "TPS62130",
      symbol_library: "TPS62130.SchLib",
      footprint_library: "TPS62130.PcbLib",
      receipt_path: "receipt.json",
    });
    renderSection();

    await screen.findByText("3");
    expect(mockApi.altiumSetup).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: /Set Up In Altium/ }));

    await waitFor(() => expect(mockApi.altiumSetup).toHaveBeenCalledTimes(1));
    expect(await screen.findByText(/Installed and verified from the explicit action/)).toBeInTheDocument();
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

    expect(await screen.findByText(/cannot be validated/i)).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Download Driver/ })).toBeNull();
  });

  it("opens the on-demand setup guide with the live diagnostic path", async () => {
    mockApi.altiumStatus.mockResolvedValue(STATUS);
    mockApi.altiumOdbcStatus.mockResolvedValue(odbc(true));
    renderSection();

    await screen.findByText("3");
    await userEvent.click(screen.getByRole("button", { name: /Setup Guide/ }));

    const dialog = await screen.findByRole("dialog", { name: "Altium Setup" });
    // the four steps, with the real mechanics named
    expect(dialog).toHaveTextContent(/Explicit Install And Verification/);
    expect(dialog).toHaveTextContent(/never launch Altium/i);
    expect(dialog).toHaveTextContent(/shared STEP remains linked in KiCad/i);
    expect(dialog).not.toHaveTextContent(/Installed tab/);
    // the LIVE library path is in the guide (not a placeholder)
    expect(dialog).toHaveTextContent(STATUS.dblib);
    // driver installed: step 1 reports done, no download link inside the guide
    expect(dialog).toHaveTextContent(/Installed on this machine/);
    expect(screen.queryByRole("link", { name: /Download Driver/ })).toBeNull();
  });

  it("the setup guide surfaces the missing driver with a working download link", async () => {
    mockApi.altiumStatus.mockResolvedValue(STATUS);
    mockApi.altiumOdbcStatus.mockResolvedValue(odbc(false));
    renderSection();

    await screen.findByText("3");
    await userEvent.click(screen.getByRole("button", { name: /Setup Guide/ }));

    const dialog = await screen.findByRole("dialog", { name: "Altium Setup" });
    expect(dialog).toHaveTextContent(/Not installed/);
    const links = within(dialog).getAllByRole("link", { name: /Download Driver/ });
    expect(links[0]).toHaveAttribute("href", ODBC_URL);
    expect(links[0]).toHaveAttribute("target", "_blank");
  });

  it("the setup guide closes on Escape", async () => {
    mockApi.altiumStatus.mockResolvedValue(STATUS);
    mockApi.altiumOdbcStatus.mockResolvedValue(odbc(true));
    renderSection();

    await screen.findByText("3");
    await userEvent.click(screen.getByRole("button", { name: /Setup Guide/ }));
    await screen.findByRole("dialog", { name: "Altium Setup" });

    await userEvent.keyboard("{Escape}");
    expect(screen.queryByRole("dialog", { name: "Altium Setup" })).toBeNull();
  });

  it("says when the derived data source has not been built on this machine yet", async () => {
    // It is no longer shared through git (Batch 2 item 3), so a fresh clone legitimately has
    // none. Silence here means Altium fails later with an ODBC error against a file nobody
    // mentioned, which reads as a broken library rather than an unbuilt one.
    mockApi.altiumStatus.mockResolvedValue({ ...STATUS, datasource_present: false });
    renderSection();
    expect(await screen.findByTestId("altium-datasource-missing")).toBeInTheDocument();
  });

  it("says nothing about the data source once it is built", async () => {
    mockApi.altiumStatus.mockResolvedValue(STATUS);
    renderSection();
    await screen.findByText(/parts prepared to place/);
    expect(screen.queryByTestId("altium-datasource-missing")).toBeNull();
  });
});
