import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ProviderCoverageRow } from "../../api/dossierTypes";
import { runtimeDesignId } from "../../lib/designIdentity";
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

describe("ManageModelsWorkspace", () => {
  beforeEach(() => captureMocks.useOptionalCapture.mockReturnValue(null));
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
    expect(providerButtons.map((button) => button.textContent)).toEqual([
      partial.label,
      complete.label,
    ]);
    expect(
      providerButtons[0].querySelector(
        `[data-design-id="${runtimeDesignId("icon", "detail.provider")}"]`,
      ),
    ).not.toBeNull();
    expect(screen.queryByText("Complete Set")).toBeNull();
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

  it("never submits a useful provider URL that has no task-bound capture adapter", () => {
    const dossier = makeDossier();
    dossier.cadSourceCoverage.rows = [providerRow("mouser", false, false)];
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

    expect(screen.queryByRole("button", { name: "Open Provider" })).toBeNull();
    expect(screen.getByRole("link", { name: "Open Listing" })).toHaveAttribute(
      "href",
      "https://mouser.example",
    );
    expect(screen.getByText(/no task-bound Provider Visit/)).toBeVisible();
    expect(onOpenProvider).not.toHaveBeenCalled();
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

    expect(screen.getByRole("region", { name: "SnapEDA Browser" })).toBeVisible();
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

    await user.click(screen.getByRole("button", { name: "Hide Provider" }));
    expect(closeProvider).not.toHaveBeenCalled();
    expect(screen.queryByRole("region", { name: "SnapEDA Browser" })).toBeNull();
    expect(screen.getByRole("radio", { name: /Ultra Librarian/ })).toBeEnabled();

    await user.click(screen.getByRole("button", { name: "Show Provider" }));
    expect(showProvider).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("region", { name: "SnapEDA Browser" })).toBeVisible();
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
    await user.click(screen.getByRole("button", { name: "Hide Provider" }));
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

    await user.click(screen.getByRole("button", { name: "Hide Provider" }));
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
          inactive_evidence: [],
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
    await user.click(screen.getByRole("button", { name: "Commit Attachments" }));
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

  it("uses only the CAD tool selected in Settings", async () => {
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

    expect(screen.getByText(/Downloads follow Altium Designer/)).toBeVisible();
    expect(screen.queryByRole("checkbox")).toBeNull();

    await user.click(screen.getByRole("radio", { name: /SnapEDA/ }));

    expect(onOpenProvider).toHaveBeenCalledWith("complete", [
      "altium_symbol",
      "altium_footprint",
    ]);
  });

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
        onRecoverFiles={vi.fn().mockResolvedValue({ selected: 1, accepted: 3, outcome: "attached" })}
        onAttached={onAttached}
      />,
    );

    await user.click(screen.getByRole("button", { name: "Import Existing CAD Files" }));
    expect(await screen.findByRole("status")).toHaveTextContent("3 CAD roles attached");
    expect(onAttached).toHaveBeenCalledTimes(1);
  });
});
