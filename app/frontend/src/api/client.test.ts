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

  it("posts inspect paths and lcsc ids and returns the job id", async () => {
    fetchMock.mockResolvedValueOnce(okJson({ job_id: "job123" }));

    const res = await api.ingestInspect(["/tmp/part.zip"], ["C123"]);

    expect(res).toEqual({ job_id: "job123" });
    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toContain("/api/ingest/inspect");
    expect((init as RequestInit).method).toBe("POST");
    expect(JSON.parse((init as RequestInit).body as string)).toEqual({
      paths: ["/tmp/part.zip"],
      lcsc_ids: ["C123"],
    });
  });

  it("surfaces the 422 complete-to-add gate missing list on commit as ApiError.missing", async () => {
    fetchMock.mockResolvedValueOnce(
      errJson(422, {
        error: "IncompleteError",
        detail: "cannot add an incomplete part; missing: 3D model, datasheet",
        missing: ["3D model", "datasheet"],
      }),
    );

    await expect(
      api.ingestCommit({ vendor: "snapeda", display_name: "X" } as never),
    ).rejects.toMatchObject({ status: 422, missing: ["3D model", "datasheet"] });
  });

  it("opens the job event stream with the bearer header and returns the raw body", async () => {
    const fakeBody = {} as ReadableStream<Uint8Array>;
    fetchMock.mockResolvedValueOnce({
      ok: true,
      status: 200,
      body: fakeBody,
    } as unknown as Response);

    const body = await api.openJobStream("job123");

    expect(body).toBe(fakeBody);
    const [url, init] = fetchMock.mock.calls[0];
    expect(new URL(String(url)).pathname).toBe("/api/jobs/job123/events");
    // The token rides the header only; it must never leak into the URL query
    // string (which lands in logs) since the SSE route is header-auth only.
    expect(new URL(String(url)).search).toBe("");
    expect((init as RequestInit).headers).toMatchObject({
      Authorization: "Bearer test-token",
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

  it("reads the redacted settings", async () => {
    fetchMock.mockResolvedValueOnce(
      okJson({ mouser_api_key_set: true, mouser_api_key_hint: "1234" }),
    );
    const res = await api.getSettings();
    expect(res.mouser_api_key_set).toBe(true);
    expect(String(fetchMock.mock.calls[0][0])).toContain("/api/settings");
  });

  it("PATCHes the mouser key and returns the redacted result", async () => {
    fetchMock.mockResolvedValueOnce(
      okJson({ mouser_api_key_set: true, mouser_api_key_hint: "9999" }),
    );
    const res = await api.updateSettings({ mouser_api_key: "SECRET9999" });
    expect(res.mouser_api_key_hint).toBe("9999");
    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toContain("/api/settings");
    expect((init as RequestInit).method).toBe("PATCH");
    expect(JSON.parse((init as RequestInit).body as string)).toEqual({
      mouser_api_key: "SECRET9999",
    });
  });

  it("lists profiles and creates one with an archive flag", async () => {
    fetchMock.mockResolvedValueOnce(okJson({ profiles: ["Main"], active: "Main" }));
    await api.listProfiles();
    expect(String(fetchMock.mock.calls[0][0])).toContain("/api/profiles");

    fetchMock.mockResolvedValueOnce(
      okJson({ profiles: ["Main", "Archive"], active: "Main" }),
    );
    await api.createProfile("Archive", true);
    const init = fetchMock.mock.calls[1][1] as RequestInit;
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body as string)).toEqual({ name: "Archive", archive: true });
  });

  it("activates and deletes a profile by name", async () => {
    fetchMock.mockResolvedValueOnce(okJson({ active: "Archive", part_count: 0 }));
    const res = await api.activateProfile("Archive");
    expect(res.active).toBe("Archive");
    expect(new URL(String(fetchMock.mock.calls[0][0])).pathname).toBe(
      "/api/profiles/Archive/activate",
    );
    expect((fetchMock.mock.calls[0][1] as RequestInit).method).toBe("POST");

    fetchMock.mockResolvedValueOnce({ ok: true, status: 204 } as unknown as Response);
    await api.deleteProfile("Archive");
    expect((fetchMock.mock.calls[1][1] as RequestInit).method).toBe("DELETE");
  });

  it("reads sync status and runs a sync", async () => {
    fetchMock.mockResolvedValueOnce(
      okJson({ has_remote: true, current_branch: "main", ahead: 0, behind: 2 }),
    );
    const status = await api.getSyncStatus();
    expect(status.behind).toBe(2);

    fetchMock.mockResolvedValueOnce(
      okJson({ state: "synced", pulled: true, pushed: false, detail: "" }),
    );
    const res = await api.doSync();
    expect(res.pulled).toBe(true);
    expect((fetchMock.mock.calls[1][1] as RequestInit).method).toBe("POST");
    expect(new URL(String(fetchMock.mock.calls[1][0])).pathname).toBe("/api/sync");
  });

  it("checks for and applies an app update", async () => {
    fetchMock.mockResolvedValueOnce(okJson({ update_available: true, behind: 3 }));
    const check = await api.checkUpdate();
    expect(check.update_available).toBe(true);

    fetchMock.mockResolvedValueOnce(
      okJson({ state: "updated", updated: true, detail: "", restart_requested: true }),
    );
    const res = await api.applyUpdate();
    expect(res.restart_requested).toBe(true);
    expect((fetchMock.mock.calls[1][1] as RequestInit).method).toBe("POST");
  });

  it("reads system info", async () => {
    fetchMock.mockResolvedValueOnce(
      okJson({
        active_profile: "Main",
        part_count: 8,
        kicad_config_dir: "/x/kicad",
        kicad_running: false,
        kicad_cli_available: true,
        kicad_cli_path: "/usr/bin/kicad-cli",
      }),
    );
    const info = await api.getSystemInfo();
    expect(info.kicad_cli_available).toBe(true);
    expect(String(fetchMock.mock.calls[0][0])).toContain("/api/system/info");
  });
});
