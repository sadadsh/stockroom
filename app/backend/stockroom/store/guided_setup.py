"""Server-owned resumable Guided Setup state and readiness projection.

MachineConfig stores only accepted setup decisions and operation receipts. Current repository,
GitHub, and selected-tool facts are revalidated for every DTO, so a stale green boolean can never
open the product after a repository disappears or a tool connection breaks.
"""

from __future__ import annotations

from pathlib import Path
from urllib.parse import urlsplit

from stockroom.altium.odbc import odbc_status
from stockroom.eda.primary_policy import PrimaryEdaPolicy
from stockroom.kicad.common_json import read_env_var

SETUP_SCHEMA = 1
SETUP_STEPS = (
    "choose_cad_tool",
    "catalog_repository",
    "connect_the_tool",
    "improve_source_data",
    "ready",
)


def _state(config) -> dict[str, object]:
    raw = getattr(config, "guided_setup", None)
    return dict(raw) if isinstance(raw, dict) else {}


def _save(config, **changes: object) -> dict[str, object]:
    state = _state(config)
    state.update(changes)
    state["schema"] = SETUP_SCHEMA
    config.guided_setup = state
    config.save()
    return state


def record_repository(
    config,
    *,
    owner: str,
    name: str,
    visibility: str,
    url: str,
) -> None:
    """Persist only the non-secret identity returned by GitHub after clone/create succeeds."""

    _save(
        config,
        repository={
            "owner": owner,
            "name": name,
            "visibility": visibility,
            "url": url,
        },
    )


def record_tool_connection(config, *, tool: str, receipt: dict[str, object]) -> None:
    """Retain an operation receipt while leaving current readiness to live revalidation."""

    _save(config, tool_connection={"tool": tool, "receipt": dict(receipt)})


def record_source_decision(config, *, skipped: bool) -> None:
    _save(config, source_data={"decided": True, "skipped": bool(skipped)})


def clear_after_primary_change(config) -> None:
    """Keep repository/source choices but require a fresh connection receipt for the new tool."""

    state = _state(config)
    state.pop("tool_connection", None)
    state["schema"] = SETUP_SCHEMA
    config.guided_setup = state
    config.save()


def _github_remote(repo) -> dict[str, str] | None:
    try:
        remote = str(repo.remote_url("origin") or "").strip()
    except Exception:  # noqa: BLE001 - a malformed/missing repository is simply not ready
        return None
    parsed = urlsplit(remote)
    parts = [part for part in parsed.path.strip("/").split("/") if part]
    if (
        parsed.scheme.casefold() != "https"
        or (parsed.hostname or "").casefold() != "github.com"
        or parsed.username is not None
        or parsed.password is not None
        or len(parts) != 2
    ):
        return None
    owner, name = parts
    if name.casefold().endswith(".git"):
        name = name[:-4]
    if not owner or not name:
        return None
    return {
        "owner": owner,
        "name": name,
        "url": f"https://github.com/{owner}/{name}.git",
    }


def _kicad_connection(ctx) -> dict[str, object]:
    available = bool(getattr(getattr(ctx, "cli", None), "available", False))
    wired = (
        read_env_var(Path(ctx.kicad_dir) / "kicad_common.json", "SR_LIB")
        == str(ctx.profile.root.resolve())
    )
    last = getattr(ctx, "last_wiring", None)
    error = str(getattr(last, "error", "") or "")
    skipped = str(getattr(last, "skipped", "") or "")
    return {
        "tool": "kicad",
        "installed": available,
        "connected": available and wired and not error and not skipped,
        "restart_required": bool(getattr(last, "restart_needed", False)),
        "detail": error or skipped or ("KiCad is connected." if available and wired else "KiCad needs connection."),
    }


def _altium_connection(ctx, state: dict[str, object]) -> dict[str, object]:
    from stockroom.altium.driver import AltiumDriver

    driver = AltiumDriver()
    odbc = odbc_status()
    recorded = state.get("tool_connection")
    receipt = recorded.get("receipt") if isinstance(recorded, dict) else None
    verified = bool(
        isinstance(recorded, dict)
        and recorded.get("tool") == "altium"
        and isinstance(receipt, dict)
        and receipt.get("verified") is True
    )
    installed = bool(driver.installed)
    driver_ready = odbc.get("installed") is True
    return {
        "tool": "altium",
        "installed": installed,
        "connected": installed and driver_ready and verified,
        "restart_required": False,
        "detail": (
            "Altium is connected."
            if installed and driver_ready and verified
            else "Altium, its ODBC driver, and one-time catalog setup are required."
        ),
        "odbc_installed": odbc.get("installed"),
        "busy": (driver.busy_titles() or [""])[0],
    }


def status(ctx, github: dict[str, object]) -> dict[str, object]:
    """Return the one authoritative Guided Setup document consumed by every setup surface."""

    config = ctx.config
    state = _state(config)
    policy = PrimaryEdaPolicy(config)
    primary = policy.primary_tool
    remote = _github_remote(ctx.repo)
    authenticated = bool(github.get("authenticated"))
    online = bool(github.get("online"))
    repository_ready = remote is not None and authenticated and online

    if primary is None:
        tool = {
            "tool": None,
            "installed": False,
            "connected": False,
            "restart_required": False,
            "detail": "Choose KiCad or Altium.",
        }
    elif primary.key == "kicad":
        tool = _kicad_connection(ctx)
    else:
        tool = _altium_connection(ctx, state)

    source = state.get("source_data")
    source_decided = bool(isinstance(source, dict) and source.get("decided") is True)
    if primary is None:
        step = "choose_cad_tool"
    elif not repository_ready:
        step = "catalog_repository"
    elif not bool(tool["connected"]):
        step = "connect_the_tool"
    elif not source_decided:
        step = "improve_source_data"
    else:
        step = "ready"

    ready = step == "ready"
    return {
        "schema": SETUP_SCHEMA,
        "step": step,
        "steps": list(SETUP_STEPS),
        "ready": ready,
        "repository_ready": repository_ready,
        "repository": remote,
        "github": dict(github),
        "tool_connection": tool,
        "source_data": {
            "decided": source_decided,
            "skipped": bool(isinstance(source, dict) and source.get("skipped") is True),
            "mouser_connected": bool(config.mouser_api_key),
            "digikey_connected": bool(config.digikey_client_id and config.digikey_client_secret),
        },
    }
