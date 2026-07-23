"""Qt-free FastAPI surface over the STM32 pinout/spec index (stm-viewer workstream Phase 3).

Every handler reads ``ctx = request.app.state.ctx`` and gates a read on ``ctx.stm_index is
None`` with ``ApiError(409, "STM index not built")`` - mirroring api/routers/library.py's
``request.app.state.ctx`` pattern. This module (and everything under ``stockroom.stm``) must
NEVER import PyQt/pywebview, nor reference any board/switch-fabric concept from
INTERFACES.md section 6's DO-NOT-REUSE row - tests/backend/test_stm_import_boundary.py and
CI both enforce this (and the test itself greps for those literal legacy identifiers, so
they are deliberately not spelled out here)."""

from __future__ import annotations

import threading
from pathlib import Path

from fastapi import APIRouter, Depends, Request

from stockroom.api.errors import ApiError
from stockroom.api.schemas import (
    AfOptionDTO,
    FamilyDTO,
    McuSpecRow,
    PinDTO,
    PinoutDTO,
    StmStatusDTO,
    SuggestionGroupDTO,
    UnionDTO,
)
from stockroom.stm import authority as stm_authority
from stockroom.stm import geometry as stm_geometry
from stockroom.stm import source as stm_source

# Single-flight guard for POST /build, mirroring library.py's _rescan_lock: a second POST
# while one build is QUEUED/RUNNING must return the SAME in-flight job, never spawn a second
# multi-thousand-file build. Wired here in 03-01 so the lock exists from the first commit;
# the handler that actually uses it lands in 03-03.
_stm_build_lock = threading.Lock()


def _configured_source(ctx) -> str:
    """The configured CubeMX source path: MachineConfig.stm_cubemx_source when set (that field
    lands in 03-03 - getattr keeps this working before it exists), else stm.source's own
    env-var/candidate-path discovery."""
    configured = (getattr(ctx.config, "stm_cubemx_source", "") or "").strip()
    if configured:
        return configured
    found = stm_source.default_cubemx_source()
    return str(found) if found else ""


def _is_building(request: Request) -> bool:
    """True when a POST /build job (request.app.state.stm_build_job_id, set by the 03-03
    build handler) is QUEUED/RUNNING. Absent job id = never built this run = not building."""
    ctx = request.app.state.ctx
    job_id = getattr(request.app.state, "stm_build_job_id", "")
    if not job_id:
        return False
    from stockroom.api.jobs import JobStatus

    try:
        job = ctx.jobs.get(job_id)
    except KeyError:
        return False
    return job.status in (JobStatus.QUEUED, JobStatus.RUNNING)


def _mpn_example_from_ref(ref_name: str) -> str:
    """A best-effort, display-only expansion of a CubeMX ref name into a plausible real MPN:
    the FIRST option inside any "(A-B)" variant group, and each "x"/"X" wildcard filled with
    "6" (matching INTERFACES.md's own worked example, 'STM32F407V(E-G)Tx' -> 'STM32F407VGT6').
    This is NOT part resolution (stm.authority.resolve_part, 03-02, is the real exact/prefix/
    regex MPN match) - purely a readable example string for the spec-matrix table."""
    out: list[str] = []
    i, s = 0, ref_name
    while i < len(s):
        c = s[i]
        if c == "(":
            j = s.find(")", i)
            if j == -1:
                out.append(c)
                i += 1
                continue
            options = s[i + 1 : j].split("-")
            out.append(options[0] if options and options[0] else "")
            i = j + 1
        elif c in "xX":
            out.append("6")
            i += 1
        else:
            out.append(c)
            i += 1
    return "".join(out)


