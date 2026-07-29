import { afterEach, describe, expect, it, vi } from "vitest";
import {
  cadVariantApi,
  CadVariantApiError,
  type CadVariantDocument,
} from "./cadVariantClient";

const DOCUMENT: CadVariantDocument = {
  partId: "part/1",
  inventories: [],
  supplementary: [],
};

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("cadVariantApi", () => {
  it("reads only the requested part through the authenticated API boundary", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(DOCUMENT), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await expect(cadVariantApi.inventory("part/1")).resolves.toEqual(DOCUMENT);
    expect(fetchMock).toHaveBeenCalledWith(
      "http://127.0.0.1:8765/api/library/parts/part%2F1/cad-variants",
      {
        method: "GET",
        headers: {
          Accept: "application/json",
          Authorization: "Bearer test-token",
        },
      },
    );
  });

  it("posts the exact compare-and-switch body without a download or delete request", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(DOCUMENT), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await cadVariantApi.activate("part/1", {
      tool: "kicad",
      variantId: "sha256:new",
      expectedActiveVariantId: "sha256:old",
    });

    expect(fetchMock).toHaveBeenCalledWith(
      "http://127.0.0.1:8765/api/library/parts/part%2F1/cad-variants/activate",
      {
        method: "POST",
        headers: {
          Accept: "application/json",
          Authorization: "Bearer test-token",
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          tool: "kicad",
          variantId: "sha256:new",
          expectedActiveVariantId: "sha256:old",
        }),
      },
    );
  });

  it("preserves a stale-selection conflict as a typed 409", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ detail: "active variant changed" }), {
          status: 409,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );

    const result = cadVariantApi.activate("p1", {
      tool: "altium",
      variantId: "sha256:new",
      expectedActiveVariantId: null,
    });

    await expect(result).rejects.toMatchObject({
      name: "CadVariantApiError",
      status: 409,
      message: "active variant changed",
    } satisfies Partial<CadVariantApiError>);
  });
});
