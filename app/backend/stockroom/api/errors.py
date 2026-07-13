"""The single exception-to-HTTP mapping for the API.

Routers never invent a status code or an error shape; they raise the engine's
own exceptions and this module decides the status and the honest error envelope
(spec section 2.2: no swallowed errors, every failure states what happened). An
incomplete add carries its per-field missing list so the UI can tell the user
exactly what to fill, never a bare 500."""

from __future__ import annotations

from stockroom.enrich.errors import EnrichError
from stockroom.ingest.errors import IngestError
from stockroom.kicad.errors import KiCadCliError
from stockroom.mutation.library_ops import IncompleteError
from stockroom.vcs.repo import GitError


class ApiError(Exception):
    """A deliberate API-level failure with an explicit status."""

    def __init__(self, status: int, detail: str):
        self.status = status
        self.detail = detail
        super().__init__(detail)


def status_for(exc: Exception) -> int:
    if isinstance(exc, ApiError):
        return exc.status
    if isinstance(exc, IncompleteError):
        return 422
    if isinstance(exc, GitError):
        return 503
    if isinstance(exc, (IngestError, EnrichError, KiCadCliError)):
        return 502
    if isinstance(exc, (FileNotFoundError, KeyError)):
        return 404
    if isinstance(exc, ValueError):
        return 400
    return 500


def error_body(exc: Exception) -> dict:
    body = {"error": type(exc).__name__, "detail": str(exc)}
    missing = getattr(exc, "missing", None)
    if missing is not None:
        body["missing"] = list(missing)
    return body
