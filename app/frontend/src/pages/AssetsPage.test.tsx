import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { api } from "../api/client";
import { SETTINGS_ONBOARDING } from "../design-studio/fixtures/settingsFixtures";
import { AddPartProvider } from "../lib/addPart";
import { RouterProvider } from "../lib/router";
import { makeDossier, makeProviderRow } from "../test/dossierFixture";
import { AssetsPage } from "./AssetsPage";

vi.mock("../api/client", async (importActual) => {
  const actual = await importActual<typeof import("../api/client")>();
  return {
    ...actual,
    api: {
      ...actual.api,
      getOnboarding: vi.fn(),
      listParts: vi.fn(),
      partDossier: vi.fn(),
      catalogBuildStatus: vi.fn(),
      catalogBuild: vi.fn(),
      startManualProviderBrowser: vi.fn(),
      manualProviderBrowserStatus: vi.fn(),
      stopManualProviderBrowser: vi.fn(),
      applyPartFiles: vi.fn(),
    },
  };
});

const mockApi = vi.mocked(api);

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <RouterProvider initial="assets">
        <AddPartProvider><AssetsPage /></AddPartProvider>
      </RouterProvider>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  mockApi.getOnboarding.mockResolvedValue({ ...SETTINGS_ONBOARDING, primary_eda: "altium" });
  mockApi.partDossier.mockResolvedValue(makeDossier());
  mockApi.listParts.mockResolvedValue({
    count: 2,
    parts: [
      {
        id: "missing",
        display_name: "ADG714BRUZ-REEL",
        category: "Switches",
        mpn: "ADG714BRUZ-REEL",
        manufacturer: "Analog Devices",
        is_complete: false,
        missing: ["symbol", "footprint"],
        eda_readiness: { altium: { required: ["symbol", "footprint", "model"], missing: ["symbol", "footprint"], coverage_complete: false, trust: "unknown", ready: false } },
      },
      {
        id: "ready",
        display_name: "LM358DR",
        category: "Integrated Circuits",
        mpn: "LM358DR",
        manufacturer: "Texas Instruments",
        is_complete: true,
        missing: [],
        eda_readiness: { altium: { required: ["symbol", "footprint", "model"], missing: [], coverage_complete: true, trust: "pass", ready: true } },
      },
    ],
  });
  mockApi.catalogBuildStatus.mockResolvedValue({
    state: "pending",
    primary_eda: "altium",
    tool_label: "Altium Designer",
    desired_identity: "desired-1",
    completed_identity: "",
    pending_count: 1,
    pending_parts: [{ id: "ready", display_name: "LM358DR", identity: "part-1" }],
    blocked_parts: [],
    last_result: null,
    history: [],
  });
  mockApi.catalogBuild.mockResolvedValue({
    status: "completed",
    primary_eda: "altium",
    tool_label: "Altium Designer",
    attempted: 1,
    succeeded: 1,
    failed: 0,
    started_at: "2026-08-19T12:00:00Z",
    completed_at: "2026-08-19T12:00:01Z",
    items: [{ part_id: "ready", status: "current", detail: "Altium catalog projection is current." }],
  });
  mockApi.stopManualProviderBrowser.mockResolvedValue({
    stopped: true,
    session_id: "7ed4d06c-66b0-4dbe-88ef-35edce7a373f",
  });
});

