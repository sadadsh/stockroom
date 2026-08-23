import { defineScenarioStateContracts } from "../scenarioStateContracts";

/* Product-owned state authority. Kept independent from scenario factories so deleting or renaming
 * a preview case cannot silently rewrite both sides of the parity gate. */
const globalContractIds = [
  "global.real-data", "global.onboarding.open", "global.onboarding.create", "global.onboarding.clone",
  "global.onboarding.error", "global.onboarding.create-error", "global.onboarding.clone-error",
  "global.rail.expanded", "global.rail.collapsed", "global.theme.dark", "global.theme.light",
  "global.update.current", "global.update.available", "global.update.updating", "global.update.error",
  "global.add-parts.empty", "global.add-parts.validating", "global.add-parts.exact", "global.add-parts.mismatch",
  "global.add-parts.duplicate", "global.add-parts.failure", "global.search.initial", "global.search.filtered", "global.search.empty", "global.search.error",
  "global.confirmation.neutral", "global.confirmation.destructive",
  "global.toast.neutral", "global.toast.success", "global.toast.error",
  "global.capture.active", "global.capture.backgrounded", "global.capture.complete", "global.capture.error", "global.offline",
  "global.service-error", "global.stale", "global.source-promotion.unavailable", "global.source-promotion.ready",
  "global.source-promotion.blocked", "global.source-promotion.success", "global.source-promotion.failure",
] as const;

const assetsContractIds = ["assets.landing"] as const;

const componentContractIds = [
  "components.full-data", "components.empty", "components.loading", "components.server-error",
  "components.no-selection", "components.no-matches", "components.complete-only", "components.duplicates-only",
  "components.category-filter", "components.incomplete", "components.missing-model", "components.missing-symbol",
  "components.missing-footprint", "components.cad-source-conflict", "components.spec-conflict", "components.pinout-absent",
  "components.sourcing-sparse", "components.offer-failure", "components.documents-empty", "components.related-empty",
  "components.provenance-conflict", "components.preview-3d", "components.preview-symbol", "components.preview-footprint",
  "components.offers-open",
  "components.diff-open", "components.pinout-open", "components.delete-confirm",
] as const;

const componentAssetContractIds = [
  "components.manage-models-ready", "components.manage-models-partial", "components.manage-models-blocked",
  "components.manage-models-attached", "components.manage-models-invalid",
] as const;

const providerContractIds = [
  "provider.loading", "provider.ready", "provider.sign-in", "provider.waiting-for-person",
  "provider.format-selection", "provider.download-armed", "provider.one-file", "provider.multiple-files",
  "provider.partial-retained", "provider.unavailable", "provider.timeout", "provider.canceled", "provider.error",
  "provider.selected-file-recovery", "provider.returned-to-stockroom", "provider.complete",
] as const;

const projectContractIds = [
  "projects.loading", "projects.empty", "projects.list-error", "projects.workspace-error",
  "projects.kicad.overview", "projects.kicad.bom", "projects.kicad.build", "projects.kicad.activity",
  "projects.altium.overview", "projects.altium.bom", "projects.altium.build", "projects.altium.activity",
  "projects.render-blocked", "projects.native-render-ready", "projects.missing-kicad", "projects.missing-altium",
  "projects.overlay-blocked", "projects.no-repository", "projects.diverged", "projects.shared-review",
  "projects.build-complete",
] as const;

const stmContractIds = [
  "stm.index-missing", "stm.index-building", "stm.index-error", "stm.explorer-loading", "stm.explorer-error", "stm.explorer-empty",
  "stm.explorer-matrix", "stm.explorer-selected-mcu", "stm.explorer-selected-package", "stm.explorer-selected-pin",
  "stm.explorer-pinout", "stm.explorer-af-options", "stm.target-definition", "stm.target-evidence",
  "stm.target-policy", "stm.target-package-map", "stm.compatibility-ready", "stm.compatibility-conflict",
  "stm.bench-part-selection", "stm.bench-socket-solution", "stm.bench-blocked",
] as const;

const settingsContractIds = [
  "settings.appearance.ready", "settings.libraries.ready", "settings.libraries.attention", "settings.libraries.error",
  "settings.libraries.create", "settings.libraries.clone", "settings.libraries.current",
  "settings.sync.ready",
  "settings.sync.attention", "settings.sync.error", "settings.sync.syncing", "settings.sync.diverged",
  "settings.kicad.ready", "settings.kicad.attention", "settings.kicad.error", "settings.kicad.picker",
  "settings.altium.ready", "settings.altium.attention", "settings.altium.error", "settings.altium.setup-dialog",
  "settings.altium.dblib-dialog", "settings.cubemx.ready", "settings.cubemx.attention", "settings.cubemx.error",
  "settings.cubemx.picker", "settings.distributors.ready", "settings.distributors.attention",
  "settings.distributors.error", "settings.distributors.credentials-partial", "settings.distributors.credentials-refresh", "settings.vendor-logins.ready",
  "settings.vendor-logins.attention",
  "settings.vendor-logins.error", "settings.github.ready", "settings.github.attention", "settings.github.error",
  "settings.update-store", "settings.updates.attention", "settings.updates.error", "settings.maintenance.ready",
  "settings.maintenance.attention", "settings.maintenance.error", "settings.completion.ready",
  "settings.completion.attention", "settings.completion.error", "settings.health.ready", "settings.health.attention",
  "settings.health.error", "settings.rescan.ready", "settings.rescan.attention", "settings.rescan.error",
  "settings.reset-cad.confirmation",
] as const;

export const globalStateContracts = defineScenarioStateContracts("global", "components", globalContractIds);
export const assetsStateContracts = defineScenarioStateContracts("assets", "assets", assetsContractIds);
export const componentStateContracts = defineScenarioStateContracts("components", "components", componentContractIds);
export const componentAssetStateContracts = defineScenarioStateContracts("assets", "assets", componentAssetContractIds);
export const providerStateContracts = defineScenarioStateContracts("assets", "assets", providerContractIds);
export const projectStateContracts = defineScenarioStateContracts("projects", "projects", projectContractIds);
export const stmStateContracts = defineScenarioStateContracts("stm", "stm", stmContractIds);
export const settingsStateContracts = defineScenarioStateContracts("settings", "settings", settingsContractIds);

export const bootstrapStateContracts = [
  ...globalStateContracts,
  ...assetsStateContracts,
  ...componentStateContracts,
  ...componentAssetStateContracts,
  ...providerStateContracts,
  ...projectStateContracts,
  ...stmStateContracts,
  ...settingsStateContracts,
] as const;
