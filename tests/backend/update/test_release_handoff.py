from __future__ import annotations

import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest
from fastapi import FastAPI

from stockroom.api.serve import pick_free_port
from stockroom.api.updater import AppUpdater
from stockroom.host.proxy import SwitchableBackendProxy
from stockroom.host.run import _serve_in_thread
from stockroom.update.convergence import ConvergencePhase, UpdateConvergenceService
from stockroom.update.handoff import (
    BackendEndpoint,
    SeamlessBackendHandoff,
    health_probe,
)
from stockroom.update.releases import CandidateIntegrityError, GitReleaseStore
from stockroom.vcs.repo import GitRepo


def _release_repos(tmp_path: Path) -> tuple[GitRepo, GitRepo, str]:
    origin = GitRepo(tmp_path / "origin")
    origin.init()
    runtime = origin.root / "runtime.txt"
    runtime.write_text("v1\n", encoding="utf-8")
    origin.commit("v1", [runtime])
    install = GitRepo(tmp_path / "install")
    install.clone_from(origin.root)
    runtime.write_text("v2\n", encoding="utf-8")
    target = origin.commit("v2", [runtime])
    assert install.fetch()[0]
    return origin, install, target


def _port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _server(revision: str) -> BackendEndpoint:
    port = _port()
    code = """
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import sys
class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/api/health":
            self.send_response(200); self.end_headers(); self.wfile.write(b'{"ok":true}')
        else:
            self.send_response(404); self.end_headers()
    def log_message(self, *args): pass
ThreadingHTTPServer(("127.0.0.1", int(sys.argv[1])), Handler).serve_forever()
"""
    process = subprocess.Popen(
        [sys.executable, "-c", code, str(port)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    endpoint = BackendEndpoint(revision, f"http://127.0.0.1:{port}", process)
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and not health_probe(endpoint.base_url, 0.1):
        time.sleep(0.02)
    assert health_probe(endpoint.base_url, 0.5)
    return endpoint


def _stop(endpoint: BackendEndpoint) -> None:
    if endpoint.process is not None and endpoint.process.poll() is None:
        endpoint.process.terminate()
        endpoint.process.wait(timeout=5)


def test_side_by_side_stage_preserves_dirty_live_checkout_and_verifies_exact_tree(
    tmp_path: Path,
) -> None:
    _origin, install, target = _release_repos(tmp_path)
    live = install.root / "runtime.txt"
    live.write_text("valuable in-progress edit\n", encoding="utf-8")
    before = install.head()
    store = GitReleaseStore(
        install,
        tmp_path / "releases",
        required_runtime_files=("runtime.txt",),
    )

    candidate = store.stage(target)

    assert install.head() == before
    assert live.read_text(encoding="utf-8") == "valuable in-progress edit\n"
    assert (candidate.root / "runtime.txt").read_text(encoding="utf-8") == "v2\n"
    assert store.verify(candidate).revision == target


def test_corrupt_candidate_is_rejected_then_rebuilt_from_git(tmp_path: Path) -> None:
    _origin, install, target = _release_repos(tmp_path)
    store = GitReleaseStore(
        install,
        tmp_path / "releases",
        required_runtime_files=("runtime.txt",),
    )
    candidate = store.stage(target)
    (candidate.root / "runtime.txt").write_text("tampered\n", encoding="utf-8")

    with pytest.raises(CandidateIntegrityError, match="differ"):
        store.verify(candidate)

    rebuilt = store.stage(target)
    assert (rebuilt.root / "runtime.txt").read_text(encoding="utf-8") == "v2\n"
    assert rebuilt.tree_digest == candidate.tree_digest


def test_release_store_prunes_only_obsolete_private_worktrees(tmp_path: Path) -> None:
    origin, install, target = _release_repos(tmp_path)
    store = GitReleaseStore(
        install,
        tmp_path / "releases",
        required_runtime_files=("runtime.txt",),
    )
    first = store.stage(target)
    origin_file = origin.root / "runtime.txt"
    origin_file.write_text("v3\n", encoding="utf-8")
    newest = origin.commit("v3", [origin_file])
    assert install.fetch()[0]
    second = store.stage(newest)
    live_head = install.head()

    store.prune({newest})

    assert not first.root.exists()
    assert second.root.exists()
    assert install.head() == live_head
    assert (install.root / "runtime.txt").read_text(encoding="utf-8") == "v1\n"


def test_real_process_handoff_keeps_old_endpoint_and_rolls_back_after_worker_death(
    tmp_path: Path,
) -> None:
    _origin, install, target = _release_repos(tmp_path)
    store = GitReleaseStore(
        install,
        tmp_path / "releases",
        required_runtime_files=("runtime.txt",),
    )
    original = _server(install.head())
    spawned: list[BackendEndpoint] = []
    navigations: list[str] = []

    def spawn(candidate):
        endpoint = _server(candidate.revision)
        spawned.append(endpoint)
        return BackendEndpoint(
            candidate.revision,
            endpoint.base_url,
            endpoint.process,
            candidate,
        )

    handoff = SeamlessBackendHandoff(
        store,
        original_revision=install.head(),
        original_base_url=original.base_url,
        prepare=lambda _root: None,
        spawn=spawn,
        adopt=navigations.append,
        startup_timeout_seconds=3,
        probe_interval_seconds=0,
    )
    try:
        activated = handoff.activate(target)
        assert activated.ok
        assert navigations == [spawned[0].base_url]
        assert handoff.active_revision == target

        assert spawned[0].process is not None
        spawned[0].process.terminate()
        spawned[0].process.wait(timeout=5)
        rolled_back = handoff.verify_active()

        assert not rolled_back.ok
        assert rolled_back.rolled_back
        assert handoff.active_revision == install.head()
        assert navigations[-1] == original.base_url
        assert health_probe(original.base_url)
    finally:
        handoff.close()
        _stop(original)
        for endpoint in spawned:
            _stop(endpoint)


def test_production_proxy_topology_can_reach_bundled_fallback_after_worker_death(
    tmp_path: Path,
) -> None:
    """The stable URL must be switched local before it can prove the local fallback healthy."""
    _origin, install, target = _release_repos(tmp_path)
    store = GitReleaseStore(
        install,
        tmp_path / "releases",
        required_runtime_files=("runtime.txt",),
    )
    bundled = FastAPI()

    @bundled.get("/api/health")
    def bundled_health():
        return {"ok": True}

    proxy = SwitchableBackendProxy(bundled)
    stable_port = pick_free_port()
    stable_url = f"http://127.0.0.1:{stable_port}"
    proxy_server, proxy_thread = _serve_in_thread(proxy, stable_port)
    spawned: list[BackendEndpoint] = []

    def spawn(candidate):
        endpoint = _server(candidate.revision)
        spawned.append(endpoint)
        return BackendEndpoint(
            candidate.revision,
            endpoint.base_url,
            endpoint.process,
            candidate,
        )

    def adopt(target_url: str) -> None:
        proxy.switch(None if target_url == stable_url else target_url)

    handoff = SeamlessBackendHandoff(
        store,
        original_revision=install.head(),
        original_base_url=stable_url,
        prepare=lambda _root: None,
        spawn=spawn,
        adopt=adopt,
        startup_timeout_seconds=3,
        probe_interval_seconds=0,
    )
    try:
        assert health_probe(stable_url)
        assert handoff.activate(target).ok
        assert health_probe(stable_url)

        assert spawned[0].process is not None
        spawned[0].process.terminate()
        spawned[0].process.wait(timeout=5)
        assert not health_probe(stable_url, 0.2)

        rolled_back = handoff.verify_active()

        assert not rolled_back.ok
        assert rolled_back.rolled_back
        assert handoff.active_revision == install.head()
        assert proxy.target is None
        assert health_probe(stable_url)
    finally:
        handoff.close()
        proxy_server.should_exit = True
        proxy_thread.join(timeout=5)
        for endpoint in spawned:
            _stop(endpoint)


def test_failure_injected_after_dependency_prepare_never_adopts_candidate(
    tmp_path: Path,
) -> None:
    _origin, install, target = _release_repos(tmp_path)
    store = GitReleaseStore(
        install,
        tmp_path / "releases",
        required_runtime_files=("runtime.txt",),
    )
    navigations: list[str] = []

    def corrupt(root: Path) -> None:
        (root / "runtime.txt").write_text("dependency tool corrupted tracked bytes\n")

    handoff = SeamlessBackendHandoff(
        store,
        original_revision=install.head(),
        original_base_url="http://127.0.0.1:1",
        prepare=corrupt,
        spawn=lambda _candidate: pytest.fail("corrupt candidate must never start"),
        adopt=navigations.append,
        probe=lambda _url: True,
        startup_timeout_seconds=1,
        probe_interval_seconds=0,
    )

    outcome = handoff.activate(target)

    assert not outcome.ok
    assert not outcome.rolled_back
    assert navigations == []
    assert handoff.active_revision == install.head()
    assert (install.root / "runtime.txt").read_text(encoding="utf-8") == "v1\n"


def test_background_health_monitor_rolls_back_dead_worker_without_window_close(
    tmp_path: Path,
) -> None:
    _origin, install, target = _release_repos(tmp_path)
    store = GitReleaseStore(
        install,
        tmp_path / "releases",
        required_runtime_files=("runtime.txt",),
    )
    original = _server(install.head())
    spawned: list[BackendEndpoint] = []
    navigations: list[str] = []

    def spawn(candidate):
        endpoint = _server(candidate.revision)
        spawned.append(endpoint)
        return BackendEndpoint(
            candidate.revision,
            endpoint.base_url,
            endpoint.process,
            candidate,
        )

    handoff = SeamlessBackendHandoff(
        store,
        original_revision=install.head(),
        original_base_url=original.base_url,
        prepare=lambda _root: None,
        spawn=spawn,
        adopt=navigations.append,
        startup_timeout_seconds=3,
        probe_interval_seconds=0,
    )
    service = UpdateConvergenceService(
        AppUpdater(
            install,
            release_activation=handoff.activate,
            active_revision=lambda: handoff.active_revision,
            active_health=handoff.verify_active,
        ),
        interval_seconds=2,
        health_interval_seconds=0.25,
    )
    stop = service.start(initial_delay_seconds=0)
    try:
        deadline = time.monotonic() + 8
        while handoff.active_revision != target and time.monotonic() < deadline:
            time.sleep(0.02)
        assert handoff.active_revision == target
        assert spawned[0].process is not None
        spawned[0].process.terminate()
        spawned[0].process.wait(timeout=5)

        while (
            service.status()["convergence_phase"] != ConvergencePhase.ROLLED_BACK
            and time.monotonic() < deadline
        ):
            time.sleep(0.02)

        assert service.status()["convergence_phase"] == ConvergencePhase.ROLLED_BACK
        assert handoff.active_revision == install.head()
        assert navigations[-1] == original.base_url
    finally:
        stop.set()
        handoff.close()
        _stop(original)
        for endpoint in spawned:
            _stop(endpoint)


def test_last_verified_release_restores_offline_before_the_window_opens(
    tmp_path: Path,
) -> None:
    _origin, install, target = _release_repos(tmp_path)
    store = GitReleaseStore(
        install,
        tmp_path / "releases",
        required_runtime_files=("runtime.txt",),
    )
    original = _server(install.head())
    spawned: list[BackendEndpoint] = []

    def spawn(candidate):
        endpoint = _server(candidate.revision)
        spawned.append(endpoint)
        return BackendEndpoint(
            candidate.revision,
            endpoint.base_url,
            endpoint.process,
            candidate,
        )

    first = SeamlessBackendHandoff(
        store,
        original_revision=install.head(),
        original_base_url=original.base_url,
        prepare=lambda _root: None,
        spawn=spawn,
        adopt=lambda _url: None,
        probe_interval_seconds=0,
    )
    assert first.activate(target).ok
    first.close()

    navigations: list[str] = []
    restarted = SeamlessBackendHandoff(
        store,
        original_revision=install.head(),
        original_base_url=original.base_url,
        prepare=lambda _root: None,
        spawn=spawn,
        adopt=navigations.append,
        probe_interval_seconds=0,
    )
    try:
        restored = restarted.restore_last_active()

        assert restored.ok
        assert restarted.active_revision == target
        assert health_probe(restarted.active_base_url)
        assert navigations == []  # the host opens this URL directly; no visible reload
        assert install.head() != target  # no fetch/pull of the dirty-capable live tree
    finally:
        restarted.close()
        _stop(original)
        for endpoint in spawned:
            _stop(endpoint)
