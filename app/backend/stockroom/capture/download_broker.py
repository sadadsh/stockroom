"""Task-bound network and browser download staging.

The broker is the ownership boundary between an acquisition adapter and the
rest of Stockroom.  A broker instance belongs to exactly one workflow item and
canonical MPN, so a late browser event cannot be correlated by provider-wide
list position or by a mutable "current part" variable.
"""

from __future__ import annotations

import hashlib
import os
import re
import threading
import time
import uuid
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlparse, urlunsplit


class DownloadBrokerError(RuntimeError):
    """A download could not produce a complete, task-bound staging artifact."""


_TASK_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", re.ASCII)
_WINDOWS_INVALID_FILENAME = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_WINDOWS_RESERVED_NAMES = {
    "aux",
    "clock$",
    "con",
    "nul",
    "prn",
    *(f"com{number}" for number in range(1, 10)),
    *(f"lpt{number}" for number in range(1, 10)),
}
_RETRYABLE_HTTP_STATUS = frozenset({408, 425, 429, 500, 502, 503, 504})
_DEFAULT_MAX_BYTES = 512 * 1024 * 1024
_CHUNK_BYTES = 1024 * 1024


@dataclass(frozen=True, slots=True)
class DownloadTask:
    """Exact workflow identity and the batch staging root it owns."""

    task_id: str
    manufacturer_key: str
    mpn_canonical: str
    staging_root: Path
    surface_key: str = ""
    evidence_provider_key: str = ""

    def __post_init__(self) -> None:
        if type(self.task_id) is not str or _TASK_ID.fullmatch(self.task_id) is None:
            raise ValueError("task_id must be a portable opaque identifier")
        if (
            type(self.manufacturer_key) is not str
            or not self.manufacturer_key
            or self.manufacturer_key != self.manufacturer_key.strip()
        ):
            raise ValueError("manufacturer_key must be canonical non-empty text")
        if (
            type(self.mpn_canonical) is not str
            or not self.mpn_canonical
            or self.mpn_canonical != self.mpn_canonical.strip()
        ):
            raise ValueError("mpn_canonical must be canonical non-empty text")
        for name, value in (
            ("surface_key", self.surface_key),
            ("evidence_provider_key", self.evidence_provider_key),
        ):
            if type(value) is not str or (
                value and _TASK_ID.fullmatch(value) is None
            ):
                raise ValueError(f"{name} must be empty or a portable provider identifier")
        if bool(self.surface_key) != bool(self.evidence_provider_key):
            raise ValueError(
                "surface_key and evidence_provider_key must both be set for attributed capture"
            )
        root = Path(self.staging_root)
        if not root.is_dir() or root.is_symlink():
            raise ValueError("staging_root must be an existing non-linked directory")
        object.__setattr__(self, "staging_root", root.resolve(strict=True))


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    """Bounded attempts and deterministic delays between them."""

    attempts: int = 3
    backoff_seconds: tuple[float, ...] = (0.25, 1.0)

    def __post_init__(self) -> None:
        if type(self.attempts) is not int or not 1 <= self.attempts <= 5:
            raise ValueError("attempts must be between 1 and 5")
        if (
            type(self.backoff_seconds) is not tuple
            or len(self.backoff_seconds) < self.attempts - 1
            or any(
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not 0 <= float(value) <= 60
                for value in self.backoff_seconds
            )
        ):
            raise ValueError("backoff_seconds must cover every retry with bounded delays")

    def delay_before(self, attempt: int) -> float:
        """Return the delay before one-indexed ``attempt``."""

        if attempt <= 1:
            return 0.0
        return float(self.backoff_seconds[attempt - 2])


@dataclass(frozen=True, slots=True)
class DownloadReceipt:
    """Immutable content and identity evidence for one completed file."""

    task_id: str
    manufacturer_key: str
    mpn_canonical: str
    path: Path
    suggested_name: str
    source_url: str
    final_url: str
    sha256: str
    size_bytes: int
    transport: str
    attempt: int
    surface_key: str = ""
    evidence_provider_key: str = ""


def _default_http_get(url: str, *, headers: dict[str, str], timeout: float):
    from curl_cffi import requests as curl_requests

    session = curl_requests.Session(impersonate="chrome")
    try:
        response = session.get(
            url,
            headers=headers,
            timeout=timeout,
            allow_redirects=True,
            stream=True,
        )
    except BaseException:
        session.close()
        raise
    setattr(response, "_stockroom_session", session)
    return response


