"""Task-bound direct and browser download capture."""

from __future__ import annotations

import hashlib
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from stockroom.capture.browser import _allow_automatic_downloads, chromium_unavailable_reason
from stockroom.capture.download_broker import (
    DownloadBroker,
    DownloadBrokerError,
    DownloadTask,
    RetryPolicy,
)


class _Response:
    def __init__(
        self,
        content: bytes,
        *,
        status_code: int = 200,
        url: str = "https://cdn.example.test/final",
        headers: dict[str, str] | None = None,
    ):
        self.content = content
        self.status_code = status_code
        self.url = url
        self.headers = headers or {}

    def iter_content(self, chunk_size: int):
        assert chunk_size > 0
        midpoint = max(1, len(self.content) // 2)
        yield self.content[:midpoint]
        yield self.content[midpoint:]

    def close(self) -> None:
        pass


class _Download:
    def __init__(self, name: str, content: bytes):
        self.suggested_filename = name
        self.url = "https://vendor.example.test/download"
        self._content = content
        self.calls = 0

    def save_as(self, destination: str) -> None:
        self.calls += 1
        Path(destination).write_bytes(self._content)


class _FlakyDownload(_Download):
    def save_as(self, destination: str) -> None:
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("temporary browser failure")
        Path(destination).write_bytes(self._content)


class _Page:
    def __init__(self):
        self.handlers: list = []

    def on(self, event: str, handler) -> None:
        assert event == "download"
        self.handlers.append(handler)

    def remove_listener(self, event: str, handler) -> None:
        assert event == "download"
        self.handlers.remove(handler)

    def emit(self, download) -> None:
        for handler in tuple(self.handlers):
            handler(download)

    def wait_for_timeout(self, milliseconds: int) -> None:
        assert milliseconds > 0


def _task(tmp_path: Path, *, task_id: str = "item-01", mpn: str = "S1M") -> DownloadTask:
    staging = tmp_path / "Staging"
    staging.mkdir(exist_ok=True)
    return DownloadTask(
        task_id=task_id,
        manufacturer_key="on-semiconductor",
        mpn_canonical=mpn,
        staging_root=staging,
    )


def test_direct_http_download_is_task_bound_atomic_and_digest_verified(tmp_path):
    calls: list[tuple[str, float]] = []

    def get(url: str, *, headers: dict[str, str], timeout: float):
        calls.append((url, timeout))
        assert headers["Accept"] == "*/*"
        return _Response(
            b"native-library",
            headers={"Content-Disposition": 'attachment; filename="S1M.IntLib"'},
        )

    broker = DownloadBroker(_task(tmp_path), http_get=get)
    receipt = broker.download_http("https://vendor.example.test/export?token=secret")

    assert calls == [("https://vendor.example.test/export?token=secret", 120.0)]
    assert receipt.task_id == "item-01"
    assert receipt.manufacturer_key == "on-semiconductor"
    assert receipt.mpn_canonical == "S1M"
    assert receipt.transport == "http"
    assert receipt.source_url == "https://vendor.example.test/export"
    assert receipt.final_url == "https://cdn.example.test/final"
    assert receipt.attempt == 1
    assert receipt.path == tmp_path / "Staging" / "item-01" / "S1M.IntLib"
    assert receipt.path.read_bytes() == b"native-library"
    assert receipt.size_bytes == len(b"native-library")
    assert receipt.sha256 == f"sha256:{hashlib.sha256(b'native-library').hexdigest()}"
    assert not list(receipt.path.parent.glob("*.partial"))


def test_digikey_author_routes_are_staged_and_receipted_separately(tmp_path):
    staging = tmp_path / "Staging"
    staging.mkdir()

    def task(provider: str) -> DownloadTask:
        return DownloadTask(
            task_id="item-01",
            manufacturer_key="texas-instruments",
            mpn_canonical="TPD6E05U06RVZR",
            staging_root=staging,
            surface_key="digikey",
            evidence_provider_key=provider,
        )

    def get(*_args, **_kwargs):
        return _Response(b"same-name-and-bytes")

    snap = DownloadBroker(task("digikey-snapmagic"), http_get=get).download_http(
        "https://vendor.example.test/export",
        suggested_filename="Model.zip",
    )
    ultra = DownloadBroker(task("digikey-ultralibrarian"), http_get=get).download_http(
        "https://vendor.example.test/export",
        suggested_filename="Model.zip",
    )

    assert snap.surface_key == ultra.surface_key == "digikey"
    assert {
        snap.evidence_provider_key,
        ultra.evidence_provider_key,
    } == {"digikey-snapmagic", "digikey-ultralibrarian"}
    assert snap.path != ultra.path
    assert snap.path.parent.name == "digikey-snapmagic"
    assert ultra.path.parent.name == "digikey-ultralibrarian"
    assert snap.path.read_bytes() == ultra.path.read_bytes() == b"same-name-and-bytes"


def test_redirect_and_browser_receipt_urls_discard_embedded_credentials(tmp_path):
    broker = DownloadBroker(
        _task(tmp_path),
        http_get=lambda *_args, **_kwargs: _Response(
            b"payload",
            url="https://user:password@cdn.example.test:8443/file?token=secret",
        ),
    )

    receipt = broker.download_http("https://vendor.example.test/export")
    browser_download = _Download("part.zip", b"browser-payload")
    browser_download.url = "https://user:password@vendor.example.test/download?token=secret"
    browser_receipt = broker.capture_playwright(browser_download)

    assert receipt.final_url == "https://cdn.example.test:8443/file"
    assert "user" not in receipt.final_url
    assert "password" not in receipt.final_url
    assert "secret" not in receipt.final_url
    assert browser_receipt.source_url == "https://vendor.example.test/download"
    assert "password" not in browser_receipt.source_url


def test_http_retries_retryable_status_without_leaving_partial_files(tmp_path):
    responses = [
        _Response(b"busy", status_code=503),
        _Response(b"real", headers={"Content-Disposition": "attachment; filename=part.zip"}),
    ]
    sleeps: list[float] = []

    def get(_url: str, *, headers: dict[str, str], timeout: float):
        del headers, timeout
        return responses.pop(0)

    broker = DownloadBroker(
        _task(tmp_path),
        http_get=get,
        retry_policy=RetryPolicy(attempts=2, backoff_seconds=(0.25,)),
        sleep=sleeps.append,
    )

    receipt = broker.download_http("https://vendor.example.test/export")

    assert receipt.attempt == 2
    assert receipt.path.read_bytes() == b"real"
    assert sleeps == [0.25]
    assert not responses
    assert not list(receipt.path.parent.glob("*.partial"))


def test_real_http_transport_streams_a_local_download(tmp_path):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler contract
            body = b"real-http-bytes"
            self.send_response(200)
            self.send_header("Content-Disposition", 'attachment; filename="local.step"')
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, _format: str, *_args) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        receipt = DownloadBroker(_task(tmp_path)).download_http(f"http://{host}:{port}/file")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    assert receipt.path.name == "local.step"
    assert receipt.path.read_bytes() == b"real-http-bytes"


