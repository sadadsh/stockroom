/**
 * Response shapes mirrored from the backend DTOs. These are the presentation
 * contract only; the source of truth stays the PartRecord JSON + derived index
 * (stockroom.api.schemas, stockroom.model.part). Kept in lockstep with those.
 */

export type TrustVerdict = "pass" | "fail" | "unknown";

/**
 * One tool's independently measured CAD state. `coverage_complete` says only whether every
 * required representation is present; `trust` says what the recorded checks prove. `ready`
 * requires both, except that a part class with no required assets is ready by definition.
 */
export interface EdaReadinessSummary {
  required: string[];
  missing: string[];
  coverage_complete: boolean;
  trust: TrustVerdict;
  ready: boolean;
}

// GET /api/library/parts -> { parts: PartSummary[], count }
export interface PartSummary {
  id: string;
  display_name: string;
  category: string;
  mpn: string;
  manufacturer: string;
  // Passport/data completeness. This is not a CAD-presence or trust verdict.
  is_complete: boolean;
  missing: string[];
  // Registry-keyed, per-tool CAD presence + evidence. Never inferred from the default EDA.
  // Optional only across a rolling frontend/backend handoff from the preceding additive API;
  // its absence fails closed and never falls back to passport completeness.
  eda_readiness?: Record<string, EdaReadinessSummary>;
}

export interface PartsResponse {
  parts: PartSummary[];
  count: number;
}

// GET /api/duplicates -> parts that share a duplicate key. by_mpn groups parts
// recorded under the same MPN (a real accidental duplicate); by_footprint groups
// parts sharing a footprint name (often a legitimate shared standard footprint).
// Within each group the members are ordered most-complete-first (the keep-candidate).
export interface DuplicateGroup {
  key: string;
  parts: PartSummary[];
}

export interface DuplicatesResponse {
  by_mpn: DuplicateGroup[];
  by_footprint: DuplicateGroup[];
}

// GET /api/library/facets
export interface Facets {
  by_category: Record<string, number>;
  /** Every filing destination Stockroom supports, including currently empty categories. */
  category_catalog?: string[];
  by_manufacturer: Record<string, number>;
  complete: number;
  incomplete: number;
}

// GET /api/library/facets/parametric — filter dimensions GENERATED from the parts' own spec
// bags (never a hardcoded per-category list). A numeric key becomes a `range`; any other key
// becomes `options` (the top distinct values with counts). A new spec key surfaces on its own.
export interface FacetOption {
  value: string;
  count: number;
}

export interface ParametricFacet {
  key: string;
  label: string;
  kind: "options" | "range";
  count: number;
  options?: FacetOption[] | null;
  // range facets carry SI-normalized magnitude bounds + the shared base unit
  min?: number | null;
  max?: number | null;
  unit?: string | null;
}

export interface ParametricFacets {
  category: string | null;
  facets: ParametricFacet[];
  total: number;
}

// GET /api/library/search — a rich results row: the lean identity plus the part's own scalar
// spec bag and a flattened sourcing summary. The results table picks its columns from `specs`,
// so a new spec becomes a column with no code change.
export interface SearchRow {
  id: string;
  display_name: string;
  category: string;
  mpn: string;
  manufacturer: string;
  is_complete: boolean;
  missing: string[];
  specs: Record<string, string | number | boolean>;
  stock: number | null;
  unit_price: number | null;
  currency: string;
}

export interface SearchResponse {
  parts: SearchRow[];
  count: number;
}

// Nested records inside the full part detail (stockroom.model.part).
export interface DatasheetRef {
  file: string;
  source_url: string;
  fetched_at: string;
}

export interface PriceBreak {
  // price_breaks are emitted as raw lists; tolerate either [qty, price] pairs
  // or objects so the panel never crashes on a shape it did not expect.
  [key: string]: unknown;
}

export interface PurchaseRef {
  vendor: string;
  url: string;
  // The distributor's own order number (e.g. Mouser "667-ERJ-P03F1101V"), distinct
  // from the manufacturer MPN. Optional so older records without it still type-check.
  part_number?: string;
  price_breaks: PriceBreak[];
  stock: number | null;
  currency: string;
  fetched_at: string;
}

// One EDA asset reference (stockroom.model.asset.AssetRef). `lib` names the container (a
// KiCad library nickname, an Altium .SchLib/.PcbLib filename), `name` the entry inside it,
// and `file` the repo-relative path for a file-shaped asset such as a 3D model. A kind fills
// the fields it needs and leaves the rest blank -- nothing here is tool-specific.
export interface AssetRef {
  lib: string;
  name: string;
  file: string;
}

// WHERE an asset came from (stockroom.model.asset.AssetOrigin). Absent -- not blank -- when
// the asset was attached before anyone recorded its source: an unattributed asset must read
// as unattributed, never as one whose vendor happens to be the empty string.
export interface AssetOrigin {
  vendor: string;
  url: string;
  captured_at: string;
  [key: string]: unknown;
}

// ONE measurement taken against an asset (stockroom.model.trust.AssetCheck). Facts only; the
// pass/fail/unknown verdict is DERIVED from these on read and is never stored, so a verdict
// can never silently disagree with its own evidence. `measured === null` means the check could
// not measure and `expected === null` means there was no authority -- either is UNKNOWN, and
// neither is a failure. `0` is a real measurement, never "missing".
export interface AssetCheck {
  check: string;
  measured: unknown;
  expected: unknown;
  against: string;
  checked_at: string;
  tolerance: number | null;
  note: string;
}

// One asset a part holds for one tool (stockroom.model.asset.Asset): its reference, its
// provenance, its evidence. `origin` and `checks` are OMITTED while empty rather than nulled,
// so adopting the schema did not have to rewrite every record; absence means "nobody recorded
// this", never a trusted blank.
export interface Asset {
  ref: AssetRef;
  origin?: AssetOrigin;
  checks?: AssetCheck[];
}

// Everything ONE EDA tool holds for a part (stockroom.model.asset.EdaAssets). Every tool gets
// the same symmetric bundle, which is what makes readiness a single generic check instead of
// a per-tool branch. Slots are null when the tool has no such asset.
export interface EdaAssets {
  symbol: Asset | null;
  footprint: Asset | null;
  model: Asset | null;
}

export interface Provenance {
  source: string;
  source_url: string;
  original_zip_sha256: string;
  ingested_at: string;
}

// One entry of a persisted pinout (specs.pinout). The datasheet extractor emits
// {pin, name}; the viewer tolerates numbers by coercing to string.
export interface PinoutPin {
  pin: string;
  name: string;
}

// What a part IS, which decides which assets it needs (stockroom.model.part_class.PartClass).
// It replaced the two-valued `passive` boolean, which could not express an M3 mounting hole or
// a fiducial -- both of which the owner's register holds and both of which had to be kept out
// of the library by hand.
export type PartClass = "passive" | "component" | "mechanical" | "virtual";

// The per-part escape hatch (stockroom.model.part_class.RequirementOverride): `needs` REPLACES
// the class's asset list. A null override means "use the class default"; an override with an
// empty `needs` is somebody stating this one part needs nothing, which is a different claim.
export interface RequirementOverride {
  needs: string[];
  // EDA tool keys the override applies to. Empty means every tool.
  tools: string[];
  reason: string;
}

// The DERIVED block (stockroom.model.derived.Derived): everything recomputable from the raw
// payloads in `sourced/`. Disposable by construction -- drop it, recompute, get the record
// back -- which is what makes a naming-scheme or normalization change a re-derive rather than
// a re-import. Identity (`id`, `mpn`, `manufacturer`, `part_class`) is deliberately NOT in here.
export interface Derived {
  display_name: string;
  // The schematic/BOM Value: a passive's parametric value, an active's MPN.
  value: string;
  category: string;
  description: string;
  // Normalized spec keys and values; specs.pinout is a list of {pin, name}. Per-key
  // provenance lives in the record's `enrichment`.
  specs: Record<string, unknown>;
  derived_at: string;
  // Which ruleset produced this block ("rules@1"), so a library can be swept for parts still
  // carrying an older derivation instead of everything being re-derived blindly.
  derived_by: string;
}

// One line of the record's `sources` INDEX (stockroom.model.sourced.SourceEntry): when a
// source was pulled and where its raw payload sits. Never the payload itself.
export interface SourceEntry {
  fetched_at: string;
  // Repo-relative POSIX path, normally `sourced/<id>/<source>.json`.
  file: string;
}

// GET /api/library/parts/{id} -> full PartRecord.to_dict(), verbatim.
//
// This is the WIRE SHAPE, not a convenience view: the endpoint returns the record dataclass's
// own dict. `tests/backend/test_part_wire_contract.py` compares the key set the backend really
// emits against the fields declared here and fails in BOTH directions, because on 2026-07-27
// the record was renamed wholesale, no frontend file was touched, and all three gates stayed
// green while the detail panel crashed and every part read "CAD Incomplete".
export interface PartDetail {
  schema_version: number;
  id: string;
  mpn: string;
  manufacturer: string;
  part_class: PartClass;
  requires_override: RequirementOverride | null;
  // The recomputable half. `display_name`, `category`, `description` and `specs` live HERE, not
  // at the top level -- read them as `detail.derived.<field>`. No dedicated helper module exists
  // (a prior version of this comment pointed to a lib/partFields.ts that was never written);
  // lib/edaTarget.ts's `neededKinds`/`assetsFor` are the closest thing to shared logic over this
  // block today.
  derived: Derived;
  // Which sources this record was derived from, keyed by source name ("mouser", "digikey").
  sources: Record<string, SourceEntry>;
  // The CAD assets, one symmetric bundle per EDA tool key ("kicad", "altium", ...). Tools
  // with nothing attached are omitted by the backend, so read it through
  // `assetsFor(detail, tool)` in lib/edaTarget.ts rather than indexing it directly.
  assets: Record<string, EdaAssets>;
  tags: string[];
  datasheet: DatasheetRef | null;
  purchase: PurchaseRef[];
  provenance: Provenance | null;
  hashes: Record<string, string> | null;
  enrichment: Record<string, { source: string; confidence: string }>;
  // Every value a source offered for a field and did NOT win with, keyed exactly like
  // `enrichment` (a canonical field name in lower_snake, or a spec label). The value in force is
  // repeated as the first entry, so a reader sees which answer is stored beside the ones set
  // aside. Optional because the backend omits the key entirely for a part whose sources never
  // disagreed - most parts carry no alternates at all.
  alternates?: Record<string, SourcedAlternate[]>;
  // Structured provider catalogue intelligence captured at intake. Optional for records written
  // before this capability; provider keys are lowercase (currently `digikey`).
  catalog?: Record<string, CatalogProductData>;
}

// One value a source offered for a field. `value` is unknown, not string: a tariff rate is a
// number whose 0.0 means "confirmed no tariff", not a missing value.
export interface SourcedAlternate {
  value: unknown;
  source: string;
  confidence: string;
}

