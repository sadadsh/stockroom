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
  it("shows every provider, places complete sets first, and opens the best complete provider", async () => {
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
    await waitFor(() => expect(onOpenProvider).toHaveBeenCalledWith(complete.id));
  });

  it("keeps partial providers usable as a manual fallback", async () => {
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
    expect(providers[0]).toHaveTextContent("Missing 3D Model");
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
        onRecoverFiles={vi.fn().mockResolvedValue({ selected: 1, accepted: 3 })}
        onAttached={onAttached}
      />,
    );

    await user.click(screen.getByRole("button", { name: "Choose Downloaded Files" }));
    expect(await screen.findByRole("status")).toHaveTextContent("3 CAD roles attached");
    expect(onAttached).toHaveBeenCalledTimes(1);
  });
});
