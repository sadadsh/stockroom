import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { api } from "../api/client";
import type { OnboardingStatus, SettingsInfo, WiringReport } from "../api/types";
import { ToastProvider } from "../lib/toast";
import { AstryxThemeBridge, ThemeProvider } from "../lib/theme";
import { DevModeProvider } from "../lib/devMode";
import { resetUpdateClocksForTests } from "../lib/useUpdateStanding";
import { SettingsPage } from "./SettingsPage";
import { GUIDED_SETUP_READY } from "../design-studio/fixtures/onboardingFixtures";

// The revision THIS bundle was built at. A backend revision that disagrees with the running bundle
// is a standing of its own now ("Restart Required", C8), so the update cases below have to state
// the agreeing revision rather than inherit a synthetic one no build could match. Empty when the
// build carries no revision (no git at build time), where the comparison is never made.
const BUNDLE_REVISION = /\+([0-9a-f]{7,})$/i.exec(__APP_VERSION__)?.[1] ?? "";
const BACKEND_REVISION = BUNDLE_REVISION || "123456789abc";

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
      getOnboarding: vi.fn(),
      setLibrary: vi.fn(),
      getSyncStatus: vi.fn(),
      startGitHubLogin: vi.fn(),
      doSync: vi.fn(),
      connectLibraryRemote: vi.fn(),
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
      altiumModelsPending: vi.fn(),
      altiumEmbedCapability: vi.fn(),
      altiumEmbedModels: vi.fn(),
      libraryCoverage: vi.fn(),
      libraryDerivation: vi.fn(),
      cadInventory: vi.fn(),
      getLibraryLfs: vi.fn(),
      getRescanState: vi.fn(),
    },
  };
});

const mockApi = vi.mocked(api);

const BASE_SETTINGS: SettingsInfo = {
  primary_eda: "kicad",
  primary_eda_pending: null,
  primary_eda_confirmation_required: false,
  recommended_primary_eda: "kicad",
  primary_eda_requirements: ["symbol", "footprint", "model"],
  retained_optional_eda: ["altium"],
  eda_tools: [],
  mouser_api_key_set: false,
  mouser_api_key_hint: "",
  github_token_set: false,
  github_token_hint: "",
  digikey_client_id: "",
  digikey_client_secret_set: false,
  digikey_client_secret_hint: "",
  kicad_config_override: "",
  kicad_cli_override: "",
  kicad_config_dir: "/home/x/.config/kicad/10.0",
  kicad_cli_path: "/usr/bin/kicad-cli",
  kicad_cli_available: true,
  kicad_wired: true,
};

const BASE_ONBOARDING: OnboardingStatus = {
  primary_eda: "kicad",
  primary_eda_pending: null,
  primary_eda_confirmation_required: false,
  recommended_primary_eda: "kicad",
  primary_eda_requirements: ["symbol", "footprint", "model"],
  retained_optional_eda: ["altium"],
  eda_tools: [],
  onboarded: true,
  first_run: false,
  libraries_root: "C:/Libraries/Main",
  profiles: ["Main"],
  under_git: true,
  default_dir: "C:/Libraries/Library",
  libraries: [
    {
      name: "Main",
      path: "C:/Libraries/Main",
      active: true,
      available: true,
      under_git: true,
    },
    {
      name: "Archive",
      path: "C:/Libraries/Archive",
      active: false,
      available: true,
      under_git: true,
    },
  ],
  guided_setup: GUIDED_SETUP_READY,
};

function renderPage() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={qc}>
      <ThemeProvider>
        <AstryxThemeBridge>
          <ToastProvider>
            <SettingsPage />
          </ToastProvider>
        </AstryxThemeBridge>
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
        <AstryxThemeBridge>
          <DevModeProvider>
            <ToastProvider>
              <SettingsPage />
            </ToastProvider>
          </DevModeProvider>
        </AstryxThemeBridge>
      </ThemeProvider>
    </QueryClientProvider>,
  );
}

