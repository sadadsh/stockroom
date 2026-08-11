import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import App from "../../App";
import { AddPartProvider } from "../../lib/addPart";
import { CaptureProvider } from "../../lib/capture";
import { RouterProvider } from "../../lib/router";
import { ThemeProvider } from "../../lib/theme";
import { ToastProvider } from "../../lib/toast";
import { DesignStudioProvider } from "../../design-studio/DesignStudioProvider";
import { DesignStudioShell } from "./DesignStudioShell";

vi.mock("../../api/client", async (importActual) => {
  const actual = await importActual<typeof import("../../api/client")>();
  return {
    ...actual,
    api: {
      ...actual.api,
      listParts: vi.fn().mockResolvedValue({ parts: [], count: 0 }),
      facets: vi.fn().mockResolvedValue({
        by_category: {},
        by_manufacturer: {},
        complete: 0,
        incomplete: 0,
      }),
      getOnboarding: vi.fn().mockResolvedValue({
        onboarded: true,
        first_run: false,
        libraries_root: "C:\\Stockroom",
        profiles: [],
        under_git: true,
        default_dir: "C:\\Stockroom\\Components",
        libraries: [],
      }),
      designStudioGet: vi.fn().mockRejectedValue(new Error("No personal design fixture")),
      devStatus: vi.fn().mockResolvedValue({
        available: false,
        can_publish: false,
        publish_blocker: "Source promotion is unavailable.",
      }),
      getStmStatus: vi.fn().mockResolvedValue({
        built: true,
        building: false,
        source_path: "C:\\ST-MCU-FINDER",
        source_present: true,
        all_families: true,
        device_xml_count: 1,
        family_count: 1,
        families: ["STM32F4"],
        mcu_count: 1,
        classifier_rev: 1,
        af_schema_rev: 1,
        geometry_rev: 1,
        source_sha256: "a".repeat(64),
        built_at: "2026-08-11T00:00:00Z",
      }),
      getStmMcus: vi.fn().mockResolvedValue({
        mcus: [{
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
          peripherals: { USART: 4, SPI: 3 },
        }],
        count: 1,
        facets: {
          family: { STM32F4: 1 },
          core: { "Cortex-M4": 1 },
          package: { LQFP100: 1 },
          series: { STM32F4: 1 },
        },
      }),
      getStmFamilies: vi.fn().mockResolvedValue({
        families: [{
          family: "STM32F4",
          lines: ["STM32F407"],
          mcu_count: 1,
          packages: ["LQFP100"],
        }],
      }),
    },
  };
});

function Providers({ children }: { children: ReactNode }) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return (
    <QueryClientProvider client={queryClient}>
      <ThemeProvider>
        <DesignStudioProvider>
          <ToastProvider>
            <RouterProvider initial="components">
              <CaptureProvider>
                <AddPartProvider>{children}</AddPartProvider>
              </CaptureProvider>
            </RouterProvider>
          </ToastProvider>
        </DesignStudioProvider>
      </ThemeProvider>
    </QueryClientProvider>
  );
}

function renderApp() {
  return render(
    <Providers>
      <DesignStudioShell>
        <App />
      </DesignStudioShell>
    </Providers>,
  );
}

async function renderStudio() {
  const result = renderApp();
  const entry = screen.getByRole("button", { name: "Design Studio" });
  await userEvent.setup().click(entry);
  await screen.findByRole("region", { name: "Stockroom Preview" });
  return { ...result, entry };
}

