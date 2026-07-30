from __future__ import annotations

import os
import sys
import types
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from stockroom.host import window as W


class _PackageKernel:
    def __init__(self, result: int) -> None:
        self.result = result
        self.calls = 0

    def GetCurrentPackageFullName(self, length, name) -> int:
        del name
        self.calls += 1
        length._obj.value = 64
        return self.result


class _Shell:
    def __init__(self, result: int = 0) -> None:
        self.result = result
        self.identities: list[str] = []

    def SetCurrentProcessExplicitAppUserModelID(self, identity: str) -> int:
        self.identities.append(identity)
        return self.result


class _DotNetHandle:
    def __init__(self, value: int) -> None:
        self.value = value

    def ToInt64(self) -> int:
        return self.value


class _User32:
    def __init__(self, *, hwnd: int, owner_process_id: int, dpi: int = 144) -> None:
        self.hwnd = hwnd
        self.owner_process_id = owner_process_id
        self.dpi = dpi
        self.loaded: list[tuple[object, str, int, int, int, int]] = []
        self.messages: list[tuple[int, int, int, int]] = []
        self.destroyed: list[int] = []
        self.icon_slots: dict[int, int] = {}
        self.fail_kinds: list[int] = []

    def IsWindow(self, hwnd: int) -> bool:
        return hwnd == self.hwnd

    def GetWindowThreadProcessId(self, hwnd: int, owner) -> int:
        if hwnd != self.hwnd:
            return 0
        owner._obj.value = self.owner_process_id
        return 1

    def GetDpiForWindow(self, hwnd: int) -> int:
        return self.dpi if hwnd == self.hwnd else 0

    def GetSystemMetricsForDpi(self, metric: int, dpi: int) -> int:
        logical = {
            W._SM_CXSMICON: 16,
            W._SM_CYSMICON: 16,
            W._SM_CXICON: 32,
            W._SM_CYICON: 32,
        }[metric]
        return round(logical * dpi / 96)

    def GetSystemMetrics(self, metric: int) -> int:
        return {
            W._SM_CXSMICON: 16,
            W._SM_CYSMICON: 16,
            W._SM_CXICON: 32,
            W._SM_CYICON: 32,
        }[metric]

    def LoadImageW(
        self,
        instance,
        path: str,
        image_type: int,
        width: int,
        height: int,
        flags: int,
    ) -> int:
        self.loaded.append((instance, path, image_type, width, height, flags))
        return 500 + len(self.loaded)

    def SendMessageW(self, hwnd: int, message: int, kind: int, icon: int) -> int:
        self.messages.append((hwnd, message, kind, icon))
        previous = self.icon_slots.get(kind, 0)
        self.icon_slots[kind] = icon
        if self.fail_kinds and self.fail_kinds[0] == kind:
            self.fail_kinds.pop(0)
            raise OSError("injected WM_SETICON failure after slot replacement")
        return previous

    def DestroyIcon(self, icon: int) -> bool:
        self.destroyed.append(icon)
        return True


def _window(hwnd: int) -> SimpleNamespace:
    return SimpleNamespace(native=SimpleNamespace(Handle=_DotNetHandle(hwnd)))


def test_unpacked_process_gets_one_stable_app_user_model_id(monkeypatch) -> None:
    monkeypatch.setattr(W, "_is_windows", lambda: True)
    kernel = _PackageKernel(W._APP_MODEL_ERROR_NO_PACKAGE)
    shell = _Shell()

    assert W._configure_windows_process_identity(
        kernel32=kernel,
        shell32=shell,
    )
    assert kernel.calls == 1
    assert shell.identities == [W.UNPACKAGED_APP_USER_MODEL_ID]


def test_msix_process_keeps_the_shell_assigned_app_user_model_id(monkeypatch) -> None:
    monkeypatch.setattr(W, "_is_windows", lambda: True)
    shell = _Shell()

    assert not W._configure_windows_process_identity(
        kernel32=_PackageKernel(W._ERROR_INSUFFICIENT_BUFFER),
        shell32=shell,
    )
    assert shell.identities == []

    # An unexpected package-query failure also fails safe: never risk
    # splitting an installed app from its package identity.
    assert not W._configure_windows_process_identity(
        kernel32=_PackageKernel(5),
        shell32=shell,
    )
    assert shell.identities == []