function toggleDevMode() {
  fireEvent.keyDown(window, { key: "D", ctrlKey: true, shiftKey: true });
}

// Settings is one continuous page. Tests wait for the exact permanent capability card they use.
async function openSettings(devId: string) {
  await screen.findByTestId(`${devId}.header`);
}

beforeEach(() => {
  resetUpdateClocksForTests();
  localStorage.clear();
  delete document.documentElement.dataset.theme;
  mockApi.getSettings.mockResolvedValue({ ...BASE_SETTINGS });
  mockApi.listProfiles.mockResolvedValue({
    profiles: ["Main", "Archive"],
    active: "Main",
  });
  mockApi.getOnboarding.mockResolvedValue(BASE_ONBOARDING);
  mockApi.setLibrary.mockResolvedValue(BASE_ONBOARDING);
  mockApi.getSyncStatus.mockResolvedValue({
    has_remote: true,
    current_branch: "main",
    ahead: 0,
    behind: 2,
    github_auth: { mode: "git_credential_manager", accounts: [] },
  });
  mockApi.checkUpdate.mockResolvedValue({
    update_available: false,
    state: "up_to_date",
    behind: 0,
    current_revision: BACKEND_REVISION,
    target_revision: BACKEND_REVISION,
    frontend_revision: BUNDLE_REVISION,
  } as never);
  mockApi.altiumOdbcStatus.mockResolvedValue({
    installed: true,
    driver: "SQLite3 ODBC Driver",
    download_url: "",
  });
  mockApi.altiumStatus.mockResolvedValue({
    profile: "Main",
    dblib: "C:/Stockroom/libraries/Main/altium/Stockroom.DbLib",
    dblib_dir: "C:/Stockroom/libraries/Main/altium",
    ready: 8,
    total: 8,
    datasource_present: true,
    rows: [],
  });
  mockApi.altiumModelsPending.mockResolvedValue({ pending: [], count: 0 });
  mockApi.altiumEmbedCapability.mockResolvedValue({
    installed: true,
    binary: "C:/Program Files/Altium/Altium.exe",
    requires_tool_installed: true,
    reason: "",
    busy: "",
    available: true,
  });
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
  mockApi.connectLibraryRemote.mockResolvedValue({
    configured: true,
    remote: "https://github.com/sadadsh/library.git",
  });
  mockApi.applyUpdate.mockResolvedValue({
    state: "updated",
    updated: true,
    detail: "",
    restart_requested: true,
  });
  mockApi.libraryCoverage.mockResolvedValue({
    total: 158,
    complete: 92,
    needs_files: 50,
    unsourced: 16,
    by_requirement: {},
    sources: ["ultralibrarian"],
    can_provide: ["kicad_symbol"],
  });
  mockApi.libraryDerivation.mockResolvedValue({
    ruleset: "rules@2",
    counts: { "rules@2": 158 },
    current: 158,
    stale: 0,
  });
  mockApi.cadInventory.mockResolvedValue({
    cleared: 184,
    kept_stock: 0,
    items: [],
    failed: [],
    missing_files: [],
  });
  mockApi.getLibraryLfs.mockResolvedValue({
    installed: true,
    version: "3.4.1",
    enabled: true,
    tracked_patterns: ["*.step"],
    objects: 62,
    legacy_blobs: 0,
    covers: [],
    adopted: true,
    reason: "",
  });
  mockApi.getRescanState.mockResolvedValue({
    parts: { "SR-0001": { checked_at: "2026-07-20T10:00:00Z", outcome: "updated" } },
    counts: { updated: 1 },
  });
});

function libraryRow(name: string): HTMLElement {
  const row = screen
    .getAllByText(name)
    .map((el) => el.closest("[data-library-row]"))
    .find(Boolean);
  return row as HTMLElement;
}

