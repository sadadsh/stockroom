"""One durable, readable trace of every capture DECISION, written to a known file.

WHY THIS MODULE EXISTS
On 2026-07-31 an automatic capture ran, produced no CAD package, and the only thing the owner
was told was "Automatic lookup finished without a complete CAD package." The real cause (a
signed-out Ultra Librarian profile) had to be guessed. Meanwhile ``%APPDATA%\\Stockroom\\capture.log``
still held entries from 2026-07-26, because the handler that wrote it lived in
``host/window.py::_install_capture_logfile`` and was deleted with the rest of the pre-rewrite CAD
host in commit 24a5125. The capture package that replaced it shipped with NO logging of any kind.

That is the defect this fixes, and the fix is deliberately NOT in the host: capture now runs inside
the API/worker process, so a handler installed by the desktop shell would never see it. Installation
is lazy and idempotent, performed by the first trace call in whichever process actually captures.

WHAT MAY BE WRITTEN
Decision INPUTS only: a selector, a match count, the NAME of a marker that fired, a URL host and
path, a file name and byte size, a bounded provider-authored reason that already reached the report.
Never credentials, tokens, cookies, session identifiers, or harvested page content. Two independent
guards enforce that:

  * a field whose NAME looks credential-bearing is emitted as ``[redacted]`` without ever formatting
    its value, so a future call site cannot leak a secret by passing it;
  * every string value is collapsed, stripped of URL queries and ``secret=value`` assignments, and
    bounded, so a value that unexpectedly carries provider text cannot become a page dump.

Prefer a boolean, a count, or a length over any value that could carry provider content.

IT MAY NEVER CHANGE OR FAIL A CAPTURE
Every public entry point swallows everything. A read-only config directory, a full disk, or a
detector that raises while being described must all end as a missing log line and nothing else.
"""

from __future__ import annotations

import logging
import os
import re
import threading
from collections.abc import Sized
from pathlib import Path
from urllib.parse import urlsplit

LOGGER_NAME = "stockroom.capture"

_log = logging.getLogger(LOGGER_NAME)

_INSTALL_LOCK = threading.Lock()
# ``wanted`` is the destination the last attempt was made FOR, so a failed install is remembered
# rather than retried on every line, while a genuinely different destination still reinstalls.
_INSTALLED: dict[str, object] = {"wanted": None, "path": None}

# A trace line is read by a person scanning for one part's story, so values stay short. 200 is
# comfortably longer than every provider reason this repo produces and far shorter than any
# page body, which is the point.
_MAX_VALUE_CHARS = 200
_MAX_SEQUENCE_ITEMS = 12
_MAX_FIELDS = 32
_MAX_BYTES = 4_000_000
_BACKUP_COUNT = 3

# Substrings that make a field name ineligible to carry a value at all. Matched on the NAME so the
# value is never formatted, never truncated into a line, and never held in a local.
_FORBIDDEN_FIELD_MARKERS = (
    "password",
    "passwd",
    "secret",
    "token",
    "cookie",
    "credential",
    "apikey",
    "api_key",
    "authorization",
    "auth_header",
    "bearer",
    "session_id",
    "sessionid",
    "session_key",
    "username",
    "user_name",
    "passphrase",
    "private_key",
    "otp",
)

_URL = re.compile(r"https?://[^\s]+", re.IGNORECASE)
_SECRET_ASSIGNMENT = re.compile(
    r"(?i)\b(password|passwd|token|secret|api[-_ ]?key|authorization|cookie)"
    r"\s*[:=]\s*[^\s;,]+"
)
_UNSAFE_EVENT = re.compile(r"[^a-z0-9._-]+")


def capture_log_path() -> Path:
    """The one discoverable file every capture run appends to.

    ``%APPDATA%\\Stockroom\\capture.log`` on Windows because that is where the owner already
    looks; ``STOCKROOM_CAPTURE_LOG`` overrides it for tests and portable installs, and
    ``STOCKROOM_CONFIG_DIR`` moves it with the rest of the machine config.
    """

    override = os.environ.get("STOCKROOM_CAPTURE_LOG")
    if override:
        return Path(override)
    from stockroom.store.machine_config import config_dir

    return config_dir() / "capture.log"


def install_capture_log() -> Path | None:
    """Attach the rotating file handler. Returns the path, or None when it could not be attached.

    Idempotent and best effort. A read-only or unwritable location leaves the logger without a
    file handler; the trace calls then cost a level check and nothing else, and the capture is
    entirely unaffected.

    The destination is re-derived rather than frozen at first use, because a long-lived process
    can legitimately change ``STOCKROOM_CONFIG_DIR``/``STOCKROOM_CAPTURE_LOG`` under it - the whole
    test suite does exactly that, per test. A handler left pointing at a directory that no longer
    exists is a silently dead log, which is the failure this module was written to end.
    """

    try:
        wanted = capture_log_path()
    except Exception:  # noqa: BLE001 - an underivable path is simply no file log
        return None
    if _INSTALLED["wanted"] == wanted:
        path = _INSTALLED["path"]
        return path if isinstance(path, Path) else None
    with _INSTALL_LOCK:
        if _INSTALLED["wanted"] == wanted:
            path = _INSTALLED["path"]
            return path if isinstance(path, Path) else None
        _INSTALLED["wanted"] = wanted
        _INSTALLED["path"] = None
        try:
            from logging.handlers import RotatingFileHandler

            # Drop any handler this module installed for a previous destination. Handlers the
            # host or a test added itself are left alone.
            for existing in list(_log.handlers):
                if getattr(existing, "_stockroom_capture_trace", False):
                    _log.removeHandler(existing)
                    try:
                        existing.close()
                    except Exception:  # noqa: BLE001 - teardown is best effort
                        pass
            wanted.parent.mkdir(parents=True, exist_ok=True)
            handler = RotatingFileHandler(
                wanted,
                maxBytes=_MAX_BYTES,
                backupCount=_BACKUP_COUNT,
                encoding="utf-8",
                delay=True,
            )
            handler.setFormatter(
                logging.Formatter("%(asctime)s %(levelname)s %(message)s")
            )
            handler.setLevel(logging.DEBUG)
            setattr(handler, "_stockroom_capture_trace", True)
            _log.addHandler(handler)
            _log.setLevel(_configured_level())
            _INSTALLED["path"] = wanted
            return wanted
        except Exception:  # noqa: BLE001 - a diagnostic aid is never a capture blocker
            _INSTALLED["path"] = None
            return None


