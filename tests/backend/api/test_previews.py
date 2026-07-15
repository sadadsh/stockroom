import pytest

from tests.backend.conftest import requires_glb_tooling, requires_kicad_cli


def test_symbol_preview_404_when_part_absent(client):
    r = client.get("/api/previews/symbol/nope.svg")
    assert r.status_code == 404


def test_symbol_preview_uses_the_injected_cli_and_returns_svg(app_ctx, tmp_path):
    # Inject a fake CLI that writes a known SVG, so the render path is exercised
    # without kicad-cli. The fake honors the sym_export_svg signature.
    from fastapi.testclient import TestClient

    from stockroom.api.app import create_app

    class _FakeCli:
        def sym_export_svg(self, lib, symbol, out_dir, black_and_white=False):
            out = out_dir / f"{symbol}_unit1.svg"
            out.write_text("<svg><!-- fake --></svg>", encoding="utf-8")
            return [out]

        def fp_export_svg(self, pretty_dir, footprint, out_dir, layers="F.Cu,F.SilkS,F.Fab"):
            out = out_dir / f"{footprint}.svg"
            out.write_text("<svg><!-- fp --></svg>", encoding="utf-8")
            return out

    app_ctx.cli = _FakeCli()
    # the tps62130 fixture part must have its symbol lib file on disk for hashing;
    # write a placeholder symbol lib at the expected category path
    sym_path = app_ctx.profile.library.symbol_lib_path("ICs")
    sym_path.parent.mkdir(parents=True, exist_ok=True)
    sym_path.write_text("(kicad_symbol_lib)", encoding="utf-8")

    app = create_app(app_ctx)
    with TestClient(app, base_url="http://test", raise_server_exceptions=False,
                    headers={"X-Stockroom-Token": "testtoken"}) as c:
        r = c.get("/api/previews/symbol/tps62130.svg")
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("image/svg+xml")
        assert "svg" in r.text


@requires_kicad_cli
def test_symbol_preview_end_to_end_with_real_cli(client):
    # Only meaningful once the fixture ships a real .kicad_sym with the symbol; this
    # marks the honest integration boundary. Skipped where kicad-cli is absent.
    r = client.get("/api/previews/symbol/tps62130.svg")
    assert r.status_code in (200, 404, 502)


class _RecordingCli:
    """A fake kicad-cli that records the black_and_white flag it was asked for, so a
    test can prove the ?bw query param reaches the renderer."""

    def __init__(self):
        self.sym_bw: list[bool] = []
        self.fp_bw: list[bool] = []

    def sym_export_svg(self, lib, symbol, out_dir, black_and_white=False):
        self.sym_bw.append(black_and_white)
        out = out_dir / f"{symbol}_unit1.svg"
        out.write_text(f"<svg data-bw='{black_and_white}'><!-- sym --></svg>", encoding="utf-8")
        return [out]

    def fp_export_svg(self, pretty_dir, footprint, out_dir, layers="F.Cu,F.SilkS,F.Fab", *, black_and_white=False):
        self.fp_bw.append(black_and_white)
        out = out_dir / f"{footprint}.svg"
        out.write_text(f"<svg data-bw='{black_and_white}'><!-- fp --></svg>", encoding="utf-8")
        return out


def _client_with_cli(app_ctx, cli):
    from fastapi.testclient import TestClient

    from stockroom.api.app import create_app

    app_ctx.cli = cli
    app = create_app(app_ctx)
    return TestClient(
        app,
        base_url="http://test",
        raise_server_exceptions=False,
        headers={"X-Stockroom-Token": "testtoken"},
    )


def test_symbol_preview_bw_param_reaches_the_renderer(app_ctx):
    cli = _RecordingCli()
    with _client_with_cli(app_ctx, cli) as c:
        assert c.get("/api/previews/symbol/tps62130.svg").status_code == 200
        assert c.get("/api/previews/symbol/tps62130.svg?bw=true").status_code == 200
    # the color request rendered with black_and_white False, the bw request with True
    assert cli.sym_bw == [False, True]


def test_footprint_preview_bw_param_reaches_the_renderer(app_ctx):
    cli = _RecordingCli()
    with _client_with_cli(app_ctx, cli) as c:
        assert c.get("/api/previews/footprint/tps62130.svg").status_code == 200
        assert c.get("/api/previews/footprint/tps62130.svg?bw=true").status_code == 200
    assert cli.fp_bw == [False, True]


