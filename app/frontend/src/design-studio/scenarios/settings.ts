import type { DesignScenario, ScenarioUiState } from "../scenario";
import { settingsReadFixtures } from "../fixtures/settingsFixtures";

export const settingsScenarioIds = [
  "settings.appearance.ready", "settings.libraries.ready", "settings.libraries.attention", "settings.libraries.error",
  "settings.libraries.create", "settings.libraries.clone", "settings.libraries.current",
  "settings.sync.ready", "settings.sync.attention", "settings.sync.error", "settings.sync.syncing", "settings.sync.diverged",
  "settings.kicad.ready", "settings.kicad.attention", "settings.kicad.error", "settings.kicad.picker",
  "settings.altium.ready", "settings.altium.attention", "settings.altium.error", "settings.altium.setup-dialog", "settings.altium.dblib-dialog",
  "settings.cubemx.ready", "settings.cubemx.attention", "settings.cubemx.error", "settings.cubemx.picker",
  "settings.distributors.ready", "settings.distributors.attention", "settings.distributors.error", "settings.distributors.credentials-partial", "settings.distributors.credentials-refresh",
  "settings.vendor-logins.ready", "settings.vendor-logins.attention", "settings.vendor-logins.error",
  "settings.github.ready", "settings.github.attention", "settings.github.error",
  "settings.updates.ready", "settings.updates.attention", "settings.updates.error",
  "settings.maintenance.ready", "settings.maintenance.attention", "settings.maintenance.error",
  "settings.completion.ready", "settings.completion.attention", "settings.completion.error",
  "settings.health.ready", "settings.health.attention", "settings.health.error",
  "settings.rescan.ready", "settings.rescan.attention", "settings.rescan.error", "settings.reset-cad.confirmation",
] as const;

type SettingsScenarioId = typeof settingsScenarioIds[number];

function stateFor(id: SettingsScenarioId): { group: NonNullable<ScenarioUiState["settings"]>["group"]; target: string; errorPath?: string } {
  if (id.includes("appearance") || id.includes("updates")) return { group: "general", target: id.includes("updates") ? "settings.update" : "settings.appearance", errorPath: id.endsWith(".error") ? "/api/update/check" : undefined };
  if (id.includes("libraries")) return { group: "library", target: "settings.profiles", errorPath: id.endsWith(".error") ? "/api/onboarding" : undefined };
  if (id.includes("sync")) return { group: "library", target: "settings.sync", errorPath: id.endsWith(".error") ? "/api/sync/status" : undefined };
  if (id.includes("github")) return { group: "library", target: "settings.github", errorPath: id.endsWith(".error") ? "/api/sync/status" : undefined };
  if (id.includes("kicad")) return { group: "eda", target: "settings.kicad", errorPath: id.endsWith(".error") ? "/api/system/info" : undefined };
  if (id.includes("altium")) return { group: "eda", target: id.endsWith("setup-dialog") ? "altiumdb.setup-modal" : id.endsWith("dblib-dialog") ? "altiumdb.modal" : "settings.altium", errorPath: id.endsWith(".error") ? "/api/altium/status" : undefined };
  if (id.includes("cubemx")) return { group: "eda", target: "settings.cubemx", errorPath: id.endsWith(".error") ? "/api/settings" : undefined };
  if (id.includes("distributors") || id.includes("vendor-logins")) return { group: "sources", target: id.includes("vendor-logins") ? "settings.vendor-login-row" : "settings.distributor", errorPath: id.endsWith(".error") ? "/api/settings" : undefined };
  if (id.includes("rescan")) return { group: "sources", target: "settings.rescan", errorPath: id.endsWith(".error") ? "/api/library/rescan/state" : undefined };
  if (id.includes("health")) return { group: "maintenance", target: "settings.health", errorPath: id.endsWith(".error") ? "/api/doctor/scan" : undefined };
  if (id.includes("completion")) return { group: "maintenance", target: "settings.completion", errorPath: id.endsWith(".error") ? "/api/library/completion" : undefined };
  if (id.includes("reset-cad")) return { group: "maintenance", target: "confirm.root" };
  return { group: "maintenance", target: "settings.completion", errorPath: id.endsWith(".error") ? "/api/doctor/scan" : undefined };
}

function scenario(id: SettingsScenarioId): DesignScenario {
  const state = stateFor(id);
  const attention = id.endsWith(".attention") || id.endsWith(".diverged") || id.endsWith(".syncing") || id.endsWith("credentials-partial");
  const initialSettings: NonNullable<ScenarioUiState["settings"]> = {
    group: state.group,
    altiumDialog: id.endsWith("setup-dialog") ? "setup" : id.endsWith("dblib-dialog") ? "dblib" : undefined,
    confirmResetCad: id.endsWith("reset-cad.confirmation"),
    picker: id.endsWith("kicad.picker") ? "kicad" : id.endsWith("cubemx.picker") ? "cubemx" : undefined,
  };
  return {
    id, title: id.split(".").slice(1).join(" "), area: "settings", group: "Settings", route: "settings",
    fixtures: settingsReadFixtures({
      attention, errorPath: state.errorPath,
      updateState: id.includes("updates.attention") ? "update_available" : undefined,
      syncState: id.endsWith(".syncing") ? "syncing" : id.endsWith(".diverged") ? "diverged" : undefined,
      credentialsPartial: id.endsWith("credentials-partial"),
    }),
    initialUi: { settings: initialSettings }, expectedTargets: [state.target],
  };
}

export const settingsScenarios: readonly DesignScenario[] = settingsScenarioIds.map(scenario);
