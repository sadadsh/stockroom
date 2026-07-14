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
}

// POST /api/ingest/inspect -> a background job.
export interface JobRef {
  job_id: string;
}

// GET/PATCH /api/settings -> the redacted per-machine settings surface. The raw
// Mouser key never crosses the wire; only its presence and a last-4 hint do.
export interface SettingsInfo {
  mouser_api_key_set: boolean;
  mouser_api_key_hint: string;
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

// GET /api/system/info
export interface SystemInfo {
  active_profile: string;
  part_count: number;
  kicad_config_dir: string;
  kicad_running: boolean;
  kicad_cli_available: boolean;
  kicad_cli_path: string;
}
