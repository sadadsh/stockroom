import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { api } from "../api/client";
import type { ProfilesResponse, SettingsInfo, WiringReport } from "../api/types";
import { ToastProvider } from "../lib/toast";
import { ThemeProvider } from "../lib/theme";
import { SettingsPage } from "./SettingsPage";

vi.mock("../api/client", async (importActual) => {
  const actual = await importActual<typeof import("../api/client")>();
  return {
    ...actual,
    api: {
      getSettings: vi.fn(),
      updateSettings: vi.fn(),
      listProfiles: vi.fn(),
      createProfile: vi.fn(),
      activateProfile: vi.fn(),
      deleteProfile: vi.fn(),
      getSyncStatus: vi.fn(),
      doSync: vi.fn(),
      checkUpdate: vi.fn(),
      applyUpdate: vi.fn(),
      getSystemInfo: vi.fn(),
      scanDoctor: vi.fn(),
      repairLibrary: vi.fn(),
      wireKicad: vi.fn(),
      openJobStream: vi.fn(),
      altiumStatus: vi.fn(),
      altiumRegenerate: vi.fn(),
      altiumAttach: vi.fn(),
    },
  };
});

const mockApi = vi.mocked(api);

const BASE_SETTINGS: SettingsInfo = {
  mouser_api_key_set: false,
  mouser_api_key_hint: "",
  github_token_set: false,
  github_token_hint: "",
  digikey_client_id: "",
  digikey_client_secret_set: false,
  digikey_client_secret_hint: "",
  digikey_username: "",
  digikey_password_set: false,
  digikey_password_hint: "",
  ul_username: "",
  ul_password_set: false,
  ul_password_hint: "",
  snapeda_username: "",
  snapeda_password_set: false,
  snapeda_password_hint: "",
  samacsys_username: "",
  samacsys_password_set: false,
  samacsys_password_hint: "",
  kicad_config_override: "",
  kicad_cli_override: "",
  kicad_config_dir: "/home/x/.config/kicad/10.0",
  kicad_cli_path: "/usr/bin/kicad-cli",
  kicad_cli_available: true,
  kicad_wired: true,
};

function renderPage() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={qc}>
      <ThemeProvider>
        <ToastProvider>
          <SettingsPage />
        </ToastProvider>
      </ThemeProvider>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  localStorage.clear();
  delete document.documentElement.dataset.theme;
  mockApi.getSettings.mockResolvedValue({ ...BASE_SETTINGS });
  mockApi.listProfiles.mockResolvedValue({
    profiles: ["Main", "Archive"],
    active: "Main",
  });
  mockApi.getSyncStatus.mockResolvedValue({
    has_remote: true,
    current_branch: "main",
    ahead: 0,
    behind: 2,
  });
  mockApi.checkUpdate.mockResolvedValue({ update_available: false, behind: 0 });
  mockApi.getSystemInfo.mockResolvedValue({
    active_profile: "Main",
    part_count: 8,
    kicad_config_dir: "/home/x/.config/kicad",
    kicad_running: false,
    kicad_cli_available: true,
    kicad_cli_path: "/usr/bin/kicad-cli",
  });
  mockApi.scanDoctor.mockResolvedValue({ fixable: [], manual: [], uncommitted: [], healthy: true });
  mockApi.activateProfile.mockResolvedValue({ active: "Archive", part_count: 0 });
  mockApi.createProfile.mockResolvedValue({
    profiles: ["Main", "Archive", "Scratch"],
    active: "Main",
  });
  mockApi.deleteProfile.mockResolvedValue(undefined);
  mockApi.updateSettings.mockResolvedValue({
    ...BASE_SETTINGS,
    mouser_api_key_set: true,
    mouser_api_key_hint: "Y123",
    github_token_set: true,
    github_token_hint: "1234",
  });
  mockApi.doSync.mockResolvedValue({
    state: "synced",
    pulled: true,
    pushed: false,
    detail: "",
  });
  mockApi.applyUpdate.mockResolvedValue({
    state: "updated",
    updated: true,
    detail: "",
    restart_requested: true,
  });
});

function profileRow(name: string): HTMLElement {
  const label = screen.getByText(name);
  return label.closest("[data-profile-row]") as HTMLElement;
}