def _mcu_spec_rows(ctx) -> list[dict]:
    """The full spec-matrix as plain dicts, one self-contained SELECT over the built index's
    connection joined to a per-peripheral COUNT(*) rollup (StmIndex exposes no equivalent
    query method today - stm/db.py is Phase 1's file; this stays a router-local helper per
    CONTEXT.md rather than growing StmIndex's surface for one caller)."""
    conn = ctx.stm_index.conn
    periph_by_mcu: dict[int, dict[str, int]] = {}
    for mcu_id, name, count in conn.execute(
        "SELECT mcu_id, peripheral_name, COUNT(*) FROM mcu_peripheral "
        "GROUP BY mcu_id, peripheral_name"
    ):
        periph_by_mcu.setdefault(mcu_id, {})[name] = count

    rows: list[dict] = []
    for row in conn.execute(
        "SELECT m.id AS id, m.ref_name AS part, m.family AS series, m.line AS line, "
        "m.package_name AS package, m.pin_count AS pin_count, ms.core AS core, "
        "ms.flash_kb AS flash_kb, ms.ram_kb AS ram_kb, ms.max_freq_mhz AS max_freq_mhz, "
        "ms.io_count AS io_count, ms.vdd_min AS vdd_min, ms.vdd_max AS vdd_max, "
        "ms.temp_min_c AS temp_min_c, ms.temp_max_c AS temp_max_c "
        "FROM mcu m LEFT JOIN mcu_spec ms ON ms.mcu_id = m.id ORDER BY m.ref_name"
    ):
        rows.append(
            {
                "part": row["part"],
                "mpn_example": _mpn_example_from_ref(row["part"]),
                "series": row["series"] or "",
                "line": row["line"] or "",
                "core": row["core"] or "",
                "package": row["package"] or "",
                "pin_count": row["pin_count"] or 0,
                "io_count": row["io_count"] or 0,
                "flash_kb": row["flash_kb"],
                "ram_kb": row["ram_kb"],
                "max_freq_mhz": row["max_freq_mhz"],
                "vdd_min": row["vdd_min"],
                "vdd_max": row["vdd_max"],
                "temp_min_c": row["temp_min_c"],
                "temp_max_c": row["temp_max_c"],
                "peripherals": periph_by_mcu.get(row["id"], {}),
            }
        )
    return rows


