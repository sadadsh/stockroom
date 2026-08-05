// The component dossier: the one read model the opened component reads.
//
// These types mirror `stockroom.dossier` exactly. The canonical `PartDetail` shape stays
// available for diagnostics, but no presentation component reaches into it: every decision
// about what a specification MEANS - which group it belongs to for THIS kind of component,
// whether the category even expects it, which source won and which disagreed - is made once,
// on the backend, and arrives already made.
//
// Nothing here is provider-shaped. A component never asks "what did DigiKey return"; it asks
// for offers, documents and relationships, and the projection decides which provider filled
// them in.

// Bump in step with DOSSIER_SCHEMA_VERSION so a stale client degrades honestly.
export const DOSSIER_SCHEMA_VERSION = 2;

/**
 * What we know about ONE specification. Six named situations, never collapsed into "unknown".
 *
 * `missing` is the category expecting a field nobody supplied - a real gap that MUST render as a
 * row. `not_reported` is nobody supplying a field the category does not require, which is not a
 * gap. The difference cannot be inferred from an empty string, which is exactly why it is sent.
 */
export type VerificationState =
  | "missing"
  | "not_reported"
  | "not_applicable"
  | "unverified"
  | "conflicting"
  | "verified";

/** Whether the category wants this field at all. Completeness counts the first two only. */
export type Applicability = "expected" | "recommended" | "applicable" | "not_applicable";

/** How much a field matters when the category is read at a glance. */
export type Importance = "key" | "primary" | "secondary";

/** Whether the sources agreed. `resolved` means a reviewed override settled a disagreement. */
export type ConflictState = "none" | "conflicting" | "resolved";

/** What kind of thing the value IS, which decides whether it can be compared or ranged. */
export type ValueType =
  | "quantity"
  | "range"
  | "integer"
  | "boolean"
  | "enum"
  | "text"
  | "list";

/** One answer a source offered for one field, with the trust tier that ranked it. */
export interface SourceCandidate {
  sourceId: string;
  sourceLabel: string;
  tier: string;
  tierLabel: string;
  value: unknown;
  displayValue: string;
  normalizedValue: number | number[] | string | boolean | null;
  unit: string;
  confidence: string;
  retrievedAt: string;
  originalKey: string;
}

/** The category's own rule about a value, and what it is allowed to be. */
export interface SpecificationConstraint {
  minimum: number | null;
  maximum: number | null;
  unit: string;
  allowed: string[];
  note: string;
}

/**
 * What a reviewed decision pushed aside.
 *
 * Both kinds of decision carry this, because a decision that cannot say what it replaced asks to
 * be taken on trust, and one whose alternative nobody can see cannot be undone with any
 * confidence. The displaced evidence always names what a SOURCE said - never the person's own
 * earlier edit - so a second edit still reports the sourced value it is standing in for.
 */
export interface DisplacedEvidence {
  replacedValue: string | null;
  replacedSource: string;
  replacedSourceLabel: string;
}

/** A value a person reviewed and typed, which outranks every source. */
export interface SpecificationOverride extends DisplacedEvidence {
  value: string;
  /** Why the reviewer decided this. Blank when they gave no reason. */
  note: string;
  /**
   * Whether the reviewer stands behind the value as checked.
   *
   * False is not a lesser write: it is the honest record of a value somebody entered but has not
   * confirmed, and it is why a row can carry a reviewed value and still read `Unverified` rather
   * than borrowing the authority a reviewed override otherwise outranks the datasheet with.
   */
  verified: boolean;
  reviewedBy: string;
  reviewedAt: string;
}

/**
 * A source a person pinned for this field.
 *
 * The pin FOLLOWS its source rather than copying a value, so a later refresh can legitimately move
 * the field. `inForce` is false when the pinned source stopped offering the field, and false while
 * a reviewed value override outranks it. Both states have to be visible: a control that reports
 * itself in force while something else decides the value is a control that lies about what it did,
 * and a pin that is silently ignored is worse than no pin, because the person believes they set it.
 */
export interface SpecificationSourcePin extends DisplacedEvidence {
  sourceId: string;
  sourceLabel: string;
  reviewedBy: string;
  reviewedAt: string;
  inForce: boolean;
}

