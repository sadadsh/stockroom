"""Dev mode (owner-only): persist nudged design tokens, reworded UI copy, re-drawn icons, and
per-element overrides back to source.

The frontend's hidden dev mode (Ctrl+Shift+D) edits the app's own colours, radii, labels, icons,
and per-element size / spacing / layout live, then POSTs the complete override set here. This writes
four committed source files - ``lib/token.overrides.ts``, ``lib/copy.overrides.ts``,
``lib/icon.overrides.ts`` and ``lib/element.overrides.ts`` - so a saved change ships for everyone
once committed, not as a per-machine setting. It is a source-tree tool: with no frontend source
present (a packaged build) it refuses honestly rather than pretending to save.

Every value is validated and the writer re-serialises from the validated fields, never echoing raw
input, so nothing a caller sends can inject code into a generated module: tokens/copy against a
conservative grammar; icon bodies through a strict SVG sanitiser (whitelisted shape/path elements +
geometry/stroke/fill attributes only, no script / event handlers / remote refs / foreignObject /
DOCTYPE); per-element CSS through a safe length / keyword / grid-slot grammar. A malicious icon or
CSS value is rejected with a 400 before anything is written, so a bad payload leaves the four files
untouched.
"""

from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path

from fastapi import APIRouter, Depends, Request

from stockroom.api.errors import ApiError

# frontend/src, relative to this file: routers -> api -> stockroom -> backend -> app -> frontend/src
_FRONTEND_SRC = Path(__file__).resolve().parents[4] / "frontend" / "src"

# A CSS custom property name, a conservative CSS value (colour or length), and a copy id / text.
_CSS_VAR_RE = re.compile(r"^--[a-z0-9-]+$")
_VALUE_RE = re.compile(r"^[#a-zA-Z0-9(),.%/ \-]+$")
_COPY_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
# A stable dot-namespaced id: lowercase-kebab segments joined by dots (icon ids, dev-element ids,
# a glyph swap target), mirroring lib/devIds.ts + the copy id convention. Shape-checks keys +
# swapToId so only a "known-shaped" id is ever written into committed source.
_DEV_ID_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*(?:\.[a-z0-9]+(?:-[a-z0-9]+)*)*$")
_MAX_VALUE_LEN = 200
_MAX_COPY_LEN = 2000
_MAX_ICON_BODY_LEN = 20000
_MAX_CSS_VALUE_LEN = 64

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

# Header + the IconOverride interface, ending at the const assignment; the writer appends the JSON
# object + ";\n". An empty save reproduces the committed lib/icon.overrides.ts byte-for-byte.
_ICONS_HEADER = """/**
 * Committed icon overrides, written by dev mode (Ctrl+Shift+D, then the Icon tab). This file is the
 * SOURCE OF TRUTH for any icon the owner has re-drawn: it is read on boot for everyone (not a per-machine
 * setting), so a saved icon ships with the app. A key is a stable icon id (see lib/iconRegistry.ts /
 * <Icon id="...">); an absent id falls back to the registry default. Each value is either `{ body }` -
 * sanitised inner SVG markup that replaces the glyph - or `{ swapToId }` - another registry id whose glyph
 * to render instead. Generated whole by POST /api/dev/save through a strict SVG validator; safe to
 * hand-edit but the backend validator is the authority on what may ship.
 */
export interface IconOverride {
  // Sanitised inner SVG markup (paths, shapes) that replaces the registry glyph's body.
  body?: string;
  // Another registry icon id whose glyph to render instead (a glyph swap).
  swapToId?: string;
}

export const ICON_OVERRIDES: Record<string, IconOverride> = """

