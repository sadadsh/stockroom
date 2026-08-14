"""Isolated Windows source-development host with Vite HMR.

This entry point is deliberately separate from installed Stockroom. It runs only a
selected local checkout, owns development-only state, never pulls Git, and restarts
its source child when backend Python changes. Production packaging never imports it.
"""

from __future__ import annotations

import argparse
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
from collections.abc import Mapping
from pathlib import Path
from urllib.error import URLError
from urllib.parse import quote
from urllib.request import urlopen

from stockroom.host.windows_job import WindowsProcessJob, launch_in_windows_job

_RESTART_EXIT = 75
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
_DEVELOPMENT_AUTHORITY_SCOPE = "DevelopmentApplicationService"
_DEVELOPMENT_AUMID = "Stockroom.Development.Unpackaged"
_DEVELOPMENT_TITLE = "Stockroom Development"
_SOURCE_POLL_SECONDS = 0.35


class DevelopmentHostError(RuntimeError):
    """The isolated development host cannot start safely."""


def _absolute_path(path: Path) -> Path:
    return Path(os.path.abspath(path))


def development_state_root(environment: Mapping[str, str]) -> Path:
    local_app_data = environment.get("LOCALAPPDATA", "").strip()
    if not local_app_data:
        raise DevelopmentHostError("LOCALAPPDATA is required for Stockroom Development")
    return _absolute_path(Path(local_app_data) / "Stockroom Development")


def _is_reparse_point(path: Path) -> bool:
    if path.is_symlink():
        return True
    is_junction = getattr(path, "is_junction", None)
    if callable(is_junction) and is_junction():
        return True
    try:
        return bool(path.stat(follow_symlinks=False).st_file_attributes & 0x400)
    except (AttributeError, OSError):
        return False


def validate_development_state_layout(state_root: Path) -> None:
    state = _absolute_path(state_root)
    for path in (
        state,
        state / "Config",
        state / "Service State",
        state / "Logs",
        state / "Libraries",
        state / "Vite Environment",
    ):
        if path.exists() and _is_reparse_point(path):
            raise DevelopmentHostError(
                f"development state cannot use a junction or symbolic link: {path}"
            )


def validate_repository_root(path: Path) -> Path:
    root = Path(path).resolve()
    required = (
        root / "pyproject.toml",
        root / "uv.lock",
        root / "app" / "backend" / "stockroom" / "__init__.py",
        root / "app" / "frontend" / "package.json",
        root / "app" / "frontend" / "node_modules" / "vite" / "bin" / "vite.js",
        root / ".venv" / "Scripts" / "python.exe",
    )
    missing = [str(item) for item in required if not item.exists()]
    if missing:
        raise DevelopmentHostError(
            "development dependencies are not ready; run "
            "scripts\\Setup-Stockroom-Development.ps1 first; missing: "
            + ", ".join(missing)
        )
    return root


def development_environment(
    repository_root: Path,
    state_root: Path,
    source: Mapping[str, str],
) -> dict[str, str]:
    root = Path(repository_root).resolve()
    state = _absolute_path(state_root)
    environment = {
        key: value
        for key, value in source.items()
        if not key.startswith("STOCKROOM_")
    }
    local_python_path = os.pathsep.join((str(root / "app" / "backend"), str(root)))
    environment.update(
        {
            "PYTHONPATH": local_python_path,
            "STOCKROOM_UPDATE_MODE": "development_source",
            "STOCKROOM_CONFIG_DIR": str(state / "Config"),
            "STOCKROOM_SERVICE_DATA_ROOT": str(state / "Service State"),
            "STOCKROOM_DEVELOPMENT_LOG_DIR": str(state / "Logs"),
            "STOCKROOM_LIBRARY_ROOT_BOUNDARY": str(state / "Libraries"),
            "STOCKROOM_DEV_ENV_DIR": str(state / "Vite Environment"),
            "STOCKROOM_DEV_BOOTSTRAP": "1",
        }
    )
    return environment


def vite_environment(
    source: Mapping[str, str],
    *,
    backend_url: str,
) -> dict[str, str]:
    environment = dict(source)
    environment.pop("VITE_API_BASE", None)
    environment.pop("VITE_API_TOKEN", None)
    environment["STOCKROOM_DEV_BACKEND_URL"] = backend_url
    return environment


def development_renderer_url(vite_url: str, token: str) -> str:
    if not vite_url.startswith("http://127.0.0.1:") or not token:
        raise DevelopmentHostError("development renderer identity is invalid")
    return f"{vite_url}/#__stockroom_development_token={quote(token, safe='')}"


def source_snapshot(repository_root: Path) -> tuple[tuple[str, int, int], ...]:
    root = Path(repository_root).resolve()
    candidates = list((root / "app" / "backend" / "stockroom").rglob("*.py"))
    candidates.extend((root / name) for name in ("pyproject.toml", "uv.lock"))
    snapshot: list[tuple[str, int, int]] = []
    for path in candidates:
        if "__pycache__" in path.parts:
            continue
        try:
            if not path.is_file():
                continue
            stat = path.stat()
        except OSError:
            # Editors commonly replace a file atomically. A transiently absent path is a
            # changed snapshot and therefore correctly causes one clean source restart.
            continue
        snapshot.append(
            (path.relative_to(root).as_posix(), stat.st_mtime_ns, stat.st_size)
        )
    return tuple(sorted(snapshot))


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _wait_for_vite(process: subprocess.Popen[bytes], url: str, timeout: float = 30.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        exit_code = process.poll()
        if exit_code is not None:
            raise DevelopmentHostError(
                f"Vite stopped before readiness with exit code {exit_code}"
            )
        try:
            with urlopen(url, timeout=0.5) as response:  # noqa: S310 - fixed loopback URL
                if 200 <= response.status < 500:
                    return
        except (OSError, URLError):
            pass
        time.sleep(0.05)
    raise DevelopmentHostError("Vite did not become ready within 30 seconds")


def _stop_job(
    process: subprocess.Popen[bytes],
    job: WindowsProcessJob,
    *,
    timeout: float = 8.0,
) -> None:
    try:
        job.terminate_all(timeout=timeout)
    finally:
        try:
            process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=timeout)


