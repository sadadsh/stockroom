"""Dev mode (owner-only): persist nudged design tokens, reworded UI copy, re-drawn icons,
per-element overrides and the committed ARRANGEMENT back to source.

The frontend's hidden dev mode (Ctrl+Shift+D) edits the app's own colours, radii, labels, icons,
per-element size / spacing / layout and - since Design Mode Phase 4 - the layout document itself
live, then POSTs the complete override set here. This writes six committed source files -
``lib/token.overrides.ts``, ``lib/copy.overrides.ts``, ``lib/icon.overrides.ts``,
``lib/element.overrides.ts``, ``lib/behavior.overrides.ts`` and ``lib/layout.overrides.ts`` - so a
saved change ships for everyone once committed, not as a per-machine setting. It is a source-tree
tool: with no frontend source present (a packaged build) it refuses honestly rather than pretending
to save.

WHAT GATES THIS ENDPOINT RUNS, stated plainly because the Phase 4 brief asks for the finding rather
than an assumption: /api/dev/save runs NO build, NO typecheck and NO test suite. It validates every
value, writes the six modules, and returns. The gates a saved design actually passes are the ones
every one of the six slices has always relied on - ``POST /api/dev/publish`` below runs a locked
dependency install, ``npm run typecheck`` and a production build before it commits and pushes, and
the repository's own CI / pre-commit run the suites. The layout module is deliberately inside that
same regime rather than gaining a private one: it is in ``_DEV_SOURCE_PATHS`` (so publish owns it,
commits it, and refuses if a build moved anything outside the boundary), and because it is a TYPED
module - the emitted document is assigned to ``LayoutOverrides`` - a malformed commit fails the
publish typecheck exactly as a malformed token file would.

Every value is validated and the writer re-serialises from the validated fields, never echoing raw
input, so nothing a caller sends can inject code into a generated module: tokens/copy against a
conservative grammar; icon bodies through a strict SVG sanitiser (whitelisted shape/path elements +
geometry/stroke/fill attributes only, no script / event handlers / remote refs / foreignObject /
DOCTYPE); per-element CSS through a safe length / keyword / grid-slot grammar. A malicious icon or
CSS value is rejected with a 400 before anything is written, so a bad payload leaves the five files
untouched.

Two things the writer is the authority on beyond raw safety:

  * COPY PLACEHOLDERS. A copy entry that carries a value writes it as ``{name}``. The default lives
    in the JSX, so the frontend sends the placeholder set each id DECLARES and a rewording that is
    malformed, drops a required name, or invents an unknown one is refused with a message naming
    the placeholder. The render path fails safe on a stale override; this stops one being made.
  * DYNAMIC ELEMENT IDS. An element that exists once per open component or per staged candidate has
    no catalogue row, so its id carries a bracketed instance value. Those ids are accepted only in
    the shapes ``lib/componentDevIds.ts`` builds; any other bracketed id is dropped, so an override
    can never be keyed on an unregistered selector.
"""

from __future__ import annotations

import json
import re
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

from fastapi import APIRouter, Depends, Request

from stockroom.api.errors import ApiError
from stockroom.vcs.repo import GitError

# frontend/src, relative to this file: routers -> api -> stockroom -> backend -> app -> frontend/src
_FRONTEND_SRC = Path(__file__).resolve().parents[4] / "frontend" / "src"

# A CSS custom property name, a conservative CSS value (colour or length), and a copy id / text.
_CSS_VAR_RE = re.compile(r"^--[a-z0-9-]+$")
_VALUE_RE = re.compile(r"^[#a-zA-Z0-9(),.%/ \-]+$")
_COPY_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
# A stable dot-namespaced id: lowercase-kebab segments joined by dots (icon ids, catalogued
# dev-element ids, a glyph swap target), mirroring lib/devIds.ts + the copy id convention.
# Shape-checks keys + swapToId so only a "known-shaped" id is ever written into committed source.
_DEV_ID_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*(?:\.[a-z0-9]+(?:-[a-z0-9]+)*)*$")

# --- dynamic (per-instance) dev ids -------------------------------------------------------------
# An element that exists once per OPEN COMPONENT or per STAGED CANDIDATE cannot have a catalogue
# row, so lib/componentDevIds.ts builds its id from a bracket grammar instead. Those ids must be
# writable - editing exactly one repeated instance is the point of them - but only in the SHAPES the
# builder emits. An arbitrary bracketed id is not "a dev id we forgot to catalogue", it is an
# unregistered selector, and it is dropped like any other malformed key.
#
# The bracket VALUE mirrors what `devIdSegment()` guarantees on the way in: bounded, and free of the
# brackets / quotes / backslash / whitespace / control characters that could close the grammar early
# or make the attribute unreadable.
_DEV_ID_VALUE = r"[^\[\]\"'`\\\s\x00-\x1f\x7f]{1,192}"
_DYNAMIC_DEV_ID_RES = tuple(
    re.compile(pattern)
    for pattern in (
        rf"^component-browser\.component\[{_DEV_ID_VALUE}\]$",
        rf"^component-browser\.component\[{_DEV_ID_VALUE}\]\.tab$",
        rf"^component-browser\.component\[{_DEV_ID_VALUE}\]\.representation\[{_DEV_ID_VALUE}\]$",
        rf"^component-browser\.component\[{_DEV_ID_VALUE}\]\.provider\[{_DEV_ID_VALUE}\]$",
        rf"^ingest\.candidate\[{_DEV_ID_VALUE}\]$",
        rf"^detail\.handoff-field\[{_DEV_ID_VALUE}\]$",
        rf"^detail\.handoff-open\[{_DEV_ID_VALUE}\]$",
        rf"^stm\.package\[{_DEV_ID_VALUE}\]$",
        rf"^stm\.family\[{_DEV_ID_VALUE}\]$",
    )
)
_MAX_DEV_ID_LEN = 512


