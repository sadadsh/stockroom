import { screen, within } from "@testing-library/react";
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
    const browser = await screen.findByRole("region", { name: "Ultra Librarian Browser" });
    expect(within(workspace).getByRole("status")).toHaveTextContent("Download capture ready");
    expect(within(browser).getByRole("button", { name: "Back" })).toBeEnabled();
    expect(within(browser).getByRole("button", { name: "Forward" })).toBeEnabled();
    expect(within(browser).getByRole("button", { name: "Reload" })).toBeEnabled();
    expect(within(workspace).queryByRole("button", { name: "Use Downloaded Files" })).toBeNull();
    await user.click(within(browser).getByRole("button", { name: "Reload" }));
    expect(document.querySelector('[data-dev-id="shell.root"]')).toBeInTheDocument();
    expect(liveRequest).not.toHaveBeenCalled();
  });

  it("keeps selected-file recovery out of the active browser surface", async () => {
    const host = window as unknown as {
      __STOCKROOM_HOST__?: { pickFiles: (purpose: string) => Promise<string[]> };
    };
    const pickFiles = vi.fn().mockResolvedValue(["C:\\Downloads\\LM358DR.zip"]);
    host.__STOCKROOM_HOST__ = { pickFiles };
    try {
      const { liveRequest } = await mountScenario("provider.selected-file-recovery");
      const workspace = await screen.findByTestId("manage-models-workspace");
      expect(within(workspace).queryByRole("button", { name: "Use Downloaded Files" })).toBeNull();
      expect(pickFiles).not.toHaveBeenCalled();
      expect(document.querySelector('[data-dev-id="shell.root"]')).toBeInTheDocument();
      expect(liveRequest).not.toHaveBeenCalled();
    } finally {
      delete host.__STOCKROOM_HOST__;
    }
  });
});
