"""The source host stages provider downloads privately and suppresses Save As."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from stockroom.host.window import (
    _NATIVE_DOWNLOAD_EVENTS,
    _begin_native_webview_download_lease,
    _discard_native_webview_downloads,
    _end_native_webview_download_lease,
    _install_silent_webview2_download_handler,
)


class _Edge:
    original_calls = []

    def on_download_starting(self, _sender, args):
        type(self).original_calls.append(args)


class _Args:
    def __init__(self) -> None:
        self.Cancel = False
        self.Handled = False
        self.ResultFilePath = r"C:\Task\browser-domain-guid"


class _CoreWebView:
    def __init__(self) -> None:
        self.closed_download_dialog = 0

    def CloseDefaultDownloadDialog(self) -> None:
        self.closed_download_dialog += 1


def test_provider_download_uses_the_task_private_root_and_suppresses_save_as(tmp_path):
    edge = type("Edge", (_Edge,), {"original_calls": []})
    webview = SimpleNamespace(settings={"ALLOW_DOWNLOADS": True})
    _install_silent_webview2_download_handler(webview, edge)
    args = _Args()
    core = _CoreWebView()
    staging = tmp_path / "Provider Staging"
    lease_token = _begin_native_webview_download_lease(staging)

    try:
        edge().on_download_starting(core, args)

        assert args.Cancel is False
        assert args.Handled is True
        assert Path(args.ResultFilePath).parent == staging.resolve()
        assert Path(args.ResultFilePath).name.endswith("browser-domain-guid")
        assert edge.original_calls == []
        assert core.closed_download_dialog == 1
    finally:
        _end_native_webview_download_lease(lease_token)
        _discard_native_webview_downloads()


def test_provider_lease_accepts_downloads_only_from_its_exact_webview_author(tmp_path):
    edge = type("Edge", (_Edge,), {"original_calls": []})
    _install_silent_webview2_download_handler(
        SimpleNamespace(settings={"ALLOW_DOWNLOADS": True}),
        edge,
    )
    leased_author = edge()
    foreign_author = edge()
    args = _Args()
    lease_token = _begin_native_webview_download_lease(
        tmp_path / "Provider Staging",
        author=leased_author,
    )
    try:
        foreign_author.on_download_starting(_CoreWebView(), args)

        assert args.Cancel is True
        assert args.Handled is True
        assert _NATIVE_DOWNLOAD_EVENTS == []
        assert edge.original_calls == []
    finally:
        _end_native_webview_download_lease(lease_token)
        _discard_native_webview_downloads()


def test_provider_download_still_fails_closed_when_downloads_are_disabled(tmp_path):
    edge = type("Edge", (_Edge,), {"original_calls": []})
    webview = SimpleNamespace(settings={"ALLOW_DOWNLOADS": False})
    _install_silent_webview2_download_handler(webview, edge)
    args = _Args()
    lease_token = _begin_native_webview_download_lease(tmp_path / "Provider Staging")

    try:
        edge().on_download_starting(None, args)

        assert args.Cancel is True
        assert args.Handled is False
        assert edge.original_calls == []
    finally:
        _end_native_webview_download_lease(lease_token)
        _discard_native_webview_downloads()


def test_download_delegates_to_pywebview_outside_provider_lease():
    edge = type("Edge", (_Edge,), {"original_calls": []})
    webview = SimpleNamespace(settings={"ALLOW_DOWNLOADS": True})
    _install_silent_webview2_download_handler(webview, edge)
    args = _Args()

    edge().on_download_starting(None, args)

    assert edge.original_calls == [args]
    assert args.Handled is False


def test_download_hook_is_idempotent():
    edge = type("Edge", (_Edge,), {})
    webview = SimpleNamespace(settings={"ALLOW_DOWNLOADS": True})

    _install_silent_webview2_download_handler(webview, edge)
    installed = edge.on_download_starting
    _install_silent_webview2_download_handler(webview, edge)

    assert edge.on_download_starting is installed


def test_source_host_journals_terminal_download_while_automation_is_detached(tmp_path):
    class EventHook:
        def __init__(self) -> None:
            self.handlers = []

        def __iadd__(self, handler):
            self.handlers.append(handler)
            return self

        def __isub__(self, handler):
            self.handlers.remove(handler)
            return self

        def fire(self, sender) -> None:
            for handler in list(self.handlers):
                handler(sender, None)

    class Operation:
        def __init__(self) -> None:
            self.State = "InProgress"
            self.StateChanged = EventHook()
            self.Uri = "https://provider.example.test/Part.step"

    class Args(_Args):
        def __init__(self) -> None:
            super().__init__()
            self.DownloadOperation = Operation()

    edge = type("Edge", (_Edge,), {"original_calls": []})
    _install_silent_webview2_download_handler(
        SimpleNamespace(settings={"ALLOW_DOWNLOADS": True}),
        edge,
    )
    args = Args()
    lease_token = _begin_native_webview_download_lease(tmp_path / "Provider Staging")
    try:
        edge().on_download_starting(_CoreWebView(), args)
        args.DownloadOperation.State = "Completed"
        args.DownloadOperation.StateChanged.fire(args.DownloadOperation)

        assert [(event.phase, event.state) for event in _NATIVE_DOWNLOAD_EVENTS] == [
            ("started", "in_progress"),
            ("progress", "completed"),
            ("terminal", "completed"),
        ]
        assert _NATIVE_DOWNLOAD_EVENTS[-1].result_file_path == args.ResultFilePath
    finally:
        _end_native_webview_download_lease(lease_token)
        _discard_native_webview_downloads()


def test_source_host_allows_only_task_bound_multi_download_permission(tmp_path):
    class EventHook:
        def __init__(self) -> None:
            self.handlers = []

        def __iadd__(self, handler):
            self.handlers.append(handler)
            return self

        def fire(self, sender, args) -> None:
            for handler in list(self.handlers):
                handler(sender, args)

    class Core:
        def __init__(self) -> None:
            self.PermissionRequested = EventHook()

    class Sender:
        def __init__(self) -> None:
            self.CoreWebView2 = Core()

    class Edge(_Edge):
        def on_webview_ready(self, _sender, _args):
            return None

    class PermissionArgs:
        def __init__(self, kind: str) -> None:
            self.PermissionKind = kind
            self.State = None
            self.SavesInProfile = None

    edge = type("Edge", (Edge,), {"original_calls": []})
    _install_silent_webview2_download_handler(
        SimpleNamespace(settings={"ALLOW_DOWNLOADS": True}),
        edge,
    )
    sender = Sender()
    instance = edge()
    instance.on_webview_ready(sender, SimpleNamespace())
    lease_token = _begin_native_webview_download_lease(tmp_path / "Provider Staging")
    try:
        automatic = PermissionArgs("MultipleAutomaticDownloads")
        location = PermissionArgs("Geolocation")
        sender.CoreWebView2.PermissionRequested.fire(sender.CoreWebView2, automatic)
        sender.CoreWebView2.PermissionRequested.fire(sender.CoreWebView2, location)

        assert str(automatic.State).lower().endswith("allow")
        assert automatic.SavesInProfile is False
        assert str(location.State).lower().endswith("deny")
        assert location.SavesInProfile is False
    finally:
        _end_native_webview_download_lease(lease_token)
        _discard_native_webview_downloads()

    after_release = PermissionArgs("MultipleAutomaticDownloads")
    sender.CoreWebView2.PermissionRequested.fire(sender.CoreWebView2, after_release)
    assert str(after_release.State).lower().endswith("deny")
