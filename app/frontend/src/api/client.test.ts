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

function okDownload(content: string, filename: string): Response {
  const blob = new Blob([content], { type: "text/csv" });
  return {
    ok: true,
    status: 200,
    blob: async () => blob,
    headers: new Headers({
      "content-disposition": `attachment; filename="${filename}"`,
    }),
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

  it("routes delete recovery through the exact part-scoped undo endpoint", async () => {
    fetchMock.mockResolvedValueOnce(okJson({ id: "part/with space" }));

    await api.restoreDeletedPart("part/with space");

    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toContain("/api/library/parts/part%2Fwith%20space/undo-delete");
    expect((init as RequestInit).method).toBe("POST");
  });

  it("searchParts serializes each spec constraint as a repeated query param", async () => {
    fetchMock.mockResolvedValueOnce(okJson({ parts: [], count: 0 }));

    await api.searchParts({
      category: "Resistors",
      spec: ["Resistance:1000~10000", "Tolerance:1%"],
    });

    const url = new URL(String(fetchMock.mock.calls[0][0]));
    expect(url.pathname).toContain("/api/library/search");
    expect(url.searchParams.get("category")).toBe("Resistors");
    expect(url.searchParams.getAll("spec")).toEqual(["Resistance:1000~10000", "Tolerance:1%"]);
  });

  it("parametricFacets scopes by category and query", async () => {
    fetchMock.mockResolvedValueOnce(okJson({ category: "Resistors", facets: [], total: 0 }));

    await api.parametricFacets({ category: "Resistors", q: "0603" });

    const url = new URL(String(fetchMock.mock.calls[0][0]));
    expect(url.pathname).toContain("/api/library/facets/parametric");
    expect(url.searchParams.get("category")).toBe("Resistors");
    expect(url.searchParams.get("q")).toBe("0603");
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

  it("binds a change request to the exact displayed project review", async () => {
    fetchMock.mockResolvedValueOnce(
      okJson({
        event: { id: "event-1", kind: "changes_requested" },
        candidate: {},
      }),
    );

    await api.requestProjectChanges("amp", {
      branch: "work/mina/power",
      commit: "b".repeat(40),
      base_branch: "main",
      base_commit: "a".repeat(40),
      reviewer: "Sadad",
      message: "Verify the power-stage clearance.",
    });

    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toContain("/api/projects/amp/reviews/request-changes");
    expect(init).toMatchObject({
      method: "POST",
      body: JSON.stringify({
        branch: "work/mina/power",
        commit: "b".repeat(40),
        base_branch: "main",
        base_commit: "a".repeat(40),
        reviewer: "Sadad",
        message: "Verify the power-stage clearance.",
      }),
    });
  });

  it("builds evidence for the exact displayed project review", async () => {
    fetchMock.mockResolvedValueOnce(
      okJson({
        schema_version: 1,
        commit: "b".repeat(40),
        digest: "d".repeat(64),
      }),
    );

    await api.projectReviewEvidence("amp", {
      branch: "work/mina/power",
      commit: "b".repeat(40),
      base_branch: "main",
      base_commit: "a".repeat(40),
    });

    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toContain("/api/projects/amp/reviews/evidence");
    expect(init).toMatchObject({
      method: "POST",
      body: JSON.stringify({
        branch: "work/mina/power",
        commit: "b".repeat(40),
        base_branch: "main",
        base_commit: "a".repeat(40),
      }),
    });
  });

  it("runs native checks for the exact displayed project review", async () => {
    fetchMock.mockResolvedValueOnce(
      okJson({
        schema_version: 1,
        status: "passed",
        commit: "b".repeat(40),
        digest: "d".repeat(64),
      }),
    );

    await api.validateProjectReview("amp", {
      branch: "work/mina/power",
      commit: "b".repeat(40),
      base_branch: "main",
      base_commit: "a".repeat(40),
    });

    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toContain("/api/projects/amp/reviews/validate");
    expect(init).toMatchObject({
      method: "POST",
      body: JSON.stringify({
        branch: "work/mina/power",
        commit: "b".repeat(40),
        base_branch: "main",
        base_commit: "a".repeat(40),
      }),
    });
  });

  it("reads the live project BOM at the selected board quantity", async () => {
    fetchMock.mockResolvedValueOnce(okJson({ lines: [], evidence: {} }));

    await api.liveProjectBom("amp power", 7);

    const url = new URL(String(fetchMock.mock.calls[0][0]));
    expect(url.pathname).toContain("/api/projects/amp%20power/bom/live");
    expect(url.searchParams.get("boards")).toBe("7");
  });

  it("downloads the live project BOM with the server filename", async () => {
    fetchMock.mockResolvedValueOnce(okDownload("Qty,MPN\n7,LM358DR\n", "amp-bom.csv"));

    const result = await api.liveProjectBomExport("amp power", 7);

    const [rawUrl, init] = fetchMock.mock.calls[0];
    const url = new URL(String(rawUrl));
    expect(url.pathname).toContain("/api/projects/amp%20power/bom/live/export");
    expect(url.searchParams.get("boards")).toBe("7");
    expect(url.searchParams.get("kind")).toBe("csv");
    expect((init as RequestInit).headers).toMatchObject({
      Authorization: "Bearer test-token",
      Accept: "text/csv",
    });
    expect(result.filename).toBe("amp-bom.csv");
    expect(result.blob.type).toBe("text/csv");
    expect(result.blob.size).toBeGreaterThan(0);
  });

  it("assigns one exact placement group through the shared project route", async () => {
    fetchMock.mockResolvedValueOnce(
      okJson({ project: "Amp", refs: ["R1", "R2"], part_id: "r10k", bound: 2 }),
    );

    await api.assignProjectGroup("amp power", ["R1", "R2"], "r10k");

    const [url, init] = fetchMock.mock.calls[0];
    expect(new URL(String(url)).pathname).toContain("/api/projects/amp%20power/assign");
    expect(init).toMatchObject({
      method: "POST",
      body: JSON.stringify({ refs: ["R1", "R2"], part_id: "r10k" }),
    });
  });

  it("resumes one exact persisted project work session", async () => {
    fetchMock.mockResolvedValueOnce(okJson({ repository: null, session: null, recovery: null }));

    await api.resumeWorkSession("amp power", "session/a");

    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toContain("/api/projects/amp%20power/work-sessions/session%2Fa/resume");
    expect(init).toMatchObject({ method: "POST" });
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

  it("surfaces an MPN collision as a typed conflict naming the existing component", async () => {
    fetchMock.mockResolvedValueOnce(
      errJson(409, {
        error: "MpnConflictError",
        detail: "MPN 'lm 358' already exists as 'LM/358'",
        code: "mpn_conflict",
        existing_part_id: "lm-358-a1b2",
        existing_mpn: "LM/358",
      }),
    );

    await expect(
      api.ingestCommit({ vendor: "manual", mpn: "lm 358" } as never),
    ).rejects.toMatchObject({
      status: 409,
      code: "mpn_conflict",
      existingPartId: "lm-358-a1b2",
      existingMpn: "LM/358",
    });
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

  it("posts the mpn and category to enrich and returns the job ref (the sourced result now streams over SSE)", async () => {
    fetchMock.mockResolvedValueOnce(okJson({ job_id: "job456" }));

    const res = await api.enrichPart("LM358DR", "ICs");

    expect(res).toEqual({ job_id: "job456" });
    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toContain("/api/enrich/part");
    expect((init as RequestInit).method).toBe("POST");
    expect(JSON.parse((init as RequestInit).body as string)).toEqual({
      mpn: "LM358DR",
      category: "ICs",
    });
  });

  it("POSTs the per-part sourcing refresh and returns the job ref", async () => {
    fetchMock.mockResolvedValueOnce(okJson({ job_id: "job789" }));

    const res = await api.refreshSourcing("lm358");

    expect(res).toEqual({ job_id: "job789" });
    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toContain("/api/library/parts/lm358/refresh");
    expect((init as RequestInit).method).toBe("POST");
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

    fetchMock.mockResolvedValueOnce(okJson({ profiles: ["Main", "Archive"], active: "Main" }));
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
    expect(new Uint8Array(buf).slice(0, 4)).toEqual(new Uint8Array([0x67, 0x6c, 0x54, 0x46]));
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

  it("loads shared native project visual metadata for any adapter", async () => {
    fetchMock.mockResolvedValueOnce(
      okJson({ adapter: "altium", status: "ready", documents: [] }),
    );

    const result = await api.projectVisuals("control board", true);

    expect(result).toMatchObject({ adapter: "altium", status: "ready" });
    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toContain("/api/projects/control%20board/visuals");
    expect(String(url)).toContain("refresh=true");
    expect((init as RequestInit).headers).toMatchObject({
      Authorization: "Bearer test-token",
    });
  });

  it("connects a project remote through the project-scoped collaboration route", async () => {
    fetchMock.mockResolvedValueOnce(
      okJson({
        collaboration: { repository: { has_remote: true } },
        sync: {
          state: "pushed",
          pulled: false,
          pushed: true,
          converged: false,
          detail: "",
        },
      }),
    );

    const result = await api.connectProjectRemote(
      "power board",
      "git@github.com:team/power-board.git",
    );

    expect(result.sync.state).toBe("pushed");
    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toContain(
      "/api/projects/power%20board/collaboration/remote",
    );
    expect(init).toMatchObject({
      method: "POST",
      body: JSON.stringify({ url: "git@github.com:team/power-board.git" }),
    });
  });

  it("opens an adapter-reported project document without sending a filesystem path", async () => {
    fetchMock.mockResolvedValueOnce(
      okJson({
        opened: true,
        document_id: "pcb:Boards/Main.PcbDoc",
        path: "Boards/Main.PcbDoc",
      }),
    );

    await api.openProjectDocument(
      "control board",
      "pcb:Boards/Main.PcbDoc",
    );

    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toContain(
      "/api/projects/control%20board/documents/pcb%3ABoards%2FMain.PcbDoc/open",
    );
    expect(init).toMatchObject({ method: "POST" });
    expect((init as RequestInit).body).toBeUndefined();
  });

  it("surfaces typed remote URL validation as readable field guidance", async () => {
    fetchMock.mockResolvedValueOnce(
      errJson(422, {
        detail: [
          {
            type: "value_error",
            loc: ["body", "url"],
            msg: "Value error, use a secure HTTPS or SSH repository URL",
          },
        ],
      }),
    );

    await expect(
      api.connectProjectRemote("power board", "ftp://example.com/project.git"),
    ).rejects.toMatchObject({
      status: 422,
      message: "use a secure HTTPS or SSH repository URL",
    });
  });

  it("fetches a native PCB artifact with the bearer and returns a blob", async () => {
    fetchMock.mockResolvedValueOnce(okBlob(new Uint8Array([1, 2, 3]), "image/svg+xml"));

    const blob = await api.projectVisualArtifact("power board", "top/view");

    expect(blob).toBeInstanceOf(Blob);
    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toContain(
      "/api/projects/power%20board/visuals/top%2Fview",
    );
    expect((init as RequestInit).headers).toMatchObject({
      Authorization: "Bearer test-token",
      Accept: "image/*",
    });
  });

  // --- Per-part git timeline (M6k) ---

  it("reads the part git history at the history path", async () => {
    fetchMock.mockResolvedValueOnce(
      okJson({
        commits: [
          {
            sha: "a".repeat(40),
            subject: "Edit tps: mpn",
            author: "Sadad",
            iso_date: "2026-07-13T12:00:00-04:00",
          },
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
      okJson({
        a: "",
        b: "def",
        fields: [],
        assets: { symbol: false, footprint: false, model: false, datasheet: false },
      }),
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
      okJson({
        a: "abc",
        b: "def",
        fields: [],
        assets: { symbol: true, footprint: false, model: false, datasheet: false },
      }),
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

  // --- STM Viewer (Phase 3 contract) ---

  it("getStmMcus builds the mcus URL with only the provided scope params", async () => {
    fetchMock.mockResolvedValueOnce(okJson({ mcus: [], count: 0, facets: {} }));

    await api.getStmMcus({ family: "STM32F4", q: "", core: "Cortex-M4", package: "" });

    const url = new URL(String(fetchMock.mock.calls[0][0]));
    expect(url.pathname).toBe("/api/stm/mcus");
    expect(url.searchParams.get("family")).toBe("STM32F4");
    expect(url.searchParams.get("core")).toBe("Cortex-M4");
    // empty q + package are dropped from the query, exactly like listParts
    expect(url.searchParams.has("q")).toBe(false);
    expect(url.searchParams.has("package")).toBe(false);
  });

  it("getStmMcus with a blank scope requests the full matrix (no query params)", async () => {
    fetchMock.mockResolvedValueOnce(okJson({ mcus: [], count: 0, facets: {} }));

    await api.getStmMcus();

    const url = new URL(String(fetchMock.mock.calls[0][0]));
    expect(url.pathname).toBe("/api/stm/mcus");
    expect(url.search).toBe("");
  });

  it("getStmPinout passes part as a query param (never path-encoded)", async () => {
    fetchMock.mockResolvedValueOnce(okJson({ part: "x", pins: [] }));

    await api.getStmPinout("STM32F407V(E-G)Tx");

    const url = new URL(String(fetchMock.mock.calls[0][0]));
    expect(url.pathname).toBe("/api/stm/pinout");
    // the ref name's parentheses live in the ?part= value, not the path
    expect(url.searchParams.get("part")).toBe("STM32F407V(E-G)Tx");
  });

  it("getStmStatus and getStmFamilies send the bearer token", async () => {
    fetchMock.mockResolvedValueOnce(okJson({ built: false }));
    await api.getStmStatus();
    const [statusUrl, statusInit] = fetchMock.mock.calls[0];
    expect(String(statusUrl)).toContain("/api/stm/status");
    expect((statusInit as RequestInit).headers).toMatchObject({
      Authorization: "Bearer test-token",
    });

    fetchMock.mockResolvedValueOnce(okJson({ families: [] }));
    await api.getStmFamilies();
    expect(String(fetchMock.mock.calls[1][0])).toContain("/api/stm/families");
  });

  it("buildStmIndex POSTs to /api/stm/build and resolves the job ref", async () => {
    fetchMock.mockResolvedValueOnce(okJson({ job_id: "job-42" }));

    const ref = await api.buildStmIndex();

    expect(ref).toEqual({ job_id: "job-42" });
    const [url, init] = fetchMock.mock.calls[0];
    expect(new URL(String(url)).pathname).toBe("/api/stm/build");
    expect((init as RequestInit).method).toBe("POST");
  });

  it("a 409 from an STM read surfaces as ApiError.status === 409 the caller can branch on", async () => {
    fetchMock.mockResolvedValueOnce(errJson(409, { detail: "STM index not built" }));

    await expect(api.getStmMcus()).rejects.toMatchObject({
      name: "ApiError",
      status: 409,
    });
    // and the message is carried through for an honest surface
    await expect(
      (async () => {
        fetchMock.mockResolvedValueOnce(errJson(409, { detail: "STM index not built" }));
        try {
          await api.getStmStatus();
        } catch (err) {
          throw err instanceof ApiError ? err.message : "wrong error type";
        }
      })(),
    ).rejects.toBe("STM index not built");
  });

  it("preserves the durable completion reference returned by submission", async () => {
    fetchMock.mockResolvedValueOnce(okJson({ workflow_batch_id: "batch-1", event_cursor: 17 }));

    const result = await api.runCompletion({
      limit: 1_000,
      idempotencyKey: "completion-command-1",
    });

    expect(result).toEqual({
      workflow_batch_id: "batch-1",
      event_cursor: 17,
    });
    const [url, init] = fetchMock.mock.calls[0];
    expect(new URL(String(url)).pathname).toBe("/api/library/completion/run");
    expect((init as RequestInit).method).toBe("POST");
    expect(JSON.parse(String((init as RequestInit).body))).toEqual({
      limit: 1_000,
      idempotency_key: "completion-command-1",
    });
  });

  it("serializes bounded durable event cursors and batch pages", async () => {
    fetchMock
      .mockResolvedValueOnce(okJson({ schema_version: 1, events: [] }))
      .mockResolvedValueOnce(okJson({ schema_version: 1, items: [] }));

    await api.workflowEvents("batch-1", 42, 200);
    await api.workflowBatch("batch-1", 99, 100);

    const eventUrl = new URL(String(fetchMock.mock.calls[0][0]));
    expect(eventUrl.pathname).toBe("/api/workflows/batches/batch-1/events");
    expect(eventUrl.searchParams.get("after_sequence")).toBe("42");
    expect(eventUrl.searchParams.get("limit")).toBe("200");
    const batchUrl = new URL(String(fetchMock.mock.calls[1][0]));
    expect(batchUrl.pathname).toBe("/api/workflows/batches/batch-1");
    expect(batchUrl.searchParams.get("after_ordinal")).toBe("99");
    expect(batchUrl.searchParams.get("limit")).toBe("100");
  });

  it("routes every durable control to its exact batch-scoped endpoint", async () => {
    for (let index = 0; index < 4; index += 1) {
      fetchMock.mockResolvedValueOnce(okJson({ schema_version: 1 }));
    }

    await api.workflowPause("batch-1");
    await api.workflowResume("batch-1");
    await api.workflowRetry("batch-1");
    await api.workflowCancel("batch-1");

    expect(
      fetchMock.mock.calls.map(([url, init]) => ({
        method: (init as RequestInit).method,
        path: new URL(String(url)).pathname,
      })),
    ).toEqual([
      { method: "POST", path: "/api/workflows/batches/batch-1/pause" },
      { method: "POST", path: "/api/workflows/batches/batch-1/resume" },
      { method: "POST", path: "/api/workflows/batches/batch-1/retry" },
      { method: "POST", path: "/api/workflows/batches/batch-1/cancel" },
    ]);
  });

  it("reads Catalog Build status and confirms the only build mutation", async () => {
    fetchMock
      .mockResolvedValueOnce(okJson({ state: "pending", pending_count: 2 }))
      .mockResolvedValueOnce(okJson({ status: "completed", succeeded: 2 }));

    await api.catalogBuildStatus();
    await api.catalogBuild();

    const status = fetchMock.mock.calls[0];
    expect(new URL(String(status[0])).pathname).toBe("/api/catalog-build/status");
    expect((status[1] as RequestInit).method).toBe("GET");
    const build = fetchMock.mock.calls[1];
    expect(new URL(String(build[0])).pathname).toBe("/api/catalog-build");
    expect((build[1] as RequestInit).method).toBe("POST");
    expect(JSON.parse(String((build[1] as RequestInit).body))).toEqual({ confirmed: true });
  });
});
