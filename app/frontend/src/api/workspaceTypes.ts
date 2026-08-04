// The component workspace: the normalized presentation model the opened component reads.
//
// These types mirror `stockroom.workspace` exactly. The canonical `PartDetail` shape stays
// available for diagnostics, but no presentation component should reach into it: every
// decision about where a datum belongs is made once, on the backend, and arrives already made.
//
// Nothing here is provider-shaped. A component never asks "what did DigiKey return" - it asks
// for offers, resources, and relationships, and the projection decides which provider filled
// them in.

// Bump in step with WORKSPACE_SCHEMA_VERSION so a stale client degrades honestly.
export const WORKSPACE_SCHEMA_VERSION = 1;

/** One fact's agreement state. Closed vocabulary; never a confidence percentage. */
export type FactState =
  | "verified"
  | "agrees"
  | "conflict"
  | "manual"
  | "unknown"
  | "stale";

/** One representation's readiness. `review` means a check could not be measured. */
export type RepresentationStatus =
  | "ready"
  | "review"
  | "missing"
  | "failed"
  | "not_required";

export type RepresentationKind = "symbol" | "footprint" | "model";

export interface FactSource {
  id: string;
  label: string;
  fetchedAt: string | null;
}

export interface FactAlternate {
  rawValue: unknown;
  formattedValue: string;
  sourceId: string;
  sourceLabel: string;
}

/** One presented datum, with where it came from and what else was offered for it. */
export interface ComponentFact {
  id: string;
  label: string;
  rawValue: unknown;
  formattedValue: string;
  unit?: string | null;
  source?: FactSource | null;
  alternates: FactAlternate[];
  state: FactState;
}

export interface ComponentIdentityView {
  id: string;
  displayName: string;
  mpn: string;
  manufacturer: string;
  category: string;
  partClass: string;
  value: string;
  package: string | null;
  pinCount: number | null;
  lifecycle: string | null;
  tags: string[];
}

export interface ComponentSummaryView {
  description: ComponentFact;
  datasheetUrl: string;
  datasheetFile: string;
}

export interface RepresentationCheckView {
  check: string;
  measured: unknown;
  expected: unknown;
  against: string;
  checkedAt: string;
  note: string;
}

export interface RepresentationToolView {
  tool: string;
  toolLabel: string;
  status: RepresentationStatus;
  present: boolean;
  /** True when the tool stores this asset inside another file rather than separately. */
  embedded: boolean;
  reference: { lib: string; name: string; file: string };
  sourceId: string;
  sourceLabel: string;
  sourceUrl: string;
  capturedAt: string;
  checks: RepresentationCheckView[];
}

export interface RepresentationView {
  kind: RepresentationKind;
  status: RepresentationStatus;
  selectedTool: string;
  tools: RepresentationToolView[];
  sourceLabel: string;
  issue: string | null;
  alternativeCount: number;
}

export interface SpecificationGroupView {
  id: string;
  label: string;
  facts: ComponentFact[];
  count: number;
}

export interface ComponentSpecificationsView {
  groups: SpecificationGroupView[];
  total: number;
  pinout: Array<Record<string, unknown>>;
  pinCount: number;
}

export interface SourcingOfferView {
  sourceId: string;
  sourceLabel: string;
  partNumber: string;
  url: string;
  stock: number | null;
  currency: string;
  priceBreaks: Array<{ qty: number | null; price: number | null }>;
  fetchedAt: string;
}

export interface SourcingRelationshipItem {
  mpn: string;
  manufacturer: string;
  description: string;
  url: string;
  sourceId: string;
  sourceLabel: string;
}

/**
 * A distributor-suggested relationship. Stockroom has NOT validated electrical or mechanical
 * interchangeability, and the UI must never imply that it has.
 */
export interface SourcingRelationshipGroup {
  id: string;
  label: string;
  items: SourcingRelationshipItem[];
  count: number;
}

export interface SourcingResourceView {
  title: string;
  url: string;
  sourceId: string;
  sourceLabel: string;
}

export interface ComponentSourcingView {
  offers: SourcingOfferView[];
  shared: ComponentFact[];
  relationships: SourcingRelationshipGroup[];
  resources: SourcingResourceView[];
}

/**
 * What actually happened to one consulted source. Mirrors `stockroom.enrich.schema.SOURCE_STATES`.
 *
 * The distinction is the point: a source that FAILED (network, auth, rate limit) is not a source
 * that answered and does not carry this part (`unavailable`), and neither is a source that was
 * never attempted because this machine has no credentials for it (`not_configured`). Collapsing
 * the three into "no data" is what made a broken API look like a part nobody sells.
 */
export type SourceState = "success" | "unavailable" | "failed" | "not_configured";

export interface SourceRecordView {
  id: string;
  label: string;
  state: SourceState;
  /** How many presented fields this source is currently answering for. */
  fieldCount: number;
  fetchedAt: string;
  file: string;
  url?: string;
  digest?: string;
}

