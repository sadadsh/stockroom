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
}

export interface ApiErrorBody {
  error?: string;
  detail?: string;
  message?: string;
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
  kind: "missing_symbol" | "dangling_model" | "dangling_datasheet" | "dangling_model_link";
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

// GET /api/system/info
export interface SystemInfo {
  active_profile: string;
  part_count: number;
  kicad_config_dir: string;
  kicad_running: boolean;
  kicad_cli_available: boolean;
  kicad_cli_path: string;
}
