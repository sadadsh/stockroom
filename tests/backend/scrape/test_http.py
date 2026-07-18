import asyncio

from stockroom.scrape.fetch.http import HttpClient
from stockroom.scrape.model import Page, FetchError
from stockroom.scrape.stealth.fingerprint import Fingerprint, FingerprintRotator


class _Resp:
    def __init__(self, status=200, text="<html>ok</html>", content=None,
                 url="https://x/final", headers=None):
        self.status_code = status
        self.text = text
        self.content = content if content is not None else text.encode()
        self.url = url
        self.headers = headers or {"Content-Type": "text/html; charset=utf-8"}


class _Session:
    """One action per session, mirroring HttpClient creating a session per attempt."""

    def __init__(self, action, seen):
        self._action = action
        self._seen = seen

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, url, headers=None, impersonate=None, timeout=None):
        self._seen.append(impersonate)
        kind, payload = self._action
        if kind == "raise":
            raise payload
        return payload


def _factory(actions, seen):
    it = iter(actions)

    def make():
        return _Session(next(it), seen)

    return make


def test_success_returns_page():
    seen: list[str] = []
    client = HttpClient(
        rotator=FingerprintRotator([Fingerprint("chrome146", {"Accept": "x"})]),
        session_factory=_factory([("resp", _Resp(status=200))], seen),
    )
    out = asyncio.run(client.get("https://x/page"))
    assert isinstance(out, Page)
    assert out.status == 200
    assert out.final_url == "https://x/final"
    assert out.render_tier == "http"
    assert out.content_type.startswith("text/html")
    assert seen == ["chrome146"]


def test_block_rotates_identity_and_reports_blocked():
    seen: list[str] = []
    rotator = FingerprintRotator([Fingerprint("chrome146"), Fingerprint("edge101")])
    client = HttpClient(
        rotator=rotator,
        session_factory=_factory([("resp", _Resp(status=403, text="denied")),
                                  ("resp", _Resp(status=429, text="slow down"))], seen),
        retries=1,
    )
    out = asyncio.run(client.get("https://x/page"))
    assert isinstance(out, FetchError)
    assert out.kind == "blocked"
    assert out.status == 429  # the last attempt's status
    assert seen == ["chrome146", "edge101"]  # rotated between attempts


def test_transport_error_retries_then_succeeds():
    seen: list[str] = []
    rotator = FingerprintRotator([Fingerprint("chrome146"), Fingerprint("edge101")])
    client = HttpClient(
        rotator=rotator,
        session_factory=_factory([("raise", ConnectionError("reset")),
                                  ("resp", _Resp(status=200))], seen),
        retries=2,
    )
    out = asyncio.run(client.get("https://x/page"))
    assert isinstance(out, Page)
    assert seen == ["chrome146", "edge101"]


def test_transport_error_exhausted_returns_error():
    seen: list[str] = []
    client = HttpClient(
        rotator=FingerprintRotator([Fingerprint("chrome146")]),
        session_factory=_factory([("raise", ConnectionError("a")),
                                  ("raise", ConnectionError("b"))], seen),
        retries=1,
    )
    out = asyncio.run(client.get("https://x/page"))
    assert isinstance(out, FetchError)
    assert out.kind == "transport"