// POST /api/library/passive/preview -> either a decoded, not-yet-committed passive
// record (status "ok"), or a needs_input signal (status "needs_input") when the MPN
// could not be decoded and the user must pick a kind + package to add it file-less.
export interface PassivePreviewOk {
  status: "ok";
  record: PartDetail;
  gaps: string[];
  stock_present: boolean;
}

// The MPN did not decode: reveal the manual pickers, pre-filled with what is known.
// `packages` are the only EIA cases that resolve to a KiCad stock footprint.
export interface PassiveNeedsInput {
  status: "needs_input";
  mpn: string;
  manufacturer: string;
  suggested_kind: string | null;
  packages: string[];
  message: string;
}

export type PassivePreview = PassivePreviewOk | PassiveNeedsInput;

// The body for a file-less passive preview/add: an MPN or a Mouser product URL, plus
// optional category/manufacturer overrides, a datasheet URL, and the manual
// kind/package/value/tolerance the user picks when the MPN cannot be decoded.
export interface PassiveAddBody {
  input: string;
  kind?: string;
  package?: string;
  value?: string;
  tolerance?: string;
  category?: string;
  manufacturer?: string;
  datasheet_url?: string;
  purchase_part_number?: string;
  // A7: the full pulled result carried onto the passive commit (parametric specs + the price
  // ladder + live stock), so a passive from a link keeps the same depth the non-passive path does.
  specs?: Record<string, string>;
  price_breaks?: { qty: number; price: number }[];
  stock?: number;
  catalog?: Record<string, CatalogProductData>;
}

export interface ApiErrorBody {
  error?: string;
  detail?: string;
  message?: string;
}

// GET /api/library/parts/{id}/history -> the per-part git timeline (M6k), newest
// first, one entry per commit that touched the part's canonical JSON.
export interface HistoryCommit {
  sha: string;
  subject: string;
  author: string;
  iso_date: string;
}

export interface HistoryResponse {
  commits: HistoryCommit[];
  count: number;
}

// GET /api/library/parts/{id}/diff -> a structured field-level diff of the part JSON
// between two revs (M6k), plus which asset kinds changed so the UI can offer an
// old/new SVG overlay. before/after are the raw JSON values (scalar, list, or null).
export interface DiffField {
  key: string;
  before: unknown;
  after: unknown;
  status: "added" | "removed" | "changed";
}

export interface DiffAssets {
  symbol: boolean;
  footprint: boolean;
  model: boolean;
  datasheet: boolean;
}

export interface DiffResponse {
  a: string;
  b: string;
  fields: DiffField[];
  assets: DiffAssets;
}

// POST /api/enrich/part -> the canonical enrichment result (stockroom.enrich.schema).
// Each single-valued field carries the source it came from and a confidence, or is
// null when no source could fill it (a scrape miss is null, never an error).
export interface SourcedField {
  value: unknown;
  source: string;
  confidence: string;
}

export interface EnrichPriceBreak {
  qty: number;
  price: number;
  currency: string;
}

export interface CatalogMediaLink {
  media_type: string;
  title: string;
  url: string;
}

export interface CatalogModelAvailability {
  cad_model: boolean | null;
  three_d_model: boolean | null;
  providers: string[];
}

/** Provider-owned structured catalogue data. Relationship response objects remain distinct:
 * alternate packaging is identity-equivalent, substitutions are possible replacements,
 * recommendations are weaker suggestions, and associations are companion/mating parts. */
export interface CatalogProductData {
  schema_version: number;
  product_number: string;
  manufacturer_product_number: string;
  product_url: string;
  availability: CatalogModelAvailability;
  media: CatalogMediaLink[];
  alternate_packaging: Record<string, unknown>;
  substitutions: Record<string, unknown>;
  recommended_products: Record<string, unknown>;
  associations: Record<string, unknown>;
}

export interface DigiKeyQuantityPricing {
  product_number: string;
  quantity: number;
  options: Array<{
    product_number: string;
    packaging: string;
    quantity: number;
    unit_price: number;
    currency: string;
  }>;
  pricing_options: Record<string, unknown>;
  digireel: Record<string, unknown> | null;
}

// The passive-or-not determination the unified Add-A-Part flow branches on. Non-null
// means the pulled page describes a file-less passive (R/C/L) that adds with KiCad
// stock symbol/footprint/3D, carrying the fields the file-less add needs; null means
// the part needs its symbol/footprint/3D dropped.
export interface PassiveAddPlan {
  kind: string;
  package: string;
  value: string;
  tolerance: string;
}

export interface EnrichmentResult {
  category: string;
  mpn: SourcedField | null;
  manufacturer: SourcedField | null;
  description: SourcedField | null;
  datasheet_url: SourcedField | null;
  stock: SourcedField | null;
  package: SourcedField | null;
  // A2 procurement depth: a part's manufacturing status, factory lead time, distributor
  // product page, and the distributor's own order numbers. The backend always emits these;
  // optional so fixtures/older payloads without them still type-check (null = not pulled).
  lifecycle?: SourcedField | null;
  lead_time?: SourcedField | null;
  product_url?: SourcedField | null;
  dist_pns?: Record<string, string>;
  dist_price_breaks?: Record<string, { qty: number; price: number; currency: string }[]>;
  dist_stock?: Record<string, number | null>;
  // Each distributor's own buy link ("mouser"->..., "digikey"->...): when both APIs answer a
  // lookup we keep BOTH, so the part carries every place it can be ordered, not only the pasted
  // link. Optional so older payloads without it still type-check.
  dist_urls?: Record<string, string>;
  catalog?: Record<string, CatalogProductData>;
  price_breaks: EnrichPriceBreak[];
  specs: Record<string, SourcedField | null>;
  // Every kept disagreement between sources for a spec key: all values with their
  // origins (merge-only-identical, owner 2026-07-24). Optional so fixtures/older
  // payloads without it still type-check.
  spec_conflicts?: Record<string, SourcedField[]>;
  // The same, for the single-valued canonical fields: both descriptions, both packages, both
  // datasheet links. Keyed by the field name in lower_snake ("description"). Optional for the
  // same reason.
  field_conflicts?: Record<string, SourcedField[]>;
  // The backend always emits this; optional so fixtures/older payloads without it
  // still type-check. null (or absent) means the part is not a file-less passive.
  add_plan?: PassiveAddPlan | null;
  // What actually happened to each official distributor API, keyed by its lowercase
  // vendor key ("mouser"/"digikey"). Fixed vocabulary; optional so cached results
  // written before the field existed still type-check.
  source_states?: Record<string, EnrichSourceState>;
  schema_version: number;
}

// The closed per-source verdict vocabulary for EnrichmentResult.source_states.
export type EnrichSourceState = "success" | "unavailable" | "failed" | "not_configured";

// A purchase link on a staging candidate (a scrape/API supplies vendor + url;
// the gate needs at least one entry with a non-empty url).
export interface PurchaseDTO {
  vendor?: string;
  url?: string;
  // The distributor's own order number (e.g. Mouser "667-ERJ-P03F1101V"), carried onto the
  // committed record so an order export can say "order from {vendor} by {this P/N}".
  part_number?: string;
  price_breaks?: unknown[];
  stock?: number | null;
  currency?: string;
  fetched_at?: string;
}

// A staging candidate produced by POST /api/ingest/inspect (the SSE result), and
// the exact DTO POST /api/ingest/commit accepts (stockroom.ingest.StagingCandidate).
// The user edits these fields until the complete-to-add gate passes.
export interface StagingCandidate {
  vendor: string;
  symbol_lib_path: string | null;
  symbol_name: string;
  footprint_variants: string[];
  chosen_footprint_index: number;
  model_path: string | null;
  datasheet_path: string | null;
  display_name: string;
  entry_name: string;
  category: string;
  mpn: string;
  manufacturer: string;
  description: string;
  tags: string[];
  purchase: PurchaseDTO[];
  gaps: string[];
  // the enriched spec bag the inspect -> edit -> commit trip carries onto the record
  // (every parametric field a distributor page yielded); absent on a bare ZIP candidate.
  specs?: Record<string, unknown>;
  // Every value a source offered and LOST with, keyed like the record's `alternates`. The
  // review modal already showed these disagreements; without carrying them here the commit
  // dropped them, so a part added and never refreshed kept none of the competing answers.
  alternates?: Record<string, { value: string; source: string; confidence: string }[]>;
  // per-key provenance for `specs`, the same trip and the same reason
  enrichment?: Record<string, { source: string; confidence: string }>;
  catalog?: Record<string, CatalogProductData>;
  // carries the datasheet source_url onto the committed record; absent on
  // candidates staged before it was round-tripped
  provenance?: {
    source: string;
    source_url: string;
    original_zip_sha256: string;
    ingested_at: string;
  } | null;
}

// POST /api/ingest/enrich -> a background job whose result is this report.
export interface IngestEnrichResult {
  candidate: StagingCandidate;
  filled: string[];
  notes?: string[];
  missing: string[];
}

// POST /api/ingest/inspect -> a background job.
export interface JobRef {
  job_id: string;
}

// GET /api/library/parts/{id}/cad-source (Phase-2 DigiKey asset download, spec section
// 5). `url` is the DigiKey product-detail page hosting the Ultra Librarian / SnapEDA CAD
// download for the part's MPN, or null when the part has no MPN, DigiKey enrichment is
// disabled, or nothing resolved - a resolvable 200 either way, never an error.
// The KiCad + Altium asset types a part can still need. Mirrors the backend
// stockroom.capture.requirements.Requirement enum values exactly (the wire contract).
export type Requirement =
  "kicad_symbol" | "kicad_footprint" | "kicad_model" | "altium_symbol" | "altium_footprint";

// ONE vendor's page for one part, and what the person has to do when they get there.
export interface CadSource {
  // "digikey" | "ultralibrarian" | "samacsys" | "snapmagic"
  key: string;
  label: string;
  url: string;
  // Which EDA tools this vendor can actually export for. The owner needs BOTH, and a vendor that
  // cannot emit Altium must say so rather than send someone to a page that can never satisfy the
  // requirement they are working on.
  tools: string[];
  // True when the vendor merely HOSTS models other libraries built (DigiKey shows SnapEDA / Ultra
  // Librarian / SamacSys downloads on its product pages) rather than authoring them. Data, so a
  // surface can label it honestly instead of implying a fourth library.
  aggregator: boolean;
  // Per-vendor, because "click Download" is not the same journey on a distributor product page as
  // on a model library's part page.
  instruction: string;
  // True only when the network capture broker has a real browser adapter for this provider.
  // A discoverable provider page is not the same as an implemented capture route.
  capture_available: boolean;
}

