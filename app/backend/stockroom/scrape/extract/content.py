"""Readability-style main-content -> clean markdown (spec sections 3, 4 extract step).
Picks the densest content block (html.main_content), then walks it to markdown:
headings, paragraphs, lists, links (absolutized), code, and emphasis. Inline content and
loose text that sit directly inside a container are gathered into implicit paragraphs (so
a bare link or standalone text is never dropped); nested lists render as indented
sub-items and are emitted exactly once. Generic and never raises: a deep DOM or parse
failure falls back to the flat visible text, never an exception."""

from __future__ import annotations

from urllib.parse import urljoin

from stockroom.scrape.extract.html import main_content, parse, visible_text

_HEADINGS = {"h1": "# ", "h2": "## ", "h3": "### ",
             "h4": "#### ", "h5": "##### ", "h6": "###### "}

# Tags that START a new block; everything else (a, span, strong, em, code, br, text) is
# inline and is buffered into the surrounding implicit paragraph.
_BLOCK_TAGS = frozenset({
    "p", "div", "section", "article", "main", "header", "footer", "figure",
    "figcaption", "blockquote", "ul", "ol", "li", "pre", "table", "thead", "tbody",
    "tfoot", "tr", "td", "th", "dl", "dt", "dd", "hr", "nav", "aside", "form",
    "address", "details", "summary",
    "h1", "h2", "h3", "h4", "h5", "h6",
})
# A bound so a pathologically deep DOM cannot overflow the recursion limit (the whole
# page would then be silently lost); past this depth to_markdown falls back to flat text.
_MAX_DEPTH = 400


def _inline(node, base_url: str) -> str:
    tag = node.tag
    if tag == "-text":
        return node.text(deep=False) or ""
    if tag in _BLOCK_TAGS or tag in _HEADINGS:
        return ""  # block content is emitted by _block, never flattened into an inline run
    if tag == "a":
        href = (node.attributes.get("href") or "").strip()
        text = _children_inline(node, base_url).strip()
        if href and text:
            return f"[{text}]({urljoin(base_url, href)})"
        return text
    if tag in ("strong", "b"):
        return f"**{_children_inline(node, base_url).strip()}**"
    if tag in ("em", "i"):
        return f"*{_children_inline(node, base_url).strip()}*"
    if tag == "code":
        return f"`{(node.text() or '').strip()}`"
    if tag == "br":
        return "\n"
    return _children_inline(node, base_url)


def _children_inline(node, base_url: str) -> str:
    return "".join(_inline(c, base_url) for c in node.iter(include_text=True))


def _emit_list(node, base_url: str, out: list[str], ordered: bool, indent: int) -> None:
    """Emit each DIRECT-child <li> once (never node.css('li'), which grabbed nested items
    too), sequentially numbered for an <ol>, recursing nested lists as indented sub-items."""
    i = 0
    for li in node.iter(include_text=False):
        if li.tag != "li":
            continue
        i += 1
        text = " ".join(_children_inline(li, base_url).split())
        prefix = "  " * indent + (f"{i}. " if ordered else "- ")
        if text:
            out.append(prefix + text)
        for sub in li.iter(include_text=False):
            if sub.tag in ("ul", "ol"):
                _emit_list(sub, base_url, out, sub.tag == "ol", indent + 1)


def _block(node, base_url: str, out: list[str], depth: int = 0) -> None:
    if depth > _MAX_DEPTH:
        return
    tag = node.tag
    if tag in _HEADINGS:
        text = _children_inline(node, base_url).strip()
        if text:
            out.append(_HEADINGS[tag] + text)
        return
    if tag == "p":
        text = " ".join(_children_inline(node, base_url).split())
        if text:
            out.append(text)
        return
    if tag in ("ul", "ol"):
        _emit_list(node, base_url, out, tag == "ol", 0)
        return
    if tag == "pre":
        code = (node.text() or "").strip("\n")
        if code:
            out.append("```\n" + code + "\n```")
        return
    if tag == "blockquote":
        text = " ".join(_children_inline(node, base_url).split())
        if text:
            out.append("> " + text)
        return
    # A generic container: gather runs of inline/text children into implicit paragraphs
    # (so a bare link or loose text is not lost), and recurse into block children.
    buf: list[str] = []

    def _flush() -> None:
        if buf:
            text = " ".join("".join(buf).split())
            if text:
                out.append(text)
            buf.clear()

    for child in node.iter(include_text=True):
        ctag = child.tag
        if ctag in _BLOCK_TAGS or ctag in _HEADINGS:
            _flush()
            _block(child, base_url, out, depth + 1)
        else:
            buf.append(_inline(child, base_url))
    _flush()


def to_markdown(html: str, base_url: str = "") -> str:
    try:
        tree = parse(html)
        root = main_content(tree)
        if root is None:
            return ""
        out: list[str] = []
        _block(root, base_url, out, 0)
        if out:
            return "\n\n".join(part.strip() for part in out if part.strip())
        # An empty walk (edge/pathological DOM) still yields the flat visible text, so a
        # real page never collapses to nothing.
        return " ".join((root.text() or "").split())
    except Exception:  # noqa: BLE001 - content extraction never raises (spec section 3.1)
        try:
            return visible_text(html)
        except Exception:  # noqa: BLE001
            return ""
