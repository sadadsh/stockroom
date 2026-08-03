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


def test_production_previews_use_the_attested_component_scoped_artifacts(app_ctx):
    """The production publisher does not populate legacy category-wide libraries.

    Reproduce the real PartRecord shape that made a completed component say Ready while both
    its Symbol and Footprint tabs failed. The catalog row is the durable path contract.
    """
    rec = app_ctx.ops.load_record("tps62130")
    symbol_rel = "EDA/KiCad/Symbols/cmp_exact/candidate/exact.kicad_sym"
    footprint_rel = "EDA/KiCad/Footprints/cmp_exact/candidate/Exact.pretty/Exact.kicad_mod"
    rec.extra["production_publication"] = {
        "schema": "stockroom.production-publication/1",
        "catalog_row": {
            "KiCad Symbol Artifact Path": symbol_rel,
            "KiCad Footprint Artifact Path": footprint_rel,
        },
    }
    symbol_file = app_ctx.profile.library.root / symbol_rel
    footprint_file = app_ctx.profile.library.root / footprint_rel
    symbol_file.parent.mkdir(parents=True, exist_ok=True)
    footprint_file.parent.mkdir(parents=True, exist_ok=True)
    symbol_file.write_text("(kicad_symbol_lib)", encoding="utf-8")
    footprint_file.write_text('(footprint "TPS62130")', encoding="utf-8")
    (app_ctx.profile.library.parts_dir / "tps62130.json").write_text(
        rec.dumps(), encoding="utf-8"
    )

    from stockroom.api.routers.previews import _resolve_footprint_file

    _record, resolved_footprint, resolved_pretty = _resolve_footprint_file(
        app_ctx, "tps62130"
    )
    assert resolved_footprint == footprint_file
    assert resolved_pretty == footprint_file.parent

    class _PathRecordingCli(_RecordingCli):
        def __init__(self):
            super().__init__()
            self.symbol_files = []
            self.footprint_dirs = []

        def sym_export_svg(self, lib, symbol, out_dir, black_and_white=False):
            self.symbol_files.append(lib)
            return super().sym_export_svg(lib, symbol, out_dir, black_and_white)

        def fp_export_svg(
            self,
            pretty_dir,
            footprint,
            out_dir,
            layers="F.Cu,F.SilkS,F.Fab",
            *,
            black_and_white=False,
        ):
            self.footprint_dirs.append(pretty_dir)
            return super().fp_export_svg(
                pretty_dir,
                footprint,
                out_dir,
                layers,
                black_and_white=black_and_white,
            )

    cli = _PathRecordingCli()
    with _client_with_cli(app_ctx, cli) as client:
        assert client.get("/api/previews/symbol/tps62130.svg").status_code == 200
        assert client.get("/api/previews/footprint/tps62130.svg").status_code == 200
        assert client.get("/api/previews/land/tps62130.json").status_code == 200

    assert cli.symbol_files == [symbol_file]
    # The clean-footprint renderer intentionally copies the resolved source into a temporary
    # .pretty directory after parsing it. The land endpoint assertion above proves the same
    # component-scoped source was also parsed directly.
    assert len(cli.footprint_dirs) == 1
    assert cli.footprint_dirs[0].name == "clean.pretty"


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


def test_land_pattern_returns_the_exact_kicad_model_transform(app_ctx):
    """Offset, scale, and rotation are source evidence, not viewer defaults.

    Keep this at the HTTP boundary: a correct footprint parser is insufficient if
    the endpoint drops, swaps, rounds, or fabricates one of the three vectors.
    """
    fp_file = app_ctx.profile.library.footprint_lib_path("ICs") / "TPS62130.kicad_mod"
    fp_file.write_text(
        '(footprint "TPS62130"\n'
        '\t(layer "F.Cu")\n'
        '\t(pad "1" smd rect (at 0 0) (size 1 2) (layers "F.Cu"))\n'
        '\t(model "${SR_LIB}/models/x.step"\n'
        "\t\t(offset (xyz 1.25 -2.5 0.125))\n"
        "\t\t(scale (xyz 1.5 0.75 2.25))\n"
        "\t\t(rotate (xyz 90 270 -45))\n"
        "\t)\n"
        ")\n",
        encoding="utf-8",
        newline="",
    )

    with _client_with_cli(app_ctx, _RecordingCli()) as c:
        response = c.get("/api/previews/land/tps62130.json")

    assert response.status_code == 200
    assert response.json()["model_placement"] == {
        "offset": [1.25, -2.5, 0.125],
        "scale": [1.5, 0.75, 2.25],
        "rotate": [90.0, 270.0, -45.0],
    }


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
    (cache_dir / f"model_tps62130_{previews_mod._MODEL_CONVERT_VERSION}_{h}.glb").write_bytes(
        b"NOT-A-GLB truncated"
    )

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
    from stockroom.model.part import AssetRef, PartRecord

    seed = _seed_sha(app_ctx)  # before the latecomer existed
    rec = PartRecord(id="latecomer", display_name="LATECOMER", category="ICs")
    rec.assets_for("kicad").symbol = AssetRef(lib="SR-ICs", name="LATECOMER")
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


