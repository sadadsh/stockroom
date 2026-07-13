"""Web MIME-type registration seam (the Windows mimetypes registry trap).

Task 4 needs this import to resolve so the app factory can call it before any
static mount. The real registration logic (forcing .js/.mjs/.css/.json/.wasm to
their correct types so WebView2 does not refuse a text/plain script) lands in
Task 12; this stub is a safe no-op on Linux where the default mimetypes map is
already correct. It is deliberately harmless until Task 12 fleshes it out."""

from __future__ import annotations


def register_web_mime_types() -> None:
    """No-op placeholder; the real implementation is added in Task 12."""
    return None