def _valid_element_id(value: object) -> bool:
    """True for a stable box id or its explicit ``::text`` / ``::icon`` internal domain."""
    if not isinstance(value, str) or not value or len(value) > _MAX_DEV_ID_LEN:
        return False
    if "::" in value:
        base, separator, domain = value.rpartition("::")
        if not separator or domain not in {"text", "icon"} or "::" in base:
            return False
        value = base
    if "[" in value or "]" in value:
        return any(pattern.match(value) for pattern in _DYNAMIC_DEV_ID_RES)
    return bool(_DEV_ID_RE.match(value))


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

_BEHAVIORS_HEADER = """/**
 * Committed behavior overrides written by Dev Mode. Each entry changes how one compatible
 * control renders while preserving its value, options, disabled state, and change handler.
 * Generated whole by POST /api/dev/save.
 */
export type ChoicePreset = \"dropdown\" | \"segmented\" | \"radio\" | \"searchable\";

export interface BehaviorOverride {
  preset?: ChoicePreset;
  disabled?: boolean;
}

export const BEHAVIOR_OVERRIDES: Record<string, BehaviorOverride> = """

# --- the committed ARRANGEMENT (Design Mode Phase 4) --------------------------------------------
# Two exports in one module, written together and never apart: the document the owner committed, and
# the validator's reading of it AT THAT MOMENT. The second is not recomputed here - the validator is
# frontend TypeScript (layout/validateDocument.ts) and re-deriving it in Python would be a second
# implementation of the same rules, which is the shape that drifts. The frontend computes it at save
# time and this writer emits it verbatim after a structural check.
_LAYOUT_HEADER = """/**
 * Committed LAYOUT overrides: the arrangement the owner shipped, written by Design Mode's commit.
 *
 * The sibling of `token.overrides.ts`, `copy.overrides.ts`, `icon.overrides.ts`,
 * `element.overrides.ts` and `behavior.overrides.ts`, and it follows the same rule: this file is the
 * SOURCE OF TRUTH for a redesign, it applies on boot for EVERYONE (Design Mode on or off, because a
 * committed layout is not a per-machine setting), and `null` means "use the shipped default in
 * `layout/defaultWorkspaceLayout.ts`".
 *
 * Regenerated whole by POST /api/dev/save, exactly as its five siblings are - that is the owner's
 * decision 4 (plan 1.6): a committed redesign becomes the app and ships through main like any other
 * change. Named local drafts are still where an experiment lives; Save is what ends the experiment.
 *
 * WHY A KEYED OBJECT rather than a bare document. The plan's sequencing puts the workspace first
 * (Phase 1), the application shell in Phase 6 and the remaining routes in Phase 7, one at a time. Each
 * of those is its own layout document with its own default, so each gets its own key here rather than
 * its own module - one file the writer regenerates whole.
 *
 * WHAT MAY BE WRITTEN HERE: a document `layout/document.ts` can validate, at the schema version this
 * build knows. Nothing enforces that at boot and nothing should - a committed layout naming a piece
 * this build has not shipped is a real state (an older machine opening a newer layout), and
 * `validateLayout` REPORTS it while the renderer draws what it can. Warn, never block.
 */
import type { LayoutDocument } from "../layout/document";
import type { ValidatorIssue } from "../layout/validatorIssues";

export interface LayoutOverrides {
  /** The opened-component workspace (`workspace.component`), or `null` for the shipped default. */
  workspace: LayoutDocument | null;
}

export const LAYOUT_OVERRIDES: LayoutOverrides = """

_LAYOUT_ISSUES_HEADER = """/**
 * THE DEVIATION LIST THAT SHIPS WITH THE COMMIT (plan 1.4: "a committed layout's known issues are
 * part of the commit, visible in Dev Mode - honesty travels with the design").
 *
 * These are `validateDocument`'s findings for the document above, computed on the frontend at the
 * moment Save was pressed and written here verbatim. They are a RECORD, not a cache: live validation
 * may legitimately differ, because contrast is measured against whatever palette is in force, a
 * reachability finding follows the piece registry this build ships, and a later build can register
 * pieces this commit had never heard of. A row here that live validation no longer reports is not a
 * bug in either one - it is what the owner accepted when they committed, next to what is true now.
 *
 * An empty array for a slice means the validator found nothing at commit time. An absent slice key
 * cannot happen: the writer emits one entry per key of `LayoutOverrides`.
 */
export interface LayoutCommittedIssues {
  /** The validator's reading of `LAYOUT_OVERRIDES.workspace`, as of the commit that wrote it. */
  workspace: readonly ValidatorIssue[];
}

export const LAYOUT_COMMITTED_ISSUES: LayoutCommittedIssues = """

# Appended to lib/copy.overrides.ts beneath COPY_OVERRIDES. See `_clean_owner_authored_copy`.
_OWNER_AUTHORED_COPY_HEADER = """/**
 * OWNER-AUTHORED PROVENANCE for the rewordings above (plan 1.5, the owner amendment).
 *
 * The letter rule and the term map are the owner's own rules, enforced by `copy.letterRule.test.ts`
 * against text this application AUTHORS FOR the owner. Text the owner types themselves, through the
 * Design Mode editor, is not that: the lint exists to catch an agent writing a blocked word into
 * their product, not to overrule the owner inside it. So an id listed here is exempt from the letter
 * rule and every id that is not listed stays bound by it - including a rewording somebody hand-edited
 * into the map above, which is exactly the case the exemption must not cover.
 *
 * Written by POST /api/dev/save from what the editor reports it authored. Only an id that HAS an
 * override above can appear; the writer drops any other, so this can never become a standing
 * exemption for a string that is not there.
 */
export const OWNER_AUTHORED_COPY_IDS: readonly string[] = """


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