/**
 * The canonical specification record. Everything a reader needs about one specification travels
 * on this one object, so nothing is left for a consumer to work out.
 */
export interface SpecificationRecord {
  key: string;
  label: string;
  group: string;
  groupLabel: string;
  order: number;
  valueType: ValueType;
  preferredValue: unknown;
  normalizedValue: number | number[] | string | boolean | null;
  displayValue: string;
  unit: string;
  applicability: Applicability;
  importance: Importance;
  verificationState: VerificationState;
  sourceCandidates: SourceCandidate[];
  preferredSource: SourceCandidate | null;
  /** The reviewed value in force on this field, so the row can say what it overrides. */
  override: SpecificationOverride | null;
  /** The pinned source, whether or not it is the one currently deciding the value. */
  preferredSourcePin: SpecificationSourcePin | null;
  confidence: string;
  conflictState: ConflictState;
  expectedForCategory: boolean;
  filterable: boolean;
  sortable: boolean;
  comparable: boolean;
  /** False when no canonical field claims this key yet: the source's own wording is showing. */
  mapped: boolean;
  constraint: SpecificationConstraint | null;
  constraintViolation: string | null;
}

export interface SpecificationGroup {
  id: string;
  label: string;
  specifications: SpecificationRecord[];
  count: number;
}

/**
 * A record-level sourced fact - the description, the MPN, the manufacturer. Not a specification,
 * but sources disagree about these too and the disagreement is never settled in silence.
 */
export interface RecordFieldView {
  key: string;
  label: string;
  preferredValue: unknown;
  displayValue: string;
  sourceCandidates: SourceCandidate[];
  preferredSource: SourceCandidate | null;
  conflictState: ConflictState;
  verificationState: VerificationState;
  mapped: boolean;
}

/**
 * How the manufacturer's own page was proved - or why a candidate was refused.
 *
 * `rejected` means a distributor listing was offered as the official page and turned down. That
 * is kept rather than dropped: a person needs to see the link was considered.
 */
export type ManufacturerPageState = "verified" | "unverified" | "rejected" | "absent";

export interface ManufacturerPageView {
  url: string;
  host: string;
  sourceId: string;
  sourceLabel: string;
  state: ManufacturerPageState;
  verified: boolean;
  reason: string;
  checkedAt: string;
  rejectedCandidates: Array<{
    url: string;
    sourceId: string;
    sourceLabel: string;
    reason: string;
  }>;
}

export interface CategorySchemaView {
  key: string;
  label: string;
  parent: string;
}

export interface ComponentIdentityView {
  id: string;
  displayName: string;
  mpn: string;
  manufacturer: string;
  category: string;
  categorySchema: CategorySchemaView;
  partClass: string;
  value: string;
  package: string | null;
  pinCount: number | null;
  lifecycle: string | null;
  tags: string[];
  /** Never taken from an offer. See `stockroom.dossier.manufacturer`. */
  manufacturerPage: ManufacturerPageView;
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

/**
 * How complete this part is FOR ITS CATEGORY. `basis` names WHICH definition of complete
 * produced the number, so a resistor's score and a microcontroller's are never compared blind.
 */
export interface CompletenessView {
  score: number;
  expectedPresent: number;
  expectedTotal: number;
  recommendedPresent: number;
  recommendedTotal: number;
  missingExpected: string[];
  missingRecommended: string[];
  basis: string;
}

export interface QualitySummaryView {
  description: string;
  completeness: CompletenessView;
  stateCounts: Record<VerificationState, number>;
  attention: AttentionItem[];
  blockingCount: number;
  missingPassportFields: string[];
}

/** One representation's readiness. `review` means a check could not be measured. */
export type RepresentationStatus =
  | "ready"
  | "review"
  | "missing"
  | "failed"
  | "not_required";

export type RepresentationKind = "symbol" | "footprint" | "model";

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
}

/** What a CAD artifact can be checked against, named by the category schema. */
export interface CadValidationRelationship {
  field: string;
  artifact: string;
  check: string;
  note: string;
}

