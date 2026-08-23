import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import App from "../../App";
import { AddPartProvider } from "../../lib/addPart";
import { CaptureProvider } from "../../lib/capture";
import { RouterProvider } from "../../lib/router";
import { ThemeProvider } from "../../lib/theme";
import { ToastProvider } from "../../lib/toast";
import { DesignStudioProvider, useDesignStudio } from "../../design-studio/DesignStudioProvider";
import { useDevMode } from "../../lib/devMode";
import {
  DEV_MODE_HISTORY_GESTURE_END_EVENT,
  DEV_MODE_HISTORY_GESTURE_START_EVENT,
} from "../../lib/devModeHistory";
import { DevInspector } from "../DevInspector";
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
        primary_eda: "kicad",
        primary_eda_pending: null,
        primary_eda_confirmation_required: false,
        recommended_primary_eda: "kicad",
        primary_eda_requirements: ["symbol", "footprint", "model"],
        retained_optional_eda: ["altium"],
        eda_tools: [],
        onboarded: true,
        first_run: false,
        libraries_root: "C:\\Stockroom",
        profiles: [],
        under_git: true,
        default_dir: "C:\\Stockroom\\Components",
        libraries: [],
        guided_setup: {
          schema: 1,
          step: "ready",
          steps: ["choose_cad_tool", "catalog_repository", "connect_the_tool"],
          ready: true,
          repository_ready: true,
          repository: { owner: "engineer", name: "stockroom-catalog", url: "https://github.com/engineer/stockroom-catalog.git" },
          github: { available: true, version: "2.80.0", authenticated: true, online: true, viewer: { login: "engineer", name: null }, owners: [{ login: "engineer", kind: "personal" }] },
          tool_connection: { tool: "kicad", installed: true, connected: true, restart_required: false, detail: "KiCad is connected." },
          source_data: { decided: true, skipped: true, mouser_connected: false, digikey_connected: false },
        },
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

function InteractionProduct({ onAction }: { onAction: () => void }) {
  const studio = useDesignStudio();
  const dev = useDevMode();
  return (
    <div data-dev-id="interaction.root">
      <button type="button" data-design-studio-entry onClick={studio.open}>Open Design Studio</button>
      <button type="button" data-dev-id="interaction.action" onClick={onAction}>Product Action</button>
      <output data-testid="interaction-selection">{dev.selectedDevId ?? "none"}</output>
    </div>
  );
}

function PersistenceProduct() {
  const studio = useDesignStudio();
  const dev = useDevMode();
  return (
    <div data-dev-id="shell.root">
      <button type="button" data-design-studio-entry onClick={studio.open}>Open Persistence Studio</button>
      <button type="button" onClick={() => dev.setCopy("rail.about", "Unsaved Shell Edit")}>Make Draft Edit</button>
    </div>
  );
}

function DuplicateLayersProduct() {
  const studio = useDesignStudio();
  const dev = useDevMode();
  return (
    <main data-dev-id="shell.root">
      <button type="button" data-design-studio-entry onClick={studio.open}>Open Duplicate Studio</button>
      <section data-dev-id="rail.root">
        <button type="button" data-dev-id="rail.nav-settings" data-testid="duplicate-first">First Settings</button>
      </section>
      <section data-dev-id="settings.root">
        <button type="button" data-dev-id="rail.nav-settings" data-testid="duplicate-second">Second Settings</button>
      </section>
      <output data-testid="duplicate-selection">
        {dev.selectedTarget?.element.getAttribute("data-testid") ?? "none"}
      </output>
    </main>
  );
}

function DeterministicCrashProduct() {
  const studio = useDesignStudio();
  const dev = useDevMode();
  if (dev.draft.elements["crash.preview"]?.display === "none") {
    throw new Error("deterministic design draft crash");
  }
  return (
    <div>
      <button type="button" data-design-studio-entry onClick={studio.open}>Open Crash Studio</button>
      <button
        type="button"
        onClick={() => {
          window.dispatchEvent(new Event(DEV_MODE_HISTORY_GESTURE_START_EVENT));
          dev.setCopy("unrelated.copy", "Preserve Me");
          dev.setElementProp("unrelated.target", "color", "#123456");
        }}
      >
        Prepare Unrelated Design
      </button>
      <button type="button" onClick={() => dev.setElementProp("crash.preview", "display", "none")}>Arm Deterministic Crash</button>
      <output data-testid="crash-draft">{JSON.stringify(dev.draft)}</output>
      <output data-testid="crash-can-undo">{String(dev.canUndo)}</output>
    </div>
  );
}