export interface CadSourceResponse {
  mpn: string;
  // The requirements this part is missing, so the guided checklist knows what to fill.
  needs: Requirement[];
  // Persistent completion authority for the current record projection. Optional only so an old
  // or malformed server fails closed in the UI instead of becoming implicitly complete.
  completion_evidence?: CompletionEvidence | null;
  // Every vendor this part can be fetched from, in the owner's trust order. EMPTY when the part
  // has no MPN: sending someone to a search for "" is worse than telling them there is nowhere.
  sources: CadSource[];
  // The first source, flattened -- the page a capture opens by default. The SAME object as
  // `sources[0]`, never a second answer.
  url: string | null;
  vendor: string;
}

// Bulk MPN / BOM-CSV enrichment triage (POST /api/enrich/bulk, spec section 8.1). Each item
// reports whether enrichment could resolve the part's identity and, if not, exactly what is
// still missing to complete it (or the error that stopped it). It does NOT add parts.
export interface BulkReportItem {
  mpn: string;
  complete: boolean;
  missing: string[];
  error: string;
}

export interface BulkReport {
  items: BulkReportItem[];
}

// GET/PATCH /api/settings -> the redacted per-machine settings surface. The raw
// Mouser key never crosses the wire; only its presence and a last-4 hint do.
export interface SettingsInfo {
  mouser_api_key_set: boolean;
  mouser_api_key_hint: string;
  github_token_set: boolean;
  github_token_hint: string;
  // DigiKey Product Information API OAuth creds. The client_id is echoed raw (a
  // non-secret identifier); the client_secret crosses only as presence + last-4 hint.
  digikey_client_id: string;
  digikey_client_secret_set: boolean;
  digikey_client_secret_hint: string;
  // No provider-website logins live here. Stockroom never signs in to a provider site on
  // someone's behalf, so there is nothing for the machine to store.
  // KiCad wiring: the per-machine overrides (plain paths, not secrets), the
  // effective locations they resolve to, and whether SR_LIB currently points at
  // the active profile's library.
  kicad_config_override: string;
  kicad_cli_override: string;
  kicad_config_dir: string;
  kicad_cli_path: string;
  kicad_cli_available: boolean;
  kicad_wired: boolean;
  stm_cubemx_source?: string;
}

// The PATCH /api/settings body: only the sent fields are touched.
export interface SettingsPatch {
  mouser_api_key?: string;
  github_token?: string;
  digikey_client_id?: string;
  digikey_client_secret?: string;
  kicad_config_override?: string;
  kicad_cli_override?: string;
  stm_cubemx_source?: string;
}

// GET /api/profiles, POST /api/profiles
export interface ProfilesResponse {
  profiles: string[];
  active: string;
}

// POST /api/profiles/{name}/activate
export interface ActivateResponse {
  active: string;
  part_count: number;
}

// GET /api/onboarding (M9b/M9c): where the library lives + whether the one-time
// first-run welcome should show. A frozen exe ships no library, so this is the gate.
export interface OnboardingStatus {
  onboarded: boolean;
  first_run: boolean;
  libraries_root: string;
  profiles: string[];
  under_git: boolean;
  default_dir: string;
  libraries: Array<{
    name: string;
    path: string;
    active: boolean;
    available: boolean;
    under_git: boolean;
  }>;
}

export interface ProjectSummary {
  id: string;
  name: string;
  root: string;
  eda: "kicad" | "altium";
  board_count: number;
  sheet_count: number;
  has_git: boolean;
  registered_at: string;
}

export interface DiscoveredProject {
  eda: "kicad" | "altium";
  eda_label: string;
  name: string;
  root: string;
  descriptor: string;
  boards: string[];
  schematics: string[];
}

export interface ProjectDocument {
  document_id: string;
  path: string;
  label: string;
  kind: "project" | "schematic" | "pcb";
  exists: boolean;
  lock_required: boolean;
}

export interface ProjectWorkspace {
  project: {
    id: string;
    name: string;
    root: string;
    pro_path: string;
    board_paths: string[];
    sheet_paths: string[];
    eda: "kicad" | "altium";
    git_root: string | null;
  };
  eda_label: string;
  tools: Array<"design" | "bom" | "assemble" | "changes" | "releases">;
  parity: {
    schema: "stockroom-project-parity/1";
    edas: ["kicad", "altium"];
    strict: true;
    adapter_boundary: "native_io_only";
    tools: Array<{
      key: "design" | "bom" | "assemble" | "changes" | "releases";
      label: string;
      status: "active" | "planned";
      behavior: "identical";
      actions: string[];
      inputs: string[];
      states: string[];
      results: string[];
      recovery: string[];
      acceptance: string[];
    }>;
  };
  runtime: {
    adapter_key: "kicad" | "altium";
    available: boolean;
    status: string;
    version: string;
    detail: string;
  };
  documents: ProjectDocument[];
}

export interface ProjectPlacement {
  reference: string;
  board: string;
  x_mm: number;
  y_mm: number;
  rotation_deg: number;
  side: "top" | "bottom";
  footprint: string;
}

export interface ProjectPlacementGeometry {
  schema_version: number;
  adapter: "kicad" | "altium";
  status: "ready" | "blocked";
  runtime: {
    name?: string;
    version?: string;
    available?: boolean;
  };
  boards: string[];
  placements: ProjectPlacement[];
  summary: {
    boards: number;
    placements: number;
    top: number;
    bottom: number;
  };
  source: {
    digest: string;
    files: Array<{
      path: string;
      bytes?: number;
      sha256?: string;
    }>;
    preserved: boolean;
  };
  detail: string;
  digest: string;
}

export interface ProjectVisualArtifact {
  id: string;
  kind: "schematic" | "pcb";
  path: string;
  view: string;
  label: string;
  page: number;
  media_type: string;
  width: number;
  height: number;
  bytes: number;
  sha256: string;
}

export interface ProjectBoardBounds {
  min_x: number;
  min_y: number;
  max_x: number;
  max_y: number;
  width: number;
  height: number;
}

export interface ProjectBoardSceneComponent {
  reference: string;
  x_mm: number;
  y_mm: number;
  rotation_deg: number;
  side: "top" | "bottom";
  package: string;
  part: string;
  bounds: ProjectBoardBounds | null;
  pins?: ProjectBoardScenePin[];
}

export interface ProjectBoardScenePin {
  number: string;
  net: string;
  x_mm: number;
  y_mm: number;
  rotation_deg: number;
  side: "top" | "bottom";
  layer: string;
  shape: {
    kind: "circle" | "rect" | "rounded-rect" | "oval" | "unknown";
    width_mm: number;
    height_mm: number;
  } | null;
}

export interface ProjectBoardSceneVia {
  name: string;
  net: string;
  x_mm: number;
  y_mm: number;
  diameter_mm: number;
  from_layer: string;
  to_layer: string;
  sides: Array<"top" | "bottom">;
}

export interface ProjectBoardSceneTrack {
  net: string;
  layer: string;
  side: "top" | "bottom";
  start_x_mm: number;
  start_y_mm: number;
  end_x_mm: number;
  end_y_mm: number;
  width_mm: number;
}

export interface ProjectBoardScene {
  schema_version: number;
  board: string;
  units: "mm";
  bounds: ProjectBoardBounds;
  components: ProjectBoardSceneComponent[];
  vias?: ProjectBoardSceneVia[];
  tracks?: ProjectBoardSceneTrack[];
  summary: {
    components: number;
    pins?: number;
    vias?: number;
    tracks?: number;
    top: number;
    bottom: number;
  };
  source: {
    format: "ipc-2581";
    sha256: string;
  };
}

export interface ProjectVisualDocument {
  kind: "schematic" | "pcb";
  path: string;
  status: "ready" | "blocked";
  detail: string;
  artifacts: ProjectVisualArtifact[];
  scene?: ProjectBoardScene;
}

export interface ProjectVisualBundle {
  schema_version: number;
  adapter: "kicad" | "altium";
  status: "ready" | "blocked";
  runtime: {
    name: string;
    version: string;
  };
  documents: ProjectVisualDocument[];
  summary: {
    documents: number;
    artifacts: number;
    blocked: number;
  };
  detail: string;
  digest: string;
}

export interface ProjectBomLine {
  refs: string[];
  qty: number;
  value: string;
  mpn: string;
  manufacturer: string;
  footprint: string;
  description: string;
  package: string;
  basic: boolean;
  in_library: boolean;
  library_part_id: string;
  final_qty: number;
  final_unit_price: number | null;
  line_total: number | null;
}

export interface ProjectBom {
  project: string;
  ran_at: string;
  boards: number;
  priced: boolean;
  line_count: number;
  component_count: number;
  lines: ProjectBomLine[];
  summary: {
    state: "empty" | "built" | "unpriced" | "partial" | "costed";
    total_cost: number;
    priced_lines: number;
    unpriced_lines: number;
    line_count: number;
    currency: string;
  };
  evidence: {
    eda: "kicad" | "altium";
    variant: string;
    source_commit: string;
    source_documents: string[];
    bom_digest: string;
    repository_pinned: boolean;
  };
}

export interface ProjectAssignmentCandidate {
  part_id: string;
  display_name: string;
  mpn: string;
  description: string;
  confidence: "value+footprint" | "value+package" | "value";
  distinguish: string[];
}

export interface ProjectAssignmentGroup {
  key: string;
  lib_id: string;
  value: string;
  footprint: string;
  refs: string[];
  count: number;
  sheets: string[];
  candidates: ProjectAssignmentCandidate[];
}

export interface ProjectAssignments {
  project: string;
  eda: "kicad" | "altium";
  under_git: boolean;
  binding: {
    field: string;
    writable: boolean;
    reason: string;
  };
  components: number;
  unassigned: number;
  bound: Array<{
    ref: string;
    sheet: string;
    key: string;
    weak_key: boolean;
    part_id: string;
    display_name: string;
    mpn: string;
    missing: boolean;
    drift: Array<{ prop: string; old: string; new: string; kind: string }>;
  }>;
  groups: ProjectAssignmentGroup[];
}

export interface ProjectDocumentLock {
  id: string;
  path: string;
  owner: string;
  locked_at: string;
}

export interface ProjectWorkSession {
  id: string;
  owner: string;
  branch: string;
  base_branch: string;
  base_commit: string;
  documents: string[];
  locks: ProjectDocumentLock[];
  started_at: string;
  shared_commit: string;
}

export interface ProjectSessionRecovery {
  state: "healthy" | "resume_available" | "offline" | "attention";
  detail: string;
  safe_to_resume: boolean;
  ready_to_share: boolean;
  source_preserved: boolean;
  current_branch: string;
  dirty_claimed: string[];
  dirty_unclaimed: string[];
  claims: {
    held: string[];
    lost: string[];
    unknown: string[];
  };
  issues: Array<{
    code: string;
    severity: "action" | "offline" | "error";
    detail: string;
    paths: string[];
  }>;
}

