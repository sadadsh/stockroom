"""Stable-loopback-origin proxy for swapping health-checked backend workers."""

from __future__ import annotations

import asyncio
import math
import threading
import time
from dataclasses import dataclass
from urllib.parse import SplitResult, urlsplit, urlunsplit

import httpx
from starlette.responses import JSONResponse

_HOP_BY_HOP = {
    b"connection",
    b"keep-alive",
    b"proxy-authenticate",
    b"proxy-authorization",
    b"te",
    b"trailers",
    b"transfer-encoding",
    b"upgrade",
}
_FORWARDED_ORIGIN_HEADERS = {b"x-forwarded-host", b"x-forwarded-proto"}


class BackendRouteError(RuntimeError):
    """The stable backend route could not make a proven transition."""


class BackendDrainTimeout(BackendRouteError):
    """Existing requests did not reach a safe empty checkpoint in time."""


class BackendRouteConflict(BackendRouteError):
    """A stale drain or adoption receipt attempted to change the live route."""


@dataclass(frozen=True, slots=True)
class BackendRouteSnapshot:
    """A credential-free snapshot of the stable route."""

    target: str | None
    generation: int
    accepting_requests: bool
    in_flight: int


@dataclass(frozen=True, slots=True)
class BackendDrainReceipt:
    """Proof that one exact route generation reached zero in-flight requests."""

    target: str | None
    generation: int


@dataclass(frozen=True, slots=True)
class BackendAdoptionReceipt:
    """The exact old and new route generations for a reversible adoption."""

    previous_target: str | None
    previous_generation: int
    adopted_target: str | None
    adopted_generation: int


@dataclass(frozen=True, slots=True)
class BackendRollbackDrainReceipt:
    """Proof that the exact adopted route is closed and has no live requests."""

    adopted_target: str | None
    adopted_generation: int


def _scope_host(scope) -> bytes | None:
    """The stable public Host, preferring the exact header the WebView sent."""

    for name, value in scope.get("headers", []):
        if name.lower() == b"host":
            return value
    server = scope.get("server")
    if not server:
        return None
    host, port = server
    host = str(host)
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    scheme = str(scope.get("scheme") or "http").lower()
    default_port = 443 if scheme == "https" else 80
    text = host if int(port) == default_port else f"{host}:{port}"
    return text.encode("ascii")


def _request_headers(scope) -> list[tuple[bytes, bytes]]:
    """Forward end-to-end headers while keeping the public origin authoritative.

    Letting httpx synthesize ``Host`` from the private target makes the worker believe every
    request arrived on its ephemeral port. That private topology then appears in generated links
    and redirects. Forward the WebView's stable Host instead, and replace forwarded-origin headers
    rather than trusting values a caller supplied.
    """

    public_host = _scope_host(scope)
    headers: list[tuple[bytes, bytes]] = []
    host_written = False
    for name, value in scope.get("headers", []):
        lower = name.lower()
        if lower in _HOP_BY_HOP or lower in _FORWARDED_ORIGIN_HEADERS:
            continue
        if lower == b"host":
            if host_written:
                continue
            host_written = True
            if public_host is not None:
                headers.append((b"host", public_host))
            continue
        headers.append((name, value))
    if public_host is not None and not host_written:
        headers.append((b"host", public_host))
    if public_host is not None:
        headers.append((b"x-forwarded-host", public_host))
    headers.append(
        (b"x-forwarded-proto", str(scope.get("scheme") or "http").lower().encode("ascii"))
    )
    return headers


def _port(parsed: SplitResult) -> int | None:
    try:
        if parsed.port is not None:
            return parsed.port
    except ValueError:
        return None
    if parsed.scheme.lower() == "http":
        return 80
    if parsed.scheme.lower() == "https":
        return 443
    return None


def _same_worker_location(location: SplitResult, target: SplitResult) -> bool:
    if not location.netloc:
        return False
    location_scheme = (location.scheme or target.scheme).lower()
    if location_scheme != target.scheme.lower():
        return False
    location_host = (location.hostname or "").rstrip(".").lower()
    target_host = (target.hostname or "").rstrip(".").lower()
    same_host = location_host == target_host
    # Frameworks sometimes canonicalize 127.0.0.1 to localhost while retaining the worker port.
    if {location_host, target_host} <= {"127.0.0.1", "localhost"}:
        same_host = True
    return same_host and _port(location) == _port(target)


def _public_location(value: bytes, target_base_url: str) -> bytes:
    """Turn a private-worker absolute redirect into a safe origin-relative redirect."""

    try:
        text = value.decode("latin-1")
        location = urlsplit(text)
        target = urlsplit(target_base_url)
    except (UnicodeError, ValueError):
        return value
    if not _same_worker_location(location, target):
        return value
    # A path beginning with ``//`` is a network-path reference when made relative. Collapse only
    # its leading separators so a worker URL can never become an off-origin redirect by rewrite.
    path = "/" + (location.path or "").lstrip("/")
    relative = urlunsplit(("", "", path, location.query, location.fragment))
    try:
        return relative.encode("latin-1")
    except UnicodeError:
        return value


