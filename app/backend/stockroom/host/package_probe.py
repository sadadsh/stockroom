"""Headless acceptance probe for the exact packaged managed host executable."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from pathlib import Path


class ManagedHostProbeError(RuntimeError):
    """The packaged host failed at the user-visible managed-runtime boundary."""


def _json_get(
    url: str,
    *,
    token: str | None = None,
) -> tuple[int, dict[str, object], str]:
    headers = {} if token is None else {"X-Stockroom-Token": token}
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=15.0) as response:
            raw = response.read(1024 * 1024)
            content_type = response.headers.get("Content-Type", "")
            return (
                response.status,
                json.loads(raw.decode("utf-8")),
                content_type,
            )
    except (OSError, UnicodeError, ValueError, urllib.error.URLError) as exc:
        raise ManagedHostProbeError("packaged host endpoint is unavailable") from exc


def _page_get(url: str) -> tuple[int, str]:
    try:
        with urllib.request.urlopen(url, timeout=15.0) as response:
            return response.status, response.read(2 * 1024 * 1024).decode("utf-8")
    except (OSError, UnicodeError, urllib.error.URLError) as exc:
        raise ManagedHostProbeError("packaged frontend is unavailable") from exc


def run_managed_host_probe(receipt_path: Path) -> None:
    """Boot, inspect, and cleanly stop the production host without opening a window."""

    receipt_path = Path(receipt_path)
    if not receipt_path.is_absolute():
        raise ManagedHostProbeError("managed-host receipt path must be absolute")
    if receipt_path.exists() or receipt_path.is_symlink():
        raise ManagedHostProbeError("managed-host receipt path already exists")

    from stockroom import BUILD_IDENTITY
    from stockroom.host.run import run_windowed

    receipt: dict[str, object] = {}

    def inspect(base_url: str, token: str) -> None:
        health_status, health, _ = _json_get(f"{base_url}/api/health")
        service_generation = health.get("service_generation")
        release_id = health.get("release_id")
        if (
            health_status != 200
            or health.get("status") != "ok"
            or health.get("service_mode") != "coordinator"
            or health.get("coordinator_status") != "active"
            or type(service_generation) is not int
            or service_generation <= 0
            or type(release_id) is not str
            or not release_id
        ):
            raise ManagedHostProbeError(
                "packaged host did not acquire managed service authority"
            )
        coordinator_status, coordinator, _ = _json_get(
            f"{base_url}/api/system/workflow-coordinator",
            token=token,
        )
        if (
            coordinator_status != 200
            or coordinator.get("state") != "running"
            or coordinator.get("thread_alive") is not True
            or coordinator.get("generation") != health["service_generation"]
        ):
            raise ManagedHostProbeError(
                "packaged workflow coordinator is not running"
            )
        index_status, index = _page_get(f"{base_url}/")
        if (
            index_status != 200
            or "__STOCKROOM_TOKEN__" not in index
            or "__API_BASE__" not in index
        ):
            raise ManagedHostProbeError(
                "packaged frontend is not served by the managed host"
            )
        update_status, update, _ = _json_get(
            f"{base_url}/api/update/check",
            token=token,
        )
        if (
            update_status != 200
            or update.get("channel") != "production"
            or update.get("current_release_id") != health["release_id"]
        ):
            raise ManagedHostProbeError(
                "packaged signed-release convergence is not mounted"
            )
        receipt.update(
            {
                "coordinator_state": coordinator["state"],
                "frontend_injected": True,
                "host_package_version": BUILD_IDENTITY.package_version,
                "host_protocol_version": BUILD_IDENTITY.protocol_version,
                "process_id": os.getpid(),
                "release_id": release_id,
                "schema": "stockroom-managed-host-launch/1",
                "service_generation": service_generation,
                "service_mode": health["service_mode"],
                "update_channel": update["channel"],
            }
        )

    restarted = run_windowed(open_window=inspect)
    if restarted:
        raise ManagedHostProbeError("managed-host probe unexpectedly requested restart")
    if not receipt:
        raise ManagedHostProbeError("managed-host probe produced no receipt")
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = receipt_path.with_name(f".{receipt_path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(
            receipt,
            ensure_ascii=True,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, receipt_path)


__all__ = ["ManagedHostProbeError", "run_managed_host_probe"]
