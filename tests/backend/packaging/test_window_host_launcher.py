from __future__ import annotations

import sys

import pytest

import packaging.stockroom_launcher as launcher


def test_normal_launch_is_rejected_because_native_host_is_the_only_entry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys, "argv", ["Stockroom Worker.exe"])

    with pytest.raises(SystemExit, match="no interactive entry point"):
        launcher._dispatch()


def test_window_host_contract_is_not_available_from_python_worker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "Stockroom Worker.exe",
            "--window-host",
            "--handoff-pipe",
            "Stockroom.WindowHandoff." + "a" * 32,
            "--parent-pid",
            "111",
        ],
    )

    with pytest.raises(SystemExit, match="no interactive entry point"):
        launcher._dispatch()


def test_worker_failure_is_noninteractive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: list[tuple[str, bool]] = []

    def fail_dispatch() -> None:
        raise RuntimeError("worker exploded")

    monkeypatch.setattr(launcher, "_dispatch", fail_dispatch)
    monkeypatch.setattr(
        launcher,
        "_fatal",
        lambda message, *, interactive: observed.append((message, interactive)),
    )
    monkeypatch.setattr(sys, "argv", ["Stockroom Worker.exe", "--port", "39123"])

    with pytest.raises(SystemExit) as stopped:
        launcher._main()

    assert stopped.value.code == 1
    assert observed == [
        (
            "Stockroom's managed runtime could not start.\n\nworker exploded",
            False,
        )
    ]


def test_launcher_contains_no_mutable_startup_or_browser_provisioning() -> None:
    source = launcher.__file__
    assert source is not None
    text = open(source, encoding="utf-8").read()
    assert "stockroom.launcher.launch" not in text
    assert "ensure_webview2" not in text
    assert "STOCKROOM_UV" not in text
    assert "mingit" not in text.casefold()
    assert "node.exe" not in text.casefold()
