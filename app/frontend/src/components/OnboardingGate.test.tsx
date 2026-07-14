import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { OnboardingGate } from "./OnboardingGate";
import { ApiError, api } from "../api/client";
import { ToastProvider } from "../lib/toast";
import type { OnboardingStatus } from "../api/types";

vi.mock("../api/client", async (importActual) => {
  const actual = await importActual<typeof import("../api/client")>();
  return { ...actual, api: { setLibrary: vi.fn(), completeOnboarding: vi.fn() } };
});

const mockApi = vi.mocked(api);

const STATUS: OnboardingStatus = {
  onboarded: false,
  first_run: true,
  libraries_root: "/x",
  profiles: [],
  under_git: false,
  default_dir: "/home/u/.config/stockroom/library",
};

function renderGate() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <ToastProvider>
        <OnboardingGate status={STATUS} />
      </ToastProvider>
    </QueryClientProvider>,
  );
}

describe("OnboardingGate", () => {
  it("shows the welcome and the three modes", () => {
    renderGate();
    expect(
      screen.getByRole("heading", { name: "Set Up Your Library" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Open Existing" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Create New" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Clone From Git" })).toBeInTheDocument();
  });

  it("disables Set Up Library until the open path is entered", () => {
    renderGate();
    expect(screen.getByRole("button", { name: "Set Up Library" })).toBeDisabled();
  });

  it("opens an existing library with the entered path", async () => {
    mockApi.setLibrary.mockResolvedValue({ ...STATUS, first_run: false, libraries_root: "/lib" });
    renderGate();
    const u = userEvent.setup();
    await u.type(screen.getByPlaceholderText(/stockroom-library/), "/my/lib");
    await u.click(screen.getByRole("button", { name: "Set Up Library" }));
    await waitFor(() =>
      expect(mockApi.setLibrary).toHaveBeenCalledWith({ mode: "open", path: "/my/lib" }),
    );
  });

  it("creates with the default location when no path is given", async () => {
    mockApi.setLibrary.mockResolvedValue({ ...STATUS, first_run: false });
    renderGate();
    const u = userEvent.setup();
    await u.click(screen.getByRole("button", { name: "Create New" }));
    await u.click(screen.getByRole("button", { name: "Set Up Library" }));
    await waitFor(() =>
      expect(mockApi.setLibrary).toHaveBeenCalledWith({ mode: "create", path: undefined }),
    );
  });

  it("requires a url before cloning", async () => {
    renderGate();
    const u = userEvent.setup();
    await u.click(screen.getByRole("button", { name: "Clone From Git" }));
    expect(screen.getByRole("button", { name: "Set Up Library" })).toBeDisabled();
  });

  it("clones from a git url", async () => {
    mockApi.setLibrary.mockResolvedValue({ ...STATUS, first_run: false });
    renderGate();
    const u = userEvent.setup();
    await u.click(screen.getByRole("button", { name: "Clone From Git" }));
    await u.type(screen.getByPlaceholderText(/github\.com/), "https://x/lib.git");
    await u.click(screen.getByRole("button", { name: "Set Up Library" }));
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
      screen.getByRole("button", { name: "Continue With the Default Library" }),
    );
    await waitFor(() => expect(mockApi.completeOnboarding).toHaveBeenCalled());
  });

  it("surfaces an error when continuing with the default fails", async () => {
    mockApi.completeOnboarding.mockRejectedValue(new ApiError(503, "git is offline"));
    renderGate();
    const u = userEvent.setup();
    await u.click(
      screen.getByRole("button", { name: "Continue With the Default Library" }),
    );
    await waitFor(() => expect(screen.getByText("git is offline")).toBeInTheDocument());
  });
});
