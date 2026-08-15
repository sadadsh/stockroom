import type { LandPattern, SymbolGeometry } from "../../api/client";
import type {
  ComponentDossier,
  CoverageStatus,
  ProviderArtifactCoverage,
  ProviderCoverageRow,
  RepresentationKind,
  RepresentationStatus,
  RepresentationView,
} from "../../api/dossierTypes";
import type {
  DuplicatesResponse,
  Facets,
  OnboardingStatus,
  PartShell,
  PartSummary,
  PartsResponse,
} from "../../api/types";
import type { ScenarioFixture } from "../scenario";
import type { CadVariantDocument } from "../../api/cadVariantClient";
import {
  bootstrapFixtureValidators,
  createScenarioFixtureValidatorRegistry,
} from "../scenarioFixtureValidation";

export const COMPONENT_ID = "component-ti-lm358dr";

export const ONBOARDING_READY: OnboardingStatus = {
  onboarded: true,
  first_run: false,
  libraries_root: "C:\\Stockroom",
  profiles: [],
  under_git: true,
  default_dir: "C:\\Stockroom\\Components",
  libraries: [{
    name: "Components",
    path: "C:\\Stockroom\\Components",
    active: true,
    available: true,
    under_git: true,
  }],
};

export const FULL_COMPONENT_SUMMARY: PartSummary = {
  id: COMPONENT_ID,
  display_name: "LM358",
  category: "ICs",
  mpn: "LM358DR",
  manufacturer: "Texas Instruments",
  package: "SOIC-8",
  is_complete: true,
  missing: [],
  eda_readiness: {
    kicad: { required: ["symbol", "footprint", "model"], missing: [], coverage_complete: true, trust: "pass", ready: true },
    altium: { required: ["symbol", "footprint", "model"], missing: [], coverage_complete: true, trust: "pass", ready: true },
  },
};

export const SECOND_COMPONENT_SUMMARY: PartSummary = {
  ...FULL_COMPONENT_SUMMARY,
  id: "component-ti-lm358dr-duplicate",
  display_name: "LM358 Alternate Record",
  is_complete: false,
  missing: ["model"],
};

function coverage(status: CoverageStatus, origin: ProviderArtifactCoverage["origin"] = "official_api"): ProviderArtifactCoverage {
  return { status, origin, userAssertion: null };
}

function providerRow(): ProviderCoverageRow {
  const statusCounts: Record<CoverageStatus, number> = {
    unknown: 0,
    available: 3,
    not_available: 0,
    downloaded: 0,
    validated: 0,
  };
  return {
    id: "ultralibrarian",
    label: "Ultra Librarian",
    order: 10,
    url: "https://example.invalid/ultralibrarian/lm358dr",
    urlKind: "evidence",
    instruction: "Sign in if asked, select KiCad and Altium, then download the complete set.",
    needsLogin: true,
    aggregator: true,
    distributor: false,
    statusCounts,
    complete: true,
    symbol: coverage("available"),
    footprint: coverage("available"),
    model: coverage("available"),
    kicad: { count: 3, total: 3, summary: "3/3", complete: true, supported: true },
    altium: { count: 3, total: 3, summary: "3/3", complete: true, supported: true },
  };
}

function providerVariant(
  base: ProviderCoverageRow,
  options: {
    id: string;
    label: string;
    order: number;
    statuses: readonly [CoverageStatus, CoverageStatus, CoverageStatus];
    reachable?: boolean;
  },
): ProviderCoverageRow {
  const [symbolStatus, footprintStatus, modelStatus] = options.statuses;
  const suppliedStatuses = new Set<CoverageStatus>(["available", "downloaded", "validated"]);
  const suppliedCount = options.statuses.filter((status) => suppliedStatuses.has(status)).length;
  const complete = suppliedCount === 3;
  const statusCounts: Record<CoverageStatus, number> = {
    unknown: options.statuses.filter((status) => status === "unknown").length,
    available: options.statuses.filter((status) => status === "available").length,
    not_available: options.statuses.filter((status) => status === "not_available").length,
    downloaded: options.statuses.filter((status) => status === "downloaded").length,
    validated: options.statuses.filter((status) => status === "validated").length,
  };
  const toolCoverage = {
    count: suppliedCount,
    total: 3,
    summary: `${suppliedCount}/3`,
    complete,
    supported: suppliedCount > 0,
  };
  return {
    ...base,
    id: options.id,
    label: options.label,
    order: options.order,
    url: options.reachable === false ? "" : `https://example.invalid/${options.id}/lm358dr`,
    statusCounts,
    complete,
    symbol: coverage(symbolStatus),
    footprint: coverage(footprintStatus),
    model: coverage(modelStatus),
    kicad: toolCoverage,
    altium: toolCoverage,
  };
}

