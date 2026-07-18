"""Rotating browser fingerprints for the HTTP tier (spec section 6): a curl_cffi
impersonation target paired with a header profile that matches that browser.
Rotation is deterministic round-robin, so a blocked request retries under a fresh
identity and tests stay stable. curl_cffi sets the TLS/JA3 and User-Agent from
the impersonate target; these headers add the accompanying Accept / sec-ch-ua so
the whole request is internally coherent."""

from __future__ import annotations

from dataclasses import dataclass, field

_CHROME_ACCEPT = (
    "text/html,application/xhtml+xml,application/xml;q=0.9,"
    "image/avif,image/webp,image/apng,*/*;q=0.8"
)


@dataclass(frozen=True)
class Fingerprint:
    impersonate: str
    headers: dict[str, str] = field(default_factory=dict)


def default_fingerprints() -> list[Fingerprint]:
    return [
        Fingerprint(
            "chrome146",
            {
                "Accept": _CHROME_ACCEPT,
                "Accept-Language": "en-US,en;q=0.9",
                "sec-ch-ua": '"Chromium";v="146", "Google Chrome";v="146", "Not_A Brand";v="24"',
                "sec-ch-ua-mobile": "?0",
                "sec-ch-ua-platform": '"Windows"',
                "Upgrade-Insecure-Requests": "1",
            },
        ),
        Fingerprint(
            "edge101",
            {
                "Accept": _CHROME_ACCEPT,
                "Accept-Language": "en-US,en;q=0.9",
                "sec-ch-ua": '"Microsoft Edge";v="101", "Chromium";v="101", "Not_A Brand";v="24"',
                "sec-ch-ua-mobile": "?0",
                "sec-ch-ua-platform": '"Windows"',
                "Upgrade-Insecure-Requests": "1",
            },
        ),
        Fingerprint(
            "safari184",
            {
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
            },
        ),
        Fingerprint(
            "firefox147",
            {
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.5",
            },
        ),
    ]


class FingerprintRotator:
    def __init__(self, fingerprints: list[Fingerprint] | None = None, index: int = 0):
        self._fps = list(fingerprints) if fingerprints is not None else default_fingerprints()
        if not self._fps:
            raise ValueError("at least one fingerprint is required")
        self._i = index % len(self._fps)

    def current(self) -> Fingerprint:
        return self._fps[self._i]

    def rotate(self) -> Fingerprint:
        self._i = (self._i + 1) % len(self._fps)
        return self._fps[self._i]
