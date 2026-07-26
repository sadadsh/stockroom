"""Shared exception type for the enrichment pipeline."""

from __future__ import annotations


class EnrichError(Exception):
    """Raised by an adapter/requester when a lookup call fails. `status_code` carries the
    HTTP status when the failure was an `HTTPError` (429 rate-limited, 401/403 auth), so a
    caller (the rescan circuit breaker) can distinguish a throttled/auth-failed provider
    from any other failure (a DNS blip, a timeout, a malformed body). Stays None when the
    failure was not HTTP-coded. Backward compatible: `EnrichError("msg")` still works."""

    def __init__(self, message: str = "", *, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


def status_from_error(exc: EnrichError) -> str:
    """Map a failed-lookup EnrichError onto the adapter last_status vocabulary the rescan
    circuit breaker reads: 'rate_limited' (429), 'auth_error' (401/403), or the catch-all
    'error' for anything else (transport failure, malformed body, no status code, etc.)."""
    if exc.status_code == 429:
        return "rate_limited"
    if exc.status_code in (401, 403):
        return "auth_error"
    return "error"