/**
 * Where one asset's provider came from. `installed` is what the attached file happens to be;
 * the two `preference` values are decisions somebody recorded. Replacing a download and
 * overriding a decision are different acts and the reader is owed the difference.
 */
export type CadSourceOrigin = "" | "installed" | "set_preference" | "asset_preference";

export interface CadAssetSource {
  provider: string;
  label: string;
  origin: CadSourceOrigin;
}

/** One asset that a preferred-source change would move, and what would supply it instead. */
export interface CadPreferenceChange {
  asset: RepresentationKind;
  assetLabel: string;
  fromProvider: string;
  fromLabel: string;
  fromOrigin: CadSourceOrigin;
  toProvider: string;
  toLabel: string;
}

/** Why a choice is not available. Dispatched on the CODE, never on the wording of `reason`. */
export type CadPreferenceRefusal = "" | "unknown_provider" | "unsupplied" | "mixed";

/**
 * What one choice would do, planned by the backend BEFORE anything is written.
 *
 * The same function refuses the write, so a confirmation built from this cannot describe a
 * different outcome from the one that happens.
 */
export interface CadPreferenceScope {
  allowed: boolean;
  refusal: CadPreferenceRefusal;
  reason: string;
  changes: CadPreferenceChange[];
  /** Already in force. Kept apart from `allowed`, which answers "may you choose this". */
  current: boolean;
}

export interface CadPreferenceOption {
  provider: string;
  label: string;
  /** This provider's coverage of each artifact, in the five-state vocabulary. */
  coverage: Record<RepresentationKind, CoverageStatus>;
  set: CadPreferenceScope;
  assets: Record<RepresentationKind, CadPreferenceScope>;
}

/**
 * Which provider supplies this component's CAD, and what choosing another would replace.
 *
 * `mixed` is a real state and is stated rather than averaged away: Stockroom never combines
 * files from two providers, so three assets naming two providers is a fact worth seeing.
 */
export interface CadPreferenceView {
  provider: string;
  label: string;
  mixed: boolean;
  /** Whether a person DECIDED this, as opposed to it being what happened to be downloaded. */
  pinned: boolean;
  reviewedAt: string;
  assets: Record<RepresentationKind, CadAssetSource>;
  assetLabels: Record<RepresentationKind, string>;
  options: CadPreferenceOption[];
}

export interface CadAssetsView {
  kinds: Record<RepresentationKind, RepresentationView>;
  preference: CadPreferenceView;
  tools: Array<{ key: string; label: string }>;
  validationRelationships: CadValidationRelationship[];
}

/** How much a stock reading can still be relied on. `unknown` means no clock was available. */
export type Staleness = "fresh" | "aging" | "stale" | "unknown";

/** What happened to one consulted source. Mirrors `stockroom.enrich.schema.SOURCE_STATES`. */
export type SourceState = "success" | "unavailable" | "failed" | "not_configured";

export interface PriceBreak {
  qty: number | null;
  price: number | null;
}

/**
 * One distributor's normalized offer. Nothing downstream parses a vendor payload: every offer
 * answers the same questions in the same units whichever distributor it came from.
 */
export interface DistributorOffer {
  provider: string;
  /** Always present, so an action can say "Open Mouser Listing" rather than "Product Page". */
  providerLabel: string;
  sku: string;
  /** `null` means nobody reported a count - NOT that the count is zero. */
  stock: number | null;
  currency: string;
  unitPrice: number | null;
  priceBreaks: PriceBreak[];
  moq: number | null;
  leadTime: string;
  factoryLeadTime: string;
  lifecycle: string;
  offerUrl: string;
  lastCheckedAt: string;
  staleness: Staleness;
  /** Empty when the source answered. Otherwise why the numbers beside it may be old. */
  failureState: string;
}

/**
 * The buying answer in one line.
 *
 * `totalStock: null` is UNKNOWN and must never render as 0: "no distributor reported a count"
 * and "every distributor reported none" are different facts with different consequences.
 */
