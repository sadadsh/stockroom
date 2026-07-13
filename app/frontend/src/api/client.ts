/**
 * A small typed fetch client over the Stockroom API. Sends the per-launch token
 * as a bearer header (the backend also accepts X-Stockroom-Token); both point at
 * the same guard. Every read is served from the warm index so responses are
 * instant even at thousands of parts.
 */
import { apiBase, apiToken } from "../lib/runtime";
import type { Facets, PartDetail, PartsResponse } from "./types";

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

async function apiGet<T>(path: string, params?: Record<string, string>): Promise<T> {
  const url = new URL(apiBase() + path);
  if (params) {
    for (const [k, v] of Object.entries(params)) {
      if (v !== "" && v != null) url.searchParams.set(k, v);
    }
  }
  const token = apiToken();
  const headers: Record<string, string> = { Accept: "application/json" };
  if (token) headers.Authorization = `Bearer ${token}`;

  let res: Response;
  try {
    res = await fetch(url.toString(), { headers });
  } catch (err) {
    // network / connection refused: the server is not up. Surface it honestly.
    throw new ApiError(0, err instanceof Error ? err.message : "network error");
  }

  if (!res.ok) {
    let msg = `request failed (${res.status})`;
    try {
      const body = await res.json();
      msg = body.error || body.detail || body.message || msg;
    } catch {
      /* non-JSON error body, keep the status message */
    }
    throw new ApiError(res.status, msg);
  }
  return (await res.json()) as T;
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
};
