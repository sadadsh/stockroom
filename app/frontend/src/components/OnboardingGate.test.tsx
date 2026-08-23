import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../api/client";
import type { OnboardingStatus } from "../api/types";
import { guidedSetupAt, GUIDED_SETUP_READY } from "../design-studio/fixtures/onboardingFixtures";
import { ScenarioUiProvider } from "../design-studio/scenarioState";
import { ToastProvider } from "../lib/toast";
import { OnboardingGate } from "./OnboardingGate";

vi.mock("../api/client", async (importActual) => {
  const actual = await importActual<typeof import("../api/client")>();
  return {
    ...actual,
    api: {
      ...actual.api,
      updateSettings: vi.fn(),
      startOnboardingGitHubLogin: vi.fn(),
      getOnboardingGitHubRepositories: vi.fn(),
      setGuidedRepository: vi.fn(),
      connectGuidedTool: vi.fn(),
      saveGuidedSourceData: vi.fn(),
      completeOnboarding: vi.fn(),
      openJobStream: vi.fn(),
    },
  };
});

const mockApi = vi.mocked(api);

const EDA_TOOLS: OnboardingStatus["eda_tools"] = [
  { key: "kicad", label: "KiCad", detected: true, selected: true, pending: false, setup_checks: ["installation", "catalog_wiring"], settings_target: "settings.kicad" },
  { key: "altium", label: "Altium Designer", detected: true, selected: false, pending: false, setup_checks: ["installation", "odbc", "catalog_connection"], settings_target: "settings.altium" },
];

function statusAt(step: OnboardingStatus["guided_setup"]["step"], overrides: Partial<OnboardingStatus> = {}): OnboardingStatus {
  return {
    primary_eda: "kicad",
    primary_eda_pending: null,
    primary_eda_confirmation_required: false,
    recommended_primary_eda: "kicad",
    primary_eda_requirements: ["symbol", "footprint", "model"],
    retained_optional_eda: ["altium"],
    eda_tools: EDA_TOOLS,
    onboarded: false,
    first_run: true,
    libraries_root: "C:/Stockroom",
    profiles: [],
    under_git: true,
    default_dir: "C:/Users/Engineer/Stockroom Catalog",
    libraries: [],
    guided_setup: guidedSetupAt(step, { ready: step === "ready" }),
    ...overrides,
  };
}

function streamOf(...events: string[]): ReadableStream<Uint8Array> {
  return new ReadableStream({
    start(controller) {
      const encoder = new TextEncoder();
      events.forEach((event) => controller.enqueue(encoder.encode(event)));
      controller.close();
    },
  });
}

function controlledStream() {
  const encoder = new TextEncoder();
  let controller!: ReadableStreamDefaultController<Uint8Array>;
  return {
    stream: new ReadableStream<Uint8Array>({ start(value) { controller = value; } }),
    send(event: string) { controller.enqueue(encoder.encode(event)); },
    close() { controller.close(); },
  };
}

function renderGate(status: OnboardingStatus, scenario = {}) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  client.setQueryData(["onboarding"], status);
  return render(
    <QueryClientProvider client={client}>
      <ToastProvider>
        <ScenarioUiProvider state={scenario}>
          <OnboardingGate status={status} />
        </ScenarioUiProvider>
      </ToastProvider>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  mockApi.getOnboardingGitHubRepositories.mockResolvedValue({ repositories: [] });
  Object.defineProperty(window, "__STOCKROOM_HOST__", {
    configurable: true,
    value: { pickFolder: vi.fn().mockResolvedValue(["D:\\Catalogs\\Stockroom Catalog"]) },
  });
});