describe("AssetsPage", () => {
  it("opens on Needs Assets when required CAD work exists", async () => {
    const user = userEvent.setup();
    renderPage();

    expect(await screen.findByText("ADG714BRUZ-REEL")).toBeVisible();
    expect(screen.queryByText("Choose Needs Assets or Build Now.")).toBeNull();
    expect(await screen.findByText("1 Pending")).toBeVisible();
    const addParts = screen.getByRole("button", { name: "Add Parts" });
    expect(addParts).toHaveClass("w-full", "!h-12");
    expect(screen.getByRole("heading", { name: "Assets" }).parentElement).not.toContainElement(addParts);
    expect(screen.getByText("Symbol, Footprint")).toBeVisible();
    expect(screen.queryByText("symbol, footprint")).toBeNull();
    expect(screen.queryByText("LM358DR")).toBeNull();

    await user.click(screen.getByRole("button", { name: "Manage CAD Assets" }));
    expect(await screen.findByRole("button", { name: "Back To Assets" })).toBeVisible();
    await user.click(screen.getByRole("button", { name: "Back To Assets" }));

    await user.click(screen.getByRole("button", { name: /Build Now/ }));
    expect(await screen.findByText("LM358DR")).toBeVisible();
    expect(screen.getByText("CAD Ready On Part")).toBeVisible();
    expect(screen.queryByText("ADG714BRUZ-REEL")).toBeNull();
  });

  it("opens on Build Now when no component needs CAD and a catalog build is pending", async () => {
    const response = await mockApi.listParts({});
    mockApi.listParts.mockResolvedValue({ parts: [response.parts[1]!], count: 1 });

    renderPage();

    expect(await screen.findByText("LM358DR")).toBeVisible();
    expect(screen.getByText("CAD Ready On Part")).toBeVisible();
    expect(
      within(screen.getByRole("group", { name: "Asset workflow" }))
        .getByRole("button", { name: /Build Now/ }),
    ).toHaveAttribute("aria-pressed", "true");
    expect(screen.queryByRole("button", { name: "Add Parts" })).toBeNull();
  });

  it("shows a true empty state when neither asset repair nor catalog build is needed", async () => {
    mockApi.listParts.mockResolvedValue({ parts: [], count: 0 });
    mockApi.catalogBuildStatus.mockResolvedValue({
      ...(await mockApi.catalogBuildStatus()),
      state: "current",
      pending_count: 0,
      pending_parts: [],
    });

    renderPage();

    expect(await screen.findByText("All CAD assets and the Altium Designer catalog are current.")).toBeVisible();
    expect(screen.queryByText("Choose Needs Assets or Build Now.")).toBeNull();
    expect(screen.getByRole("button", { name: /Needs Assets/ })).toHaveAttribute("aria-pressed", "false");
    expect(screen.getByRole("button", { name: /Build Now/ })).toHaveAttribute("aria-pressed", "false");
  });

  it("requires confirmation, runs one build, and keeps results with secondary history", async () => {
    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByRole("button", { name: /Build Now/ }));
    const action = screen.getByRole("button", { name: "Build Now" });
    expect(action).toBeEnabled();
    expect(screen.queryByRole("dialog")).toBeNull();

    await user.click(action);
    expect(screen.getByRole("dialog", { name: "Build Altium Designer Catalog" })).toBeVisible();
    expect(screen.getByText(/one coalesced batch/i)).toBeVisible();
    expect(mockApi.catalogBuild).not.toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: "Build Catalog" }));
    expect(mockApi.catalogBuild).toHaveBeenCalledTimes(1);
    expect(await screen.findByRole("status")).toHaveTextContent("1 component current. 0 failed.");
    expect(screen.getByText("Build History")).toBeVisible();
    expect(screen.queryByText("Altium catalog projection is current.")).toBeNull();
    await user.click(screen.getByText("Build History"));
    expect(await screen.findByText(/Altium catalog projection is current/)).toBeVisible();
  });

  it("restores the concise last result while keeping its details secondary", async () => {
    const lastResult = await mockApi.catalogBuild();
    mockApi.catalogBuild.mockClear();
    mockApi.catalogBuildStatus.mockResolvedValue({
      ...(await mockApi.catalogBuildStatus()),
      last_result: lastResult,
      history: [lastResult],
    });
    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByRole("button", { name: /Build Now/ }));
    expect(screen.getByText("1 component current. 0 failed.")).toBeVisible();
    expect(screen.queryByText("Altium catalog projection is current.")).toBeNull();
    expect(mockApi.catalogBuild).not.toHaveBeenCalled();
  });

  it("refetches Assets immediately after provider auto-attachment", async () => {
    const dossier = makeDossier();
    dossier.cadSourceCoverage.rows = [makeProviderRow({
      id: "mouser",
      label: "Mouser",
      url: "https://www.mouser.com/c/?q=ADG714BRUZ-REEL",
      captureAvailable: false,
    })];
    mockApi.partDossier.mockResolvedValue(dossier);
    mockApi.startManualProviderBrowser.mockImplementation(async (input) => ({
      session_id: input.sessionId,
      part_id: input.partId,
      provider_id: input.providerId,
      url: input.url,
      browser_owner_id: input.browserOwnerId,
      state: "ready",
      proposal: null,
      error: "",
      browser_state: null,
      cad_ready: {
        attached: ["altium_symbol", "altium_footprint", "kicad_model"],
        edas: ["altium"],
        landed_files: ["ADG714BRUZ-REEL.zip"],
        part_complete: true,
        provider_id: "mouser",
        remaining_roles: [],
      },
    }));
    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByRole("button", { name: /Needs Assets/ }));
    await user.click(await screen.findByRole("button", { name: "Manage CAD Assets" }));
    const before = {
      dossier: mockApi.partDossier.mock.calls.length,
      parts: mockApi.listParts.mock.calls.length,
      catalog: mockApi.catalogBuildStatus.mock.calls.length,
    };
    await user.click(await screen.findByRole("radio", { name: "Mouser" }));
    expect((await screen.findAllByText("CAD Ready")).length).toBeGreaterThan(0);

    await screen.findByText("ADG714BRUZ-REEL.zip");
    expect(mockApi.partDossier).toHaveBeenCalledTimes(before.dossier + 1);
    expect(mockApi.listParts).toHaveBeenCalledTimes(before.parts + 1);
    expect(mockApi.catalogBuildStatus).toHaveBeenCalledTimes(before.catalog + 1);
  });

  it("refetches Assets immediately after manual provider Apply", async () => {
    const dossier = makeDossier();
    dossier.cadSourceCoverage.rows = [makeProviderRow({
      id: "mouser",
      label: "Mouser",
      url: "https://www.mouser.com/c/?q=ADG714BRUZ-REEL",
      captureAvailable: false,
    })];
    mockApi.partDossier.mockResolvedValue(dossier);
    mockApi.startManualProviderBrowser.mockImplementation(async (input) => ({
      session_id: input.sessionId,
      part_id: input.partId,
      provider_id: input.providerId,
      url: input.url,
      browser_owner_id: input.browserOwnerId,
      state: "active",
      error: "",
      browser_state: null,
      proposal: {
        proposal_token: "proposal-1",
        part_id: input.partId,
        provider: "manual",
        primary_tool: "altium",
        attachments: [{
          role: "Altium Symbol",
          file_name: "ADG714BRUZ-REEL.SchLib",
          target: "Active Altium Symbol",
        }],
        inactive_evidence: [],
        landed_files: ["ADG714BRUZ-REEL.zip", "ADG714BRUZ-REEL.SchLib"],
        remaining_roles: ["Altium Footprint", "3D Model"],
        automatic_apply_ready: false,
      },
    }));
    mockApi.applyPartFiles.mockResolvedValue({
      part_id: "missing",
      selected_files: 1,
      attached: ["altium_symbol"],
      ignored: [],
      remaining: ["footprint", "model"],
      complete: false,
    });
    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByRole("button", { name: /Needs Assets/ }));
    await user.click(await screen.findByRole("button", { name: "Manage CAD Assets" }));
    await user.click(await screen.findByRole("radio", { name: "Mouser" }));
    expect(await screen.findByText("ADG714BRUZ-REEL.zip")).toBeVisible();
    const before = {
      dossier: mockApi.partDossier.mock.calls.length,
      parts: mockApi.listParts.mock.calls.length,
      catalog: mockApi.catalogBuildStatus.mock.calls.length,
    };

    await user.click(screen.getByRole("button", { name: "Apply Attachments" }));

    expect(mockApi.applyPartFiles).toHaveBeenCalledWith({
      partId: "missing",
      proposalToken: "proposal-1",
    });
    await screen.findByText("1 CAD role attached");
    expect(mockApi.partDossier).toHaveBeenCalledTimes(before.dossier + 1);
    expect(mockApi.listParts).toHaveBeenCalledTimes(before.parts + 1);
    expect(mockApi.catalogBuildStatus).toHaveBeenCalledTimes(before.catalog + 1);
  });
});