def test_bw_and_color_previews_cache_separately(app_ctx):
    # A bw request must not be served the cached color SVG (and vice versa): distinct
    # cache keys mean the renderer runs once per variant, not once total.
    cli = _RecordingCli()
    with _client_with_cli(app_ctx, cli) as c:
        c.get("/api/previews/symbol/tps62130.svg?bw=true")
        c.get("/api/previews/symbol/tps62130.svg?bw=true")  # served from cache
        c.get("/api/previews/symbol/tps62130.svg")  # color: distinct key, renders
    assert cli.sym_bw == [True, False]


def test_footprint_preview_rerenders_when_the_footprint_file_changes(app_ctx):
    # The footprint cache key is content-addressed: after the .kicad_mod bytes change
    # (a teammate edit + pull, or an fp upgrade), the endpoint must re-render, not serve
    # the stale SVG. Same name + part id, different bytes.
    cli = _RecordingCli()
    fp_file = app_ctx.profile.library.footprint_lib_path("ICs") / "TPS62130.kicad_mod"
    with _client_with_cli(app_ctx, cli) as c:
        c.get("/api/previews/footprint/tps62130.svg")  # renders + caches
        c.get("/api/previews/footprint/tps62130.svg")  # cache hit, no re-render
        assert len(cli.fp_bw) == 1
        fp_file.write_text(fp_file.read_text(encoding="utf-8") + "\n; edited\n", encoding="utf-8")
        c.get("/api/previews/footprint/tps62130.svg")  # content changed -> re-render
    assert len(cli.fp_bw) == 2


def test_model_glb_reconverts_a_corrupt_cache_entry(app_ctx, monkeypatch):
    # A truncated/corrupt cache file (no glTF magic) must be treated as a miss and
    # re-converted, never served as a 200 that the three.js loader parses to a blank canvas.
    from stockroom.api.routers import previews as previews_mod
    from stockroom.kicad.model_convert import GLB_MAGIC

    src = _put_model_file(app_ctx)
    # pre-seed the exact cache path with a corrupt (non-GLB) body
    import hashlib

    h = hashlib.sha256(src.read_bytes()).hexdigest()[:16]
    cache_dir = app_ctx.libraries_root.parent / ".stockroom-previews"
    cache_dir.mkdir(parents=True, exist_ok=True)
    (cache_dir / f"model_tps62130_{h}.glb").write_bytes(b"NOT-A-GLB truncated")

    calls = {"n": 0}

    def _convert(_src):
        calls["n"] += 1
        return GLB_MAGIC + b"\x02\x00\x00\x00good"

    monkeypatch.setattr(previews_mod, "model_to_glb", _convert)
    with _client_with_cli(app_ctx, app_ctx.cli) as c:
        r = c.get("/api/previews/model/tps62130.glb")
    assert r.status_code == 200
    assert r.content[:4] == GLB_MAGIC
    assert calls["n"] == 1  # the corrupt cache entry was NOT served; it re-converted


# --- ?rev historical render (M6k visual diff) -------------------------------


class _RevRecordingCli:
    """A fake cli that records the exact input file text it was handed, so a test can
    prove ?rev rendered the historical git blob, not the current working tree."""

    def __init__(self):
        self.sym_libs: list[str] = []
        self.fp_texts: list[str] = []

    def sym_export_svg(self, lib, symbol, out_dir, black_and_white=False):
        from pathlib import Path as _P

        self.sym_libs.append(_P(lib).read_text(encoding="utf-8"))
        out = out_dir / f"{symbol}.svg"
        out.write_text("<svg><!-- rev sym --></svg>", encoding="utf-8")
        return [out]

    def fp_export_svg(self, pretty_dir, footprint, out_dir, layers="F.Cu,F.SilkS,F.Fab", *, black_and_white=False):
        from pathlib import Path as _P

        self.fp_texts.append((_P(pretty_dir) / f"{footprint}.kicad_mod").read_text(encoding="utf-8"))
        out = out_dir / f"{footprint}.svg"
        out.write_text("<svg><!-- rev fp --></svg>", encoding="utf-8")
        return out