def _facet_counts(rows: list[dict], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        value = row.get(key) or ""
        counts[value] = counts.get(value, 0) + 1
    return counts


def _families_rollup(ctx) -> list[dict]:
    """One row per distinct mcu.family: its distinct lines, packages, and mcu_count -
    a simple Layer A rollup, no Layer B computation needed."""
    conn = ctx.stm_index.conn
    out: dict[str, dict] = {}
    for row in conn.execute(
        "SELECT family, line, package_name FROM mcu WHERE family IS NOT NULL AND family <> ''"
    ):
        entry = out.setdefault(
            row["family"], {"family": row["family"], "lines": set(), "packages": set(), "mcu_count": 0}
        )
        entry["mcu_count"] += 1
        if row["line"]:
            entry["lines"].add(row["line"])
        if row["package_name"]:
            entry["packages"].add(row["package_name"])
    return [
        {
            "family": entry["family"],
            "lines": sorted(entry["lines"]),
            "packages": sorted(entry["packages"]),
            "mcu_count": entry["mcu_count"],
        }
        for entry in sorted(out.values(), key=lambda e: e["family"])
    ]


def _pin_category(electrical_class: str, role_names: list[str]) -> str:
    """The visual-encoding category (color-is-data, VIZ-02/03): a coarser bucket than
    electrical_class for the io case, distinguishing analog/debug/oscillator/plain-gpio."""
    if electrical_class != "io":
        return electrical_class
    if "analog" in role_names:
        return "analog"
    if any(r in ("swdio", "swclk", "swo", "jtag_extra") for r in role_names):
        return "debug"
    if any(r.startswith("oscillator") for r in role_names):
        return "oscillator"
    return "gpio"


def _pin_supply(role_names: list[str]) -> str | None:
    """The VDD/VDDA/VBAT/VREF domain, when a power pin (role_name "power_<domain>",
    stm/db.py's roles() convention) - None for every non-power pin."""
    for name in role_names:
        if name.startswith("power_"):
            return name[len("power_") :].upper()
    return None


def _build_pinout_dto(ctx, part: str) -> dict | None:
    """The full PinoutDTO-shaped dict for one resolved part: resolve_part's per-pin
    roles/functions/five_v, enriched here with geometry, alternate_functions, category,
    and supply (facts resolve_part's leaner Layer B contract does not carry). Returns
    None on a resolve_part miss."""
    conn = ctx.stm_index.conn
    resolved = stm_authority.resolve_part(conn, part)
    if resolved is None:
        return None

    mcu_row = conn.execute(
        "SELECT id FROM mcu WHERE ref_name = ?", (resolved["part"],)
    ).fetchone()
    mcu_id = mcu_row["id"]

    facts_by_position = {p["position"]: p for p in resolved["pins"]}
    pins: list[dict] = []
    for pin_row in conn.execute(
        "SELECT id, physical_pin_number, position_kind, lqfp_side, bga_row, bga_col, "
        "canonical_pin_name, raw_pin_name, pin_type, electrical_class "
        "FROM mcu_package_pin WHERE mcu_id = ? ORDER BY physical_pin_number",
        (mcu_id,),
    ):
        position = pin_row["physical_pin_number"]
        base = facts_by_position.get(position, {})
        roles = base.get("roles", [])
        functions = base.get("functions", [])
        five_v = base.get("five_v")
        role_names = [r["role_name"] for r in roles]
        af_rows = [
            {"af_index": r["af_index"], "signal": r["signal"], "peripheral": r["peripheral"]}
            for r in conn.execute(
                "SELECT af_index, signal, peripheral FROM pin_alternate_function "
                "WHERE mcu_package_pin_id = ? ORDER BY af_index",
                (pin_row["id"],),
            )
        ]
        pins.append(
            {
                "position": position,
                "position_kind": pin_row["position_kind"],
                "lqfp_side": pin_row["lqfp_side"],
                "bga_row": pin_row["bga_row"],
                "bga_col": pin_row["bga_col"],
                "canonical_pin_name": pin_row["canonical_pin_name"],
                "raw_pin_name": pin_row["raw_pin_name"],
                "pin_type": pin_row["pin_type"],
                "electrical_class": pin_row["electrical_class"],
                "category": _pin_category(pin_row["electrical_class"], role_names),
                "roles": roles,
                "functions": functions,
                "alternate_functions": af_rows,
                "five_v": five_v,
                "supply": _pin_supply(role_names),
            }
        )

    geometry_row = conn.execute(
        "SELECT body_shape, pin_count, rows, cols, pitch_mm, has_center_pad "
        "FROM package_geometry WHERE package_name = ?",
        (resolved["package"],),
    ).fetchone()
    if geometry_row:
        geometry = {
            "body_shape": geometry_row["body_shape"],
            "pin_count": geometry_row["pin_count"],
            "rows": geometry_row["rows"],
            "cols": geometry_row["cols"],
            "pitch_mm": geometry_row["pitch_mm"],
            "has_center_pad": bool(geometry_row["has_center_pad"]),
            "source": "curated",
        }
    else:
        # No curated row: infer an honest geometry from the pins themselves, so every
        # package renders (never the old perimeter-qfp default, which a ball-grid
        # package cannot satisfy: its pins carry no lqfp_side, so the map laid out
        # zero pads). Grid span = the real ball maxima; balls whose row label the
        # JEDEC letter alphabet cannot order (the STM32MP1 SiP secondary zones, e.g.
        # "1A2") are skipped for the span, exactly as the frontend skips laying them.
        alnum = [p for p in pins if p["position_kind"] == "alnum"]
        rows = cols = None
        if alnum:
            row_indexes = []
            for p in alnum:
                try:
                    row_indexes.append(stm_geometry.bga_row_index(p["bga_row"]))
                except ValueError:
                    continue
            rows = max(row_indexes) + 1 if row_indexes else None
            cols = max(p["bga_col"] for p in alnum if p["bga_col"] is not None) or None
        geometry = {
            "body_shape": stm_geometry.infer_body_shape(resolved["package"], bool(alnum)),
            "pin_count": len({p["position"] for p in pins}),
            "rows": rows,
            "cols": cols,
            "pitch_mm": None,
            "has_center_pad": False,
            "source": "inferred",
        }

    return {
        "part": resolved["part"],
        "mpn_example": _mpn_example_from_ref(resolved["part"]),
        "package": resolved["package"],
        "geometry": geometry,
        "pins": pins,
    }


def stm_router(require_token) -> APIRouter:
    r = APIRouter(prefix="/api/stm", dependencies=[Depends(require_token)])

    @r.get("/status")
    def stm_status(request: Request) -> dict:
        """Never 409s - this IS the is-it-built probe a 409-gated read routes the frontend
        to. built=false + zeroed stamp fields when ctx.stm_index is None."""
        ctx = request.app.state.ctx
        building = _is_building(request)
        configured_source = _configured_source(ctx)
        if ctx.stm_index is None:
            return StmStatusDTO.from_dict(
                {
                    "built": False,
                    "building": building,
                    "source_path": configured_source,
                    "source_present": bool(configured_source)
                    and Path(configured_source).is_dir(),
                    "all_families": False,
                    "device_xml_count": 0,
                    "family_count": 0,
                    "families": [],
                    "mcu_count": 0,
                    "classifier_rev": 0,
                    "af_schema_rev": 0,
                    "geometry_rev": 0,
                    "source_sha256": "",
                    "built_at": "",
                }
            ).model_dump()

        meta = ctx.stm_index.meta()
        families = sorted(
            {
                row["family"]
                for row in ctx.stm_index.conn.execute(
                    "SELECT DISTINCT family FROM mcu WHERE family IS NOT NULL AND family <> ''"
                )
            }
        )
        source_path = meta.get("source_path", "") or configured_source
        return StmStatusDTO.from_dict(
            {
                "built": True,
                "building": building,
                "source_path": source_path,
                "source_present": bool(source_path) and Path(source_path).is_dir(),
                "all_families": meta.get("all_families") == "true",
                "device_xml_count": meta.get("device_xml_count", 0),
                "family_count": meta.get("family_count", 0),
                "families": families,
                "mcu_count": ctx.stm_index.mcu_count(),
                "classifier_rev": meta.get("classifier_rev", 0),
                "af_schema_rev": meta.get("af_schema_rev", 0),
                "geometry_rev": meta.get("geometry_rev", 0),
                "source_sha256": meta.get("source_sha256", ""),
                "built_at": meta.get("built_at", ""),
            }
        ).model_dump()

    @r.get("/mcus")
    def list_mcus(
        request: Request,
        q: str = "",
        family: str | None = None,
        core: str | None = None,
        package: str | None = None,
        series: str | None = None,
    ) -> dict:
        """The full spec matrix for client-side TanStack filtering, plus a server-computed
        `series`/`family` (an EXPLICIT filter narrowing - `family` and `series` both address
        mcu.family; INTERFACES.md section 4 lists them as separate query params/facet keys, so
        both are accepted and both facet dimensions are served, kept identical by construction)
        and `core`/`package` narrowing. Facets always reflect the FULL unfiltered set."""
        ctx = request.app.state.ctx
        if ctx.stm_index is None:
            raise ApiError(409, "STM index not built")

        all_rows = _mcu_spec_rows(ctx)
        facets = {
            "family": _facet_counts(all_rows, "series"),
            "core": _facet_counts(all_rows, "core"),
            "package": _facet_counts(all_rows, "package"),
            "series": _facet_counts(all_rows, "series"),
        }

        rows = all_rows
        series_filter = family or series
        if series_filter:
            rows = [row for row in rows if row["series"] == series_filter]
        if core:
            rows = [row for row in rows if row["core"] == core]
        if package:
            rows = [row for row in rows if row["package"] == package]
        if q:
            needle = q.strip().lower()
            rows = [
                row
                for row in rows
                if needle in row["part"].lower()
                or needle in row["series"].lower()
                or needle in row["line"].lower()
            ]

        return {
            "mcus": [McuSpecRow.from_dict(row).model_dump() for row in rows],
            "count": len(rows),
            "facets": facets,
        }

    @r.get("/families")
    def list_families(request: Request) -> dict:
        ctx = request.app.state.ctx
        if ctx.stm_index is None:
            raise ApiError(409, "STM index not built")
        return {"families": [FamilyDTO.from_dict(f).model_dump() for f in _families_rollup(ctx)]}

    @r.get("/pinout")
    def get_pinout(request: Request, part: str) -> dict:
        ctx = request.app.state.ctx
        if ctx.stm_index is None:
            raise ApiError(409, "STM index not built")
        dto_dict = _build_pinout_dto(ctx, part)
        if dto_dict is None:
            raise ApiError(404, f"no such part: {part}")
        return PinoutDTO.from_dict(dto_dict).model_dump()

    @r.get("/pin")
    def get_pin(request: Request, part: str, position: str) -> dict:
        ctx = request.app.state.ctx
        if ctx.stm_index is None:
            raise ApiError(409, "STM index not built")
        dto_dict = _build_pinout_dto(ctx, part)
        if dto_dict is None:
            raise ApiError(404, f"no such part: {part}")
        pin = next((p for p in dto_dict["pins"] if p["position"] == position), None)
        if pin is None:
            raise ApiError(404, f"no such position {position!r} on {part}")
        return PinDTO.from_dict(pin).model_dump()

    @r.get("/pin/af")
    def get_pin_af(request: Request, part: str, position: str) -> dict:
        """The complete AF set for one pin (SWAP-01); 404 if the position is absent, but an
        EMPTY alternate_functions list (not 404) when the pin simply has no AF-mux entries."""
        ctx = request.app.state.ctx
        if ctx.stm_index is None:
            raise ApiError(409, "STM index not built")
        dto_dict = _build_pinout_dto(ctx, part)
        if dto_dict is None:
            raise ApiError(404, f"no such part: {part}")
        pin = next((p for p in dto_dict["pins"] if p["position"] == position), None)
        if pin is None:
            raise ApiError(404, f"no such position {position!r} on {part}")
        return {
            "position": position,
            "alternate_functions": [
                AfOptionDTO.from_dict(a).model_dump() for a in pin["alternate_functions"]
            ],
        }

    @r.get("/signal/candidates")
    def get_signal_candidates(request: Request, part: str, signal: str) -> dict:
        """Every pin the signal can route to across the part (SWAP-02); an EMPTY candidates
        list (not 404) when the part does not carry the signal at all."""
        ctx = request.app.state.ctx
        if ctx.stm_index is None:
            raise ApiError(409, "STM index not built")
        conn = ctx.stm_index.conn
        resolved = stm_authority.resolve_part(conn, part)
        if resolved is None:
            raise ApiError(404, f"no such part: {part}")
        mcu_row = conn.execute(
            "SELECT id FROM mcu WHERE ref_name = ?", (resolved["part"],)
        ).fetchone()
        candidates = [
            {
                "position": row["physical_pin_number"],
                "canonical_pin_name": row["canonical_pin_name"],
                "af_index": row["af_index"],
            }
            for row in conn.execute(
                "SELECT p.physical_pin_number, p.canonical_pin_name, af.af_index "
                "FROM pin_alternate_function af "
                "JOIN mcu_package_pin p ON p.id = af.mcu_package_pin_id "
                "WHERE p.mcu_id = ? AND af.signal = ? ORDER BY p.physical_pin_number",
                (mcu_row["id"], signal),
            )
        ]
        return {"signal": signal, "candidates": candidates}

    @r.post("/compat/union")
    def compat_union(request: Request, body: dict) -> dict:
        """socket_union's UnionDTO (COMPAT-01/02/03/05): an explicit {"parts": [...]} set OR
        a {"family", "package"} group. A mixed-scope ValueError from socket_union surfaces as
        400 via the app's existing ValueError -> 400 mapping (errors.status_for)."""
        ctx = request.app.state.ctx
        if ctx.stm_index is None:
            raise ApiError(409, "STM index not built")
        parts = body.get("parts")
        family = body.get("family")
        package = body.get("package")
        result = stm_authority.socket_union(
            ctx.stm_index.conn, refs=parts, family=family, package=package
        )
        result = dict(result)
        result["resolved"] = [
            {"ref": ref, "mpn": _mpn_example_from_ref(ref)} for ref in result["parts"]
        ]
        return UnionDTO.from_dict(result).model_dump()

    @r.get("/compat/suggestions")
    def compat_suggestions(
        request: Request, package: str, family: str, tolerance: int = 0
    ) -> dict:
        ctx = request.app.state.ctx
        if ctx.stm_index is None:
            raise ApiError(409, "STM index not built")
        groups = stm_authority.compatibility_suggestions(
            ctx.stm_index.conn, package, family, tolerance=tolerance
        )
        return {"groups": [SuggestionGroupDTO.from_dict(g).model_dump() for g in groups]}

    @r.post("/af-check")
    def af_check(request: Request, body: dict) -> dict:
        ctx = request.app.state.ctx
        if ctx.stm_index is None:
            raise ApiError(409, "STM index not built")
        part = body.get("part")
        assignment = body.get("assignment") or {}
        conflicts = stm_authority.af_conflicts(ctx.stm_index.conn, part, assignment)
        return {"conflicts": conflicts}

    @r.post("/build")
    def build_stm_index(request: Request) -> dict:
        """Submit a single-flight, READ-lane background build (API-02): the build writes
        its OWN derived sqlite, not the library git tree, so it must not occupy the single
        write worker. Mirrors POST /api/library/rescan's check-and-submit-under-one-lock
        shape exactly, with the STM names."""
        ctx = request.app.state.ctx

        def work(progress):
            source = (ctx.config.stm_cubemx_source or "").strip() or stm_source.default_cubemx_source()
            return ctx.rebuild_stm_index(source, progress=progress)

        with _stm_build_lock:
            existing = getattr(request.app.state, "stm_build_job_id", "")
            if existing:
                try:
                    job = ctx.jobs.get(existing)
                except KeyError:
                    job = None
                from stockroom.api.jobs import JobStatus

                if job is not None and job.status in (JobStatus.QUEUED, JobStatus.RUNNING):
                    return {"job_id": existing, "already_running": True}
            job_id = ctx.jobs.submit(work, write=False)
            request.app.state.stm_build_job_id = job_id
            return {"job_id": job_id}

    return r
