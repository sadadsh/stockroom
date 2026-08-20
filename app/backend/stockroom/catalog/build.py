"""Restart-safe, explicitly confirmed Assets Catalog Builds.

Canonical part JSON remains authoritative.  This module records the exact record digest each
machine-local EDA projection completed, so a restart reconstructs pending work without an
ephemeral job file.  It delegates all actual work to the existing KiCad wiring and Altium
embed/DbLib authorities.
"""

from __future__ import annotations

import hashlib
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import cast

from stockroom.model.part import (
    PartRecord,
    asset_label,
    asset_present,
    tool_place_ready,
)

_BUILD_LOCK = threading.Lock()
_BUILDING_SCOPES: set[str] = set()
_BUILDING_LOCK = threading.Lock()
_HISTORY_LIMIT = 10


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _digest_map(items: dict[str, str]) -> str:
    if not items:
        return ""
    encoded = "\n".join(f"{part_id}:{identity}" for part_id, identity in sorted(items.items()))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _record_identity(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _scope_key(ctx) -> str:
    identity = f"{ctx.libraries_root.resolve()}\0{ctx.profile.name}".casefold()
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]


def _tool_label(tool: str) -> str:
    from stockroom.eda.registry import get_tool

    return get_tool(tool).label


def _save_config(ctx) -> None:
    source = ctx.config.source_path
    ctx.config.save(source) if source is not None else ctx.config.save()


def _ledger(ctx, tool: str) -> dict[str, object]:
    root = ctx.config.catalog_build
    if not isinstance(root, dict):
        root = {}
        ctx.config.catalog_build = root
    profiles = root.setdefault("profiles", {})
    if not isinstance(profiles, dict):
        profiles = {}
        root["profiles"] = profiles
    scope = profiles.setdefault(_scope_key(ctx), {})
    if not isinstance(scope, dict):
        scope = {}
        profiles[_scope_key(ctx)] = scope
    tool_state = scope.setdefault(tool, {})
    if not isinstance(tool_state, dict):
        tool_state = {}
        scope[tool] = tool_state
    tool_state.setdefault("desired", {})
    tool_state.setdefault("completed", {})
    tool_state.setdefault("history", [])
    return tool_state


def _ready_records(ctx, tool: str) -> tuple[dict[str, dict], list[dict]]:
    ready: dict[str, dict] = {}
    blocked: list[dict] = []
    for path in sorted(ctx.profile.library.parts_dir.glob("*.json")):
        try:
            record = PartRecord.loads(path.read_text(encoding="utf-8"))
            missing = list(record.missing_assets(tool))
            if tool == "altium" and asset_label("model") in missing:
                # Altium's model slot is the OUTPUT of Build Now.  A shared STEP on any tool is
                # the input, so this row is buildable precisely while the Altium slot is absent.
                if any(asset_present(record.assets_for(key).model) for key in ("kicad", "altium")):
                    missing.remove(asset_label("model"))
            if not tool_place_ready(record, tool):
                if not record.mpn:
                    missing.append("MPN")
                if not record.manufacturer:
                    missing.append("Manufacturer")
                if not record.description:
                    missing.append("Description")
        except Exception as exc:  # noqa: BLE001 - one bad row stays visible without hiding peers
            blocked.append({"id": path.stem, "detail": str(exc)})
            continue
        if missing:
            blocked.append({"id": record.id, "detail": ", ".join(missing)})
            continue
        ready[record.id] = {
            "id": record.id,
            "display_name": record.display_name or record.mpn or record.id,
            "identity": _record_identity(path),
        }
    return ready, blocked


def _is_building(scope: str) -> bool:
    with _BUILDING_LOCK:
        return scope in _BUILDING_SCOPES


def _set_building(scope: str, value: bool) -> None:
    with _BUILDING_LOCK:
        if value:
            _BUILDING_SCOPES.add(scope)
        else:
            _BUILDING_SCOPES.discard(scope)


def catalog_build_status(ctx, *, persist_desired: bool = True) -> dict:
    tool = str(ctx.config.primary_eda or "").strip().casefold()
    if tool not in {"kicad", "altium"}:
        return {
            "state": "pending",
            "primary_eda": None,
            "tool_label": "CAD",
            "desired_identity": "",
            "completed_identity": "",
            "pending_count": 0,
            "pending_parts": [],
            "blocked_parts": [],
            "last_result": None,
            "history": [],
        }

    ready, blocked = _ready_records(ctx, tool)
    desired = {part_id: item["identity"] for part_id, item in ready.items()}
    state = _ledger(ctx, tool)
    previous_desired = state.get("desired") if isinstance(state.get("desired"), dict) else {}
    changed = previous_desired != desired
    if changed:
        state["desired"] = desired
    raw_completed = state.get("completed")
    completed = cast(dict[str, str], raw_completed) if isinstance(raw_completed, dict) else {}
    pruned_completed = {part_id: identity for part_id, identity in completed.items() if part_id in desired}
    if pruned_completed != completed:
        completed = pruned_completed
        state["completed"] = completed
        changed = True
    if persist_desired and changed:
        _save_config(ctx)
    pending = [item for part_id, item in ready.items() if completed.get(part_id) != item["identity"]]
    scope = _scope_key(ctx)
    building = _is_building(scope)
    raw_history = state.get("history")
    history = cast(list[dict], raw_history) if isinstance(raw_history, list) else []
    return {
        "state": "building" if building else ("pending" if pending else "current"),
        "primary_eda": tool,
        "tool_label": _tool_label(tool),
        "desired_identity": _digest_map(desired),
        "completed_identity": _digest_map(
            {part_id: completed[part_id] for part_id in desired if completed.get(part_id) == desired[part_id]}
        ),
        "pending_count": len(pending),
        "pending_parts": pending,
        "blocked_parts": blocked,
        "last_result": history[0] if history else None,
        "history": history,
    }


