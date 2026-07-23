"""Dev mode (owner-only): persist nudged design tokens + reworded UI copy back to source.

The frontend's hidden dev mode (Ctrl+Shift+D) edits the app's own colours, radii, and labels
live, then POSTs the complete override set here. This writes two committed source files -
``lib/token.overrides.ts`` and ``lib/copy.overrides.ts`` - so a saved change ships for everyone
once committed, not as a per-machine setting. It is a source-tree tool: with no frontend source
present (a packaged build) it refuses honestly rather than pretending to save. Every value is
validated and JSON-encoded, so a value can never inject arbitrary code into the generated module.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from fastapi import APIRouter, Depends, Request

from stockroom.api.errors import ApiError

# frontend/src, relative to this file: routers -> api -> stockroom -> backend -> app -> frontend/src
_FRONTEND_SRC = Path(__file__).resolve().parents[4] / "frontend" / "src"

# A CSS custom property name, a conservative CSS value (colour or length), and a copy id / text.
_CSS_VAR_RE = re.compile(r"^--[a-z0-9-]+$")
_VALUE_RE = re.compile(r"^[#a-zA-Z0-9(),.%/ \-]+$")
_COPY_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_MAX_VALUE_LEN = 200
_MAX_COPY_LEN = 2000

_TOKENS_HEADER = """/**
 * Committed design-token overrides, written by dev mode (Ctrl+Shift+D -> the Design panel).
 * This file is the SOURCE OF TRUTH for any token the owner has nudged: it is applied on boot for
 * everyone (not a per-machine setting), so a saved tweak ships with the app. Empty means "use the
 * shipped defaults in styles/index.css".
 *
 * `root` holds the dark-theme colours AND the theme-agnostic radii (they live on :root, like the
 * index.css defaults); `light` holds the light-theme colour overrides. Each value is a raw CSS
 * value (a hex / rgb(a) colour or a px length). This file is regenerated whole by POST
 * /api/dev/save - keep it to the single const export so the writer stays simple; it is safe to
 * hand-edit.
 */
export const TOKEN_OVERRIDES: {
  root: Record<string, string>;
  light: Record<string, string>;
} = """

_COPY_HEADER = """/**
 * Committed UI-copy overrides, written by dev mode (Ctrl+Shift+D, then click any label). This
 * file is the SOURCE OF TRUTH for any label the owner has reworded: it is read on every render
 * for everyone (not a per-machine setting), so a saved rewording ships with the app. A key is a
 * stable copy id (see <Text id="...">); an absent id falls back to the default text written in
 * the JSX. Regenerated whole by POST /api/dev/save - safe to hand-edit.
 */
export const COPY_OVERRIDES: Record<string, string> = """


def _clean_tokens(block: object) -> dict:
    """Keep only well-formed (css-var -> safe css value) pairs; drop anything suspect."""
    out: dict = {}
    if not isinstance(block, dict):
        return out
    for key, value in block.items():
        if not isinstance(key, str) or not _CSS_VAR_RE.match(key):
            continue
        if not isinstance(value, str):
            continue
        v = value.strip()
        if not v or len(v) > _MAX_VALUE_LEN or not _VALUE_RE.match(v):
            continue
        out[key] = v
    return out


def _clean_copy(block: object) -> dict:
    """Keep only well-formed (copy-id -> text) pairs, length-capped."""
    out: dict = {}
    if not isinstance(block, dict):
        return out
    for key, value in block.items():
        if not isinstance(key, str) or not _COPY_ID_RE.match(key):
            continue
        if not isinstance(value, str) or len(value) > _MAX_COPY_LEN:
            continue
        out[key] = value
    return out


def _emit(path: Path, header: str, data) -> None:
    body = json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True)
    path.write_text(header + body + ";\n", encoding="utf-8")


def dev_router(require_token) -> APIRouter:
    r = APIRouter(prefix="/api/dev", dependencies=[Depends(require_token)])

    @r.post("/save")
    def save(request: Request, body: dict) -> dict:
        lib = _FRONTEND_SRC / "lib"
        if not lib.exists():
            # Hidden dev tool: with no source tree there is nothing to write, so refuse honestly
            # instead of pretending. This is the expected state inside a packaged build.
            raise ApiError(409, "Dev mode needs the frontend source tree; it is not available in a packaged build.")
        tokens = body.get("tokens") if isinstance(body, dict) else None
        copy = body.get("copy") if isinstance(body, dict) else None
        root = _clean_tokens((tokens or {}).get("root") if isinstance(tokens, dict) else None)
        light = _clean_tokens((tokens or {}).get("light") if isinstance(tokens, dict) else None)
        clean_copy = _clean_copy(copy)

        _emit(lib / "token.overrides.ts", _TOKENS_HEADER, {"root": root, "light": light})
        _emit(lib / "copy.overrides.ts", _COPY_HEADER, clean_copy)

        return {
            "ok": True,
            "written": [
                "app/frontend/src/lib/token.overrides.ts",
                "app/frontend/src/lib/copy.overrides.ts",
            ],
            "tokens": len(root) + len(light),
            "copy": len(clean_copy),
        }

    return r