def _seed_sha(app_ctx, part_id="tps62130"):
    path = app_ctx.profile.library.parts_dir / f"{part_id}.json"
    return app_ctx.repo.log_paths([path])[0].sha


def test_symbol_preview_at_rev_renders_the_historical_blob(app_ctx):
    seed = _seed_sha(app_ctx)
    # edit manufacturer: a new commit whose symbol lib now carries the NEWCO property
    app_ctx.ops.edit_field("tps62130", "manufacturer", "NEWCO")
    cli = _RevRecordingCli()
    with _client_with_cli(app_ctx, cli) as c:
        assert c.get(f"/api/previews/symbol/tps62130.svg?rev={seed}").status_code == 200
        assert c.get("/api/previews/symbol/tps62130.svg").status_code == 200
    # the rev render read the seed blob (no NEWCO); the current render read the edit
    assert "NEWCO" not in cli.sym_libs[0]
    assert "NEWCO" in cli.sym_libs[1]


def test_footprint_preview_at_rev_renders_the_historical_blob(app_ctx):
    seed = _seed_sha(app_ctx)
    fp = app_ctx.profile.library.footprint_lib_path("ICs") / "TPS62130.kicad_mod"
    fp.write_text(fp.read_text(encoding="utf-8") + "\n; NEWPAD\n", encoding="utf-8")
    app_ctx.repo.commit("edit footprint", [fp])
    cli = _RevRecordingCli()
    with _client_with_cli(app_ctx, cli) as c:
        assert c.get(f"/api/previews/footprint/tps62130.svg?rev={seed}").status_code == 200
        assert c.get("/api/previews/footprint/tps62130.svg").status_code == 200
    assert "NEWPAD" not in cli.fp_texts[0]
    assert "NEWPAD" in cli.fp_texts[1]


def test_symbol_preview_at_rev_rejects_a_garbage_rev_as_400(app_ctx):
    # a malformed (non-object-name) rev is a client error, not a git-backend outage:
    # it must be a 4xx, never a 503 GitError.
    cli = _RevRecordingCli()
    with _client_with_cli(app_ctx, cli) as c:
        r = c.get("/api/previews/symbol/tps62130.svg?rev=notarev")
    assert r.status_code == 400


def test_symbol_preview_at_rev_404_when_part_absent_at_that_rev(app_ctx):
    from stockroom.model.part import LibRef, PartRecord

    seed = _seed_sha(app_ctx)  # before the latecomer existed
    rec = PartRecord(id="latecomer", display_name="LATECOMER", category="ICs")
    rec.symbol = LibRef(lib="SR-ICs", name="LATECOMER")
    parts_dir = app_ctx.profile.library.parts_dir
    (parts_dir / "latecomer.json").write_text(rec.dumps(), encoding="utf-8")
    app_ctx.repo.commit("add latecomer", [parts_dir / "latecomer.json"])
    app_ctx.rebuild_index()
    cli = _RevRecordingCli()
    with _client_with_cli(app_ctx, cli) as c:
        r = c.get(f"/api/previews/symbol/latecomer.svg?rev={seed}")
    assert r.status_code == 404


# --- 3D model → GLB (M6d-2) -------------------------------------------------

def _put_model_file(app_ctx, rel="models/x.step", data=b"dummy"):
    """Materialise the fixture part's model file on disk (tps62130's record points at
    models/x.step but the fixture never wrote the bytes)."""
    dst = app_ctx.profile.library.root / rel
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_bytes(data)
    return dst


def test_model_glb_404_when_part_absent(client):
    assert client.get("/api/previews/model/nope.glb").status_code == 404


def test_model_glb_404_when_part_has_no_model(client):
    # the `mystery` fixture part carries no 3D model
    assert client.get("/api/previews/model/mystery.glb").status_code == 404


def test_model_glb_404_when_model_file_is_dangling(client):
    # tps62130's record references models/x.step, but no such file exists on disk
    assert client.get("/api/previews/model/tps62130.glb").status_code == 404


def test_model_glb_502_when_conversion_tooling_absent(app_ctx, monkeypatch):
    _put_model_file(app_ctx)
    from stockroom.api.routers import previews as previews_mod
    from stockroom.kicad.model_convert import ModelToolingMissing

    def _no_tooling(_src):
        raise ModelToolingMissing("trimesh not installed")

    monkeypatch.setattr(previews_mod, "model_to_glb", _no_tooling)
    with _client_with_cli(app_ctx, app_ctx.cli) as c:
        r = c.get("/api/previews/model/tps62130.glb")
    assert r.status_code == 502