def _kicad_build(ctx, targets: list[str]) -> tuple[dict[str, str], dict[str, str]]:
    ctx.rewire_kicad()
    report = ctx.last_wiring
    error = str(getattr(report, "error", "") or getattr(report, "skipped", "") or "")
    if error:
        return {}, {part_id: error for part_id in targets}
    return {part_id: "KiCad catalog wiring is current." for part_id in targets}, {}


def _altium_build(ctx, targets: list[str]) -> tuple[dict[str, str], dict[str, str]]:
    embed = ctx.ops.embed_altium_models(part_ids=targets)
    failures = {
        str(item.get("part_id", "")): str(item.get("detail", "Altium model embedding failed."))
        for item in embed.get("results", [])
        if item.get("status") == "failed" and item.get("part_id")
    }
    for part_id in embed.get("skipped", []):
        part_id = str(part_id)
        if part_id not in targets or part_id in failures:
            continue
        record = ctx.ops.load_record(part_id)
        if not asset_present(record.assets_for("altium").model):
            failures[part_id] = (
                "Altium model embedding was skipped without producing a staged model."
            )
    projection = ctx.ops.regenerate_altium_dblib()
    for part_id in projection.get("skipped", []):
        part_id = str(part_id)
        if part_id in targets and part_id not in failures:
            failures[part_id] = "Altium DbLib projection skipped this component."
    ctx.rebuild_index()
    ctx.auto_push()
    successes = {
        part_id: "Altium catalog projection is current."
        for part_id in targets
        if part_id not in failures
    }
    return successes, failures


def run_catalog_build(ctx) -> dict:
    tool = str(ctx.config.primary_eda or "").strip().casefold()
    if tool not in {"kicad", "altium"}:
        raise ValueError("Choose a Primary CAD Tool before building the catalog.")
    scope = _scope_key(ctx)
    if not _BUILD_LOCK.acquire(blocking=False):
        raise RuntimeError("A Catalog Build is already running.")
    _set_building(scope, True)
    started = _now()
    try:
        before = catalog_build_status(ctx)
        targets = [part["id"] for part in before["pending_parts"]]
        successes: dict[str, str] = {}
        failures: dict[str, str] = {}
        try:
            if tool == "kicad":
                successes, failures = _kicad_build(ctx, targets)
            else:
                successes, failures = _altium_build(ctx, targets)
        except Exception as exc:  # noqa: BLE001 - retain the exact build authority failure
            detail = str(exc) or type(exc).__name__
            failures = {part_id: detail for part_id in targets}
            successes = {}

        after_ready, _blocked = _ready_records(ctx, tool)
        for part_id in list(successes):
            if part_id not in after_ready:
                failures[part_id] = "The component is no longer CAD Ready after the build."
                del successes[part_id]
        state = _ledger(ctx, tool)
        state["desired"] = {
            part_id: item["identity"] for part_id, item in after_ready.items()
        }
        raw_completed = state.get("completed")
        completed = cast(dict[str, str], raw_completed) if isinstance(raw_completed, dict) else {}
        for part_id in successes:
            if part_id in after_ready:
                completed[part_id] = after_ready[part_id]["identity"]
        state["completed"] = completed
        items = [
            {
                "part_id": part_id,
                "status": "failed" if part_id in failures else "current",
                "detail": failures.get(part_id, successes.get(part_id, "Catalog projection is current.")),
            }
            for part_id in targets
        ]
        result = {
            "status": "partial" if successes and failures else ("failed" if failures else "completed"),
            "primary_eda": tool,
            "tool_label": _tool_label(tool),
            "attempted": len(targets),
            "succeeded": len(successes),
            "failed": len(failures),
            "started_at": started,
            "completed_at": _now(),
            "items": items,
        }
        raw_history = state.get("history")
        history = cast(list[dict], raw_history) if isinstance(raw_history, list) else []
        state["history"] = [result, *history][:_HISTORY_LIMIT]
        _save_config(ctx)
        return result
    finally:
        _set_building(scope, False)
        _BUILD_LOCK.release()


__all__ = ["catalog_build_status", "run_catalog_build"]
