import { screen, waitFor, within } from "@testing-library/react";
import { bootstrapScenarioRegistry } from ".";
import { providerScenarioIds } from "./provider";
import { mountScenario } from "./testHarness";

const EXPECTED_PROVIDER_CASES = [
  "provider.loading",
  "provider.ready",
  "provider.sign-in",
  "provider.waiting-for-person",
  "provider.format-selection",
  "provider.download-armed",
  "provider.one-file",
  "provider.multiple-files",
  "provider.partial-retained",
  "provider.unavailable",
  "provider.timeout",
  "provider.canceled",
  "provider.error",
  "provider.selected-file-recovery",
  "provider.returned-to-stockroom",
  "provider.complete",
] as const;

describe("provider-download Design Studio scenarios", () => {
  it("registers the exact provider case inventory with valid endpoint fixtures", () => {
    expect(providerScenarioIds).toEqual(EXPECTED_PROVIDER_CASES);
    expect(
      bootstrapScenarioRegistry.issues.filter((issue) => issue.scenarioId?.startsWith("provider.")),
    ).toEqual([]);
  });

  it.each(EXPECTED_PROVIDER_CASES)("mounts %s through the real application tree", async (id) => {
    const { liveRequest } = await mountScenario(id);
    const scenario = bootstrapScenarioRegistry.scenarioById(id);
    expect(scenario).toBeDefined();
    for (const target of scenario?.expectedTargets ?? []) {
      expect(document.querySelector(`[data-dev-id="${target}"], [data-dev-role="${target}"]`)).toBeInTheDocument();
    }
    expect(document.querySelector('[data-dev-id="shell.root"]')).toBeInTheDocument();
    expect(liveRequest).not.toHaveBeenCalled();
  });

  it("clicks through the real Complete Component provider trip without live product I/O", async () => {
    const { user, liveRequest } = await mountScenario("provider.download-armed");
    await user.click(await screen.findByRole("button", { name: "Manage" }));
    await user.click(screen.getByRole("menuitem", { name: "Review CAD Sources..." }));

    const dialog = await screen.findByRole("dialog", { name: "Review CAD Sources" });
    expect(within(dialog).getByText("The Provider Trip")).toBeVisible();
    expect(document.querySelector('[data-dev-id="component-browser.complete-component"]')).toBeVisible();
    expect(document.querySelector('[data-dev-id="component-browser.provider-browser"]')).toBeVisible();
    const showProvider = within(dialog).getByRole("button", { name: "Show Provider Page" });
    const returnToStockroom = within(dialog).getByRole("button", { name: "Return To Stockroom" });
    expect(showProvider).toBeEnabled();
    expect(returnToStockroom).toBeEnabled();
    expect(within(dialog).getByRole("button", { name: "Import Downloaded Files" })).toBeEnabled();
    await user.click(showProvider);
    await user.click(returnToStockroom);
    expect(screen.queryByRole("dialog", { name: "Review CAD Sources" })).not.toBeInTheDocument();
    expect(document.querySelector('[data-dev-id="shell.root"]')).toBeInTheDocument();
    expect(liveRequest).not.toHaveBeenCalled();
  });

  it("recovers a selected download through the real host chooser and an in-memory outcome", async () => {
    const host = window as unknown as {
      __STOCKROOM_HOST__?: { pickFiles: (purpose: string) => Promise<string[]> };
    };
    const pickFiles = vi.fn().mockResolvedValue(["C:\\Downloads\\LM358DR.zip"]);
    host.__STOCKROOM_HOST__ = { pickFiles };
    try {
      const { user, liveRequest } = await mountScenario("provider.selected-file-recovery");
      const dialog = await screen.findByRole("dialog", { name: "Review CAD Sources" });
      await user.click(within(dialog).getByRole("button", { name: "Import Downloaded Files" }));
      expect(pickFiles).toHaveBeenCalledWith("cad-recovery");
      await waitFor(() =>
        expect(document.querySelector('[data-dev-id="toast.status"]')).toHaveTextContent(
          /Attached 2 CAD roles/i,
        ),
      );
      expect(document.querySelector('[data-dev-id="shell.root"]')).toBeInTheDocument();
      expect(liveRequest).not.toHaveBeenCalled();
    } finally {
      delete host.__STOCKROOM_HOST__;
    }
  });
});
