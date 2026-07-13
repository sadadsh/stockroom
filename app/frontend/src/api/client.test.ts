import { api, ApiError } from "./client";

// Characterization tests for the typed fetch client. These lock today's
// behavior (bearer header, param serialization, honest error surfacing) so the
// M6 mutation work can extend the client without regressing the read path.

function okJson(body: unknown): Response {
  return {
    ok: true,
    status: 200,
    json: async () => body,
  } as unknown as Response;
}

function errJson(status: number, body: unknown): Response {
  return {
    ok: false,
    status,
    json: async () => body,
  } as unknown as Response;
}

describe("api client", () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
  });

  it("sends the bearer token and parses the parts response", async () => {
    fetchMock.mockResolvedValueOnce(okJson({ parts: [], count: 0 }));

    const res = await api.listParts({ q: "lm358" });

    expect(res).toEqual({ parts: [], count: 0 });
    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toContain("/api/library/parts");
    expect(String(url)).toContain("q=lm358");
    expect((init as RequestInit).headers).toMatchObject({
      Authorization: "Bearer test-token",
    });
  });

  it("only serializes truthy list params", async () => {
    fetchMock.mockResolvedValueOnce(okJson({ parts: [], count: 0 }));

    await api.listParts({ q: "", category: null, completeOnly: true });

    const url = String(fetchMock.mock.calls[0][0]);
    expect(url).not.toContain("q=");
    expect(url).not.toContain("category=");
    expect(url).toContain("complete_only=true");
  });

  it("surfaces the backend error message and status on a non-ok response", async () => {
    fetchMock.mockResolvedValueOnce(errJson(404, { error: "not found" }));

    await expect(api.partDetail("nope")).rejects.toMatchObject({
      status: 404,
      message: "not found",
    });
  });

  it("prefers detail over a generic message when error is absent", async () => {
    fetchMock.mockResolvedValueOnce(errJson(422, { detail: "incomplete" }));

    await expect(api.partDetail("x")).rejects.toBeInstanceOf(ApiError);
    fetchMock.mockResolvedValueOnce(errJson(422, { detail: "incomplete" }));
    await expect(api.partDetail("x")).rejects.toMatchObject({ message: "incomplete" });
  });

  it("reports a network failure as ApiError status 0", async () => {
    fetchMock.mockRejectedValueOnce(new Error("connection refused"));

    await expect(api.facets()).rejects.toMatchObject({
      status: 0,
      message: "connection refused",
    });
  });

  it("posts the mpn and category to enrich and returns the sourced result", async () => {
    fetchMock.mockResolvedValueOnce(
      okJson({
        category: "ICs",
        mpn: { value: "LM358DR", source: "jsonld", confidence: "high" },
        manufacturer: { value: "Texas Instruments", source: "jsonld", confidence: "high" },
        description: null,
        datasheet_url: null,
        stock: null,
        package: null,
        price_breaks: [],
        specs: {},
        schema_version: 1,
      }),
    );

    const res = await api.enrichPart("LM358DR", "ICs");

    expect(res.manufacturer?.value).toBe("Texas Instruments");
    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toContain("/api/enrich/part");
    expect((init as RequestInit).method).toBe("POST");
    expect(JSON.parse((init as RequestInit).body as string)).toEqual({
      mpn: "LM358DR",
      category: "ICs",
    });
  });
});