beforeEach(() => {
  window.history.replaceState({}, "", "/#route=components");
  window.__STOCKROOM_UI__ = { rail_collapsed: false };
  localStorage.clear();
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ schema_version: 1, document: null, revision: 0 }),
    }),
  );
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("DesignStudioShell", () => {
  it("opens from the visible rail entry and starts with the simple screen-first workflow", async () => {
    renderApp();
    await userEvent.setup().click(screen.getByRole("button", { name: "Design Studio" }));

    expect(screen.getByRole("complementary", { name: "Screens And States" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Browse" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(
      screen
        .getByRole("region", { name: "Stockroom Preview" })
        .querySelector('[data-dev-id="shell.root"]'),
    ).toBeVisible();
  });

  it("previews the exact desktop presets and an explicit custom width", async () => {
    await renderStudio();
    const preview = screen.getByRole("region", { name: "Stockroom Preview" });
    const frame = preview.firstElementChild as HTMLElement;
    const viewport = screen.getByLabelText("Viewport");

    expect(viewport).toHaveValue("desktop-1366");
    expect(frame.style.width).toBe("1366px");
    await userEvent.setup().selectOptions(viewport, "desktop-1920");
    expect(frame.style.width).toBe("1920px");
    await userEvent.setup().selectOptions(viewport, "custom");
    const custom = screen.getByLabelText("Custom Viewport Width");
    fireEvent.change(custom, { target: { value: "1472" } });
    expect(frame.style.width).toBe("1472px");
    fireEvent.change(custom, { target: { value: "" } });
    expect(frame.style.width).toBe("1472px");
  });

  it("lists only rendered stable targets and exposes their hierarchy without index keys", async () => {
    await renderStudio();
    const sidebar = screen.getByRole("complementary", { name: "Screens And States" });
    const rail = within(sidebar).getByRole("button", { name: "Navigation rail" });
    expect(rail).toHaveAttribute("data-target-key", "dev:rail.root");
    expect(within(sidebar).queryByRole("button", { name: "About dialog" })).toBeNull();

    await userEvent.setup().click(within(sidebar).getByRole("button", { name: "Structure" }));
    expect(rail.getAttribute("data-target-depth")).toMatch(/^\d+$/);
    expect(sidebar.innerHTML).not.toContain("data-target-index");
  });

  it("collapses every editor region without hiding Stockroom chrome", async () => {
    const { container } = await renderStudio();
    await userEvent.setup().click(
      within(screen.getByLabelText("Studio Mode")).getByRole("button", { name: "Inspect" }),
    );
    await userEvent.setup().click(screen.getByRole("button", { name: "Presentation Mode" }));

    expect(screen.queryByRole("complementary", { name: "Screens And States" })).not.toBeInTheDocument();
    expect(screen.queryByRole("complementary", { name: "Inspector" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Browse" })).toHaveAttribute("aria-pressed", "true");
    expect(container.querySelector('[data-dev-id="rail.root"]')).toBeVisible();
  });

  it("uses Escape to return to Browse before closing and restores focus to the rail entry", async () => {
    const { entry } = await renderStudio();
    await userEvent.setup().click(
      within(screen.getByLabelText("Studio Mode")).getByRole("button", { name: "Inspect" }),
    );

    fireEvent.keyDown(window, { key: "Escape" });
    expect(screen.getByRole("button", { name: "Browse" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("region", { name: "Stockroom Preview" })).toBeVisible();

    fireEvent.keyDown(window, { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("region", { name: "Stockroom Preview" })).toBeNull());
    expect(entry).toHaveFocus();
  });

  it("shares one mode authority with the retained Dev panel controls", async () => {
    const { entry } = await renderStudio();
    const studioMode = within(screen.getByLabelText("Studio Mode"));
    const devPanel = within(screen.getByRole("complementary", { name: "Dev mode" }));

    await userEvent.setup().click(devPanel.getByRole("button", { name: "Inspect" }));
    expect(studioMode.getByRole("button", { name: "Inspect" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );

    await userEvent.setup().click(devPanel.getByRole("button", { name: "Arrange" }));
    expect(studioMode.getByRole("button", { name: "Inspect" })).toHaveAttribute(
      "aria-pressed",
      "false",
    );
    expect(studioMode.getByRole("button", { name: "Arrange" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );

    fireEvent.keyDown(window, { key: "Escape" });
    expect(studioMode.getByRole("button", { name: "Browse" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(screen.getByRole("region", { name: "Stockroom Preview" })).toBeVisible();

    fireEvent.keyDown(window, { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("region", { name: "Stockroom Preview" })).toBeNull());
    expect(entry).toHaveFocus();
  });

  it("lets an open production modal own Escape before Design Studio", async () => {
    await renderStudio();
    const aboutButton = screen.getByRole("button", { name: "About" });
    await userEvent.setup().click(aboutButton);
    expect(await screen.findByRole("dialog", { name: "About Stockroom" })).toBeVisible();

    fireEvent.keyDown(window, { key: "Escape" });

    await waitFor(() =>
      expect(screen.queryByRole("dialog", { name: "About Stockroom" })).not.toBeInTheDocument(),
    );
    expect(screen.getByRole("region", { name: "Stockroom Preview" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Browse" })).toHaveAttribute("aria-pressed", "true");
    await waitFor(() => expect(aboutButton).toHaveFocus());
  });

  it("lets the real SpecMatrix Columns popover own Escape before Design Studio", async () => {
    const { entry } = await renderStudio();
    await userEvent.setup().click(screen.getByRole("button", { name: "STM Viewer" }));
    const columnsButton = await screen.findByRole("button", { name: "Columns" });
    await userEvent.setup().click(columnsButton);
    expect(screen.getByTestId("column-picker")).toBeVisible();

    await userEvent.setup().keyboard("{Escape}");

    await waitFor(() => expect(screen.queryByTestId("column-picker")).not.toBeInTheDocument());
    expect(screen.getByRole("region", { name: "Stockroom Preview" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Browse" })).toHaveAttribute("aria-pressed", "true");

    await userEvent.setup().keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("region", { name: "Stockroom Preview" })).toBeNull());
    expect(entry).toHaveFocus();
  });

  it("gives panel resizers named keyboard controls", async () => {
    await renderStudio();
    const resizer = screen.getByRole("separator", { name: "Resize Screens And States Panel" });
    const before = screen.getByRole("complementary", { name: "Screens And States" }).getAttribute("style");

    fireEvent.keyDown(resizer, { key: "ArrowRight" });

    expect(screen.getByRole("complementary", { name: "Screens And States" }).getAttribute("style")).not.toBe(before);
  });

  it("keeps a failed fixture-preview panel preference dirty and flushes it in Real Data", async () => {
    await renderStudio();
    await userEvent.setup().click(screen.getByRole("button", { name: /^Onboarding Open/ }));
    const resizer = screen.getByRole("separator", { name: "Resize Screens And States Panel" });
    const fetchMock = vi.mocked(fetch);
    fetchMock.mockClear();

    fireEvent.keyDown(resizer, { key: "ArrowRight" });
    await waitFor(() =>
      expect(window.__STOCKROOM_UI__?.design_studio_left_width).toBeGreaterThan(0),
    );
    const queuedWidth = window.__STOCKROOM_UI__?.design_studio_left_width;
    expect(
      fetchMock.mock.calls.filter(
        ([input, init]) => String(input).includes("/api/settings") && init?.method === "PATCH",
      ),
    ).toHaveLength(0);

    await userEvent.setup().click(screen.getByRole("button", { name: "Real Data" }));
    await waitFor(() =>
      expect(
        fetchMock.mock.calls.filter(
          ([input, init]) => String(input).includes("/api/settings") && init?.method === "PATCH",
        ),
      ).toHaveLength(1),
    );
    const settingsCall = fetchMock.mock.calls.find(
      ([input, init]) => String(input).includes("/api/settings") && init?.method === "PATCH",
    );
    expect(settingsCall?.[1]?.body).toBe(
      JSON.stringify({ ui: { design_studio_left_width: queuedWidth } }),
    );
  });
});
