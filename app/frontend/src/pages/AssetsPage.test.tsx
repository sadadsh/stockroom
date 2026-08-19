import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { api } from "../api/client";
import { SETTINGS_ONBOARDING } from "../design-studio/fixtures/settingsFixtures";
import { AddPartProvider } from "../lib/addPart";
import { RouterProvider } from "../lib/router";
import { makeDossier } from "../test/dossierFixture";
import { AssetsPage } from "./AssetsPage";

vi.mock("../api/client", async (importActual) => {
  const actual = await importActual<typeof import("../api/client")>();
  return { ...actual, api: { ...actual.api, getOnboarding: vi.fn(), listParts: vi.fn(), partDossier: vi.fn() } };
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
});

describe("AssetsPage", () => {
  it("opens neutrally and separates missing assets from build-ready components", async () => {
    const user = userEvent.setup();
    renderPage();

    expect(await screen.findByText("Choose Needs Assets or Build Now.")).toBeVisible();
    const addParts = screen.getByRole("button", { name: "Add Parts" });
    expect(addParts).toHaveClass("w-full", "!h-12");
    expect(screen.getByRole("heading", { name: "Assets" }).parentElement).not.toContainElement(addParts);
    expect(screen.queryByText("ADG714BRUZ-REEL")).toBeNull();

    await user.click(screen.getByRole("button", { name: /Needs Assets/ }));
    expect(await screen.findByText("ADG714BRUZ-REEL")).toBeVisible();
    expect(screen.getByText("Symbol, Footprint")).toBeVisible();
    expect(screen.queryByText("symbol, footprint")).toBeNull();
    expect(screen.queryByText("LM358DR")).toBeNull();

    await user.click(screen.getByRole("button", { name: "Manage CAD Assets" }));
    expect(await screen.findByRole("button", { name: "Back To Assets" })).toBeVisible();
    expect(screen.getByText(/Downloads follow Altium Designer/)).toBeVisible();
    await user.click(screen.getByRole("button", { name: "Back To Assets" }));

    await user.click(screen.getByRole("button", { name: /Build Now/ }));
    expect(await screen.findByText("LM358DR")).toBeVisible();
    expect(screen.queryByText("ADG714BRUZ-REEL")).toBeNull();
  });
});