describe("OnboardingGate", () => {
  it("renders only the three required setup steps", () => {
    renderGate(statusAt("connect_the_tool"));

    const progress = screen.getByRole("list", { name: "Setup Progress" });
    expect(within(progress).getAllByRole("listitem").map((item) => item.textContent)).toEqual([
      "1.Choose CAD Tool",
      "2.Catalog Repository",
      "3.Connect The Tool",
    ]);
    expect(screen.getByRole("heading", { name: "Connect The Tool" })).toBeInTheDocument();
  });

  it("records one explicit CAD choice from one primary action", async () => {
    mockApi.updateSettings.mockResolvedValue({} as never);
    const status = statusAt("choose_cad_tool", {
      primary_eda: null,
      primary_eda_confirmation_required: true,
      primary_eda_requirements: [],
      retained_optional_eda: ["kicad", "altium"],
    });
    renderGate(status);

    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: /^Altium Designer/ }));
    expect(mockApi.updateSettings).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "Continue" }));

    await waitFor(() => expect(mockApi.updateSettings).toHaveBeenCalledWith({ primary_eda: "altium" }));
  });

  it("shows the GitHub device code before opening the authorization page", async () => {
    const open = vi.spyOn(window, "open").mockReturnValue(null);
    const events = controlledStream();
    const unsigned = statusAt("catalog_repository");
    unsigned.guided_setup = guidedSetupAt("catalog_repository", {
      ready: false,
      repository_ready: false,
      repository: null,
      github: { available: true, version: "2.80.0", authenticated: false, online: true, viewer: null, owners: [] },
    });
    mockApi.startOnboardingGitHubLogin.mockResolvedValue({ job_id: "login-1" });
    mockApi.openJobStream.mockResolvedValue(events.stream);
    renderGate(unsigned);

    expect(screen.queryByLabelText(/token/i)).not.toBeInTheDocument();
    await userEvent.setup().click(screen.getByRole("button", { name: "Sign In With GitHub" }));
    await waitFor(() => expect(mockApi.openJobStream).toHaveBeenCalledWith("login-1"));
    expect(open).not.toHaveBeenCalled();

    events.send('event: progress\ndata: {"stage":"device_code","pct":0.3,"message":"Enter this code in GitHub","user_code":"ABCD-EFGH","verification_uri":"https://github.com/login/device"}\n\n');
    expect(await screen.findByText("ABCD-EFGH")).toBeVisible();
    expect(open).toHaveBeenCalledWith(
      "https://github.com/login/device",
      "_blank",
      "noreferrer",
    );
    events.send('event: result\ndata: {"result":{"viewer":{"login":"engineer","name":null},"owners":[]}}\n\n');
    events.send("event: done\ndata: {}\n\n");
    events.close();
  });

  it("creates for a personal or organization owner with an editable slug, access, and native folder picker", async () => {
    const status = statusAt("catalog_repository");
    mockApi.setGuidedRepository.mockResolvedValue(statusAt("connect_the_tool"));
    renderGate(status, { onboarding: { mode: "create" } });

    const user = userEvent.setup();
    expect(screen.getByLabelText("Git Checkout Name")).toHaveValue("stockroom-catalog");
    expect(screen.getByText("Suggested Name: Stockroom Catalog")).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "hardware-team (Organization)" })).toBeInTheDocument();
    expect(screen.queryByLabelText(/path|url|token/i)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Create Catalog" })).toBeEnabled();

    await user.selectOptions(screen.getByLabelText("GitHub Owner"), "hardware-team");
    await user.clear(screen.getByLabelText("Git Checkout Name"));
    await user.type(screen.getByLabelText("Git Checkout Name"), "shared-catalog");
    await user.click(screen.getByRole("button", { name: "Public" }));
    await user.click(screen.getByRole("button", { name: "Create Catalog" }));

    expect((window as unknown as { __STOCKROOM_HOST__: { pickFolder: ReturnType<typeof vi.fn> } }).__STOCKROOM_HOST__.pickFolder).not.toHaveBeenCalled();
    await waitFor(() => expect(mockApi.setGuidedRepository).toHaveBeenCalledWith({
      mode: "create",
      owner: "hardware-team",
      name: "shared-catalog",
      visibility: "public",
      path: "C:/Users/Engineer/Stockroom Catalog",
    }));
  });

  it("makes the likely catalog an obvious selection and connects it without a path choice", async () => {
    mockApi.getOnboardingGitHubRepositories.mockResolvedValue({ repositories: [
      { owner: "engineer", name: "unrelated-app", url: "https://github.com/engineer/unrelated-app.git", visibility: "private", permission: "admin", writable: true },
      { owner: "engineer", name: "Mainline-Components", url: "https://github.com/engineer/Mainline-Components.git", visibility: "private", permission: "admin", writable: true },
      { owner: "engineer", name: "read-only", url: "https://github.com/engineer/read-only.git", visibility: "public", permission: "read", writable: false },
    ] });
    mockApi.setGuidedRepository.mockResolvedValue(statusAt("connect_the_tool"));
    renderGate(statusAt("catalog_repository"));

    const selector = await screen.findByRole("combobox", { name: "Catalog Repository" });
    expect(selector).toHaveValue("Mainline-Components");
    expect(screen.queryByText(/read-only/)).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/path|url|token/i)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Change Folder" })).not.toBeInTheDocument();
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Connect Mainline-Components" }));

    await waitFor(() => expect(mockApi.setGuidedRepository).toHaveBeenCalledWith({
      mode: "connect",
      owner: "engineer",
      name: "Mainline-Components",
      visibility: undefined,
      path: "C:/Users/Engineer/Stockroom Catalog",
    }));
  });

  it("discloses the explicit Altium launch before starting its connection job", async () => {
    mockApi.connectGuidedTool.mockResolvedValue({ job_id: "tool-1" });
    mockApi.openJobStream.mockResolvedValue(streamOf(
      'event: result\ndata: {"result":{"tool_connection":{"tool":"altium","installed":true,"connected":true,"restart_required":false,"detail":"Altium is connected."},"receipt":{}}}\n\n',
      "event: done\ndata: {}\n\n",
    ));
    const status = statusAt("connect_the_tool", { primary_eda: "altium" });
    status.guided_setup = guidedSetupAt("connect_the_tool", {
      ready: false,
      tool_connection: { tool: "altium", installed: true, connected: false, restart_required: false, detail: "Setup required.", odbc_installed: true, busy: "" },
    });
    renderGate(status);

    expect(screen.getByText(/Altium Designer can open during this explicit setup/)).toBeInTheDocument();
    await userEvent.setup().click(screen.getByRole("button", { name: "Connect Altium Designer" }));
    await waitFor(() => expect(mockApi.connectGuidedTool).toHaveBeenCalledOnce());
  });

  it("completes an already-ready setup without another confirmation screen", async () => {
    const status = statusAt("ready", { guided_setup: GUIDED_SETUP_READY });
    mockApi.completeOnboarding.mockResolvedValue({ ...status, onboarded: true, first_run: false });
    renderGate(status);

    await waitFor(() => expect(mockApi.completeOnboarding).toHaveBeenCalledOnce());
    expect(screen.queryByRole("button", { name: "Open Components" })).not.toBeInTheDocument();
  });
});