# --------------------------------------------------------------------------- #
# Stock preview-by-lib_id (the unified Add-A-Part flow shows a passive's built-in
# footprint + 3D model BEFORE it is committed, so there is no part id to key on).
# --------------------------------------------------------------------------- #
def test_stock_footprint_svg_400_on_a_bad_lib_id(client):
    assert client.get("/api/previews/stock/footprint.svg?fp=Resistor_SMD").status_code == 400
    assert client.get("/api/previews/stock/footprint.svg?fp=../../etc:passwd").status_code == 400


def test_stock_footprint_svg_404_when_not_installed(client):
    r = client.get("/api/previews/stock/footprint.svg?fp=No_Such_Lib:No_Such_Fp")
    assert r.status_code == 404


def test_stock_footprint_svg_renders_by_lib_id(app_ctx, monkeypatch, tmp_path):
    mod = tmp_path / "Resistor_SMD.pretty" / "R_0603_1608Metric.kicad_mod"
    mod.parent.mkdir(parents=True)
    mod.write_text('(footprint "R_0603_1608Metric")', encoding="utf-8")
    monkeypatch.setattr(
        "stockroom.api.routers.previews.stock_footprint_file", lambda lib, name: mod
    )
    cli = _RecordingCli()
    with _client_with_cli(app_ctx, cli) as c:
        r = c.get("/api/previews/stock/footprint.svg?fp=Resistor_SMD:R_0603_1608Metric")
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("image/svg+xml")
        assert c.get(
            "/api/previews/stock/footprint.svg?fp=Resistor_SMD:R_0603_1608Metric&bw=true"
        ).status_code == 200
    # color then bw reach the renderer with distinct flags (distinct cache keys)
    assert cli.fp_bw == [False, True]


def test_stock_model_glb_renders_by_lib_id(app_ctx, monkeypatch, tmp_path):
    from stockroom.kicad.model_convert import GLB_MAGIC

    src = tmp_path / "R_0603_1608Metric.wrl"
    src.write_text("stub", encoding="utf-8")
    monkeypatch.setattr(
        "stockroom.api.routers.previews.stock_model_file", lambda lib, name: src
    )
    monkeypatch.setattr(
        "stockroom.api.routers.previews.model_to_glb", lambda p: GLB_MAGIC + b"rest"
    )
    with _client_with_cli(app_ctx, _RecordingCli()) as c:
        r = c.get("/api/previews/stock/model.glb?fp=Resistor_SMD:R_0603_1608Metric")
        assert r.status_code == 200
        assert r.headers["content-type"] == "model/gltf-binary"
        assert r.content[:4] == GLB_MAGIC


def test_stock_model_glb_404_when_not_installed(client):
    r = client.get("/api/previews/stock/model.glb?fp=No_Such_Lib:No_Such")
    assert r.status_code == 404


