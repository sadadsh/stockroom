import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import App from "./App";
import { api } from "./api/client";
import type { PartDetail, PartSummary } from "./api/types";
import { makePartDetail } from "./test/partFixture";
import { makeWorkspace } from "./test/workspaceFixture";
import { RouterProvider } from "./lib/router";
import { AddPartProvider } from "./lib/addPart";
import { CaptureProvider } from "./lib/capture";
import { ToastProvider } from "./lib/toast";
import { ThemeProvider } from "./lib/theme";

vi.mock("./api/client", async (importActual) => {
  const actual = await importActual<typeof import("./api/client")>();
  return {
    ...actual,
    api: {
      listParts: vi.fn(),
      facets: vi.fn(),
      partDetail: vi.fn(),
      partWorkspace: vi.fn(),
      getStmStatus: vi.fn(),
      getStmMcus: vi.fn(),
      getStmFamilies: vi.fn(),
      buildStmIndex: vi.fn(),
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

describe("App shell", () => {
  it("renders the rail and the Components page for the default route", async () => {
    mockApi.listParts.mockResolvedValue({ parts: [SUMMARY], count: 1 });
    mockApi.facets.mockResolvedValue({
      by_category: { ICs: 1 },
      by_manufacturer: {},
      complete: 1,
      incomplete: 0,
    });
    mockApi.partDetail.mockResolvedValue(DETAIL);
    mockApi.partWorkspace.mockResolvedValue(makeWorkspace());

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
    expect(screen.getByText("Stockroom")).toBeInTheDocument();
    // findAllByText: one component now reads its name in three honest places - the picker row,
    // its open tab, and the workspace identity header.
    expect((await screen.findAllByText("LM358")).length).toBeGreaterThan(0);
    // The opened component states what the part IS in its Overview description region.
    expect((await screen.findAllByText("Dual Operational Amplifier")).length).toBeGreaterThan(0);
    // the default route renders the Components flagship: no page-level tab strip
    // (BOM Coverage / Duplicates / Doctor all moved out). The tabs now are the open
    // components themselves plus the opened component's four information tabs.
    expect(
      screen.queryByRole("tab", { name: /BOM Coverage|Duplicates|Doctor/ }),
    ).toBeNull();
    expect(screen.getByRole("tab", { name: "Overview" })).toBeInTheDocument();
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

  it("renders the STM Viewer page for the stm route", async () => {
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

    expect(screen.getByRole("heading", { name: "STM Viewer" })).toBeInTheDocument();
    expect(await screen.findByText("STM32F407VETx")).toBeInTheDocument();
  });
});
