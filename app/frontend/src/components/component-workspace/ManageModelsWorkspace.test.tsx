import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ProviderCoverageRow } from "../../api/dossierTypes";
import { api } from "../../api/client";
import { ScenarioUiProvider } from "../../design-studio/scenarioState";
import { makeDossier } from "../../test/dossierFixture";
import { ManageModelsWorkspace } from "./ManageModelsWorkspace";

const captureMocks = vi.hoisted(() => ({ useOptionalCapture: vi.fn() }));
vi.mock("../../lib/capture", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../../lib/capture")>()),
  useOptionalCapture: captureMocks.useOptionalCapture,
}));

function providerRow(id: string, complete: boolean, captureAvailable = true): ProviderCoverageRow {
  return {
    id,
    label: id === "complete" ? "SnapEDA" : "Ultra Librarian",
    order: complete ? 2 : 1,
    url: `https://${id}.example`,
    urlKind: "evidence",
    instruction: "",
    needsLogin: false,
    captureAvailable,
    aggregator: true,
    distributor: false,
    statusCounts: {
      unknown: 0,
      available: complete ? 3 : 2,
      not_available: complete ? 0 : 1,
      downloaded: 0,
      validated: 0,
    },
    complete,
    symbol: { status: "available", origin: "official_api", userAssertion: null },
    footprint: { status: "available", origin: "official_api", userAssertion: null },
    model: {
      status: complete ? "available" : "not_available",
      origin: "official_api",
      userAssertion: null,
    },
    kicad: { count: 0, total: 3, summary: "0/3", complete: false, supported: true },
    altium: { count: 0, total: 3, summary: "0/3", complete: false, supported: true },
  };
}

function rect(x: number, y: number, width: number, height: number): DOMRect {
  return {
    x,
    y,
    width,
    height,
    top: y,
    right: x + width,
    bottom: y + height,
    left: x,
    toJSON: () => ({}),
  } as DOMRect;
}

