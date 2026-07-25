"""Altium Database Library surface for the active profile: a status view over every part, a
synchronous regenerate of the DbLib, and a per-part asset attach. The engine lives in
LibraryOps (regenerate_altium_dblib / attach_altium_assets); this router is thin and guarded.

Everything is scoped to the ACTIVE profile via ctx.ops / ctx.profile, so switching profiles
switches the DbLib this surface reflects."""
from __future__ import annotations

import threading
from pathlib import Path

from fastapi import APIRouter, Depends, Request

from stockroom.altium.odbc import odbc_status
from stockroom.api.errors import ApiError
from stockroom.ingest.component_naming import derive_display_value
from stockroom.model.part import PartRecord, tool_place_ready

# regenerate + attach both commit to the one git repo and write the shared .db/.DbLib, and
# FastAPI runs these sync handlers in the threadpool, so two triggers (the Settings Regenerate,
# the modal's attach-then-regenerate, two quick attaches) can overlap. Serialize every
# library-mutating altium call so concurrent git commits can never collide on .git/index.lock.
_WRITE_LOCK = threading.Lock()


def _row(record) -> dict:
    """One status row per part: its identity + the human-facing display Value (a resistor keeps
    its Ω, unlike the schematic-convention value the DbLib emitter writes) + the resolved Altium
    symbol/footprint names, and whether it is place-ready. Uses the SAME predicate the emitter
    uses (tool_place_ready), so the count can never disagree with what is emitted."""
    sym = record.assets_for("altium").symbol
    fp = record.assets_for("altium").footprint
    return {
        "id": record.id,
        "display_name": record.display_name,
        "category": record.category,
        "mpn": record.mpn,
        "value": record.value or derive_display_value(record),
        "symbol": sym.name if sym else "",
        "footprint": fp.name if fp else "",
        "ready": tool_place_ready(record, "altium"),
    }


def altium_router(require_token) -> APIRouter:
    r = APIRouter(prefix="/api/altium", dependencies=[Depends(require_token)])

    @r.get("/status")
    def status(request: Request) -> dict:
        ctx = request.app.state.ctx
        parts_dir = ctx.profile.library.parts_dir
        # Read records straight from parts_dir (the SAME source regenerate globs) so the count
        # agrees with the emitter, and skip a bad/missing record rather than 404 the whole
        # surface on a stale index (mirrors the guarded full-scan in library.py).
        rows = []
        for json_path in sorted(parts_dir.glob("*.json")):
            try:
                record = PartRecord.loads(json_path.read_text(encoding="utf-8"))
            except Exception:
                continue
            rows.append(_row(record))
        altium_dir = parts_dir.parent / "altium"
        return {
            "profile": ctx.profile.name,
            # .as_posix() (never str(Path)) so the path reads the same on Windows and Linux
            # (backslashes would break a "/altium/..." consumer and the test); repo display rule.
            "dblib": (altium_dir / "Stockroom.DbLib").as_posix(),
            "dblib_dir": altium_dir.as_posix(),
            # The SQLite data source is DERIVED and no longer shared through git, so it can
            # legitimately be absent on a fresh clone until Stockroom rebuilds it. A plain
            # exists() and never a rebuild: a GET must not write to the library.
            "datasource_present": (altium_dir / "stockroom-parts.db").exists(),
            "ready": sum(1 for x in rows if x["ready"]),
            "total": len(rows),
            # not-ready first (the ones needing attention), then by name
            "rows": sorted(rows, key=lambda x: (x["ready"], x["display_name"].lower())),
        }

    @r.get("/odbc-status")
    def odbc() -> dict:
        # Machine-level, not profile-scoped: whether the 64-bit SQLite3 ODBC driver Altium needs to
        # read the DbLib is registered on this host, plus where to get it. Honest null off Windows.
        return odbc_status()

    @r.post("/regenerate")
    def regenerate(request: Request) -> dict:
        ctx = request.app.state.ctx
        with _WRITE_LOCK:
            result = ctx.ops.regenerate_altium_dblib()
            ctx.auto_push()  # the DbLib commit pushes like any library write (no-op without a token)
        return {
            "emitted": result["emitted"],
            "skipped": result["skipped"],
            "dblib": Path(result["dblib"]).as_posix(),
        }

    @r.get("/embed-capability")
    def embed_capability() -> dict:
        """Whether a 3D embed can run HERE, and why not when it cannot.

        Machine-level like `/odbc-status`, not profile-scoped. A 3D body is written into the
        footprint's `.PcbLib` by Altium itself, so this needs Altium installed and its license seat
        free. A KiCad-only peer gets an explained unavailable state instead of a button that
        silently does nothing, which is the whole reason the requirement is registry DATA.
        """
        from stockroom.altium.driver import AltiumDriver
        from stockroom.eda.registry import get_tool

        spec = get_tool("altium").embedded_assets.get("model")
        driver = AltiumDriver()
        busy = driver.busy_titles()
        return {
            "installed": driver.installed,
            # .as_posix() rather than str(Path), so the path reads the same on both platforms.
            "binary": driver.x2.as_posix() if driver.x2 else "",
            "requires_tool_installed": bool(spec and spec.requires_tool_installed),
            "reason": spec.reason if spec else "",
            # A windowed Altium holds the single On-Demand seat, so a scripted run would wait for
            # it forever. Reported up front rather than discovered by a run that never returns.
            "busy": busy[0] if busy else "",
            "available": driver.installed and not busy,
        }

    @r.post("/parts/{part_id}/embed-model")
    def embed_model_route(request: Request, part_id: str, body: dict | None = None) -> dict:
        """Embed the part's 3D model into its Altium footprint's `.PcbLib`.

        Serialized behind the same module lock as the other git-committing endpoints: this one
        drives Altium AND commits, so two concurrent calls would collide on both the license seat
        and `.git/index.lock`.
        """
        ctx = request.app.state.ctx
        if ctx.index.get(part_id) is None:
            raise FileNotFoundError(f"no such part: {part_id}")
        with _WRITE_LOCK:
            # ValueError -> 400 with the reason (including Altium's own words on a tool failure).
            result = ctx.ops.embed_altium_model(part_id, replace=bool((body or {}).get("replace")))
            ctx.rebuild_index()
            ctx.auto_push()
        return result

    @r.post("/parts/{part_id}/attach")
    def attach(request: Request, part_id: str, body: dict) -> dict:
        ctx = request.app.state.ctx
        if ctx.index.get(part_id) is None:
            raise FileNotFoundError(f"no such part: {part_id}")
        sources = [Path(p) for p in body.get("paths", [])]
        if not sources:
            raise ApiError(422, "attach needs a .SchLib and .PcbLib pair, or a single .IntLib")
        with _WRITE_LOCK:
            record = ctx.ops.attach_altium_assets(part_id, *sources)  # ValueError -> 400 on bad source
            ctx.rebuild_index()
            ctx.auto_push()
        return record.to_dict()

    return r
