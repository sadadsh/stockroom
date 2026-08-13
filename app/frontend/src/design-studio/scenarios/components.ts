import type { ComponentDossier } from "../../api/dossierTypes";
import type { PartSummary } from "../../api/types";
import {
  COMPONENT_ID,
  FULL_COMPONENT_SUMMARY,
  componentReadFixtures,
  fullComponentDossier,
} from "../fixtures/componentFixtures";
import type { DesignScenario, ScenarioUiState } from "../scenario";

export const componentScenarioIds = [
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

type ComponentScenarioId = (typeof componentScenarioIds)[number];

function cloneDossier(): ComponentDossier {
  return structuredClone(fullComponentDossier());
}

function scenario(
  id: ComponentScenarioId,
  options: {
    title: string;
    parts?: PartSummary[];
    dossier?: ComponentDossier;
    initialUi?: ScenarioUiState;
    expectedTargets?: string[];
    listParams?: Readonly<Record<string, string | readonly string[]>>;
    listBehavior?: ReturnType<typeof componentReadFixtures>[number]["behavior"];
    dossierBehavior?: ReturnType<typeof componentReadFixtures>[number]["behavior"];
  },
): DesignScenario {
  return {
    id,
    title: options.title,
    area: "components",
    group: "Components",
    route: "components",
    fixtures: componentReadFixtures(options),
    initialUi: options.initialUi ?? {},
    expectedTargets: options.expectedTargets ?? ["components.root"],
  };
}

const incomplete = cloneDossier();
incomplete.qualitySummary.completeness.score = 0.5;
incomplete.qualitySummary.completeness.missingExpected = ["Pin Count"];
incomplete.qualitySummary.blockingCount = 1;

function missingAsset(kind: "symbol" | "footprint" | "model"): ComponentDossier {
  const dossier = cloneDossier();
  dossier.cadAssets.kinds[kind] = {
    ...dossier.cadAssets.kinds[kind],
    status: "missing",
    tools: dossier.cadAssets.kinds[kind].tools.map((tool) => ({ ...tool, status: "missing", present: false })),
    issue: "No file is attached yet.",
  };
  return dossier;
}

const cadConflict = cloneDossier();
cadConflict.cadAssets.preference.mixed = true;
cadConflict.cadAssets.preference.provider = "";
cadConflict.cadAssets.preference.label = "Mixed Sources";

const specConflict = cloneDossier();
specConflict.keySpecifications[0] = {
  ...specConflict.keySpecifications[0],
  verificationState: "conflicting",
  conflictState: "conflicting",
};
specConflict.qualitySummary.stateCounts.verified = 1;
specConflict.qualitySummary.stateCounts.conflicting = 1;

const pinoutAbsent = cloneDossier();
pinoutAbsent.diagnostics.pinout = [];

const sparse = cloneDossier();
sparse.supplySummary = {
  ...sparse.supplySummary,
  offerCount: 0,
  providersInStock: [],
  totalStock: null,
  bestUnitPrice: null,
  bestUnitPriceProvider: "",
  lifecycle: "",
  manufacturerStatus: "",
  leadTime: "",
  factoryLeadTime: "",
  staleness: "unknown",
};
sparse.distributorOffers = [];
sparse.documents = { ...sparse.documents, items: [], count: 0, countsByType: {}, preferredDatasheet: null, preferredDatasheetReason: "", hasDatasheet: false };
sparse.relatedParts = [];
sparse.provenance = { ...sparse.provenance, sources: [], conflicts: [], manualOverrides: [] };
sparse.revisions = [];

const offerFailure = cloneDossier();
offerFailure.supplySummary.failures = [{ provider: "mouser", providerLabel: "Mouser", state: "timeout" }];

const documentsEmpty = cloneDossier();
documentsEmpty.documents = { ...documentsEmpty.documents, items: [], count: 0, countsByType: {}, preferredDatasheet: null, preferredDatasheetReason: "", hasDatasheet: false };

const relatedEmpty = cloneDossier();
relatedEmpty.relatedParts = [];

const partialProvider = cloneDossier();
partialProvider.cadSourceCoverage.completeProviders = [];
partialProvider.cadSourceCoverage.rows[0] = {
  ...partialProvider.cadSourceCoverage.rows[0],
  complete: false,
  model: { status: "unknown", origin: "", userAssertion: null },
};

const blockedProvider = cloneDossier();
blockedProvider.identity.manufacturer = "";

export const componentScenarios: readonly DesignScenario[] = [
  scenario("components.full-data", {
    title: "Full Data",
    expectedTargets: [
      "components.root",
      "component-browser.cad-asset",
      "component-browser.offers-table",
      "component-browser.documents",
      "component-browser.related",
      "component-browser.provenance",
    ],
  }),
  scenario("components.empty", { title: "Empty Library", parts: [], expectedTargets: ["components.empty"] }),
  scenario("components.loading", { title: "Loading", listBehavior: { state: "pending" }, expectedTargets: ["components.list-loading"] }),
  scenario("components.server-error", { title: "Server Error", listBehavior: { state: "error", status: 500, message: "Catalog unavailable" }, expectedTargets: ["components.list-failed"] }),
  scenario("components.no-selection", { title: "No Selection", initialUi: { components: { selectedId: null, autoSelect: false } }, expectedTargets: ["component-browser.empty"] }),
  scenario("components.no-matches", { title: "No Matches", parts: [], listParams: { q: "not-a-part" }, initialUi: { components: { filters: { query: "not-a-part" } } }, expectedTargets: ["components.list-no-match"] }),
  scenario("components.complete-only", { title: "Complete Only", parts: [FULL_COMPONENT_SUMMARY], listParams: { complete_only: "true" }, initialUi: { components: { filters: { completeOnly: true } } } }),
  scenario("components.duplicates-only", { title: "Duplicates Only", initialUi: { components: { filters: { duplicatesOnly: true } } } }),
  scenario("components.category-filter", { title: "Category Filter", listParams: { category: "ICs" }, initialUi: { components: { filters: { category: "ICs" } } } }),
  scenario("components.incomplete", { title: "Incomplete", parts: [{ ...FULL_COMPONENT_SUMMARY, is_complete: false, missing: ["Pin Count"] }], dossier: incomplete }),
  scenario("components.missing-model", { title: "Missing Model", dossier: missingAsset("model") }),
  scenario("components.missing-symbol", { title: "Missing Symbol", dossier: missingAsset("symbol") }),
  scenario("components.missing-footprint", { title: "Missing Footprint", dossier: missingAsset("footprint") }),
  scenario("components.cad-source-conflict", { title: "CAD Source Conflict", dossier: cadConflict }),
  scenario("components.spec-conflict", { title: "Specification Conflict", dossier: specConflict }),
  scenario("components.pinout-absent", { title: "Pinout Absent", dossier: pinoutAbsent }),
  scenario("components.sourcing-sparse", { title: "Sparse Sourcing", dossier: sparse }),
  scenario("components.offer-failure", { title: "Offer Failure", dossier: offerFailure }),
  scenario("components.documents-empty", { title: "Documents Empty", dossier: documentsEmpty }),
  scenario("components.related-empty", { title: "Related Empty", dossier: relatedEmpty }),
  scenario("components.provenance-conflict", { title: "Provenance Conflict", initialUi: { components: { surface: "provenance" } }, expectedTargets: ["component-browser.sources-sheet"] }),
  scenario("components.preview-3d", { title: "3D Preview", initialUi: { components: { preview: "model" } } }),
  scenario("components.preview-symbol", { title: "Symbol Preview", initialUi: { components: { preview: "symbol" } } }),
  scenario("components.preview-footprint", { title: "Footprint Preview", initialUi: { components: { preview: "footprint" } } }),
  scenario("components.manage-models-ready", { title: "Manage Models Ready", initialUi: { components: { cadView: "manage-models" } }, expectedTargets: ["component-browser.manage-models", "component-browser.eda-selection", "component-browser.provider-list"] }),
  scenario("components.manage-models-partial", { title: "Manage Models Partial", dossier: partialProvider, initialUi: { components: { cadView: "manage-models" }, provider: { state: "ready" } }, expectedTargets: ["component-browser.manage-models", "component-browser.provider-list"] }),
  scenario("components.manage-models-blocked", { title: "Manage Models Blocked", dossier: blockedProvider, initialUi: { components: { cadView: "manage-models" }, provider: { state: "unavailable" } }, expectedTargets: ["component-browser.manage-models", "component-browser.provider-status"] }),
  scenario("components.bulk-import", { title: "Bulk Import", initialUi: { addParts: { state: "empty" } }, expectedTargets: ["ingest.bulk"] }),
  scenario("components.offers-open", { title: "Price Breaks Open", initialUi: { components: { surface: "offers" } }, expectedTargets: ["component-browser.sourcing-sheet"] }),
  scenario("components.manage-models-attached", { title: "Manage Models Attached", initialUi: { components: { cadView: "manage-models" }, provider: { state: "complete" }, capture: { status: "done", backgrounded: false } }, expectedTargets: ["component-browser.manage-models", "component-browser.provider-status"] }),
  scenario("components.manage-models-invalid", { title: "Manage Models Invalid Files", initialUi: { components: { cadView: "manage-models" }, provider: { state: "error" }, capture: { status: "error", backgrounded: false } }, expectedTargets: ["component-browser.manage-models", "component-browser.provider-import"] }),
  scenario("components.diff-open", { title: "Diff Open", initialUi: { components: { surface: "provenance", sourcesTab: "changes" } }, expectedTargets: ["component-browser.sources-sheet"] }),
  scenario("components.pinout-open", { title: "Pinout Open", initialUi: { components: { surface: "pinout" } }, expectedTargets: ["component-browser.pinout-table"] }),
  scenario("components.delete-confirm", { title: "Delete Confirmation", initialUi: { components: { confirmDelete: true } } }),
];

// The canonical component identity is part of every dynamic target and endpoint, never an array index.
export const componentScenarioIdentity = COMPONENT_ID;
