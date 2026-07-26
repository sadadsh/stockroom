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
from stockroom.kicad.symbol_lib import SymbolLib
from stockroom.model.part import PartRecord
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
    # Parse through PartRecord rather than poking the raw dict: a blob from git history may
    # predate the per-EDA cutover, and from_dict folds those legacy flat fields into the
    # per-tool map. Reading `rec["symbol"]` here would render nothing for every part added
    # before the cutover, which is most of the owner's history.
    rec = PartRecord.from_dict(json.loads(rec_text))
    kicad = rec.assets_for("kicad")
    category = rec.category
    variant = "_bw" if bw else ""
    cached = _cache_dir(ctx) / f"{kind}_{part_id}_{rev}{variant}.svg"
    if cached.exists():
        return cached.read_text(encoding="utf-8")
    with tempfile.TemporaryDirectory() as td:
        tdp = Path(td)
        if kind == "sym":
            name = kicad.symbol.name if kicad.symbol else ""
            if not name or not category:
                raise FileNotFoundError(f"part {part_id} had no symbol at {rev}")
            lib_text = ctx.repo.show_file(rev, ctx.profile.library.symbol_lib_path(category))
            if lib_text is None:
                raise FileNotFoundError(f"symbol library missing at {rev}")
            hist_lib = tdp / "hist.kicad_sym"
            hist_lib.write_text(lib_text, encoding="utf-8")
            svgs = _clean_symbol_svg(ctx.cli, hist_lib, name, bw, tdp)
            text = Path(svgs[0]).read_text(encoding="utf-8")
        else:  # footprint
            name = kicad.footprint.name if kicad.footprint else ""
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


# Bump when the footprint render changes (layers, hidden text, ...): the SVG cache is keyed by
# the .kicad_mod file hash, which does NOT change when the RENDER code does, so a stale blob would
# be served forever without this token. (C1: copper-only render -> "c1".)
_FP_RENDER_VERSION = "c4"  # C4: refit the viewBox to the drawn art, at a 2% margin.
# Bump when the symbol render changes (hidden fields, ...): the cache is content-hashed on
# the .kicad_sym, which does NOT change when the RENDER code does. (C1: hide the property
# fields so the body + pins show, not a smudge of overlapping Value/Footprint/Datasheet -> "c1".)
_SYM_RENDER_VERSION = "c3"  # C3: the viewBox refit applies to every preview, symbols included.
# Bump when the MODEL conversion changes: the GLB cache is keyed on the source model file
# hash, which does NOT change when the converter does. Both GLB keys had no such token at
# all, so a converter fix reached only a machine with a cold cache while every test passed.
# (C1: STEP converted by cascadio directly instead of round-tripped through trimesh, which
# was merging away every material past the first and dropping NORMAL attributes -> "c1".)
# (C2: a STEP-derived material states its metalness/roughness instead of inheriting glTF's
# fully-metallic default, which rendered a black epoxy package as an unlit silhouette.)
# (C3: that stated finish becomes MATTE (0.45 -> 0.8). A semi-gloss lobe on a near-black
# body handed back a clean reflection of the studio environment, so the package's top face
# measured rgb(144,144,144) - the viewer was rendering the room rather than the part.)
# (C4: the finish is decided PER SURFACE, so a recognised pin colour - or a solid the vendor named
# as its leadframe - is stated as metal instead of rendering as coloured plastic.)
_MODEL_CONVERT_VERSION = "c4"


def _clean_symbol_svg(cli, lib_path: Path, name: str, bw: bool, td: Path) -> list:
    """Render a symbol's SVG with EVERY property field hidden (Value / Footprint / Datasheet /
    MPN / Reference), so the preview shows the clean body + pins + pin names/numbers instead of
    the fields overlapping into a black smudge (C1). The source lib is never touched; an
    unparseable lib falls back to the raw render (a preview with fields beats no preview)."""
    render_lib = lib_path
    try:
        symlib = SymbolLib.load(lib_path)
        symlib.get_symbol(name).hide_all_properties()
        clean_lib = td / "clean.kicad_sym"
        clean_lib.write_text(symlib.serialize(), encoding="utf-8", newline="")
        render_lib = clean_lib
    except Exception:  # noqa: BLE001 - unparseable/absent symbol: raw preview, not a 500
        pass
    return cli.sym_export_svg(render_lib, name, td, black_and_white=bw)


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
    # C2: the copper pads PLUS the courtyard boundary (F/B.CrtYd) - a thin dashed outline that
    # frames the part like the north-star tile, giving the pads context. We still skip the
    # silkscreen + fab BODY that KiCad's default export fills the frame with (the "white blob");
    # the courtyard is a boundary line, not a fill, so it reads as an outline, not a smudge.
    svg = cli.fp_export_svg(
        render_pretty, name, out_dir, black_and_white=bw, layers="F.Cu,B.Cu,F.CrtYd,B.CrtYd"
    )
    return Path(svg).read_text(encoding="utf-8")


