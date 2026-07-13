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
  EnrichmentResult,
  Facets,
  JobRef,
  PartDetail,
  PartsResponse,
  ProfilesResponse,
  SettingsInfo,
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
  params?: Record<string, string>;
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
      if (v !== "" && v != null) url.searchParams.set(k, v);
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
    throw new ApiError(0, err instanceof Error ? err.message : "network error");
  }

  if (!res.ok) {
    let msg = `request failed (${res.status})`;
    let missing: string[] | undefined;
    try {
      const body = await res.json();
      msg = body.error || body.detail || body.message || msg;
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

export interface ListPartsArgs {
  q?: string;
  category?: string | null;
  completeOnly?: boolean;
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

  partDetail(id: string): Promise<PartDetail> {
    return apiGet<PartDetail>(`/api/library/parts/${encodeURIComponent(id)}`);
  },

  // Edit one field (mirrored to the KiCad symbol where the field maps to a symbol
  // property; `tags` takes an array). Category is NOT edited here, it moves.
  editField(id: string, field: string, value: unknown): Promise<PartDetail> {
    return request<PartDetail>("PATCH", `/api/library/parts/${encodeURIComponent(id)}`, {
      body: { field, value },
    });
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
  ): Promise<EnrichmentResult> {
    const body: Record<string, unknown> = { mpn };
    if (category) body.category = category;
    if (want && want.length > 0) body.want = want;
    return request<EnrichmentResult>("POST", "/api/enrich/part", { body });
  },

  // Inspect dropped file paths / LCSC ids into staging candidates. Returns a job
  // id; the candidates arrive on the job's SSE result event (openJobStream).
  ingestInspect(paths: string[], lcsc_ids: string[]): Promise<JobRef> {
    return request<JobRef>("POST", "/api/ingest/inspect", {
      body: { paths, lcsc_ids },
    });
  },

  // Add a staging candidate to the library. On success returns the new record; on
  // the complete-to-add gate failure it throws ApiError (422) with `missing` set.
  ingestCommit(candidate: StagingCandidate): Promise<PartDetail> {
    return request<PartDetail>("POST", "/api/ingest/commit", { body: candidate });
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
      throw new ApiError(res.status || 0, `job stream failed (${res.status})`);
    }
    return res.body;
  },

  // Per-machine settings (spec section 11). The GET is redacted (presence + a
  // last-4 hint, never the raw key); the PATCH applies live on the server and
  // persists. Only fields present in the patch are touched.
  getSettings(): Promise<SettingsInfo> {
    return apiGet<SettingsInfo>("/api/settings");
  },

  updateSettings(patch: { mouser_api_key?: string }): Promise<SettingsInfo> {
    return request<SettingsInfo>("PATCH", "/api/settings", { body: patch });
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
};
