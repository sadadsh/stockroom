from __future__ import annotations

import shutil
import threading
import time
from pathlib import Path

import pytest

from stockroom.api.updater import AppUpdater
from stockroom.update import ActivationOutcome, ConvergencePhase, UpdateConvergenceService
from stockroom.vcs.repo import GitRepo

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")
_BACKGROUND_UPDATE_TIMEOUT_SECONDS = 15.0


def _origin_and_clone(tmp_path: Path, path: str) -> tuple[GitRepo, GitRepo]:
    origin = GitRepo(tmp_path / "origin")
    origin.init()
    source = origin.root / path
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("v1\n", encoding="utf-8")
    origin.commit("v1", [source])
    clone = GitRepo(tmp_path / "install")
    clone.clone_from(origin.root)
    return origin, clone


def _advance(origin: GitRepo, path: str) -> str:
    changed = origin.root / path
    changed.write_text("v2\n", encoding="utf-8")
    return origin.commit("v2", [changed])


def test_scheduled_service_adopts_frontend_without_closing_the_window(
    tmp_path: Path,
) -> None:
    path = "app/frontend-dist/index.html"
    origin, install = _origin_and_clone(tmp_path, path)
    target = _advance(origin, path)
    reloaded = threading.Event()
    restarted = threading.Event()
    service = UpdateConvergenceService(
        AppUpdater(
            install,
            uv_runner=lambda: None,
            restart=restarted.set,
            frontend_reload=reloaded.set,
        ),
        interval_seconds=1,
    )

    loop = service.start(initial_delay_seconds=0)
    try:
        assert reloaded.wait(_BACKGROUND_UPDATE_TIMEOUT_SECONDS)
        deadline = time.monotonic() + _BACKGROUND_UPDATE_TIMEOUT_SECONDS
        while (
            service.status()["convergence_phase"] != ConvergencePhase.CURRENT
            and time.monotonic() < deadline
        ):
            time.sleep(0.01)
        status = service.status()
    finally:
        loop.set()
        loop.join(timeout=_BACKGROUND_UPDATE_TIMEOUT_SECONDS)

    assert not loop.is_alive()
    assert not restarted.is_set()
    assert status["convergence_phase"] == ConvergencePhase.CURRENT
    assert status["current_revision"] == target[:12]
    assert status["target_revision"] == target[:12]
    assert status["state"] == "up_to_date"
    assert status["automatic_apply"] is True
    assert (install.root / path).read_text(encoding="utf-8") == "v2\n"


def test_backend_update_requests_automatic_process_handoff(tmp_path: Path) -> None:
    path = "app/backend/stockroom/example.py"
    origin, install = _origin_and_clone(tmp_path, path)
    target = _advance(origin, path)
    restarted = threading.Event()
    service = UpdateConvergenceService(
        AppUpdater(install, uv_runner=lambda: None, restart=restarted.set),
        interval_seconds=1,
    )

    status = service.run_once()

    assert restarted.is_set()
    assert status["convergence_phase"] == ConvergencePhase.RESTARTING
    assert status["current_revision"] == target[:12]


def test_prepulled_backend_revision_still_requests_process_handoff(
    tmp_path: Path,
) -> None:
    path = "app/backend/stockroom/example.py"
    origin, install = _origin_and_clone(tmp_path, path)
    running_revision = install.head()
    target = _advance(origin, path)
    assert install.pull_ff().updated
    assert install.head() == target
    restarted = threading.Event()
    service = UpdateConvergenceService(
        AppUpdater(install, uv_runner=lambda: None, restart=restarted.set),
        interval_seconds=1,
        running_revision=running_revision,
    )

    status = service.run_once()

    assert restarted.is_set()
    assert status["convergence_phase"] == ConvergencePhase.RESTARTING
    assert status["current_revision"] == target[:12]
    assert status["target_revision"] == target[:12]


def test_failed_dependency_activation_retries_without_repulling_or_false_current(
    tmp_path: Path,
) -> None:
    path = "app/backend/stockroom/example.py"
    origin, install = _origin_and_clone(tmp_path, path)
    target = _advance(origin, path)
    calls = {"uv": 0}
    restarted = threading.Event()

    def flaky_uv() -> None:
        calls["uv"] += 1
        if calls["uv"] == 1:
            raise RuntimeError("locked dependency install failed")

    service = UpdateConvergenceService(
        AppUpdater(install, uv_runner=flaky_uv, restart=restarted.set),
        interval_seconds=1,
    )
    first = service.run_once()

    assert first["convergence_phase"] == ConvergencePhase.FAILED
    assert first["state"] == ConvergencePhase.FAILED
    assert first["update_available"] is False
    assert first["current_revision"] != target[:12]
    assert first["target_revision"] == target[:12]
    assert "will retry automatically" in str(first["detail"])
    assert not restarted.is_set()

    second = service.run_once()

    assert calls["uv"] == 2
    assert restarted.is_set()
    assert second["convergence_phase"] == ConvergencePhase.RESTARTING
    assert second["current_revision"] == target[:12]


