from __future__ import annotations

import os
import shutil
import socket
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.request import Request, urlopen

import pytest

from stockroom.host import development as development_module
from stockroom.host.development import (
    DevelopmentHostError,
    _run_supervisor,
    _stop_job,
    development_environment,
    development_renderer_url,
    development_state_root,
    source_snapshot,
    validate_development_state_layout,
    validate_repository_root,
    vite_environment,
)
from stockroom.host.windows_job import launch_in_windows_job

_REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


def _ready_repository(root: Path) -> Path:
    for relative in (
        "pyproject.toml",
        "uv.lock",
        "app/backend/stockroom/__init__.py",
        "app/frontend/package.json",
        "app/frontend/node_modules/vite/bin/vite.js",
        ".venv/Scripts/python.exe",
    ):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("fixture\n", encoding="utf-8")
    return root


def test_development_state_is_visibly_separate_from_production(tmp_path: Path) -> None:
    root = development_state_root({"LOCALAPPDATA": str(tmp_path)})

    assert root == (tmp_path / "Stockroom Development").resolve()


def test_development_state_requires_windows_local_app_data() -> None:
    with pytest.raises(DevelopmentHostError, match="LOCALAPPDATA"):
        development_state_root({})


def test_development_environment_discards_inherited_product_authority(tmp_path: Path) -> None:
    repository = tmp_path / "repo"
    state = tmp_path / "development-state"

    environment = development_environment(
        repository,
        state,
        {
            "PATH": "tools",
            "PYTHONPATH": "existing",
            "STOCKROOM_CONFIG_DIR": "production-config",
            "STOCKROOM_TUF_ROOT_BASE64": "production-trust",
            "STOCKROOM_UPDATE_MODE": "production",
        },
    )

    assert environment["PATH"] == "tools"
    assert environment["STOCKROOM_UPDATE_MODE"] == "development_source"
    assert environment["STOCKROOM_CONFIG_DIR"] == str(state.resolve() / "Config")
    assert environment["STOCKROOM_SERVICE_DATA_ROOT"] == str(
        state.resolve() / "Service State"
    )
    assert environment["STOCKROOM_DEVELOPMENT_LOG_DIR"] == str(state.resolve() / "Logs")
    assert environment["STOCKROOM_LIBRARY_ROOT_BOUNDARY"] == str(
        state.resolve() / "Libraries"
    )
    assert environment["STOCKROOM_DEV_ENV_DIR"] == str(
        state.resolve() / "Vite Environment"
    )
    assert environment["STOCKROOM_DEV_BOOTSTRAP"] == "1"
    assert "production-config" not in environment.values()
    assert "production-trust" not in environment.values()
    assert environment["PYTHONPATH"] == os.pathsep.join(
        (str(repository.resolve() / "app" / "backend"), str(repository.resolve()))
    )


def test_development_renderer_bootstraps_without_sending_token_to_vite() -> None:
    url = development_renderer_url("http://127.0.0.1:5173", "secret/value")

    assert url == (
        "http://127.0.0.1:5173/"
        "#__stockroom_development_token=secret%2Fvalue"
    )


def test_vite_proxy_keeps_the_bearer_secret_out_of_vite_build_variables() -> None:
    environment = vite_environment(
        {
            "PATH": "tools",
            "VITE_API_BASE": "http://wrong.invalid",
            "VITE_API_TOKEN": "would-be-browser-secret",
        },
        backend_url="http://127.0.0.1:43210",
    )

    assert environment["PATH"] == "tools"
    assert "VITE_API_BASE" not in environment
    assert "VITE_API_TOKEN" not in environment
    assert environment["STOCKROOM_DEV_BACKEND_URL"] == "http://127.0.0.1:43210"
    assert "STOCKROOM_DEV_API_TOKEN" not in environment