def scalable_svg(text: str) -> str:
    """Drop the ROOT `<svg>` element's physical width/height so the `viewBox` drives sizing.

    `kicad-cli` writes real-world dimensions - a 1.4x3.5mm part exports as
    `width="2.641600mm" height="4.114800mm"` - which gives the browser an INTRINSIC SIZE of about
    10x16 CSS pixels. In a 127x110 preview tile with `object-fit: contain` that is the
    near-invisible sliver users reported as a broken footprint render; nothing had failed, the
    drawing was simply being shown at its true physical size. Measured on the same file: stripping
    the two attributes takes the intrinsic size to 96x150, correctly proportioned, and the tile
    fills.

    Only the ROOT element is touched, and only when a `viewBox` exists to size from - without one
    the physical dimensions are the ONLY sizing information present, and removing them would
    collapse the image to nothing.
    """
    # SEARCH, not match: a real kicad-cli export opens with an XML declaration and a DOCTYPE, so
    # the root element is never at offset 0. Anchoring here silently did nothing on every real file
    # while passing fixtures that began with `<svg` - the reason this needs a real-preamble test.
    match = re.search(r"<svg\b[^>]*>", text)
    if not match:
        return text
    root = match.group(0)
    if "viewBox" not in root:
        return text
    stripped = re.sub(r'\s(?:width|height)="[^"]*"', "", root)
    if stripped == root:
        return text
    return text[: match.start()] + stripped + text[match.end() :]


# Fraction of the drawn content's larger dimension left as breathing room around a refit
# viewBox, so the art does not touch the tile edge. Small on purpose: the whole point is to
# fill the tile, and a generous margin re-creates the problem being fixed. Halved from 0.04
# after the owner said the footprint was still too small to read.
_REFIT_MARGIN = 0.02


def _svg_content_bbox(text: str) -> tuple[float, float, float, float] | None:
    """Bounding box of everything the SVG actually DRAWS, or None if it draws nothing.

    kicad-cli emits only `M`/`L`/`Z` paths plus `<circle>` (arcs and rounded pads arrive
    already tessellated into segments), so scraping coordinate pairs is exact rather than
    approximate. Taking every number as a coordinate pair stays CORRECT if a future KiCad
    emits curves too: a bezier is contained by its control points, so the box would be
    generous rather than wrong, and a generous box only under-zooms."""
    xs: list[float] = []
    ys: list[float] = []

    def add(px: list[float], py: list[float], pad: float) -> None:
        xs.extend(v - pad for v in px)
        xs.extend(v + pad for v in px)
        ys.extend(v - pad for v in py)
        ys.extend(v + pad for v in py)

    for element in re.finditer(r"<(path|circle)\b([^>]*)>", text, re.S):
        kind, attrs = element.group(1), element.group(2)
        # a stroke straddles its path, so half of it lies OUTSIDE the geometry. Refitting to bare
        # coordinates would shave the outer half off every courtyard line at the frame edge.
        stroke = re.search(r"stroke-width:\s*([\d.]+)", attrs)
        half = float(stroke.group(1)) / 2 if stroke and "stroke:none" not in attrs else 0.0
        if kind == "circle":
            cx = re.search(r'\bcx="(-?[\d.eE+]+)"', attrs)
            cy = re.search(r'\bcy="(-?[\d.eE+]+)"', attrs)
            cr = re.search(r'\br="(-?[\d.eE+]+)"', attrs)
            if cx and cy and cr:
                add([float(cx.group(1))], [float(cy.group(1))], float(cr.group(1)) + half)
            continue
        d = re.search(r'\bd="([^"]*)"', attrs, re.S)
        if not d:
            continue
        nums = [float(n) for n in re.findall(r"-?\d+\.?\d*(?:[eE][-+]?\d+)?", d.group(1))]
        if len(nums) >= 2:
            add(nums[0::2], nums[1::2], half)

    if not xs or not ys:
        return None
    return min(xs), min(ys), max(xs), max(ys)