function ScenarioCrashProduct() {
  const studio = useDesignStudio();
  if (studio.activeScenario) throw new Error("deterministic scenario crash");
  return (
    <div>
      <button type="button" data-design-studio-entry onClick={studio.open}>Open Scenario Crash Studio</button>
      <button type="button" onClick={() => void studio.activateScenario("global.onboarding.open")}>Arm Scenario Crash</button>
    </div>
  );
}

function renderInteractionProduct(onAction: () => void) {
  return render(
    <Providers>
      <>
        <DesignStudioShell><InteractionProduct onAction={onAction} /></DesignStudioShell>
        <DevInspector />
      </>
    </Providers>,
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
  const entry = await screen.findByRole("button", { name: "Design Studio" });
  await userEvent.setup().click(entry);
  await screen.findByRole("region", { name: "Stockroom Preview" });
  return { ...result, entry };
}

async function openView() {
  const button = screen.getByRole("button", { name: "View" });
  if (button.getAttribute("aria-expanded") !== "true") await userEvent.setup().click(button);
}

async function openDrawer(name: "Screens" | "Layers") {
  const existing = screen.queryByRole("complementary", { name });
  if (existing) return existing;
  await userEvent.setup().click(screen.getByRole("button", { name }));
  return screen.getByRole("complementary", { name });
}

async function chooseScenario(name: string | RegExp) {
  const drawer = await openDrawer("Screens");
  const search = within(drawer).getByRole("searchbox", { name: "Search Screens And States" });
  await userEvent.setup().clear(search);
  await userEvent.setup().type(search, typeof name === "string" ? name : name.source.replaceAll("^", "").replaceAll("$", ""));
  const match = within(drawer).getAllByRole("button").find((button) => {
    const text = button.textContent ?? "";
    return typeof name === "string" ? text.startsWith(name) : name.test(text);
  });
  expect(match).toBeDefined();
  await userEvent.setup().click(match!);
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
  it("awaits persistence and visibly keeps Design Studio open when Exit cannot save", async () => {
    render(
      <Providers>
        <DesignStudioShell><PersistenceProduct /></DesignStudioShell>
      </Providers>,
    );
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Open Persistence Studio" }));
    await user.click(screen.getByRole("button", { name: "Make Draft Edit" }));
    const fetchMock = vi.mocked(fetch);
    fetchMock.mockImplementation(async (input, init) => {
      if (init?.method === "PUT" && String(input).includes("/api/design-studio/personal")) {
        return {
          ok: false,
          status: 503,
          json: async () => ({ detail: "unavailable" }),
        } as Response;
      }
      return {
        ok: true,
        status: 200,
        json: async () => ({ schema_version: 1, document: null, revision: 0 }),
      } as Response;
    });

    await user.click(screen.getByRole("button", { name: "Exit" }));

    expect(screen.getByRole("region", { name: "Stockroom Preview" })).toBeVisible();
    expect(screen.getByRole("status")).toHaveTextContent("Draft is not saved. Design Studio remains open.");
  });

  it("selects and hides one duplicate occurrence while retaining its exact ghost row", async () => {
    render(
      <Providers>
        <DesignStudioShell><DuplicateLayersProduct /></DesignStudioShell>
      </Providers>,
    );
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Open Duplicate Studio" }));
    const sidebar = await openDrawer("Layers");
    const duplicateRows = within(sidebar).getAllByRole("button", {
      name: /Settings nav item · \d of 2/,
    });

    await user.click(duplicateRows[1]!);
    expect(screen.getByTestId("duplicate-selection")).toHaveTextContent("duplicate-second");
    await user.click(within(sidebar).getByRole("button", { name: "Hide Selected" }));

    expect(screen.getByTestId("duplicate-first")).not.toHaveStyle({ visibility: "hidden" });
    expect(screen.getByTestId("duplicate-second")).toHaveStyle({ visibility: "hidden" });
    expect(within(sidebar).getByRole("button", {
      name: /Settings nav item · 2 of 2 · Hidden/,
    })).toBeVisible();
  });

  it("recovers the last renderable draft without deleting unrelated edits or requiring undo", async () => {
    vi.spyOn(console, "error").mockImplementation(() => undefined);
    const fetchMock = vi.mocked(fetch);
    render(
      <Providers>
        <DesignStudioShell><DeterministicCrashProduct /></DesignStudioShell>
      </Providers>,
    );
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Open Crash Studio" }));
    await user.click(screen.getByRole("button", { name: "Prepare Unrelated Design" }));
    expect(screen.getByTestId("crash-can-undo")).toHaveTextContent("false");
    expect(JSON.parse(screen.getByTestId("crash-draft").textContent ?? "{}")).toMatchObject({
      copy: { "unrelated.copy": "Preserve Me" },
      elements: { "unrelated.target": { color: "#123456" } },
    });
    await user.click(screen.getByRole("button", { name: "Arm Deterministic Crash" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Preview stopped");

    await user.click(screen.getByRole("button", { name: "Recover Preview" }));

    expect(await screen.findByRole("button", { name: "Arm Deterministic Crash" })).toBeVisible();
    expect(JSON.parse(screen.getByTestId("crash-draft").textContent ?? "{}")).toMatchObject({
      copy: { "unrelated.copy": "Preserve Me" },
      elements: { "unrelated.target": { color: "#123456" } },
    });
    expect(JSON.parse(screen.getByTestId("crash-draft").textContent ?? "{}").elements["crash.preview"]).toBeUndefined();
    await waitFor(() => expect(fetchMock.mock.calls.some(
      ([input, init]) => String(input).includes("/api/design-studio/personal") && init?.method === "PUT",
    )).toBe(true));
    const personalWrites = fetchMock.mock.calls.filter(
      ([input, init]) => String(input).includes("/api/design-studio/personal") && init?.method === "PUT",
    );
    const savedBody = String(personalWrites[personalWrites.length - 1]?.[1]?.body);
    expect(savedBody).toContain("Preserve Me");
    expect(savedBody).toContain("unrelated.target");
    expect(savedBody).not.toContain("crash.preview");
    window.dispatchEvent(new Event(DEV_MODE_HISTORY_GESTURE_END_EVENT));
  });

  it("exits a deterministic non-draft scenario crash before remounting", async () => {
    vi.spyOn(console, "error").mockImplementation(() => undefined);
    render(
      <Providers>
        <DesignStudioShell><ScenarioCrashProduct /></DesignStudioShell>
      </Providers>,
    );
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Open Scenario Crash Studio" }));
    await user.click(screen.getByRole("button", { name: "Arm Scenario Crash" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Preview stopped");

    await user.click(screen.getByRole("button", { name: "Recover Preview" }));

    expect(await screen.findByRole("button", { name: "Arm Scenario Crash" })).toBeVisible();
  });

  it("opens canvas-first with Preview active and every drawer closed", async () => {
    renderApp();
    await userEvent.setup().click(await screen.findByRole("button", { name: "Design Studio" }));

    expect(screen.queryByRole("complementary", { name: "Screens" })).not.toBeInTheDocument();
    expect(screen.queryByRole("complementary", { name: "Inspector" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Screens" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Layers" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Preview" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(
      screen
        .getByRole("region", { name: "Stockroom Preview" })
        .querySelector('[data-dev-id="shell.root"]'),
    ).toBeVisible();
    expect(
      screen.getByRole("region", { name: "Stockroom Preview" })
        .querySelector('[data-design-grid-overlay="true"]'),
    ).not.toBeInTheDocument();
    await openView();
    expect(screen.getByLabelText("Zoom")).toHaveValue("0");
  });

  it("names the Screens and Layers drawers with their own truthful icons", async () => {
    renderApp();
    await userEvent.setup().click(await screen.findByRole("button", { name: "Design Studio" }));

    expect(screen.getByRole("button", { name: "Screens" }).querySelector("[data-icon-id]"))
      .toHaveAttribute("data-icon-id", "design.screens");
    expect(screen.getByRole("button", { name: "Layers" }).querySelector("[data-icon-id]"))
      .toHaveAttribute("data-icon-id", "design.layers");
  });

  it("blocks product actions in Edit while preserving selection and Preview interaction", async () => {
    const action = vi.fn();
    renderInteractionProduct(action);
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Open Design Studio" }));
    await user.click(screen.getByRole("button", { name: "Edit" }));

    const productAction = screen.getByRole("button", { name: "Product Action" });
    await user.click(productAction);
    expect(action).not.toHaveBeenCalled();
    expect(screen.getByTestId("interaction-selection")).toHaveTextContent("interaction.action");
    expect(productAction.closest("[data-design-product-root]"))
      .toHaveAttribute("data-product-interaction", "blocked");

    await user.click(screen.getByRole("button", { name: "Preview" }));
    await user.click(productAction);
    expect(action).toHaveBeenCalledOnce();
  });

  it("previews the exact desktop presets and an explicit custom width", async () => {
    await renderStudio();
    await openView();
    const preview = screen.getByRole("region", { name: "Stockroom Preview" });
    const frame = preview.querySelector<HTMLElement>('[data-design-product-root="true"]')!;
    const viewport = screen.getByLabelText("Viewport");

    expect(viewport).toHaveValue("desktop-1366");
    expect(frame.style.width).toBe("1366px");
    await userEvent.setup().selectOptions(viewport, "desktop-1920");
    expect(frame.style.width).toBe("1920px");
    await userEvent.setup().selectOptions(viewport, "custom");
    const custom = screen.getByLabelText("Custom Viewport Width");
    expect(custom).toHaveAttribute("type", "range");
    fireEvent.change(custom, { target: { value: "1472" } });
    expect(frame.style.width).toBe("1472px");
  });

  it("restores the last case, viewport, mode, zoom, grid, snap, and presentation preference", async () => {
    window.__STOCKROOM_UI__ = {
      rail_collapsed: false,
      design_studio_last_scenario: "global.onboarding.open",
      design_studio_viewport: "desktop-1920",
      design_studio_custom_viewport_width: 1777,
      design_studio_mode: "edit",
      design_studio_zoom: 75,
      design_studio_grid: true,
      design_studio_grid_size: 12,
      design_studio_snap: false,
      design_studio_presentation: false,
    };
    await renderStudio();
    await openView();

    await waitFor(() => expect(document.querySelector('[data-scenario-id="global.onboarding.open"]')).toBeInTheDocument());
    expect(screen.getByLabelText("Viewport")).toHaveValue("desktop-1920");
    expect(screen.getByLabelText("Zoom")).toHaveValue("75");
    expect(within(screen.getByLabelText("Studio Mode")).getByRole("button", { name: "Edit" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "Grid" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("slider", { name: "Grid And Snap Size" })).toHaveValue("12");
    expect(screen.getByRole("button", { name: "Snap" })).toHaveAttribute("aria-pressed", "false");
    expect(screen.getByRole("button", { name: "Presentation" })).toHaveAttribute("aria-pressed", "false");
  });

  it("changes the visible and snapping grid from 1 to 64 pixels", async () => {
    await renderStudio();
    await userEvent.setup().click(screen.getByRole("button", { name: "Edit" }));
    await openView();
    const gridSize = screen.getByRole("slider", { name: "Grid And Snap Size" });
    const preview = screen.getByRole("region", { name: "Stockroom Preview" });

    expect(gridSize).toHaveValue("8");
    const grid = screen.getByRole("button", { name: "Grid" });
    expect(grid).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(grid);
    expect(preview).toHaveAttribute("data-grid", "hidden");
    expect(preview.querySelector('[data-design-grid-overlay="true"]')).not.toBeInTheDocument();
    fireEvent.click(grid);
    fireEvent.change(gridSize, { target: { value: "24" } });
    expect(preview).toHaveAttribute("data-grid-size", "24");
    expect(Number.parseFloat(preview.style.getPropertyValue("--design-studio-grid-size"))).toBeGreaterThan(20);
    const overlay = preview.querySelector<HTMLElement>('[data-design-grid-overlay="true"]');
    expect(overlay).toBeInTheDocument();
    expect(overlay?.style.zIndex).toBe("10000");
    expect(Number(overlay?.style.zIndex)).toBeGreaterThan(9999);
    fireEvent.change(gridSize, { target: { value: "100" } });
    expect(gridSize).toHaveValue("64");
  });

  it("fits and visibly frames a wide canvas with keyboard and pointer panning", async () => {
    await renderStudio();
    await openView();
    await userEvent.setup().selectOptions(screen.getByLabelText("Viewport"), "desktop-1920");
    await userEvent.setup().selectOptions(screen.getByLabelText("Zoom"), "0");
    const preview = screen.getByRole("region", { name: "Stockroom Preview" });
    const frame = preview.querySelector<HTMLElement>('[data-design-product-root="true"]')!;

    expect(frame.style.width).toBe("1920px");
    expect(frame.style.transform).toMatch(/^scale\(/);
    expect(screen.getByText("Fit · Drag canvas or press arrow controls to pan")).toBeVisible();

    preview.scrollLeft = 0;
    fireEvent.keyDown(preview, { key: "ArrowRight" });
    expect(preview.scrollLeft).toBe(80);
    const pointer = (type: string, clientX: number) => {
      const event = new Event(type, { bubbles: true });
      Object.defineProperties(event, {
        button: { value: 0 }, clientX: { value: clientX }, clientY: { value: 20 }, pointerId: { value: 1 },
      });
      fireEvent(preview, event);
    };
    pointer("pointerdown", 100);
    pointer("pointermove", 20);
    expect(preview.scrollLeft).toBe(160);

    const frameDown = new Event("pointerdown", { bubbles: true });
    Object.defineProperties(frameDown, {
      button: { value: 0 }, clientX: { value: 100 }, clientY: { value: 20 }, pointerId: { value: 3 },
    });
    fireEvent(frame, frameDown);
    const frameMove = new Event("pointermove", { bubbles: true });
    Object.defineProperties(frameMove, {
      clientX: { value: 20 }, clientY: { value: 20 }, pointerId: { value: 3 },
    });
    fireEvent(preview, frameMove);
    expect(preview.scrollLeft).toBe(240);
  });

  it("recomputes Fit when the preview region changes size", async () => {
    let notifyResize: () => void = () => undefined;
    class ResizeObserverStub {
      constructor(callback: ResizeObserverCallback) {
        notifyResize = () => callback([], this as unknown as ResizeObserver);
      }
      observe() {}
      disconnect() {}
      unobserve() {}
    }
    vi.stubGlobal("ResizeObserver", ResizeObserverStub);
    await renderStudio();
    await openView();
    await userEvent.setup().selectOptions(screen.getByLabelText("Viewport"), "desktop-1920");
    await userEvent.setup().selectOptions(screen.getByLabelText("Zoom"), "0");
    const preview = screen.getByRole("region", { name: "Stockroom Preview" });
    const frame = preview.querySelector<HTMLElement>('[data-design-product-root="true"]')!;
    Object.defineProperty(preview, "clientWidth", { configurable: true, value: 1000 });

    fireEvent(window, new Event("resize"));
    act(() => notifyResize());

    await waitFor(() => expect(frame.style.transform).toBe("scale(0.5083333333333333)"));
  });

  it("fits the complete 1366 canvas between Layers and Inspector and keeps its right edge editable", async () => {
    let notifyResize: () => void = () => undefined;
    class ResizeObserverStub {
      constructor(callback: ResizeObserverCallback) {
        notifyResize = () => callback([], this as unknown as ResizeObserver);
      }
      observe() {}
      disconnect() {}
      unobserve() {}
    }
    vi.stubGlobal("ResizeObserver", ResizeObserverStub);
    const action = vi.fn();
    renderInteractionProduct(action);
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Open Design Studio" }));
    await user.click(screen.getByRole("button", { name: "Edit" }));
    await openDrawer("Layers");
    const preview = screen.getByRole("region", { name: "Stockroom Preview" });
    Object.defineProperty(preview, "clientWidth", { configurable: true, value: 700 });

    act(() => notifyResize());

    const stage = preview.querySelector<HTMLElement>('[data-design-preview-stage="true"]');
    const frame = preview.querySelector<HTMLElement>('[data-design-product-root="true"]')!;
    expect(screen.getByRole("complementary", { name: "Layers" })).toBeVisible();
    expect(screen.getByRole("complementary", { name: "Inspector" })).toBeVisible();
    expect(stage).toBeInTheDocument();
    expect(Number.parseFloat(stage?.style.width ?? "")).toBeCloseTo(676, 5);
    expect(frame.style.transformOrigin).toBe("top left");

    await user.click(screen.getByRole("button", { name: "Product Action" }));
    expect(screen.getByTestId("interaction-selection")).toHaveTextContent("interaction.action");
    expect(action).not.toHaveBeenCalled();
  });

  it("never steals arrow or pointer input from controls inside the preview", async () => {
    await renderStudio();
    const preview = screen.getByRole("region", { name: "Stockroom Preview" });
    const frame = preview.querySelector<HTMLElement>('[data-design-product-root="true"]')!;
    const slider = document.createElement("input");
    slider.type = "range";
    frame.append(slider);
    preview.scrollLeft = 0;

    fireEvent.keyDown(slider, { key: "ArrowRight" });
    fireEvent.pointerDown(slider, { button: 0, pointerId: 2, clientX: 100, clientY: 20 });
    fireEvent.pointerMove(preview, { pointerId: 2, clientX: 20, clientY: 20 });

    expect(preview.scrollLeft).toBe(0);
  });

  it("lists only rendered stable targets and exposes their hierarchy without index keys", async () => {
    await renderStudio();
    const sidebar = await openDrawer("Layers");
    const close = within(sidebar).getByRole("button", { name: "Close Drawer" });
    expect(close.querySelector("svg.ico")).not.toBeNull();
    expect(close).toHaveTextContent("");
    expect(within(sidebar).queryAllByRole("button", { name: /Icon · design\.(?:screens|layers)/ })).toHaveLength(0);
    expect(within(sidebar).queryAllByRole("button", { name: /Icon · action\.close/ })).toHaveLength(0);
    const rail = within(sidebar).getByRole("button", { name: "Navigation rail" });
    expect(rail).toHaveAttribute("data-target-key", "dev:rail.root");
    expect(within(sidebar).queryByRole("button", { name: "About dialog" })).toBeNull();

    await userEvent.setup().click(within(sidebar).getByRole("button", { name: "Structure" }));
    expect(rail.getAttribute("data-target-depth")).toMatch(/^\d+$/);
    expect(sidebar.innerHTML).not.toContain("data-target-index");
  });

  it("keeps hidden targets as ghost rows and blanks contents without hiding the preview root", async () => {
    await renderStudio();
    const sidebar = await openDrawer("Layers");
    const rail = within(sidebar).getByRole("button", { name: "Navigation rail" });
    await userEvent.setup().click(rail);
    await userEvent.setup().click(within(sidebar).getByRole("button", { name: "Hide Selected" }));
    expect(document.querySelector('[data-dev-id="rail.root"]')).toHaveStyle({ visibility: "hidden" });
    expect(within(sidebar).getByRole("button", { name: /Navigation rail.*Hidden/ })).toBeVisible();

    const productRoot = screen.getByRole("region", { name: "Stockroom Preview" })
      .querySelector("[data-design-product-root]") as HTMLElement;
    await userEvent.setup().click(within(sidebar).getByRole("button", { name: "Hide Screen Contents" }));
    expect(productRoot.style.visibility).toBe("");
    expect(productRoot.querySelector<HTMLElement>('[data-dev-id="shell.root"]')?.style.visibility ?? "").toBe("");
    expect(productRoot.querySelectorAll('[style*="visibility: hidden"]').length).toBeGreaterThan(1);

    await userEvent.setup().click(within(sidebar).getByRole("button", { name: "Show All Hidden" }));
    expect(productRoot.style.visibility).toBe("");
    expect((document.querySelector('[data-dev-id="rail.root"]') as HTMLElement).style.visibility).toBe("");
  }, 10_000);

  it("defaults to meaningful layers and can reveal every generated wrapper", async () => {
    await renderStudio();
    const sidebar = await openDrawer("Layers");
    expect(within(sidebar).getByRole("button", { name: "All Elements" })).toHaveAttribute("aria-pressed", "false");
    const internalGenerated = /Element · auto\.(?:icon|primitives-kit)\./;
    expect(within(sidebar).queryAllByRole("button", { name: internalGenerated })).toHaveLength(0);
    const before = within(sidebar).queryAllByRole("button", { name: /Element · auto\./ }).length;
    await userEvent.setup().click(within(sidebar).getByRole("button", { name: "All Elements" }));
    const after = within(sidebar).getAllByRole("button", { name: /Element · auto\./ }).length;
    const revealedInternal = within(sidebar).getAllByRole("button", { name: internalGenerated });
    expect(revealedInternal.some((entry) => entry.textContent?.includes("auto.primitives-kit."))).toBe(true);
    expect(within(sidebar).queryAllByRole("button", { name: /Icon · design\.(?:screens|layers)/ })).toHaveLength(0);
    expect(after).toBeGreaterThan(before);
  });

  it("collapses every editor region without hiding Stockroom chrome", async () => {
    const { container } = await renderStudio();
    await userEvent.setup().click(
      within(screen.getByLabelText("Studio Mode")).getByRole("button", { name: "Edit" }),
    );
    await openView();
    await userEvent.setup().click(screen.getByRole("button", { name: "Presentation" }));

    expect(screen.queryByRole("complementary", { name: "Screens" })).not.toBeInTheDocument();
    expect(screen.queryByRole("complementary", { name: "Inspector" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Preview" })).toHaveAttribute("aria-pressed", "true");
    expect(container.querySelector('[data-dev-id="rail.root"]')).toBeVisible();
  });

  it("uses Escape to return to Preview before closing and restores focus to the rail entry", async () => {
    const { entry } = await renderStudio();
    await userEvent.setup().click(
      within(screen.getByLabelText("Studio Mode")).getByRole("button", { name: "Edit" }),
    );

    fireEvent.keyDown(window, { key: "Escape" });
    expect(screen.getByRole("button", { name: "Preview" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("region", { name: "Stockroom Preview" })).toBeVisible();

    fireEvent.keyDown(window, { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("region", { name: "Stockroom Preview" })).toBeNull());
    expect(entry).toHaveFocus();
  });

  it("shares one mode authority with the retained Dev panel controls", async () => {
    const { entry } = await renderStudio();
    await openView();
    await userEvent.setup().click(screen.getByRole("button", { name: "Developer Tools" }));
    const studioMode = within(screen.getByLabelText("Studio Mode"));
    const devPanel = within(screen.getByRole("complementary", { name: "Dev mode" }));

    await userEvent.setup().click(devPanel.getByRole("button", { name: "Edit" }));
    expect(studioMode.getByRole("button", { name: "Edit" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );

    fireEvent.keyDown(window, { key: "Escape" });
    expect(studioMode.getByRole("button", { name: "Preview" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(screen.getByRole("region", { name: "Stockroom Preview" })).toBeVisible();

    fireEvent.keyDown(window, { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("region", { name: "Stockroom Preview" })).toBeNull());
    expect(entry).toHaveFocus();
  });

  it("lets the real SpecMatrix Columns popover own Escape before Design Studio", async () => {
    const { entry } = await renderStudio();
    await userEvent.setup().click(screen.getByRole("button", { name: "Tools" }));
    const columnsButton = await screen.findByRole("button", { name: "Columns" });
    await userEvent.setup().click(columnsButton);
    expect(screen.getByTestId("column-picker")).toBeVisible();

    await userEvent.setup().keyboard("{Escape}");

    await waitFor(() => expect(screen.queryByTestId("column-picker")).not.toBeInTheDocument());
    expect(screen.getByRole("region", { name: "Stockroom Preview" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Preview" })).toHaveAttribute("aria-pressed", "true");

    await userEvent.setup().keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("region", { name: "Stockroom Preview" })).toBeNull());
    expect(entry).toHaveFocus();
  });

  it("gives panel resizers named keyboard controls", async () => {
    await renderStudio();
    await openDrawer("Screens");
    const resizer = screen.getByRole("separator", { name: "Resize Screens And States Panel" });
    const before = screen.getByRole("complementary", { name: "Screens" }).getAttribute("style");

    fireEvent.keyDown(resizer, { key: "ArrowRight" });

    expect(screen.getByRole("complementary", { name: "Screens" }).getAttribute("style")).not.toBe(before);
  });

  it("keeps a failed fixture-preview panel preference dirty and flushes it in Real Data", async () => {
    await renderStudio();
    await chooseScenario("Onboarding Open");
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

    await chooseScenario("Real Data");
    await waitFor(() => expect(fetchMock.mock.calls.some(
      ([input, init]) => String(input).includes("/api/settings") && init?.method === "PATCH" &&
        String(init.body).includes("design_studio_left_width"),
    )).toBe(true));
    const settingsCall = fetchMock.mock.calls.find(
      ([input, init]) => String(input).includes("/api/settings") && init?.method === "PATCH" &&
        String(init.body).includes("design_studio_left_width"),
    );
    expect(settingsCall?.[1]?.body).toBe(
      JSON.stringify({ ui: { design_studio_left_width: queuedWidth } }),
    );
  });

  it("blocks a real Settings picker control before either native bridge and explains recovery", async () => {
    const managedPicker = vi.fn().mockResolvedValue("C:\\CubeMX");
    const legacyPicker = vi.fn().mockResolvedValue("C:\\LegacyCubeMX");
    const bridges = window as unknown as {
      __STOCKROOM_HOST__?: { pickFolder: typeof managedPicker };
      pywebview?: { api: { pick_folder: typeof legacyPicker } };
    };
    bridges.__STOCKROOM_HOST__ = { pickFolder: managedPicker };
    bridges.pywebview = { api: { pick_folder: legacyPicker } };
    await renderStudio();

    await chooseScenario(/cubemx picker/i);
    const pickerCase = await waitFor(() => {
      const element = document.querySelector<HTMLElement>('[data-scenario-picker="cubemx"]');
      expect(element).toBeVisible();
      return element!;
    });
    await userEvent.setup().click(within(pickerCase).getByRole("button", { name: "Choose Folder" }));

    expect(await screen.findByText(
      /Fixture preview blocked choosing a CubeMX folder\. Return to Real Data/,
    )).toBeInTheDocument();
    expect(managedPicker).not.toHaveBeenCalled();
    expect(legacyPicker).not.toHaveBeenCalled();
  });

  it("shows the six built-in variations and manages custom inheritance and deletion", async () => {
    await renderStudio();
    await openDrawer("Layers");
    for (const title of ["Full Data", "Compact", "Purchasing", "CAD Review", "Minimal", "Custom"]) {
      expect(screen.getByRole("button", { name: new RegExp(`^${title}$`) })).toBeInTheDocument();
    }

    await userEvent.setup().click(screen.getByRole("button", { name: "New Variation" }));
    await userEvent.setup().type(screen.getByRole("textbox", { name: "Variation Name" }), "Bench Review");
    await userEvent.setup().click(screen.getByRole("button", { name: "Create" }));

    expect(screen.getByRole("button", { name: "Bench Review" })).toHaveAttribute("aria-pressed", "true");
    await userEvent.setup().selectOptions(screen.getByRole("combobox", { name: "Variation Parent" }), "compact");
    expect(screen.getByRole("combobox", { name: "Variation Parent" })).toHaveValue("compact");
    await userEvent.setup().click(screen.getByRole("button", { name: "Delete" }));
    expect(screen.queryByRole("button", { name: "Bench Review" })).not.toBeInTheDocument();
  });
});