def test_development_state_refuses_a_windows_junction(tmp_path: Path) -> None:
    if os.name != "nt":
        pytest.skip("Windows junction proof")
    target = tmp_path / "target"
    target.mkdir()
    state = tmp_path / "Stockroom Development"
    result = subprocess.run(
        ["cmd.exe", "/d", "/c", "mklink", "/J", str(state), str(target)],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        pytest.skip("junction creation is unavailable")

    with pytest.raises(DevelopmentHostError, match="junction or symbolic link"):
        validate_development_state_layout(state)


def test_repository_validation_requires_prepared_dependencies(tmp_path: Path) -> None:
    with pytest.raises(DevelopmentHostError, match="Setup-Stockroom-Development"):
        validate_repository_root(tmp_path)

    ready = _ready_repository(tmp_path)
    assert validate_repository_root(ready) == ready.resolve()


def test_backend_snapshot_detects_added_source(tmp_path: Path) -> None:
    package = tmp_path / "app" / "backend" / "stockroom"
    package.mkdir(parents=True)
    (package / "first.py").write_text("FIRST = 1\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
    (tmp_path / "uv.lock").write_text("version = 1\n", encoding="utf-8")
    before = source_snapshot(tmp_path)

    (package / "second.py").write_text("SECOND = 2\n", encoding="utf-8")

    assert source_snapshot(tmp_path) != before


def test_supervisor_restarts_once_then_closes_every_child_job(
    monkeypatch,
    tmp_path: Path,
) -> None:
    exit_codes = iter((75, 0))
    jobs: list[object] = []

    class _Process:
        def __init__(self, exit_code):
            self.exit_code = exit_code

        def wait(self, timeout=None):
            del timeout
            return self.exit_code

        def kill(self):
            raise AssertionError("bounded job shutdown should own cleanup")

    class _Job:
        def __init__(self):
            self.terminated = 0

        def terminate_all(self, *, timeout):
            assert timeout == 8.0
            self.terminated += 1

    def launch(*args, **kwargs):
        del args, kwargs
        job = _Job()
        jobs.append(job)
        return _Process(next(exit_codes)), job

    monkeypatch.setattr(development_module, "launch_in_windows_job", launch)
    monkeypatch.setattr(
        development_module,
        "development_environment",
        lambda repository, state, source: dict(source),
    )

    assert _run_supervisor(tmp_path, tmp_path / "state") == 0
    assert [job.terminated for job in jobs] == [1, 1]


def test_real_vite_proxy_forwards_the_host_injected_authorization(tmp_path: Path) -> None:
    if os.name != "nt":
        pytest.skip("Windows process-job proxy proof")
    node = shutil.which("node.exe")
    if not node:
        pytest.skip("Node.js is unavailable")
    vite_script = (
        _REPOSITORY_ROOT
        / "app"
        / "frontend"
        / "node_modules"
        / "vite"
        / "bin"
        / "vite.js"
    )
    if not vite_script.is_file():
        pytest.skip("frontend dependencies are unavailable")

    observed: list[str] = []
    vite_environment_root = tmp_path / "Vite Environment"
    vite_environment_root.mkdir()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802 - stdlib callback contract
            if self.path != "/api/development-probe":
                self.send_response(404)
                self.end_headers()
                return
            observed.append(self.headers.get("Authorization", ""))
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"ok")

        def log_message(self, format, *args):
            del format, args

    backend = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    backend_thread = threading.Thread(target=backend.serve_forever, daemon=True)
    backend_thread.start()
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        vite_port = int(listener.getsockname()[1])
    vite_url = f"http://127.0.0.1:{vite_port}"
    process = None
    job = None
    try:
        process, job = launch_in_windows_job(
            [
                node,
                str(vite_script),
                "--host",
                "127.0.0.1",
                "--port",
                str(vite_port),
                "--strictPort",
            ],
            cwd=_REPOSITORY_ROOT / "app" / "frontend",
            environment=vite_environment(
                {
                    **os.environ,
                    "STOCKROOM_DEV_ENV_DIR": str(vite_environment_root),
                    "STOCKROOM_DEV_BOOTSTRAP": "1",
                },
                backend_url=f"http://127.0.0.1:{backend.server_port}",
            ),
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            diagnostic_path=tmp_path / "Vite.log",
        )
        deadline = time.monotonic() + 30.0
        while True:
            try:
                with urlopen(vite_url, timeout=1.0) as response:
                    index = response.read().decode("utf-8")
                assert "__stockroom_development_token" in index
                assert index.index("__stockroom_development_token") < index.index("/src/main.tsx")
                request = Request(
                    f"{vite_url}/api/development-probe",
                    headers={"Authorization": "Bearer session-secret"},
                )
                with urlopen(request, timeout=1.0) as response:
                    assert response.read() == b"ok"
                break
            except OSError:
                if time.monotonic() >= deadline:
                    pytest.fail("Vite development proxy did not become ready")
                time.sleep(0.05)
        assert observed == ["Bearer session-secret"]
    finally:
        if process is not None and job is not None:
            _stop_job(process, job)
        backend.shutdown()
        backend.server_close()
        backend_thread.join(timeout=2.0)


def test_vite_config_has_loopback_token_hiding_proxy() -> None:
    source = (_REPOSITORY_ROOT / "app" / "frontend" / "vite.config.ts").read_text(
        encoding="utf-8"
    )

    assert 'target.hostname !== "127.0.0.1"' in source
    assert "STOCKROOM_DEV_API_TOKEN" not in source
    assert "VITE_API_TOKEN" not in source
    assert "envDir: process.env.STOCKROOM_DEV_ENV_DIR" in source


def test_startup_never_provisions_or_pulls_source() -> None:
    launcher = (
        _REPOSITORY_ROOT / "scripts" / "Start-Stockroom-Development.ps1"
    ).read_text(encoding="utf-8")
    development = (
        _REPOSITORY_ROOT / "app" / "backend" / "stockroom" / "host" / "development.py"
    ).read_text(encoding="utf-8")

    assert "uv sync" not in launcher
    assert "npm.cmd" not in launcher
    assert "git pull" not in development.casefold()
    assert "enable_source_convergence=False" in development
    assert "run_window(\n                vite_url,\n                None," in development
    vite_config = (
        _REPOSITORY_ROOT / "app" / "frontend" / "vite.config.ts"
    ).read_text(encoding="utf-8")
    assert "developmentBootstrapPlugin()" in vite_config
    assert 'sessionStorage.setItem("stockroom-development-token", token)' in vite_config


def test_shortcut_requires_an_explicit_checkout() -> None:
    installer = (
        _REPOSITORY_ROOT / "scripts" / "Install-Stockroom-DevelopmentShortcut.ps1"
    ).read_text(encoding="utf-8")

    assert "[Parameter(Mandatory)]" in installer
    assert "Stockroom Development.lnk" in installer
