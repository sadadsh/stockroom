/**
 * A small typed fetch client over the Stockroom API. Sends the per-launch token
 * as a bearer header (the backend also accepts X-Stockroom-Token); both point at
 * the same guard. Reads are served from the warm index so responses are instant;
 * mutations go through the atomic engine and rebuild the index server-side, so
 * the caller invalidates the affected queries after a success.
 */
import {
  dispatchApiRequest,
  type ApiRequestDescriptor,
  type ApiRequestParams,
} from "../design-studio/requestAdapter";
import { apiBase, apiToken } from "../lib/runtime";
import type {
  ComponentDossier,
  ComponentProvidersView,
  CoverageArtifact,
} from "./dossierTypes";
import type {
  ActivateResponse,
  ApproveProjectReviewResult,
  AssemblyRun,
  AltiumEmbedCapability,
  AltiumEmbedResult,
  AltiumModelsPending,
  LibraryCoverage,
  CompletionRunRef,
  WorkflowBatchSnapshot,
  WorkflowControlResult,
  WorkflowEventsPage,
  LibraryDerivation,
  CadInventory,
  AltiumRegenerateResult,
  AltiumSetupResult,
  DevSaveBody,
  DevSaveResult,
  DevWorkspaceStatus,
  DevPublishResult,
  DevPromoteBody,
  DevPromoteResult,
  AltiumStatus,
  OdbcStatus,
  CadSourceResponse,
  CaptureBatchWorklist,
  CaptureWorkflowSession,
  ConnectProjectRemoteResult,
  PartShell,
  DiffResponse,
  DoctorScan,
  DuplicatesResponse,
  Facets,
  ParametricFacets,
  SearchResponse,
  HistoryResponse,
  JobRef,
  GuidedRepositoryBody,
  GuidedSourceDataBody,
  GitHubRepositoriesResponse,
  PartDetail,
  PassiveAddBody,
  PassivePreview,
  PartsResponse,
  HygieneRead,
  HygieneResult,
  LibraryLfsResult,
  LibraryLfsStatus,
  OnboardingStatus,
  OpenProjectDocumentResult,
  ProfilesResponse,
  ProjectSummary,
  ProjectBom,
  ProjectAssignments,
  ProjectCollaboration,
  ProjectPlacementGeometry,
  ProjectVisualBundle,
  ProjectReviewCandidate,
  ProjectReviewEvidence,
  ProjectNativeValidation,
  ProjectReviews,
  RequestProjectChangesResult,
  FinishWorkSessionResult,
  ProjectWorkspace,
  DiscoveredProject,
  SetLibraryBody,
  RepairResult,
  RescanStartResponse,
  RescanStateResponse,
  SettingsInfo,
  SettingsPatch,
  StagingCandidate,
  SyncResult,
  SyncStatus,
  SystemInfo,
  UpdateApply,
  UpdateCheck,
  StmStatusDTO,
  McusResponse,
  FamiliesResponse,
  PinoutDTO,
  CompatUnionBody,
  UnionDTO,
  TargetDefinitionBody,
  TargetDefinitionDTO,
  SocketSolutionDTO,
  PinAfResponse,
  SignalCandidatesResponse,
  SuggestionsResponse,
  AfCheckBody,
  AfCheckResponse,
  PersonalDesignResponse,
  PersonalDesignSaveBody,
  PersonalDesignPageExitBody,
  PersonalDesignDeleteBody,
  PersonalDesignDeleteResponse,
  AppliedDesignSaveBody,
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
  keepalive?: boolean;
}

function responseErrorMessage(body: unknown, fallback: string): string {
  if (!body || typeof body !== "object") return fallback;
  const payload = body as Record<string, unknown>;
  for (const key of ["detail", "error", "message"]) {
    const value = payload[key];
    if (typeof value === "string" && value.trim()) return value;
  }
  if (Array.isArray(payload.detail)) {
    const messages = payload.detail
      .map((entry) =>
        entry && typeof entry === "object"
          ? (entry as Record<string, unknown>).msg
          : null,
      )
      .filter((message): message is string => typeof message === "string")
      .map((message) => message.replace(/^Value error,\s*/i, "").trim())
      .filter(Boolean);
    if (messages.length) return [...new Set(messages)].join(" ");
  }
  return fallback;
}

async function request<T>(
  method: string,
  path: string,
  opts: RequestOptions = {},
): Promise<T> {
  const descriptor: ApiRequestDescriptor = {
    method,
    path,
    params: opts.params ?? {},
    body: opts.body,
  };
  return dispatchApiRequest(descriptor, () => liveJsonRequest<T>(descriptor, opts.keepalive));
}

function requestUrl(path: string, params: ApiRequestParams): URL {
  const url = new URL(apiBase() + path);
  for (const [k, v] of Object.entries(params)) {
    if (typeof v !== "string") {
      for (const item of v) {
        if (item !== "" && item != null) url.searchParams.append(k, item);
      }
    } else if (v !== "" && v != null) {
      url.searchParams.set(k, v);
    }
  }
  return url;
}