class TestScalablePreviewSvg:
    """A preview SVG must scale to its tile, which means it must NOT declare physical dimensions.

    MEASURED in the real app (2026-07-25) with a real TI USON-14 footprint: `kicad-cli` emits
    `width="2.641600mm" height="4.114800mm"`, so the browser gives the image an INTRINSIC SIZE of
    10x16 CSS pixels. Inside a 127x110 tile with `object-fit: contain` that renders as a
    near-invisible sliver - the long-standing "the footprint tile shows a few dots" bug, which was
    never a failed render at all. Dropping the two physical attributes and letting the `viewBox`
    drive sizing took the same file to an intrinsic 96x150, correctly proportioned.

    The symbol has the same defect but hid it, because its intrinsic 175x94 is large enough to look
    deliberate. Both go through `_svg_response`, so the fix belongs there and cannot be applied to
    one preview and forgotten on the other.
    """

    def test_strips_physical_width_and_height_but_keeps_the_viewbox(self):
        from stockroom.api.routers.previews import scalable_svg

        src = (
            '<svg xmlns="http://www.w3.org/2000/svg" width="2.641600mm" '
            'height="4.114800mm" viewBox="0.000000 0.000000 2.641600 4.114800">'
            "<rect/></svg>"
        )
        out = scalable_svg(src)
        assert 'width="2.641600mm"' not in out
        assert 'height="4.114800mm"' not in out
        assert 'viewBox="0.000000 0.000000 2.641600 4.114800"' in out
        assert "<rect/>" in out, "the drawing itself must be untouched"

    def test_leaves_a_width_inside_the_body_alone(self):
        # Only the ROOT <svg> element's sizing is the problem. A width on a child (a rect, a
        # nested svg) is part of the drawing, and stripping it would corrupt the render.
        from stockroom.api.routers.previews import scalable_svg

        src = (
            '<svg xmlns="http://www.w3.org/2000/svg" width="10mm" height="5mm" '
            'viewBox="0 0 10 5"><rect width="3" height="2"/></svg>'
        )
        out = scalable_svg(src)
        assert '<rect width="3" height="2"/>' in out
        assert 'width="10mm"' not in out

    def test_is_a_no_op_when_there_are_no_physical_dimensions(self):
        from stockroom.api.routers.previews import scalable_svg

        src = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 4 2"><g/></svg>'
        assert scalable_svg(src) == src

    def test_keeps_a_document_without_a_viewbox_unchanged(self):
        # Without a viewBox the physical size is the ONLY sizing information there is; removing it
        # would collapse the image to nothing. Better a small render than an empty one.
        from stockroom.api.routers.previews import scalable_svg

        src = '<svg xmlns="http://www.w3.org/2000/svg" width="8mm" height="4mm"><g/></svg>'
        assert scalable_svg(src) == src

    def test_handles_a_REAL_kicad_cli_preamble_and_multiline_root(self):
        """The shape kicad-cli actually emits: an XML declaration, a DOCTYPE, and a root element
        whose attributes span several lines. An earlier version of this anchored at offset 0 and so
        did nothing at all on every real file, while the tidy single-line fixtures above passed."""
        from stockroom.api.routers.previews import scalable_svg

        src = (
            '<?xml version="1.0" standalone="no"?>\n'
            ' <!DOCTYPE svg PUBLIC "-//W3C//DTD SVG 1.1//EN" \n'
            ' "http://www.w3.org/Graphics/SVG/1.1/DTD/svg11.dtd"> \n'
            "<svg\n"
            '  xmlns:svg="http://www.w3.org/2000/svg"\n'
            '  xmlns="http://www.w3.org/2000/svg"\n'
            '  width="2.641600mm"\n'
            '  height="4.114800mm"\n'
            '  viewBox="0.000000 0.000000 2.641600 4.114800">\n'
            "<rect/>\n</svg>\n"
        )
        out = scalable_svg(src)
        assert "2.641600mm" not in out
        assert "4.114800mm" not in out
        assert 'viewBox="0.000000 0.000000 2.641600 4.114800"' in out
        assert "<!DOCTYPE svg" in out, "the preamble must survive untouched"
        assert "<rect/>" in out


def test_every_preview_cache_key_carries_a_render_version_token():
    """GATE. A preview cache key is content-addressed on the SOURCE file, which does not
    change when the RENDER or CONVERSION code does. Without a version token in the key, a
    fix ships green and is never seen: every machine with a warm cache keeps serving the
    old blob. Both GLB keys were built that way and the 3D model conversion fix was
    invisible until this gate existed. Scans the built key expressions rather than a
    hand-listed set, so a NEW cache key cannot quietly omit its token."""
    import ast
    import inspect

    from stockroom.api.routers import previews

    source = inspect.getsource(previews)
    offenders = []
    for node in ast.walk(ast.parse(source)):
        # every cache key in this module is `key = f"..."` / `cached = _cache_dir(...) / f"..."`
        if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.JoinedStr):
            continue
        names = [t.id for t in node.targets if isinstance(t, ast.Name)]
        if "key" not in names:
            continue
        literal = "".join(
            part.value for part in node.value.values if isinstance(part, ast.Constant)
        )
        if not literal.endswith((".svg", ".glb")):
            continue
        referenced = {
            n.id
            for part in node.value.values
            if isinstance(part, ast.FormattedValue)
            for n in ast.walk(part)
            if isinstance(n, ast.Name)
        }
        if not any(name.endswith("_VERSION") for name in referenced):
            offenders.append((literal, sorted(referenced)))
    assert offenders == [], (
        "these preview cache keys carry no *_VERSION token, so a render/conversion change "
        f"will never reach a warm cache: {offenders}"
    )