def _response_headers(
    headers: list[tuple[bytes, bytes]],
    target_base_url: str,
) -> list[tuple[bytes, bytes]]:
    forwarded: list[tuple[bytes, bytes]] = []
    for name, value in headers:
        lower = name.lower()
        if lower in _HOP_BY_HOP:
            continue
        if lower == b"location":
            value = _public_location(value, target_base_url)
        forwarded.append((name, value))
    return forwarded


class SwitchableBackendProxy:
    """Serve the bundled ASGI app or forward to one selected loopback worker.

    The WebView always sees the original public base URL, so its origin, native
    bridge, storage, and DOM hooks survive every backend handoff.
    """

    def __init__(self, local_app) -> None:
        self._local_app = local_app
        self._target: str | None = None
        self._generation = 0
        self._accepting_requests = True
        self._in_flight = 0
        self._condition = threading.Condition()

    @property
    def target(self) -> str | None:
        with self._condition:
            return self._target

    def snapshot(self) -> BackendRouteSnapshot:
        """Return one lock-consistent route/admission snapshot."""

        with self._condition:
            return BackendRouteSnapshot(
                target=self._target,
                generation=self._generation,
                accepting_requests=self._accepting_requests,
                in_flight=self._in_flight,
            )

    @staticmethod
    def _validated_target(target_base_url: str | None) -> str | None:
        target = target_base_url.rstrip("/") if target_base_url else None
        if target is not None and not target.startswith("http://127.0.0.1:"):
            raise ValueError("backend proxy target must be a loopback HTTP endpoint")
        return target

    def switch(self, target_base_url: str | None) -> None:
        """Immediately switch an idle/development route.

        Production update adoption uses :meth:`drain` and
        :meth:`adopt_drained`; this compatibility method refuses to cut across
        an update drain.
        """

        target = self._validated_target(target_base_url)
        with self._condition:
            if not self._accepting_requests:
                raise BackendRouteConflict("backend route is currently drained")
            self._target = target
            self._generation += 1

    @staticmethod
    def _timeout(value: float) -> float:
        if type(value) not in {int, float}:
            raise TypeError("timeout must be a number")
        timeout = float(value)
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("timeout must be positive and finite")
        return timeout

    def drain(self, *, timeout: float) -> BackendDrainReceipt:
        """Stop admission and wait for every request on the exact route to finish."""

        timeout_seconds = self._timeout(timeout)
        deadline = time.monotonic() + timeout_seconds
        with self._condition:
            if not self._accepting_requests:
                raise BackendRouteConflict("backend route is already drained")
            target = self._target
            generation = self._generation
            self._accepting_requests = False
            while self._in_flight:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    self._accepting_requests = True
                    self._condition.notify_all()
                    raise BackendDrainTimeout(
                        "backend requests did not drain before the deadline"
                    )
                self._condition.wait(remaining)
            return BackendDrainReceipt(target=target, generation=generation)

    def resume(self, receipt: BackendDrainReceipt) -> bool:
        """Resume the drained route.

        ``False`` means adoption already moved the route to another generation;
        this makes the activator's post-adoption recovery call harmless without
        reopening the failed candidate.
        """

        if type(receipt) is not BackendDrainReceipt:
            raise TypeError("receipt must be a BackendDrainReceipt")
        with self._condition:
            if (
                self._target != receipt.target
                or self._generation != receipt.generation
            ):
                return False
            if self._in_flight:
                raise BackendRouteConflict("a drained route gained in-flight requests")
            self._accepting_requests = True
            self._condition.notify_all()
            return True

    def adopt_drained(
        self,
        target_base_url: str | None,
        receipt: BackendDrainReceipt,
    ) -> BackendAdoptionReceipt:
        """Atomically select a candidate and reopen request admission."""

        if type(receipt) is not BackendDrainReceipt:
            raise TypeError("receipt must be a BackendDrainReceipt")
        target = self._validated_target(target_base_url)
        with self._condition:
            if (
                self._accepting_requests
                or self._in_flight
                or self._target != receipt.target
                or self._generation != receipt.generation
            ):
                raise BackendRouteConflict(
                    "backend drain receipt no longer names the live route"
                )
            self._target = target
            self._generation += 1
            adopted_generation = self._generation
            self._accepting_requests = True
            self._condition.notify_all()
            return BackendAdoptionReceipt(
                previous_target=receipt.target,
                previous_generation=receipt.generation,
                adopted_target=target,
                adopted_generation=adopted_generation,
            )

    def rollback_adoption(
        self,
        receipt: BackendAdoptionReceipt,
        *,
        timeout: float,
    ) -> BackendRouteSnapshot:
        """Drain the exact candidate generation and atomically restore its predecessor."""

        drained = self.drain_adoption(receipt, timeout=timeout)
        return self.restore_drained_adoption(receipt, drained)

    def drain_adoption(
        self,
        receipt: BackendAdoptionReceipt,
        *,
        timeout: float,
    ) -> BackendRollbackDrainReceipt:
        """Close admission and drain the exact adopted route without switching it."""

        if type(receipt) is not BackendAdoptionReceipt:
            raise TypeError("receipt must be a BackendAdoptionReceipt")
        timeout_seconds = self._timeout(timeout)
        deadline = time.monotonic() + timeout_seconds
        with self._condition:
            if (
                self._target != receipt.adopted_target
                or self._generation != receipt.adopted_generation
                or not self._accepting_requests
            ):
                raise BackendRouteConflict(
                    "backend adoption receipt no longer names the live route"
                )
            self._accepting_requests = False
            while self._in_flight:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    self._accepting_requests = True
                    self._condition.notify_all()
                    raise BackendDrainTimeout(
                        "candidate requests did not drain before rollback"
                    )
                self._condition.wait(remaining)
            return BackendRollbackDrainReceipt(
                adopted_target=self._target,
                adopted_generation=self._generation,
            )

    def restore_drained_adoption(
        self,
        receipt: BackendAdoptionReceipt,
        drained: BackendRollbackDrainReceipt,
    ) -> BackendRouteSnapshot:
        """Restore the predecessor only after its service authority is live."""

        if type(receipt) is not BackendAdoptionReceipt:
            raise TypeError("receipt must be a BackendAdoptionReceipt")
        if type(drained) is not BackendRollbackDrainReceipt:
            raise TypeError("drained must be a BackendRollbackDrainReceipt")
        with self._condition:
            if (
                self._accepting_requests
                or self._in_flight
                or self._target != receipt.adopted_target
                or self._generation != receipt.adopted_generation
                or drained.adopted_target != receipt.adopted_target
                or drained.adopted_generation != receipt.adopted_generation
            ):
                raise BackendRouteConflict(
                    "backend rollback drain no longer names the live route"
                )
            self._target = receipt.previous_target
            self._generation += 1
            self._accepting_requests = True
            self._condition.notify_all()
            return BackendRouteSnapshot(
                target=self._target,
                generation=self._generation,
                accepting_requests=True,
                in_flight=0,
            )

    async def _admit(self) -> str | None:
        while True:
            with self._condition:
                if self._accepting_requests:
                    self._in_flight += 1
                    return self._target
            await asyncio.sleep(0.005)

    def _complete(self) -> None:
        with self._condition:
            if self._in_flight <= 0:
                raise BackendRouteConflict("backend request accounting underflow")
            self._in_flight -= 1
            if self._in_flight == 0:
                self._condition.notify_all()

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self._local_app(scope, receive, send)
            return

        target = await self._admit()
        try:
            await self._call_admitted(target, scope, receive, send)
        finally:
            self._complete()

    async def _call_admitted(self, target, scope, receive, send) -> None:
        if target is None:
            await self._local_app(scope, receive, send)
            return

        query = scope.get("query_string", b"")
        url = f"{target}{scope['path']}"
        if query:
            url += "?" + query.decode("ascii")
        headers = _request_headers(scope)

        async def body():
            while True:
                message = await receive()
                if message["type"] == "http.disconnect":
                    return
                chunk = message.get("body", b"")
                if chunk:
                    yield chunk
                if not message.get("more_body", False):
                    return

        client = httpx.AsyncClient(timeout=None)
        response = None
        response_started = False
        try:
            request = client.build_request(
                scope["method"],
                url,
                headers=headers,
                content=body(),
            )
            response = await client.send(request, stream=True)
            response_headers = _response_headers(response.headers.raw, target)
            await send(
                {
                    "type": "http.response.start",
                    "status": response.status_code,
                    "headers": response_headers,
                }
            )
            response_started = True
            async for chunk in response.aiter_raw():
                await send(
                    {
                        "type": "http.response.body",
                        "body": chunk,
                        "more_body": True,
                    }
                )
            await send({"type": "http.response.body", "body": b"", "more_body": False})
        except httpx.HTTPError as exc:
            if response_started:
                await send({"type": "http.response.body", "body": b"", "more_body": False})
            else:
                error = JSONResponse(
                    {"error": "active backend unavailable", "detail": str(exc)},
                    status_code=502,
                )
                await error(scope, receive, send)
        finally:
            if response is not None:
                await response.aclose()
            await client.aclose()