def test_native_icon_targets_only_the_pywebview_hwnd_owned_by_this_process(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(W, "_is_windows", lambda: True)
    hwnd = 0x1234_5678
    window = _window(hwnd)
    user32 = _User32(hwnd=hwnd, owner_process_id=os.getpid(), dpi=144)
    icon = tmp_path / "Stockroom.ico"
    icon.write_bytes(b"icon")

    assert W._apply_window_icon(window, user32=user32, icon_path=icon)
    assert [(call[3], call[4]) for call in user32.loaded] == [(24, 24), (48, 48)]
    assert all(call[1] == str(icon) for call in user32.loaded)
    assert user32.messages == [
        (hwnd, W._WM_SETICON, W._ICON_SMALL, 501),
        (hwnd, W._WM_SETICON, W._ICON_BIG, 502),
    ]
    assert window._stockroom_icon_handles == {
        W._ICON_SMALL: 501,
        W._ICON_BIG: 502,
    }

    W._release_window_icons(window, user32)
    assert sorted(user32.destroyed) == [501, 502]
    assert window._stockroom_icon_handles == {}


def test_icon_reapply_destroys_only_the_detached_prior_handles(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(W, "_is_windows", lambda: True)
    hwnd = 0x1234_5678
    window = _window(hwnd)
    user32 = _User32(hwnd=hwnd, owner_process_id=os.getpid())
    icon = tmp_path / "Stockroom.ico"
    icon.write_bytes(b"icon")

    assert W._apply_window_icon(window, user32=user32, icon_path=icon)
    assert W._apply_window_icon(window, user32=user32, icon_path=icon)

    assert user32.icon_slots == {
        W._ICON_SMALL: 503,
        W._ICON_BIG: 504,
    }
    assert window._stockroom_icon_handles == user32.icon_slots
    assert sorted(user32.destroyed) == [501, 502]
    assert not (set(user32.icon_slots.values()) & set(user32.destroyed))


def test_partial_icon_reapply_rolls_back_before_destroying_new_handles(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(W, "_is_windows", lambda: True)
    hwnd = 0x1234_5678
    window = _window(hwnd)
    user32 = _User32(hwnd=hwnd, owner_process_id=os.getpid())
    icon = tmp_path / "Stockroom.ico"
    icon.write_bytes(b"icon")

    assert W._apply_window_icon(window, user32=user32, icon_path=icon)
    user32.fail_kinds = [W._ICON_BIG]

    assert not W._apply_window_icon(window, user32=user32, icon_path=icon)
    assert user32.icon_slots == {
        W._ICON_SMALL: 501,
        W._ICON_BIG: 502,
    }
    assert window._stockroom_icon_handles == user32.icon_slots
    assert sorted(user32.destroyed) == [503, 504]
    assert not (set(user32.icon_slots.values()) & set(user32.destroyed))


def test_failed_icon_rollback_defers_every_possibly_attached_handle(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(W, "_is_windows", lambda: True)
    hwnd = 0x1234_5678
    window = _window(hwnd)
    user32 = _User32(hwnd=hwnd, owner_process_id=os.getpid())
    icon = tmp_path / "Stockroom.ico"
    icon.write_bytes(b"icon")

    assert W._apply_window_icon(window, user32=user32, icon_path=icon)
    user32.fail_kinds = [W._ICON_BIG, W._ICON_BIG]

    assert not W._apply_window_icon(window, user32=user32, icon_path=icon)
    assert user32.icon_slots == {
        W._ICON_SMALL: 501,
        W._ICON_BIG: 502,
    }
    assert user32.destroyed == []
    assert window._stockroom_deferred_icon_handles == {501, 502, 503, 504}

    assert W._apply_window_icon(window, user32=user32, icon_path=icon)
    assert user32.icon_slots == {
        W._ICON_SMALL: 505,
        W._ICON_BIG: 506,
    }
    assert sorted(user32.destroyed) == [501, 502, 503, 504]
    assert window._stockroom_deferred_icon_handles == set()
    assert not (set(user32.icon_slots.values()) & set(user32.destroyed))


def test_icon_refuses_a_pywebview_handle_owned_by_another_process(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(W, "_is_windows", lambda: True)
    hwnd = 0x1234_5678
    window = _window(hwnd)
    user32 = _User32(hwnd=hwnd, owner_process_id=os.getpid() + 1)
    icon = tmp_path / "Stockroom.ico"
    icon.write_bytes(b"icon")

    assert not W._apply_window_icon(window, user32=user32, icon_path=icon)
    assert user32.loaded == []
    assert user32.messages == []


def test_process_identity_is_configured_before_pywebview_creates_the_window(
    monkeypatch,
    tmp_path: Path,
) -> None:
    events: list[str] = []
    native_window = MagicMock()
    native_window._stockroom_icon_handles = {}
    native_window._stockroom_deferred_icon_handles = set()
    webview = types.ModuleType("webview")
    setattr(webview, "settings", {})

    def create_window(*args, **kwargs):
        del args, kwargs
        events.append("create-window")
        return native_window

    setattr(webview, "create_window", create_window)
    setattr(webview, "start", lambda **kwargs: None)
    monkeypatch.setitem(sys.modules, "webview", webview)
    monkeypatch.setattr(
        W,
        "_configure_windows_process_identity",
        lambda: events.append("process-identity"),
    )
    monkeypatch.setattr(
        "stockroom.store.machine_config.config_dir",
        lambda: tmp_path,
        raising=False,
    )

    W.run_window("http://127.0.0.1:1234/", "token")

    assert events == ["process-identity", "create-window"]


def test_run_window_releases_icons_and_clears_active_window_when_start_fails(
    monkeypatch,
    tmp_path: Path,
) -> None:
    native_window = MagicMock()
    webview = types.ModuleType("webview")
    setattr(webview, "settings", {})
    setattr(webview, "create_window", lambda *args, **kwargs: native_window)

    def fail_start(**kwargs) -> None:
        del kwargs
        raise RuntimeError("injected WebView start failure")

    setattr(webview, "start", fail_start)
    monkeypatch.setitem(sys.modules, "webview", webview)
    monkeypatch.setattr(W, "_configure_windows_process_identity", lambda: None)
    monkeypatch.setattr(
        "stockroom.store.machine_config.config_dir",
        lambda: tmp_path,
        raising=False,
    )
    released: list[object] = []
    monkeypatch.setattr(W, "_release_window_icons", released.append)

    with pytest.raises(RuntimeError, match="injected WebView start failure"):
        W.run_window("http://127.0.0.1:1234/", "token")

    assert released == [native_window]
    assert W.active_window() is None