def test_http_rejects_non_network_urls_and_does_not_touch_staging(tmp_path):
    task = _task(tmp_path)
    broker = DownloadBroker(task, http_get=lambda *_args, **_kwargs: None)

    with pytest.raises(DownloadBrokerError, match="http or https"):
        broker.download_http("file:///C:/Users/owner/secret")

    assert not (task.staging_root / "item-01").exists()


def test_http_enforces_size_limit_and_removes_partial_file(tmp_path):
    broker = DownloadBroker(
        _task(tmp_path),
        http_get=lambda *_args, **_kwargs: _Response(b"too large"),
        max_bytes=4,
        retry_policy=RetryPolicy(attempts=1),
    )

    with pytest.raises(DownloadBrokerError, match="exceeded"):
        broker.download_http("https://vendor.example.test/export")

    task_directory = tmp_path / "Staging" / "item-01"
    assert list(task_directory.iterdir()) == []


def test_playwright_multiple_files_are_isolated_to_the_exact_task(tmp_path):
    first = DownloadBroker(_task(tmp_path, task_id="item-a", mpn="S1M"))
    second = DownloadBroker(_task(tmp_path, task_id="item-b", mpn="BAT54"))

    first.capture_playwright(_Download("symbol.zip", b"symbol"))
    first.capture_playwright(_Download("symbol.zip", b"footprint"))
    second.capture_playwright(_Download("symbol.zip", b"different-part"))

    assert [receipt.path.name for receipt in first.receipts] == ["symbol.zip", "symbol-2.zip"]
    assert {receipt.task_id for receipt in first.receipts} == {"item-a"}
    assert {receipt.mpn_canonical for receipt in first.receipts} == {"S1M"}
    assert {receipt.path.parent for receipt in first.receipts} == {tmp_path / "Staging" / "item-a"}
    assert second.receipts[0].task_id == "item-b"
    assert second.receipts[0].mpn_canonical == "BAT54"
    assert second.receipts[0].path.parent == tmp_path / "Staging" / "item-b"


def test_playwright_duplicate_event_reuses_one_content_receipt(tmp_path):
    broker = DownloadBroker(_task(tmp_path))

    first = broker.capture_playwright(_Download("symbol.zip", b"symbol"))
    duplicate = broker.capture_playwright(_Download("symbol.zip", b"symbol"))

    assert duplicate is first
    assert broker.receipts == (first,)
    assert [path.name for path in first.path.parent.iterdir()] == ["symbol.zip"]