export interface ProjectCollaboration {
  repository: {
    root: string;
    remote: string;
    branch: string;
    commit: string;
    clean: boolean;
    dirty_paths: string[];
    has_remote: boolean;
    has_upstream: boolean;
    ahead: number;
    behind: number;
  } | null;
  session: ProjectWorkSession | null;
  recovery: ProjectSessionRecovery | null;
  blocked_reason?: string;
}

export interface ProjectSyncResult {
  state:
    | "synced"
    | "pushed"
    | "pulled"
    | "offline"
    | "diverged"
    | "denied"
    | "no_remote"
    | "converged";
  pulled: boolean;
  pushed: boolean;
  detail: string;
  converged: boolean;
}

export interface ConnectProjectRemoteResult {
  collaboration: ProjectCollaboration;
  sync: ProjectSyncResult;
}

export interface OpenProjectDocumentResult {
  opened: true;
  document_id: string;
  path: string;
}

export interface ProjectReviewCandidate {
  branch: string;
  commit: string;
  base_branch: string;
  base_commit: string;
  fork_commit: string;
  changed_paths: string[];
  commit_count: number;
  ready: boolean;
  blocked_reason: string;
  events: ProjectReviewEvent[];
}

export interface ProjectReviewEvent {
  id: string;
  kind: "changes_requested";
  branch: string;
  commit: string;
  base_branch: string;
  base_commit: string;
  reviewer: string;
  message: string;
  created_at: string;
}

export interface ProjectReviews {
  base_branch: string;
  candidates: ProjectReviewCandidate[];
  blocked_reason?: string;
}

export interface ProjectReviewEvidenceFinding {
  kind: string;
  path: string;
  detail: string;
}

export interface ProjectNativeValidationCheck {
  kind: "schematic" | "pcb";
  path: string;
  status: "passed" | "failed" | "blocked";
  errors: number;
  warnings: number;
  detail: string;
  findings?: Array<{
    severity?: string;
    rule?: string;
    message?: string;
  }>;
  artifact?: {
    name: string;
    bytes: number;
    sha256: string;
  };
}

export interface ProjectNativeValidation {
  schema_version?: number;
  adapter?: "kicad" | "altium";
  status: "pending" | "passed" | "failed" | "blocked";
  runtime?: {
    name: string;
    version: string;
  };
  checks?: ProjectNativeValidationCheck[];
  summary?: {
    checked: number;
    errors: number;
    warnings: number;
  };
  detail: string;
  project_id?: string;
  branch?: string;
  commit?: string;
  base_branch?: string;
  base_commit?: string;
  source_digest?: string;
  digest?: string;
}

export interface ProjectReviewEvidence {
  schema_version: number;
  project_id: string;
  project_name: string;
  eda: "kicad" | "altium";
  branch: string;
  commit: string;
  base_branch: string;
  base_commit: string;
  source_digest: string;
  documents: Array<{
    path: string;
    kind: "project" | "schematic" | "pcb";
    bytes: number;
    sha256: string;
  }>;
  bom: {
    variant: string;
    line_count: number;
    component_count: number;
    digest: string;
    lines: Array<{
      refs: string[];
      qty: number;
      value: string;
      mpn: string;
      manufacturer: string;
      footprint: string;
      package: string;
      description: string;
      datasheet: string;
      basic: boolean;
      identity_ready: boolean;
    }>;
  };
  semantic_audit: {
    components: number;
    sheets: number;
    counts: {
      by_severity: Record<"error" | "warning" | "info", number>;
      by_kind: Record<string, number>;
    };
    findings: Array<{
      ref: string;
      severity: "error" | "warning" | "info";
      kind: string;
      detail: string;
    }>;
    digest: string;
  };
  blockers: ProjectReviewEvidenceFinding[];
  warnings: ProjectReviewEvidenceFinding[];
  reviewable: boolean;
  native_validation: ProjectNativeValidation;
  visual_diff: {
    status: "pending" | "passed" | "failed" | "blocked";
    detail: string;
  };
  digest: string;
}

export interface ApproveProjectReviewResult {
  integrated_commit: string;
  evidence_digest: string;
  candidate: Omit<
    ProjectReviewCandidate,
    "fork_commit" | "commit_count" | "ready" | "blocked_reason"
  >;
}

export interface RequestProjectChangesResult {
  event: ProjectReviewEvent;
  candidate: Omit<
    ProjectReviewCandidate,
    "fork_commit" | "commit_count" | "ready" | "blocked_reason" | "events"
  >;
}

export interface FinishWorkSessionResult {
  integrated_commit: string;
  collaboration: ProjectCollaboration;
}

export type AssemblyPlacementState = "pending" | "done" | "skipped" | "reworked" | "issue";

export interface AssemblyPlacement {
  placement_id: string;
  board_index: number;
  native_id: string;
  reference: string;
  sheet: string;
  value: string;
  footprint: string;
  part_id: string;
  mpn: string;
  manufacturer: string;
  state: AssemblyPlacementState;
  last_event: AssemblyEvent | null;
}

export interface AssemblyEvent {
  id: string;
  sequence: number;
  run_id: string;
  placement_id: string;
  state: Exclude<AssemblyPlacementState, "pending">;
  scanned_mpn: string;
  note: string;
  recorded_at: string;
}

export interface AssemblyRun {
  schema_version: number;
  id: string;
  project_id: string;
  project_name: string;
  eda: "kicad" | "altium";
  operator: string;
  boards: number;
  source_commit: string;
  project_digest: string;
  started_at: string;
  completed_at: string;
  status: "active" | "completed";
  receipt?: {
    run_id: string;
    source_commit: string;
    project_digest: string;
    event_digest: string;
    completed_at: string;
    digest: string;
  };
  placements: AssemblyPlacement[];
  events: AssemblyEvent[];
  progress: {
    total: number;
    complete: number;
    resolved: number;
    percent: number;
    counts: Record<AssemblyPlacementState, number>;
  };
}
// POST /api/onboarding/library
export interface SetLibraryBody {
  mode: "open" | "create" | "clone";
  path?: string;
  url?: string;
  dest?: string;
}

// GET /api/sync/status
export interface SyncStatus {
  has_remote: boolean;
  current_branch: string;
  ahead: number;
  behind: number;
  github_auth: {
    mode: "git_credential_manager";
    accounts: string[];
  };
  working_copy?: {
    mode: "embedded" | "rival_application_checkout" | "separate";
    detail: string;
  };
  checkout_inventory?: {
    state: "scanning" | "complete" | "truncated" | "failed" | "unavailable";
    scanned_directories?: number;
    max_directories?: number;
    rival_count: number;
    detail?: string;
    checkouts: Array<{
      path: string;
      classification: "canonical" | "rival" | "active_rival" | "staged_release";
      revision: string;
      current: boolean;
      tracked_dirty: boolean;
      active_library: boolean;
    }>;
  };
  last_sync?: {
    state: string;
    pulled: boolean;
    pushed: boolean;
    converged: boolean;
    detail: string;
  } | null;
}

// POST /api/sync
export interface SyncResult {
  state: string;
  pulled: boolean;
  pushed: boolean;
  converged?: boolean;
  detail: string;
}

// GET /api/update/check -> check() reports availability; state/behind vary by case.
export interface UpdateCheck {
  update_available: boolean;
  state?: string;
  behind?: number;
  // Production installs identify immutable signed releases. Development installs use Git
  // revisions instead; both remain explicit so the UI never guesses an identity's kind.
  current_release_id?: string;
  target_release_id?: string;
  current_revision?: string;
  target_revision?: string;
  // Revision baked into the exact frontend bundle this backend is serving. It differs from the
  // checkout HEAD when committed generated assets are built from the preceding source commit.
  frontend_revision?: string;
  channel?: string;
  automatic_on_launch?: boolean;
  check_interval_seconds?: number;
  convergence_phase?: string;
  automatic_apply?: boolean;
  // set when the check could not reach the remote (state "offline"), so the UI
  // never shows a silent Up To Date it did not verify
  detail?: string;
}

// POST /api/update/apply
export interface UpdateApply {
  state: string;
  updated: boolean;
  detail: string;
  restart_requested: boolean;
  frontend_reload_requested?: boolean;
  seamless_handoff_requested?: boolean;
  activated_revision?: string;
  rolled_back?: boolean;
}

// GET /api/doctor/scan -> the library-health pass (stockroom.mutation.library_ops).
// A `fixable` defect heals one-click (drift toward the JSON source of truth, or a
// non-portable 3D-model link rewritten to ${SR_LIB}); a `manual` finding is real but
// cannot be auto-fixed (a missing file cannot be fabricated) and carries how to
// resolve it by hand; `uncommitted` lists working-tree changes the repair will commit.
export interface RepairAction {
  kind: "drift" | "model_path";
  part_id: string;
  detail: string;
  before: string;
  after: string;
}

export interface RepairFinding {
  kind:
    | "missing_symbol"
    | "dangling_model"
    | "dangling_datasheet"
    | "dangling_model_link"
    | "unparseable_file";
  part_id: string;
  detail: string;
  how_to_fix: string;
}

export interface DoctorScan {
  fixable: RepairAction[];
  manual: RepairFinding[];
  uncommitted: string[];
  healthy: boolean;
}

// POST /api/doctor/repair -> what the one-click pass actually did, plus the manual
// findings it could not auto-fix (returned untouched, never silently resolved).
export interface RepairResult {
  healed_drift: number;
  fixed_paths: number;
  committed_files: number;
  commit: string;
  manual: RepairFinding[];
}

// POST /api/library/rescan -> a background job (Phase-1b-3: library-scale procurement
// rescan). already_running is set (instead of a fresh job_id) when a rescan was already in
// flight; the caller attaches to that job rather than starting a second one.
export interface RescanStartResponse extends JobRef {
  already_running?: boolean;
}

// The terminal `result` event of a rescan job: one part-count per outcome, the providers
// (if any) that hit a quota/auth issue partway through and were skipped for the rest of the
// run, and the engine's own honest summary line.
export interface RescanSummary {
  total: number;
  updated: number;
  unchanged: number;
  no_data: number;
  failed: number;
  paused_providers: string[];
  message: string;
}

// GET /api/library/rescan/state -> the last-known rescan outcome per part (uncommitted,
// per-machine; empty before any rescan has ever run on this machine).
export interface RescanStateEntry {
  checked_at: string;
  outcome: string;
}

export interface RescanStateResponse {
  parts: Record<string, RescanStateEntry>;
  counts: Record<string, number>;
}

// POST /api/doctor/wire-kicad (a job) -> the KiCad wiring outcome. restart_needed is
// true when KiCad was running while the library tables changed under it.
export interface WiringReport {
  sr_lib_value: string;
  categories_registered: string[];
  symbol_rows_added: number;
  footprint_rows_added: number;
  libs_created: string[];
  kicad_running: boolean;
  restart_needed: boolean;
}

