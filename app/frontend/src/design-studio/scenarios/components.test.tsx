import { screen, within } from "@testing-library/react";
import { bootstrapScenarioRegistry } from ".";
import { componentScenarios } from "./components";
import { mountScenario } from "./testHarness";

const EXPECTED_COMPONENT_CASES = [
  "components.full-data",
  "components.empty",
  "components.loading",
  "components.server-error",
  "components.no-selection",
  "components.no-matches",
  "components.complete-only",
  "components.duplicates-only",
  "components.category-filter",
  "components.incomplete",
  "components.missing-model",
  "components.missing-symbol",
  "components.missing-footprint",
  "components.cad-source-conflict",
  "components.spec-conflict",
  "components.pinout-absent",
  "components.sourcing-sparse",
  "components.offer-failure",
  "components.documents-empty",
  "components.related-empty",
  "components.provenance-conflict",
  "components.preview-3d",
  "components.preview-symbol",
  "components.preview-footprint",
  "components.manage-models-ready",
  "components.manage-models-partial",
  "components.manage-models-blocked",
  "components.bulk-import",
  "components.offers-open",
  "components.manage-models-attached",
  "components.manage-models-invalid",
  "components.diff-open",
  "components.pinout-open",
  "components.delete-confirm",
] as const;

describe("Components Design Studio scenarios", () => {
  it("registers the exact Components case inventory with valid endpoint fixtures", () => {
    expect(componentScenarios.map((scenario) => scenario.id)).toEqual(EXPECTED_COMPONENT_CASES);
    expect(
      bootstrapScenarioRegistry.issues.filter((issue) =>
        issue.scenarioId?.startsWith("components."),
      ),
    ).toEqual([]);
  });

  it("mounts the real component workspace with every supported data region", async () => {
    const { liveRequest } = await mountScenario("components.full-data");
    for (const id of [
      "component-browser.cad-asset",
      "component-browser.offers-table",
      "component-browser.documents",
      "component-browser.related",
      "component-browser.provenance",
    ]) {
      expect(document.querySelector(`[data-dev-id="${id}"], [data-dev-role="${id}"]`)).toBeVisible();
    }
    expect(liveRequest).not.toHaveBeenCalled();
  });

  it.each(EXPECTED_COMPONENT_CASES)("mounts %s through the real application tree", async (id) => {
    const { liveRequest } = await mountScenario(id);
    const scenario = bootstrapScenarioRegistry.scenarioById(id);
    expect(scenario).toBeDefined();
    for (const target of scenario?.expectedTargets ?? []) {
      expect(document.querySelector(`[data-dev-id="${target}"], [data-dev-role="${target}"]`)).toBeInTheDocument();
    }
    expect(document.querySelector('[data-dev-id="shell.root"]')).toBeInTheDocument();
    expect(liveRequest).not.toHaveBeenCalled();
  });

  it("keeps the real Manage menu and provenance tabs clickable in preview", async () => {
    const { user, liveRequest } = await mountScenario("components.full-data");
    await user.click(await screen.findByRole("button", { name: "Manage" }));
    await user.click(screen.getByRole("menuitem", { name: "View Data Provenance..." }));
    const dialog = await screen.findByRole("dialog", { name: "Data Provenance" });
    await user.click(within(dialog).getByRole("tab", { name: "Changes" }));
    expect(document.querySelector('[data-dev-id="component-browser.sources.tab-changes"]')).toHaveAttribute(
      "aria-selected",
      "true",
    );
    expect(liveRequest).not.toHaveBeenCalled();
  });

  it("operates the real CAD visibility layers without replacing the workspace", async () => {
    const { user, liveRequest } = await mountScenario("components.full-data");
    const symbol = await screen.findByRole("region", { name: "Symbol" });
    await user.click(within(symbol).getByRole("button", { name: "Show Or Hide Drawn Detail" }));
    const names = within(symbol).getByRole("checkbox", { name: "Pin Names" });
    expect(names).toBeChecked();
    await user.click(names);
    expect(names).not.toBeChecked();
    expect(document.querySelector('[data-dev-id="shell.root"]')).toBeInTheDocument();
    expect(liveRequest).not.toHaveBeenCalled();
  });

  it("shows complete and partial provider choices together in Manage Models", async () => {
    const { liveRequest } = await mountScenario("components.manage-models-ready");
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(screen.getByText("EDAs")).toBeVisible();
    const providers = within(screen.getByRole("radiogroup", { name: "CAD model providers" }))
      .getAllByRole("radio");
    expect(providers.map((provider) => provider.textContent)).toEqual([
      expect.stringContaining("Ultra Librarian"),
      expect.stringContaining("SnapMagic"),
      expect.stringContaining("SamacSys"),
      expect.stringContaining("TraceParts"),
      expect.stringContaining("CADENAS"),
    ]);
    expect(providers[0]).toHaveTextContent("Complete Set");
    expect(providers[1]).toHaveTextContent("Complete Set");
    expect(providers[2]).toHaveTextContent("Missing 3D Model");
    expect(providers[4]).toBeDisabled();
    expect(liveRequest).not.toHaveBeenCalled();
  });
});