describe("SettingsPage — profiles", () => {
  it("lists profiles and marks the active one", async () => {
    renderPage();
    expect(await screen.findByText("Archive")).toBeInTheDocument();
    // the active profile is labelled and has no activate control
    expect(within(profileRow("Main")).getByText(/active/i)).toBeInTheDocument();
    expect(
      within(profileRow("Main")).queryByRole("button", { name: /^activate$/i }),
    ).toBeNull();
    // a non-active profile can be activated
    expect(
      within(profileRow("Archive")).getByRole("button", { name: /^activate$/i }),
    ).toBeInTheDocument();
  });

  it("activates a non-active profile", async () => {
    renderPage();
    await screen.findByText("Archive");
    await userEvent.click(
      within(profileRow("Archive")).getByRole("button", { name: /^activate$/i }),
    );
    expect(mockApi.activateProfile).toHaveBeenCalledWith("Archive");
  });

  it("creates a profile with the archive flag", async () => {
    renderPage();
    await screen.findByText("Archive");
    await userEvent.type(
      screen.getByPlaceholderText(/new profile/i),
      "Scratch",
    );
    await userEvent.click(screen.getByLabelText(/archive profile/i));
    await userEvent.click(screen.getByRole("button", { name: /^create$/i }));
    expect(mockApi.createProfile).toHaveBeenCalledWith("Scratch", true);
  });

  it("does not double-create on a rapid double-Enter while the first is in flight", async () => {
    let resolve!: (v: ProfilesResponse) => void;
    mockApi.createProfile.mockReturnValue(
      new Promise<ProfilesResponse>((r) => {
        resolve = r;
      }),
    );
    renderPage();
    await screen.findByText("Archive");
    const input = screen.getByPlaceholderText(/new profile/i);
    await userEvent.type(input, "Scratch");
    // two Enter presses before the first create resolves; the second must be
    // dropped by the pending guard, not fire a duplicate create.
    await userEvent.type(input, "{Enter}{Enter}");
    expect(mockApi.createProfile).toHaveBeenCalledTimes(1);
    resolve({ profiles: ["Main", "Archive", "Scratch"], active: "Main" });
  });

  it("deletes a non-active profile only after an in-window confirm", async () => {
    renderPage();
    await screen.findByText("Archive");
    await userEvent.click(
      within(profileRow("Archive")).getByRole("button", { name: /^delete$/i }),
    );
    // nothing deleted until the confirm dialog is accepted
    expect(mockApi.deleteProfile).not.toHaveBeenCalled();
    const dialog = screen.getByRole("dialog");
    await userEvent.click(within(dialog).getByRole("button", { name: /^delete$/i }));
    expect(mockApi.deleteProfile).toHaveBeenCalledWith("Archive");
  });
});

describe("SettingsPage — appearance", () => {
  it("switches the theme", async () => {
    renderPage();
    await screen.findByText("Archive");
    await userEvent.click(screen.getByRole("button", { name: /^light$/i }));
    expect(document.documentElement.dataset.theme).toBe("light");
  });
});

describe("SettingsPage — distributor key", () => {
  it("shows the key as not set and saves a typed key without ever exposing it", async () => {
    renderPage();
    await screen.findByText(/not set/i);
    const input = screen.getByLabelText(/mouser api key/i) as HTMLInputElement;
    expect(input.type).toBe("password");
    await userEvent.type(input, "MOUSERKEY123");
    await userEvent.click(screen.getByRole("button", { name: /save key/i }));
    expect(mockApi.updateSettings).toHaveBeenCalledWith({
      mouser_api_key: "MOUSERKEY123",
    });
  });

  it("does not double-save on a rapid double-Enter while the first is in flight", async () => {
    let resolve!: (v: SettingsInfo) => void;
    mockApi.updateSettings.mockReturnValue(
      new Promise<SettingsInfo>((r) => {
        resolve = r;
      }),
    );
    renderPage();
    await screen.findByText(/not set/i);
    const input = screen.getByLabelText(/mouser api key/i);
    await userEvent.type(input, "MOUSERKEY123");
    await userEvent.type(input, "{Enter}{Enter}");
    expect(mockApi.updateSettings).toHaveBeenCalledTimes(1);
    resolve({ ...BASE_SETTINGS, mouser_api_key_set: true, mouser_api_key_hint: "Y123" });
  });

  it("shows the hint when a key is set and can clear it", async () => {
    mockApi.getSettings.mockResolvedValue({
      ...BASE_SETTINGS,
      mouser_api_key_set: true,
      mouser_api_key_hint: "1234",
    });
    renderPage();
    expect(await screen.findByText(/1234/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /clear/i }));
    expect(mockApi.updateSettings).toHaveBeenCalledWith({ mouser_api_key: "" });
  });
});