async function liveJsonRequest<T>(descriptor: ApiRequestDescriptor, keepalive = false): Promise<T> {
  const url = requestUrl(descriptor.path, descriptor.params);
  const token = apiToken();
  const headers: Record<string, string> = { Accept: "application/json" };
  if (token) headers.Authorization = `Bearer ${token}`;
  const init: RequestInit = { method: descriptor.method, headers, keepalive };
  if (descriptor.body !== undefined) {
    headers["Content-Type"] = "application/json";
    init.body = JSON.stringify(descriptor.body);
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
      msg = responseErrorMessage(body, msg);
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
  const descriptor = descriptorFromPath("GET", path);
  return dispatchApiRequest(descriptor, () => livePreviewBlob(descriptor, accept));
}

async function livePreviewBlob(
  descriptor: ApiRequestDescriptor,
  accept: string,
): Promise<Blob> {
  const token = apiToken();
  const headers: Record<string, string> = { Accept: accept };
  if (token) headers.Authorization = `Bearer ${token}`;
  let res: Response;
  try {
    res = await fetch(requestUrl(descriptor.path, descriptor.params).toString(), { headers });
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

export interface DownloadedFile {
  blob: Blob;
  filename: string;
}

async function fetchDownload(
  path: string,
  params: Record<string, string>,
): Promise<DownloadedFile> {
  const descriptor: ApiRequestDescriptor = { method: "GET", path, params, body: undefined };
  return dispatchApiRequest(descriptor, () => liveDownload(descriptor));
}

async function liveDownload(descriptor: ApiRequestDescriptor): Promise<DownloadedFile> {
  const url = requestUrl(descriptor.path, descriptor.params);
  const token = apiToken();
  const headers: Record<string, string> = { Accept: "text/csv" };
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
  const disposition = res.headers.get("content-disposition") || "";
  const match = disposition.match(/filename="?([^";]+)"?/i);
  return {
    blob: await res.blob(),
    filename: match?.[1] || "stockroom-bom.csv",
  };
}

function descriptorFromPath(method: string, pathWithQuery: string): ApiRequestDescriptor {
  const parsed = new URL(pathWithQuery, "http://stockroom.local");
  const params: Record<string, string | string[]> = {};
  for (const key of new Set(parsed.searchParams.keys())) {
    const values = parsed.searchParams.getAll(key);
    params[key] = values.length === 1 ? values[0] : values;
  }
  return { method, path: parsed.pathname, params, body: undefined };
}

export interface LandPad {
  number: string;
  /** millimetres from the footprint origin, KiCad's frame (+Y down) */
  at: [number, number];
  size: [number, number];
  shape: string;
  /** degrees */
  rotation: number;
  /** hole diameter in mm; 0 for SMD */
  drill: number;
  /** thru_hole / smd / np_thru_hole */
  pad_type: string;
  /** front / back / both, from the pad's declared copper layer */
  side: string;
  /** KiCad's roundrect corner ratio */
  rratio: number;
  /**
   * The layers the pad DECLARES, verbatim (`F.Cu`, `F.Mask`, `F.Paste`, ...).
   *
   * Mask and paste cannot be inferred from copper: a pad that opens no aperture and one that
   * opens a full aperture are identical in copper and are different fabrication outcomes. A
   * viewer that defaulted them would draw an aperture the footprint never asked for.
   */
  layers: string[];
}

export interface LandGraphic {
  start: [number, number];
  end: [number, number];
  /** KiCad layer, e.g. F.SilkS (the human-readable outline) or F.CrtYd (the keep-out). */
  layer: string;
  width: number;
}

export interface LandPattern {
  units: string;
  pads: LandPad[];
  graphics: LandGraphic[];
  model_placement: {
    offset: [number, number, number];
    scale: [number, number, number];
    rotate: [number, number, number];
  } | null;
}

/** One terminal of a symbol, in KiCad's schematic frame (mm, +Y UP, degrees). */
export interface SymbolPin {
  number: string;
  name: string;
  /** The pin's electrical type: input, output, power_in, passive, ... A fact about the SYMBOL. */
  electrical: string;
  /** The drawn graphic style: line, inverted, clock, ... */
  style: string;
  /** The connection point. The pin body runs from here in the direction of `angle`. */
  at: [number, number];
  angle: number;
  length: number;
  hidden: boolean;
}

/** One drawn shape of a symbol body. Arcs arrive already flattened into a polyline. */
export interface SymbolGraphic {
  kind: "rectangle" | "circle" | "polyline";
  points: [number, number][];
  center: [number, number];
  radius: number;
  width: number;
  /** KiCad's fill type: none / outline / background. */
  fill: string;
  closed: boolean;
}

/**
 * A symbol's pins and body, read from the file rather than measured off a rendered picture.
 *
 * `bounds` is null when the symbol draws nothing at all - a real absence, not a zero box, which
 * would read as a body that collapsed.
 */
export interface SymbolGeometry {
  units: string;
  name: string;
  /** What the FILE asks for. A symbol whose author hid its names is not one missing them. */
  namesHidden: boolean;
  numbersHidden: boolean;
  pins: SymbolPin[];
  graphics: SymbolGraphic[];
  bounds: { x: number; y: number; width: number; height: number } | null;
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

// The coarse server-side scope for GET /api/stm/mcus. Every field is optional; an omitted /
// empty field is dropped from the query (like listParts), so a blank scope returns the FULL
// spec matrix for client-side TanStack filtering (INTERFACES.md section 4).
export interface StmMcusArgs {
  q?: string;
  family?: string;
  core?: string;
  package?: string;
  series?: string;
}

export const api = {
  designStudioGet(): Promise<PersonalDesignResponse> {
    return request<PersonalDesignResponse>("GET", "/api/design-studio/personal");
  },

  designStudioPut(body: PersonalDesignSaveBody): Promise<PersonalDesignResponse> {
    return request<PersonalDesignResponse>("PUT", "/api/design-studio/personal", { body });
  },

  designStudioPutForPageExit(body: PersonalDesignPageExitBody): Promise<PersonalDesignResponse> {
    return request<PersonalDesignResponse>("PUT", "/api/design-studio/personal/page-exit", {
      body,
      keepalive: true,
    });
  },

  designStudioDelete(body: PersonalDesignDeleteBody): Promise<PersonalDesignDeleteResponse> {
    return request<PersonalDesignDeleteResponse>("DELETE", "/api/design-studio/personal", { body });
  },

  designStudioAppliedGet(): Promise<PersonalDesignResponse> {
    return request<PersonalDesignResponse>("GET", "/api/design-studio/applied-local");
  },

  designStudioApplyLocal(body: AppliedDesignSaveBody): Promise<PersonalDesignResponse> {
    return request<PersonalDesignResponse>("POST", "/api/design-studio/apply-local", { body });
  },

  designStudioResetLocal(): Promise<PersonalDesignDeleteResponse> {
    return request<PersonalDesignDeleteResponse>("DELETE", "/api/design-studio/apply-local");
  },

  listProjects(): Promise<ProjectSummary[]> {
    return apiGet<ProjectSummary[]>("/api/projects");
  },

  discoverProjects(candidate: string): Promise<{ projects: DiscoveredProject[] }> {
    return request<{ projects: DiscoveredProject[] }>("POST", "/api/projects/discover", {
      body: { candidate },
    });
  },

  registerProject(root: string, eda: "kicad" | "altium"): Promise<ProjectSummary> {
    return request<ProjectSummary>("POST", "/api/projects", { body: { root, eda } });
  },

  projectWorkspace(projectId: string): Promise<ProjectWorkspace> {
    return apiGet<ProjectWorkspace>(`/api/projects/${encodeURIComponent(projectId)}/workspace`);
  },

  projectPlacementGeometry(projectId: string): Promise<ProjectPlacementGeometry> {
    return apiGet<ProjectPlacementGeometry>(
      `/api/projects/${encodeURIComponent(projectId)}/board-geometry`,
    );
  },

  projectVisuals(projectId: string, refresh = false): Promise<ProjectVisualBundle> {
    return apiGet<ProjectVisualBundle>(
      `/api/projects/${encodeURIComponent(projectId)}/visuals`,
      refresh ? { refresh: "true" } : undefined,
    );
  },

  projectVisualArtifact(projectId: string, artifactId: string): Promise<Blob> {
    return fetchPreviewBlob(
      `/api/projects/${encodeURIComponent(projectId)}/visuals/${encodeURIComponent(artifactId)}`,
      "image/*",
    );
  },

  liveProjectBom(projectId: string, boards = 1): Promise<ProjectBom> {
    return apiGet<ProjectBom>(`/api/projects/${encodeURIComponent(projectId)}/bom/live`, {
      boards: String(boards),
    });
  },

  liveProjectBomExport(projectId: string, boards = 1): Promise<DownloadedFile> {
    return fetchDownload(`/api/projects/${encodeURIComponent(projectId)}/bom/live/export`, {
      boards: String(boards),
      kind: "csv",
    });
  },

  projectAssignments(projectId: string): Promise<ProjectAssignments> {
    return apiGet<ProjectAssignments>(`/api/projects/${encodeURIComponent(projectId)}/assign`);
  },

  assignProjectGroup(
    projectId: string,
    refs: string[],
    partId: string,
  ): Promise<{
    project: string;
    refs: string[];
    part_id: string;
    bound: number;
    committed: string | null;
  }> {
    return request("POST", `/api/projects/${encodeURIComponent(projectId)}/assign`, {
      body: { refs, part_id: partId },
    });
  },

  projectCollaboration(projectId: string): Promise<ProjectCollaboration> {
    return apiGet<ProjectCollaboration>(
      `/api/projects/${encodeURIComponent(projectId)}/collaboration`,
    );
  },

  openProjectDocument(
    projectId: string,
    documentId: string,
  ): Promise<OpenProjectDocumentResult> {
    return request<OpenProjectDocumentResult>(
      "POST",
      `/api/projects/${encodeURIComponent(projectId)}/documents/${encodeURIComponent(documentId)}/open`,
    );
  },

  connectProjectRemote(
    projectId: string,
    url: string,
  ): Promise<ConnectProjectRemoteResult> {
    return request<ConnectProjectRemoteResult>(
      "POST",
      `/api/projects/${encodeURIComponent(projectId)}/collaboration/remote`,
      { body: { url } },
    );
  },

  startWorkSession(
    projectId: string,
    body: { owner: string; branch: string; documents: string[] },
  ): Promise<ProjectCollaboration> {
    return request<ProjectCollaboration>(
      "POST",
      `/api/projects/${encodeURIComponent(projectId)}/work-sessions`,
      { body },
    );
  },

  shareWorkSession(
    projectId: string,
    sessionId: string,
    message: string,
  ): Promise<ProjectCollaboration> {
    return request<ProjectCollaboration>(
      "POST",
      `/api/projects/${encodeURIComponent(projectId)}/work-sessions/${encodeURIComponent(sessionId)}/share`,
      { body: { message } },
    );
  },

  resumeWorkSession(projectId: string, sessionId: string): Promise<ProjectCollaboration> {
    return request<ProjectCollaboration>(
      "POST",
      `/api/projects/${encodeURIComponent(projectId)}/work-sessions/${encodeURIComponent(sessionId)}/resume`,
    );
  },

  finishWorkSession(projectId: string, sessionId: string): Promise<FinishWorkSessionResult> {
    return request<FinishWorkSessionResult>(
      "POST",
      `/api/projects/${encodeURIComponent(projectId)}/work-sessions/${encodeURIComponent(sessionId)}/finish`,
    );
  },

  projectReviews(projectId: string): Promise<ProjectReviews> {
    return apiGet<ProjectReviews>(`/api/projects/${encodeURIComponent(projectId)}/reviews`);
  },

  projectReviewEvidence(
    projectId: string,
    candidate: Pick<ProjectReviewCandidate, "branch" | "commit" | "base_branch" | "base_commit">,
  ): Promise<ProjectReviewEvidence> {
    return request<ProjectReviewEvidence>(
      "POST",
      `/api/projects/${encodeURIComponent(projectId)}/reviews/evidence`,
      { body: candidate },
    );
  },

  validateProjectReview(
    projectId: string,
    candidate: Pick<ProjectReviewCandidate, "branch" | "commit" | "base_branch" | "base_commit">,
  ): Promise<ProjectNativeValidation> {
    return request<ProjectNativeValidation>(
      "POST",
      `/api/projects/${encodeURIComponent(projectId)}/reviews/validate`,
      { body: candidate },
    );
  },

  approveProjectReview(
    projectId: string,
    candidate: Pick<ProjectReviewCandidate, "branch" | "commit" | "base_branch" | "base_commit">,
  ): Promise<ApproveProjectReviewResult> {
    return request<ApproveProjectReviewResult>(
      "POST",
      `/api/projects/${encodeURIComponent(projectId)}/reviews/approve`,
      { body: candidate },
    );
  },

  requestProjectChanges(
    projectId: string,
    decision: Pick<ProjectReviewCandidate, "branch" | "commit" | "base_branch" | "base_commit"> & {
      reviewer: string;
      message: string;
    },
  ): Promise<RequestProjectChangesResult> {
    return request<RequestProjectChangesResult>(
      "POST",
      `/api/projects/${encodeURIComponent(projectId)}/reviews/request-changes`,
      { body: decision },
    );
  },

  activeAssembly(projectId: string): Promise<AssemblyRun | null> {
    return apiGet<AssemblyRun | null>(
      `/api/projects/${encodeURIComponent(projectId)}/assemblies/active`,
    );
  },

  startAssembly(projectId: string, operator: string, boards: number): Promise<AssemblyRun> {
    return request<AssemblyRun>(
      "POST",
      `/api/projects/${encodeURIComponent(projectId)}/assemblies`,
      { body: { operator, boards } },
    );
  },

  recordAssemblyEvent(
    projectId: string,
    runId: string,
    body: {
      placement_id: string;
      state: "done" | "skipped" | "reworked" | "issue";
      scanned_mpn?: string;
      note?: string;
    },
  ): Promise<AssemblyRun> {
    return request<AssemblyRun>(
      "POST",
      `/api/projects/${encodeURIComponent(projectId)}/assemblies/${encodeURIComponent(runId)}/events`,
      { body },
    );
  },

  completeAssembly(projectId: string, runId: string): Promise<AssemblyRun> {
    return request<AssemblyRun>(
      "POST",
      `/api/projects/${encodeURIComponent(projectId)}/assemblies/${encodeURIComponent(runId)}/complete`,
    );
  },

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

  // Dev mode (owner-only): persist the nudged design tokens + reworded copy to source so a
  // saved change ships for everyone. Honest error when there is no source tree (a frozen exe).
  devSave(body: DevSaveBody): Promise<DevSaveResult> {
    return request<DevSaveResult>("POST", "/api/dev/save", { body });
  },

  devStatus(): Promise<DevWorkspaceStatus> {
    return request<DevWorkspaceStatus>("GET", "/api/dev/status");
  },

  devPublish(message: string): Promise<DevPublishResult> {
    return request<DevPublishResult>("POST", "/api/dev/publish", { body: { message } });
  },

  devPromote(body: DevPromoteBody): Promise<DevPromoteResult> {
    return request<DevPromoteResult>("POST", "/api/dev/promote", { body });
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

  // The component dossier: the normalized opened-component projection. The raw record above
  // stays available for diagnostics; every presentation surface reads this instead, so no
  // component has to decide for itself where a datum belongs, which specification group it is
  // in for THIS kind of part, or which provider shape it arrived in.
  partDossier(id: string): Promise<ComponentDossier> {
    return apiGet<ComponentDossier>(`/api/library/parts/${encodeURIComponent(id)}/dossier`);
  },

  // --- specification writes -------------------------------------------------
  //
  // Every one of these answers with the FULL updated dossier. The caller replaces its state
  // wholesale rather than merging a fragment: an override changes the value, its verification
  // state, the conflict state, the group counts, the completeness score and the revision
  // history at once, and a partial merge would leave four of those six stale.

  /** Record a reviewed override for one specification. Wins over every source. */
  setSpecificationOverride(
    id: string,
    key: string,
    value: string,
    // Why the reviewer decided this, and whether they stand behind it as checked. Both are
    // properties OF the decision, so they travel with the value rather than in a second write
    // that could succeed while the first one failed.
    review: { note?: string; verified?: boolean } = {},
  ): Promise<ComponentDossier> {
    return request<ComponentDossier>(
      "PUT",
      `/api/library/parts/${encodeURIComponent(id)}/specifications/` +
        `${encodeURIComponent(key)}/override`,
      { body: { value, note: review.note ?? "", verified: review.verified ?? true } },
    );
  },

  /** Withdraw a reviewed override, so the sources decide the value again. */
  clearSpecificationOverride(id: string, key: string): Promise<ComponentDossier> {
    return request<ComponentDossier>(
      "DELETE",
      `/api/library/parts/${encodeURIComponent(id)}/specifications/` +
        `${encodeURIComponent(key)}/override`,
    );
  },

  /** Prefer one source's answer for one specification, without inventing a new value. */
  setSpecificationPreferredSource(
    id: string,
    key: string,
    sourceId: string,
  ): Promise<ComponentDossier> {
    return request<ComponentDossier>(
      "PUT",
      `/api/library/parts/${encodeURIComponent(id)}/specifications/` +
        `${encodeURIComponent(key)}/preferred-source`,
      { body: { sourceId } },
    );
  },

  /** Go back to the precedence order's own answer for one specification. */
  clearSpecificationPreferredSource(id: string, key: string): Promise<ComponentDossier> {
    return request<ComponentDossier>(
      "DELETE",
      `/api/library/parts/${encodeURIComponent(id)}/specifications/` +
        `${encodeURIComponent(key)}/preferred-source`,
    );
  },

  /**
   * Prefer one provider for this component's whole CAD set.
   *
   * Refused (422) when that provider does not supply all three artifacts. Stockroom takes a
   * component's CAD from one provider's coherent download, so a set source that cannot answer
   * for one of the three is a preference nothing could honour.
   */
  setCadPreferredSource(id: string, provider: string): Promise<ComponentDossier> {
    return request<ComponentDossier>(
      "PUT",
      `/api/library/parts/${encodeURIComponent(id)}/cad/preferred-source`,
      { body: { provider } },
    );
  },

  clearCadPreferredSource(id: string): Promise<ComponentDossier> {
    return request<ComponentDossier>(
      "DELETE",
      `/api/library/parts/${encodeURIComponent(id)}/cad/preferred-source`,
    );
  },

  /** Prefer one provider for ONE asset. Refused (422) when it would mix two across the set. */
  setCadAssetPreferredSource(
    id: string,
    asset: string,
    provider: string,
  ): Promise<ComponentDossier> {
    return request<ComponentDossier>(
      "PUT",
      `/api/library/parts/${encodeURIComponent(id)}/cad/` +
        `${encodeURIComponent(asset)}/preferred-source`,
      { body: { provider } },
    );
  },

  clearCadAssetPreferredSource(id: string, asset: string): Promise<ComponentDossier> {
    return request<ComponentDossier>(
      "DELETE",
      `/api/library/parts/${encodeURIComponent(id)}/cad/` +
        `${encodeURIComponent(asset)}/preferred-source`,
    );
  },

  /**
   * The bytes of one stored document.
   *
   * Fetched as a Blob with the bearer rather than pointed at with a plain URL, because the
   * guard rejects an unauthenticated request and a viewer handed a 401 would show an empty
   * grey pane instead of saying what failed.
   */
  documentFile(id: string, documentId: string): Promise<Blob> {
    return fetchPreviewBlob(
      `/api/library/parts/${encodeURIComponent(id)}/documents/` +
        `${encodeURIComponent(documentId)}/file`,
      "application/pdf",
    );
  },

  // Which provider can supply everything for this component, and how to reach each one. The same
  // document also arrives inside the workspace projection above, so a surface that already holds
  // the workspace reads it from there; this exists for a caller that wants only the coverage.
  partProviders(id: string): Promise<ComponentProvidersView> {
    return apiGet<ComponentProvidersView>(
      `/api/library/parts/${encodeURIComponent(id)}/providers`,
    );
  },

  // Record what a PERSON knows about one provider's coverage of this component, and read the
  // recomputed coverage back. The status vocabulary is deliberately narrower than the coverage
  // vocabulary: "downloaded" and "validated" are claims about bytes Stockroom is holding, so the
  // backend rejects them with a 422 rather than letting a surface offer them. An empty status
  // withdraws a previous claim.
  setPartProviderCoverage(
    id: string,
    body: {
      provider: string;
      artifact: CoverageArtifact;
      status: "available" | "not_available" | "";
      note?: string;
    },
  ): Promise<ComponentProvidersView> {
    return request<ComponentProvidersView>(
      "POST",
      `/api/library/parts/${encodeURIComponent(id)}/providers`,
      {
        body: {
          provider: body.provider,
          artifact: body.artifact,
          status: body.status,
          note: body.note ?? "",
        },
      },
    );
  },

  // The part's git timeline (M6k): commits that touched its canonical JSON, newest
  // first. An uncommitted part honestly reports an empty list.
  partHistory(id: string): Promise<HistoryResponse> {
    return apiGet<HistoryResponse>(`/api/library/parts/${encodeURIComponent(id)}/history`);
  },

  // A structured field-diff of the part JSON between two revs (M6k). `a` may be ""
  // (the earliest side, the part did not exist) and is dropped from the query by the
  // param serializer, so the backend applies its "" default and every field reads as
  // added. Both revs must lie in this part's own history or the backend returns 400.
  partDiff(id: string, a: string, b: string): Promise<DiffResponse> {
    return apiGet<DiffResponse>(`/api/library/parts/${encodeURIComponent(id)}/diff`, { a, b });
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

  /** The footprint's pads + the 3D model's placement, for the viewer's board mode. Both travel in
   *  ONE response so the body and the land pattern it must line up with cannot disagree. */
  landPattern(id: string): Promise<LandPattern> {
    return apiGet<LandPattern>(`/api/previews/land/${encodeURIComponent(id)}.json`);
  },

  /** The symbol's pins and body geometry, so the preview can answer questions about the FILE. */
  symbolGeometry(id: string): Promise<SymbolGeometry> {
    return apiGet<SymbolGeometry>(`/api/previews/symbol/${encodeURIComponent(id)}.json`);
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

  // The pulled product photo (specs["Image"]) through the backend proxy - the <img>
  // fallback lane when the vendor CDN refuses the direct hotlink. Needs the bearer, so
  // it comes back as a Blob (object-URL'd by the viewer). 400 = refused URL, 404 = the
  // fetch yielded no real image; both surface as ApiError and the photo simply hides.
  productImage(url: string): Promise<Blob> {
    return fetchPreviewBlob(`/api/enrich/image?url=${encodeURIComponent(url)}`, "image/*");
  },

  // Edit one field (mirrored to the KiCad symbol where the field maps to a symbol
  // property; `tags` takes an array). Category is NOT edited here, it moves.
  editField(id: string, field: string, value: unknown): Promise<PartDetail> {
    return request<PartDetail>("PATCH", `/api/library/parts/${encodeURIComponent(id)}`, {
      body: { field, value },
    });
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
    return request<PartDetail>("POST", `/api/library/parts/${encodeURIComponent(id)}/specs`, {
      body: { specs, overwrite },
    });
  },

  moveCategory(id: string, category: string): Promise<PartDetail> {
    return request<PartDetail>("POST", `/api/library/parts/${encodeURIComponent(id)}/move`, {
      body: { category },
    });
  },

  deletePart(id: string): Promise<void> {
    return request<void>("DELETE", `/api/library/parts/${encodeURIComponent(id)}`);
  },

  restoreDeletedPart(id: string): Promise<PartDetail> {
    return request<PartDetail>("POST", `/api/library/parts/${encodeURIComponent(id)}/undo-delete`);
  },

  // Remove ONE element from a part: "datasheet", or a `<tool>_<asset kind>` pair from the
  // EDA registry (kicad_symbol, kicad_footprint, kicad_model, altium_symbol,
  // altium_footprint). The file goes, the ref nulls, one scoped commit.
  detachAsset(id: string, kind: string): Promise<PartDetail> {
    return request<PartDetail>(
      "DELETE",
      `/api/library/parts/${encodeURIComponent(id)}/assets/${encodeURIComponent(kind)}`,
    );
  },

  // Refresh one part's volatile procurement data (price/stock/lifecycle/lead/dist P/N)
  // from the distributor APIs. A write-lane job: the record commits server-side and the
  // job's terminal SSE result carries the updated record.
  refreshSourcing(id: string): Promise<JobRef> {
    return request<JobRef>("POST", `/api/library/parts/${encodeURIComponent(id)}/refresh`);
  },

  // Look up a part by its MPN through the enrichment pipeline (scrape-first, spec
  // section 6.1). Returns the sourced candidate fields; the caller applies the ones
  // it wants through editField. A scrape miss returns null fields, never an error,
  // so completeness is never blocked by a dead source.
  enrichPart(mpn: string, category?: string, want?: string[]): Promise<JobRef> {
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

  // Add a staging candidate to the library. On success returns the new record; on
  // the complete-to-add gate failure it throws ApiError (422) with `missing` set.
  ingestCommit(candidate: StagingCandidate): Promise<PartDetail> {
    return request<PartDetail>("POST", "/api/ingest/commit", { body: candidate });
  },

  // Resolve an existing part's DigiKey CAD-download source from its MPN (Phase-2 asset
  // download, spec section 5). A resolvable 200 either way; `url` is null when the part
  // has no MPN, DigiKey is disabled, or nothing resolved - never an error.
  partCadSource(id: string): Promise<CadSourceResponse> {
    return apiGet<CadSourceResponse>(`/api/library/parts/${encodeURIComponent(id)}/cad-source`);
  },

  // Open a job's Server-Sent Events stream. Native EventSource cannot send the
  // bearer token, so this reads the stream through fetch (see lib/sse) and returns
  // the raw body for streamEvents to parse.
  async openJobStream(jobId: string): Promise<ReadableStream<Uint8Array>> {
    const descriptor: ApiRequestDescriptor = {
      method: "GET",
      path: `/api/jobs/${encodeURIComponent(jobId)}/events`,
      params: {},
      body: undefined,
    };
    return dispatchApiRequest(descriptor, async () => {
      const token = apiToken();
      const headers: Record<string, string> = { Accept: "text/event-stream" };
      if (token) headers.Authorization = `Bearer ${token}`;
      const res = await fetch(apiBase() + `/api/jobs/${encodeURIComponent(jobId)}/events`, {
        headers,
      });
      if (!res.ok || !res.body) {
        throw new ApiError(res.status || 0, `Job stream failed (${res.status})`);
      }
      return res.body;
    });
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

  // Versioned, non-secret renderer continuity. The backend validates these
  // documents strictly and persists them outside the library repository; the
  // loose `unknown` boundary here is intentional so the validator in
  // lib/uiSession.ts remains the one frontend authority for the wire shape.
  getUiSession(): Promise<unknown> {
    return apiGet<unknown>("/api/ui-session");
  },

  putUiSession(snapshot: unknown): Promise<unknown> {
    return request<unknown>("PUT", "/api/ui-session", { body: snapshot });
  },

  createIntakeDraft(draft: unknown): Promise<unknown> {
    return request<unknown>("POST", "/api/intake-drafts", { body: draft });
  },

  getIntakeDraft(draftId: string, revision?: number): Promise<unknown> {
    const suffix = revision === undefined ? "" : `?revision=${encodeURIComponent(String(revision))}`;
    return apiGet<unknown>(`/api/intake-drafts/${encodeURIComponent(draftId)}${suffix}`);
  },

  updateIntakeDraft(draftId: string, draft: unknown): Promise<unknown> {
    return request<unknown>("PUT", `/api/intake-drafts/${encodeURIComponent(draftId)}`, {
      body: draft,
    });
  },

  deleteIntakeDraft(draftId: string): Promise<void> {
    return request<void>("DELETE", `/api/intake-drafts/${encodeURIComponent(draftId)}`);
  },

  // Dev convenience (the hidden Settings combo): load any API keys / logins from the per-machine
  // dev-creds.json (in the OS config dir, never the public repo) into the config. Returns the
  // redacted settings plus `loaded`, the field names that were applied.
  loadDevCreds(): Promise<SettingsInfo & { loaded: string[]; config_path: string }> {
    return request<SettingsInfo & { loaded: string[]; config_path: string }>(
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
    return request<ActivateResponse>("POST", `/api/profiles/${encodeURIComponent(name)}/activate`);
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

  connectLibraryRemote(url: string): Promise<{ configured: boolean; remote: string }> {
    return request<{ configured: boolean; remote: string }>("POST", "/api/sync/remote", {
      body: { url },
    });
  },

  startGitHubLogin(): Promise<JobRef> {
    return request<JobRef>("POST", "/api/sync/github/login");
  },

  startDigiKeyQuantityPricing(
    productNumber: string,
    quantity: number,
    prepareOrder = false,
  ): Promise<JobRef> {
    return request<JobRef>("POST", "/api/enrich/digikey/quantity-pricing", {
      body: {
        product_number: productNumber,
        quantity,
        prepare_order: prepareOrder,
      },
    });
  },

  getOnboarding(): Promise<OnboardingStatus> {
    return apiGet<OnboardingStatus>("/api/onboarding");
  },

  setLibrary(body: SetLibraryBody): Promise<OnboardingStatus> {
    return request<OnboardingStatus>("POST", "/api/onboarding/library", { body });
  },

  startOnboardingGitHubLogin(): Promise<JobRef> {
    return request<JobRef>("POST", "/api/onboarding/github/login");
  },

  getOnboardingGitHubRepositories(owner: string): Promise<GitHubRepositoriesResponse> {
    return apiGet<GitHubRepositoriesResponse>(
      `/api/onboarding/github/repositories/${encodeURIComponent(owner)}`,
    );
  },

  setGuidedRepository(body: GuidedRepositoryBody): Promise<OnboardingStatus> {
    return request<OnboardingStatus>("POST", "/api/onboarding/repository", { body });
  },

  connectGuidedTool(): Promise<JobRef> {
    return request<JobRef>("POST", "/api/onboarding/tool/connect");
  },

  saveGuidedSourceData(body: GuidedSourceDataBody): Promise<OnboardingStatus> {
    return request<OnboardingStatus>("POST", "/api/onboarding/source-data", { body });
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

  // Where the LIBRARY's binary payloads are stored (git-lfs). Read-only, no network.
  getLibraryLfs(): Promise<LibraryLfsStatus> {
    return apiGet<LibraryLfsStatus>("/api/library/lfs");
  },

  // Route the library's binary payloads through git-lfs, as one hygiene commit.
  adoptLibraryLfs(): Promise<LibraryLfsResult> {
    return request<LibraryLfsResult>("POST", "/api/library/lfs");
  },

  // What syncing the LIBRARY repo's workspace hygiene would change (the union of every tool's
  // rules, because the library holds assets for all of them and is what a peer clones).
  getLibraryHygiene(): Promise<HygieneRead> {
    return apiGet<HygieneRead>("/api/library/hygiene");
  },

  syncLibraryHygiene(): Promise<HygieneResult> {
    return request<HygieneResult>("POST", "/api/library/hygiene");
  },

  // The Altium Database Library status for the active profile: place-ready count + per-part rows.
  altiumStatus(): Promise<AltiumStatus> {
    return apiGet<AltiumStatus>("/api/altium/status");
  },

  // Whether the 64-bit SQLite3 ODBC driver Altium needs to read the DbLib is registered on this
  // machine (null off Windows), plus where to download it. Machine-level, not profile-scoped.
  altiumOdbcStatus(): Promise<OdbcStatus> {
    return apiGet<OdbcStatus>("/api/altium/odbc-status");
  },

  // Whether a 3D embed can run on this machine (Altium installed, license seat free), and the
  // registry's reason when it cannot. Machine-level, not profile-scoped.
  altiumEmbedCapability(): Promise<AltiumEmbedCapability> {
    return apiGet<AltiumEmbedCapability>("/api/altium/embed-capability");
  },

  // Embed the part's 3D model into its Altium footprint's .PcbLib by driving the installed Altium.
  // Synchronous and slow by nature (Altium boots), one atomic commit, and the result is verified by
  // reading the container back from outside Altium.
  altiumEmbedModel(partId: string, replace = false): Promise<AltiumEmbedResult> {
    return request<AltiumEmbedResult>(
      "POST",
      `/api/altium/parts/${encodeURIComponent(partId)}/embed-model`,
      { body: { replace } },
    );
  },

  // Embed the 3D model of every part that still needs one. A JOB, not a plain call: each part that
  // genuinely needs work costs an Altium boot, so a full library can run for minutes, and the
  // stream names the part it is on. Parts already carrying a model are never attempted.
  altiumEmbedModels(partIds?: string[]): Promise<{ job_id: string }> {
    return request<{ job_id: string }>("POST", "/api/altium/embed-models", {
      body: partIds ? { part_ids: partIds } : {},
    });
  },

  // Import a pasted list of part numbers (or a BOM CSV) into the library. A JOB: 169 parts is
  // minutes of network work, and the stream names the part it is on. `dryRun` reports what WOULD
  // land and writes nothing, so an import into a git-backed library is previewable first.
  bulkImport(input: {
    text?: string;
    partNumbers?: string[];
    format?: "list" | "csv";
    dryRun?: boolean;
    category?: string;
  }): Promise<{ job_id: string }> {
    return request<{ job_id: string }>("POST", "/api/enrich/bulk-import", {
      body: {
        text: input.text,
        part_numbers: input.partNumbers,
        format: input.format,
        dry_run: input.dryRun,
        category: input.category,
      },
    });
  },

  // "Is my library complete?" Counted from the records on disk, network-free.
  libraryCoverage(): Promise<LibraryCoverage> {
    return apiGet<LibraryCoverage>("/api/library/completion");
  },

  // Give every part the files it still needs. A JOB, and a long one: at the measured catalogue
  // pace a 10,000-part library is around 21 hours, which is exactly why it is stoppable and why
  // resuming is free (the worklist is derived from the library, never bookkept).
  runCompletion(
    input: { partIds?: string[]; limit?: number; idempotencyKey?: string } = {},
  ): Promise<CompletionRunRef> {
    return request<CompletionRunRef>("POST", "/api/library/completion/run", {
      body: {
        part_ids: input.partIds,
        limit: input.limit,
        idempotency_key: input.idempotencyKey,
      },
    });
  },

  workflowBatch(batchId: string, afterOrdinal = -1, limit = 100): Promise<WorkflowBatchSnapshot> {
    return apiGet<WorkflowBatchSnapshot>(`/api/workflows/batches/${encodeURIComponent(batchId)}`, {
      after_ordinal: String(afterOrdinal),
      limit: String(limit),
    });
  },

  workflowEvents(batchId: string, afterSequence: number, limit = 200): Promise<WorkflowEventsPage> {
    return apiGet<WorkflowEventsPage>(
      `/api/workflows/batches/${encodeURIComponent(batchId)}/events`,
      {
        after_sequence: String(afterSequence),
        limit: String(limit),
      },
    );
  },

  workflowPause(batchId: string): Promise<WorkflowControlResult> {
    return request<WorkflowControlResult>(
      "POST",
      `/api/workflows/batches/${encodeURIComponent(batchId)}/pause`,
    );
  },

  workflowResume(batchId: string): Promise<WorkflowControlResult> {
    return request<WorkflowControlResult>(
      "POST",
      `/api/workflows/batches/${encodeURIComponent(batchId)}/resume`,
    );
  },

  workflowRetry(batchId: string): Promise<WorkflowControlResult> {
    return request<WorkflowControlResult>(
      "POST",
      `/api/workflows/batches/${encodeURIComponent(batchId)}/retry`,
    );
  },

  workflowCancel(batchId: string): Promise<WorkflowControlResult> {
    return request<WorkflowControlResult>(
      "POST",
      `/api/workflows/batches/${encodeURIComponent(batchId)}/cancel`,
    );
  },

  // ONE ACQUISITION WORKFLOW. An explicitly selected provider uses `collect-all`: this is not a
  // second capture lane, but the durable instruction that the person's Open Provider action must
  // not be bypassed merely because retained evidence already exists.
  //
  // `partIds: [one]` is per-component; omitting it captures every part still missing files. Both
  // are the same backend path deliberately, so verifying one verifies the other.
  //
  // The native shell and browser development build share this API-owned route. Provider sessions
  // and task-bound downloads remain backend-owned.
  runCapture(
    input: {
      partIds?: string[];
      vendor?: string;
      mode?: "collect-all";
      limit?: number;
      background?: boolean;
      edas?: string[];
      idempotencyKey?: string;
    } = {},
  ): Promise<CompletionRunRef> {
    return request<CompletionRunRef>("POST", "/api/library/capture/run", {
      body: {
        part_ids: input.partIds,
        vendor: input.vendor,
        mode: input.mode,
        limit: input.limit,
        background: input.background,
        edas: input.edas,
        idempotency_key: input.idempotencyKey,
      },
    });
  },

  signalCaptureIntent(input: {
    partId: string;
    workflowItemId: string;
    action: "finish-route" | "skip-part";
    routeToken?: string;
  }): Promise<{
    part_id: string;
    workflow_item_id: string;
    action: "finish-route" | "skip-part";
    accepted: boolean;
  }> {
    return request("POST", `/api/library/capture/parts/${encodeURIComponent(input.partId)}/intent`, {
      body: {
        action: input.action,
        workflow_item_id: input.workflowItemId,
        ...(input.routeToken ? { route_token: input.routeToken } : {}),
      },
    });
  },

  applyCaptureAttachments(input: {
    partId: string;
    workflowItemId: string;
    proposalToken: string;
  }): Promise<{
    part_id: string;
    workflow_item_id: string;
    proposal_token: string;
    accepted: boolean;
  }> {
    return request("POST", `/api/library/capture/parts/${encodeURIComponent(input.partId)}/attachments/apply`, {
      body: {
        workflow_item_id: input.workflowItemId,
        proposal_token: input.proposalToken,
      },
    });
  },

  attachSelectedCaptureFiles(input: {
    partId: string;
    workflowItemId: string;
    paths: string[];
    vendor: string;
    detailUrl: string;
    routeToken: string;
  }): Promise<{
    part_id: string;
    workflow_item_id: string;
    accepted: boolean;
    queued_files: number;
  }> {
    return request("POST", `/api/library/capture/parts/${encodeURIComponent(input.partId)}/selected-files`, {
      body: {
        paths: input.paths,
        workflow_item_id: input.workflowItemId,
        vendor: input.vendor,
        detail_url: input.detailUrl,
        route_token: input.routeToken,
      },
    });
  },

  addPartFiles(input: { partId: string; paths: string[] }): Promise<{
    part_id: string;
    selected_files: number;
    attached: string[];
    ignored: string[];
    remaining: string[];
    complete: boolean;
  }> {
    return request("POST", `/api/library/parts/${encodeURIComponent(input.partId)}/files`, {
      body: { paths: input.paths },
    });
  },

  // What Manage may offer for this component: whether this host owns a native window at all,
  // whether the component has a directory to reveal, which formats it really has files for, and
  // which EDA applications this machine really carries. One request, because all three items are
  // decided by the same facts and an item with nothing behind it is not drawn.
  partShell(id: string): Promise<PartShell> {
    return apiGet<PartShell>(`/api/library/parts/${encodeURIComponent(id)}/shell`);
  },

  // Reveal takes NO path. The backend resolves the component's directory from the active library
  // root; a reveal endpoint that accepted a path would be a way to start the file browser on
  // anything the browser process chose to name.
  revealPartFiles(id: string): Promise<{ part_id: string; revealed: boolean }> {
    return request("POST", `/api/library/parts/${encodeURIComponent(id)}/reveal`);
  },

  exportPart(input: { partId: string; format: string }): Promise<{
    part_id: string;
    format: string;
    file_count: number;
    file_names: string[];
  }> {
    return request("POST", `/api/library/parts/${encodeURIComponent(input.partId)}/export`, {
      body: { format: input.format },
    });
  },

  openPartIn(input: { partId: string; applicationId: string; format: string }): Promise<{
    part_id: string;
    application_id: string;
    format: string;
    opened: boolean;
  }> {
    return request("POST", `/api/library/parts/${encodeURIComponent(input.partId)}/open-in`, {
      body: { application_id: input.applicationId, format: input.format },
    });
  },

  captureWorkflow(batchId: string): Promise<CaptureWorkflowSession> {
    return apiGet<CaptureWorkflowSession>(
      `/api/library/capture/batches/${encodeURIComponent(batchId)}`,
    );
  },

  showCaptureProvider(batchId: string): Promise<{
    workflow_batch_id: string;
    part_id: string;
    visible: boolean;
  }> {
    return request(
      "POST",
      `/api/library/capture/batches/${encodeURIComponent(batchId)}/provider/show`,
    );
  },

  // What one library-wide run finished on its own, and what it could not finish without a
  // person. Read-only: the backend projects the per-part reports the run already retained, so
  // asking again costs nothing and never re-runs a provider.
  captureWorklist(batchId: string): Promise<CaptureBatchWorklist> {
    return apiGet<CaptureBatchWorklist>(
      `/api/library/capture/batches/${encodeURIComponent(batchId)}/worklist`,
    );
  },

  // The providers a capture can open for a person, read off the adapter registry so a surface can
  // never offer one with no implementation behind it.
  captureVendors(): Promise<{
    vendors: {
      key: string;
      label: string;
      tools: string[];
      needs_login: boolean;
      aggregator: boolean;
      instruction: string;
    }[];
  }> {
    return apiGet("/api/library/capture/vendors");
  },

  // What CAD this library holds. Read-only: it runs the real walk with `dry_run`, so the number
  // the surface states before offering the action is the number the action will act on.
  cadInventory(): Promise<CadInventory> {
    return apiGet<CadInventory>("/api/library/cad");
  },

  // Remove every CAD asset this library holds. A JOB, and DESTRUCTIVE, so `dryRun` defaults to
  // true on the backend too: the write has to be asked for explicitly at both ends.
  clearCad(input: { dryRun?: boolean } = {}): Promise<{ job_id: string }> {
    return request<{ job_id: string }>("POST", "/api/library/cad/clear", {
      body: { dry_run: input.dryRun ?? true },
    });
  },

  // Which derivation ruleset produced what the library is currently showing. Read-only and
  // network-free: one grouped query over the index's `derived_by` column.
  libraryDerivation(): Promise<LibraryDerivation> {
    return apiGet<LibraryDerivation>("/api/library/derivation");
  },

  // Recompute every part's presentation data from its stored raw payloads. A JOB, and a WRITE:
  // it lands as one atomic commit. Credential-free by construction, so it works on a machine
  // that has never been given distributor keys.
  rebuildDerivation(input: { dryRun?: boolean } = {}): Promise<{ job_id: string }> {
    return request<{ job_id: string }>("POST", "/api/library/derivation/rebuild", {
      body: { dry_run: input.dryRun ?? false },
    });
  },

  // Ask a running job to stop at its next safe point. Cooperative: for a completion run that is
  // between two parts, never inside one, so the library is left exactly as a finished run would.
  stopJob(jobId: string): Promise<{ job_id: string; stopping: boolean }> {
    return request<{ job_id: string; stopping: boolean }>(
      "POST",
      `/api/jobs/${encodeURIComponent(jobId)}/stop`,
    );
  },

  // How many parts a bulk embed would actually work on, so the action can state a number it will
  // honour rather than one it might not.
  altiumModelsPending(): Promise<AltiumModelsPending> {
    return request<AltiumModelsPending>("GET", "/api/altium/models-pending");
  },

  // Regenerate the DbLib + its data source over every place-ready part (synchronous, one commit).
  altiumRegenerate(): Promise<AltiumRegenerateResult> {
    return request<AltiumRegenerateResult>("POST", "/api/altium/regenerate");
  },

  // Explicitly install and verify the active DbLib. This is the only ordinary application action
  // that may launch Altium for library setup; host startup and passive reads never call it.
  altiumSetup(): Promise<AltiumSetupResult> {
    return request<AltiumSetupResult>("POST", "/api/altium/setup");
  },

  // --- STM Viewer (Phase 3 contract, section 4). Every read raises ApiError(409, "STM index
  // not built") when the index is absent; the caller branches on .status === 409 to show the
  // Build the index call to action instead of a raw error. ---

  // The build/source/stamp state of the derived STM index (drives the 409 build gate + status).
  getStmStatus(): Promise<StmStatusDTO> {
    return apiGet<StmStatusDTO>("/api/stm/status");
  },

  // The families + their lines/packages/counts, for the FamilyPicker scope control.
  getStmFamilies(): Promise<FamiliesResponse> {
    return apiGet<FamiliesResponse>("/api/stm/families");
  },

  // The MCU spec matrix. Only the provided scope fields narrow server-side (omitting empty ones,
  // exactly like listParts); every finer facet is a client-side TanStack column filter over the
  // returned rows, so this fires once per coarse scope change, never per facet toggle (decision 3).
  getStmMcus(args: StmMcusArgs = {}): Promise<McusResponse> {
    const params: Record<string, string> = {};
    if (args.q) params.q = args.q;
    if (args.family) params.family = args.family;
    if (args.core) params.core = args.core;
    if (args.package) params.package = args.package;
    if (args.series) params.series = args.series;
    return apiGet<McusResponse>("/api/stm/mcus", params);
  },

  // One part's full pinout (every pin's derived facts inlined). `part` is a ref_name OR a real
  // MPN, passed as a query param so the ref name's parentheses are never path-encoded (section 4).
  getStmPinout(part: string): Promise<PinoutDTO> {
    return apiGet<PinoutDTO>("/api/stm/pinout", { part });
  },

  // Submit the one-time index build as a READ-lane JobRunner job; progress streams over the
  // job's SSE (useJob). A second submit while one is in flight returns the same job id.
  buildStmIndex(): Promise<JobRef> {
    return request<JobRef>("POST", "/api/stm/build");
  },

  // The socket-union of an assembled set + its set-level verdict (COMPAT-01/02/03/05). The body is
  // EITHER an explicit ref list ({ parts }) OR a (family, package) group; both shapes the endpoint
  // accepts (section 4). The result is ephemeral facts, not a stored resource, so nothing is
  // invalidated after it resolves. A 409 raises ApiError(409) the caller routes to the build gate.
  postStmCompatUnion(body: CompatUnionBody): Promise<UnionDTO> {
    return request<UnionDTO>("POST", "/api/stm/compat/union", { body });
  },

  // Compile silicon variation plus an explicit hardware policy into the
  // content-addressed artifact consumed by build documentation and firmware.
  postStmTargetDefinition(body: TargetDefinitionBody): Promise<TargetDefinitionDTO> {
    return request<TargetDefinitionDTO>("POST", "/api/stm/target-definition", { body });
  },

  // Compile the same explicit target set into compact hardware modes, reusable
  // support cells, target cohorts, and safe software-control states.
  postStmSocketSolution(body: TargetDefinitionBody): Promise<SocketSolutionDTO> {
    return request<SocketSolutionDTO>("POST", "/api/stm/socket-solution", { body });
  },

  // One pin's complete AF0-15 set (SWAP-01). `part` is a ref_name OR an MPN, passed as a query
  // param (never path-encoded), same as every other STM read.
  getStmPinAf(part: string, position: string): Promise<PinAfResponse> {
    return apiGet<PinAfResponse>("/api/stm/pin/af", { part, position });
  },

  // Every candidate pin a peripheral signal can be routed to across the part (SWAP-02).
  getStmSignalCandidates(part: string, signal: string): Promise<SignalCandidatesResponse> {
    return apiGet<SignalCandidatesResponse>("/api/stm/signal/candidates", { part, signal });
  },

  // Auto-discovered compatible sets grouped by pin-divergence signature (COMPAT-04), scoped to a
  // (package, families) - `family` accepts one name or a comma-separated multi-family scope
  // (owner amendment 2026-07-23). tolerance defaults to 0 server-side when omitted.
  getStmCompatSuggestions(
    pkg: string,
    family: string,
    tolerance?: number,
  ): Promise<SuggestionsResponse> {
    const params: Record<string, string> = { package: pkg, family };
    if (tolerance != null) params.tolerance = String(tolerance);
    return apiGet<SuggestionsResponse>("/api/stm/compat/suggestions", params);
  },

  // Conflict-check a client-held signal-to-pin assignment for one part (Layer B af_conflicts). A
  // pure read over the assignment; nothing is written or persisted (CONTEXT decision 8).
  postStmAfCheck(body: AfCheckBody): Promise<AfCheckResponse> {
    return request<AfCheckResponse>("POST", "/api/stm/af-check", { body });
  },
};
