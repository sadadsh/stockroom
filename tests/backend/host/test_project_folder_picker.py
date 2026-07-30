"""The packaged Projects folder picker is a real host bridge, not a browser-only affordance."""

from __future__ import annotations

import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

import pytest


def _webview_module(*, folder_kind: object | None = None, legacy_kind: object | None = None):
    module = types.ModuleType("webview")
    if folder_kind is not None:
        module.FileDialog = types.SimpleNamespace(FOLDER=folder_kind)
    if legacy_kind is not None:
        module.FOLDER_DIALOG = legacy_kind
    return module


def test_project_folder_picker_uses_the_current_folder_dialog_contract(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    from stockroom.host import window as host_window

    folder_kind = object()
    webview = _webview_module(folder_kind=folder_kind)
    monkeypatch.setitem(sys.modules, "webview", webview)
    win = MagicMock()
    win.create_file_dialog.return_value = (str(tmp_path),)
    monkeypatch.setattr(host_window, "active_window", lambda: win)

    selected = host_window._HostApi().pick_project_folder()

    assert selected == [str(tmp_path)]
    win.create_file_dialog.assert_called_once_with(folder_kind, allow_multiple=False)


def test_project_folder_picker_supports_an_older_pywebview_and_cancel(
    monkeypatch: pytest.MonkeyPatch,
):
    from stockroom.host import window as host_window

    legacy_kind = object()
    webview = _webview_module(legacy_kind=legacy_kind)
    monkeypatch.setitem(sys.modules, "webview", webview)
    win = MagicMock()
    win.create_file_dialog.return_value = None
    monkeypatch.setattr(host_window, "active_window", lambda: win)

    assert host_window._HostApi().pick_project_folder() == []
    win.create_file_dialog.assert_called_once_with(legacy_kind, allow_multiple=False)


def test_project_folder_picker_is_empty_without_an_active_window(
    monkeypatch: pytest.MonkeyPatch,
):
    from stockroom.host import window as host_window

    webview = _webview_module(folder_kind=object())
    monkeypatch.setitem(sys.modules, "webview", webview)
    monkeypatch.setattr(host_window, "active_window", lambda: None)

    assert host_window._HostApi().pick_project_folder() == []