class DownloadBroker:
    """Own direct HTTP and Playwright download materialization for one task."""

    def __init__(
        self,
        task: DownloadTask,
        *,
        timeout_seconds: float = 120.0,
        retry_policy: RetryPolicy = RetryPolicy(),
        max_bytes: int = _DEFAULT_MAX_BYTES,
        http_get: Callable[..., object] | None = None,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        if type(task) is not DownloadTask:
            raise TypeError("task must be a DownloadTask")
        if (
            isinstance(timeout_seconds, bool)
            or not isinstance(timeout_seconds, (int, float))
            or not 0 < float(timeout_seconds) <= 600
        ):
            raise ValueError("timeout_seconds must be between zero and 600")
        if type(retry_policy) is not RetryPolicy:
            raise TypeError("retry_policy must be a RetryPolicy")
        if type(max_bytes) is not int or not 1 <= max_bytes <= 4 * 1024 * 1024 * 1024:
            raise ValueError("max_bytes must be between 1 byte and 4 GiB")
        self.task = task
        self.timeout_seconds = float(timeout_seconds)
        self.retry_policy = retry_policy
        self.max_bytes = max_bytes
        self._http_get = http_get or _default_http_get
        self._sleep = sleep
        self._monotonic = monotonic
        self._receipts: list[DownloadReceipt] = []
        self._event_errors: list[BaseException] = []
        self._last_playwright_event_at: float | None = None
        self._lock = threading.RLock()

    @property
    def receipts(self) -> tuple[DownloadReceipt, ...]:
        with self._lock:
            return tuple(self._receipts)

    @staticmethod
    def playwright_context_options() -> dict[str, bool]:
        """Options required for a Playwright context with no save dialog."""

        return {"accept_downloads": True}

    def download_http(
        self,
        url: str,
        *,
        suggested_filename: str = "",
        headers: Mapping[str, str] | None = None,
    ) -> DownloadReceipt:
        """Fetch one URL directly with bounded retries and atomic staging."""

        _validate_network_url(url)
        request_headers = {"Accept": "*/*", **dict(headers or {})}
        last_error: BaseException | None = None
        for attempt in range(1, self.retry_policy.attempts + 1):
            if attempt > 1:
                self._sleep(self.retry_policy.delay_before(attempt))
            response = None
            try:
                response = self._http_get(
                    url,
                    headers=request_headers,
                    timeout=self.timeout_seconds,
                )
                status = int(getattr(response, "status_code", 0))
                if status in _RETRYABLE_HTTP_STATUS:
                    raise _RetryableDownloadError(f"server returned HTTP {status}")
                if not 200 <= status < 300:
                    raise DownloadBrokerError(
                        f"download returned HTTP {status} for {_receipt_url(url)}"
                    )
                response_headers = _headers(getattr(response, "headers", {}))
                name = (
                    suggested_filename
                    or _content_disposition_name(response_headers)
                    or Path(urlparse(str(getattr(response, "url", url))).path).name
                    or "download"
                )
                receipt = self._materialize_chunks(
                    _response_chunks(response),
                    suggested_name=name,
                    source_url=_receipt_url(url),
                    final_url=_receipt_url(str(getattr(response, "url", url) or url)),
                    transport="http",
                    attempt=attempt,
                )
                return receipt
            except DownloadBrokerError:
                raise
            except _RetryableDownloadError as exc:
                last_error = exc
            except Exception as exc:  # transport failure; retry is bounded by policy
                last_error = exc
            finally:
                _close_response(response)
        detail = str(last_error).strip() if last_error is not None else "unknown failure"
        raise DownloadBrokerError(
            f"download failed after {self.retry_policy.attempts} attempts for "
            f"{self.task.task_id} / {self.task.mpn_canonical} from "
            f"{_receipt_url(url)}: {type(last_error).__name__ if last_error else detail}"
        ) from last_error

    def capture_playwright(self, download) -> DownloadReceipt:
        """Save one Playwright Download into this task's staging directory."""

        name = str(getattr(download, "suggested_filename", "") or "download")
        last_error: BaseException | None = None
        for attempt in range(1, self.retry_policy.attempts + 1):
            if attempt > 1:
                self._sleep(self.retry_policy.delay_before(attempt))
            temporary = self._temporary_path(name)
            try:
                download.save_as(str(temporary))
                return self._materialize_existing(
                    temporary,
                    suggested_name=name,
                    source_url=_receipt_url(str(getattr(download, "url", "") or "")),
                    final_url=_receipt_url(str(getattr(download, "url", "") or "")),
                    transport="playwright",
                    attempt=attempt,
                )
            except Exception as exc:  # Playwright permits save_as again for the same download
                temporary.unlink(missing_ok=True)
                last_error = exc
        detail = type(last_error).__name__ if last_error is not None else "unknown failure"
        error = DownloadBrokerError(
            f"browser download failed after {self.retry_policy.attempts} attempts for "
            f"{self.task.task_id} / {self.task.mpn_canonical}: {detail}"
        )
        with self._lock:
            self._event_errors.append(error)
            self._last_playwright_event_at = self._monotonic()
        raise error from last_error

    def wait_for_playwright(
        self,
        page,
        *,
        minimum: int = 1,
        settle_seconds: float = 0.75,
        timeout_seconds: float | None = None,
    ) -> tuple[DownloadReceipt, ...]:
        """Pump Playwright until enough files land and the event stream settles."""

        if type(minimum) is not int or minimum < 1:
            raise ValueError("minimum must be a positive integer")
        if (
            isinstance(settle_seconds, bool)
            or not isinstance(settle_seconds, (int, float))
            or not 0 <= float(settle_seconds) <= 30
        ):
            raise ValueError("settle_seconds must be between zero and 30")
        timeout = self.timeout_seconds if timeout_seconds is None else float(timeout_seconds)
        if not 0 < timeout <= 600:
            raise ValueError("timeout_seconds must be between zero and 600")
        started = self._monotonic()
        while True:
            now = self._monotonic()
            with self._lock:
                if self._event_errors:
                    error = self._event_errors.pop(0)
                    if isinstance(error, DownloadBrokerError):
                        raise error
                    raise DownloadBrokerError(str(error)) from error
                receipts = tuple(
                    receipt for receipt in self._receipts if receipt.transport == "playwright"
                )
                last_event = self._last_playwright_event_at
            settled = len(receipts) >= minimum and (
                float(settle_seconds) == 0
                or last_event is not None
                and now - last_event >= float(settle_seconds)
            )
            if settled:
                return receipts
            if now - started >= timeout:
                raise DownloadBrokerError(
                    f"browser download timed out for {self.task.task_id} / "
                    f"{self.task.mpn_canonical}; received {len(receipts)}, expected at least "
                    f"{minimum}"
                )
            remaining_ms = max(1, min(100, int((timeout - (now - started)) * 1000)))
            page.wait_for_timeout(remaining_ms)

    def _task_directory(self) -> Path:
        destination = self.task.staging_root / self.task.task_id
        if destination.exists() and (destination.is_symlink() or not destination.is_dir()):
            raise DownloadBrokerError(
                f"download staging path is not a real directory: {destination}"
            )
        destination.mkdir(parents=False, exist_ok=True)
        if self.task.evidence_provider_key:
            destination = destination / self.task.evidence_provider_key
            if destination.exists() and (
                destination.is_symlink() or not destination.is_dir()
            ):
                raise DownloadBrokerError(
                    f"download route staging path is not a real directory: {destination}"
                )
            destination.mkdir(parents=False, exist_ok=True)
        resolved = destination.resolve(strict=True)
        try:
            resolved.relative_to(self.task.staging_root)
        except ValueError as exc:
            raise DownloadBrokerError("download staging path escaped its task root") from exc
        return resolved

    def _temporary_path(self, suggested_name: str) -> Path:
        directory = self._task_directory()
        safe = _safe_filename(suggested_name)
        return directory / f".{safe}.{uuid.uuid4().hex}.partial"

    def _materialize_chunks(
        self,
        chunks: Iterator[bytes],
        *,
        suggested_name: str,
        source_url: str,
        final_url: str,
        transport: str,
        attempt: int,
    ) -> DownloadReceipt:
        temporary = self._temporary_path(suggested_name)
        digest = hashlib.sha256()
        size = 0
        try:
            with temporary.open("xb") as output:
                for chunk in chunks:
                    if not chunk:
                        continue
                    size += len(chunk)
                    if size > self.max_bytes:
                        raise DownloadBrokerError(
                            f"download exceeded the {self.max_bytes}-byte task limit"
                        )
                    output.write(chunk)
                    digest.update(chunk)
                output.flush()
                os.fsync(output.fileno())
            if size == 0:
                raise DownloadBrokerError("download was empty")
            return self._finalize(
                temporary,
                suggested_name=suggested_name,
                source_url=source_url,
                final_url=final_url,
                digest=digest,
                size=size,
                transport=transport,
                attempt=attempt,
            )
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise

    def _materialize_existing(
        self,
        temporary: Path,
        *,
        suggested_name: str,
        source_url: str,
        final_url: str,
        transport: str,
        attempt: int,
    ) -> DownloadReceipt:
        digest = hashlib.sha256()
        size = 0
        try:
            with temporary.open("rb") as source:
                while chunk := source.read(_CHUNK_BYTES):
                    size += len(chunk)
                    if size > self.max_bytes:
                        raise DownloadBrokerError(
                            f"download exceeded the {self.max_bytes}-byte task limit"
                        )
                    digest.update(chunk)
            if size == 0:
                raise DownloadBrokerError("download was empty")
            return self._finalize(
                temporary,
                suggested_name=suggested_name,
                source_url=source_url,
                final_url=final_url,
                digest=digest,
                size=size,
                transport=transport,
                attempt=attempt,
            )
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise

    def _finalize(
        self,
        temporary: Path,
        *,
        suggested_name: str,
        source_url: str,
        final_url: str,
        digest,
        size: int,
        transport: str,
        attempt: int,
    ) -> DownloadReceipt:
        with self._lock:
            sha256 = f"sha256:{digest.hexdigest()}"
            duplicate = next(
                (
                    receipt
                    for receipt in self._receipts
                    if receipt.sha256 == sha256
                    and receipt.suggested_name == suggested_name
                    and receipt.source_url == source_url
                    and receipt.final_url == final_url
                    and receipt.transport == transport
                ),
                None,
            )
            if duplicate is not None:
                temporary.unlink(missing_ok=True)
                if transport == "playwright":
                    self._last_playwright_event_at = self._monotonic()
                return duplicate
            destination = _unique_path(temporary.parent, _safe_filename(suggested_name))
            os.replace(temporary, destination)
            receipt = DownloadReceipt(
                task_id=self.task.task_id,
                manufacturer_key=self.task.manufacturer_key,
                mpn_canonical=self.task.mpn_canonical,
                path=destination,
                suggested_name=suggested_name,
                source_url=source_url,
                final_url=final_url,
                sha256=sha256,
                size_bytes=size,
                transport=transport,
                attempt=attempt,
                surface_key=self.task.surface_key,
                evidence_provider_key=self.task.evidence_provider_key,
            )
            self._receipts.append(receipt)
            if transport == "playwright":
                self._last_playwright_event_at = self._monotonic()
        return receipt


class _RetryableDownloadError(RuntimeError):
    pass


def _validate_network_url(url: str) -> None:
    if type(url) is not str or urlparse(url).scheme.casefold() not in {"http", "https"}:
        raise DownloadBrokerError("download URL must use http or https")
    parsed = urlparse(url)
    if not parsed.netloc or parsed.username is not None or parsed.password is not None:
        raise DownloadBrokerError("download URL must have a host and no embedded credentials")


def _receipt_url(url: str) -> str:
    """Keep a useful locator without persisting signed query strings or fragments."""

    parsed = urlparse(url)
    hostname = parsed.hostname
    if parsed.scheme.casefold() not in {"http", "https"} or not hostname:
        return ""
    try:
        port = parsed.port
    except ValueError:
        return ""
    safe_host = f"[{hostname}]" if ":" in hostname else hostname
    safe_netloc = f"{safe_host}:{port}" if port is not None else safe_host
    return urlunsplit((parsed.scheme, safe_netloc, parsed.path, "", ""))


def _headers(value) -> dict[str, str]:
    return {str(key).casefold(): str(item) for key, item in dict(value or {}).items()}


def _content_disposition_name(headers: Mapping[str, str]) -> str:
    value = headers.get("content-disposition", "")
    encoded = re.search(r"(?:^|;)\s*filename\*=UTF-8''([^;]+)", value, re.IGNORECASE)
    if encoded:
        return unquote(encoded.group(1).strip())
    plain = re.search(r'(?:^|;)\s*filename="?([^";]+)"?', value, re.IGNORECASE)
    return plain.group(1).strip() if plain else ""


def _response_chunks(response) -> Iterator[bytes]:
    iterator = getattr(response, "iter_content", None)
    if callable(iterator):
        yield from iterator(chunk_size=_CHUNK_BYTES)
        return
    content = getattr(response, "content", b"") or b""
    if content:
        yield bytes(content)


def _close_response(response) -> None:
    if response is None:
        return
    try:
        close = getattr(response, "close", None)
        if callable(close):
            close()
    finally:
        session = getattr(response, "_stockroom_session", None)
        close_session = getattr(session, "close", None)
        if callable(close_session):
            close_session()


def _safe_filename(name: str) -> str:
    leaf = Path(name).name
    safe = _WINDOWS_INVALID_FILENAME.sub("_", leaf).strip(" .")
    if not safe:
        return "download"
    stem = Path(safe).stem[:160].rstrip(" .") or "download"
    suffix = Path(safe).suffix[:20]
    if stem.casefold() in _WINDOWS_RESERVED_NAMES:
        stem = f"_{stem}"
    return f"{stem}{suffix}"


def _unique_path(directory: Path, name: str) -> Path:
    stem = Path(name).stem or "download"
    suffix = Path(name).suffix
    destination = directory / f"{stem}{suffix}"
    counter = 2
    while destination.exists():
        destination = directory / f"{stem}-{counter}{suffix}"
        counter += 1
    return destination


__all__ = [
    "DownloadBroker",
    "DownloadBrokerError",
    "DownloadReceipt",
    "DownloadTask",
    "RetryPolicy",
]