# --- copy placeholders --------------------------------------------------------------------------
# A copy entry that has to say a number or a name writes it as `{name}` (see lib/copyPlaceholders.ts).
# The DEFAULT lives in the JSX, so the frontend sends what each id declares and the writer holds the
# rewording to it. Both halves matter: the render path fails safe on a stale committed override, and
# this refuses to commit one in the first place, with a message that says which name is wrong.
_PLACEHOLDER_RE = re.compile(r"\{([A-Za-z][A-Za-z0-9_]*)\}")
_MAX_PLACEHOLDERS = 8


def _copy_placeholders(text: str) -> set[str] | None:
    """The placeholder names in a template, or None when a brace is not part of a well-formed one."""
    names: set[str] = set()
    remainder: list[str] = []
    last = 0
    for match in _PLACEHOLDER_RE.finditer(text):
        names.add(match.group(1))
        remainder.append(text[last : match.start()])
        last = match.end()
    remainder.append(text[last:])
    rest = "".join(remainder)
    if "{" in rest or "}" in rest:
        return None
    return names


def _clean_declared_placeholders(block: object) -> dict[str, set[str]]:
    """Normalise the `copyPlaceholders` block into {copy id -> required names}; drop bad shapes."""
    out: dict[str, set[str]] = {}
    if not isinstance(block, dict):
        return out
    for key, names in block.items():
        if not isinstance(key, str) or not _COPY_ID_RE.match(key):
            continue
        if not isinstance(names, list):
            continue
        declared = {
            n for n in names if isinstance(n, str) and _PLACEHOLDER_RE.fullmatch("{" + n + "}")
        }
        if len(declared) != len(names):
            continue
        out[key] = declared
    return out


def _clean_copy(block: object, declared: dict[str, set[str]] | None = None) -> dict:
    """Keep only well-formed (copy-id -> text) pairs, length-capped and placeholder-checked.

    A malformed placeholder, or one that no longer matches the set its default declares, is a 400:
    the rewording would either show a person template syntax or silently drop the value the sentence
    exists to carry, and neither is something to write into committed source and discover later."""
    out: dict = {}
    if not isinstance(block, dict):
        return out
    declarations = declared or {}
    for key, value in block.items():
        if not isinstance(key, str) or not _COPY_ID_RE.match(key):
            continue
        if not isinstance(value, str) or len(value) > _MAX_COPY_LEN:
            continue
        names = _copy_placeholders(value)
        if names is None:
            raise ApiError(
                400,
                f"Copy override for '{key}' has malformed placeholder syntax. "
                "Write each value as {name}.",
            )
        if len(names) > _MAX_PLACEHOLDERS:
            raise ApiError(400, f"Copy override for '{key}' has too many placeholders.")
        required = declarations.get(key)
        if required is not None:
            missing = sorted(required - names)
            unknown = sorted(names - required)
            if missing:
                raise ApiError(
                    400,
                    f"Copy override for '{key}' is missing the placeholder "
                    "{" + missing[0] + "}. Keep every placeholder the default declares.",
                )
            if unknown:
                raise ApiError(
                    400,
                    f"Copy override for '{key}' uses the unknown placeholder "
                    "{" + unknown[0] + "}. There is no value to put there.",
                )
        out[key] = value
    return out


# --- icon (SVG) sanitiser ---------------------------------------------------------------------
# The main injection surface of dev-mode v2: an owner-authored SVG body ships to everyone, so the
# backend is the authority. Only a whitelist of shape/path elements + geometry/stroke/fill/transform
# attributes survive; the tree is re-serialised from validated nodes, never echoed raw.