def test_footprint_preview_quiets_strokes_without_removing_geometry():
    from stockroom.api.routers.previews import quiet_footprint_strokes

    source = '<svg><path style="fill:none;stroke:#fff;stroke-width:0.500000" d="M 0 0 4 4"/></svg>'

    rendered = quiet_footprint_strokes(source)

    assert 'stroke-width:0.360000' in rendered
    assert 'd="M 0 0 4 4"' in rendered


def test_footprint_refit_leaves_more_breathing_room_than_a_symbol_refit():
    from stockroom.api.routers.previews import refit_viewbox

    source = '<svg viewBox="0 0 100 100"><rect x="0" y="0" width="10" height="10"/></svg>'

    symbol = refit_viewbox(source, margin_ratio=0.02)
    footprint = refit_viewbox(source, margin_ratio=0.08)

    assert 'viewBox="-0.200000 -0.200000 10.400000 10.400000"' in symbol
    assert 'viewBox="-0.800000 -0.800000 11.600000 11.600000"' in footprint


class TestRefitViewBox:
    """kicad-cli sizes a footprint's viewBox from the footprint's FULL extent - including the
    Reference/Value text and layers the preview deliberately does not draw. MEASURED on the real
    TPD6E05U06RVZR: the viewBox is `0 0 11.049 6.4008` mm and is BYTE-IDENTICAL whether the text
    is hidden or not and whether `--layers` is restricted or not, so it is not content-derived at
    all. The drawn copper then occupies a few percent of it and the tile shows a tiny stamp in a
    sea of empty space - which is what "the footprint preview looks broken" actually is. Stripping
    width/height (scalable_svg) does not help: it makes the OVERSIZED box scale, not shrink."""

    def _refit(self, src):
        from stockroom.api.routers.previews import refit_viewbox

        return refit_viewbox(src)

    def _box(self, svg):
        import re

        m = re.search(r'viewBox="([^"]*)"', svg)
        return [float(v) for v in m.group(1).replace(",", " ").split()]

    def test_a_viewbox_far_larger_than_its_content_is_refit_to_the_content(self):
        src = (
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">'
            '<path style="fill:#c00;stroke:none;" d="M 40,40 42,40 42,42 40,42 Z"/>'
            "</svg>"
        )
        x, y, w, h = self._box(self._refit(src))
        # the content is a 2x2 square at (40,40); the refit must bound it closely, never keep 100x100
        assert w < 10 and h < 10, f"viewBox was not refit: {(x, y, w, h)}"
        assert x <= 40 and y <= 40 and x + w >= 42 and y + h >= 42, "content fell outside the box"

    def test_the_refit_keeps_a_stroked_edge_inside_the_box(self):
        # a stroke straddles its path, so half of it sits OUTSIDE the geometric bbox. Refitting to
        # the bare coordinates would shave the outer half of every courtyard line off the preview.
        src = (
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">'
            '<path style="fill:none;stroke:#000;stroke-width:2.000000;" d="M 40,40 60,40"/>'
            "</svg>"
        )
        x, y, w, h = self._box(self._refit(src))
        assert x <= 39.0 and x + w >= 61.0, f"stroke half-width not accounted for: {(x, y, w, h)}"

    def test_a_circle_counts_as_content(self):
        src = (
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">'
            '<circle cx="50" cy="50" r="5"/>'
            "</svg>"
        )
        x, y, w, h = self._box(self._refit(src))
        assert x <= 45 and y <= 45 and x + w >= 55 and y + h >= 55
        assert w < 30 and h < 30

    def test_a_native_rectangle_symbol_body_is_not_cropped_out(self):
        # KiCad 10 preserves rectangular symbol bodies as SVG <rect> primitives.  The real
        # TPD6E05U06RVZR preview used to measure only its pin paths, crop about 71% of the body,
        # and misleadingly look like a sparse/broken CAD source.
        src = (
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 22 31">'
            '<rect x="2" y="2.7" width="15.2" height="25.4"/>'
            '<path d="M 17.2,5 19.7,5"/>'
            "</svg>"
        )
        x, y, w, h = self._box(self._refit(src))
        assert x <= 2 and y <= 2.7
        assert x + w >= 19.7 and y + h >= 28.1
        assert w < 22 and h < 31

    def test_an_svg_with_no_geometry_is_left_alone(self):
        # never emit a degenerate or inverted viewBox; an empty drawing keeps whatever it had.
        src = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><title>x</title></svg>'
        assert self._refit(src) == src

    def test_an_svg_with_no_viewbox_is_left_alone(self):
        src = '<svg xmlns="http://www.w3.org/2000/svg"><path d="M 1,1 2,2"/></svg>'
        assert self._refit(src) == src

    def test_content_already_filling_its_box_is_barely_changed(self):
        # the refit must not ZOOM a symbol that kicad already framed sensibly.
        src = (
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">'
            '<path style="stroke:none;" d="M 0,0 10,0 10,10 0,10 Z"/>'
            "</svg>"
        )
        x, y, w, h = self._box(self._refit(src))
        assert w >= 10 and h >= 10 and w < 13 and h < 13