@pytest.mark.timeout(20)
def test_real_playwright_one_click_captures_multiple_files_without_deadlock(tmp_path):
    reason = chromium_unavailable_reason()
    if reason is not None:
        pytest.skip(reason)

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler contract
            if self.path == "/":
                body = (
                    b"<button id='go' onclick=\"for(const x of ['symbol','footprint','model'])"
                    b"{const a=document.createElement('a');a.href='/'+x;a.download='';"
                    b'document.body.appendChild(a);a.click();a.remove();}">Go</button>'
                )
                content_type = "text/html"
                filename = ""
            else:
                body = self.path[1:].encode()
                content_type = "application/octet-stream"
                filename = f"{self.path[1:]}.bin"
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            if filename:
                self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, _format: str, *_args) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    profile = tmp_path / "Profile"
    _allow_automatic_downloads(profile)
    from stockroom.capture.browser import PlaywrightCaptureBrowser

    broker = DownloadBroker(_task(tmp_path), timeout_seconds=10)
    browser = PlaywrightCaptureBrowser(
        download_dir=tmp_path / "Legacy",
        profile_dir=profile,
        provider_key="fixture",
        headless=True,
    )
    try:
        with browser.session():
            with browser.task_page(broker) as page:
                page.goto(f"http://127.0.0.1:{server.server_port}/")
                page.click("#go")
                receipts = broker.wait_for_playwright(
                    page,
                    minimum=3,
                    settle_seconds=0.2,
                )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    assert sorted(receipt.path.name for receipt in receipts) == [
        "footprint.bin",
        "model.bin",
        "symbol.bin",
    ]
    assert {receipt.path.name: receipt.path.read_bytes() for receipt in receipts} == {
        "symbol.bin": b"symbol",
        "footprint.bin": b"footprint",
        "model.bin": b"model",
    }
    assert {receipt.task_id for receipt in receipts} == {"item-01"}
    assert {receipt.mpn_canonical for receipt in receipts} == {"S1M"}
    assert len(browser.captured) == 3


def test_playwright_save_retries_and_records_digest(tmp_path):
    broker = DownloadBroker(
        _task(tmp_path),
        retry_policy=RetryPolicy(attempts=2, backoff_seconds=(0,)),
        sleep=lambda _seconds: None,
    )
    download = _FlakyDownload("S1M.step", b"step-data")

    receipt = broker.capture_playwright(download)

    assert download.calls == 2
    assert receipt.attempt == 2
    assert receipt.transport == "playwright"
    assert receipt.sha256 == f"sha256:{hashlib.sha256(b'step-data').hexdigest()}"


def test_playwright_failure_does_not_report_a_signed_url(tmp_path):
    class FailingDownload(_Download):
        url = "https://vendor.example.test/export?token=browser-secret"

        def save_as(self, _destination: str) -> None:
            raise RuntimeError(self.url)

    broker = DownloadBroker(
        _task(tmp_path),
        retry_policy=RetryPolicy(attempts=1),
    )

    with pytest.raises(DownloadBrokerError) as raised:
        broker.capture_playwright(FailingDownload("part.zip", b""))

    assert "browser-secret" not in str(raised.value)
    assert "RuntimeError" in str(raised.value)
    assert broker.receipts == ()


def test_http_receipt_cannot_satisfy_a_playwright_wait(tmp_path):
    broker = DownloadBroker(
        _task(tmp_path),
        timeout_seconds=0.01,
        http_get=lambda *_args, **_kwargs: _Response(b"metadata"),
    )
    broker.download_http(
        "https://vendor.example.test/metadata",
        suggested_filename="metadata.json",
    )

    with pytest.raises(DownloadBrokerError, match="received 0"):
        broker.wait_for_playwright(_Page(), minimum=1, settle_seconds=0)


def test_wait_for_playwright_times_out_honestly(tmp_path):
    broker = DownloadBroker(_task(tmp_path), timeout_seconds=0.01)

    with pytest.raises(DownloadBrokerError, match="timed out.*item-01.*S1M"):
        broker.wait_for_playwright(_Page(), minimum=1, settle_seconds=0)


def test_download_task_rejects_paths_and_ambiguous_identity(tmp_path):
    staging = tmp_path / "Staging"
    staging.mkdir()

    with pytest.raises(ValueError, match="task_id"):
        DownloadTask(
            task_id="../escape",
            manufacturer_key="on-semiconductor",
            mpn_canonical="S1M",
            staging_root=staging,
        )
    with pytest.raises(ValueError, match="mpn_canonical"):
        DownloadTask(
            task_id="item-01",
            manufacturer_key="on-semiconductor",
            mpn_canonical=" ",
            staging_root=staging,
        )