def refit_viewbox(text: str) -> str:
    """Shrink the root `viewBox` to what the SVG actually draws.

    kicad-cli sizes a footprint's viewBox from the footprint's WHOLE extent - every layer and
    every text item, including ones the preview deliberately does not draw. The preview renders
    only `F.Cu,B.Cu,F.CrtYd,B.CrtYd` and hides the Reference/Value, so the drawn copper ends up
    as a speck inside a box sized for things nobody sees. MEASURED on the owner's real
    TPD6E05U06RVZR: geometry spans about 1.7x4.9mm while the viewBox is 11.049x6.4008mm, so the
    art covered under a tenth of the frame and the tile rendered a tiny stamp - the
    "near-invisible footprint preview" complaint. The inflation there came from a vendor
    `(fp_text user "Designator156")`, 13 characters of text at roughly 11mm wide.

    Hiding more text would NOT have been enough, which is why this works on the OUTPUT instead:
    the same footprint carries F.SilkS and F.Fab line work that is equally undrawn and equally
    counted. Refitting to what was actually emitted is correct for any cause, present or future.

    `scalable_svg` is the necessary companion, not a substitute: it makes the box SCALE to the
    tile, while this decides what the box CONTAINS. An oversized box scales an oversized margin.
    """
    match = re.search(r"<svg\b[^>]*>", text)
    if not match:
        return text
    root = match.group(0)
    if not re.search(r'viewBox="[^"]*"', root):
        return text
    box = _svg_content_bbox(text)
    if box is None:
        return text  # nothing drawn: never invent a degenerate box
    x0, y0, x1, y1 = box
    width, height = x1 - x0, y1 - y0
    if width <= 0 or height <= 0:
        return text
    margin = max(width, height) * _REFIT_MARGIN
    fitted = (
        f'viewBox="{x0 - margin:.6f} {y0 - margin:.6f} '
        f'{width + 2 * margin:.6f} {height + 2 * margin:.6f}"'
    )
    return text[: match.start()] + re.sub(r'viewBox="[^"]*"', fitted, root) + text[match.end() :]


def _resolve_footprint_file(ctx, part_id: str):
    """(record, .kicad_mod path, its .pretty dir) for a part, or an honest FileNotFoundError.

    Shared by the SVG preview and the 3D land-pattern endpoint so the two can never disagree about
    WHICH file a part's footprint is - a passive points at a KiCad STOCK footprint it does not own,
    everything else at the profile's own library.
    """
    rec = ctx.ops.load_record(part_id)
    kicad = rec.assets_for("kicad")
    if kicad.footprint is None or not kicad.footprint.name:
        raise FileNotFoundError(f"part {part_id} has no footprint")
    if rec.passive:
        fp_file = stock_footprint_file(kicad.footprint.lib, kicad.footprint.name)
        if fp_file is None:
            raise FileNotFoundError(
                f"KiCad stock footprint {kicad.footprint.lib}:{kicad.footprint.name} "
                "is not installed"
            )
        return rec, fp_file, fp_file.parent
    pretty = ctx.profile.library.footprint_lib_path(rec.category)
    if not pretty.exists():
        raise FileNotFoundError(f"footprint library missing for {rec.category}")
    fp_file = pretty / f"{kicad.footprint.name}.kicad_mod"
    if not fp_file.exists():
        raise FileNotFoundError(f"footprint file missing: {kicad.footprint.name}")
    return rec, fp_file, pretty