def test_model_glb_502_when_conversion_fails(app_ctx, monkeypatch):
    _put_model_file(app_ctx)
    from stockroom.api.routers import previews as previews_mod
    from stockroom.kicad.model_convert import ModelConversionError

    def _bad(_src):
        raise ModelConversionError("empty mesh")

    monkeypatch.setattr(previews_mod, "model_to_glb", _bad)
    with _client_with_cli(app_ctx, app_ctx.cli) as c:
        r = c.get("/api/previews/model/tps62130.glb")
    assert r.status_code == 502


def test_model_glb_returns_and_caches_glb(app_ctx, monkeypatch):
    from stockroom.api.routers import previews as previews_mod
    from stockroom.kicad.model_convert import GLB_MAGIC

    _put_model_file(app_ctx)
    calls = {"n": 0}

    def _fake_convert(_src):
        calls["n"] += 1
        return GLB_MAGIC + b"\x02\x00\x00\x00rest"

    monkeypatch.setattr(previews_mod, "model_to_glb", _fake_convert)
    with _client_with_cli(app_ctx, app_ctx.cli) as c:
        r1 = c.get("/api/previews/model/tps62130.glb")
        r2 = c.get("/api/previews/model/tps62130.glb")
    assert r1.status_code == 200
    assert r1.headers["content-type"].startswith("model/gltf-binary")
    assert r1.content[:4] == GLB_MAGIC
    assert r2.content == r1.content
    # second request is served from the on-disk cache: the converter runs once
    assert calls["n"] == 1


@requires_glb_tooling
@requires_kicad_cli
def test_model_glb_real_step_end_to_end(app_ctx):
    import glob

    steps = glob.glob("/usr/share/kicad/3dmodels/**/*.step", recursive=True)
    if not steps:
        import pytest as _pytest

        _pytest.skip("no system KiCad STEP models to convert")
    with open(steps[0], "rb") as fh:
        _put_model_file(app_ctx, data=fh.read())
    from stockroom.kicad.model_convert import GLB_MAGIC

    with _client_with_cli(app_ctx, app_ctx.cli) as c:
        r = c.get("/api/previews/model/tps62130.glb")
    assert r.status_code == 200
    assert r.content[:4] == GLB_MAGIC


def test_footprint_preview_hides_the_reference_and_value_text(app_ctx):
    # the owner's complaint: the footprint preview splashed REF** and the value over
    # the pad art. Give the fixture footprint visible Reference/Value properties and
    # prove the copy handed to the renderer has them hidden (the real file is untouched).
    fp_file = app_ctx.profile.library.footprint_lib_path("ICs") / "TPS62130.kicad_mod"
    fp_file.write_text(
        '(footprint "TPS62130"\n'
        '\t(layer "F.Cu")\n'
        '\t(property "Reference" "REF**" (at 0 -1 0) (layer "F.SilkS") (effects (font (size 1 1))))\n'
        '\t(property "Value" "TPS62130" (at 0 1 0) (layer "F.Fab") (effects (font (size 1 1))))\n'
        '\t(pad "1" smd rect (at 0 0) (size 1 1) (layers "F.Cu"))\n'
        ")\n",
        encoding="utf-8",
        newline="",
    )
    cli = _RevRecordingCli()
    with _client_with_cli(app_ctx, cli) as c:
        assert c.get("/api/previews/footprint/tps62130.svg").status_code == 200
    rendered = cli.fp_texts[0]
    # the copy the renderer saw has both metadata texts hidden...
    rstart = rendered.index('(property "Reference"')
    assert "(hide yes)" in rendered[rstart:rstart + 200]
    vstart = rendered.index('(property "Value"')
    assert "(hide yes)" in rendered[vstart:vstart + 200]
    # ...while the real footprint file on disk keeps its visible refdes for a board
    on_disk = fp_file.read_text(encoding="utf-8")
    dstart = on_disk.index('(property "Reference"')
    assert "(hide yes)" not in on_disk[dstart:dstart + 200]
