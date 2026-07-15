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

export interface LibRef {
  lib: string;
  name: string;
}

export interface ModelRef {
  file: string;
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

// GET /api/library/parts/{id} -> full PartRecord.to_dict()
export interface PartDetail {
  id: string;
  display_name: string;
  category: string;
  description: string;
  tags: string[];
  mpn: string;
  manufacturer: string;
  // True for a passive (R/C/L) that references KiCad stock symbol/footprint/3D
  // rather than owning copied asset files. Optional so older fixtures/records
  // without the flag still type-check; the backend always emits it.
  passive?: boolean;
  datasheet: DatasheetRef | null;
  purchase: PurchaseRef[];
  symbol: LibRef | null;
  footprint: LibRef | null;
  model: ModelRef | null;
  provenance: Provenance | null;
  hashes: Record<string, string> | null;
  enrichment: Record<string, { source: string; confidence: string }>;
  // Persisted canonical spec data (M6i). A free-form value bag keyed by spec name;
  // specs.pinout is a list of {pin, name}. Per-key provenance lives in `enrichment`.
  specs: Record<string, unknown>;
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

export interface EnrichmentResult {
  category: string;
  mpn: SourcedField | null;
  manufacturer: SourcedField | null;
  description: SourcedField | null;
  datasheet_url: SourcedField | null;
  stock: SourcedField | null;
  package: SourcedField | null;
  price_breaks: EnrichPriceBreak[];
  specs: Record<string, SourcedField | null>;
  schema_version: number;
}

// A purchase link on a staging candidate (a scrape/API supplies vendor + url;
// the gate needs at least one entry with a non-empty url).
export interface PurchaseDTO {
  vendor?: string;
  url?: string;
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

// POST /api/library/bom-match: a pasted BOM line matched against the library.
export interface BomMatchItem {
  mpn: string;
  part_id: string | null;
  display_name: string;
  is_complete: boolean;
  missing: string[];
  matches: number;
}

export interface BomMatchReport {
  items: BomMatchItem[];
  in_library: number;
  total: number;
}

// GET/PATCH /api/settings -> the redacted per-machine settings surface. The raw
// Mouser key never crosses the wire; only its presence and a last-4 hint do.
export interface SettingsInfo {
  mouser_api_key_set: boolean;
  mouser_api_key_hint: string;
  github_token_set: boolean;
  github_token_hint: string;
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

// GET /api/projects/{id}/buildability (M7g): one ready-to-build verdict fusing
// completeness + ERC/DRC + BOM + git, with honest cold-cache states.
export interface BuildabilityEntry {
  kind: string;
  detail: string;
  next_step: string;
}

export interface Buildability {
  project: string;
  ready: boolean;
  signals: {
    completeness: {
      state: string;
      has_sch: boolean;
      total: number;
      complete: number;
      unannotated: number;
      missing_footprint: number;
      incomplete_refs: string[];
      missing_counts: Record<string, number>;
    };
    checks: {
      state: string;
      ran_at: string | null;
      errors: number;
      warnings: number;
      checked: number;
      ok: boolean;
    };
    bom: {
      state: string;
      ran_at: string | null;
      priced: boolean;
      line_count: number;
      unpriced_lines: number;
      risks: Record<string, number> | null;
    };
    git: { state: string; under_git: boolean; dirty: boolean };
  };
  blockers: BuildabilityEntry[];
  warnings: BuildabilityEntry[];
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

// --- Projects (M7a) ---

// GET /api/projects -> the derived project index, one row per registered project,
// sorted by name. A registered KiCad project is external to Stockroom: it is
// referenced by its root path, never owned. board_count/sheet_count/has_git are the
// digest fields the list renders; the full record loads on detail.
export interface ProjectSummary {
  id: string;
  name: string;
  root: string;
  board_count: number;
  sheet_count: number;
  has_git: boolean;
  registered_at: string;
}

// GET /api/projects/{id} and POST /api/projects -> the full canonical ProjectRecord.
// A None git_root means an edit would be an honest refuse (external files are never
// touched here); audit_digest caches the last health summary.
export interface ProjectDetail {
  id: string;
  name: string;
  root: string;
  pro_path: string;
  board_paths: string[];
  sheet_paths: string[];
  git_root: string | null;
  audit_digest: Record<string, unknown> | null;
  registered_at: string;
}

// One row of the project health audit (GET /api/projects/{id}/audit). severity is
// error | warning | info; kind is the machine reason (unannotated, duplicate_ref,
// no_footprint, no_mpn, no_3d_model, ...) that the breakdown chips filter by.
export interface AuditFinding {
  ref: string;
  severity: "error" | "warning" | "info";
  kind: string;
  detail: string;
}

// GET /api/projects/{id}/audit -> a read-only health pass over the registered sheets
// (against the ACTIVE profile's footprint/model dirs), plus a shareable markdown report.
export interface AuditResult {
  project: string;
  components: number;
  healthy: number;
  counts: {
    by_severity: { error: number; warning: number; info: number };
    by_kind: Record<string, number>;
  };
  findings: AuditFinding[];
  checked_footprints: number;
  unresolved_footprints: number;
  sheets: number;
  markdown: string;
}

// One ERC or DRC finding (POST /api/projects/{id}/checks). severity is
// error | warning | exclusion | info; rule is the KiCad violation type; where is a
// best-effort location string.
export interface CheckFinding {
  severity: "error" | "warning" | "exclusion" | "info";
  rule: string;
  message: string;
  where: string;
}

// The result of ONE check: ERC on the root schematic, or DRC on a board. ok=false
// means the check could not produce a valid report (never a clean pass); error carries
// why. `sheet` is set on the ERC run, `board` on each DRC run.
export interface CheckRun {
  ok: boolean;
  findings: CheckFinding[];
  summary: {
    total: number;
    errors: number;
    warnings: number;
    by_severity: Record<string, number>;
    by_rule: Record<string, number>;
  };
  error: string;
  returncode?: number;
  sheet?: string;
  board?: string;
}

// POST/GET /api/projects/{id}/checks -> a full ERC + DRC run (M7b). ran_at is null (and
// erc/summary null) before the first run: an honest "not checked yet" state, never a
// fabricated pass. summary.ok=false means a check failed to complete.
export interface ChecksResult {
  project: string;
  erc: CheckRun | null;
  drc: CheckRun[];
  summary: {
    ok: boolean;
    errors: number;
    warnings: number;
    total: number;
    checked: number;
  } | null;
  ran_at: string | null;
}

// One grouped BOM line (POST/GET /api/projects/{id}/bom, M7c). refs are the reference
// designators that merged into this line; basic marks a standard passive stocked by
// value; has_real_mpn is false for a passive with no purchasable part number. The
// priced fields (unit_price/extended/stock/source) are present only when the line was
// costed; an unpriced line simply omits them (a price is never invented).
export interface BomLine {
  refs: string[];
  qty: number;
  value: string;
  mpn: string;
  manufacturer: string;
  has_real_mpn: boolean;
  footprint: string;
  datasheet: string;
  description: string;
  basic: boolean;
  unit_price?: number | string;
  extended?: number;
  stock?: number;
  source?: string;
  price_breaks?: { qty: number; price: number }[];
  // M7d procurement fields, present only when the enrich layer carried them.
  lifecycle?: string;
  lead_time?: string;
  url?: string;
  mouser_pn?: string;
  lcsc_pn?: string;
  digikey_pn?: string;
  // Per-line build economics (M7... reprice): the order quantity and cost at a chosen
  // build size + tax/tariff rate. Present after a build/reprice; optional so an older
  // cached shape (before this field existed) still typechecks. final_qty is always a
  // real number once attached (never invented, but never absent either); the cost
  // fields are null when the line itself could not be priced.
  moq?: number | null;
  final_qty?: number;
  final_unit_price?: number | null;
  final_extended?: number | null;
  tax_tariff?: number | null;
  line_total?: number | null;
}

// The BOM roll-up for one build: build_qty boards at tax_rate percent, summed over every
// priced line's final_extended (+ tax). Only present once a build has been costed.
export interface BuildRollup {
  build_qty: number;
  tax_rate: number;
  subtotal: number;
  tax_total: number;
  grand_total: number;
  priced_lines: number;
  unpriced_lines: number;
  currency: string;
}

// The BOM cost roll-up. state is the honest verdict: "empty" (no lines), "built"
// (grouped, pricing not attempted), "unpriced" (pricing attempted, nothing costed, e.g.
// offline), "partial" (some lines unpriced), "costed" (every line priced). Only "costed"
// is a fully green verdict, mirroring the checks "nothing checked is never Clean" rule.
export interface BomCostSummary {
  total_cost: number;
  priced_lines: number;
  unpriced_lines: number;
  line_count: number;
  currency: string;
  state: "empty" | "built" | "unpriced" | "partial" | "costed";
  priced: boolean;
}

// POST/GET /api/projects/{id}/bom -> a grouped, optionally priced BOM (M7c). ran_at and
// summary are null before the first build: an honest "not built yet" state, never a
// fabricated cost. by_source / cost_at_qty are present only for a priced build.
export interface BomResult {
  project: string;
  ran_at: string | null;
  boards: number;
  priced: boolean;
  line_count: number;
  component_count: number;
  lines: BomLine[];
  summary: BomCostSummary | null;
  by_source: {
    sources: Record<string, { total_cost: number; lines: number }>;
    currency: string;
  } | null;
  cost_at_qty: {
    boards: number;
    total_cost: number;
    priced_lines: number;
    unpriced_lines: number;
    currency: string;
  } | null;
  // The tax/tariff rate (percent) the cached build was costed at, and the build-size cost
  // roll-up. Optional so an older cached shape (before this field existed) still typechecks.
  tax_rate?: number;
  build?: BuildRollup | null;
}

// --- Procurement (M7d) ---

// Per-line stock coverage for the current run. kind is "err" (0 stock), "warn" (short of
// the run), or null (covered, or stock unknown so never a warning); available is null when
// the line was never priced (unknown, not a risk).
export interface StockRisk {
  kind: "err" | "warn" | null;
  required: number;
  available: number | null;
  short: boolean;
}

// A BOM line enriched with its procurement verdict (GET /api/projects/{id}/procurement).
export interface ProcurementLine extends BomLine {
  stock_risk: StockRisk;
  orderable: boolean;
}

// The sourcing-risk roll-up: counts of the failures worth catching before ordering.
export interface SourcingRisks {
  not_active: number;
  no_stock: number;
  insufficient_stock: number;
  risky_mpns: string[];
  any: boolean;
}

// The critical-path lead time across the build.
export interface LeadTime {
  max_weeks: number | null;
  critical_mpn: string | null;
  with_lead: number;
  any: boolean;
}

// GET /api/projects/{id}/procurement -> the per-line + rolled-up procurement view over the
// cached BOM. built is false before a build (nothing to procure); priced is false for an
// unpriced build (lines list with unknown, never-a-risk stock).
export interface ProcurementResult {
  project?: string;
  built: boolean;
  priced: boolean;
  boards: number;
  lines: ProcurementLine[];
  risks: SourcingRisks;
  lead: LeadTime;
  summary: string;
}

// The BOM export formats (GET /api/projects/{id}/bom/export?kind=). csv/priced/cart/jlcpcb
// are CSV; xlsx/procurement are Excel workbooks.
export type BomExportKind = "csv" | "priced" | "cart" | "jlcpcb" | "xlsx" | "procurement";

// The Fab panel's honest gate (GET /api/projects/{id}/fab, M7i): has_board is false for a
// schematic-only project; cli_available is false when kicad-cli is not installed.
export interface FabStatus {
  project?: string;
  has_board: boolean;
  cli_available: boolean;
  boards: string[];
}

// Options for the fab bundle download (GET /api/projects/{id}/fab/export, M7i).
export interface FabExportOptions {
  drillFormat: "excellon" | "gerber";
  drillMap: boolean;
  includePos: boolean;
  posFormat: "csv" | "ascii" | "gerber";
  protelExt: boolean;
  board?: string;
}

// The buy-side knobs for the Procurement Sheet export (and spares for the Mouser Cart). Sent
// as query params; tax_rate / assembly_surcharge_rate are FRACTIONS (0.1 = 10%), spares_pct is
// a whole percent (10 = 10%), matching the backend procurement_xlsx signature.
export interface ProcurementExportOptions {
  boards?: number;
  spares_pct?: number;
  pcb_multiple?: number;
  tax_rate?: number;
  shipping?: number;
  labour_per_board?: number;
  assembly_surcharge_rate?: number;
}

// --- Revision diff (M7d) ---

// One commit in a project's git history (GET /api/projects/{id}/revisions).
export interface RevisionInfo {
  sha: string;
  short: string;
  subject: string;
  author: string;
  date: string;
}

export interface RevisionsResult {
  project?: string;
  under_git: boolean;
  revisions: RevisionInfo[];
}

export interface BomDiffLine {
  mpn: string;
  value: string;
  footprint: string;
  qty: number;
}

export interface BomDiffChange {
  mpn: string;
  value: string;
  footprint: string;
  from_qty: number;
  to_qty: number;
  delta: number;
}

export interface BomDiffCost {
  delta: number;
  added_cost: number;
  changed_cost: number;
  removed_unpriced: number;
  priced: boolean;
  currency: string;
}

export interface BomDiffLead {
  added_max_weeks: number | null;
  added_critical_mpn: string | null;
  build_max_weeks: number | null;
  build_critical_mpn: string | null;
  on_critical_path: boolean;
  removed_unassessed: number;
  any: boolean;
}

// GET /api/projects/{id}/bom/diff?a=&b= -> the BOM change between revision a (reconstructed
// from the project's git) and b (blank = the current build). cost/lead deltas are meaningful
// only when the current build is priced (rev_b == "current").
export interface BomDiffResult {
  project?: string;
  rev_a: string;
  rev_b: string;
  added: BomDiffLine[];
  removed: BomDiffLine[];
  changed: BomDiffChange[];
  unchanged: number;
  cost: BomDiffCost;
  lead: BomDiffLead;
  csv: string;
  a_sheets_found: number;
  b_sheets_found: number | null;
}

// --- Editor: design rules + net classes (M7e) ---

// A KiCad net class as stored in net_settings.classes[]. The routing dimensions the
// Editor edits are typed; KiCad-internal fields (colors, line_style, wire/bus stroke,
// tuning_profile) pass through the index signature and are preserved on save.
export interface NetClass {
  name: string;
  clearance?: number;
  track_width?: number;
  via_diameter?: number;
  via_drill?: number;
  microvia_diameter?: number;
  microvia_drill?: number;
  diff_pair_width?: number;
  diff_pair_gap?: number;
  priority?: number;
  [key: string]: unknown;
}

// A fab-house dimension floor (mm), for validate-on-save.
export interface FabFloor {
  label: string;
  min_clearance: number;
  min_track: number;
  min_via: number;
  min_drill: number;
  min_annular: number;
}

// A below-floor / inconsistent net-class finding (non-blocking amber).
export interface NetClassValidation {
  netclass: string;
  issue: string;
}

// The board design-rule constraints (board.design_settings.rules): min_* floats plus a
// couple of booleans. Kept a loose record so every rule KiCad writes is editable.
export type DesignRules = Record<string, number | boolean>;

// GET /api/projects/{id}/design
export interface DesignResult {
  project: string;
  under_git: boolean;
  has_pro: boolean;
  net_classes: NetClass[];
  netclass_patterns: { netclass: string; pattern: string }[];
  design_rules: DesignRules;
  track_widths: unknown[];
  via_dimensions: unknown[];
  diff_pair_dimensions: unknown[];
  fab_floors: Record<string, FabFloor>;
  validation: NetClassValidation[];
}

// PATCH /api/projects/{id}/net-classes
export interface SetNetClassesResult {
  project: string;
  committed: string;
  net_classes: NetClass[];
  validation: NetClassValidation[];
}

// PATCH /api/projects/{id}/design-rules
export interface SetDesignRulesResult {
  project: string;
  committed: string;
  design_rules: DesignRules;
}

// PATCH /api/projects/{id}/netclass-patterns
export interface SetNetclassPatternsResult {
  project: string;
  committed: string;
  netclass_patterns: { netclass: string; pattern: string }[];
}

// --- M7h KiField bulk-field editor ---

// One row of the field grid: a placed component keyed by reference. `fields` carries a value
// for every column (blank when the component lacks that field). A row is not editable when its
// reference is unannotated (ends "?") or it shares its designator with a differing component
// (a duplicate anomaly, named in `conflicts`).
export interface FieldRow {
  ref: string;
  sheet: string;
  lib_id: string;
  unannotated: boolean;
  editable: boolean;
  conflicts: string[];
  instances: number;
  fields: Record<string, string>;
}

// GET /api/projects/{id}/fields
export interface FieldsGrid {
  project: string;
  under_git: boolean;
  has_sch: boolean;
  columns: string[];
  readonly_columns: string[];
  rows: FieldRow[];
  summary: { components: number; editable: number; unannotated: number; duplicate: number };
}

// One field-cell edit the editor submits.
export interface FieldEdit {
  ref: string;
  field: string;
  value: string;
}

// PATCH /api/projects/{id}/fields
export interface SetFieldsResult {
  project: string;
  committed: string | null;
  components: number;
  fields: number;
  files: { path: string; components: number }[];
}

// One editable board-setup field the /settings endpoint describes so the form knows which
// control to render for it (M7f-A). `kind` picks the input; `label` is a Title Case caption.
export interface BoardSetupField {
  key: string;
  kind: "length" | "ratio" | "bool" | "coord";
  label: string;
}

// A board-setup value: a length/ratio number, a bool, or an [x, y] origin pair.
export type BoardSetupValue = number | boolean | [number, number];

// GET /api/projects/{id}/settings
export interface BoardSettings {
  project: string;
  under_git: boolean;
  has_board: boolean;
  board_setup: Record<string, BoardSetupValue>;
  thickness: number | null;
  fields: BoardSetupField[];
  // .kicad_pro settings (M7f-A2). erc_pin_map is null when the file has no matrix (never a
  // fabricated all-OK one, which would silently disable every pin-conflict check).
  has_pro: boolean;
  erc_severities: Record<string, string>;
  drc_severities: Record<string, string>;
  erc_pin_map: number[][] | null;
  text_variables: Record<string, string>;
  severity_levels: string[];
  erc_pin_types: string[];
}

// The body a settings PATCH sends: any concern alone, or several together in one atomic commit.
export interface SetBoardSettingsBody {
  board_setup?: Record<string, BoardSetupValue>;
  thickness?: number;
  erc_severities?: Record<string, string>;
  drc_severities?: Record<string, string>;
  erc_pin_map?: number[][];
  text_variables?: Record<string, string>;
}

// PATCH /api/projects/{id}/settings
export interface SetBoardSettingsResult extends BoardSettings {
  committed: string;
}

// --- M7f-B object conform (font/thickness normalize) -------------------------

// One conform category the editor offers (silk/fab/copper for the PCB, text/labels for the sheets).
export interface ConformCategory {
  key: string;
  label: string;
  hint: string;
}

// The suggested starting size/thickness (mm) for a category (thickness null where labels carry none).
export interface ConformSuggestion {
  size: number;
  thickness: number | null;
}

// GET /api/projects/{id}/conform
export interface ConformCatalog {
  project: string;
  under_git: boolean;
  has_pcb: boolean;
  has_sch: boolean;
  pcb_categories: ConformCategory[];
  sch_categories: ConformCategory[];
  suggested: Record<string, ConformSuggestion>;
}

// A per-category target the editor sends (either dimension may be omitted to leave it untouched).
export interface ConformTarget {
  size?: number;
  thickness?: number;
}

// POST /conform/preview and PATCH /conform body: only the selected categories are present.
export interface ConformBody {
  pcb_targets?: Record<string, ConformTarget>;
  sch_targets?: Record<string, ConformTarget>;
}

// One file's per-category change counts in a preview or apply result.
export interface ConformFile {
  path: string;
  counts: Record<string, number>;
  changed: number;
}

// POST /api/projects/{id}/conform/preview
export interface ConformPreview {
  project: string;
  files: ConformFile[];
  total: number;
}

// PATCH /api/projects/{id}/conform (committed is null when nothing changed: a no-commit no-op)
export interface ConformResult {
  project: string;
  committed: string | null;
  files: ConformFile[];
  total: number;
}

// --- M7f-C stackup / fab-preset ----------------------------------------------

// One physical layer in a board's stackup (a copper / dielectric / silk / paste / mask layer). Only
// the fields present on disk are set (a mask with no colour has no color).
export interface StackupLayer {
  name: string;
  type?: string;
  thickness?: number;
  material?: string;
  epsilon_r?: number;
  loss_tangent?: number;
  color?: string;
}

// A board's physical layer stack (or null when the board declares no stackup).
export interface Stackup {
  layers: StackupLayer[];
  copper_finish: string | null;
  dielectric_constraints: boolean | null;
}

// One fab preset the editor offers (a physical-stackup snap). verify_note is the honesty caveat.
export interface FabPreset {
  key: string;
  label: string;
  layers: number;
  board_thickness_mm: number;
  finish: string;
  soldermask_color: string | null;
  verify_note: string;
}

// GET /api/projects/{id}/stackup
export interface StackupRead {
  project: string;
  under_git: boolean;
  has_board: boolean;
  stackup: Stackup | null;
  copper_layers: string[];
  thickness: number | null;
  presets: FabPreset[];
}

// A per-layer field edit (any subset; an omitted field is left untouched).
export interface StackupLayerEdit {
  thickness?: number;
  material?: string;
  epsilon_r?: number;
  loss_tangent?: number;
}

// POST /stackup/preview and PATCH /stackup body: EITHER preset_key OR the field edits, never both.
export interface StackupBody {
  preset_key?: string;
  copper_finish?: string;
  dielectric_constraints?: boolean;
  layer_edits?: Record<string, StackupLayerEdit>;
}

// POST /api/projects/{id}/stackup/preview (the resulting stack + whether it differs from disk)
export interface StackupPreview {
  project: string;
  stackup: Stackup | null;
  thickness: number | null;
  changed: boolean;
  verify_note: string | null;
}

// PATCH /api/projects/{id}/stackup (committed is null when nothing changed: a no-commit no-op)
export interface StackupResult extends StackupRead {
  committed: string | null;
  changed: boolean;
}

// M7f-D Library Fill + Prepare/Complete-All + reversible Restore.
export interface FillChange {
  prop: string;
  old: string;
  new: string;
  kind: "fill" | "overwrite";
}

export interface FillPlanItem {
  ref: string;
  sheet: string;
  confidence: "symbol" | "mpn";
  part_id: string;
  changes: FillChange[];
  default_selected: boolean;
}

export interface FillPlan {
  items: FillPlanItem[];
  summary: { components: number; matched: number; no_match: number; fields: number };
}

export interface CompletionRoll {
  total: number;
  complete: number;
  incomplete_refs: string[];
  missing_counts: Record<string, number>;
}

// GET /api/projects/{id}/prepare (a dry-run: what a Prepare would annotate + fill + leave incomplete)
export interface PrepareRead {
  project: string;
  under_git: boolean;
  has_sch: boolean;
  annotate: number;
  fill_fields: number;
  files: { path: string; annotated: number; filled: number }[];
  plan: FillPlan;
  // The CURRENT on-disk residual: incomplete_refs are real disk designators, so the manual-fill
  // picker only names components that exist. completion_after is the projection once Prepare runs.
  completion: CompletionRoll;
  completion_after: CompletionRoll;
}

// The result of a Prepare job (POST /api/projects/{id}/prepare -> job -> this on the SSE result event)
export interface PrepareResult {
  project: string;
  committed: string | null;
  annotated: number;
  fill_fields: number;
  files: { path: string; annotated: number; filled: number }[];
  completion: CompletionRoll;
}

// POST /api/projects/{id}/prepare/fill
export interface ManualFillBody {
  ref: string;
  part_id: string;
}

export interface ManualFillResult {
  project: string;
  committed: string | null;
  ref: string;
  part_id: string;
}

// POST /api/projects/{id}/restore (revert the last Prepare/Fill commit as a new commit)
export interface RestoreResult {
  project: string;
  restored: string;
  short: string;
  subject: string;
  committed: string;
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