_ELEMENTS_HEADER = """/**
 * Committed per-element overrides, written by dev mode (Ctrl+Shift+D, then the Box tab). This file is the
 * SOURCE OF TRUTH for any single element the owner has tuned locally - the escape hatch for the one-off a
 * global token cannot reach (size, spacing, and later layout order / grid slot). It is applied on boot for
 * everyone (not a per-machine setting) as an inline style on every element carrying the matching
 * `data-dev-id`, so a saved tweak ships with the app. A key is a stable dev id (see lib/devIds.ts /
 * data-dev-id="..."); the value is a map of CSS property -> value. Generated whole by POST /api/dev/save
 * through a strict CSS-value validator (safe lengths / keywords only); safe to hand-edit but the backend
 * validator is the authority on what may ship.
 */
export const ELEMENT_OVERRIDES: Record<string, Record<string, string>> = """


# --- token + copy validators (v1, unchanged) --------------------------------------------------

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


# --- icon (SVG) sanitiser ---------------------------------------------------------------------
# The main injection surface of dev-mode v2: an owner-authored SVG body ships to everyone, so the
# backend is the authority. Only a whitelist of shape/path elements + geometry/stroke/fill/transform
# attributes survive; the tree is re-serialised from validated nodes, never echoed raw.

_SVG_ALLOWED_TAGS = {
    "path", "circle", "rect", "line", "polyline", "polygon", "ellipse", "g", "defs", "use",
}
_SVG_ALLOWED_ATTRS = {
    # identity / grouping
    "id", "class",
    # geometry
    "d", "cx", "cy", "r", "rx", "ry", "x", "y", "x1", "y1", "x2", "y2",
    "width", "height", "points", "pathlength", "transform", "transform-origin",
    # stroke
    "stroke", "stroke-width", "stroke-linecap", "stroke-linejoin", "stroke-dasharray",
    "stroke-dashoffset", "stroke-miterlimit", "stroke-opacity", "vector-effect",
    # fill / paint
    "fill", "fill-rule", "fill-opacity", "opacity", "color", "clip-rule", "clip-path",
}
# Cheap defence-in-depth pre-scan (the parse walk is authoritative): tokens that must never appear
# anywhere in the raw body. DOCTYPE / entities (`<!`), processing instructions (`<?`), remote/script
# vectors, numeric char entities (`&#`, billion-laughs vector).
_SVG_FORBIDDEN = (
    "<script", "</script", "<!", "<?", "foreignobject", "<style", "<iframe",
    "<image", "<audio", "<video", "javascript:", "vbscript:", "expression(", "data:", "&#",
)
_SVG_EVENT_ATTR_RE = re.compile(r"\son[a-z]+\s*=")


def _local(name: str) -> str:
    """Drop an XML namespace prefix: ``{http://...}path`` -> ``path`` (and pass a bare name through)."""
    return name.rsplit("}", 1)[-1]


def _xml_escape(value: str) -> str:
    return (
        value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
    )


def _validate_svg_el(el) -> None:
    """Reject the element (and recurse) unless it is a whitelisted shape with only safe attributes."""
    tag = _local(el.tag).lower()
    if tag not in _SVG_ALLOWED_TAGS:
        raise ApiError(400, f"Icon body uses a disallowed SVG element <{tag}>.")
    for key, value in el.attrib.items():
        name = _local(key).lower()
        val = value if isinstance(value, str) else ""
        low = val.lower()
        if name == "href":
            # a local fragment ref (#id) only; any external target is rejected
            if not val.strip().startswith("#"):
                raise ApiError(400, "Icon body has an external href; only #local refs are allowed.")
            continue
        if name.startswith("on"):
            raise ApiError(400, "Icon body has an event-handler attribute.")
        if name not in _SVG_ALLOWED_ATTRS:
            raise ApiError(400, f"Icon body uses a disallowed attribute '{name}'.")
        if "<" in val or "javascript:" in low or "expression(" in low or "data:" in low:
            raise ApiError(400, "Icon body has an unsafe attribute value.")
        if "url(" in low and "url(#" not in low:
            raise ApiError(400, "Icon body references a remote url(); only url(#local) is allowed.")
    for child in el:
        _validate_svg_el(child)