describe("SettingsPage - library repositories", () => {
  it("lists repositories and marks the active one", async () => {
    renderPage();
    await openSettings("settings.profiles");
    expect(await screen.findByText("Archive")).toBeInTheDocument();
    expect(within(libraryRow("Main")).getByText(/active/i)).toBeInTheDocument();
    expect(within(libraryRow("Main")).queryByRole("button", { name: /switch/i })).toBeNull();
    expect(within(libraryRow("Archive")).getByRole("button", { name: /switch catalog/i }))
      .toBeInTheDocument();
  });

  it("switches by opening the selected repository", async () => {
    renderPage();
    await openSettings("settings.profiles");
    await screen.findByText("Archive");
    await userEvent.click(
      within(libraryRow("Archive")).getByRole("button", { name: /switch catalog/i }),
    );
    expect(mockApi.setLibrary).toHaveBeenCalledWith({
      mode: "open",
      path: "C:/Libraries/Archive",
    });
  });

  it("creates a fresh Git repository at the requested path", async () => {
    renderPage();
    await openSettings("settings.profiles");
    await screen.findByText("Archive");
    await userEvent.type(screen.getByLabelText("New Catalog Folder"), "D:\\Libraries\\Scratch");
    await userEvent.click(screen.getByRole("button", { name: /set up catalog git remote/i }));
    expect(mockApi.setLibrary).toHaveBeenCalledWith({
      mode: "create",
      path: "D:\\Libraries\\Scratch",
    });
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

describe("SettingsPage — release links", () => {
  it("links to releases without promising a direct executable download", async () => {
    renderPage();
    await openSettings("settings.update");

    const releaseLinks = await screen.findAllByRole("link", { name: "View Releases" });
    expect(releaseLinks).toHaveLength(2);
    for (const link of releaseLinks) {
      expect(link).toHaveAttribute("href", "https://github.com/sadadsh/stockroom/releases");
    }
    expect(screen.queryByText(/Stockroom\.exe/i)).not.toBeInTheDocument();
  });
});

describe("SettingsPage — distributor key", () => {
  it("shows the key as not set and saves a typed key without ever exposing it", async () => {
    renderPage();
    await openSettings("settings.distributor");
    await screen.findAllByText(/not set/i);
    const input = screen.getByLabelText(/mouser api credential/i) as HTMLInputElement;
    expect(input.type).toBe("password");
    await userEvent.type(input, "MOUSERKEY123");
    await userEvent.click(screen.getByRole("button", { name: /save mouser credential/i }));
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
    const input = screen.getByLabelText(/mouser api credential/i);
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
    await userEvent.click(screen.getByRole("button", { name: /remove mouser credential/i }));
    expect(mockApi.updateSettings).toHaveBeenCalledWith({ mouser_api_key: "" });
  });
});

describe("SettingsPage — sync + kicad + update", () => {
  it("renders sync status and runs a sync", async () => {
    renderPage();
    await openSettings("settings.sync");
    expect((await screen.findAllByText(/main/)).length).toBeGreaterThan(0);
    await userEvent.click(screen.getByRole("button", { name: /pull and push catalog/i }));
    expect(mockApi.doSync).toHaveBeenCalled();
  });

  it("connects a fresh library to its own GitHub repository", async () => {
    mockApi.getSyncStatus.mockResolvedValue({
      has_remote: false,
      current_branch: "main",
      ahead: 0,
      behind: 0,
      github_auth: { mode: "git_credential_manager", accounts: ["sadadsh"] },
    });
    renderPage();
    await openSettings("settings.sync");
    const input = await screen.findByLabelText("Catalog GitHub Remote URL");
    await userEvent.type(input, "https://github.com/sadadsh/parts.git");
    await userEvent.click(screen.getByRole("button", { name: "Connect Catalog Git Remote" }));
    expect(mockApi.connectLibraryRemote).toHaveBeenCalledWith(
      "https://github.com/sadadsh/parts.git",
    );
  });

  it("shows the automatic device outcome and detects an active rival app checkout", async () => {
  mockApi.getSyncStatus.mockResolvedValue({
    has_remote: true,
    current_branch: "main",
    ahead: 0,
    behind: 0,
    github_auth: { mode: "git_credential_manager", accounts: [] },
      working_copy: {
        mode: "rival_application_checkout",
        detail: "The active library is inside a second checkout.",
      },
      checkout_inventory: {
        state: "complete",
        rival_count: 1,
        checkouts: [
          {
            path: "D:\\Other\\Stockroom",
            classification: "active_rival",
            revision: "abc123",
            current: false,
            tracked_dirty: false,
            active_library: true,
          },
        ],
      },
      last_sync: {
        state: "converged",
        pulled: true,
        pushed: true,
        converged: true,
        detail: "",
      },
    });

    renderPage();
    await openSettings("settings.sync");

    expect(await screen.findByText("Rival App Checkout Detected")).toBeInTheDocument();
    expect(screen.getByText("1 Rival Checkout Detected")).toBeInTheDocument();
    expect(screen.getByText("Devices Converged")).toBeInTheDocument();
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
    await screen.findByRole("button", { name: /pull and push catalog/i });
    await userEvent.click(screen.getByRole("button", { name: /pull and push catalog/i }));
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
    await screen.findByRole("button", { name: /pull and push catalog/i });
    await userEvent.click(screen.getByRole("button", { name: /pull and push catalog/i }));
    expect(await screen.findByText(/denied this windows account/i)).toBeInTheDocument();
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
    await screen.findByRole("button", { name: /pull and push catalog/i });
    await userEvent.click(screen.getByRole("button", { name: /pull and push catalog/i }));
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
    expect(await screen.findByText(/wired to the active catalog/i)).toBeInTheDocument();
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
    const cfg = screen.getByLabelText(/config folder override/i);
    await userEvent.type(cfg, "/custom/kicad/10.0");
    await userEvent.click(screen.getByRole("button", { name: /save paths and rewire/i }));
    expect(mockApi.updateSettings).toHaveBeenCalledWith({
      kicad_config_override: "/custom/kicad/10.0",
      kicad_cli_override: "/opt/kicad/kicad-cli",
    });
  });

  it("disables saving overrides until something changed", async () => {
    renderPage();
    await openSettings("settings.kicad");
    await screen.findByLabelText(/config folder override/i);
    expect(screen.getByRole("button", { name: /save paths and rewire/i })).toBeDisabled();
  });

  it("makes an available update automatic instead of leaving a restart action to the user", async () => {
    mockApi.checkUpdate.mockResolvedValue({
      update_available: true,
      state: "update_available",
      behind: 3,
      current_revision: BACKEND_REVISION,
      target_revision: "222222222222",
      automatic_on_launch: true,
      automatic_apply: true,
    } as never);
    renderPage();
    await openSettings("settings.update");
    expect(await screen.findByText(/automatic while stockroom is open/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /install and restart/i })).toBeNull();
    expect(screen.getByText(/health-checked/i)).toBeInTheDocument();
    expect(mockApi.applyUpdate).not.toHaveBeenCalled();
  });

  it("applies a verified ready release only after Restart Now", async () => {
    mockApi.checkUpdate.mockResolvedValue({
      update_available: true,
      state: "ready",
      convergence_phase: "ready",
      current_release_id: "release-0.7.0.1",
      target_release_id: "release-0.7.0.2",
      automatic_on_launch: true,
      automatic_apply: false,
    } as never);
    renderPage();
    await openSettings("settings.update");

    expect(await screen.findByText(/verified release is prepared/i)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /restart now/i }));

    expect(mockApi.applyUpdate).toHaveBeenCalledTimes(1);
  });

  it("does not offer to apply when up to date", async () => {
    renderPage();
    await openSettings("settings.update");
    expect((await screen.findAllByText(/^current$/i)).length).toBeGreaterThan(0);
    expect(screen.queryByRole("button", { name: /install and restart/i })).toBeNull();
  });

  it("says a restart is needed when the backend has moved past this window's bundle", async () => {
    // C8: the page reported the BACKEND's revision as the installed one, so a WebView2 bundle that
    // missed its reload read as a healthy, current install. Needs a bundle carrying a revision;
    // the pure rule for a bundle without one lives in lib/updateStanding.test.ts.
    if (!BUNDLE_REVISION) return;
    mockApi.checkUpdate.mockResolvedValue({
      update_available: false,
      state: "up_to_date",
      behind: 0,
      current_revision: "222222222222",
      target_revision: "222222222222",
      frontend_revision: "222222222222",
    } as never);
    renderPage();
    await openSettings("settings.update");
    expect(
      await screen.findByText(/restart stockroom to finish adopting the installed revision/i),
    ).toBeInTheDocument();
    const update = document.querySelector<HTMLElement>('[data-dev-id="settings.update"]')!;
    expect(within(update).queryByText(/^current$/i)).toBeNull();
  });

  it("never presents an unverified offline result as Current", async () => {
    mockApi.checkUpdate.mockResolvedValue({
      update_available: false,
      state: "offline",
      current_revision: BACKEND_REVISION,
      target_revision: "",
      detail: "network unavailable",
    } as never);
    renderPage();
    await openSettings("settings.update");
    expect(
      await screen.findByText(/remote check incomplete; automatic reruns continue/i),
    ).toBeInTheDocument();
    const update = document.querySelector<HTMLElement>('[data-dev-id="settings.update"]')!;
    expect(within(update).queryByText(/^current$/i)).toBeNull();
    expect(screen.queryByRole("button", { name: /install and restart/i })).toBeNull();
  });
});

it("signs the Windows user into GitHub without asking Stockroom for a token", async () => {
  mockApi.getSyncStatus
    .mockResolvedValueOnce({
      has_remote: true,
      current_branch: "main",
      ahead: 0,
      behind: 0,
      github_auth: { mode: "git_credential_manager", accounts: [] },
    })
    .mockResolvedValue({
      has_remote: true,
      current_branch: "main",
      ahead: 0,
      behind: 0,
      github_auth: { mode: "git_credential_manager", accounts: ["sadadsh"] },
    });
  mockApi.startGitHubLogin.mockResolvedValue({ job_id: "github-login" });
  mockApi.openJobStream.mockResolvedValue(
    sseStream([
      'event: result\ndata: {"result":{"mode":"git_credential_manager","accounts":["sadadsh"]}}',
      "event: done\ndata: {}",
    ]),
  );
  renderPage();
  await openSettings("settings.github");
  expect(screen.queryByLabelText(/personal access token/i)).toBeNull();
  await userEvent.click(screen.getByRole("button", { name: /sign in with github/i }));
  expect(mockApi.startGitHubLogin).toHaveBeenCalledTimes(1);
  expect(await screen.findByText("sadadsh")).toBeInTheDocument();
  expect(mockApi.updateSettings).not.toHaveBeenCalledWith(expect.objectContaining({
    github_token: expect.anything(),
  }));
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

    await user.click(await screen.findByRole("button", { name: "Recheck And Wire KiCad" }));

    await waitFor(() => expect(mockApi.wireKicad).toHaveBeenCalledTimes(1));
    expect(await screen.findByText(/Registered 2 categories/)).toBeInTheDocument();
    expect(screen.getByText(/Restart KiCad to load the updated tables\./)).toBeInTheDocument();
  });
});