def reset_for_tests() -> None:
    """Drop the installed handler so a test can point the trace at its own file."""

    with _INSTALL_LOCK:
        for handler in list(_log.handlers):
            _log.removeHandler(handler)
            try:
                handler.close()
            except Exception:  # noqa: BLE001 - teardown is best effort
                pass
        _INSTALLED["wanted"] = None
        _INSTALLED["path"] = None


def trace(event: str, **fields: object) -> None:
    """Record one decision in the chain. INFO: this is what a person reads by default."""

    _emit(logging.INFO, event, fields)


def trace_debug(event: str, **fields: object) -> None:
    """Record one step detail. DEBUG: available when the decision chain is not enough."""

    _emit(logging.DEBUG, event, fields)


def trace_warning(event: str, **fields: object) -> None:
    """Record a decision that ended a route or a part."""

    _emit(logging.WARNING, event, fields)


def url_note(url: object) -> str:
    """Host and path only. A provider query string can carry identifiers, so it never lands."""

    try:
        text = str(url or "").strip()
        if not text:
            return ""
        parsed = urlsplit(text)
        if not parsed.scheme and not parsed.netloc:
            return _bounded(text)
        host = parsed.hostname or ""
        return _bounded(f"{host}{parsed.path}" if host else parsed.path)
    except Exception:  # noqa: BLE001 - an unparseable URL is described, never raised over
        return "[unreadable url]"


def file_note(path: object) -> str:
    """``name(bytes)`` for one landed file, with no directory tree and no content."""

    try:
        candidate = Path(str(path))
        try:
            size: object = candidate.stat().st_size
        except OSError:
            size = "unreadable"
        return _bounded(f"{candidate.name}({size})")
    except Exception:  # noqa: BLE001
        return "[unreadable file]"


def count_of(value: object) -> int:
    """A length rather than a value, for anything that could carry provider content."""

    try:
        return len(value) if isinstance(value, Sized) else -1
    except Exception:  # noqa: BLE001
        return -1


def _configured_level() -> int:
    name = str(os.environ.get("STOCKROOM_CAPTURE_LOG_LEVEL", "") or "").strip().upper()
    return getattr(logging, name, logging.INFO) if name else logging.INFO


def _emit(level: int, event: str, fields: dict) -> None:
    try:
        install_capture_log()
        if not _log.isEnabledFor(level):
            return
        _log.log(level, "%s", _render(event, fields))
    except Exception:  # noqa: BLE001 - a logging failure must never fail a capture
        pass


def _render(event: str, fields: dict) -> str:
    parts = [_event_name(event)]
    for index, (name, value) in enumerate(fields.items()):
        if index >= _MAX_FIELDS:
            parts.append("...")
            break
        parts.append(f"{name}={_field(name, value)}")
    return " ".join(parts)


def _event_name(event: object) -> str:
    text = _UNSAFE_EVENT.sub("-", str(event or "capture").strip().casefold())
    return text[:64] or "capture"


def _forbidden(name: str) -> bool:
    folded = str(name).casefold()
    return any(marker in folded for marker in _FORBIDDEN_FIELD_MARKERS)


def _field(name: str, value: object) -> str:
    if _forbidden(name):
        return "[redacted]"
    return _value(value)


def _value(value: object) -> str:
    if value is None:
        return "none"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, int) or isinstance(value, float):
        return str(value)
    if isinstance(value, Path):
        return _quoted(_bounded(str(value)))
    if isinstance(value, (list, tuple, set, frozenset)):
        items = list(value)
        rendered = [_value(item) for item in items[:_MAX_SEQUENCE_ITEMS]]
        if len(items) > _MAX_SEQUENCE_ITEMS:
            rendered.append("...")
        return "[" + ",".join(rendered) + "]"
    return _quoted(_bounded(str(value)))


def _bounded(text: str) -> str:
    collapsed = " ".join(str(text).split())
    collapsed = _URL.sub(lambda match: url_note(match.group(0)), collapsed)
    collapsed = _SECRET_ASSIGNMENT.sub(
        lambda match: f"{match.group(1)}=[redacted]", collapsed
    )
    if len(collapsed) > _MAX_VALUE_CHARS:
        return collapsed[: _MAX_VALUE_CHARS - 1].rstrip() + "…"
    return collapsed


def _quoted(text: str) -> str:
    if text == "":
        return '""'
    if any(character in text for character in ' "'):
        return '"' + text.replace('"', "'") + '"'
    return text


__all__ = [
    "LOGGER_NAME",
    "capture_log_path",
    "count_of",
    "file_note",
    "install_capture_log",
    "reset_for_tests",
    "trace",
    "trace_debug",
    "trace_warning",
    "url_note",
]