describe("ManageModelsWorkspace", () => {
  beforeEach(() => {
    captureMocks.useOptionalCapture.mockReturnValue(null);
    vi.spyOn(crypto, "randomUUID").mockReturnValue("7ed4d06c-66b0-4dbe-88ef-35edce7a373f");
    vi.spyOn(api, "startManualProviderBrowser").mockImplementation(async (input) => ({
      session_id: input.sessionId,
      part_id: input.partId,
      provider_id: input.providerId,
      url: input.url,
      browser_owner_id: input.browserOwnerId,
      state: "active",
      proposal: null,
      error: "",
      browser_state: {
        url: input.url,
        loading: false,
        navigation_error: "",
        can_go_back: false,
        can_go_forward: false,
      },
    }));
    vi.spyOn(api, "manualProviderBrowserStatus").mockImplementation(async (input) => ({
      session_id: input.sessionId,
      part_id: "part-1",
      provider_id: "mouser",
      url: "https://www.mouser.com/c/?q=LM358DR",
      browser_owner_id: `part-1:mouser:manual:mouser:${input.sessionId}`,
      state: "active",
      proposal: null,
      error: "",
      browser_state: null,
    }));
    vi.spyOn(api, "stopManualProviderBrowser").mockResolvedValue({
      stopped: true,
      session_id: "7ed4d06c-66b0-4dbe-88ef-35edce7a373f",
    });
  });
  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
    Reflect.deleteProperty(window, "__STOCKROOM_HOST__");
    vi.restoreAllMocks();
  });
  it("shows every provider as a clean choice and opens the clicked provider", async () => {
    const user = userEvent.setup();
    const dossier = makeDossier();
    const partial = providerRow("partial", false);
    const complete = providerRow("complete", true);
    dossier.cadSourceCoverage.rows = [partial, complete];
    const onOpenProvider = vi.fn();

    render(
      <ManageModelsWorkspace
        componentId="part-1"
        dossier={dossier}
        onView={vi.fn()}
        onOpenProvider={onOpenProvider}
      />,
    );

    const providerButtons = within(screen.getByRole("radiogroup", { name: "CAD model providers" }))
      .getAllByRole("radio");
    expect(providerButtons).toHaveLength(2);
    expect(providerButtons[0]).toHaveTextContent(partial.label);
    expect(providerButtons[1]).toHaveTextContent(complete.label);
    expect(providerButtons[0].querySelector("svg")).toBeNull();
    expect(providerButtons[1].querySelector("svg")).toBeNull();
    const completeProvider = providerButtons[1];
    expect(within(completeProvider).getByText("All 3")).toBeVisible();
    expect(within(providerButtons[0]).queryByText("All 3")).toBeNull();
    expect(screen.getAllByText("All 3")).toHaveLength(1);
    expect(screen.queryByText("3D Model")).toBeNull();
    expect(screen.queryByRole("button", { name: "Open Provider" })).toBeNull();
    expect(onOpenProvider).not.toHaveBeenCalled();
    await user.click(providerButtons[1]);
    await waitFor(() => expect(onOpenProvider).toHaveBeenCalledWith(complete.id, [
      "kicad_symbol",
      "kicad_footprint",
      "kicad_model",
    ]));
  });

  it("uses the idle surface as a compact acquisition dashboard", () => {
    const dossier = makeDossier();
    dossier.cadSourceCoverage.rows = [providerRow("partial", false), providerRow("complete", true)];

    render(<ManageModelsWorkspace componentId="part-1" dossier={dossier} />);

    const summary = screen.getByRole("region", { name: "CAD acquisition overview" });
    expect(within(summary).getByText("Requested Files")).toBeVisible();
    expect(within(summary).getByText("KiCad Symbol + Footprint")).toBeVisible();
    expect(within(summary).getByText("Shared 3D Model")).toBeVisible();
    expect(within(summary).getByText("No Files Staged")).toBeVisible();
    expect(screen.getByText("Open A Provider")).toBeVisible();
    expect(
      screen.getByText(
        "Choose a provider above to download CAD, or import files on this PC.",
      ),
    ).toBeVisible();
    for (const provider of screen.getAllByRole("radio")) {
      expect(provider).toHaveAttribute("title", `Open ${provider.textContent?.replace("All 3", "").trim()}`);
      expect(provider.className).toContain("bg-control-top");
    }
    expect(screen.getByRole("button", { name: "Import Existing CAD Files" })).toBeVisible();
    expect(screen.queryByText(/opens here/i)).toBeNull();
    expect(screen.queryByText(/appear here/i)).toBeNull();
  });

  it("starts with no selected provider and launches nothing", () => {
    const dossier = makeDossier();
    dossier.cadSourceCoverage.rows = [providerRow("partial", false), providerRow("complete", true)];
    const onOpenProvider = vi.fn();

    render(
      <ManageModelsWorkspace
        componentId="part-1"
        dossier={dossier}
        onOpenProvider={onOpenProvider}
      />,
    );

    for (const provider of screen.getAllByRole("radio")) {
      expect(provider).toHaveAttribute("aria-checked", "false");
    }
    expect(screen.getByRole("region", { name: "CAD acquisition overview" })).toBeVisible();
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(onOpenProvider).not.toHaveBeenCalled();
    expect(api.startManualProviderBrowser).not.toHaveBeenCalled();
  });

  it("starts a provider visit directly from the selected provider row", async () => {
    const user = userEvent.setup();
    const dossier = makeDossier();
    dossier.cadSourceCoverage.rows = [providerRow("partial-a", false), providerRow("partial-b", false)];
    dossier.cadSourceCoverage.completeProviders = [];
    const onOpenProvider = vi.fn();

    render(
      <ManageModelsWorkspace
        componentId="part-1"
        dossier={dossier}
        onView={vi.fn()}
        onOpenProvider={onOpenProvider}
      />,
    );

    expect(onOpenProvider).not.toHaveBeenCalled();
    const providers = screen.getAllByRole("radio");
    const lastProvider = providers[providers.length - 1]!;
    await user.click(lastProvider);
    expect(lastProvider).toHaveAttribute("aria-checked", "true");
    expect(screen.queryByRole("button", { name: "Open Provider" })).toBeNull();
    expect(onOpenProvider).toHaveBeenCalledWith("partial-b", [
      "kicad_symbol",
      "kicad_footprint",
      "kicad_model",
    ]);
    expect(providers[0]).not.toHaveTextContent("Missing");
  });

  it.each([
    ["mouser", "Mouser", "https://www.mouser.com/c/?q=LM358DR", "escape"],
    ["digikey", "DigiKey", "https://www.digikey.com/en/products/result?keywords=LM358DR", "close"],
    ["lcsc", "LCSC", "https://www.lcsc.com/product-detail/C12345.html", "escape"],
  ])("opens the reachable %s row at its real URL in the in-app browser modal", async (
    id,
    label,
    url,
    dismissal,
  ) => {
    const user = userEvent.setup();
    const dossier = makeDossier();
    dossier.cadSourceCoverage.rows = [{
      ...providerRow(id, false, false),
      label,
      url,
    }];
    dossier.cadSourceCoverage.completeProviders = [];
    const onOpenProvider = vi.fn();

    render(
      <ManageModelsWorkspace
        componentId="part-1"
        dossier={dossier}
        onView={vi.fn()}
        onOpenProvider={onOpenProvider}
      />,
    );

    const trigger = screen.getByRole("radio", { name: label });
    trigger.focus();
    await user.click(trigger);
    const dialog = screen.getByRole("dialog", { name: `${label} Browser` });
    expect(dialog).toBeVisible();
    expect(screen.getByRole("textbox", { name: "Provider Address" })).toHaveValue(url);
    expect(onOpenProvider).not.toHaveBeenCalled();
    if (dismissal === "close") {
      await user.click(screen.getByRole("button", { name: "Close" }));
    } else {
      await user.keyboard("{Escape}");
    }
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(document.activeElement).toBe(trigger);
    expect(api.stopManualProviderBrowser).not.toHaveBeenCalled();
  });

  it("moves the provider modal from its title bar while keeping it resizable", async () => {
    const user = userEvent.setup();
    vi.stubGlobal("innerWidth", 1366);
    vi.stubGlobal("innerHeight", 872);
    const setProviderViewport = vi.fn();
    Object.defineProperty(window, "__STOCKROOM_HOST__", {
      configurable: true,
      value: {
        setProviderViewport,
        providerCommand: vi.fn().mockResolvedValue(true),
      },
    });
    vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockImplementation(function (
      this: HTMLElement,
    ) {
      const transform = this.closest<HTMLElement>('[role="dialog"]')?.style.transform
        ?? this.style.transform
        ?? "";
      const match = /translate\((-?\d+)px, (-?\d+)px\)/.exec(transform);
      const offsetX = Number(match?.[1] ?? 0);
      const offsetY = Number(match?.[2] ?? 0);
      if (this.getAttribute("role") === "dialog") {
        const width = this.style.width.endsWith("px")
          ? Number.parseInt(this.style.width, 10)
          : 1180;
        const height = this.style.height.endsWith("px")
          ? Number.parseInt(this.style.height, 10)
          : 628;
        return rect(
          683 + offsetX - width / 2,
          436 + offsetY - height / 2,
          width,
          height,
        );
      }
      if (this.getAttribute("data-dev-id") !== "component-browser.provider-viewport") {
        return rect(0, 0, 0, 0);
      }
      return rect(200 + offsetX, 160 + offsetY, 900, 560);
    });
    const dossier = makeDossier();
    dossier.cadSourceCoverage.rows = [{
      ...providerRow("mouser", false, false),
      label: "Mouser",
      url: "https://www.mouser.com/c/?q=LM358DR",
    }];

    render(<ManageModelsWorkspace componentId="part-1" dossier={dossier} />);
    await user.click(screen.getByRole("radio", { name: "Mouser" }));

    const dialog = screen.getByRole("dialog", { name: "Mouser Browser" });
    expect(dialog).toHaveStyle({
      width: "min(1180px, calc(100vw - 48px))",
      height: "72vh",
    });
    const titleBar = dialog.querySelector('[data-dev-id="component-browser.provider-modal-drag"]');
    expect(titleBar).not.toBeNull();
    expect(dialog.querySelectorAll("[data-modal-resize-direction]")).toHaveLength(8);
    const southeast = dialog.querySelector<HTMLElement>(
      '[data-modal-resize-direction="southeast"]',
    );
    expect(southeast).not.toBeNull();
    await user.pointer([
      { keys: "[MouseLeft>]", target: southeast!, coords: { clientX: 1273, clientY: 750 } },
      { target: southeast!, coords: { clientX: 1473, clientY: 950 } },
      { keys: "[/MouseLeft]", target: southeast!, coords: { clientX: 1473, clientY: 950 } },
    ]);
    expect(dialog).toHaveStyle({ width: "1249px", height: "726px", transform: "translate(35px, 49px)" });
    await user.pointer([
      { keys: "[MouseLeft>]", target: titleBar!, coords: { clientX: 400, clientY: 100 } },
      { target: titleBar!, coords: { clientX: -1600, clientY: -1900 } },
      { keys: "[/MouseLeft]", target: titleBar!, coords: { clientX: -1600, clientY: -1900 } },
    ]);
    expect(dialog).toHaveStyle({ transform: "translate(-34px, -49px)" });
    expect(setProviderViewport).toHaveBeenLastCalledWith({
      componentId: "part-1:mouser:manual:mouser:7ed4d06c-66b0-4dbe-88ef-35edce7a373f",
      providerId: "mouser",
      routeId: "manual:mouser",
      sessionId: "7ed4d06c-66b0-4dbe-88ef-35edce7a373f",
      visible: true,
      x: 166,
      y: 111,
      width: 900,
      height: 560,
    });
  });

  it("acknowledges focused native Escape before closing and restoring opener focus", async () => {
    const user = userEvent.setup();
    const providerCommand = vi.fn().mockResolvedValue(true);
    Object.defineProperty(window, "__STOCKROOM_HOST__", {
      configurable: true,
      value: { setProviderViewport: vi.fn(), providerCommand },
    });
    const dossier = makeDossier();
    dossier.cadSourceCoverage.rows = [{
      ...providerRow("mouser", false, false),
      label: "Mouser",
      url: "https://www.mouser.com/c/?q=LM358DR",
    }];
    render(<ManageModelsWorkspace componentId="part-1" dossier={dossier} />);
    const trigger = screen.getByRole("radio", { name: "Mouser" });
    trigger.focus();
    await user.click(trigger);
    await screen.findByRole("dialog", { name: "Mouser Browser" });

    window.dispatchEvent(new CustomEvent("stockroom:provider-close-requested", {
      detail: {
        componentId: "part-1:mouser:manual:mouser:7ed4d06c-66b0-4dbe-88ef-35edce7a373f",
        providerId: "mouser",
        routeId: "manual:mouser",
        sessionId: "7ed4d06c-66b0-4dbe-88ef-35edce7a373f",
      },
    }));

    await waitFor(() => expect(providerCommand).toHaveBeenCalledWith({
      componentId: "part-1:mouser:manual:mouser:7ed4d06c-66b0-4dbe-88ef-35edce7a373f",
      providerId: "mouser",
      routeId: "manual:mouser",
      sessionId: "7ed4d06c-66b0-4dbe-88ef-35edce7a373f",
      command: "close",
    }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(document.activeElement).toBe(trigger);
  });

  it("shows exact broker-landed files and requires explicit Apply", async () => {
    const user = userEvent.setup();
    vi.mocked(api.startManualProviderBrowser).mockImplementation(async (input) => ({
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
        part_id: "part-1",
        provider: "manual",
        primary_tool: "kicad",
        attachments: [{
          role: "KiCad Symbol",
          file_name: "LM358DR.kicad_sym",
          target: "Active KiCad Symbol",
        }],
        inactive_evidence: [],
        landed_files: ["Mouser-LM358DR.zip", "LM358DR.kicad_sym"],
        remaining_roles: ["KiCad Footprint", "3D Model"],
        automatic_apply_ready: false,
      },
    }));
    const apply = vi.spyOn(api, "applyPartFiles").mockResolvedValue({
      part_id: "part-1",
      selected_files: 2,
      attached: ["kicad_symbol"],
      ignored: [],
      remaining: [],
      complete: true,
    });
    const dossier = makeDossier();
    dossier.cadSourceCoverage.rows = [{
      ...providerRow("mouser", false, false),
      label: "Mouser",
      url: "https://www.mouser.com/c/?q=LM358DR",
    }];
    render(<ManageModelsWorkspace componentId="part-1" dossier={dossier} />);

    await user.click(screen.getByRole("radio", { name: "Mouser" }));
    expect(await screen.findByText("Mouser-LM358DR.zip")).toBeVisible();
    expect(screen.getAllByText("LM358DR.kicad_sym")).toHaveLength(2);
    expect(screen.getByText("Still needed: KiCad Footprint and 3D Model")).toBeVisible();
    expect(apply).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "Apply Attachments" }));
    expect(apply).toHaveBeenCalledWith({ partId: "part-1", proposalToken: "proposal-1" });
  });

  it("shows durable CAD Ready without another Apply for a complete exact provider package", async () => {
    const user = userEvent.setup();
    vi.mocked(api.startManualProviderBrowser).mockImplementation(async (input) => ({
      session_id: input.sessionId,
      part_id: input.partId,
      provider_id: input.providerId,
      url: input.url,
      browser_owner_id: input.browserOwnerId,
      state: "ready",
      proposal: null,
      error: "",
      browser_state: null,
      download_progress: {
        active: 0,
        completed: 1,
        bytes_received: 3,
        total_bytes: 3,
        files: [{
          name: "Mouser-LM358DR.zip",
          state: "completed",
          bytes_received: 3,
          total_bytes: 3,
        }],
      },
      cad_ready: {
        attached: ["kicad_symbol", "kicad_footprint", "kicad_model"],
        edas: ["kicad"],
        landed_files: ["Mouser-LM358DR.zip"],
        part_complete: false,
        provider_id: "mouser",
        remaining_roles: [],
      },
    }));
    const apply = vi.spyOn(api, "applyPartFiles");
    const onAttached = vi.fn();
    const dossier = makeDossier();
    dossier.cadSourceCoverage.rows = [{
      ...providerRow("mouser", false, false),
      label: "Mouser",
      url: "https://www.mouser.com/c/?q=LM358DR",
    }];
    render(
      <ManageModelsWorkspace componentId="part-1" dossier={dossier} onAttached={onAttached} />,
    );

    await user.click(screen.getByRole("radio", { name: "Mouser" }));

    expect(await screen.findByText("CAD Ready")).toBeVisible();
    expect(screen.getByText("Mouser-LM358DR.zip")).toBeVisible();
    expect(screen.queryByRole("button", { name: "Apply Attachments" })).toBeNull();
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(apply).not.toHaveBeenCalled();
    expect(onAttached).toHaveBeenCalledTimes(1);
  });

  it("shows stalled download progress and all three recovery choices", async () => {
    const user = userEvent.setup();
    vi.mocked(crypto.randomUUID)
      .mockReturnValueOnce("7ed4d06c-66b0-4dbe-88ef-35edce7a373f")
      .mockReturnValueOnce("acbd2a03-e41f-488c-8112-5da8c63c981e");
    vi.mocked(api.startManualProviderBrowser)
      .mockImplementationOnce(async (input) => ({
        session_id: input.sessionId,
        part_id: input.partId,
        provider_id: input.providerId,
        url: input.url,
        browser_owner_id: input.browserOwnerId,
        state: "stalled",
        proposal: null,
        cad_ready: null,
        error: "The provider download stalled.",
        browser_state: null,
        download_progress: {
          active: 1,
          completed: 0,
          bytes_received: 40,
          total_bytes: 100,
          files: [{
            name: "LM358DR.zip",
            state: "in_progress",
            bytes_received: 40,
            total_bytes: 100,
          }],
        },
      }))
      .mockImplementationOnce(() => new Promise(() => undefined));
    const dossier = makeDossier();
    dossier.cadSourceCoverage.rows = [{
      ...providerRow("mouser", false, false),
      label: "Mouser",
      url: "https://www.mouser.com/c/?q=LM358DR",
    }];
    render(<ManageModelsWorkspace componentId="part-1" dossier={dossier} />);

    await user.click(screen.getByRole("radio", { name: "Mouser" }));

    expect(await screen.findByRole("progressbar", { name: "Download progress" })).toHaveValue(40);
    expect(screen.getByRole("button", { name: "Retry" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Choose Another Provider" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Close" })).toBeVisible();
    await user.click(screen.getByRole("button", { name: "Retry" }));
    expect(api.startManualProviderBrowser).toHaveBeenCalledTimes(2);
    expect(screen.getByRole("dialog", { name: "Mouser Browser" })).toBeVisible();
  });

  it("bounds a provider start that never acknowledges and exposes recovery", async () => {
    vi.useFakeTimers();
    vi.mocked(api.startManualProviderBrowser).mockImplementation(() => new Promise(() => undefined));
    vi.mocked(api.manualProviderBrowserStatus).mockImplementation(() => new Promise(() => undefined));
    const dossier = makeDossier();
    dossier.cadSourceCoverage.rows = [{
      ...providerRow("mouser", false, false),
      label: "Mouser",
      url: "https://www.mouser.com/c/?q=LM358DR",
    }];
    render(<ManageModelsWorkspace componentId="part-1" dossier={dossier} />);

    fireEvent.click(screen.getByRole("radio", { name: "Mouser" }));
    expect(screen.getByText("Opening Provider...")).toBeVisible();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(8_001);
    });

    expect(screen.getAllByText(/Provider opening stalled/)).toHaveLength(2);
    expect(screen.getByRole("button", { name: "Retry" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Choose Another Provider" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Close" })).toBeVisible();
  });

  it("hides the old native session and disables stale history during provider switch", async () => {
    const user = userEvent.setup();
    vi.mocked(crypto.randomUUID)
      .mockReturnValueOnce("7ed4d06c-66b0-4dbe-88ef-35edce7a373f")
      .mockReturnValueOnce("acbd2a03-e41f-488c-8112-5da8c63c981e");
    vi.mocked(api.startManualProviderBrowser)
      .mockImplementationOnce(async (input) => ({
        session_id: input.sessionId,
        part_id: input.partId,
        provider_id: input.providerId,
        url: input.url,
        browser_owner_id: input.browserOwnerId,
        state: "active",
        proposal: null,
        error: "",
        browser_state: {
          url: input.url,
          loading: false,
          navigation_error: "",
          can_go_back: true,
          can_go_forward: true,
        },
      }))
      .mockImplementationOnce(() => new Promise(() => undefined));
    const setProviderViewport = vi.fn();
    Object.defineProperty(window, "__STOCKROOM_HOST__", {
      configurable: true,
      value: { setProviderViewport, providerCommand: vi.fn().mockResolvedValue(true) },
    });
    const dossier = makeDossier();
    dossier.cadSourceCoverage.rows = [
      { ...providerRow("mouser", false, false), label: "Mouser", url: "https://www.mouser.com/c/?q=LM358DR" },
      { ...providerRow("lcsc", false, false), label: "LCSC", url: "https://www.lcsc.com/product-detail/C12345.html" },
    ];
    render(<ManageModelsWorkspace componentId="part-1" dossier={dossier} />);

    await user.click(screen.getByRole("radio", { name: "Mouser" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Back" })).toBeEnabled());
    await user.click(screen.getByRole("radio", { name: "LCSC" }));

    expect(screen.getByRole("dialog", { name: "LCSC Browser" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Back" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Forward" })).toBeDisabled();
    expect(setProviderViewport.mock.calls.some(([viewport]) => (
      viewport.sessionId === "7ed4d06c-66b0-4dbe-88ef-35edce7a373f"
      && viewport.visible === false
    ))).toBe(true);
  });

  it("ends an adapter-backed visit before starting a manual provider", async () => {
    const user = userEvent.setup();
    const skipProvider = vi.fn().mockResolvedValue(undefined);
    captureMocks.useOptionalCapture.mockReturnValue({
      active: {
        partId: "part-1",
        workflowItemId: "item-1",
        partName: "Part One",
        status: "window-open",
        message: "Provider ready",
        url: "https://complete.example",
        routeToken: "route-1",
        vendor: "complete",
        needs: ["kicad_symbol"],
        received: {},
        backgrounded: false,
        providerOutcomes: [],
        completionEvidence: null,
        completionEvidenceReported: false,
      },
      skipProvider,
    });
    const dossier = makeDossier();
    dossier.cadSourceCoverage.rows = [
      providerRow("complete", true),
      {
        ...providerRow("mouser", false, false),
        label: "Mouser",
        url: "https://www.mouser.com/c/?q=LM358DR",
      },
    ];

    render(<ManageModelsWorkspace componentId="part-1" dossier={dossier} />);
    await user.click(screen.getByRole("radio", { name: "Mouser" }));

    expect(skipProvider).toHaveBeenCalledTimes(1);
    expect(api.startManualProviderBrowser).not.toHaveBeenCalled();
    expect(screen.getByText("Switching to Mouser...")).toBeVisible();
  });

  it("shows browser chrome immediately while the native provider route prepares", async () => {
    const user = userEvent.setup();
    const dossier = makeDossier();
    dossier.cadSourceCoverage.rows = [providerRow("complete", true)];
    const onOpenProvider = vi.fn().mockImplementation(() => new Promise(() => undefined));

    render(
      <ManageModelsWorkspace
        componentId="part-1"
        dossier={dossier}
        onView={vi.fn()}
        onOpenProvider={onOpenProvider}
      />,
    );

    expect(screen.queryByRole("region", { name: "SnapEDA Browser" })).toBeNull();
    await user.click(screen.getByRole("radio", { name: /SnapEDA/ }));

    expect(screen.getByRole("dialog", { name: "SnapEDA Browser" })).toBeVisible();
    expect(screen.getByRole("region", { name: "SnapEDA Browser Page" })).toBeVisible();
    expect(screen.getByLabelText("Current provider address")).toHaveTextContent(
      "complete.example",
    );
    expect(screen.getByText("Loading")).toBeVisible();
    expect(screen.getByRole("button", { name: "Reload" })).toBeDisabled();
    expect(onOpenProvider).toHaveBeenCalledTimes(1);
  });

  it("hides and restores the provider without ending its active visit", async () => {
    const user = userEvent.setup();
    const dossier = makeDossier();
    dossier.cadSourceCoverage.rows = [providerRow("partial", false), providerRow("complete", true)];
    const closeProvider = vi.fn().mockResolvedValue(undefined);
    const showProvider = vi.fn().mockResolvedValue(undefined);
    captureMocks.useOptionalCapture.mockReturnValue({
      active: {
        partId: "part-1",
        workflowItemId: "item-1",
        partName: "Part One",
        status: "window-open",
        message: "Provider ready",
        url: "https://complete.example",
        routeToken: "route-1",
        vendor: "complete",
        needs: ["kicad_symbol"],
        received: {},
        backgrounded: false,
        providerOutcomes: [],
        completionEvidence: null,
        completionEvidenceReported: false,
      },
      closeProvider,
      showProvider,
      finishProvider: vi.fn().mockResolvedValue(undefined),
    });

    render(
      <ManageModelsWorkspace
        componentId="part-1"
        dossier={dossier}
        onView={vi.fn()}
        onOpenProvider={vi.fn()}
      />,
    );

    expect(screen.getByRole("checkbox", { name: "KiCad" })).toBeDisabled();
    expect(screen.getByRole("checkbox", { name: "Altium Designer" })).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "Close" }));
    expect(closeProvider).not.toHaveBeenCalled();
    expect(screen.queryByRole("dialog", { name: "SnapEDA Browser" })).toBeNull();
    expect(screen.getByRole("radio", { name: /Ultra Librarian/ })).toBeEnabled();

    await user.click(screen.getByRole("button", { name: "Show Provider" }));
    expect(showProvider).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("dialog", { name: "SnapEDA Browser" })).toBeVisible();
  });

  it("reports a restore failure while retaining the hidden route", async () => {
    const user = userEvent.setup();
    const dossier = makeDossier();
    dossier.cadSourceCoverage.rows = [providerRow("complete", true)];
    const showProvider = vi.fn().mockRejectedValue(new Error("Coordinator unavailable"));
    captureMocks.useOptionalCapture.mockReturnValue({
      active: {
        partId: "part-1",
        workflowItemId: "item-1",
        partName: "Part One",
        status: "window-open",
        message: "Provider ready",
        url: "https://complete.example",
        routeToken: "route-1",
        vendor: "complete",
        needs: ["kicad_symbol"],
        received: {},
        backgrounded: false,
        providerOutcomes: [],
        completionEvidence: null,
        completionEvidenceReported: false,
      },
      closeProvider: vi.fn().mockResolvedValue(undefined),
      showProvider,
      finishProvider: vi.fn().mockResolvedValue(undefined),
    });

    render(
      <ManageModelsWorkspace
        componentId="part-1"
        dossier={dossier}
        onView={vi.fn()}
        onOpenProvider={vi.fn()}
      />,
    );
    await user.click(screen.getByRole("button", { name: "Close" }));
    await user.click(screen.getByRole("button", { name: "Show Provider" }));

    expect(await screen.findByText("Coordinator unavailable")).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "SnapEDA Browser" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Skip This Part" })).toBeNull();
  });

  it("shows exact progress and cancels the old workflow when switching providers", async () => {
    const user = userEvent.setup();
    const dossier = makeDossier();
    dossier.cadSourceCoverage.rows = [
      providerRow("complete", true),
      providerRow("partial", false),
    ];
    const finishProvider = vi.fn().mockResolvedValue(undefined);
    const showProvider = vi.fn().mockResolvedValue(undefined);
    const closeProvider = vi.fn().mockResolvedValue(undefined);
    const skipProvider = vi.fn().mockResolvedValue(undefined);
    captureMocks.useOptionalCapture.mockReturnValue({
      active: {
        partId: "part-1",
        workflowItemId: "item-1",
        partName: "Part One",
        status: "window-open",
        message: "Provider ready",
        url: "https://complete.example",
        routeToken: "route-1",
        vendor: "complete",
        authorRoute: "complete",
        handoff: {
          provider: "complete",
          provider_label: "SnapEDA",
          instruction: "Choose the CAD formats, then download.",
          manufacturer: "Texas Instruments",
          mpn: "LM358DR",
          routes: [{
            route: "complete:complete",
            label: "SnapEDA",
            author_route: "SnapEDA",
            instruction: "Choose the CAD formats, then download.",
            required_files: ["KiCad symbol and footprint", "STEP model"],
          }],
        },
        browserState: {
          url: "https://complete.example/redirected",
          loading: false,
          navigation_error: "",
          can_go_back: true,
          can_go_forward: false,
        },
        downloadProgress: {
          active: 1,
          completed: 0,
          bytes_received: 50,
          total_bytes: 100,
          files: [{
            name: "LM358DR.zip",
            state: "in_progress",
            bytes_received: 50,
            total_bytes: 100,
          }],
        },
        needs: ["kicad_symbol"],
        received: {},
        backgrounded: false,
        providerOutcomes: [],
        completionEvidence: null,
        completionEvidenceReported: false,
      },
      finishProvider,
      skipProvider,
      closeProvider,
      showProvider,
    });

    render(
      <ManageModelsWorkspace
        componentId="part-1"
        dossier={dossier}
        onView={vi.fn()}
      />,
    );

    expect(screen.getByText("Receiving LM358DR.zip")).toBeVisible();
    expect(screen.getByText("50%")).toBeVisible();
    expect(screen.getByLabelText("Current provider address")).toHaveTextContent(
      "complete.example/redirected",
    );
    expect(screen.getByRole("button", { name: "Back" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Forward" })).toBeDisabled();

    expect(screen.queryByRole("button", { name: "Done With Provider" })).toBeNull();

    await user.click(screen.getByRole("button", { name: "Close" }));
    expect(screen.queryByRole("region", { name: "SnapEDA Browser" })).toBeNull();
    await user.click(screen.getByRole("button", { name: "Show Provider" }));
    expect(showProvider).toHaveBeenCalledTimes(1);

    await user.click(screen.getByRole("radio", { name: /Ultra Librarian/ }));
    expect(skipProvider).toHaveBeenCalledTimes(1);

    expect(screen.queryByRole("button", { name: "Skip This Part" })).toBeNull();
    expect(finishProvider).not.toHaveBeenCalled();
    expect(closeProvider).not.toHaveBeenCalled();
  });

  it("keeps verified files inactive until attachment confirmation", async () => {
    const user = userEvent.setup();
    const dossier = makeDossier();
    dossier.cadSourceCoverage.rows = [providerRow("complete", true)];
    const applyAttachments = vi.fn().mockResolvedValue(undefined);
    captureMocks.useOptionalCapture.mockReturnValue({
      active: {
        partId: "part-1",
        workflowItemId: "item-1",
        partName: "Part One",
        status: "receiving",
        message: "Review attachments",
        url: null,
        routeToken: null,
        vendor: "complete",
        needs: ["kicad_symbol", "kicad_footprint"],
        received: {},
        backgrounded: false,
        providerOutcomes: [],
        completionEvidence: null,
        completionEvidenceReported: false,
        attachmentProposal: {
          proposal_token: "proposal-1",
          part_id: "part-1",
          provider: "ultralibrarian",
          primary_tool: "kicad",
          attachments: [{
            role: "Symbol",
            file_name: "Part.kicad_sym",
            target: "Active KiCad Symbol",
          }],
          inactive_evidence: [{ tool: "altium", file_name: "Part.SchLib" }],
        },
      },
      applyAttachments,
      skipProvider: vi.fn().mockResolvedValue(undefined),
    });

    render(<ManageModelsWorkspace componentId="part-1" dossier={dossier} onView={vi.fn()} />);

    expect(screen.getByText(
      "Verified files remain inactive until attachment confirmation.",
    )).toBeVisible();
    expect(screen.getByText("Part.kicad_sym")).toBeVisible();
    expect(screen.getByText("Part.SchLib")).toBeVisible();
    await user.click(screen.getByRole("button", { name: "Apply Attachments" }));
    expect(applyAttachments).toHaveBeenCalledTimes(1);
  });

  it("disables a new provider visit while another component owns the capture lane", () => {
    const dossier = makeDossier();
    dossier.cadSourceCoverage.rows = [providerRow("complete", true)];
    captureMocks.useOptionalCapture.mockReturnValue({
      active: {
        partId: "part-2",
        workflowItemId: "item-2",
        partName: "Other Part",
        status: "window-open",
        message: "Provider ready",
        url: "https://complete.example",
        routeToken: "route-2",
        vendor: "complete",
        needs: ["kicad_symbol"],
        received: {},
        backgrounded: false,
        providerOutcomes: [],
        completionEvidence: null,
        completionEvidenceReported: false,
      },
    });

    render(
      <ManageModelsWorkspace
        componentId="part-1"
        dossier={dossier}
        onView={vi.fn()}
      />,
    );

    expect(screen.queryByRole("button", { name: "Open Provider" })).toBeNull();
    expect(screen.getByRole("radio", { name: /SnapEDA/ })).toBeDisabled();
    expect(screen.getByRole("status")).toHaveTextContent(
      "Finish the active Provider Visit for Other Part first.",
    );
  });

  it("preserves EDA multi-selection and requests one shared 3D model", async () => {
    const user = userEvent.setup();
    const dossier = makeDossier();
    dossier.cadSourceCoverage.rows = [providerRow("complete", true)];
    const onOpenProvider = vi.fn().mockResolvedValue(undefined);

    render(
      <ManageModelsWorkspace
        componentId="part-1"
        dossier={dossier}
        onView={vi.fn()}
        primaryEda="altium"
        onOpenProvider={onOpenProvider}
      />,
    );

    expect(screen.getByRole("checkbox", { name: "Altium Designer" })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: "KiCad" })).not.toBeChecked();
    await user.click(screen.getByRole("checkbox", { name: "KiCad" }));

    await user.click(screen.getByRole("radio", { name: /SnapEDA/ }));

    expect(onOpenProvider).toHaveBeenCalledWith("complete", [
      "kicad_symbol",
      "kicad_footprint",
      "kicad_model",
      "altium_symbol",
      "altium_footprint",
    ]);
  });

  it.each([
    "returned-to-stockroom",
    "canceled",
    "complete",
    "unavailable",
    "timeout",
    "error",
    "selected-file-recovery",
  ] as const)(
    "does not force the native browser visible for the %s fixture",
    (state) => {
      const dossier = makeDossier();
      dossier.cadSourceCoverage.rows = [providerRow("complete", true)];
      render(
        <ScenarioUiProvider state={{ provider: { state } }}>
          <ManageModelsWorkspace componentId="part-1" dossier={dossier} />
        </ScenarioUiProvider>,
      );

      expect(screen.queryByRole("dialog", { name: "SnapEDA Browser" })).toBeNull();
    },
  );

  it("uses one file chooser as recovery and reports what attached", async () => {
    const user = userEvent.setup();
    const dossier = makeDossier();
    dossier.cadSourceCoverage.rows = [providerRow("partial", false)];
    const onAttached = vi.fn();

    render(
      <ManageModelsWorkspace
        componentId="part-1"
        dossier={dossier}
        onView={vi.fn()}
        onRecoverFiles={vi.fn().mockResolvedValue({
          selected: 1,
          accepted: 3,
          outcome: "proposed",
          proposal: {
            proposal_token: "manual-1",
            part_id: "part-1",
            provider: "manual",
            primary_tool: "kicad",
            attachments: [{ role: "3D Model", file_name: "body.step", target: "Shared 3D Model" }],
            inactive_evidence: [],
          },
        })}
        onAttached={onAttached}
      />,
    );

    await user.click(screen.getByRole("button", { name: "Import Existing CAD Files" }));
    expect(await screen.findByText("body.step")).toBeVisible();
    expect(screen.getByRole("button", { name: "Apply Attachments" })).toBeVisible();
    expect(onAttached).not.toHaveBeenCalled();
  });
});
