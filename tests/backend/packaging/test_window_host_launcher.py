from __future__ import annotations

import sys
from pathlib import Path

import pytest

import packaging.stockroom_launcher as launcher
from stockroom.host import window_process
from stockroom.host.window_process import WindowHostArguments, WindowHostError

_PIPE_NAME = "Stockroom.WindowHandoff." + "a" * 32


def _argv() -> list[str]:
    return [
        "Stockroom.exe",
        "--window-host",
        "--handoff-pipe",
        _PIPE_NAME,
        "--parent-pid",
        "111",
    ]


def test_frozen_launcher_dispatches_the_exact_window_host_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepared: list[bool] = []
    dispatched: list[WindowHostArguments] = []
    monkeypatch.setattr(
        launcher,
        "_prepare_runtime",
        lambda *, needs_window: prepared.append(needs_window),
    )
    monkeypatch.setattr(
        window_process,
        "run_window_host",
        dispatched.append,
    )
    monkeypatch.setattr(sys, "argv", _argv())

    launcher._dispatch()

    assert prepared == [True]
    assert dispatched == [
        WindowHostArguments(
            pipe_name=_PIPE_NAME,
            parent_process_id=111,
        )
    ]


def test_malformed_window_host_argv_fails_before_webview_runtime_preparation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepared: list[bool] = []
    monkeypatch.setattr(
        launcher,
        "_prepare_runtime",
        lambda *, needs_window: prepared.append(needs_window),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "Stockroom.exe",
            "--window-host",
            "--handoff-pipe",
            _PIPE_NAME,
            "--parent-pid",
            "111",
            "--unexpected",
        ],
    )

    with pytest.raises(WindowHostError, match="arguments are invalid"):
        launcher._dispatch()

    assert prepared == []


def test_window_host_failure_is_noninteractive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: list[tuple[str, bool]] = []

    def fail_dispatch() -> None:
        raise RuntimeError("window child exploded")

    monkeypatch.setattr(launcher, "_dispatch", fail_dispatch)
    monkeypatch.setattr(
        launcher,
        "_fatal",
        lambda message, *, interactive: observed.append((message, interactive)),
    )
    monkeypatch.setattr(sys, "argv", _argv())

    with pytest.raises(SystemExit) as stopped:
        launcher._main()

    assert stopped.value.code == 1
    assert observed == [
        (
            "Stockroom's managed runtime could not start.\n\nwindow child exploded",
            False,
        )
    ]


def test_malformed_window_host_argv_is_sanitized_and_noninteractive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: list[tuple[str, bool]] = []
    prepared: list[bool] = []
    secret = "must-not-be-reflected"
    monkeypatch.setattr(
        launcher,
        "_prepare_runtime",
        lambda *, needs_window: prepared.append(needs_window),
    )
    monkeypatch.setattr(
        launcher,
        "_fatal",
        lambda message, *, interactive: observed.append((message, interactive)),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            *_argv(),
            "--api-token",
            secret,
        ],
    )

    with pytest.raises(SystemExit) as stopped:
        launcher._main()

    assert stopped.value.code == 1
    assert prepared == []
    assert len(observed) == 1
    assert observed[0][1] is False
    assert secret not in observed[0][0]
    assert observed[0][0].endswith("window-host arguments are invalid")


def test_window_host_mode_wins_dispatch_and_rejects_mixed_worker_arguments(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepared: list[bool] = []
    monkeypatch.setattr(
        launcher,
        "_prepare_runtime",
        lambda *, needs_window: prepared.append(needs_window),
    )
    monkeypatch.setattr(sys, "argv", [*_argv(), "--port", "32100"])

    with pytest.raises(WindowHostError, match="arguments are invalid"):
        launcher._dispatch()

    assert prepared == []


def test_launcher_source_keeps_credentials_out_of_the_window_host_argv() -> None:
    source = (
        Path(__file__).resolve().parents[3] / "packaging" / "stockroom_launcher.py"
    ).read_text(encoding="utf-8")

    assert "--window-host" in source
    assert "--handoff-pipe" not in source
    assert "--parent-pid" not in source
    assert "--api-token" not in source
    assert "--handoff-token" not in source
