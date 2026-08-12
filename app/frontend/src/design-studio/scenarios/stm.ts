import type { DesignScenario, ScenarioUiState } from "../scenario";
import { STM_STATUS, STM_TARGET_DEFINITION, stmReadFixtures, type StmFixtureOptions } from "../fixtures/stmFixtures";

export const stmScenarioIds = [
  "stm.index-missing", "stm.index-building", "stm.index-error", "stm.explorer-loading", "stm.explorer-error", "stm.explorer-empty", "stm.explorer-matrix", "stm.explorer-selected-mcu", "stm.explorer-selected-package", "stm.explorer-selected-pin", "stm.explorer-pinout", "stm.explorer-af-options", "stm.target-definition", "stm.target-evidence", "stm.target-policy", "stm.target-package-map", "stm.compatibility-ready", "stm.compatibility-conflict", "stm.bench-part-selection", "stm.bench-socket-solution", "stm.bench-blocked",
] as const;

type StmScenarioId = (typeof stmScenarioIds)[number];

function scenario(id: StmScenarioId, title: string, fixtures: StmFixtureOptions = {}, initialUi: ScenarioUiState = {}, expectedTargets = ["stm.root"]): DesignScenario {
  return { id, title, area: "stm", group: "STM Viewer", route: "stm", fixtures: stmReadFixtures(fixtures), initialUi, expectedTargets };
}

const unavailable = { ...STM_STATUS, built: false, source_present: false };
export const stmScenarios: readonly DesignScenario[] = [
  scenario("stm.index-missing", "Index Missing", { status: unavailable, mcusBehavior: { state: "error", status: 409, message: "STM index not built" } }),
  scenario("stm.index-building", "Index Building", { status: { ...unavailable, building: true }, mcusBehavior: { state: "error", status: 409, message: "STM index is building" } }),
  scenario("stm.index-error", "Index Error", { status: unavailable, mcusBehavior: { state: "error", status: 409, message: "STM index unavailable" } }),
  scenario("stm.explorer-loading", "Explorer Loading", { mcusBehavior: { state: "pending" } }),
  scenario("stm.explorer-error", "Explorer Error", { mcusBehavior: { state: "error", status: 503, message: "Matrix unavailable" } }),
  scenario("stm.explorer-empty", "Explorer Empty", { mcus: { mcus: [], count: 0, facets: { family: {}, core: {}, package: {}, series: {} } } }),
  scenario("stm.explorer-matrix", "Explorer Matrix"),
  scenario("stm.explorer-selected-mcu", "Selected MCU", {}, { stm: { activePart: "STM32F407V(E-G)Tx" } }),
  scenario("stm.explorer-selected-package", "Selected Package", {}, { stm: { activePart: "STM32F407V(E-G)Tx", pinoutView: "map" } }),
  scenario("stm.explorer-selected-pin", "Selected Pin", {}, { stm: { activePart: "STM32F407V(E-G)Tx", selectedPosition: "23" } }),
  scenario("stm.explorer-pinout", "Pinout", {}, { stm: { activePart: "STM32F407V(E-G)Tx", pinoutView: "table" } }),
  scenario("stm.explorer-af-options", "Alternate Functions", {}, { stm: { activePart: "STM32F407V(E-G)Tx", selectedPosition: "23" } }),
  scenario("stm.target-definition", "Target Definition", {}, { stm: { tab: "compatibility", targetDefinition: STM_TARGET_DEFINITION } }, ["stm.root", "stm.target-definition"]),
  scenario("stm.target-evidence", "Target Evidence", {}, { stm: { tab: "compatibility", targetDefinition: STM_TARGET_DEFINITION } }, ["stm.root", "stm.target-definition"]),
  scenario("stm.target-policy", "Target Policy", {}, { stm: { tab: "compatibility", showTargetPolicy: true } }, ["stm.root", "stm.bench", "stm.target-policy"]),
  scenario("stm.target-package-map", "Target Package Map", {}, { stm: { tab: "compatibility", targetDefinition: STM_TARGET_DEFINITION } }, ["stm.root", "stm.target-definition", "stm.target-map"]),
  scenario("stm.compatibility-ready", "Compatibility Ready", {}, { stm: { tab: "compatibility" } }),
  scenario("stm.compatibility-conflict", "Compatibility Conflict", {}, { stm: { tab: "compatibility" } }),
  scenario("stm.bench-part-selection", "Bench Part Selection", {}, { stm: { tab: "compatibility" } }),
  scenario("stm.bench-socket-solution", "Bench Socket Solution", {}, { stm: { tab: "compatibility" } }),
  scenario("stm.bench-blocked", "Bench Blocked", { status: unavailable }, { stm: { tab: "compatibility" } }),
];