describe("SettingsPage - distributor API credentials", () => {
  it("saves the DigiKey API creds and masks the client secret input", async () => {
    const user = userEvent.setup();
    mockApi.updateSettings.mockResolvedValue({ ...BASE_SETTINGS });
    renderPage();
    await openSettings("settings.distributor");
    const secret = screen.getByLabelText("DigiKey API Client Secret");
    expect(secret).toHaveAttribute("type", "password");
    await user.type(screen.getByLabelText("DigiKey API Client ID"), "CLIENTID");
    await user.type(secret, "APISECRET");
    await user.click(screen.getByRole("button", { name: "Save DigiKey API Credentials" }));
    expect(mockApi.updateSettings).toHaveBeenCalledWith(
      expect.objectContaining({
        digikey_client_id: "CLIENTID",
        digikey_client_secret: "APISECRET",
      }),
    );
  });

  // Stockroom no longer signs in to a provider website, so no provider login can be configured.
  it("offers no provider-website sign-in anywhere in Data Sources", async () => {
    renderPage();
    await openSettings("settings.distributor");
    expect(screen.queryByText("Provider Sessions And Optional Sign-Ins")).toBeNull();
    expect(screen.queryByLabelText("Ultra Librarian Password")).toBeNull();
    expect(screen.queryByLabelText("SnapEDA Password")).toBeNull();
    expect(screen.queryByLabelText("SamacSys Password")).toBeNull();
    expect(screen.queryByLabelText("DigiKey Account Password")).toBeNull();
  });
});