def previews_router(require_token) -> APIRouter:
    r = APIRouter(prefix="/api/previews", dependencies=[Depends(require_token)])

    def _svg_response(text: str) -> Response:
        # every preview goes through here, so a scalable SVG cannot be applied to one kind and
        # forgotten on the other. Refit FIRST (decide what the box contains), then strip the
        # physical width/height (let that box drive the tile) - the two are complementary, and
        # scaling an oversized box only scales the empty margin with it.
        return Response(content=scalable_svg(refit_viewbox(text)), media_type="image/svg+xml")

    @r.get("/symbol/{part_id}.svg")
    def symbol_svg(request: Request, part_id: str, bw: bool = False, rev: str = "") -> Response:
        ctx = request.app.state.ctx
        if ctx.index.get(part_id) is None:
            raise FileNotFoundError(f"no such part: {part_id}")
        if rev:
            return _svg_response(_svg_at_rev(ctx, part_id, "sym", rev, bw))
        rec = ctx.ops.load_record(part_id)
        # Previews render KiCad artifacts (kicad-cli SVG, the footprint's linked STEP), so
        # they read the KiCad bundle by name rather than a tool-neutral-looking field.
        kicad = rec.assets_for("kicad")
        if kicad.symbol is None or not kicad.symbol.name:
            raise FileNotFoundError(f"part {part_id} has no symbol")
        # A passive references a KiCad STOCK symbol lib (Device:R) with no owned file,
        # so render it from the installed KiCad libraries, not the category lib.
        if rec.passive:
            lib = stock_symbol_lib_file(kicad.symbol.lib)
            if lib is None:
                raise FileNotFoundError(
                    f"KiCad stock symbol library {kicad.symbol.lib} is not installed"
                )
        else:
            lib = ctx.profile.library.symbol_lib_path(rec.category)
            if not lib.exists():
                raise FileNotFoundError(f"symbol library missing for {rec.category}")
        variant = "_bw" if bw else ""
        key = f"sym_{part_id}_{_SYM_RENDER_VERSION}_{_hash_file(lib)}{variant}.svg"
        cached = _cache_dir(ctx) / key
        if cached.exists():
            return _svg_response(cached.read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as td:
            svgs = _clean_symbol_svg(ctx.cli, lib, kicad.symbol.name, bw, Path(td))
            text = Path(svgs[0]).read_text(encoding="utf-8")
        cached.write_text(text, encoding="utf-8")
        return _svg_response(text)

    @r.get("/land/{part_id}.json")
    def land_pattern(request: Request, part_id: str) -> dict:
        """The footprint's pads plus the 3D model's placement, for the viewer's board mode.

        Owner, 2026-07-25: "cant see just the footprint in 3d option either. that way with the
        footprint showing u can see if the 3d model is oriented properly." A body floating alone
        cannot be checked against anything; a body sitting on its own land pattern either lines up
        or visibly does not. So the two travel together in ONE response - asking the viewer to
        correlate two endpoints is how they end up disagreeing.

        Geometry is passed in KiCad's own units and frame (mm, +Y down, degrees). The viewer owns
        the conversion to scene axes, because that is where the model's own axis convention is
        already handled.
        """
        ctx = request.app.state.ctx
        if ctx.index.get(part_id) is None:
            raise FileNotFoundError(f"no such part: {part_id}")
        _rec, fp_file, _pretty = _resolve_footprint_file(ctx, part_id)
        fp = Footprint.load(fp_file)
        place = fp.model_placement
        return {
            "units": "mm",
            "pads": [
                {
                    "number": p.number,
                    "at": [p.at[0], p.at[1]],
                    "size": [p.size[0], p.size[1]],
                    "shape": p.shape,
                    "rotation": p.rotation,
                    "drill": p.drill,
                    "pad_type": p.pad_type,
                    "side": p.side,
                    "rratio": p.roundrect_rratio,
                }
                for p in fp.pads
            ],
            "graphics": [
                {
                    "start": [g.start[0], g.start[1]],
                    "end": [g.end[0], g.end[1]],
                    "layer": g.layer,
                    "width": g.width,
                }
                for g in fp.graphics
            ],
            "model_placement": (
                None
                if place is None
                else {
                    "offset": list(place.offset),
                    "scale": list(place.scale),
                    "rotate": list(place.rotate),
                }
            ),
        }

    @r.get("/footprint/{part_id}.svg")
    def footprint_svg(request: Request, part_id: str, bw: bool = False, rev: str = "") -> Response:
        ctx = request.app.state.ctx
        if ctx.index.get(part_id) is None:
            raise FileNotFoundError(f"no such part: {part_id}")
        if rev:
            return _svg_response(_svg_at_rev(ctx, part_id, "fp", rev, bw))
        rec, fp_file, pretty = _resolve_footprint_file(ctx, part_id)
        variant = "_bw" if bw else ""
        # Content-address the key (like the symbol + model endpoints) so an edited
        # footprint re-renders and two profiles sharing a part_id + footprint name in
        # the one shared cache dir never serve each other's geometry.
        key = f"fp_{part_id}_{_FP_RENDER_VERSION}_{_hash_file(fp_file)}{variant}.svg"
        cached = _cache_dir(ctx) / key
        if cached.exists():
            return _svg_response(cached.read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as td:
            text = _clean_footprint_svg(ctx.cli, fp_file, fp_file.stem, bw, Path(td))
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
        key = f"stockfp_{lib}_{name}_{_FP_RENDER_VERSION}_{_hash_file(fp_file)}{variant}.svg"
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
        key = f"stockmodel_{lib}_{name}_{_MODEL_CONVERT_VERSION}_{_hash_file(src)}.glb"
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
        kicad = rec.assets_for("kicad")
        # A passive inherits the stock footprint's own 3D model (no owned model.file):
        # resolve it from the installed KiCad libraries keyed on the footprint lib_id.
        if rec.passive:
            if kicad.footprint is None or not kicad.footprint.name:
                raise FileNotFoundError(f"part {part_id} has no footprint for a 3D model")
            src = stock_model_file(kicad.footprint.lib, kicad.footprint.name)
            if src is None:
                raise FileNotFoundError(
                    f"KiCad stock 3D model for {kicad.footprint.lib}:{kicad.footprint.name} "
                    "is not installed"
                )
        else:
            if kicad.model is None or not kicad.model.file:
                raise FileNotFoundError(f"part {part_id} has no 3D model")
            # model.file is stored relative to the profile library root (same convention
            # the mutation engine and the doctor use).
            src = ctx.profile.library.root / kicad.model.file
            if not src.exists():
                raise FileNotFoundError(f"3D model file is missing: {kicad.model.file}")
        key = f"model_{part_id}_{_MODEL_CONVERT_VERSION}_{_hash_file(src)}.glb"
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
