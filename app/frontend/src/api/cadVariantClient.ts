/**
 * Isolated typed client for coherent CAD bundle variants.
 *
 * The main client is intentionally not widened while other acquisition work is active in it.
 * This module still follows the same runtime bearer-token contract and `/api/*` boundary.
 */
import { apiBase, apiToken } from "../lib/runtime";

export type CadVariantTool = "kicad" | "altium";
export type CadVariantArtifactKind = "symbol" | "footprint" | "model";

export interface CadVariantArtifact {
  kind: CadVariantArtifactKind;
  fileName: string;
}

export interface CadVariant {
  id: string;
  provider: string;
  format: string;
  artifacts: readonly CadVariantArtifact[];
  evidenceDigest: string;
  validationChecks: number;
  /**
   * Lower is more trusted. Ranking belongs to backend policy, not provider-name logic in the UI.
   */
  trustRank: number;
  trustLabel: string;
  trustReason?: string;
}

export interface CadVariantInventory {
  tool: CadVariantTool;
  activeVariantId: string | null;
  variants: readonly CadVariant[];
}

export interface CadVariantDocument {
  partId: string;
  inventories: readonly CadVariantInventory[];
}

export interface CadVariantActivation {
  tool: CadVariantTool;
  variantId: string;
  expectedActiveVariantId: string | null;
}

export class CadVariantApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "CadVariantApiError";
    this.status = status;
  }
}

async function requestCadVariants(
  method: "GET" | "POST",
  path: string,
  body?: CadVariantActivation,
): Promise<CadVariantDocument> {
  const headers: Record<string, string> = { Accept: "application/json" };
  const token = apiToken();
  if (token) headers.Authorization = `Bearer ${token}`;
  const init: RequestInit = { method, headers };
  if (body) {
    headers["Content-Type"] = "application/json";
    init.body = JSON.stringify(body);
  }

  let response: Response;
  try {
    response = await fetch(apiBase() + path, init);
  } catch (error) {
    throw new CadVariantApiError(
      0,
      error instanceof Error ? error.message : "Network error",
    );
  }

  if (!response.ok) {
    let message = `Request failed (${response.status})`;
    try {
      const error = (await response.json()) as {
        detail?: string;
        error?: string;
        message?: string;
      };
      message = error.detail || error.error || error.message || message;
    } catch {
      // A non-JSON response still carries the honest HTTP status above.
    }
    throw new CadVariantApiError(response.status, message);
  }
  return (await response.json()) as CadVariantDocument;
}

function variantsPath(partId: string): string {
  return `/api/library/parts/${encodeURIComponent(partId)}/cad-variants`;
}

export const cadVariantApi = {
  inventory(partId: string): Promise<CadVariantDocument> {
    return requestCadVariants("GET", variantsPath(partId));
  },

  activate(
    partId: string,
    activation: CadVariantActivation,
  ): Promise<CadVariantDocument> {
    return requestCadVariants(
      "POST",
      `${variantsPath(partId)}/activate`,
      activation,
    );
  },
};