def _serialize_svg_el(el) -> str:
    """Rebuild an element from its validated tag + attributes (local names, escaped values)."""
    tag = _local(el.tag)
    parts = ["<", tag]
    for key, value in el.attrib.items():
        parts.append(f' {_local(key)}="{_xml_escape(value)}"')
    children = list(el)
    if not children:
        parts.append("/>")
        return "".join(parts)
    parts.append(">")
    for child in children:
        parts.append(_serialize_svg_el(child))
    parts.extend(["</", tag, ">"])
    return "".join(parts)


def _sanitize_svg_body(raw: object) -> str:
    """Validate inner SVG markup and return a re-serialised, safe body, or raise ApiError(400)."""
    if not isinstance(raw, str):
        raise ApiError(400, "Icon body must be a string.")
    body = raw.strip()
    if not body:
        raise ApiError(400, "Icon body is empty.")
    if len(body) > _MAX_ICON_BODY_LEN:
        raise ApiError(400, "Icon body is too large.")
    low = body.lower()
    for bad in _SVG_FORBIDDEN:
        if bad in low:
            raise ApiError(400, f"Icon body contains a forbidden token '{bad}'.")
    if _SVG_EVENT_ATTR_RE.search(low):
        raise ApiError(400, "Icon body contains an event-handler attribute.")
    wrapped = (
        '<svg xmlns="http://www.w3.org/2000/svg" '
        'xmlns:xlink="http://www.w3.org/1999/xlink">' + body + "</svg>"
    )
    try:
        root = ET.fromstring(wrapped)  # noqa: S314 - DOCTYPE/entities pre-rejected above
    except ET.ParseError as exc:
        raise ApiError(400, f"Icon body is not well-formed SVG: {exc}.")
    children = list(root)
    if not children:
        raise ApiError(400, "Icon body has no drawable SVG elements.")
    out = []
    for child in children:
        _validate_svg_el(child)
        out.append(_serialize_svg_el(child))
    return "".join(out)


def _clean_icons(block: object) -> dict:
    """Validate the icons block into {id -> {body?, swapToId?}}; a malicious body / bad swap is a 400.

    Keys are shape-checked (a malformed id is dropped, mirroring the token/copy key handling); every
    present body / swapToId is strictly validated, and a failure raises before anything is written."""
    out: dict = {}
    if not isinstance(block, dict):
        return out
    for key, entry in block.items():
        if not isinstance(key, str) or not _DEV_ID_RE.match(key):
            continue
        if not isinstance(entry, dict):
            continue
        result: dict = {}
        body = entry.get("body")
        swap = entry.get("swapToId")
        if body is not None:
            result["body"] = _sanitize_svg_body(body)
        if swap is not None:
            if not isinstance(swap, str) or not _DEV_ID_RE.match(swap):
                raise ApiError(400, f"Icon swap target '{swap}' is not a valid icon id.")
            result["swapToId"] = swap
        if result:
            out[key] = result
    return out


# --- per-element CSS validator ----------------------------------------------------------------
# A whitelisted property set with a safe length / keyword / integer / grid-slot grammar. No arbitrary
# CSS: any value carrying `;`, `<`, `{`, `}`, `url(`, `expression(`, `/*` or a newline is rejected.

_ELEM_ALLOWED_PROPS = {
    # size
    "width", "height", "min-width", "min-height", "max-width", "max-height",
    # spacing
    "margin", "margin-top", "margin-right", "margin-bottom", "margin-left",
    "padding", "padding-top", "padding-right", "padding-bottom", "padding-left",
    "gap", "row-gap", "column-gap",
    # layout (Phase F)
    "order", "grid-column", "grid-row",
}
_ELEM_FORBIDDEN = (";", "<", ">", "{", "}", "url(", "expression(", "/*", "*/", "\\", "@")
_LENGTH_KEYWORDS = {"auto", "none", "0", "min-content", "max-content", "fit-content"}
_LENGTH_RE = re.compile(r"^-?(?:\d+|\d*\.\d+)(?:px|rem|em|vh|vw|%)$")
_ORDER_RE = re.compile(r"^-?\d{1,3}$")
# one grid line token: auto, a small integer, `span N`/`span name`, or a named grid line
_GRID_TOKEN_RE = re.compile(r"^(?:auto|-?\d{1,4}|span\s+(?:\d{1,4}|[a-zA-Z][\w-]*)|[a-zA-Z][\w-]*)$")