_SVG_ALLOWED_TAGS = {
    "path",
    "circle",
    "rect",
    "line",
    "polyline",
    "polygon",
    "ellipse",
    "g",
    "defs",
    "use",
}
_SVG_ALLOWED_ATTRS = {
    # identity / grouping
    "id",
    "class",
    # geometry
    "d",
    "cx",
    "cy",
    "r",
    "rx",
    "ry",
    "x",
    "y",
    "x1",
    "y1",
    "x2",
    "y2",
    "width",
    "height",
    "points",
    "pathlength",
    "transform",
    "transform-origin",
    # stroke
    "stroke",
    "stroke-width",
    "stroke-linecap",
    "stroke-linejoin",
    "stroke-dasharray",
    "stroke-dashoffset",
    "stroke-miterlimit",
    "stroke-opacity",
    "vector-effect",
    # fill / paint
    "fill",
    "fill-rule",
    "fill-opacity",
    "opacity",
    "color",
    "clip-rule",
    "clip-path",
}
# Cheap defence-in-depth pre-scan (the parse walk is authoritative): tokens that must never appear
# anywhere in the raw body. DOCTYPE / entities (`<!`), processing instructions (`<?`), remote/script
# vectors, numeric char entities (`&#`, billion-laughs vector).
_SVG_FORBIDDEN = (
    "<script",
    "</script",
    "<!",
    "<?",
    "foreignobject",
    "<style",
    "<iframe",
    "<image",
    "<audio",
    "<video",
    "javascript:",
    "vbscript:",
    "expression(",
    "data:",
    "&#",
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
    "width",
    "height",
    "min-width",
    "min-height",
    "max-width",
    "max-height",
    # spacing
    "margin",
    "margin-top",
    "margin-right",
    "margin-bottom",
    "margin-left",
    "padding",
    "padding-top",
    "padding-right",
    "padding-bottom",
    "padding-left",
    "gap",
    "row-gap",
    "column-gap",
    # layout (Phase F)
    "order",
    "grid-column",
    "grid-row",
    # appearance and typography
    "display",
    "visibility",
    "opacity",
    "color",
    "background-color",
    "border-color",
    "border-radius",
    "font-size",
    "font-weight",
    "line-height",
    "letter-spacing",
    "text-align",
    # container alignment
    "flex-direction",
    "flex-wrap",
    "justify-content",
    "align-items",
    "align-content",
}
_ELEM_FORBIDDEN = (";", "<", ">", "{", "}", "url(", "expression(", "/*", "*/", "\\", "@")
_LENGTH_KEYWORDS = {"auto", "none", "0", "min-content", "max-content", "fit-content"}
_LENGTH_RE = re.compile(r"^-?(?:\d+|\d*\.\d+)(?:px|rem|em|vh|vw|%)$")
_LENGTH_LIST_RE = re.compile(
    r"^-?(?:\d+|\d*\.\d+)(?:px|rem|em|vh|vw|%)"
    r"(?:\s+-?(?:\d+|\d*\.\d+)(?:px|rem|em|vh|vw|%)){0,3}$"
)
_ORDER_RE = re.compile(r"^-?\d{1,3}$")
# one grid line token: auto, a small integer, `span N`/`span name`, or a named grid line
_GRID_TOKEN_RE = re.compile(
    r"^(?:auto|-?\d{1,4}|span\s+(?:\d{1,4}|[a-zA-Z][\w-]*)|[a-zA-Z][\w-]*)$"
)
_COLOR_RE = re.compile(r"^(?:#[0-9a-fA-F]{3,8}|var\(--[a-z0-9-]+\)|transparent|currentColor)$")
_NUMBER_RE = re.compile(r"^(?:0|1|0?\.\d{1,3})$")
_LINE_HEIGHT_RE = re.compile(r"^(?:0|[1-9](?:\.\d{1,3})?|0?\.\d{1,3})$")
_FONT_WEIGHT_RE = re.compile(r"^(?:[1-9]00|normal|bold)$")
_APPEARANCE_ENUMS = {
    "display": {"block", "inline", "inline-block", "flex", "inline-flex", "grid", "none"},
    "visibility": {"visible", "hidden"},
    "text-align": {"left", "center", "right", "start", "end"},
    "flex-direction": {"row", "row-reverse", "column", "column-reverse"},
    "flex-wrap": {"nowrap", "wrap", "wrap-reverse"},
    "justify-content": {"start", "end", "center", "space-between", "space-around", "space-evenly"},
    "align-items": {"stretch", "start", "end", "flex-start", "flex-end", "center", "baseline"},
    "align-content": {
        "stretch",
        "start",
        "end",
        "flex-start",
        "flex-end",
        "center",
        "space-between",
        "space-around",
    },
}


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
    if prop in _APPEARANCE_ENUMS:
        return v in _APPEARANCE_ENUMS[prop]
    if prop in ("color", "background-color", "border-color"):
        return bool(_COLOR_RE.match(v))
    if prop == "opacity":
        return bool(_NUMBER_RE.match(v))
    if prop == "font-weight":
        return bool(_FONT_WEIGHT_RE.match(v))
    if prop == "border-radius":
        return v == "0" or bool(_LENGTH_RE.match(v)) or bool(_LENGTH_LIST_RE.match(v))
    if prop == "line-height":
        return low == "normal" or bool(_LENGTH_RE.match(v)) or bool(_LINE_HEIGHT_RE.match(v))
    if prop == "letter-spacing":
        return low == "normal" or v == "0" or bool(_LENGTH_RE.match(v))
    if prop == "font-size":
        return low in _LENGTH_KEYWORDS or bool(_LENGTH_RE.match(v))
    # size / spacing / gap: a safe length or a size keyword
    return low in _LENGTH_KEYWORDS or bool(_LENGTH_RE.match(v)) or bool(_LENGTH_LIST_RE.match(v))


def _clean_elements(block: object) -> dict:
    """Validate the elements block into {devId -> {cssProp -> value}}; a bad prop / value is a 400.

    Keys are shape-checked (a malformed dev id is dropped); every property is whitelisted and every
    value validated against its grammar, raising before anything is written."""
    out: dict = {}
    if not isinstance(block, dict):
        return out
    for key, props in block.items():
        if not _valid_element_id(key):
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


_CHOICE_PRESETS = {"dropdown", "segmented", "radio", "searchable"}


def _clean_behaviors(block: object) -> dict:
    """Validate source-backed semantic control substitutions."""
    out: dict = {}
    if not isinstance(block, dict):
        return out
    for key, entry in block.items():
        if not _valid_element_id(key) or not isinstance(entry, dict):
            continue
        clean: dict = {}
        preset = entry.get("preset")
        disabled = entry.get("disabled")
        if preset is not None:
            if not isinstance(preset, str) or preset not in _CHOICE_PRESETS:
                raise ApiError(400, f"Control preset '{preset}' is not supported.")
            clean["preset"] = preset
        if disabled is not None:
            if not isinstance(disabled, bool):
                raise ApiError(400, "Control disabled override must be true or false.")
            clean["disabled"] = disabled
        if clean:
            out[key] = clean
    return out


# --- the layout document (Design Mode Phase 4) --------------------------------------------------
# THE SERVER-SIDE CHECK IS STRUCTURAL, AND ONLY STRUCTURAL. `validateLayout` and `validateDocument`
# are frontend TypeScript, and the two things they need - the piece registry and the token palettes -
# live there too. Re-implementing either here would be a second set of design rules that drifts from
# the first, so this does what a writer of committed source has to do and nothing more: prove the
# payload is JSON-serialisable, prove it parses as a layout DOCUMENT (the node kinds, the required
# fields, the closed enums), and rebuild it from the validated fields so nothing a caller sends is
# echoed into a generated module. A document that is structurally sound but a bad DESIGN is written,
# because Design Mode warns and never blocks (decision 3) - the deviation list beside it is how that
# stays honest.