export interface SupplySummaryView {
  offerCount: number;
  providersInStock: string[];
  totalStock: number | null;
  bestUnitPrice: number | null;
  bestUnitPriceCurrency: string;
  bestUnitPriceProvider: string;
  lifecycle: string;
  /**
   * The manufacturer's OWN word for where the part is in its life, kept apart from `lifecycle`.
   * A manufacturer saying "Not Recommended For New Designs" while a distributor still lists the
   * part as active is exactly the disagreement worth showing rather than resolving.
   */
  manufacturerStatus: string;
  leadTime: string;
  factoryLeadTime: string;
  staleness: Staleness;
  /** Named, never keyed: a surface states which distributor could not be read, not its key. */
  failures: Array<{ provider: string; providerLabel: string; state: string }>;
}

/** What a document IS. Closed: "some other link" is not a document type. */
export type DocumentType =
  | "datasheet"
  | "datasheet_page"
  | "package_drawing"
  | "application_note"
  | "pcn"
  | "pdn"
  | "compliance_declaration"
  | "certificate"
  | "attachment"
  | "other";

/** Who published the COPY - a distributor's mirror of a manufacturer PDF is a distributor copy. */
export type DocumentSourceType =
  | "manufacturer"
  | "distributor"
  | "cad_provider"
  | "imported"
  | "unknown";

/** What we hold. `verified` means the bytes were checked, never that a link looked plausible. */
export type DocumentStatus = "verified" | "stored" | "referenced" | "unreachable";

export interface DocumentView {
  /**
   * A stable identity derived from the document itself, not its position.
   *
   * The file endpoint addresses documents by this. Addressing by list position would silently
   * fetch the WRONG document whenever the list changed between render and click - an enrichment
   * landing, a revision being ingested - and it would look like it worked.
   */
  id: string;
  documentType: DocumentType;
  documentTypeLabel: string;
  title: string;
  revision: string;
  manufacturer: string;
  sourceType: DocumentSourceType;
  sourceId: string;
  sourceLabel: string;
  localPath: string;
  remoteUrl: string;
  mimeType: string;
  host: string;
  isPreferred: boolean;
  isCurrent: boolean;
  retrievedAt: string;
  verifiedAt: string;
  status: DocumentStatus;
}

export interface DocumentsView {
  types: DocumentType[];
  items: DocumentView[];
  count: number;
  countsByType: Partial<Record<DocumentType, number>>;
  preferredDatasheet: DocumentView | null;
  /** Why THIS copy won. "we are showing a distributor's copy because..." is the next action. */
  preferredDatasheetReason: string;
  hasDatasheet: boolean;
}

/**
 * A related part, carrying WHY it is related.
 *
 * `validated` is always false and must be surfaced: Stockroom has checked nothing about
 * electrical or mechanical equivalence and must never imply that it has.
 */
export interface RelatedPart {
  mpn: string;
  manufacturer: string;
  description: string;
  url: string;
  provider: string;
  providerLabel: string;
  relation: string;
  relationLabel: string;
  reason: string;
  reasonLabel: string;
  /** The normalized differences the reason was read off. Empty when the reason IS provenance. */
  evidence: Array<{ field: string; ours: string; theirs: string }>;
  validated: false;
}

export interface SourceLedgerEntry {
  id: string;
  label: string;
  state: SourceState;
  /** How many presented fields this source is currently answering for. */
  fieldCount: number;
  fetchedAt: string;
  payloadRef: string;
}

export interface ManualOverrideView {
  field: string;
  value: unknown;
  /** False when the decision only PINS a source: there is no manually typed value to show. */
  hasValue: boolean;
  preferredSource: string;
  preferredSourceLabel: string;
  replacedValue: unknown;
  replacedSource: string;
  replacedSourceLabel: string;
  note: string;
  reviewedBy: string;
  reviewedAt: string;
}

/**
 * One field whose sources disagree, reported as a field with several answers.
 *
 * "Sources disagree about Tolerance: Mouser says 1 %, the datasheet says 0.5 %" is a thing a
 * person can settle. `conflictState: "conflicting"` on a key is not, which is why the projection
 * sends the answers rather than the state word.
 */
