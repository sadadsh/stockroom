import type { OnboardingStatus, SettingsInfo } from "../../api/types";
import type { ScenarioFixture } from "../scenario";
import {
  createScenarioFixtureValidatorRegistry,
  isPrimaryEdaInfo,
} from "../scenarioFixtureValidation";
import { COMPONENT_FACETS } from "./componentFixtures";
import { stmFixtureValidators } from "./stmFixtures";

export const SETTINGS_READY: SettingsInfo = {
  primary_eda: "kicad", primary_eda_pending: null,
  primary_eda_confirmation_required: false, recommended_primary_eda: "kicad",
  primary_eda_requirements: ["symbol", "footprint", "model"], retained_optional_eda: ["altium"],
  eda_tools: [
    { key: "kicad", label: "KiCad", detected: true, selected: true, pending: false, setup_checks: ["installation", "catalog_wiring"], settings_target: "settings.kicad" },
    { key: "altium", label: "Altium Designer", detected: true, selected: false, pending: false, setup_checks: ["installation", "odbc", "catalog_connection"], settings_target: "settings.altium" },
  ],
  mouser_api_key_set: true, mouser_api_key_hint: "1234", github_token_set: false,
  github_token_hint: "", digikey_client_id: "fixture-client", digikey_client_secret_set: true,
  digikey_client_secret_hint: "5678", kicad_config_override: "", kicad_cli_override: "",
  kicad_config_dir: "C:\\Users\\Fixture\\AppData\\Roaming\\kicad\\10.0",
  kicad_cli_path: "C:\\Program Files\\KiCad\\10.0\\bin\\kicad-cli.exe",
  kicad_cli_available: true, kicad_wired: true, stm_cubemx_source: "C:\\ST\\STM32CubeMX",
};

export const SETTINGS_ONBOARDING: OnboardingStatus = {
  primary_eda: "kicad", primary_eda_pending: null,
  primary_eda_confirmation_required: false, recommended_primary_eda: "kicad",
  primary_eda_requirements: ["symbol", "footprint", "model"], retained_optional_eda: ["altium"],
  eda_tools: SETTINGS_READY.eda_tools,
  onboarded: true, first_run: false, libraries_root: "C:\\Stockroom", profiles: ["Main", "Archive"],
  under_git: true, default_dir: "C:\\Stockroom\\Main", libraries: [
    { name: "Main", path: "C:\\Stockroom\\Main", active: true, available: true, under_git: true },
    { name: "Archive", path: "C:\\Stockroom\\Archive", active: false, available: true, under_git: true },
  ],
};

export const SETTINGS_UPDATE = {
  update_available: false, state: "up_to_date", behind: 0,
  current_revision: "fixture", target_revision: "fixture", detail: "Current.",
};

export type SettingsFixtureOptions = {
  attention?: boolean;
  errorPath?: string;
  updateState?: string;
  syncState?: string;
  credentialsPartial?: boolean;
};

function read(path: string, response: unknown, errorPath?: string): ScenarioFixture {
  return {
    method: "GET", path, params: {}, body: undefined, response,
    behavior: errorPath === path ? { state: "error", status: 503, message: "Fixture service unavailable." } : undefined,
  };
}

