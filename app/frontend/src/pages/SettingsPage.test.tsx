import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { api } from "../api/client";
import type { ProfilesResponse, SettingsInfo, WiringReport } from "../api/types";
import { ToastProvider } from "../lib/toast";
import { ThemeProvider } from "../lib/theme";
import { DevModeProvider } from "../lib/devMode";
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
      altiumOdbcStatus: vi.fn(),
      loadDevCreds: vi.fn(),
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

// The dev-mode harness wraps the page in a DevModeProvider so a <Text> becomes a
// click-to-edit span carrying its data-copy-id. Ctrl/Shift+D is the only way in.
function renderDevPage() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={qc}>
      <ThemeProvider>
        <DevModeProvider>
          <ToastProvider>
            <SettingsPage />
          </ToastProvider>
        </DevModeProvider>
      </ThemeProvider>
    </QueryClientProvider>,
  );
}

function toggleDevMode() {
  fireEvent.keyDown(window, { key: "D", ctrlKey: true, shiftKey: true });
}

// The grouped IA hides sections behind a nav group + a collapsed disclosure; every
// test that exercises a section first walks there the way a person does.
const SECTION_NAV: Record<string, RegExp> = {
  "settings.appearance": /application/i,
  "settings.update": /application/i,
  "settings.profiles": /library/i,
  "settings.sync": /library/i,
  "settings.github": /library/i,
  "settings.health": /library/i,
  "settings.kicad": /kicad/i,
  "settings.altium": /altium/i,
  "settings.distributor": /sourcing/i,
  "settings.vendor-logins": /sourcing/i,
  "settings.rescan": /sourcing/i,
};

async function openSettings(devId: string) {
  const user = userEvent.setup();
  const nav = screen.getByRole("navigation", { name: /settings sections/i });
  await user.click(within(nav).getByRole("button", { name: SECTION_NAV[devId] }));
  const header = await screen.findByTestId(`${devId}.header`);
  if (header.getAttribute("aria-expanded") !== "true") await user.click(header);
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
  mockApi.altiumOdbcStatus.mockResolvedValue({ installed: true, driver: "SQLite3 ODBC Driver", download_url: "" });
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
  // the active profile's name ALSO shows in the Profiles disclosure summary, so
  // resolve through the row wrapper, not a unique-text lookup
  const row = screen
    .getAllByText(name)
    .map((el) => el.closest("[data-profile-row]"))
    .find(Boolean);
  return row as HTMLElement;
}

describe("SettingsPage — profiles", () => {
  it("lists profiles and marks the active one", async () => {
    renderPage();
    await openSettings("settings.profiles");
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
    await openSettings("settings.profiles");
    await screen.findByText("Archive");
    await userEvent.click(
      within(profileRow("Archive")).getByRole("button", { name: /^activate$/i }),
    );
    expect(mockApi.activateProfile).toHaveBeenCalledWith("Archive");
  });

  it("creates a profile with the archive flag", async () => {
    renderPage();
    await openSettings("settings.profiles");
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
    await openSettings("settings.profiles");
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
    await openSettings("settings.profiles");
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
    await openSettings("settings.appearance");
    await userEvent.click(screen.getByRole("button", { name: /^light$/i }));
    expect(document.documentElement.dataset.theme).toBe("light");
  });
});

describe("SettingsPage — distributor key", () => {
  it("shows the key as not set and saves a typed key without ever exposing it", async () => {
    renderPage();
    await openSettings("settings.distributor");
    await screen.findAllByText(/not set/i);
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
    await openSettings("settings.distributor");
    await screen.findAllByText(/not set/i);
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
    await openSettings("settings.distributor");
    expect(await screen.findByText(/1234/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /clear/i }));
    expect(mockApi.updateSettings).toHaveBeenCalledWith({ mouser_api_key: "" });
  });
});

