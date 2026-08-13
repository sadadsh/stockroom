import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ProviderCoverageRow } from "../../api/dossierTypes";
import { makeDossier } from "../../test/dossierFixture";
import { ManageModelsWorkspace } from "./ManageModelsWorkspace";

function providerRow(id: string, complete: boolean): ProviderCoverageRow {
  return {
    id,
    label: id === "complete" ? "SnapEDA" : "Ultra Librarian",
    order: complete ? 2 : 1,
    url: `https://${id}.example`,
    urlKind: "evidence",
    instruction: "",
    needsLogin: false,
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
  it("shows every provider, places complete sets first, and waits for the person to open one", async () => {
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
    expect(providerButtons[0]).toHaveTextContent(complete.label);
    expect(providerButtons[0]).toHaveTextContent("Complete Set");
    expect(providerButtons[1]).toHaveTextContent(partial.label);
    expect(onOpenProvider).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "Open Provider" }));
    await waitFor(() => expect(onOpenProvider).toHaveBeenCalledWith(complete.id, [
      "kicad_symbol",
      "kicad_footprint",
      "kicad_model",
      "altium_symbol",
      "altium_footprint",
    ]));
  });

  it("uses every provider row as a person-chosen quick link", async () => {
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
    expect(onOpenProvider).toHaveBeenCalledWith("partial-b", [
      "kicad_symbol",
      "kicad_footprint",
      "kicad_model",
      "altium_symbol",
      "altium_footprint",
    ]);
    expect(providers[0]).toHaveTextContent("Missing 3D Model");
  });

  it("opens the selected provider in a closable modal while Manage Models stays mounted", async () => {
    const user = userEvent.setup();
    const dossier = makeDossier();
    dossier.cadSourceCoverage.rows = [providerRow("complete", true)];
    const onOpenProvider = vi.fn().mockResolvedValue(undefined);

    render(
      <ManageModelsWorkspace
        componentId="part-1"
        dossier={dossier}
        onView={vi.fn()}
        onOpenProvider={onOpenProvider}
      />,
    );

    expect(screen.queryByRole("dialog", { name: "SnapEDA Provider" })).toBeNull();
    await user.click(screen.getByRole("button", { name: "Open Provider" }));
    expect(await screen.findByRole("dialog", { name: "SnapEDA Provider" })).toBeVisible();
    expect(screen.getByTestId("manage-models-workspace")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Close Provider" }));

    expect(screen.queryByRole("dialog", { name: "SnapEDA Provider" })).toBeNull();
    expect(screen.getByTestId("manage-models-workspace")).toBeVisible();
    expect(onOpenProvider).toHaveBeenCalledTimes(1);
  });

  it("starts the provider task with only the selected EDAs", async () => {
    const user = userEvent.setup();
    const dossier = makeDossier();
    dossier.cadSourceCoverage.rows = [providerRow("complete", true)];
    const onOpenProvider = vi.fn().mockResolvedValue(undefined);

    render(
      <ManageModelsWorkspace
        componentId="part-1"
        dossier={dossier}
        onView={vi.fn()}
        onOpenProvider={onOpenProvider}
      />,
    );

    const kicad = screen.getByRole("checkbox", { name: "KiCad" });
    const altium = screen.getByRole("checkbox", { name: "Altium" });
    expect(kicad).toBeChecked();
    expect(altium).toBeChecked();

    await user.click(altium);
    await user.click(screen.getByRole("button", { name: "Open Provider" }));

    expect(onOpenProvider).toHaveBeenCalledWith("complete", [
      "kicad_symbol",
      "kicad_footprint",
      "kicad_model",
    ]);
    expect(kicad).toBeDisabled();
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

    await user.click(screen.getByRole("button", { name: "Choose Downloaded Files" }));
    expect(await screen.findByRole("status")).toHaveTextContent("3 CAD roles attached");
    expect(onAttached).toHaveBeenCalledTimes(1);
  });
});