function representation(
  kind: RepresentationKind,
  status: RepresentationStatus = "ready",
): RepresentationView {
  return {
    kind,
    status,
    selectedTool: "kicad",
    tools: [{
      tool: "kicad",
      toolLabel: "KiCad",
      status: status === "missing" ? "missing" : "ready",
      present: status !== "missing",
      embedded: kind === "model",
      reference: {
        lib: kind === "model" ? "" : "SR-ICs",
        name: kind === "model" ? "" : kind === "symbol" ? "LM358" : "SOIC-8",
        file: kind === "model" ? "models/lm358.step" : "",
      },
      sourceId: "ultralibrarian",
      sourceLabel: "Ultra Librarian",
      sourceUrl: "https://example.invalid/ultralibrarian/lm358dr",
      capturedAt: "2026-08-11T12:00:00Z",
      checks: [],
    }],
    sourceLabel: "Ultra Librarian",
    issue: status === "missing" ? "No file is attached yet." : null,
  };
}

export function fullComponentDossier(): ComponentDossier {
  const sourceCandidate = {
    sourceId: "digikey",
    sourceLabel: "DigiKey",
    tier: "distributor" as const,
    tierLabel: "Authorised Distributor",
    value: "3.3",
    displayValue: "3.3",
    normalizedValue: null,
    unit: "V",
    confidence: "high",
    retrievedAt: "2026-08-11T12:00:00Z",
    originalKey: "Supply Voltage",
  };
  const keySpec = {
    key: "supply_voltage",
    label: "Supply Voltage",
    group: "electrical",
    groupLabel: "Electrical",
    order: 10,
    valueType: "quantity" as const,
    preferredValue: "3.3",
    normalizedValue: null,
    displayValue: "3.3",
    unit: "V",
    applicability: "applicable" as const,
    importance: "primary" as const,
    verificationState: "verified" as const,
    sourceCandidates: [sourceCandidate],
    preferredSource: sourceCandidate,
    override: null,
    preferredSourcePin: null,
    confidence: "high",
    conflictState: "none" as const,
    expectedForCategory: true,
    filterable: true,
    sortable: true,
    comparable: true,
    mapped: true,
    constraint: null,
    constraintViolation: null,
  };
  const document = {
    id: "datasheet-ti-lm358dr-r1",
    documentType: "datasheet" as const,
    documentTypeLabel: "Datasheet",
    title: "LM358 Datasheet",
    revision: "R1",
    manufacturer: "Texas Instruments",
    sourceType: "manufacturer" as const,
    sourceId: "ti",
    sourceLabel: "Texas Instruments",
    localPath: "datasheets/lm358dr.pdf",
    remoteUrl: "https://example.invalid/ti/lm358dr.pdf",
    mimeType: "application/pdf",
    host: "example.invalid",
    isPreferred: true,
    isCurrent: true,
    retrievedAt: "2026-08-11T12:00:00Z",
    verifiedAt: "2026-08-11T12:05:00Z",
    status: "stored" as const,
  };
  const row = providerRow();
  const providerRows = [
    row,
    providerVariant(row, {
      id: "snapmagic",
      label: "SnapMagic",
      order: 20,
      statuses: ["available", "available", "available"],
    }),
    providerVariant(row, {
      id: "samacsys",
      label: "SamacSys",
      order: 30,
      statuses: ["available", "available", "not_available"],
    }),
    providerVariant(row, {
      id: "traceparts",
      label: "TraceParts",
      order: 40,
      statuses: ["unknown", "unknown", "available"],
    }),
    providerVariant(row, {
      id: "cadenas",
      label: "CADENAS",
      order: 50,
      statuses: ["unknown", "unknown", "unknown"],
      reachable: false,
    }),
  ];
  return {
    schemaVersion: 2,
    identity: {
      id: COMPONENT_ID,
      displayName: "LM358",
      mpn: "LM358DR",
      manufacturer: "Texas Instruments",
      category: "ICs",
      categorySchema: { key: "ics", label: "Integrated Circuits", parent: "" },
      partClass: "component",
      value: "LM358DR",
      package: "SOIC-8",
      pinCount: 8,
      lifecycle: "Active",
      tags: ["op-amp"],
      manufacturerPage: {
        url: "https://example.invalid/ti/lm358dr",
        host: "example.invalid",
        sourceId: "ti",
        sourceLabel: "Texas Instruments",
        state: "verified",
        verified: true,
        reason: "manufacturer host",
        checkedAt: "2026-08-11T12:00:00Z",
        rejectedCandidates: [],
      },
    },
    qualitySummary: {
      description: "Dual Operational Amplifier",
      completeness: {
        score: 1,
        expectedPresent: 1,
        expectedTotal: 1,
        recommendedPresent: 0,
        recommendedTotal: 0,
        missingExpected: [],
        missingRecommended: [],
        basis: "ics",
      },
      stateCounts: {
        missing: 0,
        not_reported: 0,
        not_applicable: 0,
        unverified: 0,
        conflicting: 0,
        verified: 2,
      },
      attention: [],
      blockingCount: 0,
      missingPassportFields: [],
    },
    keySpecifications: [keySpec],
    specificationGroups: [{ id: "electrical", label: "Electrical", count: 1, specifications: [keySpec] }],
    cadAssets: {
      kinds: {
        symbol: representation("symbol"),
        footprint: representation("footprint"),
        model: representation("model"),
      },
      preference: {
        provider: "ultralibrarian",
        label: "Ultra Librarian",
        mixed: false,
        pinned: true,
        reviewedAt: "2026-08-11T12:00:00Z",
        assets: {
          symbol: { provider: "ultralibrarian", label: "Ultra Librarian", origin: "set_preference" },
          footprint: { provider: "ultralibrarian", label: "Ultra Librarian", origin: "set_preference" },
          model: { provider: "ultralibrarian", label: "Ultra Librarian", origin: "set_preference" },
        },
        assetLabels: { symbol: "Symbol", footprint: "Footprint", model: "3D Model" },
        options: [],
      },
      tools: [{ key: "kicad", label: "KiCad" }, { key: "altium", label: "Altium" }],
      validationRelationships: [],
    },
    cadSourceCoverage: {
      artifacts: ["symbol", "footprint", "model"],
      statuses: ["unknown", "available", "not_available", "downloaded", "validated"],
      tools: ["kicad", "altium"],
      completeProviders: providerRows.filter((provider) => provider.complete).map((provider) => provider.id),
      rows: providerRows,
    },
    supplySummary: {
      offerCount: 2,
      providersInStock: ["digikey", "mouser"],
      totalStock: 1512,
      bestUnitPrice: 0.38,
      bestUnitPriceCurrency: "$",
      bestUnitPriceProvider: "mouser",
      lifecycle: "Active",
      manufacturerStatus: "Active",
      leadTime: "In Stock",
      factoryLeadTime: "12 weeks",
      staleness: "fresh",
      failures: [],
    },
    distributorOffers: [
      {
        provider: "digikey",
        providerLabel: "DigiKey",
        sku: "296-LM358DR-ND",
        stock: 512,
        currency: "$",
        unitPrice: 0.42,
        priceBreaks: [{ qty: 1, price: 0.42 }, { qty: 100, price: 0.34 }],
        moq: 1,
        leadTime: "In Stock",
        factoryLeadTime: "12 weeks",
        lifecycle: "Active",
        offerUrl: "https://example.invalid/digikey/lm358dr",
        lastCheckedAt: "2026-08-11T12:00:00Z",
        staleness: "fresh",
        failureState: "",
      },
      {
        provider: "mouser",
        providerLabel: "Mouser",
        sku: "595-LM358DR",
        stock: 1000,
        currency: "$",
        unitPrice: 0.38,
        priceBreaks: [{ qty: 1, price: 0.38 }, { qty: 100, price: 0.31 }],
        moq: 1,
        leadTime: "In Stock",
        factoryLeadTime: "12 weeks",
        lifecycle: "Active",
        offerUrl: "https://example.invalid/mouser/lm358dr",
        lastCheckedAt: "2026-08-11T12:00:00Z",
        staleness: "fresh",
        failureState: "",
      },
    ],
    officialApiData: {
      providerCount: 2,
      fieldCount: 4,
      providers: [
        {
          provider: "digikey",
          providerLabel: "DigiKey",
          state: "success",
          fetchedAt: "2026-08-11T12:00:00Z",
          payloadRef: "sourced/lm358dr/digikey.json",
          fieldCount: 2,
          rows: [
            { path: "product_details.Product.QuantityAvailable", endpoint: "product_details", kind: "number", value: 512, displayValue: "512" },
            { path: "product_details.Product.Parameters[0].ValueText", endpoint: "product_details", kind: "string", value: "3.3 V", displayValue: "3.3 V" },
          ],
        },
        {
          provider: "mouser",
          providerLabel: "Mouser",
          state: "success",
          fetchedAt: "2026-08-11T12:00:00Z",
          payloadRef: "sourced/lm358dr/mouser.json",
          fieldCount: 2,
          rows: [
            { path: "SearchResults.Parts[0].AvailabilityInStock", endpoint: "SearchResults", kind: "number", value: 1000, displayValue: "1000" },
            { path: "SearchResults.Parts[0].ProductAttributes[0].AttributeValue", endpoint: "SearchResults", kind: "string", value: "5 V", displayValue: "5 V" },
          ],
        },
      ],
    },
    documents: {
      types: ["datasheet", "datasheet_page", "package_drawing", "application_note", "pcn", "pdn", "compliance_declaration", "certificate", "attachment", "other"],
      items: [document],
      count: 1,
      countsByType: { datasheet: 1 },
      preferredDatasheet: document,
      preferredDatasheetReason: "Official manufacturer PDF",
      hasDatasheet: true,
    },
    relatedParts: [{
      mpn: "LM358ADR",
      manufacturer: "Texas Instruments",
      description: "Dual operational amplifier",
      url: "https://example.invalid/ti/lm358adr",
      provider: "digikey",
      providerLabel: "DigiKey",
      relation: "substitutions",
      relationLabel: "Potential Substitutions",
      reason: "substitution",
      reasonLabel: "Offered as a substitution",
      evidence: [],
      validated: false,
    }],
    provenance: {
      sources: [{
        id: "digikey",
        label: "DigiKey",
        state: "success",
        fieldCount: 2,
        fetchedAt: "2026-08-11T12:00:00Z",
        payloadRef: "sourced/lm358dr/digikey.json",
      }],
      recordFields: [],
      conflicts: [{
        field: "supply_voltage",
        label: "Supply Voltage",
        group: "Electrical",
        inForce: "3.3 V",
        inForceSource: "DigiKey",
        candidates: [
          { sourceId: "digikey", sourceLabel: "DigiKey", displayValue: "3.3 V", inForce: true },
          { sourceId: "mouser", sourceLabel: "Mouser", displayValue: "5 V", inForce: false },
        ],
      }],
      manualOverrides: [],
      compatibility: { isFutureRecord: false, readOnlyFieldCount: 0, fields: [], hasNotice: false },
      raw: {
        levels: [],
        canonical: { count: 0, fields: [] },
        sourceFields: { count: 0, items: [] },
        evidence: { count: 0, items: [] },
      },
    },
    revisions: [{
      kind: "source_fetched",
      kindLabel: "Source Read",
      section: "intake",
      sectionLabel: "Import and Enrichment History",
      at: "2026-08-11T12:00:00Z",
      summary: "DigiKey supplied data",
      detail: "",
    }],
    diagnostics: {
      recordSchemaVersion: 4,
      isFutureRecord: false,
      derivedBy: "rules@1",
      hashes: { symbolContent: "symbol", footprintContent: "footprint", modelFile: "model" },
      unknownKeys: [],
      categorySchema: "ics",
      groups: [],
      pinout: [
        { pin: "1", name: "OUT1", type: "output" },
        { pin: "2", name: "IN1-", type: "input" },
      ],
      pinCount: 8,
      facets: [],
      comparisonFields: [],
    },
  };
}