describe("SettingsPage — sync + kicad + update", () => {
  it("renders sync status and runs a sync", async () => {
    renderPage();
    await openSettings("settings.sync");
    expect((await screen.findAllByText(/main/)).length).toBeGreaterThan(0);
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
    await openSettings("settings.sync");
    await screen.findByRole("button", { name: /sync now/i });
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
    await openSettings("settings.sync");
    await screen.findByRole("button", { name: /sync now/i });
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
    await openSettings("settings.sync");
    await screen.findByRole("button", { name: /sync now/i });
    await userEvent.click(screen.getByRole("button", { name: /sync now/i }));
    expect(await screen.findByText(/no remote is configured/i)).toBeInTheDocument();
    expect(screen.queryByText(/already up to date/i)).toBeNull();
  });

  it("renders the kicad status", async () => {
    renderPage();
    await openSettings("settings.kicad");
    expect(await screen.findByText("/usr/bin/kicad-cli")).toBeInTheDocument();
    expect(screen.getByText("/home/x/.config/kicad")).toBeInTheDocument();
  });

  it("shows the wiring status when SR_LIB points at the active library", async () => {
    renderPage();
    await openSettings("settings.kicad");
    expect(
      await screen.findByText(/wired to the active profile/i),
    ).toBeInTheDocument();
  });

  it("shows an honest not-wired status", async () => {
    mockApi.getSettings.mockResolvedValue({ ...BASE_SETTINGS, kicad_wired: false });
    renderPage();
    await openSettings("settings.kicad");
    expect(await screen.findByText(/not wired so far/i)).toBeInTheDocument();
  });

  it("prefills the kicad overrides and saves both together", async () => {
    mockApi.getSettings.mockResolvedValue({
      ...BASE_SETTINGS,
      kicad_cli_override: "/opt/kicad/kicad-cli",
    });
    renderPage();
    await openSettings("settings.kicad");
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
    await openSettings("settings.kicad");
    await screen.findByLabelText(/config directory override/i);
    expect(screen.getByRole("button", { name: /save overrides/i })).toBeDisabled();
  });

  it("applies an available update", async () => {
    mockApi.checkUpdate.mockResolvedValue({ update_available: true, behind: 3 });
    renderPage();
    await openSettings("settings.update");
    const apply = await screen.findByRole("button", { name: /apply update/i });
    await userEvent.click(apply);
    expect(mockApi.applyUpdate).toHaveBeenCalled();
  });

  it("does not offer to apply when up to date", async () => {
    renderPage();
    await openSettings("settings.update");
    expect((await screen.findAllByText(/up to date/i)).length).toBeGreaterThan(0);
    expect(
      screen.queryByRole("button", { name: /apply update/i }),
    ).toBeNull();
  });
});

  it("connects a GitHub token so part changes auto-push, and never asks for it raw", async () => {
    mockApi.getSettings.mockResolvedValue({ ...BASE_SETTINGS });
    renderPage();
    await openSettings("settings.github");
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
    await openSettings("settings.kicad");
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
    await openSettings("settings.vendor-logins");
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
    await openSettings("settings.vendor-logins");
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
    await openSettings("settings.vendor-logins");
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
    await openSettings("settings.vendor-logins");
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
    await openSettings("settings.vendor-logins");
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
    await openSettings("settings.vendor-logins");
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

describe("SettingsPage - copy adoption", () => {
  it("exposes settings.* copy ids on its labels once dev mode is on", async () => {
    const { container } = renderDevPage();
    // Walk to the Library group and open the sections whose labels we spot-check.
    await openSettings("settings.sync");
    await openSettings("settings.github");
    await screen.findByRole("button", { name: /^connect$/i });

    // Outside dev mode a <Text> is a bare string with no wrapper: no copy targets yet.
    expect(container.querySelector("[data-copy-id]")).toBeNull();

    toggleDevMode();

    // A representative spread: the page H1, a disclosure header title, a primary
    // action whose static caption is wrapped, and a button label.
    await waitFor(() =>
      expect(container.querySelector('[data-copy-id="settings.title"]')).not.toBeNull(),
    );
    expect(container.querySelector('[data-copy-id="settings.sync.title"]')).not.toBeNull();
    expect(container.querySelector('[data-copy-id="settings.sync.action"]')).not.toBeNull();
    expect(container.querySelector('[data-copy-id="settings.github.connect"]')).not.toBeNull();
  });

  it("keeps the visible labels and behaviour unchanged outside dev mode", async () => {
    renderPage();
    // The wrapped labels still render their default text verbatim (no wrapper leaks
    // into the accessible name) and the sync action still fires its mutation. The page
    // header is the shared PanelTitle strip (no page-level heading, same as the other panes).
    await openSettings("settings.sync");
    await openSettings("settings.github");
    expect(
      document.querySelector('[data-dev-id="settings.title"]')?.textContent,
    ).toBe("Settings");
    expect(screen.getByRole("button", { name: /^connect$/i })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /sync now/i }));
    expect(mockApi.doSync).toHaveBeenCalled();
  });

  it("still shows the delete ConfirmDialog title and confirm action through the copy layer", async () => {
    renderPage();
    await openSettings("settings.profiles");
    await screen.findByText("Archive");
    await userEvent.click(
      within(profileRow("Archive")).getByRole("button", { name: /^delete$/i }),
    );
    const dialog = screen.getByRole("dialog");
    // The call-site-wrapped props resolve to their defaults: the title and the
    // danger confirm label both read through useText.
    expect(within(dialog).getByText("Delete Profile")).toBeInTheDocument();
    expect(
      within(dialog).getByRole("button", { name: /^delete$/i }),
    ).toBeInTheDocument();
  });
});