_LAYOUT_SLICES = ("workspace",)
_REGION_MODES = {"row", "column", "stack"}
_SCROLL_AXES = {"vertical", "horizontal", "both"}
_MAX_LAYOUT_ID_LEN = 256
_MAX_LAYOUT_NODES = 4000
_MAX_LAYOUT_DEPTH = 64
_MAX_LAYOUT_STRING_LEN = 512
_MAX_COMMITTED_ISSUES = 2000
# An issue code / copy id as the frontend writes them. A closed list would make a code added on the
# frontend a 400 here; the union in `layout/validatorIssues.ts` is the real authority, and an unknown
# code fails the publish typecheck rather than being silently dropped from the owner's known issues.
_ISSUE_CODE_RE = re.compile(r"^[a-z][a-z0-9-]*$")
_ISSUE_COPY_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_ISSUE_SEVERITIES = {"warning", "info"}
_ISSUE_SUBJECT_KINDS = {
    "document",
    "region",
    "slot",
    "placement",
    "piece",
    "action",
    "splitter",
    "token-pair",
}


def _layout_str(value: object, what: str, *, max_len: int = _MAX_LAYOUT_ID_LEN) -> str:
    if not isinstance(value, str) or not value or len(value) > max_len:
        raise ApiError(
            400, f"Layout {what} must be a non-empty string of at most {max_len} characters."
        )
    return value