export interface SourceDiagnosticsView {
  schemaVersion: number;
  derivedAt: string;
  derivedBy: string;
  hashes: {
    symbolContent: string;
    footprintContent: string;
    modelFile: string;
  };
  /** Keys written by a newer build: surfaced, never silently hidden. */
  unknownKeys: string[];
}

export interface ComponentSourcesView {
  fields: ComponentFact[];
  records: SourceRecordView[];
  diagnostics: SourceDiagnosticsView;
}

/**
 * Per-component provider coverage. Mirrors `stockroom.provider_coverage` exactly.
 *
 * The question this answers is "which provider can supply the WHOLE set for this part": a symbol,
 * a footprint and a 3D model, from one provider's coherent verified download. Stockroom never
 * combines files from two providers, so nothing here is a five-slot mix-and-match model - a row
 * is one provider, and `complete` is the answer the screen exists to show.
 */
export type CoverageArtifact = "symbol" | "footprint" | "model";

/** Closed vocabulary, and every value names the evidence that produced it. Never a percentage. */
export type CoverageStatus =
  | "unknown"
  | "available"
  | "not_available"
  | "downloaded"
  | "validated";

/** What proved the status. "" when nothing has said anything. */
export type CoverageOrigin =
  | ""
  | "official_api"
  | "user"
  | "native_download"
  | "validator";

/**
 * How the provider can be reached. "" means NO url exists for that provider, which is a real
 * answer: a manufacturer site, TraceParts and CADENAS have no measured search surface, and a
 * fabricated link would send a person to a page that proves nothing about this part.
 */
export type ProviderUrlKind = "" | "evidence" | "search";

/**
 * One person's recorded correction.
 *
 * `applied: false` means it was NOT applied because Stockroom already holds stronger proof
 * (a downloaded or validated file). The disagreement is kept and must be shown, not hidden.
 */
export interface ProviderUserAssertion {
  status: CoverageStatus;
  origin: string;
  notedAt: string;
  note: string;
  applied: boolean;
}

export interface ProviderArtifactCoverage {
  status: CoverageStatus;
  origin: CoverageOrigin;
  userAssertion: ProviderUserAssertion | null;
}

/** One provider's coverage of one EDA tool, counted out of the three artifacts. */
export interface ProviderToolCoverage {
  count: number;
  total: number;
  /** Already formatted by the backend: "0/3" through "3/3". Rendered, never recomputed. */
  summary: string;
  complete: boolean;
  /** Whether the provider exports for this tool at all. A 0/3 on a provider that never
   *  offered the tool is a different fact from a 0/3 on one that does. */
  supported: boolean;
}

export interface ProviderCoverageRow {
  id: string;
  label: string;
  order: number;
  url: string;
  urlKind: ProviderUrlKind;
  instruction: string;
  needsLogin: boolean;
  aggregator: boolean;
  distributor: boolean;
  statusCounts: Record<CoverageStatus, number>;
  /** This provider can supply symbol, footprint AND 3D model for this component. */
  complete: boolean;
  symbol: ProviderArtifactCoverage;
  footprint: ProviderArtifactCoverage;
  model: ProviderArtifactCoverage;
  kicad: ProviderToolCoverage;
  altium: ProviderToolCoverage;
}

export interface ComponentProvidersView {
  artifacts: CoverageArtifact[];
  statuses: CoverageStatus[];
  tools: string[];
  /** Precomputed by the backend so no reader re-derives it and gets it subtly different. */
  completeProviders: string[];
  /** Already ranked by the backend. Rendered in the given order, never re-sorted here. */
  rows: ProviderCoverageRow[];
}

/**
 * One row's coverage of a registered tool, read by key.
 *
 * The tool columns are named for the registry keys the backend sends in `tools`, so a third tool
 * arrives as data rather than as a new field. The lookup is here, once, so no call site invents
 * its own cast.
 */
export function providerToolCoverage(
  row: ProviderCoverageRow,
  tool: string,
): ProviderToolCoverage | null {
  const cell = (row as unknown as Record<string, unknown>)[tool];
  return cell && typeof cell === "object" && "summary" in (cell as object)
    ? (cell as ProviderToolCoverage)
    : null;
}

/** One row's coverage of one artifact, read by key, for the same reason. */
export function providerArtifactCoverage(
  row: ProviderCoverageRow,
  artifact: CoverageArtifact,
): ProviderArtifactCoverage {
  return row[artifact];
}

export type AttentionSeverity = "blocking" | "warning" | "info";

export interface AttentionItem {
  id: string;
  severity: AttentionSeverity;
  title: string;
  detail: string;
  /** Every attention item names something the person can actually do. */
  action: string;
}

export interface ComponentWorkspaceResponse {
  schemaVersion: number;
  identity: ComponentIdentityView;
  summary: ComponentSummaryView;
  representations: Record<RepresentationKind, RepresentationView>;
  specifications: ComponentSpecificationsView;
  sourcing: ComponentSourcingView;
  providers: ComponentProvidersView;
  sources: ComponentSourcesView;
  attention: AttentionItem[];
}