describe("SettingsPage - grouped IA + Machine Setup band", () => {
  it("opens on the Application group with every section collapsed", async () => {
    renderPage();
    // the disclosure headers are visible, their content is not mounted
    const appearance = await screen.findByTestId("settings.appearance.header");
    expect(appearance).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByRole("button", { name: /^light$/i })).toBeNull();
    // other groups' sections are not on screen at all
    expect(screen.queryByTestId("settings.profiles.header")).toBeNull();
  });

  it("states the machine verdict from the live settings (all met reads Ready)", async () => {
    mockApi.getSettings.mockResolvedValue({
      ...BASE_SETTINGS,
      mouser_api_key_set: true,
      github_token_set: true,
    });
    renderPage();
    expect(await screen.findByText("This Machine Is Ready")).toBeInTheDocument();
  });

  it("counts the unmet setup steps and jumps to the owning section on click", async () => {
    // BASE has no distributor key and no GitHub token: 2 steps remain
    renderPage();
    expect(await screen.findByText("2 Setup Steps Remaining")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /add a distributor key/i }));
    // the jump lands on the Sourcing group with the Distributor section open
    const header = await screen.findByTestId("settings.distributor.header");
    expect(header).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByLabelText(/mouser api key/i)).toBeInTheDocument();
  });

  it("auto-opens a section in an attention state (KiCad not wired)", async () => {
    mockApi.getSettings.mockResolvedValue({ ...BASE_SETTINGS, kicad_wired: false });
    renderPage();
    // the nav carries an attention dot on KiCad, and walking there finds the
    // section already open
    const user = userEvent.setup();
    const nav = screen.getByRole("navigation", { name: /settings sections/i });
    await user.click(within(nav).getByRole("button", { name: /kicad/i }));
    const header = await screen.findByTestId("settings.kicad.header");
    await waitFor(() => expect(header).toHaveAttribute("aria-expanded", "true"));
  });

  it("shows the ODBC driver step only when the probe answers (never off-Windows null)", async () => {
    mockApi.altiumOdbcStatus.mockResolvedValue({ installed: null, driver: "SQLite3 ODBC Driver", download_url: "" });
    mockApi.getSettings.mockResolvedValue({
      ...BASE_SETTINGS,
      mouser_api_key_set: true,
      github_token_set: true,
    });
    renderPage();
    // with the probe honest-null, the ODBC step is absent and the machine still reads Ready
    expect(await screen.findByText("This Machine Is Ready")).toBeInTheDocument();
    expect(screen.queryByText(/install the odbc driver/i)).toBeNull();
  });
});

describe("SettingsPage - critique fixes", () => {
  it("a met step reads as achieved state, never as a command", async () => {
    mockApi.getSettings.mockResolvedValue({
      ...BASE_SETTINGS,
      mouser_api_key_set: true,
      github_token_set: true,
    });
    renderPage();
    expect(await screen.findByText("KiCad Wired")).toBeInTheDocument();
    expect(screen.getByText("ODBC Driver Installed")).toBeInTheDocument();
    expect(screen.getByText("Distributor Key Saved")).toBeInTheDocument();
    expect(screen.getByText("GitHub Connected")).toBeInTheDocument();
    expect(screen.queryByText("Wire KiCad")).toBeNull();
  });

  it("a single-section group opens its section on arrival", async () => {
    renderPage();
    const user = userEvent.setup();
    const nav = screen.getByRole("navigation", { name: /settings sections/i });
    await user.click(within(nav).getByRole("button", { name: /altium/i }));
    const header = await screen.findByTestId("settings.altium.header");
    expect(header).toHaveAttribute("aria-expanded", "true");
  });
});

describe("SettingsPage - dev-creds hotkey", () => {
  it("Ctrl+Alt+K loads the dev creds from ANYWHERE on Settings, sections collapsed", async () => {
    // The listener must live at the page level: before this test existed it sat in
    // VendorLoginsSection, which the grouped IA only mounts when that disclosure is
    // open, so the hotkey silently died on the collapsed default (2026-07-24 report).
    mockApi.loadDevCreds.mockResolvedValue({ ...BASE_SETTINGS, loaded: ["mouser_api_key"], config_path: "C:/Users/x/AppData/Roaming/Stockroom/dev-creds.json" });
    renderPage();
    await screen.findByTestId("settings.appearance.header"); // page settled, all collapsed
    fireEvent.keyDown(window, { key: "k", ctrlKey: true, altKey: true });
    await waitFor(() => expect(mockApi.loadDevCreds).toHaveBeenCalled());
    expect(await screen.findByText(/loaded dev creds: mouser_api_key/i)).toBeInTheDocument();
  });
});
