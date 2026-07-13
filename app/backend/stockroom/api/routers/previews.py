"""Symbol/footprint/3D previews rendered by the user's own kicad-cli (SVG) and
trimesh (STEP/WRL → GLB), cached on disk by content hash so a repeat view never
re-renders (spec sections 2.2, 3.4). The backend never re-implements KiCad rendering
or 3D tessellation; it shells out to the tools. SVG tints happen client-side, so the
viewer requests the ?bw=true monochrome variant and re-colours it to the theme."""

from __future__ import annotations

import hashlib
import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response

from stockroom.api.errors import ApiError
from stockroom.kicad.model_convert import (
    ModelConversionError,
    ModelToolingMissing,
    model_to_glb,
)


def _hash_file(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()[:16]


def _cache_dir(ctx) -> Path:
    d = ctx.libraries_root.parent / ".stockroom-previews"
    d.mkdir(parents=True, exist_ok=True)
    return d


def previews_router(require_token) -> APIRouter:
    r = APIRouter(prefix="/api/previews", dependencies=[Depends(require_token)])

    def _svg_response(text: str) -> Response:
        return Response(content=text, media_type="image/svg+xml")

    @r.get("/symbol/{part_id}.svg")
    def symbol_svg(request: Request, part_id: str, bw: bool = False) -> Response:
        ctx = request.app.state.ctx
        if ctx.index.get(part_id) is None:
            raise FileNotFoundError(f"no such part: {part_id}")
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
    def footprint_svg(request: Request, part_id: str, bw: bool = False) -> Response:
        ctx = request.app.state.ctx
        if ctx.index.get(part_id) is None:
            raise FileNotFoundError(f"no such part: {part_id}")
        rec = ctx.ops.load_record(part_id)
        if rec.footprint is None or not rec.footprint.name:
            raise FileNotFoundError(f"part {part_id} has no footprint")
        pretty = ctx.profile.library.footprint_lib_path(rec.category)
        if not pretty.exists():
            raise FileNotFoundError(f"footprint library missing for {rec.category}")
        variant = "_bw" if bw else ""
        key = f"fp_{part_id}_{rec.footprint.name}{variant}.svg"
        cached = _cache_dir(ctx) / key
        if cached.exists():
            return _svg_response(cached.read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as td:
            svg = ctx.cli.fp_export_svg(
                pretty, rec.footprint.name, Path(td), black_and_white=bw
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
            return Response(
                content=cached.read_bytes(), media_type="model/gltf-binary"
            )
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