// GET/POST /api/library/hygiene -- workspace sync hygiene.
//
// Two peers conflict on every pull when an EDA tool's PER-USER files (KiCad's `.kicad_prl` window
// state, the regenerated `fp-info-cache`) are committed. Syncing writes the ignore rules AND
// untracks the files already committed, because an ignore rule does nothing to a file git already
// tracks. Untracking leaves the file on disk; only git stops sharing it.
export interface HygieneRead {
  // the hygiene files whose content would change
  writes: string[];
  // repo-relative paths that would stop being shared
  untracked: string[];
}

export interface HygieneResult extends HygieneRead {
  committed: string | null;
}

// GET/POST /api/library/lfs -- where the library's BINARY payloads are stored.
//
// Without git-lfs every captured part adds a permanent, un-GC-able copy of its .PcbLib / .SchLib /
// .step to history for everyone who will ever clone the library, so clone size only ever grows.
export interface LibraryLfsStatus {
  // is the `git lfs` binary reachable at all, and which version
  installed: boolean;
  version: string;
  // is the filter wired into THIS repository. Attributes naming `filter=lfs` are INERT without it:
  // git stores the file normally and reports nothing, so this is the flag that decides truth.
  enabled: boolean;
  // patterns git-lfs believes it is handling, read from git-lfs rather than parsed out of a file
  tracked_patterns: string[];
  // files currently stored as pointers
  objects: number;
  // tracked files matching an LFS pattern that are STILL ordinary blobs, i.e. committed before
  // adoption. Converting them needs a history rewrite plus a force-push, so the number is
  // reported and never silently "fixed".
  legacy_blobs: number;
  // what adoption WOULD route through LFS, so the offer is concrete rather than a promise
  covers: string[];
  adopted: boolean;
  reason: string;
}

export interface LibraryLfsResult extends LibraryLfsStatus {
  writes: string[];
  untracked: string[];
  committed: string | null;
}

// GET /api/system/info
export interface SystemInfo {
  active_profile: string;
  part_count: number;
  kicad_config_dir: string;
  kicad_running: boolean;
  kicad_cli_available: boolean;
  kicad_cli_path: string;
}

// One part's Altium DbLib status: its identity, the Value the emitter writes, its resolved
// Altium symbol/footprint entry names (empty until attached), and whether it is place-ready.
export interface AltiumStatusRow {
  id: string;
  display_name: string;
  category: string;
  mpn: string;
  value: string;
  symbol: string;
  footprint: string;
  ready: boolean;
}

// The Altium Database Library status for the ACTIVE profile.
export interface AltiumStatus {
  profile: string;
  dblib: string;
  dblib_dir: string;
  ready: number;
  total: number;
  // Whether the SQLite data source the .DbLib reads exists on disk. It is DERIVED from the JSON
  // records and no longer shared through git, so a fresh clone legitimately has none until
  // Stockroom rebuilds it (which it does at boot). False means "not built yet", never "broken".
  datasource_present: boolean;
  rows: AltiumStatusRow[];
}

// GET /api/altium/odbc-status -> whether the 64-bit SQLite3 ODBC driver Altium needs to read the
// DbLib is registered on this machine. `installed` is null off Windows, where it cannot be checked.
export interface OdbcStatus {
  installed: boolean | null;
  driver: string;
  download_url: string;
}

// GET /api/altium/embed-capability -> whether a 3D embed can run on THIS machine, and why not
// when it cannot. Altium writes the 3D body into the footprint's .PcbLib itself, so the action
// needs Altium installed and its license seat free. `reason` comes from the EDA registry, so a
// KiCad-only peer sees an explanation rather than a control that silently does nothing.
export interface AltiumEmbedCapability {
  installed: boolean;
  binary: string;
  requires_tool_installed: boolean;
  reason: string;
  // The window title of a running Altium holding the single On-Demand license seat, or "".
  busy: string;
  available: boolean;
}

// POST /api/altium/parts/{id}/embed-model -> the VERIFIED outcome of an embed. `embedded` and
// `payload_bytes` are read back out of the .PcbLib container from outside Altium, so they are the
// independent proof rather than Altium's own word. `orphaned` counts superseded payloads a replace
// left behind, which Altium does not prune.
export interface AltiumEmbedResult {
  part_id: string;
  status: string;
  detail: string;
  embedded: number;
  payload_bytes: number;
  orphaned: number;
  pcblib: string;
  model: string;
  commit: string;
}

// One part's outcome inside a bulk run. `status` is "ok" for an embed that was verified in the
// container, "failed" for one that was not; a failure carries Altium's own words in `detail`,
// because a run the owner walked away from is exactly where "it did not work" is useless.
export interface AltiumBulkEmbedItem {
  part_id: string;
  status: string;
  detail?: string;
}

// POST /api/altium/embed-models -> the whole run. `skipped` is the parts that were never
// candidates (no Altium footprint, no 3D model file, or a model already embedded); those are not
// failures, and keeping them separate is what makes "2 of 40" explicable rather than alarming.
export interface AltiumBulkEmbedResult {
  embedded: number;
  failed: number;
  attempted: number;
  skipped: string[];
  results: AltiumBulkEmbedItem[];
}

export interface AltiumModelsPending {
  pending: string[];
  count: number;
}

export interface AltiumRegenerateResult {
  emitted: number;
  skipped: string[];
  dblib: string;
}

export interface AltiumSetupResult {
  status: string;
  detail: string;
  dblib: string;
  component_key: string;
  symbol_library: string;
  footprint_library: string;
  receipt_path: string;
}

// A single icon override in the POST /api/dev/save request (dev-mode v2): either `body` (raw inner
// SVG markup, sanitised by the backend before it is written) or `swapToId` (another registry icon
// id to render instead). Both optional; an entry with neither is dropped server-side.
export interface DevIconOverride {
  body?: string;
  swapToId?: string;
}

// POST /api/dev/save (dev mode, owner-only): persist the nudged design tokens, reworded UI copy,
// re-drawn icons, and per-element overrides back to source (lib/token.overrides.ts +
// lib/copy.overrides.ts + lib/icon.overrides.ts + lib/element.overrides.ts), so a saved change
// ships for everyone. `tokens.root` carries the dark-theme colours + shared radii, `tokens.light`
// the light-theme colours; `copy` maps a stable copy id to its new text. The v2 blocks are
// optional (an omitted block regenerates its file empty, matching the token/copy behaviour):
// `icons` maps an icon id to its override, `elements` maps a `data-dev-id` to a CSS prop -> value
// map. Every icon body / CSS value is validated + re-serialised by the backend (the authority on
// what may ship); a malicious value is a 400.
export interface DevSaveBody {
  tokens: { root: Record<string, string>; light: Record<string, string> };
  copy: Record<string, string>;
  icons?: Record<string, DevIconOverride>;
  elements?: Record<string, Record<string, string>>;
  behaviors?: Record<
    string,
    {
      preset?: "dropdown" | "segmented" | "radio" | "searchable";
      disabled?: boolean;
    }
  >;
  // The placeholder names each copy id's DEFAULT declares (`Downloaded {count} of {total} files` ->
  // ["count", "total"]). The default lives in the JSX, so this is the only way the writer can hold a
  // reworded override to the same set and refuse one that dropped or invented a placeholder.
  copyPlaceholders?: Record<string, string[]>;
}

// The write outcome: the relative source paths written, and how many token / copy / icon / element
// overrides now persist. ok is false with a message only on an honest refuse (no source tree in a
// frozen exe).
export interface DevSaveResult {
  ok: boolean;
  written: string[];
  tokens: number;
  copy: number;
  icons: number;
  elements: number;
  behaviors: number;
}

export interface DevWorkspaceStatus {
  available: boolean;
  branch: string;
  revision: string;
  dirty: string[];
  can_publish: boolean;
  publish_blocker: string;
}

export interface DevPublishResult {
  ok: boolean;
  commit: string;
  branch: string;
  message: string;
  checks: string[];
  pushed: boolean;
}

// --- STM Viewer DTOs (Phase 3 contract, consumed verbatim; INTERFACES.md section 4) ---
// These mirror the FastAPI Pydantic models on api/routers/stm.py + api/schemas.py. Kept in
// lockstep with that frozen contract; a genuine gap is an INTERFACES.md amendment + a Phase-3
// fix, never a client-side shim.

// GET /api/stm/status
export interface StmStatusDTO {
  built: boolean;
  building: boolean;
  source_path: string;
  source_present: boolean;
  all_families: boolean;
  device_xml_count: number;
  family_count: number;
  families: string[];
  mcu_count: number;
  classifier_rev: number;
  af_schema_rev: number;
  geometry_rev: number;
  source_sha256: string;
  built_at: string;
}

// One spec-matrix row (the ST-MCU-FINDER column set). `part` is the addressable ref_name used
// as ?part=; `mpn_example` is the real MPN shown to the user (ref_name is never displayed).
export interface McuSpecRow {
  part: string;
  mpn_example: string;
  series: string;
  line: string;
  core: string;
  package: string;
  pin_count: number;
  io_count: number;
  flash_kb: number;
  ram_kb: number;
  max_freq_mhz: number;
  vdd_min: number;
  vdd_max: number;
  temp_min_c: number;
  temp_max_c: number;
  // peripheral name -> instance count (USART, SPI, I2C, TIM, ADC, USB, ...)
  peripherals: Record<string, number>;
}

// GET /api/stm/mcus -> the full matrix + server-computed facet counts for the coarse scope.
export interface McusResponse {
  mcus: McuSpecRow[];
  count: number;
  facets: {
    family: Record<string, number>;
    core: Record<string, number>;
    package: Record<string, number>;
    series: Record<string, number>;
  };
}

// GET /api/stm/families -> { families: FamilyDTO[] }
export interface FamilyDTO {
  family: string;
  lines: string[];
  mcu_count: number;
  packages: string[];
}

export interface FamiliesResponse {
  families: FamilyDTO[];
}

// One alternate-function option on a pin (SWAP-01). Declared once here and REUSED by Phase 5;
// nested on PinDTO.alternate_functions and shown read-only by the inspector in Phase 4.
export interface AfOptionDTO {
  af_index: number;
  signal: string;
  peripheral: string | null;
}

// Every derived fact for one pin (VIZ-03).
export interface PinDTO {
  position: string;
  position_kind: "numeric" | "alnum";
  lqfp_side: "left" | "bottom" | "right" | "top" | null;
  bga_row: string | null;
  bga_col: number | null;
  canonical_pin_name: string;
  raw_pin_name: string;
  pin_type: string;
  electrical_class: "io" | "power" | "ground" | "reset" | "boot" | "vcap" | "nc";
  // the visual-encoding category (color-is-data); tracks electrical_class today
  category: string;
  roles: { role_name: string; role_class: string }[];
  functions: { signal: string; io_modes: string }[];
  alternate_functions: AfOptionDTO[];
  five_v: { tolerant: boolean; by_family: Record<string, boolean>; caveat: string } | null;
  // the VDD/VDDA/VBAT domain, when a power pin
  supply: string | null;
}