export const COMPONENT_FACETS: Facets = {
  by_category: { ICs: 2, Resistors: 1 },
  category_catalog: ["ICs", "Resistors"],
  by_manufacturer: { "Texas Instruments": 2 },
  complete: 1,
  incomplete: 1,
};

export const COMPONENT_DUPLICATES: DuplicatesResponse = {
  by_mpn: [{ key: "LM358DR", parts: [FULL_COMPONENT_SUMMARY, SECOND_COMPONENT_SUMMARY] }],
  by_footprint: [],
};

export const COMPONENT_SHELL: PartShell = {
  supported: false,
  component_directory: false,
  export_formats: [],
  eda_applications: [],
};

export const COMPONENT_SYMBOL_GEOMETRY: SymbolGeometry = {
  units: "mm",
  name: "LM358",
  // Keep only the short functional marks an op-amp drawing needs. The old fake OUT1/IN1 labels
  // sprawled across a tiny rectangle and taught screenshot review to accept a symbol no EDA tool
  // would show; output and supply names remain KiCad's hidden `~` while + and - stay readable.
  namesHidden: false,
  numbersHidden: false,
  pins: [
    { number: "1", name: "~", electrical: "output", style: "line", at: [5, 2.5], angle: 180, length: 2.5, hidden: false },
    { number: "2", name: "-", electrical: "input", style: "inverted", at: [-5, 3.5], angle: 0, length: 2.5, hidden: false },
    { number: "3", name: "+", electrical: "input", style: "line", at: [-5, 1.5], angle: 0, length: 2.5, hidden: false },
    { number: "4", name: "~", electrical: "power_in", style: "line", at: [0, -7], angle: 90, length: 2.5, hidden: false },
    { number: "5", name: "+", electrical: "input", style: "line", at: [-5, -1.5], angle: 0, length: 2.5, hidden: false },
    { number: "6", name: "-", electrical: "input", style: "inverted", at: [-5, -3.5], angle: 0, length: 2.5, hidden: false },
    { number: "7", name: "~", electrical: "output", style: "line", at: [5, -2.5], angle: 180, length: 2.5, hidden: false },
    { number: "8", name: "~", electrical: "power_in", style: "line", at: [0, 7], angle: 270, length: 2.5, hidden: false },
  ],
  graphics: [
    {
      kind: "polyline",
      points: [[-2.5, 0.5], [2.5, 2.5], [-2.5, 4.5], [-2.5, 0.5]],
      center: [0, 2.5],
      radius: 0,
      width: 0.2,
      fill: "none",
      closed: true,
    },
    {
      kind: "polyline",
      points: [[-2.5, -4.5], [2.5, -2.5], [-2.5, -0.5], [-2.5, -4.5]],
      center: [0, -2.5],
      radius: 0,
      width: 0.2,
      fill: "none",
      closed: true,
    },
  ],
  // Preview geometry bounds include terminal connection points, matching the production endpoint.
  bounds: { x: -5, y: -7, width: 10, height: 14 },
};

