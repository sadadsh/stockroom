"""Symbol/footprint/3D previews rendered by the user's own kicad-cli (SVG) and
trimesh (STEP/WRL → GLB), cached on disk by content hash so a repeat view never
re-renders (spec sections 2.2, 3.4). The backend never re-implements KiCad rendering
or 3D tessellation; it shells out to the tools. SVG tints happen client-side, so the
viewer requests the ?bw=true monochrome variant and re-colours it to the theme."""

from __future__ import annotations

import hashlib
import json
import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response

from stockroom.api.errors import ApiError
from stockroom.kicad.footprint import Footprint
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
            out_dir = Path(td) / "out"
            out_dir.mkdir(parents=True, exist_ok=True)
            # Render a copy with the Reference (REF**) and Value text hidden so the
            # preview shows clean pad/silk art, not the designator splashed over it.
            # The real footprint file is never touched (a board needs its refdes). A
            # footprint that will not parse falls back to the raw export (honest
            # degradation: a preview with a refdes beats no preview).
            render_pretty, render_name = pretty, rec.footprint.name
            try:
                fp = Footprint.load(fp_file)
                fp.hide_field("Reference")
                fp.hide_field("Value")
                clean_pretty = Path(td) / f"{rec.category}.pretty"
                clean_pretty.mkdir(parents=True, exist_ok=True)
                (clean_pretty / f"{rec.footprint.name}.kicad_mod").write_text(
                    fp.serialize(), encoding="utf-8", newline=""
                )
                render_pretty = clean_pretty
            except Exception:  # noqa: BLE001 - unparseable footprint: raw preview, not a 500
                pass
            svg = ctx.cli.fp_export_svg(
                render_pretty, render_name, out_dir, black_and_white=bw
            )
            text = Path(svg).read_text(encoding="utf-8")
        cached.write_text(text, encoding="utf-8")
        return _svg_response(text)

    @r.get("/model/{part_id}.glb")
    def model_glb(request: Request, part_id: str) -> Response:
        ctx = request.app.state.ctx
        if ctx.index.get(part_id) is None:
            raise FileNotFoundError(f"no such part: {part_id}")
        rec = ctx.ops.load_record(part_id)
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
