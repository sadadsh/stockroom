import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { OnboardingGate } from "./OnboardingGate";
import { ApiError, api } from "../api/client";
import { ToastProvider } from "../lib/toast";
import type { OnboardingStatus } from "../api/types";
import type { ScenarioUiState } from "../design-studio/scenario";
import { ScenarioUiProvider } from "../design-studio/scenarioState";

vi.mock("../api/client", async (importActual) => {
  const actual = await importActual<typeof import("../api/client")>();
  return {
    ...actual,
    api: { setLibrary: vi.fn(), completeOnboarding: vi.fn(), updateSettings: vi.fn() },
  };
});

const mockApi = vi.mocked(api);

const EDA_TOOLS: OnboardingStatus["eda_tools"] = [
  {
    key: "kicad",
    label: "KiCad",
    detected: true,
    selected: true,
    pending: false,
    setup_checks: ["installation", "catalog_wiring"],
    settings_target: "settings.kicad",
  },
  {
    key: "altium",
    label: "Altium Designer",
    detected: false,
    selected: false,
    pending: false,
    setup_checks: ["installation", "odbc", "catalog_connection"],
    settings_target: "settings.altium",
  },
];

const STATUS: OnboardingStatus = {
  primary_eda: "kicad",
  primary_eda_pending: null,
  primary_eda_confirmation_required: false,
  recommended_primary_eda: "kicad",
  primary_eda_requirements: ["symbol", "footprint", "model"],
  retained_optional_eda: ["altium"],
  eda_tools: EDA_TOOLS,
  onboarded: false,
  first_run: true,
  libraries_root: "/x",
  profiles: [],
  under_git: false,
  default_dir: "/home/u/.config/stockroom/library",
  libraries: [],
};

const UNCONFIRMED_STATUS: OnboardingStatus = {
  ...STATUS,
  onboarded: true,
  first_run: false,
  primary_eda: null,
  primary_eda_confirmation_required: true,
  primary_eda_requirements: [],
  retained_optional_eda: ["kicad", "altium"],
  eda_tools: EDA_TOOLS.map((tool) => ({ ...tool, selected: false })),
};

function renderGate(scenario: ScenarioUiState = {}, status = STATUS) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <ToastProvider>
        <ScenarioUiProvider state={scenario}>
          <OnboardingGate status={status} />
        </ScenarioUiProvider>
      </ToastProvider>
    </QueryClientProvider>,
  );
}

describe("OnboardingGate", () => {
  it("requires explicit Primary CAD Tool confirmation before catalog setup", async () => {
    mockApi.updateSettings.mockResolvedValue({} as never);
    renderGate({}, UNCONFIRMED_STATUS);

    expect(screen.getByRole("heading", { name: "Choose Your CAD Tool" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Open Existing" })).not.toBeInTheDocument();
    expect(screen.getByText("Recommended")).toBeInTheDocument();

    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Use Altium Designer" }));
    await waitFor(() =>
      expect(mockApi.updateSettings).toHaveBeenCalledWith({ primary_eda: "altium" }),
    );
  });

  it("shows the welcome and the three modes after a tool is confirmed", () => {
    renderGate();
    expect(
      screen.getByRole("heading", { name: "Set Up Your Components" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Open Existing" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Create New" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Clone From Git" })).toBeInTheDocument();
  });

  it("disables Set Up Library until the open path is entered", () => {
    renderGate();
    expect(screen.getByRole("button", { name: "Set Up Components" })).toBeDisabled();
  });

  it("opens an existing library with the entered path", async () => {
    mockApi.setLibrary.mockResolvedValue({ ...STATUS, first_run: false, libraries_root: "/lib" });
    renderGate();
    const u = userEvent.setup();
    await u.type(screen.getByPlaceholderText(/stockroom-components/), "/my/lib");
    await u.click(screen.getByRole("button", { name: "Set Up Components" }));
    await waitFor(() =>
      expect(mockApi.setLibrary).toHaveBeenCalledWith({ mode: "open", path: "/my/lib" }),
    );
  });

  it("creates with the default location when no path is given", async () => {
    mockApi.setLibrary.mockResolvedValue({ ...STATUS, first_run: false });
    renderGate();
    const u = userEvent.setup();
    await u.click(screen.getByRole("button", { name: "Create New" }));
    await u.click(screen.getByRole("button", { name: "Set Up Components" }));
    await waitFor(() =>
      expect(mockApi.setLibrary).toHaveBeenCalledWith({ mode: "create", path: undefined }),
    );
  });

  it("requires a url before cloning", async () => {
    renderGate();
    const u = userEvent.setup();
    await u.click(screen.getByRole("button", { name: "Clone From Git" }));
    expect(screen.getByRole("button", { name: "Set Up Components" })).toBeDisabled();
  });

  it("clones from a git url", async () => {
    mockApi.setLibrary.mockResolvedValue({ ...STATUS, first_run: false });
    renderGate();
    const u = userEvent.setup();
    await u.click(screen.getByRole("button", { name: "Clone From Git" }));
    await u.type(screen.getByPlaceholderText(/github\.com/), "https://x/lib.git");
    await u.click(screen.getByRole("button", { name: "Set Up Components" }));
    await waitFor(() =>
      expect(mockApi.setLibrary).toHaveBeenCalledWith({
        mode: "clone",
        url: "https://x/lib.git",
        dest: undefined,
      }),
    );
  });

  it("continues with the default library", async () => {
    mockApi.completeOnboarding.mockResolvedValue({ ...STATUS, onboarded: true, first_run: false });
    renderGate();
    const u = userEvent.setup();
    await u.click(
      screen.getByRole("button", { name: "Continue with the Default" }),
    );
    await waitFor(() => expect(mockApi.completeOnboarding).toHaveBeenCalled());
  });

  it("surfaces an error when continuing with the default fails", async () => {
    mockApi.completeOnboarding.mockRejectedValue(new ApiError(503, "git is offline"));
    renderGate();
    const u = userEvent.setup();
    await u.click(
      screen.getByRole("button", { name: "Continue with the Default" }),
    );
    await waitFor(() => expect(screen.getByText("git is offline")).toBeInTheDocument());
  });

  it("keeps a fixture setup failure visible during visual acceptance", async () => {
    vi.useFakeTimers();
    try {
      renderGate({ onboarding: { mode: "open", setupError: "Could not set up the catalog." } });
      expect(screen.getByText("Could not set up the catalog.")).toBeInTheDocument();
      await act(() => vi.advanceTimersByTimeAsync(5_000));
      expect(screen.getByText("Could not set up the catalog.")).toBeInTheDocument();
    } finally {
      vi.useRealTimers();
    }
  });
});