export interface FieldConflictView {
  field: string;
  label: string;
  group: string;
  inForce: string;
  inForceSource: string;
  candidates: Array<{
    sourceId: string;
    sourceLabel: string;
    displayValue: string;
    inForce: boolean;
  }>;
}

/**
 * What "written by a newer build" means for the person reading this component.
 *
 * The raw storage keys and the schema number stay in diagnostics. What travels here is the count
 * and the human NAME of each field this build cannot edit, which is the only part of that
 * situation anybody can act on.
 */
export interface CompatibilityView {
  isFutureRecord: boolean;
  readOnlyFieldCount: number;
  fields: Array<{ key: string; label: string; origin: "record" | "derived" }>;
  /** False when this build understands the record completely: then there is no notice at all. */
  hasNotice: boolean;
}

export interface RawEvidenceRow {
  field: string;
  originalKey: string;
  originalValue: unknown;
  retrievedAt: string;
  sourceId: string;
  sourceLabel: string;
  sourceTier: string;
  payloadRef: string;
  endpoint: string;
  parserVersion: string;
  derivedBy: string;
  normalizationResult: {
    displayValue: string;
    normalizedValue: unknown;
    unit: string;
  };
  conflictsWith: string | null;
}

export interface RawLevelsView {
  levels: Array<{ id: string; label: string }>;
  canonical: { count: number; fields: string[] };
  sourceFields: {
    count: number;
    items: Array<{
      sourceKey: string;
      canonicalKey: string;
      value: unknown;
      displayValue: string;
      sourceId: string;
      sourceLabel: string;
      reason: string;
    }>;
  };
  evidence: { count: number; items: RawEvidenceRow[] };
}

export interface ProvenanceView {
  sources: SourceLedgerEntry[];
  recordFields: RecordFieldView[];
  /** Every unsettled disagreement. A surface renders these; it never re-decides which side won. */
  conflicts: FieldConflictView[];
  manualOverrides: ManualOverrideView[];
  compatibility: CompatibilityView;
  raw: RawLevelsView;
}

export type RevisionKind =
  | "imported"
  | "source_fetched"
  | "document_retrieved"
  | "document_verified"
  | "manual_override"
  | "cad_captured"
  | "derived";

/**
 * Which history an event belongs to.
 *
 * `intake` is how the data got here (imported, a source read, a derivation run); `changes` is what
 * has happened to it since. Two questions, so two lists, and the split is the projection's.
 */
export type RevisionSection = "intake" | "changes";

export interface RevisionEvent {
  kind: RevisionKind;
  kindLabel: string;
  section: RevisionSection;
  sectionLabel: string;
  at: string;
  summary: string;
  detail: string;
}

export interface DossierDiagnostics {
  recordSchemaVersion: number;
  /** This record carries data written by a newer build than the one reading it. */
  isFutureRecord: boolean;
  derivedBy: string;
  hashes: {
    symbolContent: string;
    footprintContent: string;
    modelFile: string;
  };
  /** Keys written by a newer build: surfaced, never silently hidden. */
  unknownKeys: string[];
  categorySchema: string;
  groups: Array<{ id: string; label: string }>;
  pinout: Array<Record<string, unknown>>;
  pinCount: number;
  facets: string[];
  comparisonFields: string[];
}

/* -------------------------------------------------------------------------- */
/* Provider coverage - unchanged, and still its own document                    */
/* -------------------------------------------------------------------------- */

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

/* -------------------------------------------------------------------------- */

/** The whole opened-component presentation model for one record. */
export interface ComponentDossier {
  schemaVersion: number;
  identity: ComponentIdentityView;
  qualitySummary: QualitySummaryView;
  /** Already category-aware and PROMOTED out of the groups. Never re-scanned from them. */
  keySpecifications: SpecificationRecord[];
  specificationGroups: SpecificationGroup[];
  cadAssets: CadAssetsView;
  cadSourceCoverage: ComponentProvidersView;
  supplySummary: SupplySummaryView;
  distributorOffers: DistributorOffer[];
  documents: DocumentsView;
  relatedParts: RelatedPart[];
  provenance: ProvenanceView;
  revisions: RevisionEvent[];
  diagnostics: DossierDiagnostics;
}