// GET /api/stm/pinout?part= -> the full pinout with every pin's facts inlined (one call feeds
// both the map and the inspector; decision 4).
export interface PinoutGeometryDTO {
  body_shape: "qfp" | "qfn" | "bga" | "wlcsp";
  pin_count: number;
  rows: number | null;
  cols: number | null;
  pitch_mm: number | null;
  has_center_pad: boolean;
  // "curated": from the cited PACKAGE_GEOMETRY table; "inferred": derived at request time
  // from the package name + real pin positions (the map badges this honestly).
  source?: "curated" | "inferred";
}

export interface PinoutDTO {
  part: string;
  mpn_example: string;
  package: string;
  geometry: PinoutGeometryDTO;
  pins: PinDTO[];
}

// --- Compatibility Workbench DTOs (Phase 3 contract, consumed verbatim; INTERFACES.md section 4).
// POST /api/stm/compat/union returns UnionDTO; every field mirrors the frozen Pydantic shape. The
// classification vocabulary is exactly shared | divergent | partial (never the retired switch-fabric
// identity), and reconcile is a read-only description of the alternate-function remap, never applied.

// One union position at (mcu, package, position) grain, classified from the per-part facts so the
// classification is auditable (never a silent package-majority collapse). lqfp_side / bga_row /
// bga_col carry the same geometry hint PinDTO does, so lib/pinMapGeometry lays these out unchanged.
export interface UnionPositionDTO {
  position: string;
  position_kind: "numeric" | "alnum";
  lqfp_side: "left" | "bottom" | "right" | "top" | null;
  bga_row: string | null;
  bga_col: number | null;
  classification: "shared" | "divergent" | "partial";
  present_on: number;
  total: number;
  // the raw per-part trail behind the classification (inspector detail on click, never per-pad).
  per_part: {
    ref: string;
    canonical_pin_name: string;
    roles: string[];
    functions: string[];
  }[];
  // for a divergent position (COMPAT-03): the AF remap that makes each part carry the union's
  // required signal here, or swappable:false + a reason. Read-only, never applied. null when the
  // position needs no reconcile (a shared / partial position).
  reconcile: {
    swappable: boolean;
    swaps: { ref: string; target_signal: string; via_af_index: number }[];
    reason: string | null;
  } | null;
}

// POST /api/stm/compat/union -> the socket-union of a set + its set-level verdict (COMPAT-01/02/03/05).
export interface UnionDTO {
  parts: string[];
  resolved: { ref: string; mpn: string }[];
  package: string;
  // the display scope (joined names for a cross-family set) + the real sorted family list
  family: string;
  families: string[];
  grain: "per-part";
  positions: UnionPositionDTO[];
  // the one dominant verdict (COMPAT-05): interchangeable with N swaps, or incompatible with the
  // blocking signal(s) that cannot be placed listed beneath.
  verdict: {
    interchangeable: boolean;
    swaps_required: number;
    blocking: { position: string; signal: string; reason: string }[];
  };
}

// The body POST /api/stm/compat/union accepts: an explicit set of refs OR a (families, package)
// group. Families may mix (owner amendment 2026-07-23); the package is always singular (a socket
// is a physical footprint).
export interface CompatUnionBody {
  parts?: string[];
  family?: string;
  families?: string[];
  package?: string;
}

export type TargetSiliconClass =
  "fixed_critical" | "stable_io" | "variant_io" | "safety_collision" | "partial";

export type TargetBoardAction =
  "hardwire" | "breakout" | "direct" | "switched" | "selectable" | "isolate" | "unsupported";

export interface TargetDefinitionPolicy {
  id: string;
  revision: number;
  coverage_mode?: string;
  requirements: {
    id: string;
    label: string;
    net: string;
    required: boolean;
    implementation_required?: boolean;
    signal_patterns?: string[];
    access_tags?: string[];
    preferred_positions?: string[];
    applies_to?: {
      refs?: string[];
      families?: string[];
      lines?: string[];
    };
    category?: string;
    service_group?: string;
    protocol?: string;
    direction?: string;
    access_plane?: string;
    purposes?: string[];
    claim_scope?: "pin-capability" | "documented-service" | "validated-procedure";
    onehot_group?: string;
    evidence: string[];
  }[];
  service_groups?: {
    id: string;
    label: string;
    category: string;
    protocol?: string;
    required: boolean;
    claim_scope?: "pin-capability" | "documented-service" | "validated-procedure";
    purposes?: string[];
    requirement_ids: string[];
    required_requirement_ids?: string[];
    applies_to?: {
      refs?: string[];
      families?: string[];
      lines?: string[];
    };
    entry_conditions?: string[];
    protection_constraints?: string[];
    side_effects?: string[];
    procedure_refs?: string[];
    destructive?: boolean;
    evidence: string[];
  }[];
  safety_rules: {
    position: string;
    action: TargetBoardAction;
    safe_default: "open" | "off" | "high-z";
    requires_independent_path?: boolean;
    onehot_group?: string | null;
    net?: string;
    hazard?: string;
    evidence: string[];
    branches?: {
      id: string;
      identity_patterns: string[];
      action: TargetBoardAction;
      net?: string;
      requires_independent_path?: boolean;
      safe_default?: "open" | "off" | "high-z";
      onehot_group?: string | null;
      evidence?: string[];
    }[];
  }[];
  routing_constraints?: {
    safe_default: "open";
    maximum_independent_paths?: number;
  };
  target_mpns?: Record<string, string[]>;
  declared_blockers?: string[];
}

export interface TargetDefinitionBody {
  parts: string[];
  policy: TargetDefinitionPolicy;
}

export interface TargetDefinitionPosition {
  position: string;
  position_kind: "numeric" | "alnum";
  lqfp_side: "left" | "bottom" | "right" | "top" | null;
  bga_row: string | null;
  bga_col: number | null;
  silicon_class: TargetSiliconClass;
  board_action: TargetBoardAction;
  universal_primitive?: string;
  active_path_count?: number;
  passive_path_count?: number;
  identities: string[];
  access_tags: string[];
  access_tags_union: string[];
  present_on: number;
  total_targets: number;
  route_ids: string[];
  hazard: string;
  per_target: {
    ref: string;
    family: string;
    canonical_pin_name: string;
    electrical_class: string;
    critical_identity: string | null;
    roles: string[];
    functions: string[];
    alternate_functions: AfOptionDTO[];
    access_tags: string[];
  }[];
}

export interface TargetDefinitionDTO {
  format: "stm-target-definition/2";
  compiler_rev: number;
  artifact_digest: string;
  profile: {
    id: string;
    revision: number;
    coverage_mode: string;
    policy_digest: string;
  };
  scope: {
    package: string;
    families: string[];
    target_count: number;
    targets: {
      ref: string;
      family: string;
      line: string;
      verified_mpns: string[];
    }[];
  };
  provenance: {
    silicon_source: string;
    source_sha256: string;
    source_built_at: string;
    classifier_rev: number;
    af_schema_rev: number;
    geometry_rev: number;
    policy_digest: string;
  };
  readiness: {
    status: "ready" | "blocked";
    blockers: string[];
    warnings: string[];
  };
  summary: {
    silicon_classes: Record<string, number>;
    board_actions: Record<string, number>;
    required_routes: number;
    switched_routes: number;
    safety_rules: number;
    service_groups: number;
    foundation_groups: number;
  };
  requirements: {
    id: string;
    label: string;
    net: string;
    required: boolean;
    implementation_required: boolean;
    category: string;
    service_group: string;
    protocol: string;
    direction: string;
    access_plane: string;
    purposes: string[];
    claim_scope: "pin-capability" | "documented-service" | "validated-procedure";
    route_kind: "direct" | "switched" | "partial" | "unavailable" | "blocked";
    implementation_kind: "direct" | "switched" | "none";
    coverage_status: "complete" | "partial" | "unavailable";
    applicable_targets: string[];
    not_applicable_targets: string[];
    missing_targets: string[];
    blocked_targets: string[];
    routes: {
      ref: string;
      position: string;
      canonical_pin_name: string;
      signal: string;
      af_index: number | null;
      usable: boolean;
      safety_branch: string | null;
    }[];
    candidates_by_target: Record<
      string,
      {
        ref: string;
        position: string;
        canonical_pin_name: string;
        signal: string;
        af_index: number | null;
      }[]
    >;
    candidate_counts: Record<string, number>;
    onehot_group: string | null;
    evidence: string[];
  }[];
  service_groups: {
    id: string;
    label: string;
    category: string;
    protocol: string;
    required: boolean;
    claim_scope: "pin-capability" | "documented-service" | "validated-procedure";
    purposes: string[];
    requirement_ids: string[];
    required_requirement_ids: string[];
    status: "complete" | "partial" | "unavailable";
    applicable_target_count: number;
    complete_target_count: number;
    not_applicable_targets: string[];
    per_target: {
      ref: string;
      family: string;
      line: string;
      status: "complete" | "incomplete";
      missing_requirements: string[];
      positions: Record<string, string>;
    }[];
    entry_conditions: string[];
    protection_constraints: string[];
    side_effects: string[];
    procedure_refs: string[];
    destructive: boolean;
    evidence: string[];
  }[];
  functional_foundation: {
    claim_scope: "pin-obligation";
    network_values_authority: "external-target-documentation-required";
    status: "complete" | "partial";
    unresolved_positions: string[];
    groups: {
      id: string;
      label: string;
      obligation: string;
      applicability: "when-present" | "design-policy";
      claim_scope: "pin-obligation";
      network_evidence_required: boolean;
      status: "complete" | "partial" | "unavailable";
      present_target_count: number;
      resolved_target_count: number;
      positions: string[];
      unresolved_positions: string[];
      per_target: {
        ref: string;
        family: string;
        line: string;
        present: boolean;
        resolved: boolean;
        pins: {
          position: string;
          canonical_pin_name: string;
          electrical_class: string;
          identity: string;
          board_action: TargetBoardAction;
          resolved: boolean;
        }[];
      }[];
    }[];
  };
  safety_rules: {
    position: string;
    action: string;
    safe_default: string;
    onehot_group: string | null;
    evidence: string[];
    branches: {
      id: string;
      identity_patterns: string[];
      matched_identities: string[];
      matched_targets: string[];
      action: string;
      net: string;
      requires_independent_path: boolean;
      safe_default: string;
      evidence: string[];
    }[];
  }[];
  routing_requirements: {
    strategy: "implementation-neutral-independent-paths";
    safe_default: "open";
    required_independent_paths: number;
    maximum_independent_paths: number | null;
    limit_status: "unbounded" | "within-limit" | "over-limit";
    paths: {
      kind: "route" | "safety";
      position: string;
      requested_net: string;
      requirement_id: string | null;
      branch_id?: string;
      exclusivity_group: string | null;
      safe_default: string;
      targets?: string[];
      identities?: string[];
      path_id: string;
    }[];
  };
  universalization: {
    strategy: "one-package-universal-support";
    implementation_owner: "consuming-design";
    implementation_technology: "unspecified";
    required_independent_paths: number;
    passive_conditioned_paths?: number;
    safe_default: "open";
    state_contract: {
      unknown_target: "all-independent-paths-open";
      controller_startup: "all-independent-paths-open";
      controller_reset: "all-independent-paths-open";
      power_loss: "all-independent-paths-open";
      target_change: "open-before-reconfigure";
      identity_mismatch: "refuse-activation";
      configured: "only-target-permitted-paths-may-conduct";
    };
    summary: {
      direct_or_fixed: number;
      selectable: number;
      excluded_from_common_interface: number;
      compact_hybrid?: number;
      fully_exclusive?: number;
    };
    strategies: {
      position: string;
      silicon_class: TargetSiliconClass;
      primitive:
        | "fixed-network"
        | "leave-open"
        | "universal-breakout"
        | "firmware-mapped-breakout"
        | "exclude-from-common-interface"
        | "exclusive-identity-branches"
        | "conditioned-signal-with-selected-critical-role"
        | "declared-identity-branches";
      explanation: string;
      selection: "none" | "one-of" | "critical-role-only" | "policy-defined";
      safe_default: "open" | null;
      identities: string[];
      branches: {
        id: string;
        identity_patterns: string[];
        matched_identities: string[];
        matched_targets: string[];
        action: TargetBoardAction;
        net: string;
        safe_default: string;
        evidence_status: "declared" | "suggested";
        connection_mode?: "selectable" | "isolated" | "passive-conditioned" | "passive-or-direct";
        uses_independent_path?: boolean;
      }[];
      constraints: string[];
      validation: {
        status: "not-required" | "required" | "policy-evidence-required";
        required_checks: string[];
        failure_action: "none" | "use-fully-exclusive-fallback" | "keep-independent-paths-open";
      };
      active_path_count?: number;
      passive_path_count?: number;
      fallback?: {
        primitive: "exclusive-identity-branches";
        independent_paths: number;
        reason: string;
      } | null;
      evidence_status: "compiler-derived" | "declared" | "suggested";
      implementation_owner: "consuming-design";
    }[];
  };
  positions: TargetDefinitionPosition[];
}

