/**
 * A small typed fetch client over the Stockroom API. Sends the per-launch token
 * as a bearer header (the backend also accepts X-Stockroom-Token); both point at
 * the same guard. Reads are served from the warm index so responses are instant;
 * mutations go through the atomic engine and rebuild the index server-side, so
 * the caller invalidates the affected queries after a success.
 */
import { apiBase, apiToken } from "../lib/runtime";
import type {
  ActivateResponse,
  AltiumRegenerateResult,
  AltiumStatus,
  AuditResult,
  BomDiffResult,
  BomExportKind,
  BomResult,
  CadSourceResponse,
  ChecksResult,
  DiffResponse,
  DoctorScan,
  DuplicatesResponse,
  FabExportOptions,
  FabStatus,
  Facets,
  ParametricFacets,
  SearchResponse,
  HistoryResponse,
  JobRef,
  PartDetail,
  PassiveAddBody,
  PassivePreview,
  DesignResult,
  DesignRules,
  NetClass,
  PartsResponse,
  ProcurementExportOptions,
  ProcurementResult,
  ConformBody,
  ConformCatalog,
  ConformPreview,
  ConformResult,
  StackupBody,
  StackupPreview,
  StackupRead,
  StackupResult,
  PrepareRead,
  ManualFillBody,
  ManualFillResult,
  RestoreResult,
  FieldsGrid,
  FieldEdit,
  SetFieldsResult,
  Buildability,
  OnboardingStatus,
  ProfilesResponse,
  SetLibraryBody,
  ProjectDetail,
  ProjectSummary,
  BoardSettings,
  RepairResult,
  RescanStartResponse,
  RescanStateResponse,
  RevisionsResult,
  SetBoardSettingsBody,
  SetBoardSettingsResult,
  SetDesignRulesResult,
  SetNetclassPatternsResult,
  SetNetClassesResult,
  SettingsInfo,
  SettingsPatch,
  StagingCandidate,
  SyncResult,
  SyncStatus,
  SystemInfo,
  UpdateApply,
  UpdateCheck,
} from "./types";

export class ApiError extends Error {
  status: number;
  // The complete-to-add gate returns 422 with a `missing` label list; callers
  // (the ingest commit flow) read it to highlight exactly what still needs filling.
  missing?: string[];
  constructor(status: number, message: string, missing?: string[]) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.missing = missing;
  }
}

interface RequestOptions {
  // A value may be a string, or a string[] for a REPEATED query param (?spec=a&spec=b),
  // which the parametric spec filter needs.
  params?: Record<string, string | string[]>;
  body?: unknown;
}

async function request<T>(
  method: string,
  path: string,
  opts: RequestOptions = {},
): Promise<T> {
  const url = new URL(apiBase() + path);
  if (opts.params) {
    for (const [k, v] of Object.entries(opts.params)) {
      if (Array.isArray(v)) {
        for (const item of v) {
          if (item !== "" && item != null) url.searchParams.append(k, item);
        }
      } else if (v !== "" && v != null) {
        url.searchParams.set(k, v);
      }
    }
  }
  const token = apiToken();
  const headers: Record<string, string> = { Accept: "application/json" };
  if (token) headers.Authorization = `Bearer ${token}`;
  const init: RequestInit = { method, headers };
  if (opts.body !== undefined) {
    headers["Content-Type"] = "application/json";
    init.body = JSON.stringify(opts.body);
  }

  let res: Response;
  try {
    res = await fetch(url.toString(), init);
  } catch (err) {
    // network / connection refused: the server is not up. Surface it honestly.
    throw new ApiError(0, err instanceof Error ? err.message : "Network error");
  }

  if (!res.ok) {
    let msg = `Request failed (${res.status})`;
    let missing: string[] | undefined;
    try {
      const body = await res.json();
      msg = body.detail || body.error || body.message || msg;
      // The complete-to-add gate returns 422 with a `missing` label list; carry it
      // on the error so the ingest commit flow can highlight the unfilled fields.
      if (Array.isArray(body.missing)) missing = body.missing as string[];
    } catch {
      /* non-JSON error body, keep the status message */
    }
    throw new ApiError(res.status, msg, missing);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

function apiGet<T>(path: string, params?: Record<string, string>): Promise<T> {
  return request<T>("GET", path, { params });
}

// The preview endpoints return SVG text or GLB bytes, not JSON, and the guard needs
// the bearer, so a plain <img src>/loader URL cannot reach them. Fetch the body as a
// Blob with the token (the openJobStream idiom), mapping a non-2xx to an ApiError so
// the viewer can tell "no symbol" (404) from "no 3D tooling" (502) apart.
async function fetchPreviewBlob(path: string, accept: string): Promise<Blob> {
  const token = apiToken();
  const headers: Record<string, string> = { Accept: accept };
  if (token) headers.Authorization = `Bearer ${token}`;
  let res: Response;
  try {
    res = await fetch(apiBase() + path, { headers });
  } catch (err) {
    throw new ApiError(0, err instanceof Error ? err.message : "Network error");
  }
  if (!res.ok) {
    let msg = `Request failed (${res.status})`;
    try {
      const body = await res.json();
      msg = body.detail || body.error || body.message || msg;
    } catch {
      /* non-JSON error body, keep the status message */
    }
    throw new ApiError(res.status, msg);
  }
  return res.blob();
}

// Fetch a download endpoint (with the bearer) as {blob, filename}, reading the filename from
// the Content-Disposition header the export endpoint sets. Mirrors fetchPreviewBlob's error
// mapping so a 400 (nothing built) / 404 surfaces as an ApiError, not a corrupt file.
async function fetchDownload(
  path: string,
  params: Record<string, string>,
): Promise<{ blob: Blob; filename: string }> {
  const token = apiToken();
  const url = new URL(apiBase() + path);
  for (const [k, v] of Object.entries(params)) url.searchParams.set(k, v);
  const headers: Record<string, string> = {};
  if (token) headers.Authorization = `Bearer ${token}`;
  let res: Response;
  try {
    res = await fetch(url.toString(), { headers });
  } catch (err) {
    throw new ApiError(0, err instanceof Error ? err.message : "Network error");
  }
  if (!res.ok) {
    let msg = `Request failed (${res.status})`;
    try {
      const body = await res.json();
      msg = body.detail || body.error || body.message || msg;
    } catch {
      /* non-JSON error body, keep the status message */
    }
    throw new ApiError(res.status, msg);
  }
  const cd = res.headers.get("Content-Disposition") || "";
  const m = /filename="?([^";]+)"?/.exec(cd);
  return { blob: await res.blob(), filename: m ? m[1] : "export" };
}