describe("SettingsPage — sync + kicad + update", () => {
  it("renders sync status and runs a sync", async () => {
    renderPage();
    expect(await screen.findByText(/main/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /sync now/i }));
    expect(mockApi.doSync).toHaveBeenCalled();
  });

  it("surfaces a diverged sync as a failure, never a green up-to-date success", async () => {
    mockApi.doSync.mockResolvedValue({
      state: "diverged",
      pulled: false,
      pushed: false,
      detail: "! [rejected] main -> main (non-fast-forward)",
    });
    renderPage();
    await screen.findByText("Archive");
    await userEvent.click(screen.getByRole("button", { name: /sync now/i }));
    expect(await screen.findByText(/diverged from the remote/i)).toBeInTheDocument();
    expect(screen.queryByText(/already up to date/i)).toBeNull();
  });

  it("surfaces an auth-denied sync as a credential problem, not a divergence", async () => {
    mockApi.doSync.mockResolvedValue({
      state: "denied",
      pulled: false,
      pushed: false,
      detail: "remote: Repository not found.",
    });
    renderPage();
    await screen.findByText("Archive");
    await userEvent.click(screen.getByRole("button", { name: /sync now/i }));
    expect(await screen.findByText(/refused this token/i)).toBeInTheDocument();
    expect(screen.queryByText(/diverged/i)).toBeNull();
  });

  it("surfaces a no-remote sync honestly, not as up to date", async () => {
    mockApi.doSync.mockResolvedValue({
      state: "no_remote",
      pulled: false,
      pushed: false,
      detail: "no remote configured",
    });
    renderPage();
    await screen.findByText("Archive");
    await userEvent.click(screen.getByRole("button", { name: /sync now/i }));
    expect(await screen.findByText(/no remote is configured/i)).toBeInTheDocument();
    expect(screen.queryByText(/already up to date/i)).toBeNull();
  });

  it("renders the kicad status", async () => {
    renderPage();
    expect(await screen.findByText("/usr/bin/kicad-cli")).toBeInTheDocument();
    expect(screen.getByText("/home/x/.config/kicad")).toBeInTheDocument();
  });

  it("shows the wiring status when SR_LIB points at the active library", async () => {
    renderPage();
    expect(
      await screen.findByText(/wired to the active profile/i),
    ).toBeInTheDocument();
  });

  it("shows an honest not-wired status", async () => {
    mockApi.getSettings.mockResolvedValue({ ...BASE_SETTINGS, kicad_wired: false });
    renderPage();
    expect(await screen.findByText(/not wired yet/i)).toBeInTheDocument();
  });

  it("prefills the kicad overrides and saves both together", async () => {
    mockApi.getSettings.mockResolvedValue({
      ...BASE_SETTINGS,
      kicad_cli_override: "/opt/kicad/kicad-cli",
    });
    renderPage();
    // the prefill arrives with the settings query, so wait for the value itself
    await screen.findByDisplayValue("/opt/kicad/kicad-cli");
    const cfg = screen.getByLabelText(/config directory override/i);
    await userEvent.type(cfg, "/custom/kicad/10.0");
    await userEvent.click(screen.getByRole("button", { name: /save overrides/i }));
    expect(mockApi.updateSettings).toHaveBeenCalledWith({
      kicad_config_override: "/custom/kicad/10.0",
      kicad_cli_override: "/opt/kicad/kicad-cli",
    });
  });

  it("disables saving overrides until something changed", async () => {
    renderPage();
    await screen.findByLabelText(/config directory override/i);
    expect(screen.getByRole("button", { name: /save overrides/i })).toBeDisabled();
  });

  it("applies an available update", async () => {
    mockApi.checkUpdate.mockResolvedValue({ update_available: true, behind: 3 });
    renderPage();
    const apply = await screen.findByRole("button", { name: /apply update/i });
    await userEvent.click(apply);
    expect(mockApi.applyUpdate).toHaveBeenCalled();
  });

  it("does not offer to apply when up to date", async () => {
    renderPage();
    expect(await screen.findByText(/up to date/i)).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /apply update/i }),
    ).toBeNull();
  });
});

  it("connects a GitHub token so part changes auto-push, and never asks for it raw", async () => {
    mockApi.getSettings.mockResolvedValue({ ...BASE_SETTINGS });
    renderPage();
    await screen.findByText("GitHub");
    const input = screen.getByLabelText("GitHub Personal Access Token");
    expect((input as HTMLInputElement).type).toBe("password"); // the token is never shown
    await userEvent.type(input, "ghp_TESTTOKEN");
    await userEvent.click(screen.getByRole("button", { name: "Connect" }));
    expect(mockApi.updateSettings).toHaveBeenCalledWith({ github_token: "ghp_TESTTOKEN" });
  });

// KiCad wiring moved here from the Doctor page (D3): the manual re-wire button
// now lives in the Settings KiCad section.
const WIRING: WiringReport = {
  sr_lib_value: "/lib",
  categories_registered: ["ICs", "Passives"],
  symbol_rows_added: 2,
  footprint_rows_added: 2,
  libs_created: [],
  kicad_running: true,
  restart_needed: true,
};

function sseStream(frames: string[]): ReadableStream<Uint8Array> {
  const body = frames.map((f) => f + "\r\n\r\n").join("");
  const bytes = new TextEncoder().encode(body);
  return new ReadableStream({
    start(controller) {
      controller.enqueue(bytes);
      controller.close();
    },
  });
}

