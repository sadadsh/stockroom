import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import App from "./App";
import { api } from "./api/client";
import type { PartDetail, PartSummary } from "./api/types";
import { RouterProvider } from "./lib/router";
import { AddPartProvider } from "./lib/addPart";
import { CaptureProvider } from "./lib/capture";
import { ToastProvider } from "./lib/toast";
import { ThemeProvider } from "./lib/theme";

vi.mock("./api/client", async (importActual) => {
  const actual = await importActual<typeof import("./api/client")>();
  return {
    ...actual,
    api: { listParts: vi.fn(), facets: vi.fn(), partDetail: vi.fn() },
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
};

const DETAIL: PartDetail = {
  id: "lm358",
  display_name: "LM358",
  category: "ICs",
  description: "Dual Operational Amplifier",
  tags: [],
  mpn: "LM358DR",
  manufacturer: "Texas Instruments",
  datasheet: null,
  purchase: [],
  symbol: null,
  footprint: null,
  model: null,
  provenance: null,
  hashes: null,
  enrichment: {},
  specs: {},
};

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
    expect(await screen.findByText("LM358")).toBeInTheDocument();
    expect(await screen.findByText("Dual Operational Amplifier")).toBeInTheDocument();
    // the default route renders the Components flagship: no page-level tab strip
    // (BOM Coverage / Duplicates / Doctor all moved out). The only tabs now are the
    // selected part's workbench (Specs / Sourcing / History / ...).
    expect(
      screen.queryByRole("tab", { name: /BOM Coverage|Duplicates|Doctor/ }),
    ).toBeNull();
    expect(screen.getByRole("tab", { name: "Details" })).toBeInTheDocument();
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
    await user.click(screen.getByRole("button", { name: "Add Parts" }));

    // It opens the Add A Part modal (an in-window dialog) with the flow's own
    // control and a close, over the current page.
    const dialog = await screen.findByRole("dialog", { name: "Add a Part" });
    expect(
      within(dialog).getByLabelText("Product link or part number"),
    ).toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: "Close" })).toBeInTheDocument();
  });
});