def _request_window_close_until_stopped(stop: threading.Event) -> None:
    from stockroom.host.run import _close_active_window

    while not stop.wait(0.1):
        try:
            _close_active_window()
            return
        except RuntimeError:
            continue


def _run_session(repository_root: Path, state_root: Path) -> int:
    from stockroom.host.run import run_windowed
    from stockroom.host.window import run_window

    baseline = source_snapshot(repository_root)
    changed = threading.Event()
    stop = threading.Event()

    def watch_backend() -> None:
        while not stop.wait(_SOURCE_POLL_SECONDS):
            if source_snapshot(repository_root) != baseline:
                changed.set()
                _request_window_close_until_stopped(stop)
                return

    watcher = threading.Thread(
        target=watch_backend,
        name="stockroom-development-source-watcher",
        daemon=True,
    )
    watcher.start()

    def open_development_window(backend_url: str, token: str) -> None:
        node = shutil.which("node.exe") or shutil.which("node")
        if not node:
            raise DevelopmentHostError("Node.js is unavailable; run development setup first")
        port = _free_port()
        vite_url = f"http://127.0.0.1:{port}"
        vite_script = repository_root / "app" / "frontend" / "node_modules" / "vite" / "bin" / "vite.js"
        vite_process, vite_job = launch_in_windows_job(
            [
                node,
                str(vite_script),
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
                "--strictPort",
            ],
            cwd=repository_root / "app" / "frontend",
            environment=vite_environment(
                os.environ,
                backend_url=backend_url,
            ),
            creationflags=_NO_WINDOW,
            diagnostic_path=state_root / "Logs" / "Vite.log",
        )
        vite_stopped = threading.Event()
        vite_watcher_started = False

        def watch_vite() -> None:
            while not stop.wait(0.1):
                if vite_process.poll() is not None:
                    vite_stopped.set()
                    _request_window_close_until_stopped(stop)
                    return

        vite_watcher = threading.Thread(
            target=watch_vite,
            name="stockroom-development-vite-watcher",
            daemon=True,
        )
        try:
            _wait_for_vite(vite_process, vite_url)
            if changed.is_set():
                return
            vite_watcher.start()
            vite_watcher_started = True
            run_window(
                vite_url,
                None,
                initial_url=development_renderer_url(vite_url, token),
                title=_DEVELOPMENT_TITLE,
                app_user_model_id=_DEVELOPMENT_AUMID,
            )
            if vite_stopped.is_set() and not changed.is_set():
                raise DevelopmentHostError("Vite stopped while Stockroom Development was open")
        finally:
            _stop_job(vite_process, vite_job)
            if vite_watcher_started:
                vite_watcher.join(timeout=1.0)

    try:
        run_windowed(
            open_window=open_development_window,
            source_service_state_root=state_root / "Service State",
            source_authority_scope=_DEVELOPMENT_AUTHORITY_SCOPE,
            enable_source_convergence=False,
        )
    finally:
        stop.set()
        watcher.join(timeout=1.0)
    return _RESTART_EXIT if changed.is_set() else 0


def _run_supervisor(repository_root: Path, state_root: Path) -> int:
    environment = development_environment(repository_root, state_root, os.environ)
    logs = state_root / "Logs"
    logs.mkdir(parents=True, exist_ok=True)
    command = [
        str(repository_root / ".venv" / "Scripts" / "python.exe"),
        "-m",
        "stockroom.host.development",
        "--repository-root",
        str(repository_root),
        "--state-root",
        str(state_root),
        "--session",
    ]
    while True:
        process, job = launch_in_windows_job(
            command,
            cwd=repository_root,
            environment=environment,
            creationflags=_NO_WINDOW,
            diagnostic_path=logs / "Backend.log",
        )
        try:
            exit_code = process.wait()
        except KeyboardInterrupt:
            _stop_job(process, job)
            return 130
        else:
            _stop_job(process, job)
        if exit_code != _RESTART_EXIT:
            return int(exit_code)


def _parse_arguments(arguments: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run isolated Stockroom Development")
    parser.add_argument("--repository-root", required=True, type=Path)
    parser.add_argument("--state-root", required=True, type=Path)
    parser.add_argument("--session", action="store_true")
    return parser.parse_args(arguments)


def main(arguments: list[str] | None = None) -> int:
    if os.name != "nt":
        raise DevelopmentHostError("Stockroom Development requires native Windows")
    parsed = _parse_arguments(arguments)
    repository_root = validate_repository_root(parsed.repository_root)
    state_root = _absolute_path(parsed.state_root)
    expected_state_root = development_state_root(os.environ)
    if os.path.normcase(str(state_root)) != os.path.normcase(str(expected_state_root)):
        raise DevelopmentHostError(
            f"development state must remain isolated at {expected_state_root}"
        )
    validate_development_state_layout(state_root)
    state_root.mkdir(parents=True, exist_ok=True)
    validate_development_state_layout(state_root)
    for child in ("Config", "Service State", "Logs", "Libraries", "Vite Environment"):
        (state_root / child).mkdir(parents=True, exist_ok=True)
    validate_development_state_layout(state_root)
    if parsed.session:
        return _run_session(repository_root, state_root)
    return _run_supervisor(repository_root, state_root)


if __name__ == "__main__":
    raise SystemExit(main())