describe("SettingsPage - copy adoption", () => {
  it("exposes settings.* copy ids on its labels once dev mode is on", async () => {
    const { container } = renderDevPage();
    // Walk to the Library group and open the sections whose labels we spot-check.
    await openSettings("settings.sync");
    await openSettings("settings.github");
    await screen.findByRole("button", { name: /sign in with github/i });

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
    expect(screen.getByText("Settings")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /sign in with github/i })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /pull and push catalog/i }));
    expect(mockApi.doSync).toHaveBeenCalled();
  });

  it("keeps repository setup copy in the shared copy layer", async () => {
    renderPage();
    await openSettings("settings.profiles");
    expect(
      await screen.findByRole("button", { name: /set up catalog git remote/i }),
    ).toBeInTheDocument();
  });
});

describe("SettingsPage - flat IA + Machine Setup band", () => {
  it("mounts every settings capability on one continuous page without category navigation", async () => {
    renderPage();
    await screen.findByTestId("settings.appearance.header");
    expect(screen.queryByRole("navigation", { name: /settings sections/i })).toBeNull();
    for (const id of [
      "settings.appearance", "settings.about", "settings.update", "settings.profiles", "settings.sync",
      "settings.github", "settings.kicad", "settings.altium", "settings.cubemx",
      "settings.distributor", "settings.rescan", "settings.completion", "settings.derivation",
      "settings.health", "settings.librarysync", "settings.cad-clear",
    ]) {
      expect(screen.getByTestId(`${id}.header`)).toBeInTheDocument();
    }
  });

  it("places About, the installed version, and project links inside Settings", async () => {
    renderPage();
    const about = await screen.findByTestId("settings.about.header");
    expect(about).toHaveTextContent("About Stockroom");
    expect(document.querySelector('[data-dev-id="about.root"]')).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /LinkedIn.*opens in new tab/i })).toHaveAttribute(
      "href",
      "https://www.linkedin.com/in/sadadhaidari",
    );
    expect(screen.getByRole("link", { name: /GitHub.*opens in new tab/i })).toHaveAttribute(
      "href",
      "https://github.com/sadadsh",
    );
    expect(screen.getAllByText(__APP_VERSION__).length).toBeGreaterThan(0);
    expect(screen.queryByRole("dialog", { name: "About Stockroom" })).toBeNull();
  });

  it("owns one page scroller containing readiness and every capability card", async () => {
    renderPage();
    await screen.findByTestId("settings.appearance.header");
    const content = document.querySelector<HTMLElement>('[data-dev-id="settings.content"]');
    const machine = document.querySelector<HTMLElement>('[data-dev-id="settings.machine-band"]');
    const maintenance = document.querySelector<HTMLElement>('[data-dev-id="settings.cad-clear"]');
    expect(content).not.toBeNull();
    expect(content).toHaveClass("overflow-y-auto");
    expect(content).toContainElement(machine);
    expect(content).toContainElement(maintenance);
  });

  it("states the machine verdict from the live settings (all met reads Ready)", async () => {
    mockApi.getSettings.mockResolvedValue({
      ...BASE_SETTINGS,
      mouser_api_key_set: true,
      github_token_set: true,
    });
    renderPage();
    expect(await screen.findByText("This Machine Is Prepared")).toBeInTheDocument();
    expect(screen.getByText("Signed Release Updates")).toBeInTheDocument();
    expect(screen.queryByText("Automatic Convergence")).not.toBeInTheDocument();
  });

  it("counts unmet authoritative setup steps and focuses the selected tool card", async () => {
    const scrollIntoView = vi.fn();
    Element.prototype.scrollIntoView = scrollIntoView;
    mockApi.getOnboarding.mockResolvedValue({
      ...BASE_ONBOARDING,
      guided_setup: {
        ...GUIDED_SETUP_READY,
        repository_ready: false,
        github: { ...GUIDED_SETUP_READY.github, online: false },
        tool_connection: { ...GUIDED_SETUP_READY.tool_connection, connected: false },
      },
    });
    renderPage();
    expect(await screen.findByText("2 Setup Steps Need Attention")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /connect the selected cad tool/i }));
    const section = document.querySelector<HTMLElement>('[data-dev-id="settings.kicad"]');
    expect(scrollIntoView).toHaveBeenCalledWith({ block: "start", behavior: "smooth" });
    expect(section).toHaveFocus();
  });

  it("shows both EDA integrations immediately when KiCad needs attention", async () => {
    mockApi.getSettings.mockResolvedValue({ ...BASE_SETTINGS, kicad_wired: false });
    renderPage();
    expect(await screen.findByTestId("settings.kicad.header")).toBeInTheDocument();
    expect(screen.getByTestId("settings.altium.header")).toBeInTheDocument();
    expect(await screen.findByText(/not wired so far/i)).toBeInTheDocument();
  });

  it("keeps optional provider and non-selected tool checks out of readiness", async () => {
    mockApi.altiumOdbcStatus.mockResolvedValue({
      installed: null,
      driver: "SQLite3 ODBC Driver",
      download_url: "",
    });
    mockApi.getSettings.mockResolvedValue({
      ...BASE_SETTINGS,
      mouser_api_key_set: true,
      github_token_set: true,
    });
    renderPage();
    expect(await screen.findByText("This Machine Is Prepared")).toBeInTheDocument();
    expect(screen.queryByText(/install the odbc driver/i)).toBeNull();
    expect(screen.queryByText(/distributor credential/i)).toBeNull();
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
    expect(await screen.findByText("Selected CAD Tool Connected")).toBeInTheDocument();
    expect(screen.getByText("Catalog Repository Connected")).toBeInTheDocument();
    expect(screen.queryByText("Wire KiCad")).toBeNull();
    expect(screen.queryByText(/Distributor Credential Saved/i)).toBeNull();
  });

  it("presents both EDA integrations without a second reveal", async () => {
    renderPage();
    expect(await screen.findByTestId("settings.kicad.header")).toBeInTheDocument();
    expect(screen.getByTestId("settings.altium.header")).toBeInTheDocument();
  });
});

