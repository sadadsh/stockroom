import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { api } from "../api/client";
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
    },
  };
});

const mockApi = vi.mocked(api);

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
  mockApi.getSettings.mockResolvedValue({
    mouser_api_key_set: false,
    mouser_api_key_hint: "",
  });
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
  mockApi.activateProfile.mockResolvedValue({ active: "Archive", part_count: 0 });
  mockApi.createProfile.mockResolvedValue({
    profiles: ["Main", "Archive", "Scratch"],
    active: "Main",
  });
  mockApi.deleteProfile.mockResolvedValue(undefined);
  mockApi.updateSettings.mockResolvedValue({
    mouser_api_key_set: true,
    mouser_api_key_hint: "Y123",
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

  it("shows the hint when a key is set and can clear it", async () => {
    mockApi.getSettings.mockResolvedValue({
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

  it("renders the kicad status", async () => {
    renderPage();
    expect(await screen.findByText("/usr/bin/kicad-cli")).toBeInTheDocument();
    expect(screen.getByText("/home/x/.config/kicad")).toBeInTheDocument();
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