def _layout_number(value: object, what: str) -> float | int:
    """A finite JSON number. `NaN` / `Infinity` parse from JSON in Python and would not re-parse."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ApiError(400, f"Layout {what} must be a number.")
    if value != value or value in (float("inf"), float("-inf")):
        raise ApiError(400, f"Layout {what} must be a finite number.")
    return value


def _axis_size_override(block: object, what: str) -> dict:
    if not isinstance(block, dict):
        raise ApiError(400, f"Layout {what} must be an object.")
    out: dict = {}
    for key in ("min", "preferred", "fraction"):
        if block.get(key) is not None:
            out[key] = _layout_number(block[key], f"{what}.{key}")
    return out


def _axis_size(block: object, what: str) -> dict:
    out = _axis_size_override(block, what)
    assert isinstance(block, dict)  # _axis_size_override raised otherwise
    if block.get("grow") is not None:
        if not isinstance(block["grow"], bool):
            raise ApiError(400, f"Layout {what}.grow must be true or false.")
        out["grow"] = block["grow"]
    when = block.get("when")
    if when is not None:
        if not isinstance(when, dict):
            raise ApiError(400, f"Layout {what}.when must be an object.")
        conditions: dict = {}
        for condition, sizes in when.items():
            name = _layout_str(condition, f"{what}.when key")
            conditions[name] = _axis_size_override(sizes, f"{what}.when.{name}")
        out["when"] = conditions
    return out


def _splitters(block: object, region_id: str) -> list:
    if not isinstance(block, list):
        raise ApiError(400, f"Layout region '{region_id}' splitters must be a list.")
    out: list = []
    for spec in block:
        if not isinstance(spec, dict):
            raise ApiError(
                400, f"Layout region '{region_id}' has a splitter that is not an object."
            )
        between = spec.get("between")
        if not isinstance(between, list) or len(between) != 2:
            raise ApiError(400, "A layout splitter must name exactly two slots.")
        clean = {
            "id": _layout_str(spec.get("id"), "splitter id"),
            "between": [
                _layout_str(between[0], "splitter slot"),
                _layout_str(between[1], "splitter slot"),
            ],
            "keyStep": _layout_number(spec.get("keyStep"), "splitter keyStep"),
            "lineThickness": _layout_number(spec.get("lineThickness"), "splitter lineThickness"),
            "grabWidth": _layout_number(spec.get("grabWidth"), "splitter grabWidth"),
        }
        if spec.get("persistenceKey") is not None:
            clean["persistenceKey"] = _layout_str(spec["persistenceKey"], "splitter persistenceKey")
        out.append(clean)
    return out


def _placement_params(block: object, placement_id: str) -> dict:
    if not isinstance(block, dict):
        raise ApiError(400, f"Layout placement '{placement_id}' params must be an object.")
    out: dict = {}
    for key, value in block.items():
        name = _layout_str(key, "placement param name")
        if isinstance(value, bool):
            out[name] = value
        elif isinstance(value, (int, float)):
            out[name] = _layout_number(value, f"placement param '{name}'")
        else:
            out[name] = _layout_str(
                value, f"placement param '{name}'", max_len=_MAX_LAYOUT_STRING_LEN
            )
    return out


def _layout_node(node: object, depth: int, counter: list[int]) -> dict:
    """One region or one placement, rebuilt from its validated fields."""
    counter[0] += 1
    if counter[0] > _MAX_LAYOUT_NODES:
        raise ApiError(400, "Layout document has too many nodes.")
    if depth > _MAX_LAYOUT_DEPTH:
        raise ApiError(400, "Layout document is nested too deeply.")
    if not isinstance(node, dict):
        raise ApiError(400, "A layout node must be an object.")
    kind = node.get("kind")
    if kind == "region":
        return _layout_region(node, depth, counter)
    if kind == "placement":
        return _layout_placement(node)
    raise ApiError(400, f"A layout node must be a region or a placement, not '{kind}'.")


def _layout_region(node: dict, depth: int, counter: list[int]) -> dict:
    region_id = _layout_str(node.get("id"), "region id")
    mode = node.get("mode")
    if mode not in _REGION_MODES:
        raise ApiError(
            400, f"Layout region '{region_id}' names an unknown arrangement mode '{mode}'."
        )
    slots = node.get("slots")
    if not isinstance(slots, list):
        raise ApiError(400, f"Layout region '{region_id}' must carry a list of slots.")
    clean: dict = {"kind": "region", "id": region_id, "mode": mode, "slots": []}
    if node.get("devId") is not None:
        clean["devId"] = _layout_str(node["devId"], "region devId")
    if node.get("size") is not None:
        clean["size"] = _axis_size(node["size"], f"region '{region_id}' size")
    if node.get("scroll") is not None:
        if node["scroll"] not in _SCROLL_AXES:
            raise ApiError(400, f"Layout region '{region_id}' names an unknown scroll axis.")
        clean["scroll"] = node["scroll"]
    if node.get("splitters") is not None:
        clean["splitters"] = _splitters(node["splitters"], region_id)
    for slot in slots:
        counter[0] += 1
        if counter[0] > _MAX_LAYOUT_NODES:
            raise ApiError(400, "Layout document has too many nodes.")
        if not isinstance(slot, dict) or slot.get("kind") != "slot":
            raise ApiError(400, f"Layout region '{region_id}' holds something that is not a slot.")
        slot_id = _layout_str(slot.get("id"), "slot id")
        content = slot.get("content")
        clean["slots"].append(
            {
                "kind": "slot",
                "id": slot_id,
                "content": None if content is None else _layout_node(content, depth + 1, counter),
            }
        )
    return clean


def _layout_placement(node: dict) -> dict:
    placement_id = _layout_str(node.get("id"), "placement id")
    clean: dict = {
        "kind": "placement",
        "id": placement_id,
        "piece": _layout_str(node.get("piece"), "placement piece"),
    }
    for flag in ("collapsed", "hidden"):
        if node.get(flag) is not None:
            if not isinstance(node[flag], bool):
                raise ApiError(
                    400, f"Layout placement '{placement_id}' {flag} must be true or false."
                )
            clean[flag] = node[flag]
    if node.get("size") is not None:
        clean["size"] = _axis_size(node["size"], f"placement '{placement_id}' size")
    if node.get("styleRoles") is not None:
        roles = node["styleRoles"]
        if not isinstance(roles, dict):
            raise ApiError(400, f"Layout placement '{placement_id}' styleRoles must be an object.")
        clean["styleRoles"] = {
            _layout_str(role, "style role name"): _layout_str(value, "style role value")
            for role, value in roles.items()
        }
    if node.get("params") is not None:
        clean["params"] = _placement_params(node["params"], placement_id)
    if node.get("visibility") is not None:
        visibility = node["visibility"]
        any_of = visibility.get("anyOf") if isinstance(visibility, dict) else None
        if not isinstance(any_of, list):
            raise ApiError(400, f"Layout placement '{placement_id}' visibility must carry anyOf.")
        clean["visibility"] = {"anyOf": [_layout_str(c, "visibility condition") for c in any_of]}
    if node.get("repeat") is not None:
        repeat = node["repeat"]
        over = repeat.get("over") if isinstance(repeat, dict) else None
        clean["repeat"] = {"over": _layout_str(over, "repeat collection")}
    return clean


def _clean_layout_document(document: object) -> dict:
    """A whole layout document, rebuilt field by field. `None` stays `None` (the shipped default)."""
    if not isinstance(document, dict):
        raise ApiError(400, "A committed layout must be an object.")
    version = document.get("schemaVersion")
    if isinstance(version, bool) or not isinstance(version, int):
        raise ApiError(400, "A committed layout must carry an integer schemaVersion.")
    root = document.get("root")
    if not isinstance(root, dict) or root.get("kind") != "region":
        raise ApiError(400, "A committed layout's root must be a region.")
    return {
        "schemaVersion": version,
        "id": _layout_str(document.get("id"), "document id"),
        "root": _layout_node(root, 0, [0]),
    }


def _clean_layout(block: object) -> dict:
    """The layout block into {slice -> document | None}. Every known slice key is always present."""
    out: dict = {slice_name: None for slice_name in _LAYOUT_SLICES}
    if block is None:
        return out
    if not isinstance(block, dict):
        raise ApiError(400, "The layout block must be an object keyed by surface.")
    for slice_name in _LAYOUT_SLICES:
        document = block.get(slice_name)
        if document is not None:
            out[slice_name] = _clean_layout_document(document)
    return out


def _issue_detail(block: object) -> dict:
    if not isinstance(block, dict):
        raise ApiError(400, "A committed issue's detail must be an object.")
    out: dict = {}
    for key, value in block.items():
        name = _layout_str(key, "issue detail name")
        if isinstance(value, bool):
            raise ApiError(400, f"Committed issue detail '{name}' must be a string or a number.")
        if isinstance(value, (int, float)):
            out[name] = _layout_number(value, f"issue detail '{name}'")
        else:
            out[name] = _layout_str(value, f"issue detail '{name}'", max_len=_MAX_LAYOUT_STRING_LEN)
    return out


def _issue_subject(block: object) -> dict:
    if not isinstance(block, dict):
        raise ApiError(400, "A committed issue must carry a subject object.")
    kind = block.get("kind")
    if kind not in _ISSUE_SUBJECT_KINDS:
        raise ApiError(400, f"A committed issue names an unknown subject kind '{kind}'.")
    out = {
        "kind": kind,
        "id": _layout_str(block.get("id"), "issue subject id", max_len=_MAX_LAYOUT_STRING_LEN),
    }
    if kind == "token-pair":
        for extra in ("theme", "ink", "surface"):
            out[extra] = _layout_str(block.get(extra), f"issue subject {extra}")
    return out


def _clean_committed_issues(block: object) -> dict:
    """The deviation list per slice, rebuilt from validated fields. Absent means an empty list."""
    out: dict = {slice_name: [] for slice_name in _LAYOUT_SLICES}
    if block is None:
        return out
    if not isinstance(block, dict):
        raise ApiError(400, "The committedIssues block must be an object keyed by surface.")
    for slice_name in _LAYOUT_SLICES:
        raw = block.get(slice_name)
        if raw is None:
            continue
        if not isinstance(raw, list):
            raise ApiError(400, f"Committed issues for '{slice_name}' must be a list.")
        if len(raw) > _MAX_COMMITTED_ISSUES:
            raise ApiError(400, f"Committed issues for '{slice_name}' are too many to write.")
        issues = []
        for issue in raw:
            if not isinstance(issue, dict):
                raise ApiError(400, "A committed issue must be an object.")
            code = issue.get("code")
            if not isinstance(code, str) or not _ISSUE_CODE_RE.match(code):
                raise ApiError(400, f"Committed issue code '{code}' is not a known shape.")
            severity = issue.get("severity")
            if severity not in _ISSUE_SEVERITIES:
                raise ApiError(
                    400, f"Committed issue severity '{severity}' is not warning or info."
                )
            copy_block = issue.get("copy")
            if not isinstance(copy_block, dict):
                raise ApiError(400, "A committed issue must carry its copy id and fallback.")
            copy_id = copy_block.get("id")
            if not isinstance(copy_id, str) or not _ISSUE_COPY_ID_RE.match(copy_id):
                raise ApiError(400, f"Committed issue copy id '{copy_id}' is not a known shape.")
            clean: dict = {
                "code": code,
                "severity": severity,
                "copy": {
                    "id": copy_id,
                    "fallback": _layout_str(
                        copy_block.get("fallback"), "issue fallback", max_len=_MAX_COPY_LEN
                    ),
                },
                "subject": _issue_subject(issue.get("subject")),
            }
            if issue.get("detail") is not None:
                clean["detail"] = _issue_detail(issue["detail"])
            if issue.get("path") is not None:
                if not isinstance(issue["path"], list):
                    raise ApiError(400, "A committed issue's path must be a list of node ids.")
                clean["path"] = [_layout_str(step, "issue path step") for step in issue["path"]]
            issues.append(clean)
        out[slice_name] = issues
    return out


def _clean_owner_authored_copy(block: object, written_copy: dict) -> list[str]:
    """Owner-typed copy ids, held to ids that actually carry an override in the same write.

    The letter-rule lint exempts these (plan 1.5), so the record is the one thing in this file that
    can make the gate quieter - which is why it is capped by construction rather than by size: an id
    with no committed rewording has nothing to exempt, and is dropped."""
    if block is None:
        return []
    if not isinstance(block, list):
        raise ApiError(400, "The ownerAuthoredCopy block must be a list of copy ids.")
    seen = {
        value
        for value in block
        if isinstance(value, str) and _COPY_ID_RE.match(value) and value in written_copy
    }
    return sorted(seen)


def _json_block(data) -> str:
    return json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True)


def _emit(path: Path, header: str, data) -> None:
    path.write_text(header + _json_block(data) + ";\n", encoding="utf-8")


def _emit_copy(path: Path, overrides: dict, owner_authored: list[str]) -> None:
    """copy.overrides.ts: the rewordings, then the owner-authored provenance record beside them."""
    path.write_text(
        _COPY_HEADER
        + _json_block(overrides)
        + ";\n\n"
        + _OWNER_AUTHORED_COPY_HEADER
        + _json_block(owner_authored)
        + ";\n",
        encoding="utf-8",
    )


def _emit_layout(path: Path, overrides: dict, issues: dict) -> None:
    """layout.overrides.ts: the committed documents, then the deviation list they were committed with."""
    path.write_text(
        _LAYOUT_HEADER
        + _json_block(overrides)
        + ";\n\n"
        + _LAYOUT_ISSUES_HEADER
        + _json_block(issues)
        + ";\n",
        encoding="utf-8",
    )


_DEV_SOURCE_PATHS = (
    "app/frontend/src/lib/token.overrides.ts",
    "app/frontend/src/lib/copy.overrides.ts",
    "app/frontend/src/lib/icon.overrides.ts",
    "app/frontend/src/lib/element.overrides.ts",
    "app/frontend/src/lib/behavior.overrides.ts",
    "app/frontend/src/lib/layout.overrides.ts",
)


def _app_repo(request: Request):
    repo = getattr(request.app.state.ctx, "app_repo", None)
    if repo is None:
        raise ApiError(409, "Dev Mode needs a managed Stockroom source checkout.")
    expected = _FRONTEND_SRC.parents[2].resolve()
    if repo.root.resolve() != expected:
        raise ApiError(409, "Dev Mode source and the managed application checkout do not match.")
    return repo


def _dev_status(request: Request) -> dict:
    repo = getattr(request.app.state.ctx, "app_repo", None)
    available = (
        _FRONTEND_SRC.is_dir()
        and repo is not None
        and repo.root.resolve() == _FRONTEND_SRC.parents[2].resolve()
    )
    if not available:
        return {
            "available": False,
            "branch": "",
            "revision": "",
            "dirty": [],
            "can_publish": False,
            "publish_blocker": "Dev Mode needs a managed Stockroom source checkout.",
        }
    dirty = [path.relative_to(repo.root).as_posix() for path in repo.dirty_paths()]
    allowed = set(_DEV_SOURCE_PATHS)
    owned = [path for path in dirty if path in allowed or path.startswith("app/frontend-dist/")]
    foreign = [path for path in dirty if path not in owned]
    branch = repo.current_branch()
    blocker = ""
    if branch != "main":
        blocker = "Switch the managed Stockroom checkout to main before publishing."
    elif foreign:
        blocker = "Unrelated source changes must be committed separately before publishing."
    elif not owned:
        blocker = "Save a Dev Mode change before publishing."
    return {
        "available": True,
        "branch": branch,
        "revision": repo.head(),
        "dirty": dirty,
        "can_publish": not blocker,
        "publish_blocker": blocker,
    }


def _run_frontend(repo, command: str) -> None:
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    if command == "install":
        arguments = [
            "npm.cmd",
            "--prefix",
            "app/frontend",
            "ci",
            "--no-audit",
            "--no-fund",
        ]
        timeout = 600
        label = "dependency install"
    else:
        arguments = ["npm.cmd", "--prefix", "app/frontend", "run", command]
        timeout = 300
        label = command
    proc = subprocess.run(
        arguments,
        cwd=repo.root,
        capture_output=True,
        text=True,
        timeout=timeout,
        creationflags=flags,
        check=False,
    )
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout).strip()[-4000:]
        raise ApiError(409, f"Frontend {label} failed. {detail}")


def _foreign_dev_paths(repo) -> list[str]:
    allowed = set(_DEV_SOURCE_PATHS)
    return [
        rel
        for path in repo.dirty_paths()
        if (rel := path.relative_to(repo.root).as_posix()) not in allowed
        and not rel.startswith("app/frontend-dist/")
    ]


def _publish(request: Request, body: object) -> dict:
    repo = _app_repo(request)
    if repo.current_branch() != "main":
        raise ApiError(409, "Dev Mode publishes only from main.")
    message = "Refine Stockroom interface"
    if isinstance(body, dict) and body.get("message") is not None:
        raw = body.get("message")
        if not isinstance(raw, str) or not raw.strip() or len(raw.strip()) > 120 or "\n" in raw:
            raise ApiError(
                400, "Commit message must be one non-empty line of at most 120 characters."
            )
        message = raw.strip()

    foreign = _foreign_dev_paths(repo)
    if foreign:
        raise ApiError(
            409, "Publish refused because unrelated files are changed: " + ", ".join(foreign[:8])
        )
    dirty = [path.relative_to(repo.root).as_posix() for path in repo.dirty_paths()]
    if not any(
        path in _DEV_SOURCE_PATHS or path.startswith("app/frontend-dist/") for path in dirty
    ):
        raise ApiError(409, "There is no saved Dev Mode change to publish.")

    ok, reason = repo.fetch()
    if not ok:
        raise ApiError(503, f"Could not refresh origin before publishing: {reason}")
    try:
        remote = repo.resolve_ref("origin/main")
    except GitError as exc:
        raise ApiError(409, f"Could not resolve origin/main: {exc}") from exc
    if remote != repo.head():
        raise ApiError(
            409, "Main changed on GitHub. Update Stockroom before publishing this design."
        )

    _run_frontend(repo, "install")
    _run_frontend(repo, "typecheck")
    _run_frontend(repo, "build")
    foreign = _foreign_dev_paths(repo)
    if foreign:
        raise ApiError(
            409, "Build changed files outside the Dev Mode boundary: " + ", ".join(foreign[:8])
        )
    paths = [repo.root / rel for rel in _DEV_SOURCE_PATHS]
    paths.append(repo.root / "app" / "frontend-dist")
    revision = repo.commit(message, paths)
    pushed = repo.push()
    if not pushed.ok:
        raise ApiError(
            503, f"The design was committed locally but GitHub push failed: {pushed.reason}"
        )
    return {
        "ok": True,
        "commit": revision,
        "branch": "main",
        "message": message,
        "checks": ["locked dependency install", "typecheck", "production build"],
        "pushed": True,
    }


def dev_router(require_token) -> APIRouter:
    r = APIRouter(prefix="/api/dev", dependencies=[Depends(require_token)])

    @r.post("/save")
    def save(request: Request, body: dict) -> dict:
        lib = _FRONTEND_SRC / "lib"
        if not lib.exists():
            # Hidden dev tool: with no source tree there is nothing to write, so refuse honestly
            # instead of pretending. This is the expected state inside a packaged build.
            raise ApiError(
                409,
                "Dev mode needs the frontend source tree; it is not available in a packaged build.",
            )
        tokens = body.get("tokens") if isinstance(body, dict) else None
        copy = body.get("copy") if isinstance(body, dict) else None
        icons = body.get("icons") if isinstance(body, dict) else None
        elements = body.get("elements") if isinstance(body, dict) else None
        behaviors = body.get("behaviors") if isinstance(body, dict) else None
        layout = body.get("layout") if isinstance(body, dict) else None
        committed_issues = body.get("committedIssues") if isinstance(body, dict) else None
        owner_authored = body.get("ownerAuthoredCopy") if isinstance(body, dict) else None

        # Validate every block up front: a malicious icon / CSS value, or a layout that is not a
        # document, raises here before any file is written, so a bad payload can never leave the six
        # override files half-updated.
        declared = _clean_declared_placeholders(
            body.get("copyPlaceholders") if isinstance(body, dict) else None
        )

        root = _clean_tokens((tokens or {}).get("root") if isinstance(tokens, dict) else None)
        light = _clean_tokens((tokens or {}).get("light") if isinstance(tokens, dict) else None)
        clean_copy = _clean_copy(copy, declared)
        clean_icons = _clean_icons(icons)
        clean_elements = _clean_elements(elements)
        clean_behaviors = _clean_behaviors(behaviors)
        clean_layout = _clean_layout(layout)
        clean_issues = _clean_committed_issues(committed_issues)
        clean_owner_authored = _clean_owner_authored_copy(owner_authored, clean_copy)

        _emit(lib / "token.overrides.ts", _TOKENS_HEADER, {"root": root, "light": light})
        _emit_copy(lib / "copy.overrides.ts", clean_copy, clean_owner_authored)
        _emit(lib / "icon.overrides.ts", _ICONS_HEADER, clean_icons)
        _emit(lib / "element.overrides.ts", _ELEMENTS_HEADER, clean_elements)
        _emit(lib / "behavior.overrides.ts", _BEHAVIORS_HEADER, clean_behaviors)
        _emit_layout(lib / "layout.overrides.ts", clean_layout, clean_issues)

        return {
            "ok": True,
            "written": list(_DEV_SOURCE_PATHS),
            "tokens": len(root) + len(light),
            "copy": len(clean_copy),
            "icons": len(clean_icons),
            "elements": len(clean_elements),
            "behaviors": len(clean_behaviors),
            # How many surfaces carry a committed arrangement, and how many known issues travel with
            # them - the deviation list is part of the commit, so the save reports it.
            "layouts": sum(1 for document in clean_layout.values() if document is not None),
            "committedIssues": sum(len(rows) for rows in clean_issues.values()),
            "ownerAuthoredCopy": len(clean_owner_authored),
        }

    @r.get("/status")
    def status(request: Request) -> dict:
        return _dev_status(request)

    @r.post("/publish")
    def publish(request: Request, body: dict) -> dict:
        return _publish(request, body)

    return r