describe("SettingsPage — KiCad wiring", () => {
  it("re-wires KiCad through the job and reports when a restart is needed", async () => {
    mockApi.wireKicad.mockResolvedValue({ job_id: "job-1" });
    mockApi.openJobStream.mockResolvedValue(
      sseStream([
        `event: result\r\ndata: ${JSON.stringify({ result: WIRING })}`,
        `event: done\r\ndata: {}`,
      ]),
    );
    renderPage();
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: "Wire KiCad" }));

    await waitFor(() => expect(mockApi.wireKicad).toHaveBeenCalledTimes(1));
    expect(await screen.findByText(/Registered 2 categories/)).toBeInTheDocument();
    expect(screen.getByText(/Restart KiCad to load the updated tables\./)).toBeInTheDocument();
  });
});

describe("SettingsPage - capture credentials", () => {
  it("saves the Ultra Librarian username and password", async () => {
    const user = userEvent.setup();
    mockApi.updateSettings.mockResolvedValue({ ...BASE_SETTINGS });
    renderPage();
    await screen.findByText("Capture Credentials");
    await user.type(screen.getByLabelText("Ultra Librarian Username"), "me@x.com");
    await user.type(screen.getByLabelText("Ultra Librarian Password"), "secret");
    await user.click(
      screen.getByRole("button", { name: "Save Ultra Librarian Login" }),
    );
    expect(mockApi.updateSettings).toHaveBeenCalledWith(
      expect.objectContaining({ ul_username: "me@x.com", ul_password: "secret" }),
    );
  });

  it("renders the password input as type password", async () => {
    renderPage();
    await screen.findByText("Capture Credentials");
    expect(screen.getByLabelText("Ultra Librarian Password")).toHaveAttribute(
      "type",
      "password",
    );
  });

  it("saves the SnapEDA username and password", async () => {
    const user = userEvent.setup();
    mockApi.updateSettings.mockResolvedValue({ ...BASE_SETTINGS });
    renderPage();
    await screen.findByText("Capture Credentials");
    await user.type(screen.getByLabelText("SnapEDA Username"), "sn@x.com");
    await user.type(screen.getByLabelText("SnapEDA Password"), "snpw");
    await user.click(screen.getByRole("button", { name: "Save SnapEDA Login" }));
    expect(mockApi.updateSettings).toHaveBeenCalledWith(
      expect.objectContaining({ snapeda_username: "sn@x.com", snapeda_password: "snpw" }),
    );
  });

  it("saves the SamacSys username and password", async () => {
    const user = userEvent.setup();
    mockApi.updateSettings.mockResolvedValue({ ...BASE_SETTINGS });
    renderPage();
    await screen.findByText("Capture Credentials");
    await user.type(screen.getByLabelText("SamacSys Username"), "sam@x.com");
    await user.type(screen.getByLabelText("SamacSys Password"), "sampw");
    await user.click(screen.getByRole("button", { name: "Save SamacSys Login" }));
    expect(mockApi.updateSettings).toHaveBeenCalledWith(
      expect.objectContaining({ samacsys_username: "sam@x.com", samacsys_password: "sampw" }),
    );
  });

  it("saves the DigiKey account login and masks the password input", async () => {
    const user = userEvent.setup();
    mockApi.updateSettings.mockResolvedValue({ ...BASE_SETTINGS });
    renderPage();
    await screen.findByText("Capture Credentials");
    const pass = screen.getByLabelText("DigiKey Account Password");
    expect(pass).toHaveAttribute("type", "password");
    await user.type(screen.getByLabelText("DigiKey Account Username"), "dk@x.com");
    await user.type(pass, "acctpw");
    await user.click(
      screen.getByRole("button", { name: "Save DigiKey Account Login" }),
    );
    expect(mockApi.updateSettings).toHaveBeenCalledWith(
      expect.objectContaining({ digikey_username: "dk@x.com", digikey_password: "acctpw" }),
    );
  });

  it("saves the DigiKey API creds and masks the client secret input", async () => {
    const user = userEvent.setup();
    mockApi.updateSettings.mockResolvedValue({ ...BASE_SETTINGS });
    renderPage();
    await screen.findByText("Capture Credentials");
    const secret = screen.getByLabelText("DigiKey API Client Secret");
    expect(secret).toHaveAttribute("type", "password");
    await user.type(screen.getByLabelText("DigiKey API Client ID"), "CLIENTID");
    await user.type(secret, "APISECRET");
    await user.click(
      screen.getByRole("button", { name: "Save DigiKey API Creds" }),
    );
    expect(mockApi.updateSettings).toHaveBeenCalledWith(
      expect.objectContaining({
        digikey_client_id: "CLIENTID",
        digikey_client_secret: "APISECRET",
      }),
    );
  });
});