def _valid_grid_slot(value: str) -> bool:
    """A grid-column / grid-row value: 1 or 2 line tokens separated by a single `/`."""
    parts = [p.strip() for p in value.split("/")]
    if not 1 <= len(parts) <= 2:
        return False
    return all(p and _GRID_TOKEN_RE.match(p) for p in parts)


def _valid_css_value(prop: str, value: str) -> bool:
    """True only for a value in the safe grammar for `prop` (a whitelisted property)."""
    if "\n" in value or "\r" in value:
        return False
    v = value.strip()
    if not v or len(v) > _MAX_CSS_VALUE_LEN:
        return False
    low = v.lower()
    if any(bad in low for bad in _ELEM_FORBIDDEN):
        return False
    if prop == "order":
        return bool(_ORDER_RE.match(v))
    if prop in ("grid-column", "grid-row"):
        return _valid_grid_slot(v)
    # size / spacing / gap: a safe length or a size keyword
    return low in _LENGTH_KEYWORDS or bool(_LENGTH_RE.match(v))


def _clean_elements(block: object) -> dict:
    """Validate the elements block into {devId -> {cssProp -> value}}; a bad prop / value is a 400.

    Keys are shape-checked (a malformed dev id is dropped); every property is whitelisted and every
    value validated against its grammar, raising before anything is written."""
    out: dict = {}
    if not isinstance(block, dict):
        return out
    for key, props in block.items():
        if not isinstance(key, str) or not _DEV_ID_RE.match(key):
            continue
        if not isinstance(props, dict):
            continue
        clean: dict = {}
        for prop, value in props.items():
            if not isinstance(prop, str):
                continue
            name = prop.strip().lower()
            if name not in _ELEM_ALLOWED_PROPS:
                raise ApiError(400, f"CSS property '{prop}' is not editable.")
            if not isinstance(value, str) or not _valid_css_value(name, value):
                raise ApiError(400, f"CSS value '{value}' for '{name}' is not allowed.")
            clean[name] = value.strip()
        if clean:
            out[key] = clean
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
        icons = body.get("icons") if isinstance(body, dict) else None
        elements = body.get("elements") if isinstance(body, dict) else None

        # Validate every block up front: a malicious icon / CSS value raises here, before any file is
        # written, so a bad payload can never leave the four override files half-updated.
        root = _clean_tokens((tokens or {}).get("root") if isinstance(tokens, dict) else None)
        light = _clean_tokens((tokens or {}).get("light") if isinstance(tokens, dict) else None)
        clean_copy = _clean_copy(copy)
        clean_icons = _clean_icons(icons)
        clean_elements = _clean_elements(elements)

        _emit(lib / "token.overrides.ts", _TOKENS_HEADER, {"root": root, "light": light})
        _emit(lib / "copy.overrides.ts", _COPY_HEADER, clean_copy)
        _emit(lib / "icon.overrides.ts", _ICONS_HEADER, clean_icons)
        _emit(lib / "element.overrides.ts", _ELEMENTS_HEADER, clean_elements)

        return {
            "ok": True,
            "written": [
                "app/frontend/src/lib/token.overrides.ts",
                "app/frontend/src/lib/copy.overrides.ts",
                "app/frontend/src/lib/icon.overrides.ts",
                "app/frontend/src/lib/element.overrides.ts",
            ],
            "tokens": len(root) + len(light),
            "copy": len(clean_copy),
            "icons": len(clean_icons),
            "elements": len(clean_elements),
        }

    return r