const SOIC_PAD_LAYERS = ["F.Cu", "F.Paste", "F.Mask"];

export const COMPONENT_LAND_PATTERN: LandPattern = {
  units: "mm",
  pads: [
    { number: "1", at: [-2.7, -1.905], size: [1.5, 0.6], shape: "roundrect", rotation: 0, drill: 0, pad_type: "smd", side: "front", rratio: 0.18, layers: SOIC_PAD_LAYERS },
    { number: "2", at: [-2.7, -0.635], size: [1.5, 0.6], shape: "roundrect", rotation: 0, drill: 0, pad_type: "smd", side: "front", rratio: 0.18, layers: SOIC_PAD_LAYERS },
    { number: "3", at: [-2.7, 0.635], size: [1.5, 0.6], shape: "roundrect", rotation: 0, drill: 0, pad_type: "smd", side: "front", rratio: 0.18, layers: SOIC_PAD_LAYERS },
    { number: "4", at: [-2.7, 1.905], size: [1.5, 0.6], shape: "roundrect", rotation: 0, drill: 0, pad_type: "smd", side: "front", rratio: 0.18, layers: SOIC_PAD_LAYERS },
    { number: "5", at: [2.7, 1.905], size: [1.5, 0.6], shape: "roundrect", rotation: 0, drill: 0, pad_type: "smd", side: "front", rratio: 0.18, layers: SOIC_PAD_LAYERS },
    { number: "6", at: [2.7, 0.635], size: [1.5, 0.6], shape: "roundrect", rotation: 0, drill: 0, pad_type: "smd", side: "front", rratio: 0.18, layers: SOIC_PAD_LAYERS },
    { number: "7", at: [2.7, -0.635], size: [1.5, 0.6], shape: "roundrect", rotation: 0, drill: 0, pad_type: "smd", side: "front", rratio: 0.18, layers: SOIC_PAD_LAYERS },
    { number: "8", at: [2.7, -1.905], size: [1.5, 0.6], shape: "roundrect", rotation: 0, drill: 0, pad_type: "smd", side: "front", rratio: 0.18, layers: SOIC_PAD_LAYERS },
  ],
  graphics: [
    { start: [-1.9, -2.5], end: [-0.55, -2.5], layer: "F.SilkS", width: 0.2 },
    { start: [0.55, -2.5], end: [1.9, -2.5], layer: "F.SilkS", width: 0.2 },
    { start: [-1.9, -2.5], end: [-1.9, 2.5], layer: "F.SilkS", width: 0.2 },
    { start: [1.9, -2.5], end: [1.9, 2.5], layer: "F.SilkS", width: 0.2 },
    { start: [-1.9, 2.5], end: [1.9, 2.5], layer: "F.SilkS", width: 0.2 },
    { start: [-2, -1.9], end: [-1.4, -2.5], layer: "F.Fab", width: 0.1 },
    { start: [-1.4, -2.5], end: [2, -2.5], layer: "F.Fab", width: 0.1 },
    { start: [2, -2.5], end: [2, 2.5], layer: "F.Fab", width: 0.1 },
    { start: [2, 2.5], end: [-2, 2.5], layer: "F.Fab", width: 0.1 },
    { start: [-2, 2.5], end: [-2, -1.9], layer: "F.Fab", width: 0.1 },
    { start: [-3.7, -2.85], end: [3.7, -2.85], layer: "F.CrtYd", width: 0.05 },
    { start: [3.7, -2.85], end: [3.7, 2.85], layer: "F.CrtYd", width: 0.05 },
    { start: [3.7, 2.85], end: [-3.7, 2.85], layer: "F.CrtYd", width: 0.05 },
    { start: [-3.7, 2.85], end: [-3.7, -2.85], layer: "F.CrtYd", width: 0.05 },
  ],
  model_placement: null,
};

