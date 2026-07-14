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

function okBlob(bytes: Uint8Array, type: string): Response {
  // TS 5.7+ made Uint8Array generic over its buffer, so a bare Uint8Array is no
  // longer directly assignable to BlobPart (ArrayBufferView<ArrayBuffer>); the
  // bytes are a valid BlobPart at runtime, so cast for the Blob constructor.
  const blob = new Blob([bytes as BlobPart], { type });
  return {
    ok: true,
    status: 200,
    blob: async () => blob,
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

  it("prefers the descriptive detail over the exception class name when both are present", async () => {
    // The real backend envelope is {error: <ExceptionClassName>, detail: <message>}. The toast
    // must surface the human-readable detail, not the opaque class name ("ValueError").
    fetchMock.mockResolvedValueOnce(
      errJson(400, { error: "ValueError", detail: "unknown net class 'HS'" }),
    );
    await expect(api.partDetail("x")).rejects.toMatchObject({
      message: "unknown net class 'HS'",
    });
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

  // --- Previews (M6d) ---

  it("requests the monochrome symbol SVG with the bearer and returns a blob", async () => {
    fetchMock.mockResolvedValueOnce(okBlob(new Uint8Array([1, 2, 3]), "image/svg+xml"));
    const blob = await api.previewSvg("symbol", "lm358");
    expect(blob).toBeInstanceOf(Blob);
    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toContain("/api/previews/symbol/lm358.svg");
    expect(String(url)).toContain("bw=true");
    expect((init as RequestInit).headers).toMatchObject({
      Authorization: "Bearer test-token",
    });
  });

  it("requests the footprint SVG at the footprint path", async () => {
    fetchMock.mockResolvedValueOnce(okBlob(new Uint8Array([1]), "image/svg+xml"));
    await api.previewSvg("footprint", "r0402");
    expect(String(fetchMock.mock.calls[0][0])).toContain("/api/previews/footprint/r0402.svg");
  });

  it("fetches the GLB model as an ArrayBuffer", async () => {
    fetchMock.mockResolvedValueOnce(
      okBlob(new Uint8Array([0x67, 0x6c, 0x54, 0x46]), "model/gltf-binary"),
    );
    const buf = await api.modelGlb("tps62130");
    expect(buf).toBeInstanceOf(ArrayBuffer);
    expect(new Uint8Array(buf).slice(0, 4)).toEqual(
      new Uint8Array([0x67, 0x6c, 0x54, 0x46]),
    );
    expect(String(fetchMock.mock.calls[0][0])).toContain("/api/previews/model/tps62130.glb");
  });

  it("surfaces a 502 (no 3D tooling) as an ApiError carrying the status", async () => {
    fetchMock.mockResolvedValueOnce(errJson(502, { detail: "trimesh not installed" }));
    await expect(api.modelGlb("tps62130")).rejects.toMatchObject({
      status: 502,
      message: "trimesh not installed",
    });
  });

  it("surfaces a preview 404 as an ApiError with the status", async () => {
    fetchMock.mockResolvedValueOnce(errJson(404, { detail: "no symbol" }));
    await expect(api.previewSvg("symbol", "nope")).rejects.toMatchObject({
      status: 404,
    });
  });

  // --- Per-part git timeline (M6k) ---

  it("reads the part git history at the history path", async () => {
    fetchMock.mockResolvedValueOnce(
      okJson({
        commits: [
          { sha: "a".repeat(40), subject: "Edit tps: mpn", author: "Sadad", iso_date: "2026-07-13T12:00:00-04:00" },
        ],
        count: 1,
      }),
    );
    const res = await api.partHistory("tps62130");
    expect(res.count).toBe(1);
    expect(res.commits[0].subject).toBe("Edit tps: mpn");
    expect(new URL(String(fetchMock.mock.calls[0][0])).pathname).toBe(
      "/api/library/parts/tps62130/history",
    );
  });

  it("requests the diff with both revs, dropping an empty 'a' (the earliest side)", async () => {
    fetchMock.mockResolvedValueOnce(
      okJson({ a: "", b: "def", fields: [], assets: { symbol: false, footprint: false, model: false, datasheet: false } }),
    );
    await api.partDiff("tps62130", "", "def456");
    const url = new URL(String(fetchMock.mock.calls[0][0]));
    expect(url.pathname).toBe("/api/library/parts/tps62130/diff");
    // an empty 'a' is dropped by the serializer, so the backend applies its "" default
    expect(url.searchParams.has("a")).toBe(false);
    expect(url.searchParams.get("b")).toBe("def456");
  });

  it("sends both revs when a real 'a' is given", async () => {
    fetchMock.mockResolvedValueOnce(
      okJson({ a: "abc", b: "def", fields: [], assets: { symbol: true, footprint: false, model: false, datasheet: false } }),
    );
    await api.partDiff("tps62130", "abc123", "def456");
    const url = new URL(String(fetchMock.mock.calls[0][0]));
    expect(url.searchParams.get("a")).toBe("abc123");
    expect(url.searchParams.get("b")).toBe("def456");
  });

  it("passes the rev to previewSvg for the historical render", async () => {
    fetchMock.mockResolvedValueOnce(okBlob(new Uint8Array([1]), "image/svg+xml"));
    await api.previewSvg("symbol", "tps62130", "abc123");
    const url = String(fetchMock.mock.calls[0][0]);
    expect(url).toContain("/api/previews/symbol/tps62130.svg");
    expect(url).toContain("rev=abc123");
    expect(url).toContain("bw=true");
  });

  // --- Projects (M7a) ---

  it("lists projects from the derived index", async () => {
    fetchMock.mockResolvedValueOnce(
      okJson([
        {
          id: "proj1",
          name: "Netdeck",
          root: "/home/sadad/git/netdeck",
          board_count: 1,
          sheet_count: 3,
          has_git: true,
          registered_at: "2026-07-13T12:00:00-04:00",
        },
      ]),
    );
    const res = await api.listProjects();
    expect(res).toHaveLength(1);
    expect(res[0].root).toBe("/home/sadad/git/netdeck");
    expect(new URL(String(fetchMock.mock.calls[0][0])).pathname).toBe("/api/projects");
    expect((fetchMock.mock.calls[0][1] as RequestInit).method).toBe("GET");
  });

  it("registers a project by posting its absolute root path", async () => {
    fetchMock.mockResolvedValueOnce(
      okJson({
        id: "proj1",
        name: "Netdeck",
        root: "/home/sadad/git/netdeck",
        pro_path: "/home/sadad/git/netdeck/netdeck.kicad_pro",
        board_paths: ["/home/sadad/git/netdeck/netdeck.kicad_pcb"],
        sheet_paths: ["/home/sadad/git/netdeck/netdeck.kicad_sch"],
        git_root: "/home/sadad/git/netdeck",
        audit_digest: null,
        registered_at: "2026-07-13T12:00:00-04:00",
      }),
    );
    const rec = await api.registerProject("/home/sadad/git/netdeck");
    expect(rec.name).toBe("Netdeck");
    const [url, init] = fetchMock.mock.calls[0];
    expect(new URL(String(url)).pathname).toBe("/api/projects");
    expect((init as RequestInit).method).toBe("POST");
    expect(JSON.parse((init as RequestInit).body as string)).toEqual({
      root: "/home/sadad/git/netdeck",
    });
  });

  it("surfaces a 400 (no KiCad files / already registered) as an ApiError", async () => {
    fetchMock.mockResolvedValueOnce(errJson(400, { detail: "no KiCad files found" }));
    await expect(api.registerProject("/tmp/empty")).rejects.toMatchObject({
      status: 400,
      message: "no KiCad files found",
    });
  });

  it("gets a single project record by id", async () => {
    fetchMock.mockResolvedValueOnce(
      okJson({
        id: "proj1",
        name: "Netdeck",
        root: "/home/sadad/git/netdeck",
        pro_path: "/home/sadad/git/netdeck/netdeck.kicad_pro",
        board_paths: [],
        sheet_paths: [],
        git_root: null,
        audit_digest: null,
        registered_at: "2026-07-13T12:00:00-04:00",
      }),
    );
    const rec = await api.getProject("proj1");
    expect(rec.git_root).toBeNull();
    expect(new URL(String(fetchMock.mock.calls[0][0])).pathname).toBe("/api/projects/proj1");
  });

  it("deletes a project by id (204, no body)", async () => {
    fetchMock.mockResolvedValueOnce({ ok: true, status: 204 } as unknown as Response);
    await api.deleteProject("proj1");
    const [url, init] = fetchMock.mock.calls[0];
    expect(new URL(String(url)).pathname).toBe("/api/projects/proj1");
    expect((init as RequestInit).method).toBe("DELETE");
  });

  it("reads the project audit with its markdown report", async () => {
    fetchMock.mockResolvedValueOnce(
      okJson({
        project: "netdeck",
        components: 42,
        healthy: 40,
        counts: {
          by_severity: { error: 1, warning: 1, info: 0 },
          by_kind: { unannotated: 1, no_footprint: 1 },
        },
        findings: [
          { ref: "U1", severity: "error", kind: "unannotated", detail: "reference designator not annotated" },
          { ref: "R5", severity: "warning", kind: "no_footprint", detail: "no footprint assigned" },
        ],
        checked_footprints: 40,
        unresolved_footprints: 0,
        sheets: 3,
        markdown: "# Health\n",
      }),
    );
    const au = await api.projectAudit("proj1");
    expect(au.components).toBe(42);
    expect(au.counts.by_kind.unannotated).toBe(1);
    expect(au.markdown).toContain("# Health");
    expect(new URL(String(fetchMock.mock.calls[0][0])).pathname).toBe(
      "/api/projects/proj1/audit",
    );
  });

  // --- Editor: design rules + net classes (M7e) ---

  it("reads the project design settings with the fab floor as a query param", async () => {
    fetchMock.mockResolvedValueOnce(
      okJson({
        project: "netdeck", under_git: true, has_pro: true, net_classes: [], netclass_patterns: [],
        design_rules: {}, track_widths: [], via_dimensions: [], diff_pair_dimensions: [],
        fab_floors: {}, validation: [],
      }),
    );
    await api.getDesign("proj1", "oshpark_2");
    const url = new URL(String(fetchMock.mock.calls[0][0]));
    expect(url.pathname).toBe("/api/projects/proj1/design");
    expect(url.searchParams.get("floor")).toBe("oshpark_2");
  });

  it("PATCHes net classes with the edited set, deletes and floor", async () => {
    fetchMock.mockResolvedValueOnce(
      okJson({ project: "netdeck", committed: "abc", net_classes: [], validation: [] }),
    );
    await api.setNetClasses("proj1", [{ name: "Default", track_width: 0.15 }], {
      deleted: ["OLD"], floor: "oshpark_2",
    });
    const [url, init] = fetchMock.mock.calls[0];
    expect(new URL(String(url)).pathname).toBe("/api/projects/proj1/net-classes");
    expect((init as RequestInit).method).toBe("PATCH");
    expect(JSON.parse((init as RequestInit).body as string)).toEqual({
      classes: [{ name: "Default", track_width: 0.15 }], deleted: ["OLD"], floor: "oshpark_2",
    });
  });

  it("PATCHes design rules (defaulting the size lists to omitted)", async () => {
    fetchMock.mockResolvedValueOnce(
      okJson({ project: "netdeck", committed: "abc", design_rules: { min_track_width: 0.13 } }),
    );
    await api.setDesignRules("proj1", { min_track_width: 0.13 });
    const [url, init] = fetchMock.mock.calls[0];
    expect(new URL(String(url)).pathname).toBe("/api/projects/proj1/design-rules");
    expect((init as RequestInit).method).toBe("PATCH");
    const body = JSON.parse((init as RequestInit).body as string);
    expect(body.rules).toEqual({ min_track_width: 0.13 });
  });
});