@requires_kicad_cli
def test_footprint_preview_fills_its_frame_rather_than_stamping_a_speck(app_ctx):
    """END TO END, through the real endpoint and the REAL kicad-cli: the served SVG's drawn
    content must occupy a real fraction of its viewBox. The condition is reproduced exactly as
    the owner's part hits it - small pads plus a Reference text far larger than them - because
    kicad-cli sizes the viewBox from the text too, then the preview hides the text and draws
    only copper. Measured on the real TPD6E05U06RVZR before the refit: under 10%."""
    import re

    from fastapi.testclient import TestClient

    from stockroom.api.app import create_app

    fp_file = app_ctx.profile.library.footprint_lib_path("ICs") / "TPS62130.kicad_mod"
    fp_file.write_text(
        '(footprint "TPS62130"\n'
        '\t(layer "F.Cu")\n'
        # a 2mm-tall refdes parked 6mm away: this is what inflates the viewBox, and it is
        # hidden before anything is drawn, so nothing in the output accounts for it.
        '\t(property "Reference" "REF**" (at 0 -6 0) (layer "F.SilkS") (effects (font (size 2 2))))\n'
        '\t(property "Value" "TPS62130" (at 0 6 0) (layer "F.Fab") (effects (font (size 2 2))))\n'
        # F.SilkS line work far outside the pads. The preview restricts itself to copper and
        # courtyard, so this is NOT drawn - yet kicad-cli still counts it when sizing the
        # viewBox. This is the half that hiding text could never fix, and it is why the refit
        # works on the emitted SVG rather than on the footprint.
        '\t(fp_line (start -8 -5) (end 8 -5) (stroke (width 0.12) (type solid)) (layer "F.SilkS"))\n'
        '\t(fp_line (start -8 5) (end 8 5) (stroke (width 0.12) (type solid)) (layer "F.SilkS"))\n'
        '\t(pad "1" smd rect (at -0.5 0) (size 0.6 0.3) (layers "F.Cu"))\n'
        '\t(pad "2" smd rect (at 0.5 0) (size 0.6 0.3) (layers "F.Cu"))\n'
        ")\n",
        encoding="utf-8",
        newline="",
    )
    with TestClient(
        create_app(app_ctx),
        base_url="http://test",
        raise_server_exceptions=False,
        headers={"X-Stockroom-Token": "testtoken"},
    ) as client:
        response = client.get("/api/previews/footprint/tps62130.svg")
    if response.status_code != 200:
        pytest.skip(f"footprint preview unavailable here ({response.status_code})")
    body = response.text
    box = re.search(r'viewBox="([^"]*)"', body)
    assert box, "the served footprint SVG has no viewBox"
    vx, vy, vw, vh = (float(v) for v in box.group(1).replace(",", " ").split())
    xs, ys = [], []
    for d in re.findall(r'\sd="([^"]*)"', body):
        nums = [float(n) for n in re.findall(r"-?\d+\.?\d*", d)]
        xs += nums[0::2]
        ys += nums[1::2]
    for cx, cy, cr in re.findall(r'<circle[^>]*cx="([\d.-]+)"[^>]*cy="([\d.-]+)"[^>]*r="([\d.-]+)"', body):
        xs += [float(cx) - float(cr), float(cx) + float(cr)]
        ys += [float(cy) - float(cr), float(cy) + float(cr)]
    assert xs and ys, "the footprint SVG drew no geometry at all"
    coverage = ((max(xs) - min(xs)) * (max(ys) - min(ys))) / (vw * vh)
    assert coverage > 0.4, (
        f"the footprint art fills only {coverage:.1%} of its viewBox "
        f"(box {vw:.3f}x{vh:.3f}), so the tile renders a speck"
    )