export type ComponentFixtureOptions = {
  parts?: PartSummary[];
  dossier?: ComponentDossier;
  listParams?: Readonly<Record<string, string | readonly string[]>>;
  listBehavior?: ScenarioFixture<PartsResponse, undefined>["behavior"];
  dossierBehavior?: ScenarioFixture<ComponentDossier, undefined>["behavior"];
  cadVariants?: CadVariantDocument;
  cadVariantsBehavior?: ScenarioFixture<CadVariantDocument, undefined>["behavior"];
};

export function componentReadFixtures(options: ComponentFixtureOptions = {}): ScenarioFixture[] {
  const parts = options.parts ?? [FULL_COMPONENT_SUMMARY, SECOND_COMPONENT_SUMMARY];
  const dossier = options.dossier ?? fullComponentDossier();
  return [
    { method: "GET", path: "/api/onboarding", params: {}, body: undefined, response: ONBOARDING_READY },
    {
      method: "GET",
      path: "/api/library/parts",
      params: options.listParams ?? {},
      body: undefined,
      response: { parts, count: parts.length },
      behavior: options.listBehavior,
    },
    { method: "GET", path: "/api/library/facets", params: {}, body: undefined, response: COMPONENT_FACETS },
    { method: "GET", path: "/api/duplicates", params: {}, body: undefined, response: COMPONENT_DUPLICATES },
    { method: "GET", path: `/api/library/parts/${COMPONENT_ID}/dossier`, params: {}, body: undefined, response: dossier, behavior: options.dossierBehavior },
    { method: "GET", path: `/api/library/parts/${COMPONENT_ID}/shell`, params: {}, body: undefined, response: COMPONENT_SHELL },
    ...(options.cadVariants ? [{ method: "GET", path: `/api/library/parts/${COMPONENT_ID}/cad-variants`, params: {}, body: undefined, response: options.cadVariants, behavior: options.cadVariantsBehavior } satisfies ScenarioFixture<CadVariantDocument, undefined>] : []),
    { method: "GET", path: `/api/previews/symbol/${COMPONENT_ID}.json`, params: {}, body: undefined, response: COMPONENT_SYMBOL_GEOMETRY },
    { method: "GET", path: `/api/previews/land/${COMPONENT_ID}.json`, params: {}, body: undefined, response: COMPONENT_LAND_PATTERN },
    { method: "GET", path: `/api/previews/model/${COMPONENT_ID}.glb`, params: {}, body: undefined, response: new Blob([new Uint8Array([0x67, 0x6c, 0x54, 0x46])], { type: "model/gltf-binary" }), behavior: { state: "pending" } },
  ];
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function isParts(value: unknown): value is PartsResponse {
  return isRecord(value) && Array.isArray(value.parts) && typeof value.count === "number" && value.parts.every((part) => isRecord(part) && typeof part.id === "string" && typeof part.mpn === "string");
}

function isDossier(value: unknown): value is ComponentDossier {
  return isRecord(value) && value.schemaVersion === 2 && isRecord(value.identity) && typeof value.identity.id === "string" && isRecord(value.cadAssets) && isRecord(value.documents) && Array.isArray(value.relatedParts) && isRecord(value.provenance);
}

export const componentFixtureValidators = createScenarioFixtureValidatorRegistry({
  "GET /api/library/parts": (fixture) => fixture.body === undefined && isParts(fixture.response),
  "GET /api/library/facets": (fixture) => fixture.body === undefined && isRecord(fixture.response) && isRecord(fixture.response.by_category) && isRecord(fixture.response.by_manufacturer),
  "GET /api/duplicates": (fixture) => fixture.body === undefined && isRecord(fixture.response) && Array.isArray(fixture.response.by_mpn) && Array.isArray(fixture.response.by_footprint),
  [`GET /api/library/parts/${COMPONENT_ID}/dossier`]: (fixture) => fixture.body === undefined && isDossier(fixture.response),
  [`GET /api/library/parts/${COMPONENT_ID}/shell`]: (fixture) => fixture.body === undefined && isRecord(fixture.response) && typeof fixture.response.supported === "boolean" && Array.isArray(fixture.response.export_formats) && Array.isArray(fixture.response.eda_applications),
  [`GET /api/library/parts/${COMPONENT_ID}/cad-variants`]: (fixture) => fixture.body === undefined && isRecord(fixture.response) && fixture.response.partId === COMPONENT_ID && Array.isArray(fixture.response.inventories) && Array.isArray(fixture.response.pairs),
  [`GET /api/previews/symbol/${COMPONENT_ID}.json`]: (fixture) => fixture.body === undefined && isRecord(fixture.response) && Array.isArray(fixture.response.pins) && Array.isArray(fixture.response.graphics),
  [`GET /api/previews/land/${COMPONENT_ID}.json`]: (fixture) => fixture.body === undefined && isRecord(fixture.response) && Array.isArray(fixture.response.pads) && Array.isArray(fixture.response.graphics),
  [`GET /api/previews/model/${COMPONENT_ID}.glb`]: (fixture) => fixture.body === undefined && fixture.response instanceof Blob,
}, bootstrapFixtureValidators);
