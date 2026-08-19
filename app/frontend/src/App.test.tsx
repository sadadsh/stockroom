import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useEffect } from "react";
import App from "./App";
import { api, type LandPattern, type SymbolGeometry } from "./api/client";
import type { PartDetail, PartSummary } from "./api/types";
import type { PartShell } from "./api/types";
import { makePartDetail } from "./test/partFixture";
import { makeDossier } from "./test/dossierFixture";
import { RouterProvider } from "./lib/router";
import { AddPartProvider } from "./lib/addPart";
import { CaptureProvider } from "./lib/capture";
import { ToastProvider } from "./lib/toast";
import { ThemeProvider } from "./lib/theme";
import { DesignStudioProvider, useDesignStudio } from "./design-studio/DesignStudioProvider";
import { GUIDED_SETUP_CHOOSE_CAD, guidedSetupAt } from "./design-studio/fixtures/onboardingFixtures";
import { ONBOARDING_READY } from "./design-studio/fixtures/componentFixtures";

vi.mock("./api/client", async (importActual) => {
  const actual = await importActual<typeof import("./api/client")>();
  return {
    ...actual,
    api: {
      ...actual.api,
      getOnboarding: vi.fn(),
      listParts: vi.fn(),
      facets: vi.fn(),
      partDetail: vi.fn(),
      partDossier: vi.fn(),
      getStmStatus: vi.fn(),
      getStmMcus: vi.fn(),
      getStmFamilies: vi.fn(),
      buildStmIndex: vi.fn(),
      landPattern: vi.fn().mockResolvedValue({ pads: [], graphics: [] }),
      symbolGeometry: vi.fn().mockResolvedValue({ pins: [] }),
      partShell: vi.fn().mockResolvedValue({ supported: false, component_directory: false, export_formats: [], eda_applications: [] }),
    },
  };
});

const mockApi = vi.mocked(api);

const SUMMARY: PartSummary = {
  id: "lm358",
  display_name: "LM358",
  category: "ICs",
  mpn: "LM358DR",
  manufacturer: "Texas Instruments",
  is_complete: true,
  missing: [],
  eda_readiness: {},
};

const DETAIL: PartDetail = makePartDetail({
  id: "lm358",
  mpn: "LM358DR",
  manufacturer: "Texas Instruments",
  derived: { display_name: "LM358", description: "Dual Operational Amplifier" },
});

const EMPTY_LAND_PATTERN: LandPattern = {
  units: "mm",
  pads: [],
  graphics: [],
  model_placement: null,
};

const EMPTY_SYMBOL_GEOMETRY: SymbolGeometry = {
  units: "mm",
  name: "LM358",
  namesHidden: false,
  numbersHidden: false,
  pins: [],
  graphics: [],
  bounds: null,
};

const UNSUPPORTED_PART_SHELL: PartShell = {
  supported: false,
  component_directory: false,
  export_formats: [],
  eda_applications: [],
};

function configureWorkspaceFixtures() {
  mockApi.partDetail.mockResolvedValue(DETAIL);
  mockApi.partDossier.mockResolvedValue(makeDossier());
  mockApi.landPattern.mockResolvedValue(EMPTY_LAND_PATTERN);
  mockApi.symbolGeometry.mockResolvedValue(EMPTY_SYMBOL_GEOMETRY);
  mockApi.partShell.mockResolvedValue(UNSUPPORTED_PART_SHELL);
}

function ScenarioProbe({ expose }: { expose: (activate: (id: string) => Promise<void>) => void }) {
  const studio = useDesignStudio();
  useEffect(() => expose(studio.activateScenario), [expose, studio.activateScenario]);
  return null;
}