describe("SettingsPage - capability cards state their own status", () => {
  it("Library Completion, Presentation Data and Clear CAD Files each report their state", async () => {
    renderPage();
    const completion = await screen.findByTestId("settings.completion.header");
    expect(await within(completion).findByText("92 of 158 Complete")).toBeInTheDocument();

    const derivation = screen.getByTestId("settings.derivation.header");
    expect(await within(derivation).findByText("rules@2")).toBeInTheDocument();

    const cadClear = screen.getByTestId("settings.cad-clear.header");
    expect(await within(cadClear).findByText("184 Files")).toBeInTheDocument();

    // The item named three; ENUMERATING the population found five. Library Health, Library Sync
    // and Procurement Rescan were equally silent and are covered in the same pass rather than
    // left to be rediscovered by a later critique of the same screen.
    const health = screen.getByTestId("settings.health.header");
    expect(await within(health).findByText("Sound")).toBeInTheDocument();
    const librarySync = screen.getByTestId("settings.librarysync.header");
    expect(await within(librarySync).findByText("62 In LFS")).toBeInTheDocument();
  });

  it("an LFS repo holding nothing yet reads as a state, not as the number zero", async () => {
    // Caught by LOOKING at the rendered surface against the real library, which showed
    // "0 In LFS" beside siblings reading "None" and "Sound". A zero dressed as a count is
    // the data-vomit the complaint register already names.
    mockApi.getLibraryLfs.mockResolvedValue({
      installed: true,
      version: "3.4.1",
      enabled: true,
      tracked_patterns: ["*.step"],
      objects: 0,
      legacy_blobs: 0,
      covers: [],
      adopted: true,
      reason: "",
    });
    renderPage();
    const librarySync = await screen.findByTestId("settings.librarysync.header");
    expect(await within(librarySync).findByText("Nothing In LFS")).toBeInTheDocument();
    expect(within(librarySync).queryByText("0 In LFS")).toBeNull();
  });

  it("EVERY capability card states a concise status", async () => {
    renderPage();
    await screen.findByTestId("settings.appearance.header");
    await screen.findByText("62 In LFS");

    const seen: string[] = [];
    const silent: string[] = [];
    for (const header of document.querySelectorAll<HTMLElement>('[data-testid$=".header"]')) {
      const id = header.getAttribute("data-testid") || "";
      if (!id.startsWith("settings.") || seen.includes(id)) continue;
      seen.push(id);
      const summary = within(header).queryByTestId("settings.summary");
      if (!summary || !summary.textContent?.trim()) silent.push(id);
    }

    // assert the key space is non-empty BEFORE trusting an empty failure list: a selector that
    // matched nothing would otherwise report perfect coverage of zero sections.
    expect(seen.length, "no disclosures were found at all - the selector is wrong").toBeGreaterThan(
      10,
    );
    expect(silent, `these capability cards state no status: ${silent}`).toEqual([]);
  });

  it("a complete library and an empty CAD inventory read as states, not as zeroes", async () => {
    // "0 of 158 Complete" and "0 Files" are technically true and useless. The calm states are
    // their own words, matching how Component Sync says "Up To Date" rather than "0 Behind".
    mockApi.libraryCoverage.mockResolvedValue({
      total: 158,
      complete: 158,
      needs_files: 0,
      unsourced: 0,
      by_requirement: {},
      sources: [],
      can_provide: [],
    });
    mockApi.cadInventory.mockResolvedValue({
      cleared: 0,
      kept_stock: 0,
      items: [],
      failed: [],
      missing_files: [],
    });
    mockApi.libraryDerivation.mockResolvedValue({
      ruleset: "rules@2",
      counts: {},
      current: 100,
      stale: 58,
    });
    renderPage();
    const completion = await screen.findByTestId("settings.completion.header");
    expect(await within(completion).findByText("All Complete")).toBeInTheDocument();
    const cadClear = screen.getByTestId("settings.cad-clear.header");
    expect(await within(cadClear).findByText("None")).toBeInTheDocument();
    // a stale count is the ACTIONABLE half, so it wins the row over the ruleset name
    const derivation = screen.getByTestId("settings.derivation.header");
    expect(await within(derivation).findByText("58 Stale")).toBeInTheDocument();
  });
});

describe("SettingsPage - dev-creds hotkey", () => {
  it("Ctrl+Alt+K loads the dev creds from ANYWHERE on Settings", async () => {
    mockApi.loadDevCreds.mockResolvedValue({
      ...BASE_SETTINGS,
      loaded: ["mouser_api_key"],
      config_path: "C:/Users/x/AppData/Roaming/Stockroom/dev-creds.json",
    });
    renderPage();
    await screen.findByTestId("settings.appearance.header");
    fireEvent.keyDown(window, { key: "k", ctrlKey: true, altKey: true });
    await waitFor(() => expect(mockApi.loadDevCreds).toHaveBeenCalled());
    expect(await screen.findByText(/loaded dev creds: mouser_api_key/i)).toBeInTheDocument();
  });
});
