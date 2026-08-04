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
  sources: ComponentSourcesView;
  attention: AttentionItem[];
}
