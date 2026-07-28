/**
 * Response shapes mirrored from the backend DTOs. These are the presentation
 * contract only; the source of truth stays the PartRecord JSON + derived index
 * (stockroom.api.schemas, stockroom.model.part). Kept in lockstep with those.
 */

// GET /api/library/parts -> { parts: PartSummary[], count }
export interface PartSummary {
  id: string;
  display_name: string;
  category: string;
  mpn: string;
  manufacturer: string;
  is_complete: boolean;
  missing: string[];
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
  schema_version: number;
}

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
  notes: string[];
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
  | "kicad_symbol"
  | "kicad_footprint"
  | "kicad_model"
  | "altium_symbol"
  | "altium_footprint";

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
  // DigiKey account web login (the driver's hands-free sign-in), distinct from the
  // API creds. The username is echoed raw; the password is presence + last-4 hint.
  digikey_username: string;
  digikey_password_set: boolean;
  digikey_password_hint: string;
  // Saved logins for the in-DigiKey CAD providers (Ultra Librarian, SnapEDA, SamacSys).
  // Usernames are echoed raw (not secrets); passwords cross the wire only as presence
  // + a last-4 hint.
  ul_username: string;
  ul_password_set: boolean;
  ul_password_hint: string;
  snapeda_username: string;
  snapeda_password_set: boolean;
  snapeda_password_hint: string;
  samacsys_username: string;
  samacsys_password_set: boolean;
  samacsys_password_hint: string;
  // KiCad wiring: the per-machine overrides (plain paths, not secrets), the
  // effective locations they resolve to, and whether SR_LIB currently points at
  // the active profile's library.
  kicad_config_override: string;
  kicad_cli_override: string;
  kicad_config_dir: string;
  kicad_cli_path: string;
  kicad_cli_available: boolean;
  kicad_wired: boolean;
}

// The PATCH /api/settings body: only the sent fields are touched.
export interface SettingsPatch {
  mouser_api_key?: string;
  github_token?: string;
  digikey_client_id?: string;
  digikey_client_secret?: string;
  digikey_username?: string;
  digikey_password?: string;
  ul_username?: string;
  ul_password?: string;
  snapeda_username?: string;
  snapeda_password?: string;
  samacsys_username?: string;
  samacsys_password?: string;
  kicad_config_override?: string;
  kicad_cli_override?: string;
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
}

// POST /api/sync
export interface SyncResult {
  state: string;
  pulled: boolean;
  pushed: boolean;
  detail: string;
}

// GET /api/update/check -> check() reports availability; state/behind vary by case.
export interface UpdateCheck {
  update_available: boolean;
  state?: string;
  behind?: number;
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
// The owner's central question, which until now only a script outside the app could answer.
// Two totals are deliberately separate: `needs_files` is work a run can actually do right now,
// `unsourced` is a real gap that NOTHING registered can currently fill (every Altium asset,
// today). Collapsing them would either hide the stuck parts or promise a run that cannot
// deliver on them.
export interface LibraryCoverage {
  total: number;
  complete: number;
  needs_files: number;
  unsourced: number;
  // Requirement value ("kicad_symbol", "altium_footprint", ...) -> how many parts lack it.
  by_requirement: Record<string, number>;
  // The registered source keys, and every Requirement they can between them supply.
  sources: string[];
  can_provide: string[];
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
  remaining: string[];
  sources: string[];
  error: string;
}

export interface CompletionResult {
  items: CompletionItem[];
  counts: Record<string, number>;
  stopped: boolean;
  // Why it stopped when the user did not ask it to -- empty otherwise. A stop with no reason
  // is indistinguishable from a crash.
  stop_reason: string;
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
  remaining: string[];
  message: string;
}