export interface SocketSolutionElectricalEnvelope {
  authority: string;
  families: string[];
  operating_v: [number, number] | null;
  per_pin_current_ma: number | null;
  injection_current_ma: number | null;
  five_v_tolerant: boolean | null;
  five_v_by_family?: Record<string, boolean>;
  citations: string[];
}

export interface SocketSolutionMode {
  id: string;
  label: string;
  kind: "signal" | "critical" | "reserved" | "absent";
  conductive: boolean;
  endpoint: string;
  target_mask: string;
  target_count: number;
  percentage: number;
  target_examples: string[];
  functions: string[];
  access_tags: string[];
  electrical_envelope: SocketSolutionElectricalEnvelope;
}

export interface SocketSolutionBranch {
  id: string;
  mode_id: string;
  label: string;
  endpoint: string;
  target_mask: string;
  controlled: boolean;
  default_state: "open" | "connected";
  direction: string;
  break_before_make: boolean;
  plane:
    | "open"
    | "ground-return"
    | "power-source"
    | "regulator-network"
    | "open-drain-control"
    | "signal"
    | "dedicated-network";
  electrical_envelope: SocketSolutionElectricalEnvelope;
}

export interface SocketHazardContract {
  level: "none" | "medium" | "high" | "critical";
  rank: number;
  category: string;
  label: string;
  reason: string;
}

export interface SocketCellContract {
  architecture:
    | "fail-closed-universal-position-cell"
    | "passive-common-network"
    | "fixed-or-signal-network";
  selection_authority: "declared-target-profile" | "not-required";
  default_state: "all-branches-open" | "connected";
  planes: {
    id: string;
    requirements: string[];
  }[];
  mandatory_features: string[];
  power_sequence: string[];
  failure_response: "force-all-branches-open";
  hazard: SocketHazardContract;
}

export interface SocketSolutionPosition {
  position: string;
  position_kind: "numeric" | "alnum";
  lqfp_side: "left" | "bottom" | "right" | "top" | null;
  bga_row: string | null;
  bga_col: number | null;
  cell_type:
    | "fixed-direct"
    | "fixed-network"
    | "universal-io"
    | "selected-roles"
    | "critical-role-island"
    | "passive-compatible-lane"
    | "shared-analog-network"
    | "high-integrity-path"
    | "dedicated-analog-path"
    | "reserved-open"
    | "optional-absent";
  cell_label: string;
  solution_reason: string;
  network_requirements: string[];
  validation_checks: string[];
  cell_contract: SocketCellContract;
  hazard_contract: SocketHazardContract;
  controlled: boolean;
  safe_default: "open" | "connected";
  observation_node: boolean;
  universal_lane: boolean;
  modes: SocketSolutionMode[];
  branches: SocketSolutionBranch[];
  mode_count: number;
  agreement_count: number;
  agreement_percentage: number;
  support_cell_id: string;
  hazard: string;
}

export interface SocketSupportCell {
  id: string;
  signature: string;
  type: SocketSolutionPosition["cell_type"];
  label: string;
  positions: string[];
  position_count: number;
  mode_count: number;
  controlled: boolean;
  safe_default: "open" | "connected";
  hazard_contract: SocketHazardContract;
  cell_contract: SocketCellContract;
  branch_pattern: {
    mode_id: string;
    label: string;
    endpoint: string;
    controlled: boolean;
    plane: SocketSolutionBranch["plane"];
  }[];
  implementation_capabilities: {
    default_open: boolean;
    hardware_reset: boolean;
    readback: boolean;
    break_before_make: boolean;
    bidirectional: boolean;
    passive_conditioning?: boolean;
    shared_supply?: boolean;
    proof_required?: boolean;
  };
}

export interface SocketTargetCohort {
  id: string;
  target_mask: string;
  target_count: number;
  percentage: number;
  families: string[];
  target_examples: string[];
  configuration: Record<string, string>;
}

export interface SocketSolutionDTO {
  format: "stm-socket-solution/1";
  compiler_rev: number;
  artifact_digest: string;
  source_definition_digest: string;
  scope: {
    package: string;
    families: string[];
    target_count: number;
    targets: {
      ref: string;
      family: string;
      line: string;
      verified_mpns: string[];
    }[];
    target_index: {
      index: number;
      ref: string;
      family: string;
      line: string;
    }[];
  };
  provenance: Record<string, unknown>;
  status: {
    solution: "solved" | "conditional" | "impossible";
    evidence: "complete" | "needs-source";
    bootstrap: "automatic" | "requires-declared-target" | "unavailable";
    blockers: string[];
    warnings: string[];
  };
  closure: {
    verdict: "architecture-complete" | "unsupported";
    release: "ready" | "verification-open";
    zero_omission: boolean;
    supported_target_count: number;
    unsupported_target_count: number;
    target_coverage_percentage: number;
    gates: {
      id:
        | "target-coverage"
        | "configuration-integrity"
        | "safe-before-power"
        | "required-access"
        | "electrical-verification";
      label: string;
      status: "pass" | "open" | "fail";
      value: string;
      detail: string;
    }[];
    required_requirement_coverage: {
      id: string;
      label: string;
      covered_targets: number;
      available_target_count: number;
      target_count: number;
      coverage_percentage: number;
      silicon_available_percentage: number;
      missing_targets: string[];
      architecture_missing_targets: string[];
      status: "pass" | "fail";
    }[];
    configuration_errors: {
      target: string;
      position: string;
      reason: string;
    }[];
  };
  summary: {
    target_count: number;
    target_cohort_count: number;
    position_count: number;
    support_cell_count: number;
    direct_positions: number;
    configurable_positions: number;
    critical_positions: number;
    universal_lanes: number;
    observation_nodes: number;
    controlled_branches: number;
    critical_hazard_positions: number;
    high_hazard_positions: number;
    proof_open_positions: number;
    supported_targets: number;
    direct_percentage: number;
    configurable_percentage: number;
    shared_route_savings_percentage: number;
  };
  safe_state_contract: Record<string, string>;
  bootstrap: {
    status: "automatic" | "requires-declared-target";
    debug_positions: string[];
    rule: string;
  };
  fabric: {
    strategy: string;
    universal_lanes: number;
    observation_nodes: number;
    controlled_branches: number;
    control_bits_required: number;
    cohort_configurations: number;
    capacity_limit: number | null;
    configuration_authority:
      | "declared-target-before-power"
      | "common-bootstrap-then-target-profile";
    mandatory_interlocks: string[];
  };
  target_cohorts: SocketTargetCohort[];
  support_cells: SocketSupportCell[];
  positions: SocketSolutionPosition[];
  proofs: {
    position: string;
    status: "needed";
    checks: string[];
    failure_action: string;
  }[];
}

// GET /api/stm/pin/af?part=&position= -> one pin's complete AF0-15 set (SWAP-01). Reuses Phase 4's
// AfOptionDTO for the array element (declared once above); this is only the response wrapper.
export interface PinAfResponse {
  position: string;
  alternate_functions: AfOptionDTO[];
}

// GET /api/stm/signal/candidates?part=&signal= -> every candidate pin a peripheral signal can be
// routed to across the part (SWAP-02).
export interface SignalCandidatesResponse {
  signal: string;
  candidates: { position: string; canonical_pin_name: string; af_index: number }[];
}

// One auto-discovered compatible set, grouped by pin-divergence signature (COMPAT-04). Picking a
// group loads its refs into the workbench assembly as an explicit action (never auto-applied).
export interface SuggestionGroupDTO {
  signature_id: string;
  tier: "baseline" | "divergent";
  package: string;
  family: string;
  refs: string[];
  divergent_positions: number;
}

// GET /api/stm/compat/suggestions?package=&family=&tolerance= -> { groups: [...] }.
export interface SuggestionsResponse {
  groups: SuggestionGroupDTO[];
}

// POST /api/stm/af-check body: one part + a client-held assignment (position -> { signal, af_index }).
// The assignment lives in React state only, never persisted (CONTEXT decision 8).
export interface AfCheckBody {
  part: string;
  assignment: Record<string, { signal: string; af_index: number }>;
}

// POST /api/stm/af-check -> the conflicts a held assignment would introduce (empty list = clean).
export interface AfCheckResponse {
  conflicts: { kind: string; positions: string[]; peripheral: string; message: string }[];
}

// POST /api/enrich/bulk-import -> one row per part number the run was given. `query` is what the
// user pasted and `mpn` what it resolved to, kept apart so a report can say
// "595-TPS62130RGTR -> TPS62130RGTR" rather than silently substituting one for the other.
export interface BulkImportItem {
  query: string;
  mpn: string;
  part_id: string;
  // added | would-add | exists | duplicate | incomplete | error
  status: string;
  display_name: string;
  category: string;
  missing: string[];
  error: string;
  resolved_by: string;
  // "kicad-stock" = a placeable symbol + footprint + 3D model landed with the part;
  // "none" = the record landed on identity alone and still needs a CAD capture.
  assets: string;
}

