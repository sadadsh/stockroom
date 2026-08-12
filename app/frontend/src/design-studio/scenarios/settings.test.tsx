import { cleanup, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { settingsScenarios } from "./settings";
import { mountScenario } from "./testHarness";

const SETTINGS_SCENARIO_INVENTORY = [
  "settings.appearance.ready",
  "settings.libraries.ready",
  "settings.libraries.attention",
  "settings.libraries.error",
  "settings.libraries.create",
  "settings.libraries.clone",
  "settings.libraries.current",
  "settings.sync.ready",
  "settings.sync.attention",
  "settings.sync.error",
  "settings.sync.syncing",
  "settings.sync.diverged",
  "settings.kicad.ready",
  "settings.kicad.attention",
  "settings.kicad.error",
  "settings.kicad.picker",
  "settings.altium.ready",
  "settings.altium.attention",
  "settings.altium.error",
  "settings.altium.setup-dialog",
  "settings.altium.dblib-dialog",
  "settings.cubemx.ready",
  "settings.cubemx.attention",
  "settings.cubemx.error",
  "settings.cubemx.picker",
  "settings.distributors.ready",
  "settings.distributors.attention",
  "settings.distributors.error",
  "settings.distributors.credentials-partial",
  "settings.distributors.credentials-refresh",
  "settings.vendor-logins.ready",
  "settings.vendor-logins.attention",
  "settings.vendor-logins.error",
  "settings.github.ready",
  "settings.github.attention",
  "settings.github.error",
  "settings.updates.ready",
  "settings.updates.attention",
  "settings.updates.error",
  "settings.maintenance.ready",
  "settings.maintenance.attention",
  "settings.maintenance.error",
  "settings.completion.ready",
  "settings.completion.attention",
  "settings.completion.error",
  "settings.health.ready",
  "settings.health.attention",
  "settings.health.error",
  "settings.rescan.ready",
  "settings.rescan.attention",
  "settings.rescan.error",
  "settings.reset-cad.confirmation",
] as const;

const READY_CASES = [
  ["appearance", "settings.appearance"],
  ["libraries", "settings.profiles"],
  ["sync", "settings.sync"],
  ["kicad", "settings.kicad"],
  ["altium", "settings.altium"],
  ["cubemx", "settings.cubemx"],
  ["distributors", "settings.distributor"],
  ["vendor-logins", "settings.vendor-login-row"],
  ["github", "settings.github"],
  ["updates", "settings.update"],
] as const;

afterEach(cleanup);

describe("Settings Design Studio scenarios", () => {
  it("registers the complete literal Settings inventory", () => {
    expect(settingsScenarios.map((scenario) => scenario.id)).toEqual(SETTINGS_SCENARIO_INVENTORY);
  });

  it.each(SETTINGS_SCENARIO_INVENTORY)("mounts the real Settings surface for %s", async (id) => {
    const mounted = await mountScenario(id);
    expect(document.querySelector('[data-dev-id="settings.root"]')).toBeInTheDocument();
    expect(mounted.liveRequest).not.toHaveBeenCalled();
  });

  it.each(READY_CASES)("mounts Settings %s with real controls", async (section, target) => {
    const mounted = await mountScenario(`settings.${section}.ready`);
    expect(document.querySelector(`[data-dev-id="${target}"]`)).toBeVisible();
    expect(screen.getAllByText("Settings").length).toBeGreaterThan(0);
    expect(mounted.liveRequest).not.toHaveBeenCalled();
  });
});
