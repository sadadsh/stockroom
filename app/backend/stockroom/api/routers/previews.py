"""Symbol/footprint/3D previews rendered by the user's own kicad-cli (SVG) and
trimesh (STEP/WRL → GLB), cached on disk by content hash so a repeat view never
re-renders (spec sections 2.2, 3.4). The backend never re-implements KiCad rendering
or 3D tessellation; it shells out to the tools. SVG tints happen client-side, so the
viewer requests the ?bw=true monochrome variant and re-colours it to the theme."""

from __future__ import annotations

import hashlib
import json
import re
import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response

from stockroom.api.errors import ApiError
from stockroom.kicad.footprint import Footprint
from stockroom.kicad.stock import (
    stock_footprint_file,
    stock_model_file,
    stock_symbol_lib_file,
)
from stockroom.kicad.model_convert import (
    GLB_MAGIC,
    ModelConversionError,
    ModelToolingMissing,
    model_to_glb,
)
from stockroom.vcs.repo import GitError


def _hash_file(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()[:16]


def _cache_dir(ctx) -> Path:
    d = ctx.libraries_root.parent / ".stockroom-previews"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _svg_at_rev(ctx, part_id: str, kind: str, rev: str, bw: bool) -> str:
    """Render this part's symbol or footprint SVG as it stood at revision `rev`, read
    from git blobs with no working-tree checkout (spec section 9), so the timeline can
    overlay an old geometry against the current one. The category and asset name are
    taken from the part record AT that rev (both can change over time). A rev is
    content-immutable, so it alone content-addresses the cache. A malformed rev (not a
    real object name) is a client error (400), not a git-backend outage (503)."""
    try:
        return _render_at_rev(ctx, part_id, kind, rev, bw)
    except GitError as exc:
        raise ValueError(f"unknown revision: {rev}") from exc


def _render_at_rev(ctx, part_id: str, kind: str, rev: str, bw: bool) -> str:
    rec_text = ctx.repo.show_file(rev, ctx.profile.library.parts_dir / f"{part_id}.json")
    if not rec_text:
        raise FileNotFoundError(f"part {part_id} did not exist at {rev}")
    rec = json.loads(rec_text)
    category = rec.get("category")
    variant = "_bw" if bw else ""
    cached = _cache_dir(ctx) / f"{kind}_{part_id}_{rev}{variant}.svg"
    if cached.exists():
        return cached.read_text(encoding="utf-8")
    with tempfile.TemporaryDirectory() as td:
        tdp = Path(td)
        if kind == "sym":
            name = (rec.get("symbol") or {}).get("name")
            if not name or not category:
                raise FileNotFoundError(f"part {part_id} had no symbol at {rev}")
            lib_text = ctx.repo.show_file(rev, ctx.profile.library.symbol_lib_path(category))
            if lib_text is None:
                raise FileNotFoundError(f"symbol library missing at {rev}")
            hist_lib = tdp / "hist.kicad_sym"
            hist_lib.write_text(lib_text, encoding="utf-8")
            svgs = ctx.cli.sym_export_svg(hist_lib, name, tdp, black_and_white=bw)
            text = Path(svgs[0]).read_text(encoding="utf-8")
        else:  # footprint
            name = (rec.get("footprint") or {}).get("name")
            if not name or not category:
                raise FileNotFoundError(f"part {part_id} had no footprint at {rev}")
            fp_rel = ctx.profile.library.footprint_lib_path(category) / f"{name}.kicad_mod"
            fp_text = ctx.repo.show_file(rev, fp_rel)
            if fp_text is None:
                raise FileNotFoundError(f"footprint file missing at {rev}")
            hist_pretty = tdp / "hist.pretty"
            hist_pretty.mkdir()
            (hist_pretty / f"{name}.kicad_mod").write_text(fp_text, encoding="utf-8")
            svg = ctx.cli.fp_export_svg(hist_pretty, name, tdp, black_and_white=bw)
            text = Path(svg).read_text(encoding="utf-8")
    cached.write_text(text, encoding="utf-8")
    return text


_FP_TOKEN = re.compile(r"^[A-Za-z0-9_.\-]+$")


def _split_lib_id(fp: str) -> tuple[str, str]:
    """Parse a "<lib>:<name>" footprint lib_id into (lib, name), each restricted to the
    KiCad-safe token charset so it can never traverse out of the stock library dir."""
    lib, sep, name = (fp or "").partition(":")
    if not sep or not _FP_TOKEN.match(lib) or not _FP_TOKEN.match(name):
        raise ApiError(400, f"not a valid footprint lib_id: {fp!r}")
    return lib, name


def _clean_footprint_svg(cli, fp_file: Path, name: str, bw: bool, td: Path) -> str:
    """Render a footprint's SVG with the Reference (REF**) and Value text hidden so the
    preview shows clean pad/silk art, not the designator splashed over it. The source
    .kicad_mod is never touched. A footprint that will not parse falls back to the raw
    export (honest degradation: a preview with a refdes beats no preview)."""
    out_dir = td / "out"
    out_dir.mkdir(parents=True, exist_ok=True)
    render_pretty = fp_file.parent
    try:
        fp = Footprint.load(fp_file)
        fp.hide_field("Reference")
        fp.hide_field("Value")
        fp.hide_reference_texts()  # the fab-layer ${REFERENCE} text hide_field misses
        clean_pretty = td / "clean.pretty"
        clean_pretty.mkdir(parents=True, exist_ok=True)
        (clean_pretty / f"{name}.kicad_mod").write_text(
            fp.serialize(), encoding="utf-8", newline=""
        )
        render_pretty = clean_pretty
    except Exception:  # noqa: BLE001 - unparseable footprint: raw preview, not a 500
        pass
    svg = cli.fp_export_svg(render_pretty, name, out_dir, black_and_white=bw)
    return Path(svg).read_text(encoding="utf-8")


def previews_router(require_token) -> APIRouter:
    r = APIRouter(prefix="/api/previews", dependencies=[Depends(require_token)])

    def _svg_response(text: str) -> Response:
        return Response(content=text, media_type="image/svg+xml")

    @r.get("/symbol/{part_id}.svg")
    def symbol_svg(request: Request, part_id: str, bw: bool = False, rev: str = "") -> Response:
        ctx = request.app.state.ctx
        if ctx.index.get(part_id) is None:
            raise FileNotFoundError(f"no such part: {part_id}")
        if rev:
            return _svg_response(_svg_at_rev(ctx, part_id, "sym", rev, bw))
        rec = ctx.ops.load_record(part_id)
        if rec.symbol is None or not rec.symbol.name:
            raise FileNotFoundError(f"part {part_id} has no symbol")
        # A passive references a KiCad STOCK symbol lib (Device:R) with no owned file,
        # so render it from the installed KiCad libraries, not the category lib.
        if rec.passive:
            lib = stock_symbol_lib_file(rec.symbol.lib)
            if lib is None:
                raise FileNotFoundError(
                    f"KiCad stock symbol library {rec.symbol.lib} is not installed"
                )
        else:
            lib = ctx.profile.library.symbol_lib_path(rec.category)
            if not lib.exists():
                raise FileNotFoundError(f"symbol library missing for {rec.category}")
        variant = "_bw" if bw else ""
        key = f"sym_{part_id}_{_hash_file(lib)}{variant}.svg"
        cached = _cache_dir(ctx) / key
        if cached.exists():
            return _svg_response(cached.read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as td:
            svgs = ctx.cli.sym_export_svg(
                lib, rec.symbol.name, Path(td), black_and_white=bw
            )
            text = Path(svgs[0]).read_text(encoding="utf-8")
        cached.write_text(text, encoding="utf-8")
        return _svg_response(text)

    @r.get("/footprint/{part_id}.svg")
    def footprint_svg(request: Request, part_id: str, bw: bool = False, rev: str = "") -> Response:
        ctx = request.app.state.ctx
        if ctx.index.get(part_id) is None:
            raise FileNotFoundError(f"no such part: {part_id}")
        if rev:
            return _svg_response(_svg_at_rev(ctx, part_id, "fp", rev, bw))
        rec = ctx.ops.load_record(part_id)
        if rec.footprint is None or not rec.footprint.name:
            raise FileNotFoundError(f"part {part_id} has no footprint")
        # A passive references a KiCad STOCK footprint with no owned file.
        if rec.passive:
            fp_file = stock_footprint_file(rec.footprint.lib, rec.footprint.name)
            if fp_file is None:
                raise FileNotFoundError(
                    f"KiCad stock footprint {rec.footprint.lib}:{rec.footprint.name} "
                    "is not installed"
                )
            pretty = fp_file.parent
        else:
            pretty = ctx.profile.library.footprint_lib_path(rec.category)
            if not pretty.exists():
                raise FileNotFoundError(f"footprint library missing for {rec.category}")
            fp_file = pretty / f"{rec.footprint.name}.kicad_mod"
            if not fp_file.exists():
                raise FileNotFoundError(f"footprint file missing: {rec.footprint.name}")
        variant = "_bw" if bw else ""
        # Content-address the key (like the symbol + model endpoints) so an edited
        # footprint re-renders and two profiles sharing a part_id + footprint name in
        # the one shared cache dir never serve each other's geometry.
        key = f"fp_{part_id}_{_hash_file(fp_file)}{variant}.svg"
        cached = _cache_dir(ctx) / key
        if cached.exists():
            return _svg_response(cached.read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as td:
            text = _clean_footprint_svg(ctx.cli, fp_file, rec.footprint.name, bw, Path(td))
        cached.write_text(text, encoding="utf-8")
        return _svg_response(text)

    @r.get("/stock/footprint.svg")
    def stock_footprint_svg(request: Request, fp: str, bw: bool = False) -> Response:
        """Render a KiCad STOCK footprint by its lib_id (e.g. fp=Resistor_SMD:R_0603_1608Metric)
        with no committed part, so the unified Add-A-Part flow can show a passive's built-in
        footprint before it is added. A lib_id that is not installed is a 404."""
        ctx = request.app.state.ctx
        lib, name = _split_lib_id(fp)
        fp_file = stock_footprint_file(lib, name)
        if fp_file is None:
            raise FileNotFoundError(f"KiCad stock footprint {lib}:{name} is not installed")
        variant = "_bw" if bw else ""
        key = f"stockfp_{lib}_{name}_{_hash_file(fp_file)}{variant}.svg"
        cached = _cache_dir(ctx) / key
        if cached.exists():
            return _svg_response(cached.read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as td:
            text = _clean_footprint_svg(ctx.cli, fp_file, name, bw, Path(td))
        cached.write_text(text, encoding="utf-8")
        return _svg_response(text)

    @r.get("/stock/model.glb")
    def stock_model_glb(request: Request, fp: str) -> Response:
        """Convert a KiCad STOCK 3D model by its footprint lib_id to a GLB with no committed
        part, so the Add-A-Part flow can show a passive's built-in 3D model before it is
        added. A lib_id with no installed stock model is a 404; absent 3D tooling is a 502."""
        ctx = request.app.state.ctx
        lib, name = _split_lib_id(fp)
        src = stock_model_file(lib, name)
        if src is None:
            raise FileNotFoundError(f"KiCad stock 3D model for {lib}:{name} is not installed")
        key = f"stockmodel_{lib}_{name}_{_hash_file(src)}.glb"
        cached = _cache_dir(ctx) / key
        if cached.exists():
            data = cached.read_bytes()
            if data[:4] == GLB_MAGIC:
                return Response(content=data, media_type="model/gltf-binary")
        try:
            data = model_to_glb(src)
        except ModelToolingMissing as exc:
            raise ApiError(502, str(exc)) from exc
        except ModelConversionError as exc:
            raise ApiError(502, str(exc)) from exc
        cached.write_bytes(data)
        return Response(content=data, media_type="model/gltf-binary")

    @r.get("/model/{part_id}.glb")
    def model_glb(request: Request, part_id: str) -> Response:
        ctx = request.app.state.ctx
        if ctx.index.get(part_id) is None:
            raise FileNotFoundError(f"no such part: {part_id}")
        rec = ctx.ops.load_record(part_id)
        # A passive inherits the stock footprint's own 3D model (no owned model.file):
        # resolve it from the installed KiCad libraries keyed on the footprint lib_id.
        if rec.passive:
            if rec.footprint is None or not rec.footprint.name:
                raise FileNotFoundError(f"part {part_id} has no footprint for a 3D model")
            src = stock_model_file(rec.footprint.lib, rec.footprint.name)
            if src is None:
                raise FileNotFoundError(
                    f"KiCad stock 3D model for {rec.footprint.lib}:{rec.footprint.name} "
                    "is not installed"
                )
        else:
            if rec.model is None or not rec.model.file:
                raise FileNotFoundError(f"part {part_id} has no 3D model")
            # model.file is stored relative to the profile library root (same convention
            # the mutation engine and the doctor use).
            src = ctx.profile.library.root / rec.model.file
            if not src.exists():
                raise FileNotFoundError(f"3D model file is missing: {rec.model.file}")
        key = f"model_{part_id}_{_hash_file(src)}.glb"
        cached = _cache_dir(ctx) / key
        if cached.exists():
            data = cached.read_bytes()
            # only serve a cache entry that is a real GLB; a truncated write (killed
            # mid-write, disk full) is treated as a miss and re-converted, never sent
            # as a 200 the three.js loader would fail to parse into a blank canvas.
            if data[:4] == GLB_MAGIC:
                return Response(content=data, media_type="model/gltf-binary")
        try:
            data = model_to_glb(src)
        except ModelToolingMissing as exc:
            # optional stack absent: an honest 502, never a crash; the SVG previews
            # still work and the frontend degrades to a "3D preview unavailable" note.
            raise ApiError(502, str(exc)) from exc
        except ModelConversionError as exc:
            raise ApiError(502, str(exc)) from exc
        cached.write_bytes(data)
        return Response(content=data, media_type="model/gltf-binary")

    return r