def test_dirty_development_checkout_is_observable_and_never_mutated(
    tmp_path: Path,
) -> None:
    path = "app/backend/stockroom/example.py"
    origin, install = _origin_and_clone(tmp_path, path)
    _advance(origin, path)
    local = install.root / path
    local.write_text("in progress\n", encoding="utf-8")
    service = UpdateConvergenceService(
        AppUpdater(install, uv_runner=lambda: None, restart=lambda: None),
        interval_seconds=1,
    )
    before = install.head()

    status = service.run_once()

    assert status["convergence_phase"] == ConvergencePhase.BLOCKED
    assert "uncommitted tracked" in str(status["detail"])
    assert install.head() == before
    assert local.read_text(encoding="utf-8") == "in progress\n"


def test_two_deliberately_stale_installs_converge_to_the_same_release(
    tmp_path: Path,
) -> None:
    path = "app/backend/stockroom/example.py"
    origin, first = _origin_and_clone(tmp_path, path)
    second = GitRepo(tmp_path / "second-install")
    second.clone_from(origin.root)
    old = first.head()
    target = _advance(origin, path)
    assert old != target and second.head() == old
    restarts = [threading.Event(), threading.Event()]

    first_status = UpdateConvergenceService(
        AppUpdater(first, uv_runner=lambda: None, restart=restarts[0].set),
        interval_seconds=1,
    ).run_once()
    second_status = UpdateConvergenceService(
        AppUpdater(second, uv_runner=lambda: None, restart=restarts[1].set),
        interval_seconds=1,
    ).run_once()

    assert all(event.is_set() for event in restarts)
    assert first.head() == second.head() == target
    assert first_status["current_revision"] == second_status["current_revision"] == target[:12]


def test_side_by_side_convergence_preserves_dirty_install_and_reports_active_release(
    tmp_path: Path,
) -> None:
    path = "app/backend/stockroom/example.py"
    origin, install = _origin_and_clone(tmp_path, path)
    old = install.head()
    target = _advance(origin, path)
    local = install.root / path
    local.write_text("valuable local fixture work\n", encoding="utf-8")
    active = {"revision": old}

    def activate(revision: str) -> ActivationOutcome:
        active["revision"] = revision
        return ActivationOutcome(True, revision)

    service = UpdateConvergenceService(
        AppUpdater(
            install,
            release_activation=activate,
            active_revision=lambda: active["revision"],
        ),
        interval_seconds=1,
    )

    status = service.run_once()

    assert active["revision"] == target
    assert status["convergence_phase"] == ConvergencePhase.CURRENT
    assert status["current_revision"] == target[:12]
    assert install.head() == old
    assert local.read_text(encoding="utf-8") == "valuable local fixture work\n"


def test_two_dirty_installs_converge_runtime_without_rewriting_either_checkout(
    tmp_path: Path,
) -> None:
    path = "app/backend/stockroom/example.py"
    origin, first = _origin_and_clone(tmp_path, path)
    second = GitRepo(tmp_path / "second-dirty-install")
    second.clone_from(origin.root)
    old = first.head()
    target = _advance(origin, path)
    first_file = first.root / path
    second_file = second.root / path
    first_file.write_text("device one local work\n", encoding="utf-8")
    second_file.write_text("device two local work\n", encoding="utf-8")
    active = [{"revision": old}, {"revision": old}]

    def updater(repo: GitRepo, slot: int) -> AppUpdater:
        def activate(revision: str) -> ActivationOutcome:
            active[slot]["revision"] = revision
            return ActivationOutcome(True, revision)

        return AppUpdater(
            repo,
            release_activation=activate,
            active_revision=lambda: active[slot]["revision"],
        )

    statuses = [
        UpdateConvergenceService(updater(first, 0), interval_seconds=1).run_once(),
        UpdateConvergenceService(updater(second, 1), interval_seconds=1).run_once(),
    ]

    assert [item["revision"] for item in active] == [target, target]
    assert [status["current_revision"] for status in statuses] == [target[:12], target[:12]]
    assert first.head() == second.head() == old
    assert first_file.read_text(encoding="utf-8") == "device one local work\n"
    assert second_file.read_text(encoding="utf-8") == "device two local work\n"


def test_background_loop_survives_an_unhandled_check_failure_and_can_be_joined(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, install = _origin_and_clone(tmp_path, "app/backend/stockroom/example.py")
    service = UpdateConvergenceService(
        AppUpdater(install),
        interval_seconds=1,
        health_interval_seconds=0.25,
    )
    attempts = 0

    def broken_check() -> dict[str, object]:
        nonlocal attempts
        attempts += 1
        raise RuntimeError("https://secret@example.invalid/private")

    monkeypatch.setattr(service, "run_once", broken_check)
    loop = service.start(initial_delay_seconds=0)
    deadline = time.monotonic() + 2
    while service.status()["convergence_phase"] != ConvergencePhase.FAILED:
        assert time.monotonic() < deadline
        time.sleep(0.01)

    status = service.status()
    assert attempts == 1
    assert loop.is_alive()
    assert "secret@example" not in str(status["detail"])
    assert "will retry" in str(status["detail"])
    assert service.start(initial_delay_seconds=0) is loop

    loop.set()
    loop.join(timeout=2)
    assert not loop.is_alive()
