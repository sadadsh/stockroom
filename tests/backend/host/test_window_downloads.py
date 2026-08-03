"""The host suppresses Save As while the browser-domain broker owns downloads."""

from __future__ import annotations

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


def test_provider_download_keeps_browser_domain_path_and_suppresses_save_as():
    edge = type("Edge", (_Edge,), {"original_calls": []})
    webview = SimpleNamespace(settings={"ALLOW_DOWNLOADS": True})
    _install_silent_webview2_download_handler(webview, edge)
    args = _Args()
    core = _CoreWebView()
    lease_token = _begin_native_webview_download_lease()

    try:
        edge().on_download_starting(core, args)

        assert args.Cancel is False
        assert args.Handled is True
        assert args.ResultFilePath == r"C:\Task\browser-domain-guid"
        assert edge.original_calls == []
        assert core.closed_download_dialog == 1
    finally:
        _end_native_webview_download_lease(lease_token)
        _discard_native_webview_downloads()


def test_provider_download_still_fails_closed_when_downloads_are_disabled():
    edge = type("Edge", (_Edge,), {"original_calls": []})
    webview = SimpleNamespace(settings={"ALLOW_DOWNLOADS": False})
    _install_silent_webview2_download_handler(webview, edge)
    args = _Args()
    lease_token = _begin_native_webview_download_lease()

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


def test_source_host_journals_terminal_download_while_cdp_is_detached():
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
    lease_token = _begin_native_webview_download_lease()
    try:
        edge().on_download_starting(_CoreWebView(), args)
        args.DownloadOperation.State = "Completed"
        args.DownloadOperation.StateChanged.fire(args.DownloadOperation)

        assert [(event.phase, event.state) for event in _NATIVE_DOWNLOAD_EVENTS] == [
            ("started", "in_progress"),
            ("terminal", "completed"),
        ]
        assert _NATIVE_DOWNLOAD_EVENTS[-1].result_file_path == args.ResultFilePath
    finally:
        _end_native_webview_download_lease(lease_token)
        _discard_native_webview_downloads()
