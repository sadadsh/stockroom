"""Force-register the correct web MIME types BEFORE any static mount.

Python's mimetypes reads the Windows registry, which frequently maps .js to
text/plain; served that way, a Vite JS bundle is refused by the browser and the
WebView2 window comes up blank (spec section 3.7, the verified Windows trap). This
module overrides the type map explicitly and idempotently, on every platform, so
the trap cannot fire. It imports nothing GUI and is fully testable on Linux; the
host and the app factory both call register_web_mime_types() at startup."""

from __future__ import annotations

import mimetypes

# Explicit, correct types that must win over any OS registry mapping.
_WEB_TYPES: dict[str, str] = {
    ".js": "text/javascript",
    ".mjs": "text/javascript",
    ".css": "text/css",
    ".json": "application/json",
    ".wasm": "application/wasm",
    ".svg": "image/svg+xml",
    ".map": "application/json",
}


def register_web_mime_types() -> None:
    for suffix, ctype in _WEB_TYPES.items():
        # add_type with a leading entry makes this the guessed type; calling it
        # repeatedly is safe (mimetypes stores one type per extension).
        mimetypes.add_type(ctype, suffix)


def web_mime_type(filename: str) -> str:
    register_web_mime_types()
    guessed, _ = mimetypes.guess_type(filename)
    return guessed or "application/octet-stream"