// Save a blob to disk via a temporary object URL and a synthetic anchor click (the standard
// no-dependency browser download idiom). Runs in the WebView2 host; no-op-safe in tests.
function triggerDownload(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

export interface ListPartsArgs {
  q?: string;
  category?: string | null;
  completeOnly?: boolean;
}

export interface SearchArgs extends ListPartsArgs {
  // repeated spec constraints: "<key>:<value>" (an option) or "<key>:<min>~<max>" (a range)
  spec?: string[];
}

export const api = {
  listParts({ q, category, completeOnly }: ListPartsArgs): Promise<PartsResponse> {
    const params: Record<string, string> = {};
    if (q) params.q = q;
    if (category) params.category = category;
    if (completeOnly) params.complete_only = "true";
    return apiGet<PartsResponse>("/api/library/parts", params);
  },

  facets(): Promise<Facets> {
    return apiGet<Facets>("/api/library/facets");
  },

  // Filter dimensions generated from the parts' spec bags (the modular search rail), scoped by the
  // same text/category/completeness AND the live rail `spec` selections so the counts narrow as the
  // user picks (each facet excludes its own key server-side, so it still offers its other values).
  parametricFacets({ q, category, completeOnly, spec }: SearchArgs): Promise<ParametricFacets> {
    const params: Record<string, string | string[]> = {};
    if (q) params.q = q;
    if (category) params.category = category;
    if (completeOnly) params.complete_only = "true";
    if (spec && spec.length) params.spec = spec;
    return request<ParametricFacets>("GET", "/api/library/facets/parametric", { params });
  },

  // The rich results rows for the search table: same scope + `spec` filter as the lean list, but
  // each row carries its spec bag + a sourcing summary. `spec` is a repeated `<key>:<value>` /
  // `<key>:<min>~<max>` param (request() serializes the array to ?spec=a&spec=b).
  searchParts({ q, category, completeOnly, spec }: SearchArgs): Promise<SearchResponse> {
    const params: Record<string, string | string[]> = {};
    if (q) params.q = q;
    if (category) params.category = category;
    if (completeOnly) params.complete_only = "true";
    if (spec && spec.length) params.spec = spec;
    return request<SearchResponse>("GET", "/api/library/search", { params });
  },

  // Refresh every part's procurement data (price/stock/lifecycle) from the free distributor
  // APIs, in one incremental background job (Phase-1b-3). force=true re-checks every part,
  // ignoring the freshness window; already_running (instead of a new job_id) means a rescan
  // was already in flight, so the caller attaches to that job rather than starting a second.
  rescanLibrary(force = false): Promise<RescanStartResponse> {
    return request<RescanStartResponse>("POST", "/api/library/rescan", {
      params: force ? { force: "true" } : undefined,
    });
  },

  // The last-known rescan outcome per part (empty before any rescan has run on this
  // machine), for an honest "last refreshed" summary before the next run starts.
  getRescanState(): Promise<RescanStateResponse> {
    return apiGet<RescanStateResponse>("/api/library/rescan/state");
  },

  // Preview a file-less passive add (decode + resolve stock assets) without
  // committing; and commit one. Both take a bare MPN or a Mouser product URL.
  passivePreview(body: PassiveAddBody): Promise<PassivePreview> {
    return request<PassivePreview>("POST", "/api/library/passive/preview", { body });
  },

  passiveAdd(body: PassiveAddBody): Promise<PartDetail> {
    return request<PartDetail>("POST", "/api/library/passive", { body });
  },

  // Parts that share an MPN or a footprint name, straight from the derived index
  // (M6e). Read-only: the keep/delete resolution reuses deletePart.
  getDuplicates(): Promise<DuplicatesResponse> {
    return apiGet<DuplicatesResponse>("/api/duplicates");
  },

  partDetail(id: string): Promise<PartDetail> {
    return apiGet<PartDetail>(`/api/library/parts/${encodeURIComponent(id)}`);
  },

  // The part's git timeline (M6k): commits that touched its canonical JSON, newest
  // first. An uncommitted part honestly reports an empty list.
  partHistory(id: string): Promise<HistoryResponse> {
    return apiGet<HistoryResponse>(
      `/api/library/parts/${encodeURIComponent(id)}/history`,
    );
  },

  // A structured field-diff of the part JSON between two revs (M6k). `a` may be ""
  // (the earliest side, the part did not exist) and is dropped from the query by the
  // param serializer, so the backend applies its "" default and every field reads as
  // added. Both revs must lie in this part's own history or the backend returns 400.
  partDiff(id: string, a: string, b: string): Promise<DiffResponse> {
    return apiGet<DiffResponse>(
      `/api/library/parts/${encodeURIComponent(id)}/diff`,
      { a, b },
    );
  },

  // Previews (M6d). The symbol/footprint SVG is requested in the monochrome (?bw)
  // variant so the viewer can re-tint it to the active theme client-side; the 3D model
  // arrives as a GLB (STEP/WRL converted server-side) for the three.js viewer. A part
  // with no symbol/footprint/model is a 404, absent 3D tooling is a 502, both surfaced
  // honestly by the viewer.
  // When `rev` is given, the SVG is rendered from the git blob AS OF that revision
  // (M6k) rather than the working tree, so the timeline can overlay an old geometry
  // against the current one. A rev is content-immutable, so the backend caches it.
  previewSvg(kind: "symbol" | "footprint", id: string, rev?: string): Promise<Blob> {
    const params = new URLSearchParams({ bw: "true" });
    if (rev) params.set("rev", rev);
    return fetchPreviewBlob(
      `/api/previews/${kind}/${encodeURIComponent(id)}.svg?${params.toString()}`,
      "image/svg+xml",
    );
  },

  async modelGlb(id: string): Promise<ArrayBuffer> {
    const blob = await fetchPreviewBlob(
      `/api/previews/model/${encodeURIComponent(id)}.glb`,
      "model/gltf-binary",
    );
    return blob.arrayBuffer();
  },

  // Preview a KiCad STOCK footprint / 3D model by its lib_id (e.g.
  // "Resistor_SMD:R_0603_1608Metric"), with no committed part, so the Add-A-Part flow
  // can show a passive's built-in footprint + model before it is added. A lib_id that
  // is not installed is a 404, absent 3D tooling a 502, surfaced honestly by the viewer.
  stockPreviewSvg(fp: string): Promise<Blob> {
    return fetchPreviewBlob(
      `/api/previews/stock/footprint.svg?fp=${encodeURIComponent(fp)}&bw=true`,
      "image/svg+xml",
    );
  },

  async stockModelGlb(fp: string): Promise<ArrayBuffer> {
    const blob = await fetchPreviewBlob(
      `/api/previews/stock/model.glb?fp=${encodeURIComponent(fp)}`,
      "model/gltf-binary",
    );
    return blob.arrayBuffer();
  },

  // Edit one field (mirrored to the KiCad symbol where the field maps to a symbol
  // property; `tags` takes an array). Category is NOT edited here, it moves.
  editField(id: string, field: string, value: unknown): Promise<PartDetail> {
    return request<PartDetail>("PATCH", `/api/library/parts/${encodeURIComponent(id)}`, {
      body: { field, value },
    });
  },

  // Attach (or repoint) a symbol / footprint REFERENCE on an existing part AFTER it
  // was added (assets no longer gate entry; they are attachable after). The reference
  // is a lib_id (no file copied), tagged with the EDA tool it targets ("kicad" default).
  // `name` is required; an empty name is a 422 from the gate. Returns the updated record.
  attachSymbol(id: string, lib: string, name: string, tool = "kicad"): Promise<PartDetail> {
    return request<PartDetail>(
      "POST",
      `/api/library/parts/${encodeURIComponent(id)}/symbol`,
      { body: { lib, name, tool } },
    );
  },

  attachFootprint(id: string, lib: string, name: string, tool = "kicad"): Promise<PartDetail> {
    return request<PartDetail>(
      "POST",
      `/api/library/parts/${encodeURIComponent(id)}/footprint`,
      { body: { lib, name, tool } },
    );
  },

  // Persist canonical spec data (e.g. an enriched pinout) onto the record so a
  // viewer reads the source of truth (M6i). Each entry is {value, source?,
  // confidence?}; the server merges key-by-key (an existing key is kept unless
  // overwrite) and records provenance in the record's enrichment map.
  setSpecs(
    id: string,
    specs: Record<string, { value: unknown; source?: string; confidence?: string }>,
    overwrite = false,
  ): Promise<PartDetail> {
    return request<PartDetail>(
      "POST",
      `/api/library/parts/${encodeURIComponent(id)}/specs`,
      { body: { specs, overwrite } },
    );
  },

  moveCategory(id: string, category: string): Promise<PartDetail> {
    return request<PartDetail>(
      "POST",
      `/api/library/parts/${encodeURIComponent(id)}/move`,
      { body: { category } },
    );
  },

  deletePart(id: string): Promise<void> {
    return request<void>("DELETE", `/api/library/parts/${encodeURIComponent(id)}`);
  },

  // Look up a part by its MPN through the enrichment pipeline (scrape-first, spec
  // section 6.1). Returns the sourced candidate fields; the caller applies the ones
  // it wants through editField. A scrape miss returns null fields, never an error,
  // so completeness is never blocked by a dead source.
  enrichPart(
    mpn: string,
    category?: string,
    want?: string[],
  ): Promise<JobRef> {
    const body: Record<string, unknown> = { mpn };
    if (category) body.category = category;
    if (want && want.length > 0) body.want = want;
    // A background job (spec section 8): the render tier can take seconds, so this returns a
    // job ref and the sourced EnrichmentResult arrives on the job's SSE `result` event, with
    // live fetching/rendering/extracting/validating stages streamed as progress in between.
    return request<JobRef>("POST", "/api/enrich/part", { body });
  },

  // Paste a distributor product URL (a Mouser link) -> fetch it through the real
  // browser and get back EVERY field the page exposes (identity, price, datasheet,
  // package, full spec table). A blocked/dead page returns empty fields, not an error.
  // Returns a job ref; the result + live stages stream over the job's SSE (openJobStream).
  enrichFromUrl(url: string): Promise<JobRef> {
    return request<JobRef>("POST", "/api/enrich/from-url", { body: { url } });
  },

  // Inspect dropped file paths / LCSC ids into staging candidates. Returns a job
  // id; the candidates arrive on the job's SSE result event (openJobStream).
  ingestInspect(paths: string[], lcsc_ids: string[]): Promise<JobRef> {
    return request<JobRef>("POST", "/api/ingest/inspect", {
      body: { paths, lcsc_ids },
    });
  },

  // Bulk-enrich a pasted list of MPNs (one per line) or a BOM CSV (spec section 8.1). Returns a
  // job ref; the SSE stream ends with a BulkReport of per-MPN completeness. Triage only: it
  // reports what enrichment found, it does not add parts (each still needs a symbol to pass the
  // complete-to-add gate).
  enrichBulk(input: { text?: string; csv?: string; category?: string }): Promise<JobRef> {
    return request<JobRef>("POST", "/api/enrich/bulk", { body: input });
  },

  // Fill a staged candidate: apply the pasted datasheet/purchase links, read
  // identity from the stored datasheet, then enrich what is still blank. Returns a
  // job ref; the SSE result carries the updated candidate plus an honest report.
  ingestEnrich(body: {
    candidate: StagingCandidate;
    datasheet_url?: string;
    purchase_url?: string;
    datasheet_file?: string;
  }): Promise<JobRef> {
    return request<JobRef>("POST", "/api/ingest/enrich", { body });
  },

  // Add a staging candidate to the library. On success returns the new record; on
  // the complete-to-add gate failure it throws ApiError (422) with `missing` set.
  ingestCommit(candidate: StagingCandidate): Promise<PartDetail> {
    return request<PartDetail>("POST", "/api/ingest/commit", { body: candidate });
  },

  // Resolve an existing part's DigiKey CAD-download source from its MPN (Phase-2 asset
  // download, spec section 5). A resolvable 200 either way; `url` is null when the part
  // has no MPN, DigiKey is disabled, or nothing resolved - never an error.
  partCadSource(id: string): Promise<CadSourceResponse> {
    return apiGet<CadSourceResponse>(
      `/api/library/parts/${encodeURIComponent(id)}/cad-source`,
    );
  },

  // Unpack a downloaded CAD ZIP for an EXISTING part into staging candidates. Same
  // read-lane job + candidate DTO shape as ingestInspect; the result arrives on the
  // job's SSE result event (openJobStream).
  assetsInspect(partId: string, paths: string[]): Promise<JobRef> {
    return request<JobRef>(
      "POST",
      `/api/parts/${encodeURIComponent(partId)}/assets/inspect`,
      { body: { paths } },
    );
  },

  // Attach a reviewed candidate's symbol/footprint/3D onto the existing part,
  // synchronously (one atomic Transaction). Only the assets the candidate actually
  // carries are touched; an already-present asset is left alone.
  assetsCommit(partId: string, candidate: StagingCandidate): Promise<PartDetail> {
    return request<PartDetail>(
      "POST",
      `/api/parts/${encodeURIComponent(partId)}/assets/commit`,
      { body: candidate },
    );
  },

  // Open a job's Server-Sent Events stream. Native EventSource cannot send the
  // bearer token, so this reads the stream through fetch (see lib/sse) and returns
  // the raw body for streamEvents to parse.
  async openJobStream(jobId: string): Promise<ReadableStream<Uint8Array>> {
    const token = apiToken();
    const headers: Record<string, string> = { Accept: "text/event-stream" };
    if (token) headers.Authorization = `Bearer ${token}`;
    const res = await fetch(
      apiBase() + `/api/jobs/${encodeURIComponent(jobId)}/events`,
      { headers },
    );
    if (!res.ok || !res.body) {
      throw new ApiError(res.status || 0, `Job stream failed (${res.status})`);
    }
    return res.body;
  },

  // Per-machine settings (spec section 11). The GET is redacted (presence + a
  // last-4 hint, never the raw key); the PATCH applies live on the server and
  // persists. Only fields present in the patch are touched.
  getSettings(): Promise<SettingsInfo> {
    return apiGet<SettingsInfo>("/api/settings");
  },

  updateSettings(patch: SettingsPatch): Promise<SettingsInfo> {
    return request<SettingsInfo>("PATCH", "/api/settings", { body: patch });
  },

  // Dev convenience (the hidden Settings combo): load any API keys / logins from the per-machine
  // dev-creds.json (in the OS config dir, never the public repo) into the config. Returns the
  // redacted settings plus `loaded`, the field names that were applied.
  loadDevCreds(): Promise<SettingsInfo & { loaded: string[] }> {
    return request<SettingsInfo & { loaded: string[] }>(
      "POST",
      "/api/settings/load-dev-creds",
    );
  },

  // Library profiles (spec section 5.3). Activating one rebuilds the index, so
  // the caller invalidates the parts list and facets after it resolves.
  listProfiles(): Promise<ProfilesResponse> {
    return apiGet<ProfilesResponse>("/api/profiles");
  },

  createProfile(name: string, archive = false): Promise<ProfilesResponse> {
    return request<ProfilesResponse>("POST", "/api/profiles", {
      body: { name, archive },
    });
  },

  activateProfile(name: string): Promise<ActivateResponse> {
    return request<ActivateResponse>(
      "POST",
      `/api/profiles/${encodeURIComponent(name)}/activate`,
    );
  },

  deleteProfile(name: string): Promise<void> {
    return request<void>("DELETE", `/api/profiles/${encodeURIComponent(name)}`);
  },

  // Library repo sync (spec section 9): offline and divergence are first-class
  // states surfaced verbatim, never guessed.
  getSyncStatus(): Promise<SyncStatus> {
    return apiGet<SyncStatus>("/api/sync/status");
  },

  doSync(): Promise<SyncResult> {
    return request<SyncResult>("POST", "/api/sync");
  },

  // First-run library onboarding (M9b/M9c): point the app at a library (open an existing
  // one, clone a git URL, or create a fresh one) and repoint the running engine at it live.
  // A set/complete changes which library EVERY other query reads, so callers invalidate all.
  // One ready-to-build verdict per project (M7g): completeness + ERC/DRC + BOM + git fused,
  // with honest cold-cache states (read-only; the caches are read, never re-run here).
  getBuildability(projectId: string): Promise<Buildability> {
    return apiGet<Buildability>(
      `/api/projects/${encodeURIComponent(projectId)}/buildability`,
    );
  },

  getOnboarding(): Promise<OnboardingStatus> {
    return apiGet<OnboardingStatus>("/api/onboarding");
  },

  setLibrary(body: SetLibraryBody): Promise<OnboardingStatus> {
    return request<OnboardingStatus>("POST", "/api/onboarding/library", { body });
  },

  completeOnboarding(): Promise<OnboardingStatus> {
    return request<OnboardingStatus>("POST", "/api/onboarding/complete");
  },

  // App self-update (spec section 12), distinct from library sync.
  checkUpdate(): Promise<UpdateCheck> {
    return apiGet<UpdateCheck>("/api/update/check");
  },

  applyUpdate(): Promise<UpdateApply> {
    return request<UpdateApply>("POST", "/api/update/apply");
  },

  getSystemInfo(): Promise<SystemInfo> {
    return apiGet<SystemInfo>("/api/system/info");
  },

  // Doctor (M6f). A read-only health scan (what the repair would fix, so the diff is
  // shown before healing); the one-click repair (a synchronous mutation like
  // edit/move/delete that heals drift, rewrites non-portable model links and commits
  // stray files atomically); and KiCad wiring, which registers the active profile into
  // KiCad and runs as a job because it may rewrite the KiCad config.
  scanDoctor(): Promise<DoctorScan> {
    return apiGet<DoctorScan>("/api/doctor/scan");
  },

  repairLibrary(): Promise<RepairResult> {
    return request<RepairResult>("POST", "/api/doctor/repair");
  },

  wireKicad(): Promise<JobRef> {
    return request<JobRef>("POST", "/api/doctor/wire-kicad");
  },

  // Projects (M7a). A registered project is external to Stockroom (referenced by
  // path, never owned); only its registration record lives in the library repo.
  // List reads the warm project index; register/delete rebuild it server-side, so
  // the caller invalidates ["projects"] (and the affected ["project", id]) after.
  listProjects(): Promise<ProjectSummary[]> {
    return apiGet<ProjectSummary[]>("/api/projects");
  },

  // Register an external project directory by its absolute path. A bad/nonexistent
  // dir, a dir with no KiCad files, or an already-registered root each returns 400.
  registerProject(root: string): Promise<ProjectDetail> {
    return request<ProjectDetail>("POST", "/api/projects", { body: { root } });
  },

  getProject(id: string): Promise<ProjectDetail> {
    return apiGet<ProjectDetail>(`/api/projects/${encodeURIComponent(id)}`);
  },

  // Unregister a project (its external files are never touched). 204 on success.
  deleteProject(id: string): Promise<void> {
    return request<void>("DELETE", `/api/projects/${encodeURIComponent(id)}`);
  },

  // The read-only health audit over the registered sheets, resolved against the
  // ACTIVE profile's footprint/model dirs, plus a shareable markdown report.
  projectAudit(id: string): Promise<AuditResult> {
    return apiGet<AuditResult>(`/api/projects/${encodeURIComponent(id)}/audit`);
  },

  // Run structured ERC + DRC (M7b) off the request path as a job (findings arrive on
  // the job's SSE result event, openJobStream). A missing kicad-cli is an honest 502.
  runChecks(id: string): Promise<JobRef> {
    return request<JobRef>("POST", `/api/projects/${encodeURIComponent(id)}/checks`);
  },

  // The cached last ERC/DRC run, or an honest not-run shape (ran_at null) before the
  // first run. Read on selecting a project so a prior run renders without re-running.
  getChecks(id: string): Promise<ChecksResult> {
    return apiGet<ChecksResult>(`/api/projects/${encodeURIComponent(id)}/checks`);
  },

  // Build a grouped, priced BOM (M7c) off the request path as a job (the built BOM
  // arrives on the job's SSE result event). No kicad-cli needed; pricing is best-effort
  // through the enrich layer, so a line that cannot be sourced stays honestly unpriced.
  // `opts` carries the build quantity + tax/tariff rate the per-line economics cost at;
  // both default server-side (1 board, 0% tax) when omitted.
  runBom(id: string, opts?: { boards?: number; tax_rate?: number }): Promise<JobRef> {
    return request<JobRef>("POST", `/api/projects/${encodeURIComponent(id)}/bom`, {
      body: opts ?? {},
    });
  },

  // The cached last build, or an honest not-built shape (ran_at null) before the first
  // build. Read on selecting a project so a prior build renders without rebuilding.
  getBom(id: string): Promise<BomResult> {
    return apiGet<BomResult>(`/api/projects/${encodeURIComponent(id)}/bom`);
  },

  // Re-cost the CACHED BOM for a new build quantity / tax/tariff rate, purely over the
  // already-built lines (no schematic re-read, no network, no job/SSE): synchronous.
  // Before any build it returns the same honest not-built shape as getBom.
  repriceBom(id: string, opts: { boards?: number; tax_rate?: number }): Promise<BomResult> {
    return request<BomResult>("POST", `/api/projects/${encodeURIComponent(id)}/bom/reprice`, {
      body: opts,
    });
  },

  // The per-line orderability + sourcing/stock risk + lead time computed over the cached
  // BOM (M7d). Honest not-built shape (built false) before a build; never a fabricated risk.
  getProcurement(id: string): Promise<ProcurementResult> {
    return apiGet<ProcurementResult>(`/api/projects/${encodeURIComponent(id)}/procurement`);
  },

  // The Fab panel's honest gate (M7i): whether the project has a board to fabricate and
  // whether kicad-cli is available, plus the board file names. Read-only, no shell-out.
  getFab(id: string): Promise<FabStatus> {
    return apiGet<FabStatus>(`/api/projects/${encodeURIComponent(id)}/fab`);
  },

  // Raw bytes (as text) of one REGISTERED project KiCad file, for the in-app kicanvas viewer
  // (M7 #11). Fetched WITH the bearer and inlined as a kicanvas-source, so the viewer never
  // issues its own unauthenticated fetch. An unregistered path / unknown id / escape is a 404.
  async projectFile(id: string, path: string): Promise<string> {
    const token = apiToken();
    const headers: Record<string, string> = {};
    if (token) headers.Authorization = `Bearer ${token}`;
    const url = new URL(apiBase() + `/api/projects/${encodeURIComponent(id)}/file`);
    url.searchParams.set("path", path);
    let res: Response;
    try {
      res = await fetch(url.toString(), { headers });
    } catch (err) {
      throw new ApiError(0, err instanceof Error ? err.message : "Network error");
    }
    if (!res.ok) {
      let msg = `Request failed (${res.status})`;
      try {
        const body = await res.json();
        msg = body.detail || body.error || body.message || msg;
      } catch {
        /* non-JSON error body */
      }
      throw new ApiError(res.status, msg);
    }
    return res.text();
  },

  // Download the manufacturing bundle (gerbers + drill + placement) plotted via kicad-cli as
  // a zip (M7i). Fetches with the bearer token and saves via a temporary object URL. Options
  // map straight to the export query params; a missing/failed kicad-cli surfaces as an
  // ApiError (502), never a corrupt/empty file.
  async downloadFabExport(id: string, opts: FabExportOptions): Promise<void> {
    const params: Record<string, string> = {
      drill_format: opts.drillFormat,
      drill_map: String(opts.drillMap),
      include_pos: String(opts.includePos),
      pos_format: opts.posFormat,
      protel_ext: String(opts.protelExt),
    };
    if (opts.board) params.board = opts.board;
    const { blob, filename } = await fetchDownload(
      `/api/projects/${encodeURIComponent(id)}/fab/export`,
      params,
    );
    triggerDownload(blob, filename);
  },

  // The project's git history for the revision-diff pickers (M7d). under_git false / empty
  // for a project not under git.
  getRevisions(id: string): Promise<RevisionsResult> {
    return apiGet<RevisionsResult>(`/api/projects/${encodeURIComponent(id)}/revisions`);
  },

  // Diff the BOM between revision `a` (from the project's git) and `b` (blank = the current
  // build) (M7d). The current build's prices feed the cost/lead deltas.
  getBomDiff(id: string, a: string, b = ""): Promise<BomDiffResult> {
    const params: Record<string, string> = { a };
    if (b) params.b = b;
    return apiGet<BomDiffResult>(`/api/projects/${encodeURIComponent(id)}/bom/diff`, params);
  },

  // Download a BOM export (M7d). Fetches the named binary with the bearer token and saves it
  // via a temporary object URL, so a CSV / XLSX / cart / JLCPCB sheet lands as a file. The
  // optional procurement knobs (spares / PCB pack / tax / shipping / labour / assembly) are
  // threaded to the Procurement Sheet + Mouser Cart exports; a null/undefined knob is omitted.
  async downloadBomExport(
    id: string,
    kind: BomExportKind,
    opts?: ProcurementExportOptions,
  ): Promise<void> {
    const params: Record<string, string> = { kind };
    if (opts) {
      for (const [k, v] of Object.entries(opts)) {
        if (v != null) params[k] = String(v);
      }
    }
    const { blob, filename } = await fetchDownload(
      `/api/projects/${encodeURIComponent(id)}/bom/export`,
      params,
    );
    triggerDownload(blob, filename);
  },

  // The project's current net classes + design rules read from its .kicad_pro, plus the
  // fab-floor catalog and a validation against `floor` (M7e). Read-only.
  getDesign(id: string, floor?: string): Promise<DesignResult> {
    const params: Record<string, string> = {};
    if (floor) params.floor = floor;
    return apiGet<DesignResult>(`/api/projects/${encodeURIComponent(id)}/design`, params);
  },

  // Edit the project's net classes (M7e): the full edited set, names to delete, and the
  // fab floor the returned validation checks against. Writes a minimal diff, one scoped
  // commit on the project's own git.
  setNetClasses(
    id: string,
    classes: NetClass[],
    opts?: { deleted?: string[]; floor?: string },
  ): Promise<SetNetClassesResult> {
    return request<SetNetClassesResult>(
      "PATCH",
      `/api/projects/${encodeURIComponent(id)}/net-classes`,
      { body: { classes, deleted: opts?.deleted ?? [], floor: opts?.floor ?? "none" } },
    );
  },

  // Edit the project's board design-rule constraints (M7e). `rules` field-merges; the size
  // lists, when given, replace their arrays wholesale.
  setDesignRules(
    id: string,
    rules: DesignRules,
    opts?: { track_widths?: unknown[]; via_dimensions?: unknown[]; diff_pair_dimensions?: unknown[] },
  ): Promise<SetDesignRulesResult> {
    return request<SetDesignRulesResult>(
      "PATCH",
      `/api/projects/${encodeURIComponent(id)}/design-rules`,
      { body: { rules, ...opts } },
    );
  },

  // Replace the project's netclass-pattern assignments (roadmap #4): the FULL edited list
  // (an empty list clears every pattern). Writes a minimal diff, one scoped commit on the
  // project's own git.
  setNetclassPatterns(
    id: string,
    patterns: { netclass: string; pattern: string }[],
  ): Promise<SetNetclassPatternsResult> {
    return request<SetNetclassPatternsResult>(
      "PATCH",
      `/api/projects/${encodeURIComponent(id)}/netclass-patterns`,
      { body: { patterns } },
    );
  },

  // The KiField bulk-field grid: every placed component across every sheet as a rows-by-fields
  // table, Reference read-only (M7h). Read-only.
  getFields(id: string): Promise<FieldsGrid> {
    return apiGet<FieldsGrid>(`/api/projects/${encodeURIComponent(id)}/fields`);
  },

  // Apply a batch of field-cell edits across the project's schematic as ONE atomic commit on its
  // own git (M7h). `edits` is the full set of changed cells; the engine validates each against
  // the on-disk grid and refuses the read-only Reference field / a non-editable ref.
  setFields(id: string, edits: FieldEdit[]): Promise<SetFieldsResult> {
    return request<SetFieldsResult>(
      "PATCH",
      `/api/projects/${encodeURIComponent(id)}/fields`,
      { body: { edits } },
    );
  },

  // The project's current board setup (mask/paste clearances, via protection, origins) +
  // overall thickness read from its primary .kicad_pcb, plus the editable-field schema the
  // form renders (M7f-A). Read-only.
  getBoardSettings(id: string): Promise<BoardSettings> {
    return apiGet<BoardSettings>(`/api/projects/${encodeURIComponent(id)}/settings`);
  },

  // Edit the project's board setup / thickness (its .kicad_pcb) and/or its .kicad_pro settings
  // (ERC/DRC severities, ERC pin map, text variables) (M7f-A + A2). Every field is optional;
  // whichever are given write a minimal diff as one atomic scoped commit on the project's git.
  setBoardSettings(id: string, body: SetBoardSettingsBody): Promise<SetBoardSettingsResult> {
    return request<SetBoardSettingsResult>(
      "PATCH",
      `/api/projects/${encodeURIComponent(id)}/settings`,
      { body },
    );
  },

  // The object-conform category catalog (Title Case labels + suggested sizes) plus the project's
  // honest state (has a board / a sheet / under git), for the editor's initial render (M7f-B).
  getConform(id: string): Promise<ConformCatalog> {
    return apiGet<ConformCatalog>(`/api/projects/${encodeURIComponent(id)}/conform`);
  },

  // A dry-run of an object conform: per-file change counts for the given targets, computed
  // without writing or touching git (M7f-B).
  previewConform(id: string, body: ConformBody): Promise<ConformPreview> {
    return request<ConformPreview>(
      "POST",
      `/api/projects/${encodeURIComponent(id)}/conform/preview`,
      { body },
    );
  },

  // Apply the conform across every board + sheet as one atomic commit on the project's own git
  // (M7f-B). `committed` is null when nothing changed (an honest no-commit no-op).
  applyConform(id: string, body: ConformBody): Promise<ConformResult> {
    return request<ConformResult>(
      "PATCH",
      `/api/projects/${encodeURIComponent(id)}/conform`,
      { body },
    );
  },

  // The project's current physical layer stack + copper layer names + thickness + the fab-preset
  // catalog, for the Stackup editor's render (M7f-C).
  getStackup(id: string): Promise<StackupRead> {
    return apiGet<StackupRead>(`/api/projects/${encodeURIComponent(id)}/stackup`);
  },

  // A dry-run of a stackup change (a fab preset OR per-field edits): the resulting stack + new
  // thickness + whether it differs, computed without writing or touching git (M7f-C).
  previewStackup(id: string, body: StackupBody): Promise<StackupPreview> {
    return request<StackupPreview>(
      "POST",
      `/api/projects/${encodeURIComponent(id)}/stackup/preview`,
      { body },
    );
  },

  // Apply a stackup change as one atomic commit on the project's own git (M7f-C). `committed` is
  // null when nothing changed (an honest no-commit no-op).
  applyStackup(id: string, body: StackupBody): Promise<StackupResult> {
    return request<StackupResult>(
      "PATCH",
      `/api/projects/${encodeURIComponent(id)}/stackup`,
      { body },
    );
  },

  // A dry-run of Prepare / Complete-All: what a Prepare would annotate + auto-fill (from the shared
  // library) + leave incomplete, computed without writing or touching git (M7f-D).
  getPrepare(id: string): Promise<PrepareRead> {
    return apiGet<PrepareRead>(`/api/projects/${encodeURIComponent(id)}/prepare`);
  },

  // Prepare / Complete-All off the request path as a job (the counts + residual arrive on the job's
  // SSE result event, openJobStream). Annotate + auto-fill blank identity in one atomic commit (M7f-D).
  runPrepare(id: string): Promise<JobRef> {
    return request<JobRef>("POST", `/api/projects/${encodeURIComponent(id)}/prepare`);
  },

  // Manually link one placed component to a chosen library part (the residual filler), one atomic
  // commit (M7f-D). `committed` is null when nothing changed.
  manualFill(id: string, body: ManualFillBody): Promise<ManualFillResult> {
    return request<ManualFillResult>(
      "POST",
      `/api/projects/${encodeURIComponent(id)}/prepare/fill`,
      { body },
    );
  },

  // Undo the project's last Prepare / Fill by git-reverting that commit as a new commit (M7f-D).
  restore(id: string): Promise<RestoreResult> {
    return request<RestoreResult>("POST", `/api/projects/${encodeURIComponent(id)}/restore`);
  },

  // The Altium Database Library status for the active profile: place-ready count + per-part rows.
  altiumStatus(): Promise<AltiumStatus> {
    return apiGet<AltiumStatus>("/api/altium/status");
  },

  // Regenerate the DbLib + its data source over every place-ready part (synchronous, one commit).
  altiumRegenerate(): Promise<AltiumRegenerateResult> {
    return request<AltiumRegenerateResult>("POST", "/api/altium/regenerate");
  },

  // Attach a part's Altium assets (a .SchLib + .PcbLib pair or a single .IntLib) by their native
  // filesystem paths (host-captured, same as ingest). Synchronous, one atomic commit.
  altiumAttach(partId: string, paths: string[]): Promise<unknown> {
    return request<unknown>(
      "POST",
      `/api/altium/parts/${encodeURIComponent(partId)}/attach`,
      { body: { paths } },
    );
  },
};