describe("App shell", () => {
  beforeEach(() => {
    mockApi.getOnboarding.mockResolvedValue(ONBOARDING_READY);
    mockApi.getStmFamilies.mockResolvedValue({ families: [] });
  });

  it("gates an existing installation until Primary CAD Tool confirmation", async () => {
    vi.spyOn(api, "getOnboarding").mockResolvedValue({
      primary_eda: null,
      primary_eda_pending: null,
      primary_eda_confirmation_required: true,
      recommended_primary_eda: "kicad",
      primary_eda_requirements: [],
      retained_optional_eda: ["kicad", "altium"],
      eda_tools: [
        {
          key: "kicad",
          label: "KiCad",
          detected: true,
          selected: false,
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
      ],
      onboarded: true,
      first_run: false,
      libraries_root: "C:/Stockroom",
      profiles: ["Stockroom"],
      under_git: true,
      default_dir: "C:/Stockroom",
      libraries: [],
      guided_setup: GUIDED_SETUP_CHOOSE_CAD,
    });
    try {
      const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
      render(
        <QueryClientProvider client={qc}>
          <ThemeProvider>
            <ToastProvider>
              <RouterProvider initial="components">
                <CaptureProvider>
                  <AddPartProvider>
                    <App />
                  </AddPartProvider>
                </CaptureProvider>
              </RouterProvider>
            </ToastProvider>
          </ThemeProvider>
        </QueryClientProvider>,
      );

      expect(
        await screen.findByRole("heading", { name: "Choose CAD Tool" }),
      ).toBeInTheDocument();
      expect(screen.queryByText("Stockroom", { selector: "span" })).not.toBeInTheDocument();
    } finally {
      mockApi.getOnboarding.mockResolvedValue(ONBOARDING_READY);
    }
  });

  it("shows the Ready proof until the person completes Guided Setup", async () => {
    vi.spyOn(api, "getOnboarding").mockResolvedValue({
      ...ONBOARDING_READY,
      onboarded: false,
      first_run: true,
    });
    mockApi.listParts.mockResolvedValue({ parts: [], count: 0 });
    mockApi.facets.mockResolvedValue({ by_category: {}, by_manufacturer: {}, complete: 0, incomplete: 0 });
    try {
      const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
      render(
        <QueryClientProvider client={qc}>
          <ThemeProvider>
            <ToastProvider>
              <RouterProvider initial="components">
                <CaptureProvider>
                  <AddPartProvider><App /></AddPartProvider>
                </CaptureProvider>
              </RouterProvider>
            </ToastProvider>
          </ThemeProvider>
        </QueryClientProvider>,
      );
      expect(await screen.findByRole("heading", { name: "Ready" })).toBeInTheDocument();
      expect(screen.getByRole("button", { name: "Open Components" })).toBeInTheDocument();
      expect(screen.queryByText("Stockroom", { selector: "span" })).not.toBeInTheDocument();
    } finally {
      mockApi.getOnboarding.mockResolvedValue(ONBOARDING_READY);
    }
  });

  it("renders the rail and the Components page for the default route", async () => {
    mockApi.listParts.mockResolvedValue({ parts: [SUMMARY], count: 1 });
    mockApi.facets.mockResolvedValue({
      by_category: { ICs: 1 },
      by_manufacturer: {},
      complete: 1,
      incomplete: 0,
    });
    configureWorkspaceFixtures();

    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={qc}>
        <ThemeProvider>
          <ToastProvider>
            <RouterProvider initial="components">
              <CaptureProvider>
                <AddPartProvider>
                  <App />
                </AddPartProvider>
              </CaptureProvider>
            </RouterProvider>
          </ToastProvider>
        </ThemeProvider>
      </QueryClientProvider>,
    );

    // The rail brand and a live part both render through the shell.
    expect(await screen.findByText("Stockroom")).toBeInTheDocument();
    // findAllByText: one component now reads its name in three honest places - the picker row,
    // its open tab, and the workspace identity header.
    expect((await screen.findAllByText("LM358")).length).toBeGreaterThan(0);
    // The opened component states what the part IS on its identity line.
    expect((await screen.findAllByText(/Dual Operational Amplifier/)).length).toBeGreaterThan(0);
    // Components inspects CAD evidence; acquisition is handed to the Assets route.
    expect(screen.queryAllByRole("tab")).toHaveLength(0);
    expect(screen.getByRole("button", { name: "Manage CAD Assets" })).toBeVisible();
  });

  it("reaches Add Parts as a full-screen wizard from the Parts toolbar", async () => {
    mockApi.listParts.mockResolvedValue({ parts: [], count: 0 });
    mockApi.facets.mockResolvedValue({
      by_category: {},
      by_manufacturer: {},
      complete: 0,
      incomplete: 0,
    });

    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={qc}>
        <ThemeProvider>
          <ToastProvider>
            <RouterProvider initial="components">
              <CaptureProvider>
                <AddPartProvider>
                  <App />
                </AddPartProvider>
              </CaptureProvider>
            </RouterProvider>
          </ToastProvider>
        </ThemeProvider>
      </QueryClientProvider>,
    );
    const user = userEvent.setup();

    // Add Parts is a primary button on the Parts page now, not a tab.
    expect(screen.queryByRole("tab", { name: "Add Parts" })).toBeNull();
    // Wait for the empty-library query to settle. The page deliberately replaces
    // its transient loading workstation with one coherent intake state.
    await screen.findByText("No Components Yet");
    await user.click(screen.getByRole("button", { name: "Add Parts" }));

    // It opens the Add A Part modal (an in-window dialog) with the flow's own
    // control and a close, over the current page.
    const dialog = await screen.findByRole("dialog", { name: "Add a Part" });
    expect(
      within(dialog).getByLabelText("Product link or part number"),
    ).toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: "Close" })).toBeInTheDocument();
  });

  it("renders the Tools page for the stm route", async () => {
    window.history.replaceState({}, "", "/#route=stm");
    mockApi.getStmStatus.mockResolvedValue({
      built: true,
      building: false,
      source_path: "/cubemx/mcu",
      source_present: true,
      all_families: true,
      device_xml_count: 3,
      family_count: 2,
      families: ["STM32F4"],
      mcu_count: 3,
      classifier_rev: 1,
      af_schema_rev: 1,
      geometry_rev: 1,
      source_sha256: "abc",
      built_at: "2026-07-23T00:00:00Z",
    });
    mockApi.getStmMcus.mockResolvedValue({
      mcus: [
        {
          part: "STM32F407V(E-G)Tx",
          mpn_example: "STM32F407VETx",
          series: "STM32F4",
          line: "STM32F407",
          core: "Cortex-M4",
          package: "LQFP100",
          pin_count: 100,
          io_count: 82,
          flash_kb: 512,
          ram_kb: 192,
          max_freq_mhz: 168,
          vdd_min: 1.8,
          vdd_max: 3.6,
          temp_min_c: -40,
          temp_max_c: 85,
          peripherals: {},
        },
      ],
      count: 1,
      facets: { family: {}, core: {}, package: {}, series: {} },
    });

    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={qc}>
        <ThemeProvider>
          <ToastProvider>
            <RouterProvider initial="stm">
              <CaptureProvider>
                <AddPartProvider>
                  <App />
                </AddPartProvider>
              </CaptureProvider>
            </RouterProvider>
          </ToastProvider>
        </ThemeProvider>
      </QueryClientProvider>,
    );

    expect(await screen.findByRole("heading", { name: "Tools" })).toBeInTheDocument();
    expect(await screen.findByText("STM32F407VETx")).toBeInTheDocument();
  });

  it("mounts every bootstrap scenario through existing production components", async () => {
    mockApi.listParts.mockResolvedValue({ parts: [SUMMARY], count: 1 });
    mockApi.facets.mockResolvedValue({
      by_category: { ICs: 1 },
      by_manufacturer: {},
      complete: 1,
      incomplete: 0,
    });
    configureWorkspaceFixtures();
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({
        primary_eda: "kicad",
        primary_eda_pending: null,
        primary_eda_confirmation_required: false,
        recommended_primary_eda: "kicad",
        primary_eda_requirements: ["symbol", "footprint", "model"],
        retained_optional_eda: ["altium"],
        eda_tools: [],
        onboarded: true,
        first_run: false,
        libraries: [],
        guided_setup: ONBOARDING_READY.guided_setup,
      }),
    });
    vi.stubGlobal("fetch", fetchMock);
    let activateScenario: ((id: string) => Promise<void>) | undefined;
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={qc}>
        <ThemeProvider>
          <DesignStudioProvider>
            <ToastProvider>
              <RouterProvider initial="components">
                <CaptureProvider>
                  <AddPartProvider>
                    <ScenarioProbe expose={(activate) => { activateScenario = activate; }} />
                    <App />
                  </AddPartProvider>
                </CaptureProvider>
              </RouterProvider>
            </ToastProvider>
          </DesignStudioProvider>
        </ThemeProvider>
      </QueryClientProvider>,
    );

    await waitFor(() => expect(activateScenario).toBeDefined());
    async function activate(id: string) {
      fetchMock.mockClear();
      await act(async () => activateScenario?.(id));
      if (id.startsWith("global.onboarding.")) {
        qc.setQueryData(["onboarding"], {
          ...ONBOARDING_READY,
          onboarded: false,
          first_run: true,
          guided_setup: guidedSetupAt("catalog_repository", {
            ready: false,
            repository_ready: false,
            repository: null,
          }),
        });
      }
    }

    await activate("global.onboarding.open");
    expect(await screen.findByRole("heading", { name: "Catalog Repository" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Connect Existing" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.queryByLabelText(/path|url|token/i)).not.toBeInTheDocument();
    expect(document.querySelector('[data-dev-id="onboarding.gate"]')).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();

    await activate("global.about.open");
    expect(await screen.findByRole("heading", { name: "About Stockroom" })).toBeInTheDocument();
    expect(document.querySelector('[data-dev-id="settings.about"]')).toBeInTheDocument();

    await activate("global.update.available");
    expect((await screen.findAllByText("Update Available")).length).toBeGreaterThan(0);
    expect(document.querySelector('[data-dev-id="rail.update"]')).toBeInTheDocument();

    await activate("global.search.initial");
    expect(await screen.findByLabelText("Search components")).toBeInTheDocument();
    expect(document.querySelector('[data-dev-id="search.query"]')).toBeInTheDocument();

    await activate("global.service-error");
    expect(await screen.findByText("Stockroom is not answering on this machine.")).toBeInTheDocument();
    expect(document.querySelector('[data-dev-id="components.list-unreachable"]')).toBeInTheDocument();

    await activate("global.real-data");
    expect(document.querySelector('[data-dev-id="shell.root"]')).toBeInTheDocument();
  }, 20_000);
});