/** Complete read model for the real Settings page and its production shell. */
export function settingsReadFixtures(options: SettingsFixtureOptions = {}): ScenarioFixture[] {
  const attention = options.attention ?? false;
  const settings = {
    ...SETTINGS_READY,
    kicad_wired: !attention,
    kicad_cli_available: !attention,
    mouser_api_key_set: options.credentialsPartial ? true : !attention,
    digikey_client_secret_set: options.credentialsPartial ? false : !attention,
    stm_cubemx_source: attention ? "" : SETTINGS_READY.stm_cubemx_source,
  };
  const sync = {
    has_remote: !attention, current_branch: "main", ahead: attention ? 2 : 0, behind: attention ? 3 : 0,
    github_auth: { mode: "git_credential_manager" as const, accounts: attention ? [] : ["fixture-owner"] },
    last_sync: options.syncState ? { state: options.syncState, pulled: false, pushed: false, converged: false, detail: options.syncState } : null,
  };
  const update = {
    ...SETTINGS_UPDATE,
    state: options.updateState ?? (attention ? "update_available" : "up_to_date"),
    update_available: (options.updateState ?? "") === "update_available" || attention,
    behind: attention ? 2 : 0,
  };
  return [
    read("/api/onboarding", SETTINGS_ONBOARDING, options.errorPath),
    read("/api/update/check", update, options.errorPath),
    read("/api/library/facets", COMPONENT_FACETS, options.errorPath),
    read("/api/settings", settings, options.errorPath),
    read("/api/sync/status", sync, options.errorPath),
    read("/api/altium/odbc-status", { installed: !attention, driver: "SQLite3 ODBC Driver", download_url: "https://example.invalid/odbc" }, options.errorPath),
    read("/api/system/info", { active_profile: "Main", part_count: 8, kicad_config_dir: settings.kicad_config_dir, kicad_running: false, kicad_cli_available: settings.kicad_cli_available, kicad_cli_path: settings.kicad_cli_path }, options.errorPath),
    read("/api/altium/status", { profile: "Main", dblib: "C:\\Stockroom\\Main\\altium\\Stockroom.DbLib", dblib_dir: "C:\\Stockroom\\Main\\altium", ready: attention ? 3 : 8, total: 8, datasource_present: !attention, rows: [] }, options.errorPath),
    read("/api/altium/embed-capability", { installed: true, binary: "C:\\Program Files\\Altium\\X2.EXE", requires_tool_installed: true, reason: attention ? "Altium is busy." : "", busy: attention ? "Altium Designer" : "", available: !attention }, options.errorPath),
    read("/api/altium/models-pending", { pending: [], count: 0 }, options.errorPath),
    read("/api/library/completion", { total: 8, complete: attention ? 3 : 8, needs_files: attention ? 5 : 0, unsourced: 0, by_requirement: {}, sources: ["ultralibrarian"], can_provide: ["kicad_symbol"] }, options.errorPath),
    read("/api/doctor/scan", { fixable: attention ? [{ kind: "drift", part_id: "fixture", detail: "Drift", before: "old", after: "new" }] : [], manual: [], uncommitted: [], healthy: !attention }, options.errorPath),
    read("/api/library/rescan/state", { parts: attention ? {} : { fixture: { checked_at: "2026-08-11T00:00:00Z", outcome: "updated" } }, counts: attention ? {} : { updated: 1 } }, options.errorPath),
    read("/api/library/lfs", { installed: true, version: "3.4.1", enabled: !attention, tracked_patterns: ["*.step"], objects: 8, legacy_blobs: attention ? 1 : 0, covers: ["*.step"], adopted: !attention, reason: attention ? "Needs adoption." : "" }, options.errorPath),
    read("/api/library/hygiene", { tracked: true, clean: !attention, missing: attention ? [".gitignore"] : [], extra: [], untracked: [], writes: [] }, options.errorPath),
    read("/api/library/cad", { cleared: attention ? 8 : 0, kept_stock: 0, items: [], failed: [], missing_files: [] }, options.errorPath),
    read("/api/library/derivation", { ruleset: "rules@2", counts: { "rules@2": attention ? 3 : 8 }, current: attention ? 3 : 8, stale: attention ? 5 : 0 }, options.errorPath),
  ];
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

const settingsPaths = [
  "/api/settings", "/api/sync/status", "/api/altium/odbc-status", "/api/system/info",
  "/api/altium/status", "/api/altium/embed-capability", "/api/altium/models-pending",
  "/api/library/completion", "/api/doctor/scan", "/api/library/rescan/state",
  "/api/library/lfs", "/api/library/hygiene", "/api/library/cad", "/api/library/derivation",
];

const settingsResponseValidators = Object.fromEntries(
  settingsPaths.map((path) => [
    `GET ${path}`,
    (fixture: ScenarioFixture) => fixture.body === undefined && isRecord(fixture.response),
  ]),
);
settingsResponseValidators["GET /api/settings"] = (fixture: ScenarioFixture) =>
  fixture.body === undefined &&
  isRecord(fixture.response) &&
  isPrimaryEdaInfo(fixture.response);

export const settingsFixtureValidators = createScenarioFixtureValidatorRegistry(
  settingsResponseValidators,
  stmFixtureValidators,
);