export interface BulkImportResult {
  counts: Record<string, number>;
  items: BulkImportItem[];
}

// GET /api/library/completion -- "is my library complete, and what is missing?"
//
// There is ONE provider lane: every registered provider is person-driven, so no count here means
// "a machine will fetch it". The action totals are deliberately separate because they answer
// different questions. `needs_files` is work retained verified evidence alone can still improve,
// `needs_assistance` is work a person can close at a provider, and `unsourced` is a real gap
// nothing on record can fill. The first two overlap when one part needs both.
export interface LibraryCoverage {
  total: number;
  complete: number;
  needs_files: number;
  // Optional because older backends omit it entirely, not because it is a second lane.
  needs_assistance?: number;
  unsourced: number;
  // Requirement value ("kicad_symbol", "altium_footprint", ...) -> how many parts lack it.
  by_requirement: Record<string, number>;
  // The registered source keys, and every Requirement they can between them supply.
  sources: string[];
  can_provide: string[];
  // Every registered provider, and everything those providers can between them supply. "Assisted"
  // names the only kind there is: a person works the provider page. Optional for the same
  // older-backend reason as `needs_assistance`.
  assisted_sources?: string[];
  assisted_can_provide?: string[];
}

export type WorkflowBatchStatus =
  "queued" | "running" | "blocked" | "paused" | "completed" | "failed" | "cancelled";

export interface WorkflowBatchActions {
  can_pause: boolean;
  can_resume: boolean;
  can_retry: boolean;
  can_cancel: boolean;
}

export interface WorkflowBatchSummary {
  id: string;
  kind: "completion" | "guided_capture";
  status: WorkflowBatchStatus;
  created_at: number;
  updated_at: number;
  total_items: number;
  item_counts: Record<string, number>;
  cancellation: {
    state: "requested" | "completed";
    requested_at: number;
    completed_at: number | null;
  } | null;
  actions: WorkflowBatchActions;
}

export interface WorkflowEvent {
  sequence: number;
  item_id: string | null;
  stage_id: string | null;
  kind: string;
  details: Record<string, string | number>;
  created_at: number;
}

export interface WorkflowEventsPage {
  schema_version: 1;
  batch: WorkflowBatchSummary;
  events: WorkflowEvent[];
  cursor: {
    after_sequence: number;
    next_sequence: number;
    limit: number;
    has_more: boolean;
  };
}

export interface WorkflowBatchSnapshot {
  schema_version: 1;
  batch: WorkflowBatchSummary;
  event_cursor: number;
  items: Array<{
    id: string;
    ordinal: number;
    status: string;
    stages: Array<{
      id: string;
      name: string;
      status: string;
      attempt_count: number;
      next_attempt_at: number | null;
    }>;
  }>;
  page: {
    after_ordinal: number;
    next_ordinal: number;
    limit: number;
    has_more: boolean;
  };
}

export interface WorkflowControlResult {
  schema_version: 1;
  operation: "pause" | "resume" | "retry" | "cancel";
  changed: boolean;
  batch: WorkflowBatchSummary;
}

export interface CompletionRunRef {
  /** Durable vNext authority. The desktop UI accepts only this reconnectable reference. */
  workflow_batch_id?: string;
  workflow_item_id?: string;
  event_cursor?: number;
  /**
   * Explicit standalone API compatibility transport.
   *
   * The desktop UI must fail closed when an older or deliberately standalone
   * runtime returns this process-local reference. It is represented here only
   * so the client can diagnose that runtime honestly; it is never persisted or
   * followed by the Library completion surfaces.
   */
  job_id?: string;
}

// What CAD this library holds, and what a clear would remove.
//
// `cleared` counts STOCKROOM-AUTHORED assets: an entry in an SR- library, a `.kicad_mod`, a
// `.step`, an Altium `.SchLib`/`.PcbLib`. `kept_stock` counts references to KiCad's OWN installed
// libraries (`Device:R`), which name no file this app holds and are therefore never removed --
// clearing one would empty a passive permanently, since nothing can refill it.
export interface CadInventory {
  cleared: number;
  kept_stock: number;
  items: { part_id: string; assets: string[] }[];
  failed: { id: string; error: string }[];
  // References whose backing FILE was not where the reference said it would be. The reference is
  // still cleared (a dangling one is worse than none), but this must be reported rather than
  // folded into `cleared`: a count that cannot be wrong is how six Altium libraries survived a
  // clear that claimed to have deleted them.
  missing_files: { part_id: string; asset: string; expected: string }[];
}

// Which derivation ruleset produced the presentation data the library is currently showing.
//
// A part's `derived` block (display name, description, category, normalized specs) is computed
// FROM its stored raw distributor payloads. Change the rules and every stored block is stale, so
// the library can be showing two different answers for the same evidence.
export interface LibraryDerivation {
  // The ruleset this build runs, e.g. "rules@2".
  ruleset: string;
  // Every stamp found in the library -> how many parts carry it. The empty string means a part
  // that has never been derived at all, which is a real state and not the same as being behind.
  counts: Record<string, number>;
  current: number;
  stale: number;
}

// What a whole-library re-derive did. `no_evidence` is not a failure: a part with no stored raw
// payloads is SKIPPED rather than recomputed from nothing, which would blank it.
export interface DerivationReport {
  ruleset: string;
  checked: number;
  rewritten: number;
  unchanged: number;
  no_evidence: number;
  failed: { id: string; error: string }[];
}

// One part's outcome from a completion run.
export type ProviderOutcomeStatus =
  | "succeeded-retained"
  | "activated"
  | "unavailable"
  | "requires-human"
  | "blocked"
  | "failed"
  | "cancelled"
  | "not-attempted";

export interface ProviderOutcome {
  route_id: string;
  provider_key: string;
  author_key: string;
  label: string;
  status: ProviderOutcomeStatus;
  attempted: boolean;
  retained: number;
  activated: boolean;
  reason: string;
}

export type CompletionEvidenceState = "verified" | "not-required" | "unverified";

/**
 * The backend's terminal proof for one completion item.
 *
 * The field is optional on CompletionItem only so an older or malformed response can be handled
 * honestly at runtime. Absence never inherits success from `needs: []` or `remaining: []`.
 * `verified` is accepted only with a canonical immutable manifest digest; `not-required` is a
 * distinct policy outcome and carries no fabricated file evidence.
 */
export interface CompletionEvidence {
  state: CompletionEvidenceState;
  manifest_digest: string | null;
  reason: string;
}

export interface CompletionItem {
  part_id: string;
  mpn: string;
  display_name: string;
  category: string;
  // already-complete | completed | improved | deferred | unchanged | error
  //
  // `deferred` is its own status on purpose: the catalogue was rate-limiting us, so the part
  // was never really attempted. Folding it into `unchanged` would read as "nothing can be
  // done for this part", which is the opposite of the truth.
  status: string;
  needed: string[];
  satisfied: string[];
  // Exact provider files preserved as non-projectable evidence. These do not satisfy a CAD
  // requirement until a complete, compatible symbol/footprint/model bundle is activated.
  retained?: number;
  remaining: string[];
  sources: string[];
  // Provider-named reasons a source declined this exact part. These are explanations, not
  // failures; `error` remains reserved for an operation that broke.
  notes: string[];
  error: string;
  // One terminal result for every planned surface/author route. DigiKey's Ultra Librarian,
  // SnapMagic, and TraceParts rows remain independent.
  provider_outcomes?: ProviderOutcome[];
  // Null for ordinary missing-only completion, which is the only completion there is now that a
  // run has one lane. Kept because the backend still reports the field.
  collection_complete?: boolean | null;
  // Required by the current backend contract. Optional here is deliberate defensive decoding:
  // a missing field must fail closed instead of making an old server look complete.
  completion_evidence?: CompletionEvidence | null;
}

export interface CompletionResult {
  items: CompletionItem[];
  counts: Record<string, number>;
  retained?: number;
  collection_complete?: boolean | null;
  stopped: boolean;
  // Why it stopped when the user did not ask it to -- empty otherwise. A stop with no reason
  // is indistinguishable from a crash.
  stop_reason: string;
}

/**
 * GET /api/library/capture/batches/{id}/worklist -- one library-wide run, split into what
 * finished with nobody watching and what still needs one person.
 *
 * A row is ONE provider route the run itself terminated as `requires-human`, so `reason` is that
 * route's own words rather than a category this surface invented. `remaining` is what the part
 * still lacks, so the person knows what to tick before they leave the provider page.
 */
export interface CaptureWorklistRow {
  part_id: string;
  mpn: string;
  display_name: string;
  route_id: string;
  // The provider key to open for this part. It matches one CadSource.key, which is where the URL
  // comes from -- this surface never builds a provider URL of its own.
  provider_key: string;
  label: string;
  status: "requires-human";
  reason: string;
  remaining: Requirement[];
}

// A part the run finished WITHOUT opening a provider page: retained verified evidence already
// covered what it needed. Not an automatic provider route - no such route exists.
export interface CaptureWorklistCompleted {
  part_id: string;
  mpn: string;
  display_name: string;
  status: string;
  remaining: Requirement[];
}

// A part that finished with files still missing and NO route that a person could advance. A
// different fact from needing a person, and never merged with one.
export interface CaptureWorklistStalled extends CaptureWorklistCompleted {
  reason: string;
}

export interface CaptureBatchWorklist {
  workflow_batch_id: string;
  total_items: number;
  // Items whose per-part report has not landed yet: neither finished nor stuck.
  pending_items: number;
  // Bounded rows; `*_total` is the true count behind each bounded list.
  worklist: CaptureWorklistRow[];
  // Missing on older backends, where rows/totals were provider-route scoped.
  worklist_unit?: "components";
  worklist_total: number;
  // Finished from retained verified evidence, with no provider page opened.
  unattended: CaptureWorklistCompleted[];
  unattended_total: number;
  stalled: CaptureWorklistStalled[];
  stalled_total: number;
  // Parts whose retained report could not be read. Named rather than dropped in silence.
  unreadable: string[];
}

export interface CaptureWorkflowSession {
  workflow_batch_id: string;
  workflow_item_id: string;
  part_id: string;
  vendor: string | null;
  background: boolean;
  active_route?: { vendor: string; detail_url: string; route_token: string } | null;
  initial_needs: Requirement[];
  report: CompletionResult | null;
}

// A progress frame from a completion run's SSE stream.
export interface CompletionProgress {
  stage: string;
  done: number;
  total: number | null;
  pct: number | null;
  part_id: string;
  mpn: string;
  display_name: string;
  status: string;
  satisfied: string[];
  retained?: number;
  remaining: string[];
  message: string;
}
