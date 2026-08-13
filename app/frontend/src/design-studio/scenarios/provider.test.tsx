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

  it("clicks through the real Manage Models browser without live product I/O", async () => {
    const { user, liveRequest } = await mountScenario("provider.download-armed");
    const workspace = await screen.findByTestId("manage-models-workspace");
    const dialog = await screen.findByRole("dialog", { name: "Ultra Librarian Provider" });
    expect(within(workspace).getByRole("status")).toHaveTextContent("Download capture ready");
    expect(within(dialog).getByRole("button", { name: "Back" })).toBeEnabled();
    expect(within(dialog).getByRole("button", { name: "Forward" })).toBeEnabled();
    expect(within(dialog).getByRole("button", { name: "Reload" })).toBeEnabled();
    expect(within(workspace).getByRole("button", { name: "Choose Downloaded Files" })).toBeEnabled();
    await user.click(within(dialog).getByRole("button", { name: "Reload" }));
    expect(document.querySelector('[data-dev-id="shell.root"]')).toBeInTheDocument();
    expect(liveRequest).not.toHaveBeenCalled();
  });

  it("blocks selected-file recovery before the real host chooser while previewing", async () => {
    const host = window as unknown as {
      __STOCKROOM_HOST__?: { pickFiles: (purpose: string) => Promise<string[]> };
    };
    const pickFiles = vi.fn().mockResolvedValue(["C:\\Downloads\\LM358DR.zip"]);
    host.__STOCKROOM_HOST__ = { pickFiles };
    try {
      const { user, liveRequest } = await mountScenario("provider.selected-file-recovery");
      const workspace = await screen.findByTestId("manage-models-workspace");
      await user.click(within(workspace).getByRole("button", { name: "Choose Downloaded Files" }));
      expect(pickFiles).not.toHaveBeenCalled();
      await waitFor(() => expect(document.querySelector('[data-dev-id="toast.status"]')).toHaveTextContent(
        /Fixture preview blocked choosing CAD recovery files/i,
      ));
      expect(document.querySelector('[data-dev-id="shell.root"]')).toBeInTheDocument();
      expect(liveRequest).not.toHaveBeenCalled();
    } finally {
      delete host.__STOCKROOM_HOST__;
    }
  });
});
